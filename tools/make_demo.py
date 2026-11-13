#!/usr/bin/env python3
"""Build examples/demo-cube.3mf: a 30 mm cube on the default U1 filaments (1 white, 2 black, 3 yellow, 4 red),
white body, yellow top, red front and an orange right side mixed from yellow + red (Full Spectrum).
Usage: python3 tools/make_demo.py"""

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import session  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    s = session.Session(Path(tmp) / "data", Path(tmp) / "models")
    s.op({"op": "add_primitive", "shape": "box", "size": [30, 30, 30], "name": "Demo cube", "ext": 1})
    orange = s.op({"op": "mix_add", "ids": [3, 4], "weights": [60, 40]})
    mix_id = len(s.st["filaments"]) + 1
    for facing, filament in (("up", 3), ("-y", 4), ("+x", mix_id)):
        s.op({"op": "paint_region", "id": "o1", "filament": filament, "facing": facing, "max_angle": 10})
    s.op({"op": "arrange"})
    out = ROOT / "examples/demo-cube.3mf"
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(s.build())
    print("wrote", out.relative_to(ROOT), "-", orange["msg"])
