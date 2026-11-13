#!/usr/bin/env python3
"""MCP server (stdio, stdlib only) for the U1 web slicer: drives the same single global session the browser shows
(server.py on :3060), so every change is live in the phone UI.  Register: .mcp.json -> "u1web"."""

import json
import sys
import urllib.request
from pathlib import Path

import config

API = config.URL
SCHEMA = json.loads((Path(__file__).parent / "static/schema.json").read_text())


def ensure_server():
    """start server.py if nothing answers at U1WEB_URL (a systemd unit is optional); log goes to <data>/server.log"""
    import subprocess
    import time

    config.DATA.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [sys.executable, str(Path(__file__).parent / "server.py")],
        cwd=Path(__file__).parent,
        start_new_session=True,
        stdout=open(config.DATA / "server.log", "a"),
        stderr=subprocess.STDOUT,
    )
    time.sleep(2)


def http(path, body=None, retry=True):
    req = urllib.request.Request(
        API + path, data=None if body is None else json.dumps(body).encode(), method="GET" if body is None else "POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}") or {"error": str(e)}
    except urllib.error.URLError:
        if not retry:
            raise
        ensure_server()
        return http(path, body, retry=False)


def op(**kw):
    r = http("/api/op", kw)
    if r.get("error"):
        raise ValueError(r["error"])
    return r


def part_index(obj, part):
    if part is None or isinstance(part, int):
        return part
    if str(part).isdigit():
        return int(part)
    o = next((o for o in http("/api/summary")["objects"] if obj in (o["id"], o["name"])), None)
    hit = [p["index"] for p in (o or {"parts": []})["parts"] if p["name"].lower() == str(part).lower()]
    if not hit:
        raise ValueError(f"part '{part}' not found in '{obj}'")
    return hit[0]


def map_colours(source, overrides):
    plan = http(f"/api/colours/plan?source={source}")
    if plan.get("error"):
        raise ValueError(plan["error"])
    choice = {str(t["id"]): t["best"] for t in plan["targets"]}
    choice.update({str(k): v for k, v in overrides.items()})
    if source == "printer":
        fil = [{"colour": f["colour"], "type": f["type"]} for f in http("/api/printer")["filaments"]]
    else:
        fil = [{"colour": c} for c in plan["physical"]]
    return op(op="apply_colour_map", filaments=fil, map=choice)


def find_settings(query, per_object=False, limit=25):
    q = query.lower()
    st = http("/api/state")
    out = []
    for pg in SCHEMA["pages"]:
        for gr in pg["groups"]:
            for k in gr["opts"]:
                o = SCHEMA["opts"][k]
                if per_object and not o["obj"]:
                    continue
                if q in " ".join([k, o["label"], o["tip"], pg["name"], gr["name"]]).lower():
                    out.append(
                        {
                            "key": k,
                            "label": o["label"],
                            "section": f"{pg['name']} / {gr['name']}",
                            "type": o["type"],
                            "unit": o["side"],
                            "options": [e[0] for e in o["enum"]] if o["enum"] else None,
                            "per_object": o["obj"],
                            "level": "advanced" if o["adv"] else "basic",
                            "value": st["overrides"].get(k, st["settings"].get(k)),
                            "help": o["tip"][:300],
                        }
                    )
    return out[:limit] or f"no setting matches '{query}'"


def filament_presets(t=None):
    d = http("/api/filaments")
    return [
        {
            "name": n,
            "type": v["filament_type"][0],
            "nozzle": v["nozzle_temperature"][0],
            "bed": v["hot_plate_temp"][0],
            "max_flow": v["filament_max_volumetric_speed"][0],
            "user": v.get("user", False),
        }
        for n, v in d.items()
        if not t or v["filament_type"][0].lower() == t.lower()
    ]


