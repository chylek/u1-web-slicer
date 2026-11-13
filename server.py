#!/usr/bin/env python3
"""U1 web slicer HTTP server: one global session (session.py) over REST + SSE, slicing with the Snapmaker Orca CLI
(normally inside a docker container, see config.py). No authentication: run it on a trusted network or behind an
authenticating reverse proxy. Run: python3 server.py -> http://<host>:3060. mcp_server.py talks to the same API."""

import json
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config
import printer
import session as sessmod

HERE = config.ROOT
ART = config.MODELS.resolve()
JOBS = config.DATA
PROGRESS = {"stage": "", "plate": 0, "of": 0, "t0": 0}  # live slice stage for /api/slice_progress
STAGES = [
    ("Slicing volumes", "Slicing layers"),
    ("Generating walls", "Walls"),
    ("Detecting solid", "Solid surfaces"),
    ("Preparing fill", "Infill"),
    ("Processing external", "Top/bottom surfaces"),
    ("Bridge over infill", "Bridges"),
    ("is_support_necessary", "Support check"),
    ("path conflicts", "Collision check"),
    ("Exporting G-code", "Writing G-code"),
]  # substrings of Orca's --debug 3 log
SLICE = threading.Lock()  # ponytail: one slice at a time (4 cores)
for d in (JOBS, JOBS / ".home", JOBS / ".dd", ART):
    d.mkdir(parents=True, exist_ok=True)
S = sessmod.Session(JOBS, ART)


def stats(gcode):
    out = {}
    typ = None
    tw = 0.0
    mm = 0.0
    with open(gcode, errors="ignore") as f:
        for line in f:
            if line.startswith(";TYPE:"):
                typ = line[6:].strip()
            elif line[:2] in ("G1", "G0") and typ == "Prime tower" and (m := re.search(r" E(-?[\d.]+)", line)):
                tw += float(m[1])  # relative E (M83)
            elif line.startswith("; filament used [mm] = "):
                mm = sum(float(x) for x in line.split("=", 1)[1].split(","))
            if line.startswith("; estimated printing time (normal mode) = "):
                out["time"] = line.split("=", 1)[1].strip()
            elif line.startswith("; total filament used [g] = "):
                out["grams"] = line.split("=", 1)[1].strip()
            elif line.startswith("; filament used [g] = "):
                out["grams_each"] = line.split("=", 1)[1].strip()
    g = sum(float(x) for x in out.get("grams_each", "").split(",") if x.strip())
    if mm and g and tw > 0:
        out["tower_g"] = round(tw * g / mm, 1)  # ponytail: net E in tower sections x g/mm; ignores start purge
    return out


def secs(t):
    """'1d 2h 3m 4s' -> seconds"""
    return sum(
        int(n) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u] for n, u in re.findall(r"(\d+)\s*([dhms])", t or "")
    )


