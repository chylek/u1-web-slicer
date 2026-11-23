"""The slice path converts a foreign-printer project to U1 settings and says so (Orca would answer -51)."""

import importlib
import sys


def test_slice_converts_foreign_printer_and_warns(tmp_path, monkeypatch):
    monkeypatch.setenv("U1WEB_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("U1WEB_MODELS", str(tmp_path / "models"))
    for m in ("config", "server"):
        sys.modules.pop(m, None)
    server = importlib.import_module("server")
    try:
        S = server.S
        S.op({"op": "add_primitive", "shape": "box", "size": [10, 10, 10]})
        S.cfg = dict(S.cfg, printer_model="Bambu Lab A1 mini")
        monkeypatch.setattr(
            server, "slice_plate", lambda p: ({"plate": p, "ok": True, "seconds": 1, "time": "1m 0s"}, None)
        )
        res = server._do_slice()
        assert S.cfg["printer_model"] == "Snapmaker U1"
        assert "converted from Bambu Lab A1 mini" in (res.get("warning") or ""), res
        assert "converted from" in (S.st["result"].get("warning") or "")
    finally:
        for m in ("config", "server"):
            sys.modules.pop(m, None)
