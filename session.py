"""Single global slicing session (the server is the source of truth).
Used by server.py (REST + SSE) and, via HTTP, by mcp_server.py.
Object = {id, gid, name, m:[12] (3MF row-vector matrix), ext:[per part], cfg:{per-object overrides}}."""

import json
import math
import pickle
import re
import threading
from pathlib import Path

import colormix
import gcodeprev
import paintree
import threemf

GAP = 6


def parse_mix_row(row):
    """Orca mixed_filament_definitions row -> normalized (ids, weights). Pairs: 'a,b,en,custom,pctB'; 3+ components
    carry 'g<ids>' (compact digits or '/'-separated) and 'w<w1/w2/..>' tokens
    (MixedFilament.cpp parse_row_definition)."""
    t = row.split(",")
    a, b = int(t[0]), int(t[1])
    pct = int(t[4] if len(t) > 4 else t[3])
    g = next((x[1:] for x in t[5:] if x[:1] in "gG" and len(x) > 1), "")
    w = next((x[1:] for x in t[5:] if x[:1] in "wW" and len(x) > 1), "")
    ids = [int(x) for x in (g.strip("/").split("/") if "/" in g else list(g))] if g else []
    if len(ids) >= 3:
        ws = [int(x) for x in w.split("/")] if w else [1] * len(ids)
        return colormix.norm(ids, ws)
    return colormix.norm((a, b), (100 - pct, pct))


def encode_mix(ids, weights):
    ids, ws = colormix.norm(ids, weights)
    if len(ids) == 2:
        return f"{ids[0]},{ids[1]},1,1,{ws[1]}"
    pct = round(100 * ws[1] / (ws[0] + ws[1]))
    g = "".join(map(str, ids)) if max(ids) < 10 else "/".join(map(str, ids))
    return f"{ids[0]},{ids[1]},1,1,{pct},0,g{g},w{'/'.join(map(str, ws))},m0"  # m0 = layer cycle (Orca's choice for 3+)


def opt_recipe(o):
    """mix option (ids/weights or a/b/pct) -> normalized recipe"""
    if o.get("ids"):
        return colormix.norm(o["ids"], o["weights"])
    return colormix.norm((int(o["a"]), int(o["b"])), (100 - int(o.get("pct", 50)), int(o.get("pct", 50))))


class GeoStore(dict):
    """Immutable geometries by gid, lazily loaded. A gid = shape (verts/tris/types, stored once per shape id) + per-gid
    names and paint. Paint strokes / renames make a new gid that shares the shape, so undo snapshots stay cheap."""

    def __init__(self, d: Path):
        super().__init__()
        self.d = d
        d.mkdir(parents=True, exist_ok=True)
        self.shapes = {}

    def __missing__(self, gid):
        g = pickle.loads((self.d / f"g-{gid}.pkl").read_bytes())
        sid = g["shape"]
        if sid not in self.shapes:
            self.shapes[sid] = pickle.loads((self.d / f"s-{sid}.pkl").read_bytes())
        parts = [dict(sp, name=n, paint=pa) for sp, n, pa in zip(self.shapes[sid], g["names"], g["paint"])]
        geo = {"name": g["name"], "shape": sid, "parts": parts}
        self[gid] = geo
        return geo

    def persist(self, gid):
        import uuid

        geo = self[gid]
        if not geo.get("shape"):
            geo["shape"] = uuid.uuid4().hex[:10]
        sid = geo["shape"]
        sp = self.d / f"s-{sid}.pkl"
        if not sp.exists():
            sp.write_bytes(
                pickle.dumps(
                    [
                        {"verts": p["verts"], "tris": p["tris"], "type": p.get("type", "normal_part")}
                        for p in geo["parts"]
                    ]
                )
            )
        (self.d / f"g-{gid}.pkl").write_bytes(
            pickle.dumps(
                {
                    "name": geo["name"],
                    "shape": sid,
                    "names": [p["name"] for p in geo["parts"]],
                    "paint": [p.get("paint") for p in geo["parts"]],
                }
            )
        )


PRESETS = json.loads(
    (Path(__file__).parent / "static/presets.json").read_text()
)  # Orca U1 0.4 process presets (gen_presets.py)
NO_PROFILE = {
    k for k in threemf.SETTINGS if k.endswith("_filament")
}  # filament/colour assignments stay with the project


FILAMENTS = json.loads((Path(__file__).parent / "static/filaments.json").read_text())  # gen_filaments.py
FLOW_KEYS = {k for v in FILAMENTS.values() for k, x in v.items() if len(x) > 1} | {"filament_flow_support"}


def filament_preset(cfg, i, preset):  # preset = name of a built-in or a {key: [values]} dict
    """cfg with Orca filament preset `preset` in slot i (0-based). Flow-variant keys are stored interleaved:
    filament i owns filament_flow_step_size[i] entries starting at the sum of the preceding sizes."""
    p = FILAMENTS[preset] if isinstance(preset, str) else preset
    cfg = dict(cfg)
    n = len(cfg["filament_type"])
    step = [int(x) for x in cfg.get("filament_flow_step_size") or ["1"] * n]
    a, b, L = sum(step[:i]), sum(step[: i + 1]), len(p.get("filament_flow_support", ["standard"]))
    pad = lambda v: (list(v) + [v[-1]] * L)[:L]
    for k, v in cfg.items():
        if not isinstance(v, list):
            continue
        if k in FLOW_KEYS and len(v) == sum(step):
            cfg[k] = v[:a] + pad(p.get(k) or v[a:b]) + v[b:]
        elif k in p and len(v) == n:
            cfg[k] = v[:i] + [p[k][0]] + v[i + 1 :]
    step[i] = L
    cfg["filament_flow_step_size"] = [str(x) for x in step]
    return cfg


FIL_KEYS = {k for v in FILAMENTS.values() for k in v} - {
    "filament_settings_id",
    "filament_ids",
    "filament_flow_support",
}


def set_filament_values(cfg, i, vals):
    """slot i (0-based): every flow variant of a key gets the same value"""
    cfg = dict(cfg)
    n = len(cfg["filament_type"])
    step = [int(x) for x in cfg.get("filament_flow_step_size") or ["1"] * n]
    a, b = sum(step[:i]), sum(step[: i + 1])
    for k, v in vals.items():
        if k not in FIL_KEYS or not isinstance(cfg.get(k), list):
            raise ValueError(f"'{k}' is not a filament setting")
        v = str(v)
        old = cfg[k]
        cfg[k] = (
            old[:a] + [v] * (b - a) + old[b:]
            if k in FLOW_KEYS and len(old) == sum(step)
            else old[:i] + [v] + old[i + 1 :]
        )
    return cfg


def slot_values(cfg, i):
    """slot i as a preset dict (inverse of filament_preset)"""
    n = len(cfg["filament_type"])
    step = [int(x) for x in cfg.get("filament_flow_step_size") or ["1"] * n]
    a, b = sum(step[:i]), sum(step[: i + 1])
    out = {}
    for k in FIL_KEYS | {"filament_flow_support", "filament_ids"}:
        v = cfg.get(k)
        if isinstance(v, list):
            out[k] = v[a:b] if k in FLOW_KEYS and len(v) == sum(step) else [v[i]]
    return out


def match_preset(type_, vendor="", sub=""):
    """best U1 preset for what the printer reports (type PLA/TPU..., vendor, sub_type) or None"""
    c = [
        (2 * (v["filament_vendor"][0] == vendor) + bool(sub and sub.lower() in n.lower()), -len(n), n)
        for n, v in FILAMENTS.items()
        if v["filament_type"][0] == type_
    ]
    return max(c)[2] if c else None


