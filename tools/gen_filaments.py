#!/usr/bin/env python3
"""Snapmaker Orca filament presets for the U1 0.4 nozzle -> static/filaments.json {name: {key: [values]}}
(inherits resolved; only keys a U1 project stores per filament).
Usage: python3 tools/gen_filaments.py ~/src/snapmaker-orca"""

import json
import sys
from pathlib import Path

root = (
    Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "src/snapmaker-orca")
    / "resources/profiles/Snapmaker/filament"
)
REPO = Path(__file__).resolve().parents[1]
by_name = {}
for f in root.glob("*.json"):
    d = json.loads(f.read_text(encoding="utf-8-sig"))
    by_name[d.get("name", f.stem)] = d
# keys a project keeps per filament = list options of a real U1 project (4 filaments, flow-interleaved or not)
proj = json.loads((REPO / "base_project_settings.config").read_text())
keys = {k for k, v in proj.items() if isinstance(v, list) and len(v) in (4, 7)}


def resolved(name, seen=()):
    d = by_name[name]
    base = resolved(d["inherits"], seen + (name,)) if d.get("inherits") in by_name and name not in seen else {}
    return {**base, **d}


keys &= {k for n in by_name for k in resolved(n)} - {"compatible_printers", "inherits"}
out = {}
for name, d in sorted(by_name.items()):
    if d.get("instantiation") != "true" or "Snapmaker U1 (0.4 nozzle)" not in d.get("compatible_printers", []):
        continue
    r = resolved(name)
    v = {k: (x if isinstance(x, list) else [x]) for k, x in r.items() if k in keys}
    v["filament_settings_id"] = [name]
    v["filament_ids"] = [r.get("setting_id") or r.get("filament_id", "")]  # projects store the setting id here
    out[name] = v
json.dump(out, open(REPO / "static/filaments.json", "w"), indent=0)
print(len(out), "filaments,", len(keys), "keys:", ", ".join(out))
