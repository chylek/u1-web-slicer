#!/usr/bin/env python3
"""Snapmaker Orca U1 (0.4 nozzle) process presets -> static/presets.json {name: {setting: value}} (inherits resolved,
only settings in the UI schema, per-nozzle lists collapsed). Usage: python3 tools/gen_presets.py ~/src/snapmaker-orca"""

import json
import sys
from pathlib import Path

root = (
    Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "src/snapmaker-orca")
    / "resources/profiles/Snapmaker/process"
)
REPO = Path(__file__).resolve().parents[1]
schema = json.loads((REPO / "static/schema.json").read_text())["opts"]
by_name = {}
for f in root.glob("*.json"):
    d = json.loads(f.read_text(encoding="utf-8-sig"))
    by_name[d.get("name", f.stem)] = d


def resolved(name, seen=()):
    d = by_name[name]
    base = (
        resolved(d["inherits"], seen + (name,))
        if d.get("inherits") and d["inherits"] in by_name and name not in seen
        else {}
    )
    return {**base, **d}


out = {}
for name, d in sorted(by_name.items()):
    if "U1" not in name or "0.4 nozzle" not in name or d.get("instantiation") != "true":
        continue
    r = resolved(name)
    out[name.replace(" @Snapmaker U1 (0.4 nozzle)", "")] = {
        k: (v[0] if isinstance(v, list) else v) for k, v in r.items() if k in schema and not isinstance(v, dict)
    }
json.dump(out, open(REPO / "static/presets.json", "w"), indent=1)
print(len(out), "presets:", ", ".join(out))