class Session:
    HISTORY = 2000  # undo depth (snapshots are a few KB; geometry is shared)

    def __init__(self, jobs: Path, art: Path):
        import sqlite3

        self.jobs, self.art = jobs, art
        self.dir = jobs / "session"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.listeners = []  # callables(state) for SSE
        self.rev, self.st, self.cfg = 0, None, None
        self.geos = GeoStore(self.dir / "blobs")
        self.dirty = set()
        self._vcache = {}
        self.db = sqlite3.connect(self.dir / "history.db", check_same_thread=False)
        self.db.executescript(
            "create table if not exists hist(id integer primary key, state text, label text, ts real);"
            "create table if not exists meta(k text primary key, v text);"
        )
        try:
            self.st = json.loads((self.dir / "state.json").read_text())
            self.rev = self.st.get("rev", 0)
            if (self.dir / "geos.pkl").exists():  # migrate the pre-history format (one pickle of everything)
                old, self.cfg = pickle.loads((self.dir / "geos.pkl").read_bytes())
                for gid, g in old.items():
                    self.geos[gid] = g
                    self.geos.persist(gid)
                self.st["cfg_id"] = self._put_cfg(self.cfg)
                (self.dir / "geos.pkl").rename(self.dir / "geos.pkl.migrated")
                self._commit(label="migrated")
            self.cfg = self._get_cfg(self.st["cfg_id"])
            self._gc()
        except Exception:
            self.load_scene(threemf.new_scene(), {}, "new")

    # ---------- persistence / history / broadcast
    def _put_cfg(self, cfg):
        import hashlib

        b = json.dumps(cfg, sort_keys=True).encode()
        cid = hashlib.sha1(b).hexdigest()[:12]
        p = self.geos.d / f"c-{cid}.json"
        if not p.exists():
            p.write_bytes(b)
        return cid

    def _get_cfg(self, cid):
        return json.loads((self.geos.d / f"c-{cid}.json").read_text())

    def _cursor(self):
        r = self.db.execute("select v from meta where k='cursor'").fetchone()
        return int(r[0]) if r else 0

    def _commit(self, geo_changed=False, label=None, record=True):
        import time

        label = label or getattr(self, "_label", None)
        for gid in list(self.dirty):
            if gid in self.geos:
                self.geos.persist(gid)
        self.dirty.clear()
        if record and self.st.get("result") and not str(label or "").startswith("open "):
            self.st["result"] = dict(self.st["result"], stale=True)  # the plate changed since slicing
        self.rev += 1
        self.st["rev"] = self.rev
        (self.dir / "state.json").write_text(json.dumps(self.st))
        if record:  # new edit after an undo drops the redo branch
            cur = self._cursor()
            self.db.execute("delete from hist where id > ?", (cur,))
            snap = dict(
                self.st, result=None, objects=[{k: v for k, v in o.items() if k != "lock"} for o in self.st["objects"]]
            )  # locks aren't undoable
            new = self.db.execute(
                "insert into hist(state, label, ts) values (?, ?, ?)", (json.dumps(snap), label or "edit", time.time())
            ).lastrowid
            self.db.execute("insert or replace into meta values ('cursor', ?)", (str(new),))
            self.db.execute("delete from hist where id <= ?", (new - self.HISTORY,))
            self.db.commit()
        for f in list(self.listeners):
            try:
                f(self.state())
            except Exception:
                self.listeners.remove(f)

    def _step(self, direction):
        cur = self._cursor()
        q = (
            "select id, state, label from hist where id < ? order by id desc limit 1"
            if direction < 0
            else "select id, state, label from hist where id > ? order by id limit 1"
        )
        row = self.db.execute(q, (cur,)).fetchone()
        if not row:
            raise ValueError("nothing to " + ("undo" if direction < 0 else "redo"))
        undone = self.db.execute("select label from hist where id = ?", (cur,)).fetchone()
        st = json.loads(row[1])
        res = self.st.get("result")
        st["result"] = dict(res, stale=True) if res else None  # undo/redo changes the plate too
        locks = {o["id"]: o["lock"] for o in self.st["objects"] if o.get("lock")}
        for o in st["objects"]:
            if o["id"] in locks:
                o["lock"] = locks[o["id"]]
        if st.get("cfg_id") != self.st.get("cfg_id"):
            self.cfg = self._get_cfg(st["cfg_id"])
        self.st = st
        self._vcache = {}
        self.db.execute("insert or replace into meta values ('cursor', ?)", (str(row[0]),))
        self.db.commit()
        self._commit(record=False)
        return {
            "ok": True,
            "rev": self.rev,
            "msg": ("undo: " + (undone[0] if undone else "")) if direction < 0 else ("redo: " + row[2]),
        }

    def undo(self):
        with self.lock:
            return self._step(-1)

    def redo(self):
        with self.lock:
            return self._step(+1)

    def history(self, n=20):
        cur = self._cursor()
        return [
            {"id": i, "label": lab, "current": i == cur, "undone": i > cur}
            for i, lab in self.db.execute("select id, label from hist order by id desc limit ?", (n,)).fetchall()
        ]

    def _gc(self):
        """drop blobs no snapshot references any more"""
        gids, cids = set(), set()
        for (st,) in self.db.execute("select state from hist"):
            st = json.loads(st)
            cids.add(st.get("cfg_id"))
            gids |= {o["gid"] for o in st["objects"]}
        gids |= {o["gid"] for o in self.st["objects"]}
        cids.add(self.st.get("cfg_id"))
        shapes = set()
        for p in self.geos.d.glob("g-*.pkl"):
            gid = p.stem[2:]
            if gid in gids:
                shapes.add(pickle.loads(p.read_bytes())["shape"])
            else:
                p.unlink()
        for p in self.geos.d.glob("s-*.pkl"):
            if p.stem[2:] not in shapes:
                p.unlink()
        for p in self.geos.d.glob("c-*.json"):
            if p.stem[2:] not in cids:
                p.unlink()

    def state(self):
        s = dict(self.st)
        s["objects"] = [
            dict(
                o,
                parts=[{"name": p["name"], "type": p.get("type", "normal_part")} for p in self.geos[o["gid"]]["parts"]],
                pcfg=self.pcfg(o),
                shape=self.geos[o["gid"]].get("shape"),
            )
            for o in self.st["objects"]
        ]
        s["filaments"] = self.fil_info()
        s["mix_colours"] = self.mix_colours()
        cur = self._cursor()
        s["can_undo"] = bool(self.db.execute("select 1 from hist where id < ?", (cur,)).fetchone())
        s["can_redo"] = bool(self.db.execute("select 1 from hist where id > ?", (cur,)).fetchone())
        return s

    def geo(self, gid):
        g = self.geos[gid]
        return {
            "gid": gid,
            "shape": g.get("shape"),
            "parts": [
                {
                    "name": p["name"],
                    "type": p.get("type", "normal_part"),
                    "pos": threemf.pos_b64(p["verts"], p["tris"]),
                    "paint": self._paint_b64(p),
                }
                for p in g["parts"]
            ],
        }

    def _tree_paint(self, o, parts, classify, st, detail, normal_ok=None):
        """apply an adaptive (Orca TriangleSelector-style) paint to parts of o; classify works in object-local "
        "coordinates"""
        g = self.own_geo(o)
        total = 0
        for i in parts:
            p = g["parts"][i]
            V = p["verts"]
            paint_ = list(p["paint"]) if p.get("paint") else [None] * len(p["tris"])
            changed = 0
            for t, (a, b, c) in enumerate(p["tris"]):
                v = (V[a], V[b], V[c])
                if normal_ok and not normal_ok(v):
                    continue
                if classify(v) == 0:
                    continue
                old = paint_[t]
                new = paintree.encode(paintree.paint(paintree.decode(old), v, classify, st, detail))
                if new != old:
                    paint_[t] = new
                    changed += 1
            p["paint"] = paint_ if any(paint_) else None
            total += changed
        return total

    def paint(self, gid):
        return {"gid": gid, "parts": [self._paint_b64(p) for p in self.geos[gid]["parts"]]}

    @staticmethod
    def _paint_b64(p):
        """{s: state per base triangle (255 = split, drawn by its leaves), lp: leaf triangles (float32 xyz, "
        "local), ls: leaf states}"""
        import base64
        import struct

        if not p.get("paint"):
            return None
        st, lp, ls = bytearray(), [], bytearray()
        for t, code in enumerate(p["paint"]):
            if not code:
                st.append(0)
                continue
            nd = paintree.decode(code)
            s = paintree.state_of(nd)
            st.append(min(s, 255))
            if s == 255:
                v = tuple(p["verts"][i] for i in p["tris"][t])
                for tri, ls_ in paintree.leaves(nd, v):
                    lp += [c for q in tri for c in q]
                    ls.append(min(ls_, 254))
        e = lambda b: base64.b64encode(bytes(b)).decode()
        return {"s": e(st), "lp": e(struct.pack(f"<{len(lp)}f", *lp)), "ls": e(ls)}

    def _put_geo(self, gid, geo):
        geo.setdefault("shape", None)
        self.geos[gid] = geo
        self.dirty.add(gid)

    # ---------- loading
    def load_scene(self, ui, geos, name):
        import uuid

        tag = uuid.uuid4().hex[:6]  # gids must be unique across loads: browsers cache geometry by gid
        for g, v in geos.items():
            self._put_geo(f"{tag}{g}", v)
        for o in ui["objects"]:
            o["gid"] = f"{tag}{o['gid']}"
        self.cfg = ui.pop("cfg")
        self._vcache = {}
        n = 0
        objs = []
        for o in ui["objects"]:
            n += 1
            objs.append(
                {
                    "id": f"o{n}",
                    "gid": o["gid"],
                    "name": o["name"],
                    "m": o["m"],
                    "ext": [p["extruder"] for p in o["parts"]],
                    "cfg": o.get("cfg", {}),
                    "pcfg": o.get("pcfg") or [{} for _ in o["parts"]],
                    "plate": o.get("plate", 1),
                }
            )
        w = ui["wipe"]
        w["fp"] = [-5, w["w"] * 1.55 + 4, -5, w["w"] * 1.55 + 4]  # real tower ~1.55x nominal width + brim
        self.st = {
            "rev": self.rev,
            "name": Path(name).stem if name != "new" else "",
            "bed": ui["bed"],
            "filaments": ui["filaments"],
            "wipe": w,
            "mix": ui.get("mix", ""),
            "settings": ui["settings"],
            "overrides": {},
            "objects": objs,
            "next": n,
            "result": None,
            "plates": max([ui.get("plates", 1)] + [o["plate"] for o in objs]),
            "cfg_id": self._put_cfg(self.cfg),
        }
        self.fix_wipe()
        self._commit(True, label=f"open {name}")

    def open(self, data, name):
        with self.lock:
            ui, geos = threemf.parse(data)
            self.load_scene(ui, geos, name)

    def new(self):
        with self.lock:
            self.load_scene(threemf.new_scene(), {}, "new")

    def add(self, data, name, plate=None, files=None):
        """STL or 3MF (or `files` = [(data, name), ...] in one undo step) -> new objects, then arrange.
        A file that fails to parse is skipped and listed in self.add_skipped as (name, reason) when there are
        several."""
        with self.lock:
            files = files or [(data, name)]
            plate = int(plate or 1)
            ids, added, notes, self.add_skipped = [], [], [], []
            for d, n in files:
                try:
                    a, note = self._add_one(d, n, plate)
                except Exception:
                    if len(files) == 1:
                        raise
                    self.add_skipped.append((n, "broken or empty model, could not be read"))
                    continue
                added += a
                ids += [o["id"] for o in a]
                if note:
                    notes.append(note if len(files) == 1 else f"{n}: {note}")
            if not added:
                raise ValueError("nothing could be added")
            self.add_msg = "colours: " + "; ".join(notes) if notes else None
            self.arrange(commit=False, plate=added[0]["plate"])
            self._label = f"add {name}"
            self._commit(True)
            return ids

    def _add_one(self, data, name, plate):
        import uuid

        if name.lower().endswith(".stl"):
            gid = "x" + uuid.uuid4().hex[:6]
            self._put_geo(gid, threemf.load_stl(data, Path(name).stem))
            new = [(gid, Path(name).stem, [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], [1], {})]
        else:
            ui, geos = threemf.parse(data)
            file_pal = [f["colour"] for f in ui["filaments"]]
            fr = [parse_mix_row(x) for x in (ui.get("mix") or "").split(";") if x and x.split(",")[2:3] != ["0"]]
            file_pal += [colormix.recipe_colour(file_pal, ids, ws) for ids, ws in fr]
            ren = {g: "x" + uuid.uuid4().hex[:6] for g in geos}
            for g, v in geos.items():
                self._put_geo(ren[g], v)
            new = [
                (ren[o["gid"]], o["name"], o["m"], [p["extruder"] for p in o["parts"]], o.get("cfg", {}))
                for o in ui["objects"]
            ]
        added = []
        for gid, nm, m, ext, cfg in new:
            o = self._new_obj(gid, nm, m, ext, cfg)
            o["plate"] = min(plate, self.nplates())
            self.drop(o)
            added.append(o)
        if name.lower().endswith(".stl"):
            return added, None
        # map the file's own colours onto this project's filaments (+ mixes)
        phys = [f["colour"] for f in self.st["filaments"]]
        rows = self.mix_rows()
        new_id = {}
        notes = []
        for i in sorted(self.used_ids(added)):
            if i > len(file_pal):
                continue
            bo = colormix.best(file_pal[i - 1], phys)
            new_id[i] = bo["ext"] if bo["kind"] == "phys" else self._mix_id(rows, opt_recipe(bo))
            notes.append(f"{file_pal[i - 1]}→{new_id[i]} (ΔE {bo['de']})")
        self.st["mix"] = ";".join(encode_mix(*r_) for r_ in rows)
        self._remap(added, lambda e: new_id.get(e, 1))
        return added, ", ".join(notes)

    def _new_obj(self, gid, name, m, ext, cfg):
        self.st["next"] += 1
        o = {
            "id": f"o{self.st['next']}",
            "gid": gid,
            "name": name,
            "m": list(m),
            "ext": list(ext),
            "cfg": dict(cfg),
            "pcfg": [{} for _ in ext],
            "plate": 1,
        }
        self.st["objects"].append(o)
        return o

    # ---------- profiles (a library outside the undo history; applying one is an undoable edit)
    def _profiles(self):
        p = self.dir / "profiles.json"
        return json.loads(p.read_text()) if p.exists() else {"global": {}, "object": {}}

    def profiles(self):
        u = self._profiles()
        return {
            "global": [{"name": n, "builtin": True, "count": len(v)} for n, v in PRESETS.items()]
            + [{"name": n, "builtin": False, "count": len(v)} for n, v in u["global"].items()],
            "object": [{"name": n, "builtin": False, "count": len(v), "settings": v} for n, v in u["object"].items()],
            "active": self.st.get("profile"),
        }

    def profile_save(self, kind, name, oid=None, part=None):
        """global: every effective print setting (minus filament assignments); object: the object's overrides"""
        with self.lock:
            name = (name or "").strip()
            if not name:
                raise ValueError("profile needs a name")
            if kind == "global" and name in PRESETS:
                raise ValueError(f"'{name}' is a built-in Orca preset — pick another name")
            if kind == "global":
                vals = {
                    k: str(v)
                    for k, v in {**self.st["settings"], **self.st["overrides"]}.items()
                    if k in threemf.SETTINGS and k not in NO_PROFILE
                }
            else:
                o = self.obj(oid)
                src = o["cfg"] if part is None else self.pcfg(o)[int(part)]
                vals = {k: v for k, v in src.items() if k not in NO_PROFILE}
                if not vals:
                    raise ValueError(f"this {'object' if part is None else 'part'} has no own settings to save")
            u = self._profiles()
            u.setdefault(kind, {})[name] = vals
            (self.dir / "profiles.json").write_text(json.dumps(u, indent=1))
            return {"ok": True, "msg": f"saved {kind} profile '{name}' ({len(vals)} settings)"}

    def fil_presets(self):
        """built-in Orca filament presets + the user's own (filaments.user.json)"""
        p = self.dir / "filaments.user.json"
        return {**FILAMENTS, **(json.loads(p.read_text()) if p.exists() else {})}

    def filament_save(self, i, name):
        """save project filament slot i (1-based) as the user's preset `name` and label the slot with it"""
        name = (name or "").strip()
        if not name:
            raise ValueError("preset needs a name")
        if name in FILAMENTS:
            raise ValueError(f"'{name}' is a built-in preset — pick another name")
        p = self.dir / "filaments.user.json"
        u = json.loads(p.read_text()) if p.exists() else {}
        with self.lock:
            v = slot_values(self.cfg, int(i) - 1)
            v["filament_settings_id"] = [name]
        u[name] = v
        p.write_text(json.dumps(u, indent=0))
        return self.op({"op": "set_filament_preset", "filament": int(i), "preset": name})

    def filament_delete(self, name):
        p = self.dir / "filaments.user.json"
        u = json.loads(p.read_text()) if p.exists() else {}
        u.pop(name, None)
        p.write_text(json.dumps(u, indent=0))
        return {"ok": True, "msg": f"deleted '{name}'"}

    def profile_delete(self, kind, name):
        with self.lock:
            u = self._profiles()
            u.get(kind, {}).pop(name, None)
            (self.dir / "profiles.json").write_text(json.dumps(u, indent=1))
            return {"ok": True, "msg": f"deleted '{name}'"}

    # ---------- geometry helpers
    def obj(self, ref):
        for o in self.st["objects"]:
            if o["id"] == ref:
                return o
        hits = [o for o in self.st["objects"] if o["name"].lower() == str(ref).lower()]
        if len(hits) == 1:
            return hits[0]
        raise KeyError(f"object '{ref}' not found" if not hits else f"name '{ref}' is ambiguous, use id")

    def _verts(self, gid):
        if gid not in self._vcache:
            parts = self.geos[gid]["parts"]
            solid = [
                p for p in parts if p.get("type", "normal_part") == "normal_part"
            ] or parts  # modifiers etc. don't count for size/placement
            self._vcache[gid] = [v for p in solid for v in p["verts"]]
        return self._vcache[gid]

    def bbox(self, o):
        m = o["m"]
        xs, ys, zs = [], [], []
        for x, y, z in self._verts(o["gid"]):
            xs.append(x * m[0] + y * m[3] + z * m[6] + m[9])
            ys.append(x * m[1] + y * m[4] + z * m[7] + m[10])
            zs.append(x * m[2] + y * m[5] + z * m[8] + m[11])
        return [min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)]

    def translate(self, o, dx=0, dy=0, dz=0):
        o["m"][9] += dx
        o["m"][10] += dy
        o["m"][11] += dz

    def drop(self, o):
        self.translate(o, dz=-self.bbox(o)[4])

    def rotate(self, o, deg):
        """about the bbox centre, counter-clockwise seen from above"""
        b = self.bbox(o)
        cx, cy = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2
        a = math.radians(deg)
        c, s = math.cos(a), math.sin(a)
        m = o["m"]
        for r in (0, 3, 6):  # R' = R * Rz  (row vectors)
            x, y = m[r], m[r + 1]
            m[r], m[r + 1] = x * c - y * s, x * s + y * c
        tx, ty = m[9] - cx, m[10] - cy
        m[9], m[10] = tx * c - ty * s + cx, tx * s + ty * c + cy

    def rot_scale(self, o):
        """Z angle (degrees) and mean scale factor — the uniform view used by painting/MCP; per-axis values: "
        "decompose()"""
        r, s = self.decompose(o)
        return r[2], (s[0] * s[1] * s[2]) ** (1 / 3)

    @staticmethod
    def decompose(o):
        """m[0:3]/m[3:6]/m[6:9] = images of the local X/Y/Z axes (rotation · per-axis scale, no shear) ->
        ([rx, ry, rz] degrees with R = Rz·Ry·Rx, so turning about the bed's Z only changes rz; [sx, sy, sz] factors)"""
        m = o["m"]
        s = [math.hypot(*m[i : i + 3]) or 1 for i in (0, 3, 6)]
        R = lambda r, c: m[3 * c + r] / s[c]  # rotation matrix entry, row r, column c
        ry = math.asin(-max(-1.0, min(1.0, R(2, 0))))
        if abs(R(2, 0)) < 0.9999999:
            rx, rz = math.atan2(R(2, 1), R(2, 2)), math.atan2(R(1, 0), R(0, 0))
        else:
            rx, rz = 0.0, math.atan2(-R(0, 1), R(1, 1))  # gimbal lock: fold X into Z
        return [math.degrees(a) for a in (rx, ry, rz)], s

    @staticmethod
    def compose(rot, s):
        a, b, c = (math.radians(v) for v in rot)
        ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
        R = [
            [cc * cb, cc * sb * sa - sc * ca, cc * sb * ca + sc * sa],
            [sc * cb, sc * sb * sa + cc * ca, sc * sb * ca - cc * sa],
            [-sb, cb * sa, cb * ca],
        ]
        return [R[r][c] * s[c] for c in range(3) for r in range(3)]

    def set_transform(self, o, x=None, y=None, rot=None, scale=None, z=None):
        """absolute placement: x/y = bbox centre, z = bottom height (None keeps it);
        rot = degrees about Z or [rx, ry, rz];
        scale = uniform % or [sx, sy, sz] %; None inside a list keeps that axis"""
        b = self.bbox(o)
        cx, cy, z0 = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2, b[4]
        r0, s0 = self.decompose(o)
        if rot is not None:
            r0 = (
                [v if w is None else float(w) for v, w in zip(r0, rot)]
                if isinstance(rot, (list, tuple))
                else r0[:2] + [float(rot)]
            )
        if scale is not None:
            sc = scale if isinstance(scale, (list, tuple)) else [scale] * 3
            s0 = [v if w is None or float(w) <= 0 else float(w) / 100 for v, w in zip(s0, sc)]
        o["m"][:9] = self.compose(r0, s0)
        b = self.bbox(o)
        self.translate(
            o,
            (cx if x is None else x) - (b[0] + b[1]) / 2,
            (cy if y is None else y) - (b[2] + b[3]) / 2,
            (z0 if z is None else z) - b[4],
        )

    def pcfg(self, o):
        n = len(self.geos[o["gid"]]["parts"])
        p = o.setdefault("pcfg", [])
        p += [{} for _ in range(n - len(p))]
        return p[:n]

    def own_geo(self, o, fresh=False, new_shape=False):
        """copy-on-write. Geometries are immutable once committed (undo snapshots point at them), so every edit gets a
        new gid: paint/rename keep the shape (no mesh copy), part add/remove/subdivide get a new shape."""
        import uuid

        g = self.geos[o["gid"]]
        gid = "c" + uuid.uuid4().hex[:10]
        self._put_geo(
            gid,
            {"name": g["name"], "shape": None if new_shape else g.get("shape"), "parts": [dict(p) for p in g["parts"]]},
        )
        o["gid"] = gid
        self._vcache.pop(gid, None)
        return self.geos[gid]

    def to_local(self, o, pts):
        m = o["m"]
        R = [m[0:3], m[3:6], m[6:9]]
        t = m[9:12]
        a, b, c = R[0]
        d, e, f = R[1]
        g, h, i = R[2]
        det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
        inv = [
            [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det],
        ]
        out = []
        for x, y, z in pts:  # v = (w - t) · R^-1   (row vectors)
            x, y, z = x - t[0], y - t[1], z - t[2]
            out.append(tuple(x * inv[0][j] + y * inv[1][j] + z * inv[2][j] for j in range(3)))
        return out

    def part_index(self, o, part):
        if isinstance(part, int) or str(part).isdigit():
            return int(part)
        hit = [i for i, p in enumerate(self.geos[o["gid"]]["parts"]) if p["name"].lower() == str(part).lower()]
        if not hit:
            raise KeyError(f"part '{part}' not found in {o['name']}")
        return hit[0]

    def _region_cls(self, o, r):
        """paint_region selectors -> (classifier in object-local coords, per-triangle normal filter).
        World boxes/spheres are
        converted to local space (rotation about Z + uniform scale keep spheres spheres; boxes use their local bbox)."""
        m = o["m"]
        INF = 1e9
        Wn = lambda n: (
            n[0] * m[0] + n[1] * m[3] + n[2] * m[6],
            n[0] * m[1] + n[1] * m[4] + n[2] * m[7],
            n[0] * m[2] + n[1] * m[5] + n[2] * m[8],
        )
        k_ = self.rot_scale(o)[1] or 1

        def local_box(lo, hi):
            cs = [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
            cs = [tuple(max(-INF, min(INF, c)) for c in p) for p in cs]
            L = self.to_local(o, cs)
            return paintree.box([min(p[j] for p in L) for j in range(3)], [max(p[j] for p in L) for j in range(3)])

        cls = []
        if any(f"{a}_{e}" in r for a in "xyz" for e in ("min", "max")):
            cls.append(local_box([r.get(f"{a}_min", -INF) for a in "xyz"], [r.get(f"{a}_max", INF) for a in "xyz"]))
        if r.get("sphere"):
            c = self.to_local(o, [tuple(r["sphere"]["center"])])[0]
            cls.append(paintree.sphere(c, float(r["sphere"]["radius"]) / k_))
        if r.get("box"):
            cls.append(local_box(r["box"]["min"], r["box"]["max"]))
        if r.get("inside_part") is not None:
            pv = self.geos[o["gid"]]["parts"][self.part_index(o, r["inside_part"])]["verts"]
            cls.append(
                paintree.box([min(v[j] for v in pv) for j in range(3)], [max(v[j] for v in pv) for j in range(3)])
            )
        classify = paintree.both(*cls) if cls else (lambda v: 1)
        face = r.get("facing")
        normal_ok = None
        if face is not None:
            lim = math.cos(math.radians(float(r.get("max_angle", 45))))
            if isinstance(face, str):
                face = {
                    "up": (0, 0, 1),
                    "down": (0, 0, -1),
                    "side": "side",
                    "+x": (1, 0, 0),
                    "-x": (-1, 0, 0),
                    "+y": (0, 1, 0),
                    "-y": (0, -1, 0),
                }[face]
            if isinstance(face, (list, tuple)):
                ln = math.sqrt(sum(c * c for c in face))
                face = tuple(c / ln for c in face)

            def normal_ok(v, face=face, lim=lim):
                u = [v[1][j] - v[0][j] for j in range(3)]
                w = [v[2][j] - v[0][j] for j in range(3)]
                n = Wn((u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]))
                ln = math.sqrt(sum(c * c for c in n)) or 1
                n = [c / ln for c in n]
                return (
                    abs(n[2]) <= 1 - lim if face == "side" else n[0] * face[0] + n[1] * face[1] + n[2] * face[2] >= lim
                )

        return classify, normal_ok

    def _region(self, o, r):
        """triangle selector in world coordinates: z/x/y ranges, facing (up/down/side or [x,y,z]) within max_angle,
        inside sphere {center, radius}, box {min, max}, or the bbox of another part of the same object (inside_part)."""
        m = o["m"]
        W = lambda v: (
            v[0] * m[0] + v[1] * m[3] + v[2] * m[6] + m[9],
            v[0] * m[1] + v[1] * m[4] + v[2] * m[7] + m[10],
            v[0] * m[2] + v[1] * m[5] + v[2] * m[8] + m[11],
        )
        rng = {a: (r.get(f"{a}_min", -1e9), r.get(f"{a}_max", 1e9)) for a in "xyz"}
        face = r.get("facing")
        lim = math.cos(math.radians(float(r.get("max_angle", 45))))
        if isinstance(face, str):
            face = (
                {
                    "up": (0, 0, 1),
                    "down": (0, 0, -1),
                    "side": None,
                    "+x": (1, 0, 0),
                    "-x": (-1, 0, 0),
                    "+y": (0, 1, 0),
                    "-y": (0, -1, 0),
                }[face]
                if face != "side"
                else "side"
            )
        if isinstance(face, (list, tuple)):
            n = math.sqrt(sum(c * c for c in face))
            face = tuple(c / n for c in face)
        sph = r.get("sphere")
        box = r.get("box")
        inp = r.get("inside_part")
        if inp is not None:
            pv = [W(v) for v in self.geos[o["gid"]]["parts"][self.part_index(o, inp)]["verts"]]
            box = {"min": [min(v[k] for v in pv) for k in range(3)], "max": [max(v[k] for v in pv) for k in range(3)]}

        def sel(p):
            V = [W(v) for v in p["verts"]]
            out = []
            for t, (a, b, c) in enumerate(p["tris"]):
                A, B, C = V[a], V[b], V[c]
                ce = [(A[k] + B[k] + C[k]) / 3 for k in range(3)]
                if not all(rng[ax][0] <= ce[k] <= rng[ax][1] for k, ax in enumerate("xyz")):
                    continue
                if sph and math.dist(ce, sph["center"]) > sph["radius"]:
                    continue
                if box and not all(box["min"][k] <= ce[k] <= box["max"][k] for k in range(3)):
                    continue
                if face is not None:
                    u = [B[k] - A[k] for k in range(3)]
                    w = [C[k] - A[k] for k in range(3)]
                    nx, ny, nz = u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]
                    ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
                    nx, ny, nz = nx / ln, ny / ln, nz / ln
                    if face == "side":
                        if abs(nz) > 1 - lim:
                            continue
                    elif nx * face[0] + ny * face[1] + nz * face[2] < lim:
                        continue
                out.append(t)
            return out

        return sel

    # ---------- layout
    def nplates(self):
        return max([self.st.get("plates", 1)] + [o.get("plate", 1) for o in self.st["objects"]])

    def on_plate(self, p):
        return [o for o in self.st["objects"] if o.get("plate", 1) == p]

    def _pack(self, items):
        """shelf-pack (o, bbox) items (tallest first) into one plate: returns (placed [(o, q, x, y)], W, H, leftover)"""
        b, w = self.st["bed"], self.st["wipe"]
        f = w["fp"]
        ww = (f[1] - f[0] + GAP) if w["enabled"] else 0
        maxw, maxh = b["x1"] - b["x0"] - 2 * GAP - ww, b["y1"] - b["y0"] - 2 * GAP
        total = sum((q[1] - q[0] + GAP) * (q[3] - q[2] + GAP) for _, q in items)
        roww = min(maxw, max(*(q[1] - q[0] for _, q in items), math.sqrt(total) * 1.15))
        x = y = rowh = W = 0
        place, left = [], []
        for o, q in items:
            sx, sy = q[1] - q[0], q[3] - q[2]
            if x > 0 and x + sx > roww:
                x = 0
                y += rowh + GAP
                rowh = 0
            if place and y + sy > maxh:  # this plate is full -> spill over
                left.append((o, q))
                continue
            place.append((o, q, x, y))
            x += sx + GAP
            rowh = max(rowh, sy)
            W = max(W, x - GAP)
        return place, W, y + rowh, left

    def arrange(self, commit=True, plate=None, all_plates=False):
        """modifier-role objects ride along with the first object they overlap"""
        mods = [o for o in self.st["objects"] if o.get("role")]
        hosts = {}
        for mo in mods:
            q = self.bbox(mo)
            for o in self.st["objects"]:
                b = self.bbox(o)
                if (
                    not o.get("role")
                    and o.get("plate", 1) == mo.get("plate", 1)
                    and q[0] < b[1]
                    and q[1] > b[0]
                    and q[2] < b[3]
                    and q[3] > b[2]
                ):
                    hosts[mo["id"]] = (o, b)
                    break
        self._arrange(commit=False, plate=plate, all_plates=all_plates)
        for mo in mods:
            if mo["id"] in hosts:
                o, b = hosts[mo["id"]]
                n = self.bbox(o)
                self.translate(mo, n[0] - b[0], n[2] - b[2])
                mo["plate"] = o.get("plate", 1)
        if commit:
            self._commit()

    def _arrange(self, commit=True, plate=None, all_plates=False):
        """shelf packing (tallest rows first) into a block centred on each plate; wipe tower right of it. Objects that
        don't fit spill onto the next plate (new plates are added as needed). all_plates=True repacks everything from
        plate 1 (fewest plates). ponytail: bbox-only, no rotation/nesting"""
        objs = [o for o in self.st["objects"] if not o.get("role")]  # modifier objects stay where the user put them
        if not objs:
            return
        b, w = self.st["bed"], self.st["wipe"]
        f = w["fp"]
        w["enabled"] = self.needs_tower()
        if all_plates:
            todo, p, spill_to = [o for o in objs], 1, None
        else:
            p = plate or 1
            todo = [o for o in self.on_plate(p) if not o.get("role")]
            spill_to = self.nplates() + 1
        items = sorted(((o, self.bbox(o)) for o in todo), key=lambda t: -(t[1][3] - t[1][2]))
        used = set()
        while items:
            place, W, H, items = self._pack(items)
            ww = (f[1] - f[0] + GAP) if w["enabled"] else 0
            ox, oy = (b["x0"] + b["x1"]) / 2 - (W + ww) / 2, (b["y0"] + b["y1"]) / 2 - H / 2
            for o, q, px, py in place:
                o["plate"] = p
                self.translate(o, ox + px - q[0], oy + (H - py) - (q[3] - q[2]) - q[2])
            if w["enabled"] and p == (plate or 1):
                w["x"] = min(ox + W + GAP - f[0], b["x1"] - 2 - f[1])
                w["y"] = b["y1"] - 2 - f[3]  # back edge, away from the door (front = low y)
            used.add(p)
            p = (p + 1) if spill_to is None else spill_to
            spill_to = None if spill_to is None else spill_to + 1
        self.st["plates"] = max(used) if all_plates else max(self.nplates(), *used)
        self.fix_wipe()
        if commit:
            self._commit()

    def place_free(self, o, gap=GAP):
        """move o to the free spot nearest the bed centre (other objects + wipe tower count as obstacles)"""
        b, w = self.st["bed"], self.st["wipe"]
        q = self.bbox(o)
        sx, sy = q[1] - q[0], q[3] - q[2]
        boxes = [self.bbox(x) for x in self.on_plate(o.get("plate", 1)) if x is not o]
        if w["enabled"]:
            f = w["fp"]
            boxes.append([w["x"] + f[0], w["x"] + f[1], w["y"] + f[2], w["y"] + f[3]])
        cx, cy = (b["x0"] + b["x1"]) / 2, (b["y0"] + b["y1"]) / 2
        best, bd = None, float("inf")
        x = b["x0"] + 2
        while x + sx <= b["x1"] - 2:
            y = b["y0"] + 2
            while y + sy <= b["y1"] - 2:
                if all(
                    x + sx + gap <= p[0] or x - gap >= p[1] or y + sy + gap <= p[2] or y - gap >= p[3] for p in boxes
                ):
                    d = (x + sx / 2 - cx) ** 2 + (y + sy / 2 - cy) ** 2
                    if d < bd:
                        bd, best = d, (x, y)
                y += 4
            x += 4
        if best:
            self.translate(o, best[0] - q[0], best[1] - q[2])
        return bool(best)

    def overlaps(self):
        """pairs of objects whose footprints overlap (Orca then fails with 'G-code conflicts')"""
        bs = [(o["name"], o.get("plate", 1), self.bbox(o)) for o in self.st["objects"]]
        return [
            (a, b)
            for i, (a, pa, p) in enumerate(bs)
            for b, pb, q in bs[i + 1 :]
            if pa == pb and p[0] < q[1] and q[0] < p[1] and p[2] < q[3] and q[2] < p[3]
        ]

    def off_bed(self):
        b = self.st["bed"]
        out = []
        for o in self.st["objects"]:
            q = self.bbox(o)
            if q[0] < b["x0"] or q[1] > b["x1"] or q[2] < b["y0"] or q[3] > b["y1"]:
                out.append(o["name"])
        return out

    def needs_tower(self):
        """a prime tower is only useful when the objects use 2+ filaments (parts, paint, or a mix = 2+ physical ones)"""
        n, used = len(self.st["filaments"]), set()
        for o in self.st["objects"]:
            used.update(e for e in o["ext"] if e)
            for p in self.geos[o["gid"]]["parts"]:
                for c in p.get("paint") or ():
                    if c:
                        used |= paintree.used_states(c)
        return len(used) > 1 or any(e > n for e in used)

    def fix_wipe(self):
        """tower on/off follows needs_tower(). When it appears (or is in the way) it goes to the first free corner,
        else the nearest
        free spot on a 5 mm grid - objects never move. No room: corner anyway. Returns "" | "moved" | "conflict"."""
        w, b = self.st["wipe"], self.st["bed"]
        was = w["enabled"]
        w["enabled"] = self.needs_tower()
        if not w["enabled"] or not self.st["objects"]:
            return ""
        f, gap = w["fp"], 4
        boxes = [self.bbox(o) for o in self.st["objects"]]
        free = lambda x, y: all(
            x + f[1] + gap <= q[0] or x + f[0] - gap >= q[1] or y + f[3] + gap <= q[2] or y + f[2] - gap >= q[3]
            for q in boxes
        )
        if was and free(w["x"], w["y"]):
            return ""
        xs, ys = (b["x0"] + 2 - f[0], b["x1"] - 2 - f[1]), (b["y0"] + 2 - f[2], b["y1"] - 2 - f[3])
        corners = [(x, y) for y in ys[::-1] for x in xs[::-1]]  # back-right, back-left, front-right, front-left
        best = next((c for c in corners if free(*c)), None)
        if not best:
            bd, x = float("inf"), xs[0]
            while x <= xs[1]:
                y = ys[0]
                while y <= ys[1]:
                    d = (x - w["x"]) ** 2 + (y - w["y"]) ** 2
                    if d < bd and free(x, y):
                        bd, best = d, (x, y)
                    y += 5
                x += 5
        res = "moved"
        if not best:
            best, res = corners[0], "conflict"
        if (w["x"], w["y"]) == best and was:
            return "conflict" if res == "conflict" else ""
        w["x"], w["y"] = best
        return res

    # ---------- operations (all mutations go through here)
    LABELS = {
        "set_ext": "filament",
        "move": "move",
        "drop": "drop to bed",
        "set_object": "object settings",
        "set_object_settings": "object settings",
        "rotate": "rotate",
        "dup": "duplicate",
        "del": "delete",
        "arrange": "arrange",
        "set_wipe": "wipe tower",
        "set_global": "print settings",
        "mix_add": "add mix",
        "mix_del": "remove mix",
        "add_primitive": "add primitive",
        "add_part": "add volume",
        "del_part": "remove volume",
        "set_part": "part settings",
        "move_part": "move volume",
        "set_role": "object role",
        "set_filaments": "filament colours",
        "set_filament_preset": "filament preset",
        "set_filament_temps": "filament temperatures",
        "set_filament_values": "filament settings",
        "dedupe_mixes": "merge duplicate mixes",
        "apply_colour_map": "map colours",
        "replace_colour": "replace colour",
        "paint": "paint",
        "paint_brush": "paint",
        "paint_region": "paint",
        "subdivide": "refine mesh",
        "checkin": "check-in",
    }

    def _check_lock(self, r):
        """objects checked out (MCP) can only be changed with the checkout token"""
        if r["op"] == "arrange":
            return
        ids = [r["id"]] if r.get("id") else []
        for ref in ids:
            o = self.obj(ref)
            lk = o.get("lock")
            if lk and r.get("token") != lk["token"] and r["op"] not in ("release",):
                raise ValueError(f"{o['name']} is checked out by {lk['by']} — check it in or release it first")

    def op(self, r):
        with self.lock:
            k = r["op"]
            msg = None
            self._check_lock(r)
            name = self.obj(r["id"])["name"] if r.get("id") else ""
            self._label = f"{self.LABELS.get(k, k)}{' · ' + name if name else ''}"
            if k == "clear_result":  # discard the last slice (not undoable, it isn't plate state)
                self.st["result"] = None
                self._commit(record=False)
                return {"ok": True, "rev": self.rev}
            if k == "checkout":  # lock + export the object for external editing
                import secrets

                o = self.obj(r["id"])
                if o.get("lock"):
                    raise ValueError(f"'{o['name']}' is already checked out by {o['lock']['by']}")
                token = secrets.token_hex(6)
                d = self.dir / "checkout"
                d.mkdir(exist_ok=True)
                safe = re.sub(r"[^\w.-]+", "_", o["name"])
                path = d / f"{safe}-{o['id']}.3mf"
                path.write_bytes(threemf.build(self.cfg, self.geos, [self._build_obj(o)]))
                import time

                o["lock"] = {"token": token, "by": r.get("by", "MCP"), "since": time.time(), "path": str(path)}
                self._commit(record=False)
                return {"ok": True, "token": token, "path": str(path), "object": o["id"]}
            if k == "release":  # unlock without changes (token, or force)
                o = self.obj(r["id"])
                lk = o.get("lock")
                if lk and not r.get("force") and r.get("token") != lk["token"]:
                    raise ValueError("wrong token (use force to break the lock)")
                o.pop("lock", None)
                self._commit(record=False)
                return {"ok": True, "rev": self.rev, "msg": f"{o['name']} released"}
            if k == "checkin":  # replace geometry/paint from the edited 3MF, keep transform + settings
                o = self.obj(r["id"])
                lk = o.get("lock")
                if not lk or r.get("token") != lk["token"]:
                    raise ValueError("object is not checked out with this token")
                data = Path(r.get("path") or lk["path"]).read_bytes()
                ui, geos = threemf.parse(data)
                if len(ui["objects"]) != 1:
                    raise ValueError(f"expected exactly 1 object in the 3MF, found {len(ui['objects'])}")
                no = ui["objects"][0]
                ng = geos[no["gid"]]
                if not any(p.get("type", "normal_part") == "normal_part" for p in ng["parts"]):
                    raise ValueError("no solid part in the checked-in object")
                old_pc = {p["name"]: c for p, c in zip(self.geos[o["gid"]]["parts"], self.pcfg(o))}
                import uuid

                gid = "k" + uuid.uuid4().hex[:10]
                ng["name"] = o["name"]
                ng["shape"] = None
                self._put_geo(gid, ng)
                o["gid"] = gid
                self._vcache.pop(gid, None)
                o["ext"] = [p["extruder"] for p in no["parts"]]
                o["pcfg"] = [
                    old_pc.get(p["name"], c) or c
                    for p, c in zip(ng["parts"], no.get("pcfg") or [{} for _ in ng["parts"]])
                ]
                if r.get("use_file_transform"):
                    o["m"] = no["m"]
                o.pop("lock", None)
                self.drop(o)
                self.fix_wipe()
                self._commit(True)
                return {
                    "ok": True,
                    "rev": self.rev,
                    "msg": f"{o['name']} checked in: {len(ng['parts'])} parts, "
                    f"{sum(len(p['tris']) for p in ng['parts'])} triangles",
                    "off_bed": self.off_bed(),
                }
            if k == "apply_profile":  # {kind: global|object, name, id?}
                kind, name = r.get("kind", "global"), r["name"]
                u = self._profiles()
                vals = (
                    PRESETS.get(name)
                    if kind == "global" and name in PRESETS and not r.get("user")
                    else u.get(kind, {}).get(name)
                )
                if vals is None:
                    raise KeyError(f"no {kind} profile '{name}'")
                vals = {k: str(v) for k, v in vals.items() if k not in NO_PROFILE}
                if kind == "global":  # replaces the project-level overrides
                    self.st["overrides"] = {
                        k: v for k, v in vals.items() if k in threemf.SETTINGS and v != str(self.st["settings"].get(k))
                    }
                    self.st["profile"] = name
                    self._label = f"profile · {name}"
                    msg = f"profile '{name}': {len(self.st['overrides'])} settings differ from the project"
                else:  # merges into the object's own settings
                    o = self.obj(r["id"])
                    vals = {k: v for k, v in vals.items() if k in threemf.OBJ_SETTINGS}
                    if r.get("part") is not None:  # one volume (e.g. the TPU body of a PLA+TPU object)
                        pi = int(r["part"])
                        pc = self.pcfg(o)
                        pc[pi] = {**pc[pi], **vals}
                        o["pcfg"] = pc
                        pn = self.geos[o["gid"]]["parts"][pi]["name"]
                        self._label = f"profile {name} · {pn}"
                        msg = f"'{name}' applied to {o['name']} · {pn}"
                    else:
                        o["cfg"].update(vals)
                        self._label = f"profile {name} · {o['name']}"
                        msg = f"'{name}' applied to {o['name']}"
            elif (
                k == "apply_colour_map"
            ):  # recolour the scene onto a palette: {filaments: [{colour, type}], map: {old_id: option}}
                n = len(self.st["filaments"])
                fs = r["filaments"]
                if len(fs) != n:
                    raise ValueError(f"project has {n} filaments, got {len(fs)}")
                rows, new = [], {}
                for old, opt in r["map"].items():
                    new[int(old)] = int(opt["ext"]) if opt["kind"] == "phys" else self._mix_id(rows, opt_recipe(opt))
                for i, f in enumerate(fs):
                    self.st["filaments"][i]["colour"] = f["colour"].upper()
                cfg = dict(self.cfg)
                cfg["filament_colour"] = [f["colour"] for f in self.st["filaments"]]
                self.cfg = cfg
                self.st["cfg_id"] = self._put_cfg(cfg)
                self.st["mix"] = ";".join(encode_mix(*r_) for r_ in rows)
                self._remap(self.st["objects"], lambda e: new.get(e, e if e <= n else 1))
                msg = f"colours mapped: {len(new)} model colours -> {n} filaments" + (
                    f" + {len(rows)} mixes" if rows else ""
                )
            elif k == "set_filaments":  # e.g. synced from the printer's RFID: [{colour, type?}] per physical filament
                fs = r["filaments"]
                cfg = dict(self.cfg)
                n = len(self.st["filaments"])
                if len(fs) != n:
                    raise ValueError(f"project has {n} filaments, got {len(fs)}")
                warn = []
                for i, f in enumerate(fs):
                    if f.get("colour"):
                        self.st["filaments"][i]["colour"] = f["colour"].upper()
                cfg["filament_colour"] = [f["colour"] for f in self.st["filaments"]]
                for i, f in enumerate(fs):  # different material loaded -> switch that slot's preset
                    if f.get("type") and f["type"] != self.st["filaments"][i]["type"]:
                        p = match_preset(f["type"], f.get("vendor", ""), f.get("sub_type", ""))
                        if p:
                            cfg = filament_preset(cfg, i, p)
                            self.st["filaments"][i].update(type=f["type"], preset=p)
                            warn.append(f"{i + 1} → {p}")
                        else:
                            warn.append(f"{i + 1}: no U1 preset for {f['type']}")
                self.cfg = cfg
                self.st["cfg_id"] = self._put_cfg(cfg)
                msg = "colours synced" + (" — material changed: " + "; ".join(warn) if warn else "")
            elif k == "set_filament_preset":  # {filament: 1-based, preset: Orca filament preset name}
                i = int(r["filament"]) - 1
                if not 0 <= i < len(self.st["filaments"]):
                    raise ValueError(f"filament {i + 1} does not exist")
                fp = self.fil_presets()
                if r["preset"] not in fp:
                    raise ValueError(f"unknown filament preset '{r['preset']}'")
                cfg = filament_preset(self.cfg, i, fp[r["preset"]])
                self.cfg = cfg
                self.st["cfg_id"] = self._put_cfg(cfg)
                self.st["filaments"][i].update(type=cfg["filament_type"][i], preset=r["preset"])
                first = sum(map(int, cfg["filament_flow_step_size"][:i]))  # flow variants are interleaved
                msg = f"filament {i + 1}: {r['preset']} ({cfg['nozzle_temperature'][first]} °C)"
            elif k in (
                "set_filament_values",
                "set_filament_temps",
            ):  # {filament, values: {key: v}} | {filament, nozzle?, bed?} °C
                i = int(r["filament"]) - 1
                vals = dict(r.get("values") or {})
                if r.get("nozzle"):
                    vals.update(nozzle_temperature=r["nozzle"], nozzle_temperature_initial_layer=r["nozzle"])
                if r.get("bed"):
                    vals.update(
                        {x: r["bed"] for x in self.cfg if x.endswith(("plate_temp", "plate_temp_initial_layer"))}
                    )
                cfg = set_filament_values(self.cfg, i, vals)
                self.cfg = cfg
                self.st["cfg_id"] = self._put_cfg(cfg)
                msg = f"filament {i + 1}: " + ", ".join(
                    f"{k} = {v}" for k, v in vals.items() if "plate_temp" not in k or k == "hot_plate_temp"
                )
            elif (
                k == "replace_colour"
            ):  # every use of filament `from` (parts + paint) -> `to`; scoped to object `id` if given
                a, b = int(r["from"]), int(r["to"])
                tot = len(self.st["filaments"]) + len(self.mixes())
                if not 1 <= b <= tot:
                    raise ValueError(f"filament {b} does not exist")
                objs = [self.obj(r["id"])] if r.get("id") else self.st["objects"]
                if a not in self.used_ids(objs):
                    raise ValueError(f"filament {a} is not used" + (" by this object" if r.get("id") else ""))
                self._remap(objs, lambda e: b if e == a else e)
                msg = f"colour {a} -> {b}"
            elif k == "set_ext":
                o = self.obj(r["id"])
                e = int(r["ext"])
                if not 1 <= e <= len(self.st["filaments"]) + len(self.mixes()):
                    raise ValueError(f"filament {e} does not exist")
                if r.get("part") is None:
                    o["ext"] = [e] * len(o["ext"])
                else:
                    o["ext"][int(r["part"])] = e
            elif k == "move":  # raw matrix from a drag in the browser (+ plate when dropped on another one)
                o = self.obj(r["id"])
                o["m"] = [float(v) for v in r["m"]]
                if r.get("plate"):
                    o["plate"] = int(r["plate"])
                    self.st["plates"] = max(self.nplates(), o["plate"])
                if r.get("drop"):
                    self.drop(o)  # lay on face: the face goes onto the bed
            elif k == "drop":  # back onto the bed after a Z lift / sink
                self.drop(self.obj(r["id"]))
            elif k == "set_object":
                o = self.obj(r["id"])
                if r.get("name"):
                    o["name"] = r["name"]
                if "cfg" in r:
                    o["cfg"] = {a: str(v) for a, v in r["cfg"].items() if a in threemf.OBJ_SETTINGS and v is not None}
                if any(r.get(a) is not None for a in ("x", "y", "z", "rot", "scale")):
                    self.set_transform(o, r.get("x"), r.get("y"), r.get("rot"), r.get("scale"), r.get("z"))
            elif k == "set_object_settings":  # merge; value None removes the override
                o = self.obj(r["id"])
                for a, v in r["settings"].items():
                    if a not in threemf.OBJ_SETTINGS:
                        raise KeyError(f"'{a}' is not a per-object setting")
                    if v is None:
                        o["cfg"].pop(a, None)
                    else:
                        o["cfg"][a] = str(v)
            elif k == "add_primitive":  # new object: box / cylinder / sphere
                import uuid

                gid = "p" + uuid.uuid4().hex[:8]
                self._put_geo(gid, threemf.primitive(r.get("shape", "box"), r.get("size", [20, 20, 20]), r.get("name")))
                o = self._new_obj(
                    gid, self.geos[gid]["name"], [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0], [int(r.get("ext", 1))], {}
                )
                o["plate"] = min(int(r.get("plate") or 1), self.nplates())
                b = self.st["bed"]
                self.translate(o, r.get("x", (b["x0"] + b["x1"]) / 2), r.get("y", (b["y0"] + b["y1"]) / 2))
                if r.get("x") is None:
                    self.place_free(o)
                msg = f"added {o['id']}"
                self._commit(True)
                return {"ok": True, "rev": self.rev, "msg": msg, "id": o["id"], "off_bed": self.off_bed()}
            elif k == "add_part":  # modifier / negative volume / support blocker|enforcer / extra part inside an object
                kinds = {
                    "part": "normal_part",
                    "modifier": "modifier_part",
                    "negative": "negative_part",
                    "support_blocker": "support_blocker",
                    "support_enforcer": "support_enforcer",
                }
                o = self.obj(r["id"])
                kind = kinds[r.get("kind", "modifier")]
                q = self.bbox(o)
                size = r.get("size") or [
                    round((q[1] - q[0]) * 0.6, 1),
                    round((q[3] - q[2]) * 0.6, 1),
                    round((q[5] - q[4]) * 0.5, 1),
                ]
                cx, cy = r.get("x", (q[0] + q[1]) / 2), r.get("y", (q[2] + q[3]) / 2)
                z0 = r.get("z", q[4] if kind == "normal_part" else (q[4] + q[5]) / 2 - size[2] / 2)
                prim = threemf.primitive(r.get("shape", "box"), size)["parts"][0]
                prim["verts"] = self.to_local(o, [(x + cx, y + cy, z + z0) for x, y, z in prim["verts"]])
                label = {
                    "normal_part": "Part",
                    "modifier_part": "Modifier",
                    "negative_part": "Negative",
                    "support_blocker": "Support blocker",
                    "support_enforcer": "Support enforcer",
                }[kind]
                prim.update(type=kind, name=r.get("name") or f"{label} {r.get('shape', 'box')}")
                pc = self.pcfg(o)
                g = self.own_geo(o, new_shape=True)
                g["parts"].append(prim)
                o["ext"].append(int(r.get("ext", o["ext"][0])))
                pc.append({})
                o["pcfg"] = pc
                self._commit(True)
                return {
                    "ok": True,
                    "rev": self.rev,
                    "part": len(g["parts"]) - 1,
                    "msg": f"{label} added to {o['name']}",
                }
            elif k == "move_part":  # {id, part, x?, y?, z?} world centre of the volume (omitted axis stays)
                o = self.obj(r["id"])
                i = int(r["part"])
                g = self.own_geo(o, new_shape=True)
                p = g["parts"][i]
                m = o["m"]
                V = p["verts"]
                n = len(V) or 1
                c = [sum(v[j] for v in V) / n for j in range(3)]  # local centre
                w = [
                    c[0] * m[0] + c[1] * m[3] + c[2] * m[6] + m[9],
                    c[0] * m[1] + c[1] * m[4] + c[2] * m[7] + m[10],
                    c[0] * m[2] + c[1] * m[5] + c[2] * m[8] + m[11],
                ]
                w2 = [r.get(a, w[j]) if r.get(a) is not None else w[j] for j, a in enumerate("xyz")]
                c2 = self.to_local(o, [tuple(w2)])[0]
                p["verts"] = [(x + c2[0] - c[0], y + c2[1] - c[1], z + c2[2] - c[2]) for x, y, z in V]
                self._vcache.pop(o["gid"], None)
                o["pv"] = o.get("pv", 0) + 1
                self._commit(True)
                return {"ok": True, "rev": self.rev, "gid": o["gid"], "msg": f"{p['name']} moved"}
            elif (
                k == "set_role"
            ):  # the whole object acts as a modifier/negative/blocker/enforcer for objects it overlaps (null = normal)
                o = self.obj(r["id"])
                role = r.get("role") or None
                if role not in (None, "modifier_part", "negative_part", "support_blocker", "support_enforcer"):
                    raise ValueError("bad role")
                if role:
                    o["role"] = role
                else:
                    o.pop("role", None)
                msg = f"{o['name']}: " + (
                    "normal object"
                    if not role
                    else role.replace("_part", "").replace("_", " ") + " — applies to objects it overlaps"
                )
            elif k == "del_part":
                o = self.obj(r["id"])
                i = int(r["part"])
                pc = self.pcfg(o)
                g = self.own_geo(o, new_shape=True)
                if (
                    len([p for p in g["parts"] if p.get("type", "normal_part") == "normal_part"]) == 1
                    and g["parts"][i].get("type", "normal_part") == "normal_part"
                ):
                    raise ValueError("cannot delete the last solid part — delete the object instead")
                g["parts"].pop(i)
                o["ext"].pop(i)
                pc.pop(i)
                o["pcfg"] = pc
                self._commit(True)
                return {"ok": True, "rev": self.rev, "msg": "part removed"}
            elif k == "set_part":  # per-part (modifier) settings / name / filament
                o = self.obj(r["id"])
                i = int(r["part"])
                pc = self.pcfg(o)
                if "cfg" in r:
                    pc[i] = {a: str(v) for a, v in r["cfg"].items() if a in threemf.OBJ_SETTINGS and v is not None}
                if r.get("ext"):
                    o["ext"][i] = int(r["ext"])
                if r.get("name") and r["name"] != self.geos[o["gid"]]["parts"][i]["name"]:
                    self.own_geo(o)["parts"][i]["name"] = r["name"]
                o["pcfg"] = pc
            elif k == "paint":  # {id, part, set: {"<filament>": [triangle indices]}}  (0 = erase)
                o = self.obj(r["id"])
                i = int(r["part"])
                g = self.own_geo(o)
                p = g["parts"][i]
                n = len(p["tris"])
                p["paint"] = list(p["paint"]) if p.get("paint") else [None] * n  # copy: older snapshots keep theirs
                for st, idx in r["set"].items():
                    code = threemf.paint_code(int(st))
                    for t in idx:
                        if 0 <= t < n:
                            p["paint"][t] = code
                if not any(p["paint"]):
                    p["paint"] = None
                o["pv"] = o.get("pv", 0) + 1
                self._commit(True)
                return {"ok": True, "rev": self.rev, "pv": o["pv"], "gid": o["gid"]}
            elif (
                k == "paint_brush"
            ):  # adaptive brush: strokes = [{center: world xyz, radius: mm}]; triangles split only at the edge
                o = self.obj(r["id"])
                st = int(r.get("filament", 0))
                i = self.part_index(o, r["part"])
                k_ = self.rot_scale(o)[1] or 1
                balls = [(self.to_local(o, [tuple(b["center"])])[0], float(b["radius"]) / k_) for b in r["strokes"]]
                detail = float(r.get("detail") or max(0.15, min(1.0, min(b[1] for b in balls) / 5))) / k_
                cls = [paintree.sphere(c, rad) for c, rad in balls]
                lo = [min(c[j] - rad for c, rad in balls) for j in range(3)]
                hi = [max(c[j] + rad for c, rad in balls) for j in range(3)]

                def union(v, cls=cls, lo=lo, hi=hi):
                    if any(all(p[j] < lo[j] for p in v) or all(p[j] > hi[j] for p in v) for j in range(3)):
                        return 0
                    res = [f(v) for f in cls]
                    return 1 if 1 in res else (-1 if -1 in res else 0)

                n = self._tree_paint(o, [i], union, st, detail)
                self._commit(True)
                return {"ok": True, "rev": self.rev, "gid": o["gid"], "msg": f"{n} triangles touched"}
            elif k == "paint_region":  # rule-based painting (MCP): all given selectors must match (AND)
                o = self.obj(r["id"])
                g = self.geos[o["gid"]]
                st = int(r.get("filament", 0))
                if not 0 <= st <= len(self.st["filaments"]) + len(self.mixes()):
                    raise ValueError(f"filament {st} does not exist")
                solid = [i for i, p in enumerate(g["parts"]) if p.get("type", "normal_part") == "normal_part"]
                parts = [self.part_index(o, r["part"])] if r.get("part") is not None else solid
                # adaptive like Orca: geometry stays, border triangles get split trees down to `detail` mm (default 0.5)
                detail = float(r.get("detail") or r.get("refine") or 0.5) / (self.rot_scale(o)[1] or 1)
                cls, normal_ok = self._region_cls(o, r)
                total = self._tree_paint(o, parts, cls, st, detail, normal_ok)
                if not total:
                    raise ValueError(
                        "no triangles match the region (check coordinates; get_scene gives object centre/size)"
                    )
                self._commit(True)
                return {
                    "ok": True,
                    "rev": self.rev,
                    "msg": f"painted {total} triangles with filament {st}" + (" (erased)" if st == 0 else ""),
                }
            elif k == "subdivide":  # finer triangles for painting
                o = self.obj(r["id"])
                i = int(r["part"])
                g = self.own_geo(o, new_shape=True)
                p = g["parts"][i]
                before = len(p["tris"])
                passes = threemf.subdivide(p, float(r.get("max_edge", 1.5)), int(r.get("max_tris", 300000)))
                self._vcache.pop(o["gid"], None)
                self._commit(True)
                return {
                    "ok": True,
                    "rev": self.rev,
                    "msg": f"{before} → {len(p['tris'])} triangles"
                    + ("" if passes else " (already fine enough or over budget)"),
                }
            elif k == "rotate":
                self.rotate(self.obj(r["id"]), float(r["deg"]))
            elif k == "dup":
                src = self.obj(r["id"])
                for _ in range(int(r.get("count", 1))):
                    o = self._new_obj(src["gid"], src["name"], src["m"], src["ext"], src["cfg"])
                    o["pcfg"] = [dict(p) for p in self.pcfg(src)]
                    o["plate"] = src.get("plate", 1)
                    q = self.bbox(src)
                    self.translate(o, q[1] - q[0] + GAP)
                if r.get("arrange", True):
                    self.arrange(commit=False, plate=src.get("plate", 1))
            elif k == "del":
                o = self.obj(r["id"])
                self.st["objects"].remove(o)
            elif k == "arrange":  # {plate?} one plate (spills to new plates) | {all: true} repack everything
                self.arrange(commit=False, plate=int(r.get("plate") or 1), all_plates=bool(r.get("all")))
                msg = f"arranged on {self.nplates()} plate(s)"
            elif k == "set_plate":  # move an object to another plate (plates+1 = new plate)
                o = self.obj(r["id"])
                p = int(r["plate"])
                if not 1 <= p <= self.nplates() + 1:
                    raise ValueError(f"plate {p} does not exist")
                o["plate"] = p
                self.st["plates"] = max(self.nplates(), p)
                self.place_free(o)
            elif k == "add_plate":
                self.st["plates"] = self.nplates() + 1
                msg = f"plate {self.st['plates']} added"
            elif k == "del_plate":  # removes the plate AND its objects (like Orca); later plates shift down
                p = int(r["plate"])
                n_ = self.nplates()
                if n_ <= 1:
                    raise ValueError("the last plate can't be deleted")
                gone = self.on_plate(p)
                self.st["objects"] = [o for o in self.st["objects"] if o not in gone]
                for o in self.st["objects"]:
                    if o.get("plate", 1) > p:
                        o["plate"] -= 1
                self.st["plates"] = n_ - 1
                msg = f"plate {p} deleted" + (f" with {len(gone)} objects" if gone else "")
            elif k == "set_wipe":
                self.st["wipe"]["x"], self.st["wipe"]["y"] = float(r["x"]), float(r["y"])
            elif k == "set_global":  # value None = back to the project value
                self.st.pop("profile", None)
                for a, v in r["settings"].items():
                    if a not in threemf.SETTINGS:
                        raise KeyError(f"unknown setting '{a}'")
                    if v is None or str(v) == str(self.st["settings"].get(a)):
                        self.st["overrides"].pop(a, None)
                    else:
                        self.st["overrides"][a] = str(v)
            elif k == "dedupe_mixes":
                msg = self.dedupe_mixes()
            elif k == "mix_add":  # {a, b, pct} or {ids:[..], weights:[..]} (2-4 physical filaments)
                n = len(self.st["filaments"])
                ids = r.get("ids") or [r["a"], r["b"]]
                ws = r.get("weights") or [100 - int(r.get("pct", 50)), int(r.get("pct", 50))]
                ids = [int(x) for x in ids]
                ws = [int(x) for x in ws]
                if (
                    len(set(ids)) != len(ids)
                    or not 2 <= len(ids) <= 4
                    or not all(1 <= x <= n for x in ids)
                    or len(ws) != len(ids)
                    or min(ws) <= 0
                ):
                    raise ValueError("a mix needs 2-4 different physical filaments with positive weights")
                rec = colormix.norm(ids, ws)
                rows = self.mix_rows()
                if rec in rows:
                    return {
                        "ok": True,
                        "rev": self.rev,
                        "msg": f"already there as filament {n + 1 + rows.index(rec)}",
                        "id": n + 1 + rows.index(rec),
                    }
                self.st["mix"] = ";".join(filter(None, [self.st["mix"], encode_mix(*rec)]))
                msg = f"mix = filament {n + len(self.mixes())}"
            elif k == "mix_del":  # parts/paint on the removed mix fall back to its main component
                n = len(self.st["filaments"])
                rows = self.mix_rows()
                i = int(r["index"])
                vid = n + 1 + i
                first = rows[i][0][0]
                rows.pop(i)
                self.st["mix"] = ";".join(encode_mix(*r_) for r_ in rows)
                self._remap(self.st["objects"], lambda e: first if e == vid else e - 1 if e > vid else e)
            else:
                raise KeyError(f"unknown op '{k}'")
            if k != "set_wipe":
                fw = self.fix_wipe()
                if fw == "conflict":
                    msg = "wipe tower doesn't fit — placed in the corner, it overlaps objects"
                elif fw and not msg:
                    msg = "wipe tower placed clear of objects"
            self._commit()
            return {"ok": True, "rev": self.rev, "msg": msg, "off_bed": self.off_bed()}

    def fil_info(self):
        """filaments + their preset and main temperatures (from the project config)"""
        c = self.cfg
        n = len(self.st["filaments"])
        step = [int(x) for x in c.get("filament_flow_step_size") or ["1"] * n]
        g = lambda k, i: (c.get(k) or [""] * n)[i]
        keys = (
            "nozzle_temperature",
            "hot_plate_temp",
            "filament_max_volumetric_speed",
            "filament_flow_ratio",
            "filament_retraction_length",
            "filament_retraction_speed",
            "fan_min_speed",
            "fan_max_speed",
        )
        return [
            dict(
                f,
                preset=g("filament_settings_id", i),
                nozzle=c["nozzle_temperature"][sum(step[:i])],
                bed=g("hot_plate_temp", i),
                vals={k: v[0] for k, v in slot_values(c, i).items() if k in keys},
            )
            for i, f in enumerate(self.st["filaments"])
        ]

    def summary(self):
        """compact, model-friendly view of the session (for MCP)"""
        st = self.st
        n = len(st["filaments"])
        objs = []
        for o in st["objects"]:
            q = self.bbox(o)
            rot, k = self.rot_scale(o)
            objs.append(
                {
                    "id": o["id"],
                    "name": o["name"],
                    "plate": o.get("plate", 1),
                    "parts": [
                        {
                            "index": i,
                            "name": p["name"],
                            "type": p.get("type", "normal_part").replace("_part", ""),
                            "filament": e,
                            "overrides": pc,
                        }
                        for i, (p, e, pc) in enumerate(zip(self.geos[o["gid"]]["parts"], o["ext"], self.pcfg(o)))
                    ],
                    "center_xy": [round((q[0] + q[1]) / 2, 1), round((q[2] + q[3]) / 2, 1)],
                    "size_xyz": [round(q[1] - q[0], 1), round(q[3] - q[2], 1), round(q[5] - q[4], 1)],
                    "rotation_deg": round(rot, 1),
                    "scale_pct": round(k * 100, 1),
                    "overrides": o["cfg"],
                }
            )
        mixes = []
        for i, ((ids, ws), c) in enumerate(zip(self.mix_rows(), self.mix_colours())):
            mixes.append({"index": i, "filament": n + 1 + i, "components": list(ids), "weights": list(ws), "colour": c})
        w = st["wipe"]
        return {
            "project": st["name"] or "(unsaved)",
            "bed": st["bed"],
            "plates": self.nplates(),
            "filaments": [{"filament": i + 1, **f} for i, f in enumerate(self.fil_info())],
            "mixes": mixes,
            "objects": objs,
            "off_bed": self.off_bed(),
            "wipe_tower": {
                "enabled": w["enabled"],
                "x": round(w["x"], 1),
                "y": round(w["y"], 1),
                "footprint": [round(v, 1) for v in w["fp"]],
            },
            "global_overrides": st["overrides"],
            "process": self.cfg.get("print_settings_id"),
            "last_slice": st["result"],
        }

    def mix_rows(self):
        """enabled mixes as normalized (ids, weights)"""
        return [parse_mix_row(r) for r in self.mixes()]

    def mix_colours(self, filaments=None, rows=None):
        fc = [f["colour"] for f in (filaments or self.st["filaments"])]
        return [colormix.recipe_colour(fc, ids, ws) for ids, ws in (rows if rows is not None else self.mix_rows())]

    def palette_colours(self):
        """colour of every filament id in the project: physical then mixes (1-based ids -> list index id-1)"""
        return [f["colour"] for f in self.st["filaments"]] + self.mix_colours()

    def used_ids(self, objs=None):
        """filament ids used by parts or paint -> {id: {"parts": n, "painted": bool}}"""
        used = {}
        for o in objs if objs is not None else self.st["objects"]:
            g = self.geos[o["gid"]]
            for p, e in zip(g["parts"], o["ext"]):
                if p.get("type", "normal_part") in ("normal_part", "modifier_part"):
                    used.setdefault(e, {"parts": 0, "painted": False})["parts"] += 1
                for code in p.get("paint") or []:
                    if code:
                        for s_ in paintree.used_states(code):
                            used.setdefault(s_, {"parts": 0, "painted": False})["painted"] = True
        return used

    def colour_plan(self, physical):
        """for every used model colour: ranked options on the target palette `physical` (list of hex)"""
        pal = self.palette_colours()
        used = self.used_ids()
        out = []
        for i in sorted(used):
            if i > len(pal):
                continue
            c = pal[i - 1]
            cands = colormix.candidates(c, physical)
            out.append(
                {
                    "id": i,
                    "colour": c.upper(),
                    **used[i],
                    "best": colormix.best(c, physical),
                    "options": [o for o in cands if o["kind"] == "phys"] + [o for o in cands if o["kind"] == "mix"][:6],
                }
            )
        return out

    def _remap(self, objs, f):
        """apply id mapping f to ext + paint of objs (new gids where paint changes)"""
        for o in objs:
            o["ext"] = [f(e) for e in o["ext"]]
            g = self.geos[o["gid"]]
            if any(p.get("paint") for p in g["parts"]):
                g = self.own_geo(o)
                for p in g["parts"]:
                    if p.get("paint"):
                        p["paint"] = [paintree.remap(c, f) if c else c for c in p["paint"]]

    def dedupe_mixes(self):
        """merge identical mixes (same components + weights) and remap parts/paint to the first one"""
        n = len(self.st["filaments"])
        rows = self.mix_rows()
        keep, new = [], {}
        for i, rec in enumerate(rows):
            if rec not in keep:
                keep.append(rec)
            new[n + 1 + i] = n + 1 + keep.index(rec)
        if len(keep) == len(rows):
            return "no duplicate mixes"
        self.st["mix"] = ";".join(encode_mix(*r_) for r_ in keep)
        self._remap(self.st["objects"], lambda e: new.get(e, e))
        return f"merged {len(rows) - len(keep)} duplicate mixes ({len(keep)} left)"

    def _mix_id(self, rows, rec):
        """id of recipe `rec` in rows (list of normalized recipes), appending it when new"""
        if rec not in rows:
            rows.append(rec)
        return len(self.st["filaments"]) + 1 + rows.index(rec)

    def mixes(self):
        return [x for x in self.st["mix"].split(";") if x and x.split(",")[2:3] != ["0"]]

    def thumb_tris(self, plate=None):
        """every visible solid triangle of the plate in world mm with its printed colour (paint leaves included)"""
        pal = self.palette_colours()
        col = lambda i: pal[i - 1] if 1 <= i <= len(pal) else "#888888"
        out = []
        for o in self.on_plate(plate) if plate else self.st["objects"]:
            m = o["m"]
            W = lambda v: (
                v[0] * m[0] + v[1] * m[3] + v[2] * m[6] + m[9],
                v[0] * m[1] + v[1] * m[4] + v[2] * m[7] + m[10],
                v[0] * m[2] + v[1] * m[5] + v[2] * m[8] + m[11],
            )
            for p, e in zip(self.geos[o["gid"]]["parts"], o["ext"]):
                if p.get("type", "normal_part") != "normal_part":
                    continue
                V = [W(v) for v in p["verts"]]
                paint = p.get("paint") or []
                for t, (a, b, c) in enumerate(p["tris"]):
                    code = paint[t] if t < len(paint) else None
                    if code:
                        for tri, st in paintree.leaves(paintree.decode(code), (V[a], V[b], V[c])):
                            out.append((*tri, col(st or e)))
                    else:
                        out.append((V[a], V[b], V[c], col(e)))
        return out

    # ---------- outputs
    def _build_obj(self, o):
        return {"gid": o["gid"], "name": o["name"], "m": o["m"], "ext": o["ext"], "cfg": o["cfg"], "pcfg": self.pcfg(o)}

    def _merged(self, olist):
        """objects flagged with a role stop being printed objects: each becomes a modifier/negative/... volume inside
        every other object
        (same plate, bbox overlap). -> (geos, build objects)"""
        geos = dict(self.geos)
        out = []
        mods = [o for o in olist if o.get("role")]
        for o in olist:
            if o.get("role"):
                continue
            b = self.bbox(o)
            b_ = [*b]
            extra = []
            for mo in mods:
                if mo.get("plate", 1) != o.get("plate", 1):
                    continue
                q = self.bbox(mo)
                if q[0] < b_[1] and q[1] > b_[0] and q[2] < b_[3] and q[3] > b_[2] and q[4] < b_[5] and q[5] > b_[4]:
                    extra.append(mo)
            bo = self._build_obj(o)
            if extra:
                g = self.geos[o["gid"]]
                parts = [dict(p) for p in g["parts"]]
                ext = list(o["ext"])
                pc = list(self.pcfg(o))
                for mo in extra:
                    m = mo["m"]
                    mg = self.geos[mo["gid"]]
                    for p, e in zip(mg["parts"], mo["ext"]):
                        if p.get("type", "normal_part") != "normal_part":
                            continue
                        W = [
                            (
                                x * m[0] + y * m[3] + z * m[6] + m[9],
                                x * m[1] + y * m[4] + z * m[7] + m[10],
                                x * m[2] + y * m[5] + z * m[8] + m[11],
                            )
                            for x, y, z in p["verts"]
                        ]
                        parts.append(dict(p, verts=self.to_local(o, W), type=mo["role"], name=mo["name"], paint=None))
                        ext.append(e)
                        pc.append({a: v for a, v in mo["cfg"].items() if a in threemf.OBJ_SETTINGS})
                gid = f"m{o['id']}"
                geos[gid] = dict(g, parts=parts)
                bo.update(gid=gid, ext=ext, pcfg=pc)
            out.append(bo)
        return geos, out

    def build(self, plate=None):
        """plate=None: the whole project as a multi-plate Orca 3MF (save); plate=p: just that plate, "
        "plate-local (slicing)"""
        if plate is not None:
            geos, objs = self._merged(self.on_plate(plate))
            w = self.st["wipe"]
            return threemf.build(
                self.cfg,
                geos,
                objs,
                {"x": w["x"], "y": w["y"]} if w["enabled"] else None,
                self.st["mix"],
                self.st["overrides"],
            )
        geos, objs = self._merged(self.st["objects"])
        objs = [
            dict(b, plate=o.get("plate", 1)) for b, o in zip(objs, [o for o in self.st["objects"] if not o.get("role")])
        ]
        w = self.st["wipe"]
        return threemf.build(
            self.cfg,
            geos,
            objs,
            {"x": w["x"], "y": w["y"]} if w["enabled"] else None,
            self.st["mix"],
            self.st["overrides"],
            plates=self.nplates(),
        )

    def save(self, name):
        with self.lock:
            name = re.sub(r"[^\w.-]+", "_", name or self.st["name"] or "project").strip("._") or "project"
            dst = self.art / "u1web" / f"{name}.3mf"
            dst.parent.mkdir(exist_ok=True)
            dst.write_bytes(self.build())
            self.st["name"] = name
            self._commit(record=False)
            return str(dst.relative_to(self.art))

    def after_slice(self, res, gcode, store=True):
        """per plate (store=False): preview data + learn the real wipe tower footprint from the G-code; "
        "store=True: keep the result"""
        with self.lock:
            if gcode is not None and res.get("ok"):
                meta, b = gcodeprev.parse(gcode)
                import gzip

                (gcode.parent / "preview.json").write_text(json.dumps(meta))
                (gcode.parent / "preview.bin.gz").write_bytes(gzip.compress(b, 5))
                w = self.st["wipe"]
                if meta.get("tower") and w["enabled"]:
                    t = meta["tower"]
                    w["fp"] = [t[0] - w["x"], t[1] - w["x"], t[2] - w["y"], t[3] - w["y"]]
            if store:
                self.st["result"] = res
                self._commit(record=False)
