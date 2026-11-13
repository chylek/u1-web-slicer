"""Snapmaker U1 over Moonraker (LAN, no API key): status, loaded filaments (RFID), G-code upload / start, camera.
Host: env U1_HOST (config.py); every call raises OSError while it is unset."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

import config

HOST = config.PRINTER_HOST
BUSY = ("printing", "paused")


def _get(path, timeout=5):
    if not HOST:
        raise OSError("U1_HOST is not set (printer address, e.g. 192.168.1.10:7125)")
    with urllib.request.urlopen(f"http://{HOST}{path}", timeout=timeout) as r:
        return json.loads(r.read())["result"]


def status():
    q = _get(
        "/printer/objects/query?print_stats&virtual_sdcard&print_task_config&extruder&extruder1&extruder2&extruder3&heater_bed&temperature_sensor%20cavity"
    )["status"]
    ps, ptc = q.get("print_stats", {}), q.get("print_task_config", {})
    n = len(ptc.get("filament_type", []))
    fil = [
        {
            "filament": i + 1,
            "type": ptc["filament_type"][i],
            "sub_type": (ptc.get("filament_sub_type") or [""] * n)[i],
            "vendor": (ptc.get("filament_vendor") or [""] * n)[i],
            "colour": "#" + ptc["filament_color_rgba"][i][:6].upper(),
            "loaded": (ptc.get("filament_exist") or [True] * n)[i],
        }
        for i in range(n)
    ]
    info = ps.get("info") or {}
    temps = {
        k: round(q[k]["temperature"])
        for k in ("extruder", "extruder1", "extruder2", "extruder3", "heater_bed")
        if k in q and "temperature" in q[k]
    }
    cav = (q.get("temperature_sensor cavity") or {}).get("temperature")
    if cav is not None:
        temps["chamber"] = round(cav)
    prog = (q.get("virtual_sdcard") or {}).get("progress", 0)
    remaining = _remaining(ps.get("filename"), ps.get("print_duration") or 0, prog) if ps.get("state") in BUSY else None
    return {
        "host": HOST,
        "remaining_s": remaining,
        "state": ps.get("state", "unknown"),
        "file": ps.get("filename") or None,
        "progress": round(100 * (q.get("virtual_sdcard") or {}).get("progress", 0), 1),
        "layer": [info.get("current_layer"), info.get("total_layer")],
        "temps": temps,
        "filaments": fil,
    }


_est = {}  # filename -> slicer estimate (s)


def _remaining(fn, done, prog):
    """seconds left: slicer estimate early on, file-progress extrapolation later (it's skewed by slow/fast sections).
    ponytail: linear blend by progress, like Mainsail; per-layer times from the G-code would be more exact."""
    if fn and fn not in _est:
        try:
            _est[fn] = _get("/server/files/metadata?filename=" + urllib.parse.quote(fn)).get("estimated_time")
        except (OSError, ValueError):
            _est[fn] = None
    est = _est.get(fn)
    by_slicer = max(est - done, 0) if est else None
    by_file = done / prog - done if prog > 0.01 else None
    if by_slicer is None:
        return None if by_file is None else round(by_file)
    if by_file is None:
        return round(by_slicer)
    return round((1 - prog) * by_slicer + prog * by_file)


def exists(name):
    try:
        _get("/server/files/metadata?filename=" + urllib.parse.quote(name))
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def upload(path, name, start=False):
    """multipart POST /server/files/upload; start=True asks Moonraker to print it right away"""
    if start:
        st = status()["state"]
        if st in BUSY:
            raise ValueError(f"printer is {st} — not starting a new print (upload without start, or wait)")
    b = uuid.uuid4().hex
    body = (
        (
            f'--{b}\r\nContent-Disposition: form-data; name="root"\r\n\r\ngcodes\r\n'
            + (f'--{b}\r\nContent-Disposition: form-data; name="print"\r\n\r\ntrue\r\n' if start else "")
            + f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            + "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + open(path, "rb").read()
        + f"\r\n--{b}--\r\n".encode()
    )
    req = urllib.request.Request(
        f"http://{HOST}/server/files/upload",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={b}"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.loads(r.read())
    return {
        "ok": True,
        "file": res.get("item", {}).get("path", name),
        "started": bool(res.get("print_started")),
        "queued": bool(res.get("print_queued")),
    }


def _ws_send(path, text, timeout=5):
    """minimal stdlib WebSocket client: handshake, send one masked text frame, close"""
    import base64
    import socket

    host, _, port = HOST.partition(":")
    s = socket.create_connection((host, int(port or 80)), timeout=timeout)
    try:
        s.sendall(
            (
                f"GET {path} HTTP/1.1\r\nHost: {HOST}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {base64.b64encode(os.urandom(16)).decode()}\r\nSec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        head = s.recv(4096)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise RuntimeError("websocket refused: " + head.split(b"\r\n")[0].decode())
        d = text.encode()
        mask = os.urandom(4)
        assert len(d) < 126
        s.sendall(bytes([0x81, 0x80 | len(d)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(d)))
        s.settimeout(1)
        try:
            s.recv(4096)  # let the printer process it
        except OSError:
            pass
        s.sendall(b"\x88\x80" + os.urandom(4))
    finally:
        s.close()


_last_wake = 0


def camera_wake():
    """The stock camera only refreshes monitor.jpg while a client keeps calling camera.start_monitor
    (what the Snapmaker app does). Call every <=10 s."""
    tok = _get("/access/oneshot_token")
    _ws_send(
        f"/websocket?token={tok}",
        json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": "camera.start_monitor", "params": {"domain": "lan", "interval": 0}}
        ),
    )


def camera_frame():
    with urllib.request.urlopen(f"http://{HOST}/server/files/camera/monitor.jpg", timeout=5) as r:
        return r.read()


if __name__ == "__main__":  # self-check of the ETA blend
    _est["t"] = 1000
    assert _remaining("t", 0, 0) == 1000  # nothing printed: slicer estimate
    assert _remaining("t", 500, 0.5) == 500  # on schedule: both agree
    assert _remaining("t", 900, 0.9) == round(0.1 * 100 + 0.9 * 100)
    assert _remaining("t", 200, 0.1) == round(0.9 * 800 + 0.1 * 1800)  # slower than sliced: drifts later
    _est["n"] = None
    assert _remaining("n", 100, 0.5) == 100 and _remaining("n", 0, 0) is None
    print("eta ok", status().get("remaining_s"))