OBJ = {"type": "string", "description": "object id (o3) or exact name"}
PLATE = {"type": "integer", "description": "plate number, 1-based"}
TOOLS = {
    "get_scene": (
        "Current session: project, filaments, mixes, objects (id, name, parts+filament, position, size, "
        "rotation, scale, per-object overrides), wipe tower, global overrides, last slice result.",
        {},
        lambda a: http("/api/summary"),
    ),
    "list_files": (
        "3MF/STL files in the models folder (paths usable in open_project / add_model).",
        {},
        lambda a: http("/api/files"),
    ),
    "open_project": (
        "Open a 3MF from the models folder (replaces the session).",
        {"path": {"type": "string"}},
        lambda a: http("/api/open", {"path": a["path"]}),
    ),
    "new_project": ("Start an empty Snapmaker U1 project (4 filaments).", {}, lambda a: http("/api/new", {})),
    "add_model": (
        "Add an STL/3MF/ZIP (path in the models folder, or absolute) to a plate (default 1); auto-arranges. A "
        "zip is unpacked into <models>/uploads/<name>/ (STL/3MF only; the reply lists `ignored` files) and a "
        "zip inside the models folder is then deleted.",
        {"path": {"type": "string"}, "plate": PLATE},
        lambda a: http("/api/add_path", {"path": a["path"], "plate": a.get("plate")}),
    ),
    "list_filament_presets": (
        "Orca filament presets for the U1 (name, type, nozzle/bed °C, max flow). Optional type filter (PLA, "
        "PETG, TPU, ABS...).",
        {"type": {"type": "string"}},
        lambda a: filament_presets(a.get("type")),
    ),
    "set_filament_preset": (
        "Load an Orca filament preset (see list_filament_presets) into a project filament slot 1-4: type, "
        "temperatures, "
        "speeds/flow, retraction, cooling. Sync from the printer does this automatically when the loaded "
        "material differs.",
        {"filament": {"type": "integer"}, "preset": {"type": "string"}},
        lambda a: op(op="set_filament_preset", filament=a["filament"], preset=a["preset"]),
    ),
    "set_filament_temps": (
        "Override a filament slot's nozzle and/or bed temperature in °C (all layers), and/or any other filament "
        "setting "
        "via values {key: value} (e.g. filament_max_volumetric_speed, filament_flow_ratio, filament_retraction_length, "
        "filament_retraction_speed, fan_min_speed, fan_max_speed).",
        {
            "filament": {"type": "integer"},
            "nozzle": {"type": "integer"},
            "bed": {"type": "integer"},
            "values": {"type": "object"},
        },
        lambda a: op(
            op="set_filament_values",
            filament=a["filament"],
            nozzle=a.get("nozzle"),
            bed=a.get("bed"),
            values=a.get("values"),
        ),
    ),
    "save_filament_preset": (
        "Save a project filament slot (with its tweaks) as the user's own filament preset `name` (reusable via "
        "set_filament_preset).",
        {"filament": {"type": "integer"}, "name": {"type": "string"}},
        lambda a: http("/api/filaments/save", {"filament": a["filament"], "name": a["name"]}),
    ),
    "set_filament": (
        "Assign a filament (1-based; mixes continue after the physical ones) to an object, or to one part "
        "(index or name).",
        {"object": OBJ, "filament": {"type": "integer"}, "part": {"type": ["integer", "string"]}},
        lambda a: op(op="set_ext", id=a["object"], ext=a["filament"], part=part_index(a["object"], a.get("part"))),
    ),
    "transform_object": (
        "Absolute placement: x/y of the bbox centre and z = bottom height in mm (0 = on the bed; omitted = unchanged), "
        "rotation in degrees (number = about Z, or [x, y, z] with R = Rz·Ry·Rx), scale in % (number = uniform, "
        "or [x, y, z] along the object's own axes), "
        "optional rename. Orca refuses to slice an object floating above the bed.",
        {
            "object": OBJ,
            "x": {"type": "number"},
            "y": {"type": "number"},
            "z": {"type": "number"},
            "rotation": {"type": ["number", "array"], "items": {"type": ["number", "null"]}},
            "scale": {"type": ["number", "array"], "items": {"type": ["number", "null"]}},
            "name": {"type": "string"},
        },
        lambda a: op(
            op="set_object",
            id=a["object"],
            x=a.get("x"),
            y=a.get("y"),
            z=a.get("z"),
            rot=a.get("rotation"),
            scale=a.get("scale"),
            name=a.get("name"),
        ),
    ),
    "duplicate_object": (
        "Make copies of an object, then auto-arrange.",
        {"object": OBJ, "count": {"type": "integer", "default": 1}},
        lambda a: op(op="dup", id=a["object"], count=a.get("count", 1)),
    ),
    "delete_object": ("Remove an object from the plate.", {"object": OBJ}, lambda a: op(op="del", id=a["object"])),
    "arrange": (
        "Auto-arrange one plate's objects around the bed centre (default plate 1), or all=true to repack every "
        "object onto as few plates as needed "
        "(objects that don't fit spill onto new plates). Places the wipe tower next to them.",
        {"plate": PLATE, "all": {"type": "boolean", "default": False}},
        lambda a: op(op="arrange", all=True) if a.get("all") else op(op="arrange", plate=a.get("plate", 1)),
    ),
    "set_plate": (
        "Move an object to another plate (plates+1 creates a new plate); it is placed in a free spot there.",
        {"object": OBJ, "plate": PLATE},
        lambda a: op(op="set_plate", id=a["object"], plate=a["plate"]),
    ),
    "add_plate": ("Add an empty plate.", {}, lambda a: op(op="add_plate")),
    "delete_plate": (
        "Delete a plate AND its objects; higher plates shift down.",
        {"plate": PLATE},
        lambda a: op(op="del_plate", plate=a["plate"]),
    ),
    "set_wipe_tower": (
        "Move the wipe (prime) tower; x/y = Orca wipe_tower_x/y (its real footprint is in get_scene).",
        {"x": {"type": "number"}, "y": {"type": "number"}},
        lambda a: op(op="set_wipe", x=a["x"], y=a["y"]),
    ),
    "find_settings": (
        "Search the Orca print settings (label, key, section, help text) and show current values plus "
        "basic/advanced level. Use before set_settings.",
        {"query": {"type": "string"}, "per_object": {"type": "boolean", "default": False}},
        lambda a: find_settings(a["query"], a.get("per_object", False)),
    ),
    "set_settings": (
        "Set print settings by key. Without 'object' they are global (project); with 'object' they are "
        "per-object overrides. Value null resets to the inherited value. Percent values like '15%'.",
        {"settings": {"type": "object", "description": "{key: value|null}"}, "object": OBJ},
        lambda a: (
            op(op="set_object_settings", id=a["object"], settings=a["settings"])
            if a.get("object")
            else op(op="set_global", settings=a["settings"])
        ),
    ),
    "add_mix": (
        "Create a Full-Spectrum mixed (virtual) filament from 2-4 physical filaments: either a + b + percent_b, or "
        "components [ids] + weights [%]. Layers alternate between them. Returns its filament number.",
        {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
            "percent_b": {"type": "integer", "default": 50},
            "components": {"type": "array", "items": {"type": "integer"}},
            "weights": {"type": "array", "items": {"type": "integer"}},
        },
        lambda a: (
            op(op="mix_add", ids=a["components"], weights=a.get("weights") or [1] * len(a["components"]))
            if a.get("components")
            else op(op="mix_add", a=a["a"], b=a["b"], pct=a.get("percent_b", 50))
        ),
    ),
    "remove_mix": (
        "Delete a mix by its index (see get_scene.mixes); parts using it fall back to filament a.",
        {"index": {"type": "integer"}},
        lambda a: op(op="mix_del", index=a["index"]),
    ),
    "add_primitive": (
        "Add a new object: box, cylinder or sphere with size [x, y, z] mm (default 20 mm), optional position "
        "and filament.",
        {
            "shape": {"type": "string", "enum": ["box", "cylinder", "sphere"]},
            "size": {"type": "array", "items": {"type": "number"}},
            "x": {"type": "number"},
            "y": {"type": "number"},
            "filament": {"type": "integer"},
            "name": {"type": "string"},
            "plate": PLATE,
        },
        lambda a: (
            op(
                op="add_primitive",
                shape=a.get("shape", "box"),
                size=a.get("size", [20, 20, 20]),
                x=a.get("x"),
                y=a.get("y"),
                ext=a.get("filament", 1),
                name=a.get("name"),
                plate=a.get("plate"),
            )
            if a.get("x") is not None
            else op(
                op="add_primitive",
                shape=a.get("shape", "box"),
                size=a.get("size", [20, 20, 20]),
                ext=a.get("filament", 1),
                name=a.get("name"),
                plate=a.get("plate"),
            )
        ),
    ),
    "add_part": (
        "Add a box/cylinder/sphere volume to an object: kind = modifier (own settings via set_part), negative "
        "(subtracts), part (adds solid), "
        "support_blocker or support_enforcer. size [x,y,z] mm (default 60 % of the object), x/y = centre, z = "
        "bottom (world mm; default centred).",
        {
            "object": OBJ,
            "kind": {"type": "string", "enum": ["modifier", "negative", "part", "support_blocker", "support_enforcer"]},
            "shape": {"type": "string", "enum": ["box", "cylinder", "sphere"]},
            "size": {"type": "array", "items": {"type": "number"}},
            "x": {"type": "number"},
            "y": {"type": "number"},
            "z": {"type": "number"},
            "filament": {"type": "integer"},
        },
        lambda a: op(
            op="add_part",
            id=a["object"],
            **{
                k: v
                for k, v in {
                    "kind": a.get("kind"),
                    "shape": a.get("shape"),
                    "size": a.get("size"),
                    "x": a.get("x"),
                    "y": a.get("y"),
                    "z": a.get("z"),
                    "ext": a.get("filament"),
                }.items()
                if v is not None
            },
        ),
    ),
    "set_part": (
        "Per-part settings (e.g. a modifier's infill), filament or name. settings replaces the part's overrides "
        "({} clears).",
        {
            "object": OBJ,
            "part": {"type": ["integer", "string"]},
            "settings": {"type": "object"},
            "filament": {"type": "integer"},
            "name": {"type": "string"},
        },
        lambda a: op(
            op="set_part",
            id=a["object"],
            part=part_index(a["object"], a["part"]),
            **{
                k: v
                for k, v in {"cfg": a.get("settings"), "ext": a.get("filament"), "name": a.get("name")}.items()
                if v is not None
            },
        ),
    ),
    "remove_part": (
        "Delete a part/modifier from an object (not the last solid part).",
        {"object": OBJ, "part": {"type": ["integer", "string"]}},
        lambda a: op(op="del_part", id=a["object"], part=part_index(a["object"], a["part"])),
    ),
    "paint_region": (
        "Paint triangles of an object by rule (no clicking): every given selector must match. World mm (see "
        "get_scene centre/size). "
        "filament 0 = erase. Selectors: z_min/z_max, x_min/x_max, y_min/y_max; facing "
        "'up'|'down'|'side'|'+x'|'-x'|'+y'|'-y' or [x,y,z] "
        "with max_angle (deg, default 45); sphere {center:[x,y,z], radius}; box {min:[..], max:[..]}; "
        "inside_part (index/name, e.g. a modifier "
        "volume, uses its bounding box). The mesh is never changed: like Orca, triangles crossing the region "
        "border get a paint tree split "
        "down to `detail` mm (default 0.5), so borders are sharp even on coarse meshes.",
        {
            "object": OBJ,
            "filament": {"type": "integer"},
            "part": {"type": ["integer", "string"]},
            "z_min": {"type": "number"},
            "z_max": {"type": "number"},
            "x_min": {"type": "number"},
            "x_max": {"type": "number"},
            "y_min": {"type": "number"},
            "y_max": {"type": "number"},
            "facing": {"type": ["string", "array"]},
            "max_angle": {"type": "number"},
            "sphere": {"type": "object"},
            "box": {"type": "object"},
            "inside_part": {"type": ["integer", "string"]},
            "detail": {"type": "number"},
        },
        lambda a: op(op="paint_region", id=a.pop("object"), **a),
    ),
    "printer_status": (
        "Snapmaker U1 status via Moonraker: state, current file/progress/layer, temperatures and the loaded "
        "filaments (RFID type/colour per head).",
        {},
        lambda a: http("/api/printer"),
    ),
    "sync_printer_colours": (
        "Set the project's filament colours to what is loaded in the U1 (undoable). Reports type mismatches.",
        {},
        lambda a: http("/api/printer/sync", {}),
    ),
    "send_to_printer": (
        "Upload the last sliced G-code of `plate` (default: first sliced plate; each plate is its own G-code, "
        "printed one after another) to the U1 as `name` (.gcode added). If the file exists you get "
        "{exists:true} — ask, then repeat with overwrite=true. If the plate changed since slicing you get "
        "{stale:true}: slice again (stale_ok=true sends the old G-code anyway). start=true also starts printing "
        "(refused while the printer is printing/paused) — "
        "only start when the user explicitly asked to print now.",
        {
            "start": {"type": "boolean", "default": False},
            "plate": PLATE,
            "name": {"type": "string"},
            "overwrite": {"type": "boolean", "default": False},
            "stale_ok": {"type": "boolean", "default": False},
        },
        lambda a: http(
            "/api/printer/send",
            {
                "start": bool(a.get("start")),
                "plate": a.get("plate"),
                "name": a.get("name"),
                "overwrite": bool(a.get("overwrite")),
                "stale_ok": bool(a.get("stale_ok")),
            },
        ),
    ),
    "colour_plan": (
        "How the project's colours would map onto a palette (source 'printer' = loaded filaments, 'project' = "
        "current): "
        "per used colour the best option (filament or Full Spectrum mix with dE) and alternatives.",
        {"source": {"type": "string", "enum": ["printer", "project"], "default": "printer"}},
        lambda a: http(f"/api/colours/plan?source={a.get('source', 'printer')}"),
    ),
    "map_colours": (
        "Recolour the whole scene onto the printer's loaded filaments (or project palette): uses the best "
        "option per colour "
        "unless overrides {old_id: {kind:'phys', ext} | {kind:'mix', a, b, pct}} are given. Creates needed "
        "mixes, remaps parts + paint. Undoable.",
        {
            "source": {"type": "string", "enum": ["printer", "project"], "default": "printer"},
            "overrides": {"type": "object"},
        },
        lambda a: map_colours(a.get("source", "printer"), a.get("overrides") or {}),
    ),
    "replace_colour": (
        "Replace every use of filament `from` (painted areas and part colour) by filament `to` (physical or mix "
        "id), in one object (`object`) or the whole scene. Undoable.",
        {"from": {"type": "integer"}, "to": {"type": "integer"}, "object": {"type": "string"}},
        lambda a: op(
            op="replace_colour",
            **{"from": a["from"], "to": a["to"], **({"id": a["object"]} if a.get("object") else {})},
        ),
    ),
    "mixable_colours": (
        "Distinct colours that can be mixed from the current filaments (a, b, pct) — add one with add_mix.",
        {},
        lambda a: http("/api/colours/palette"),
    ),
    "list_profiles": (
        "Print-setting profiles: global (Orca U1 presets + saved ones; 'active' = last applied) and object "
        "profiles (favourite per-object overrides).",
        {},
        lambda a: http("/api/profiles"),
    ),
    "apply_profile": (
        "Apply a profile. kind 'global' replaces the project-level print settings; kind 'object' merges into "
        "one object's settings (or one part's with `part`). "
        "Filament colours/assignments are never part of a profile.",
        {
            "name": {"type": "string"},
            "kind": {"type": "string", "enum": ["global", "object"], "default": "global"},
            "object": OBJ,
            "part": {"type": ["integer", "string"]},
        },
        lambda a: op(
            op="apply_profile",
            kind=a.get("kind", "global"),
            name=a["name"],
            id=a.get("object"),
            part=part_index(a["object"], a.get("part")) if a.get("part") is not None else None,
        ),
    ),
    "save_profile": (
        "Save the current global print settings (kind 'global') or an object's own settings (kind 'object', "
        "needs object) as a named profile.",
        {
            "name": {"type": "string"},
            "kind": {"type": "string", "enum": ["global", "object"], "default": "global"},
            "object": OBJ,
        },
        lambda a: http(
            "/api/profiles/save", {"kind": a.get("kind", "global"), "name": a["name"], "id": a.get("object")}
        ),
    ),
    "undo": (
        "Undo the last change in the shared session (browser + MCP edits share one history).",
        {},
        lambda a: http("/api/undo", {}),
    ),
    "redo": ("Redo the last undone change.", {}, lambda a: http("/api/redo", {})),
    "history": (
        "Recent history entries (newest first; 'undone' ones can be redone).",
        {"n": {"type": "integer", "default": 20}},
        lambda a: http(f"/api/history?n={int(a.get('n', 20))}"),
    ),
    "checkout_object": (
        "Lock an object and export it as a single-object Orca 3MF for external editing (geometry, parts with subtypes, "
        "per-triangle paint_color = Orca code: filament 1 '4', 2 '8', 3 '0C', 4 '1C', 5 '2C'...). Returns path "
        "+ token. "
        "While locked the UI/other ops can't change it. Edit the file in place (keep it one object), then "
        "checkin_object.",
        {"object": OBJ},
        lambda a: op(op="checkout", id=a["object"], by="MCP"),
    ),
    "checkin_object": (
        "Replace the checked-out object's geometry/parts/paint from the (edited) 3MF and unlock it. Position, "
        "object settings, "
        "part settings (matched by part name) stay; filaments come from the file. path defaults to the checkout file.",
        {
            "object": OBJ,
            "token": {"type": "string"},
            "path": {"type": "string"},
            "use_file_transform": {"type": "boolean", "default": False},
        },
        lambda a: op(
            op="checkin",
            id=a["object"],
            token=a["token"],
            path=a.get("path"),
            use_file_transform=a.get("use_file_transform", False),
        ),
    ),
    "release_object": (
        "Unlock a checked-out object without changes (token, or force=true to break someone else's lock).",
        {"object": OBJ, "token": {"type": "string"}, "force": {"type": "boolean", "default": False}},
        lambda a: op(op="release", id=a["object"], token=a.get("token"), force=a.get("force", False)),
    ),
    "slice": (
        "Slice with Snapmaker Orca (20-60 s per plate): every plate with objects, or just `plate`. Returns "
        "totals plus `plates` (per plate: time, grams, G-code URL or error).",
        {"plate": PLATE},
        lambda a: http("/api/slice", {"plate": a.get("plate")}),
    ),
    "save_project": (
        "Save the session as <models>/u1web/<name>.3mf (opens in Orca too).",
        {"name": {"type": "string"}},
        lambda a: http("/api/save", {"name": a.get("name")}),
    ),
}
REQUIRED = {
    "apply_profile": ["name"],
    "save_profile": ["name"],
    "add_mix": [],
    "paint_region": ["object", "filament"],
    "checkout_object": ["object"],
    "checkin_object": ["object", "token"],
    "release_object": ["object"],
    "add_part": ["object"],
    "set_part": ["object", "part"],
    "remove_part": ["object", "part"],
    "open_project": ["path"],
    "add_model": ["path"],
    "set_plate": ["object", "plate"],
    "set_filament_preset": ["filament", "preset"],
    "set_filament_temps": ["filament"],
    "save_filament_preset": ["filament", "name"],
    "delete_plate": ["plate"],
    "set_filament": ["object", "filament"],
    "transform_object": ["object"],
    "duplicate_object": ["object"],
    "delete_object": ["object"],
    "set_wipe_tower": ["x", "y"],
    "find_settings": ["query"],
    "set_settings": ["settings"],
    "remove_mix": ["index"],
}


