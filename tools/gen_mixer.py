#!/usr/bin/env python3
"""Extract FilamentMixer (MIT, Justin Hayes; shipped in Snapmaker Orca as src/libslic3r/filament_mixer_model.h)
polynomial
coefficients -> static/mixer.json.  Usage: python3 tools/gen_mixer.py ~/src/snapmaker-orca"""

import json
import re
import sys
from pathlib import Path

src = (
    Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "src/snapmaker-orca")
    / "src/libslic3r/filament_mixer_model.h"
)
h = src.read_text()
block = lambda name: h[h.index(name) : h.index("};", h.index(name))]
nums = lambda s: [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:e[-+]?\d+)?", s.split("=", 1)[1])]
powers = [int(x) for x in nums(block("POWERS[330][7]"))]
coef = nums(block("COEF[330][3]"))
icpt = nums(block("INTERCEPT[3]"))
assert len(powers) == 330 * 7 and len(coef) == 330 * 3 and len(icpt) == 3
json.dump(
    {
        "license": "MIT (c) 2026 Justin Hayes - FilamentMixer polynomial pigment mixing "
        "(approximates Mixbox, mean dE ~2.07)",
        "powers": [powers[i * 7 : i * 7 + 7] for i in range(330)],
        "coef": [coef[i * 3 : i * 3 + 3] for i in range(330)],
        "intercept": icpt,
    },
    open(Path(__file__).resolve().parents[1] / "static/mixer.json", "w"),
)
print("ok")