def fmt_secs(s):
    d, s = divmod(int(s), 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return " ".join(f"{v}{u}" for v, u in ((d, "d"), (h, "h"), (m, "m"), (s, "s")) if v) or "0s"


def slice_plate(p):
    """one plate -> its own 3MF, CLI run, G-code (+ thumbnails); returns the plate result"""
    job = uuid.uuid4().hex[:12]
    d = JOBS / job
    d.mkdir()
    with S.lock:
        (d / "in.3mf").write_bytes(S.build(plate=p))
        n = S.nplates()
        (d / "name.txt").write_text((S.st["name"] or "project") + (f"_plate{p}" if n > 1 else ""))
    cj = config.in_container
    cmd = config.orca_command(
        [
            "--datadir",
            cj(JOBS / ".dd"),
            "--allow-newer-file",
            "--debug",
            "3",
            "--slice",
            "0",
            "--outputdir",
            cj(d),
            cj(d / "in.3mf"),
        ]
    )
    with SLICE:
        t = time.time()
        PROGRESS["t0"] = t
        po = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        threading.Timer(900, po.kill).start()
        lines = []
        for ln in po.stdout:
            lines.append(ln)
            for k, v in STAGES:
                if k in ln:
                    PROGRESS["stage"] = v
        po.wait()
        pr = subprocess.CompletedProcess(cmd, po.returncode, "".join(lines), "")
    res = {"plate": p, "seconds": round(time.time() - t, 1), "job": job}
    rj, g = d / "result.json", d / "plate_1.gcode"
    err = json.loads(rj.read_text()).get("error_string", "") if rj.exists() else ""
    err = "" if err.strip(". ") == "Success" else err
    if g.exists() and not err:
        try:  # the CLI can't render: add the plate thumbnails the U1 screen shows
            import thumbs

            with S.lock:
                tris = S.thumb_tris(p)
            png = thumbs.inject(g, tris)
            if png:
                (d / "thumb.png").write_bytes(png)
                res["thumb"] = f"/job/{job}/thumb.png"
        except Exception as e:
            print("thumbnail failed:", e, file=sys.stderr)
        res.update(ok=True, gcode=f"/job/{job}/plate_1.gcode", **stats(g))
        plates = json.loads(rj.read_text()).get("sliced_plates", []) if rj.exists() else []
        warn = [x.get("warning_message") for x in plates if x.get("warning_message")]
        if warn:
            res["warning"] = warn[0]  # e.g. Orca's support-necessity check ("... has floating cantilever ...")
    else:
        log = [ln for ln in pr.stdout.splitlines() + pr.stderr.splitlines() if "error" in ln.lower()]
        res.update(ok=False, error=(err or "slicing failed").strip() + (" | " + log[-1][-200:] if log else ""))
        if "conflict" in res["error"].lower():
            with S.lock:
                ov = S.overlaps()
            res["error"] = (
                (
                    f"Objects overlap: {', '.join(f'{a} + {b}' for a, b in ov)} — use Arrange. "
                    if ov
                    else "Toolpaths collide (often the wipe tower) — move the tower or use Arrange. "
                )
                + "("
                + res["error"]
                + ")"
            )
    return res, g


UPLOADS = ART / "uploads"
MODEL_EXT = (".stl", ".3mf")


def unzip_models(data, name):
    """zip -> STL/3MF files saved flat into <models>/uploads/<zip name>/ (the zip itself is never kept).
    Returns (saved paths, ignored [(entry, reason)]). Guards: no path traversal (names are flattened),
    max 2000 entries / 1 GB uncompressed."""
    import io
    import zipfile

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError(f"{name} is not a valid zip file") from e
    infos = [i for i in z.infolist() if not i.is_dir()]
    if len(infos) > 2000 or sum(i.file_size for i in infos) > 1 << 30:
        raise ValueError(f"{name} is too big (max 2000 files / 1 GB unpacked)")
    stem = re.sub(r"[^\w.() -]+", "_", Path(name).stem).strip(" .") or "upload"
    dest = UPLOADS / stem
    k = 1
    while dest.exists():
        k += 1
        dest = UPLOADS / f"{stem}-{k}"
    saved, ignored = [], []
    for i in infos:
        parts = [p for p in re.split(r"[\\/]", i.filename) if p not in ("", ".", "..")]
        if not parts:
            continue
        if parts[0] == "__MACOSX" or parts[-1].startswith("."):
            ignored.append((i.filename, "system file"))
            continue
        if Path(parts[-1]).suffix.lower() not in MODEL_EXT:
            ignored.append((i.filename, "unsupported type (only STL and 3MF)"))
            continue
        fn = re.sub(r"[^\w.() -]+", "_", "_".join(parts)).strip(" .")  # flat: a/b.stl -> a_b.stl
        dest.mkdir(parents=True, exist_ok=True)
        p = dest / fn
        p.write_bytes(z.read(i))
        saved.append(p)
    return saved, ignored


def add_files(files, name, plate):
    """add [(bytes, filename)] (zips are unpacked first) in one undo step -> API reply incl. what was ignored"""
    todo, ignored, folder, paths = [], [], None, {}
    for d, n in files:
        if n.lower().endswith(".zip"):
            saved, ig = unzip_models(d, n)
            ignored += ig
            if saved:
                folder = str(saved[0].parent.relative_to(ART))
            todo += [(p.read_bytes(), p.name) for p in saved]
            paths.update({p.name: p for p in saved})
        else:
            todo.append((d, n))
    if not todo:
        return {
            "ok": False,
            "error": f"no STL or 3MF in {name}",
            "ignored": [{"file": f, "why": w} for f, w in ignored],
        }
    try:
        ids = S.add(None, name, plate, files=todo)
    except ValueError:
        for p in paths.values():
            p.unlink(missing_ok=True)
        raise
    for n, _ in S.add_skipped:  # unreadable -> don't keep it in uploads/
        if n in paths:
            paths[n].unlink(missing_ok=True)
    ignored += S.add_skipped
    return {
        "ok": True,
        "ids": ids,
        "msg": S.add_msg,
        "added": len(ids),
        "folder": folder,
        "ignored": [{"file": f, "why": w} for f, w in ignored],
    }


def do_slice(only=None):
    """slice every plate that has objects (or just `only`); the result keeps one entry per plate + totals.
    Each plate is its own G-code: send and print them one after another."""
    with S.lock:
        todo = [p for p in range(1, S.nplates() + 1) if S.on_plate(p)] if only is None else [only]
    if not todo:
        return {"ok": False, "error": "nothing to slice — the plates are empty"}
    with S.lock:
        floating = [
            (o["name"], S.bbox(o)[4]) for p in todo for o in S.on_plate(p) if S.bbox(o)[4] > 0.05
        ]  # Orca refuses an empty first layer
    if floating:
        return {
            "ok": False,
            "error": "Floating above the bed: "
            + ", ".join(f"{n} ({z:.1f} mm)" for n, z in floating)
            + " — use Drop onto the bed",
        }
    plates = []
    for i, p in enumerate(todo):
        PROGRESS.update(stage="Starting", plate=i + 1, of=len(todo), t0=time.time())
        res, g = slice_plate(p)
        if res.get("ok"):
            S.after_slice(res, g, store=False)  # preview data + real wipe tower footprint
        plates.append(res)
    ok = [x for x in plates if x.get("ok")]
    first = ok[0] if ok else plates[0]
    total = {
        "ok": bool(ok),
        "partial": len(ok) < len(plates),
        "plates": plates,
        "job": first.get("job"),
        "gcode": first.get("gcode"),
        "thumb": first.get("thumb"),
        "time": fmt_secs(sum(secs(x.get("time")) for x in ok)),
        "grams": f"{sum(float(x.get('grams') or 0) for x in ok):.2f}",
        "grams_each": ",".join(
            f"{sum(float(((x.get('grams_each') or '').split(',') + [''] * 4)[i] or 0) for x in ok):.2f}"
            for i in range(4)
        ),
        "seconds": round(sum(x["seconds"] for x in plates), 1),
    }
    errs = [f"plate {x['plate']}: {x['error']}" if len(plates) > 1 else x["error"] for x in plates if not x.get("ok")]
    if errs:
        total["error"] = " · ".join(errs)
    warns = [
        f"plate {x['plate']}: {x['warning']}" if len(plates) > 1 else x["warning"] for x in plates if x.get("warning")
    ]
    if warns:
        total["warning"] = " · ".join(warns)
    PROGRESS["stage"] = ""  # idle: the UI ignores an empty stage
    S.after_slice(total, None)
    return total


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, body, ctype, extra=()):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, o, code=200):
        self._send(code, json.dumps(o).encode(), "application/json")

    def _file(self, p, ctype=None, name=None):
        if not p.is_file():
            return self._json({"error": "not found"}, 404)
        ct = ctype or {
            ".html": "text/html",
            ".js": "text/javascript",
            ".css": "text/css",
            ".json": "application/json",
            ".webmanifest": "application/manifest+json",
            ".png": "image/png",
        }.get(p.suffix, "application/octet-stream")
        self._send(
            200,
            p.read_bytes(),
            ct,
            [("Content-Disposition", f'attachment; filename="{name}"')] if name else [("Cache-Control", "no-cache")],
        )

    def _art(self, rel, exts):
        p = (ART / rel).resolve()
        if ART not in p.parents or p.suffix.lower() not in exts:
            raise ValueError("path must be a file under the models folder with extension " + "/".join(exts))
        return p

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/slice_progress":
                return self._json(dict(PROGRESS, elapsed=round(time.time() - PROGRESS["t0"], 1)))
            if u.path == "/api/printer":
                try:
                    return self._json(printer.status())
                except OSError as e:
                    return self._json({"error": f"printer {printer.HOST} unreachable: {e}"}, 502)
            if u.path == "/api/printer/camera.jpg":  # stock camera needs a keepalive; wake at most every 8 s
                try:
                    if time.time() - printer._last_wake > 8:
                        printer._last_wake = time.time()
                        printer.camera_wake()
                    return self._send(200, printer.camera_frame(), "image/jpeg", [("Cache-Control", "no-store")])
                except (OSError, RuntimeError) as e:
                    return self._json({"error": str(e)}, 502)
            if u.path == "/api/colours/plan":  # model colours -> printer (or current) palette, ranked options
                src = q.get("source", ["printer"])[0]
                phys = (
                    [f["colour"] for f in printer.status()["filaments"]]
                    if src == "printer"
                    else [f["colour"] for f in S.st["filaments"]]
                )
                with S.lock:
                    return self._json({"physical": phys, "targets": S.colour_plan(phys)})
            if u.path == "/api/colours/used":  # filament ids used by one object (parts + paint)
                with S.lock:
                    return self._json(sorted(S.used_ids([S.obj(q["id"][0])])))
            if u.path == "/api/colours/palette":  # quick-add mixable colours from the current filaments
                import colormix

                return self._json(colormix.palette([f["colour"] for f in S.st["filaments"]]))
            if u.path == "/api/profiles":
                with S.lock:
                    return self._json(S.profiles())
            if u.path == "/api/filaments":  # built-in + user filament presets {name: {key: [values]}}
                u_ = set(S.fil_presets()) - set(sessmod.FILAMENTS)
                return self._json({n: dict(v, user=n in u_) for n, v in S.fil_presets().items()})
            if u.path == "/api/summary":
                with S.lock:
                    return self._json(S.summary())
            if u.path == "/api/state":
                return self._json(S.state())
            if u.path.startswith("/api/paint/"):
                with S.lock:
                    return self._json(S.paint(u.path.rsplit("/", 1)[1]))
            if u.path == "/api/history":
                with S.lock:
                    return self._json(S.history(int(q.get("n", ["30"])[0])))
            if u.path.startswith("/api/geo/"):
                return self._json(S.geo(u.path.rsplit("/", 1)[1]))
            if u.path == "/api/events":
                return self._events()
            if u.path == "/api/files":
                fs = sorted(
                    [p for p in [*ART.glob("*/*"), *UPLOADS.glob("*/*")] if p.suffix.lower() in MODEL_EXT],
                    key=lambda p: -p.stat().st_mtime,
                )
                return self._json([str(p.relative_to(ART)) for p in fs])
            m = re.fullmatch(r"/job/([0-9a-f]{12})/preview\.(json|bin)", u.path)
            if m:
                d = JOBS / m[1]
                if m[2] == "json":
                    return self._file(d / "preview.json")
                return self._send(
                    200, (d / "preview.bin.gz").read_bytes(), "application/octet-stream", [("Content-Encoding", "gzip")]
                )
            m = re.fullmatch(r"/job/([0-9a-f]{12})/thumb\.png", u.path)
            if m:
                return self._file(JOBS / m[1] / "thumb.png", "image/png")
            m = re.fullmatch(r"/job/([0-9a-f]{12})/plate_1\.gcode", u.path)
            if m:
                return self._file(
                    JOBS / m[1] / "plate_1.gcode", "text/plain", f"{(JOBS / m[1] / 'name.txt').read_text()}.gcode"
                )
            s = (HERE / "static" / (u.path.lstrip("/") or "index.html")).resolve()
            if HERE / "static" not in s.parents:
                return self._json({"error": "not found"}, 404)
            self._file(s)
        except (KeyError, ValueError, FileNotFoundError) as e:
            self._json({"error": str(e)}, 400)

    def _events(self):
        q_ = queue.Queue()
        S.listeners.append(q_.put)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.wfile.write(f"event: state\ndata: {json.dumps(S.state())}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    st = q_.get(timeout=15)
                    self.wfile.write(f"event: state\ndata: {json.dumps(st)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            if q_.put in S.listeners:
                S.listeners.remove(q_.put)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/upload":  # binary 3MF -> replaces the session
                S.open(body, q.get("name", ["upload.3mf"])[0])
                return self._json({"ok": True})
            if u.path == "/api/add":  # binary STL/3MF -> added to the session
                n = q.get("name", ["part.stl"])[0]
                return self._json(add_files([(body, n)], n, q.get("plate", [1])[0]))
            r = json.loads(body or b"{}")
            if u.path == "/api/open":
                p = self._art(r["path"], (".3mf",))
                S.open(p.read_bytes(), p.name)
                return self._json({"ok": True})
            if u.path == "/api/add_path":
                p = Path(r["path"]) if Path(r["path"]).is_absolute() else self._art(r["path"], (".3mf", ".stl", ".zip"))
                res = add_files([(p.read_bytes(), p.name)], p.name, r.get("plate"))
                if p.suffix.lower() == ".zip" and res.get("folder") and ART in p.resolve().parents:
                    p.unlink()  # extracted -> the zip is no longer needed
                return self._json(res)
            if u.path == "/api/new":
                S.new()
                return self._json({"ok": True})
            if u.path == "/api/printer/sync":  # RFID colours from the U1 -> project filaments
                fs = printer.status()["filaments"]
                return self._json(
                    S.op({"op": "set_filaments", "filaments": [{"colour": f["colour"], "type": f["type"]} for f in fs]})
                )
            if u.path == "/api/printer/send":  # last sliced G-code -> printer; start only on explicit request
                res = S.st.get("result") or {}
                pls = res.get("plates") or ([dict(res, plate=1)] if res.get("ok") else [])
                want = int(r.get("plate") or (pls[0]["plate"] if pls else 1))
                pr_ = next((x for x in pls if x.get("plate") == want), None)
                if not pr_ or not pr_.get("ok"):
                    raise ValueError("slice first" if not pls else f"plate {r.get('plate')} has no G-code")
                if res.get("stale") and not r.get("stale_ok"):
                    return self._json(
                        {
                            "stale": True,
                            "error": "the plate changed since slicing — slice again (or confirm sending the old "
                            "G-code)",
                        }
                    )
                g = JOBS / pr_["job"] / "plate_1.gcode"
                name = (
                    re.sub(r"[^\w.() -]+", "_", (r.get("name") or S.st["name"] or "u1web").strip()).strip(" .")
                    or "u1web"
                )
                name = name if name.lower().endswith(".gcode") else name + ".gcode"
                try:
                    if not r.get("overwrite") and printer.exists(name):
                        return self._json({"exists": True, "file": name})
                    return self._json(printer.upload(g, name, start=bool(r.get("start"))))
                except OSError as e:
                    return self._json({"error": f"printer {printer.HOST} unreachable: {e}"}, 502)
            if u.path == "/api/profiles/save":
                return self._json(S.profile_save(r.get("kind", "global"), r.get("name"), r.get("id"), r.get("part")))
            if u.path == "/api/filaments/save":
                return self._json(S.filament_save(r["filament"], r.get("name")))
            if u.path == "/api/filaments/delete":
                return self._json(S.filament_delete(r["name"]))
            if u.path == "/api/profiles/delete":
                return self._json(S.profile_delete(r.get("kind", "global"), r["name"]))
            if u.path == "/api/undo":
                return self._json(S.undo())
            if u.path == "/api/redo":
                return self._json(S.redo())
            if u.path == "/api/op":
                return self._json(S.op(r))
            if u.path == "/api/slice":
                return self._json(do_slice(r.get("plate")))
            if u.path == "/api/save":
                return self._json({"ok": True, "path": S.save(r.get("name"))})
            self._json({"error": "not found"}, 404)
        except (KeyError, ValueError, FileNotFoundError) as e:
            self._json({"error": str(e).strip("'\"")}, 400)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"u1web on http://0.0.0.0:{config.PORT}  data={JOBS}  models={ART}", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", config.PORT), H).serve_forever()