def handle(m):
    meth = m.get("method")
    if meth == "initialize":
        return {
            "protocolVersion": m["params"].get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "u1web", "version": "1.0"},
            "instructions": f"Snapmaker U1 slicer session shared live with the user's browser UI ({API}). "
            "Call get_scene first; edits are visible to the user immediately.",
        }
    if meth == "ping":
        return {}
    if meth == "tools/list":
        return {
            "tools": [
                {
                    "name": n,
                    "description": d,
                    "inputSchema": {"type": "object", "properties": p, "required": REQUIRED.get(n, [])},
                }
                for n, (d, p, _) in TOOLS.items()
            ]
        }
    if meth == "tools/call":
        name, args = m["params"]["name"], m["params"].get("arguments") or {}
        try:
            res = TOOLS[name][2](args)
            err = isinstance(res, dict) and bool(res.get("error"))
        except Exception as e:
            res, err = {"error": str(e)}, True
        return {
            "content": [{"type": "text", "text": res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)}],
            "isError": err,
        }
    raise LookupError(meth)


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        m = json.loads(line)
        if "id" not in m:  # notification (e.g. notifications/initialized)
            continue
        try:
            out = {"jsonrpc": "2.0", "id": m["id"], "result": handle(m)}
        except LookupError as e:
            out = {"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": f"method not found: {e}"}}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
