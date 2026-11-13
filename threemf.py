"""Orca/Bambu-style 3MF <-> scene for the web UI, plus STL import. Stdlib only.
Scene object = {gid, name, m:[12 numbers, 3MF row-vector matrix], parts:[{name, extruder}]}.
Geometry (kept server-side per gid): {name, parts:[{name, verts, tris, paint}]} in object-local coordinates."""

import base64
import io
import json
import re
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
P = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path"
BASE = (Path(__file__).parent / "base_project_settings.config").read_bytes()
ID = "1 0 0 0 1 0 0 0 1 0 0 0"
# settings exposed in the UI (static/schema.json from tools/gen_schema.py): global = project config,
# per object = <metadata> in model_settings.config
SCHEMA = json.loads((Path(__file__).parent / "static/schema.json").read_text())["opts"]
SETTINGS = set(SCHEMA)
OBJ_SETTINGS = {k for k, o in SCHEMA.items() if o["obj"]}


def scalar(v):
    """per-nozzle list -> its (single, uniform) value; metadata '60,60' -> '60'"""
    return v[0] if isinstance(v, list) else v


def _tf(s):
    v = [float(x) for x in s.split()] if s else [float(x) for x in ID.split()]
    return lambda x, y, z: (
        x * v[0] + y * v[3] + z * v[6] + v[9],
        x * v[1] + y * v[4] + z * v[7] + v[10],
        x * v[2] + y * v[5] + z * v[8] + v[11],
    )


def _mesh(root):
    out = {}
    for o in root.iterfind(".//m:object", NS):
        me = o.find("m:mesh", NS)
        if me is None:
            continue
        vs = [(float(v.get("x")), float(v.get("y")), float(v.get("z"))) for v in me.iterfind("m:vertices/m:vertex", NS)]
        tr = list(me.iterfind("m:triangles/m:triangle", NS))
        ts = [(int(t.get("v1")), int(t.get("v2")), int(t.get("v3"))) for t in tr]
        pa = [t.get("paint_color") for t in tr]
        out[o.get("id")] = (vs, ts, pa if any(pa) else None)
    return out


def pos_b64(vs, ts):
    return base64.b64encode(struct.pack(f"<{len(ts) * 9}f", *[c for t in ts for i in t for c in vs[i]])).decode()


def paint_state(code):
    """Orca paint_color -> filament of an unsplit triangle; 255 when the triangle carries a split tree (see "
    "paintree)."""
    import paintree

    return paintree.state_of(paintree.decode(code)) if code else 0


def paint_code(state):
    """filament number -> Orca paint_color for an unsplit triangle (inverse of paint_state): 1 '4', 2 '8', 3 "
    "'0C', 4 '1C', 5 '2C' …"""
    if not state:
        return None
    return "%X" % (state << 2) if state < 3 else "%XC" % (state - 3)


def subdivide(part, max_edge, max_tris=300000):
    """uniform 4-way split (shared edge midpoints -> stays watertight) until the longest edge <= max_edge or the
    triangle budget is hit. Children keep the parent's paint. Returns the number of passes."""
    import math

    passes = 0
    while True:
        V, Tr = part["verts"], part["tris"]
        longest = max(math.dist(V[a], V[b]) for t in Tr for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])))
        if longest <= max_edge or len(Tr) * 4 > max_tris:
            return passes
        V = list(V)
        mid = {}
        nt = []
        npaint = [] if part["paint"] else None

        def m(a, b):
            k = (a, b) if a < b else (b, a)
            if k not in mid:
                mid[k] = len(V)
                V.append(tuple((V[a][i] + V[b][i]) / 2 for i in range(3)))
            return mid[k]

        for i, (a, b, c) in enumerate(Tr):
            ab, bc, ca = m(a, b), m(b, c), m(c, a)
            nt += [(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)]
            if npaint is not None:
                npaint += [part["paint"][i]] * 4
        part.update(verts=V, tris=nt, paint=npaint)
        passes += 1


def ui_object(gid, geo, m, extruders, oid=None):
    return {
        "id": oid or gid,
        "gid": gid,
        "name": geo["name"],
        "m": m,
        "parts": [
            {
                "name": p["name"],
                "type": p.get("type", "normal_part"),
                "extruder": e,
                "pos": pos_b64(p["verts"], p["tris"]),
                "paint": base64.b64encode(bytes(min(paint_state(c), 255) for c in p["paint"])).decode()
                if p["paint"]
                else None,
            }
            for p, e in zip(geo["parts"], extruders)
        ],
    }


def plate_cols(n):
    """Orca compute_colum_count: plates are laid out in a grid of ~sqrt(n) columns"""
    import math

    v = math.sqrt(n)
    r = round(v)
    return r + 1 if v > r else max(1, r)


def plate_origin(p, n, bed_):
    """world offset of plate p (1-based) when there are n plates (Orca PartPlateList::compute_shape_position, "
    "gap 1/5)"""
    cols = plate_cols(n)
    i = p - 1
    return ((i % cols) * (bed_["x1"] - bed_["x0"]) * 1.2, -(i // cols) * (bed_["y1"] - bed_["y0"]) * 1.2)


def parse(data):
    """-> (ui dict, geos {gid: geo}). 3MF only."""
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    # plain 3MFs (our generators, other slicers) lack Orca's configs: fall back to the U1 base profile / default names
    cfg = json.loads(
        z.read("Metadata/project_settings.config") if "Metadata/project_settings.config" in names else BASE
    )
    ms = (
        ET.fromstring(z.read("Metadata/model_settings.config"))
        if "Metadata/model_settings.config" in names
        else ET.Element("config")
    )
    info = {}
    for o in ms.iterfind("object"):
        md = {m.get("key"): m.get("value") for m in o.iterfind("metadata")}
        info[o.get("id")] = {
            "name": md.get("name", "?"),
            "extruder": int(md.get("extruder", 1)),
            "cfg": {k: (v.split(",")[0] if SCHEMA[k].get("vec") else v) for k, v in md.items() if k in OBJ_SETTINGS},
            "parts": {
                p.get("id"): {
                    "_subtype": p.get("subtype", "normal_part"),
                    **{m.get("key"): m.get("value") for m in p.iterfind("metadata")},
                }
                for p in o.iterfind("part")
            },
        }
    plate_of = {}  # Orca <plate> blocks: assembly object id -> plate number
    for pl in ms.iterfind("plate"):
        pid = int(next((m.get("value") for m in pl.iterfind("metadata") if m.get("key") == "plater_id"), 1))
        for mi in pl.iterfind("model_instance"):
            oid_ = next((m.get("value") for m in mi.iterfind("metadata") if m.get("key") == "object_id"), None)
            if oid_:
                plate_of[oid_] = pid
    n_plates = max(list(plate_of.values()) + [1])
    bed_ = bed(cfg)
    main = ET.fromstring(z.read("3D/3dmodel.model"))
    top = {o.get("id"): o for o in main.iterfind("m:resources/m:object", NS)}
    files, geos, objs = {}, {}, []
    for item in main.iterfind("m:build/m:item", NS):
        oid = item.get("objectid")
        if item.get("printable") == "0" or oid not in top:
            continue
        meta = info.get(oid, {"name": "obj" + oid, "extruder": 1, "parts": {}})
        parts, ext, pcfg = [], [], []
        comps = list(top[oid].iterfind("m:components/m:component", NS))
        if not comps and top[oid].find("m:mesh", NS) is not None:  # mesh directly in the build object
            comps = [ET.Element("c", objectid=oid)]
        for c in comps:
            path = (c.get(P) or "").lstrip("/")
            if path not in files:
                files[path] = _mesh(ET.fromstring(z.read(path))) if path else _mesh(main)
            vs, ts, pa = files[path][c.get("objectid")]
            ctf = _tf(c.get("transform"))
            pm = meta["parts"].get(c.get("objectid"), {})
            parts.append(
                {
                    "name": pm.get("name", meta["name"]),
                    "verts": [ctf(*v) for v in vs],
                    "tris": ts,
                    "paint": pa,
                    "type": pm.get("_subtype", "normal_part"),
                }
            )
            ext.append(int(pm.get("extruder", meta["extruder"])))
            pcfg.append(
                {k: (v.split(",")[0] if SCHEMA[k].get("vec") else v) for k, v in pm.items() if k in OBJ_SETTINGS}
            )
        gid = "g" + oid
        geos[gid] = {"name": meta["name"], "parts": parts}
        m = [float(x) for x in (item.get("transform") or ID).split()]
        p = plate_of.get(oid, 1)
        ox, oy = plate_origin(p, n_plates, bed_)
        m[9] -= ox
        m[10] -= oy  # keep plate-local coordinates
        objs.append(dict(ui_object(gid, geos[gid], m, ext), cfg=meta.get("cfg", {}), pcfg=pcfg, plate=p))
    return {
        "bed": bed(cfg),
        "filaments": filaments(cfg),
        "wipe": {
            "x": float(cfg["wipe_tower_x"][0]),
            "y": float(cfg["wipe_tower_y"][0]),
            "w": float(cfg["prime_tower_width"]),
            "enabled": cfg.get("enable_prime_tower") == "1",
        },
        "objects": objs,
        "mix": cfg.get("mixed_filament_definitions", ""),
        "settings": {k: scalar(cfg[k]) for k in SETTINGS if k in cfg},
        "plates": n_plates,
        "cfg": cfg,
    }, geos


def filaments(cfg):
    ids = cfg.get("filament_settings_id") or [""] * len(cfg["filament_type"])
    return [{"colour": c, "type": t, "preset": p} for c, t, p in zip(cfg["filament_colour"], cfg["filament_type"], ids)]


def bed(cfg):
    area = [tuple(float(n) for n in p.split("x")) for p in cfg["printable_area"]]
    xs, ys = [a[0] for a in area], [a[1] for a in area]
    return {"x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys), "h": float(cfg["printable_height"])}


def new_scene():
    cfg = json.loads(BASE)
    return {
        "bed": bed(cfg),
        "filaments": filaments(cfg),
        "wipe": {
            "x": float(cfg["wipe_tower_x"][0]),
            "y": float(cfg["wipe_tower_y"][0]),
            "w": float(cfg["prime_tower_width"]),
            "enabled": True,
        },
        "objects": [],
        "mix": "",
        "settings": {k: scalar(cfg[k]) for k in SETTINGS if k in cfg},
        "plates": 1,
        "cfg": cfg,
    }


def load_stl(data, name):
    """Binary or ASCII STL -> geo with one part, centred in xy, sitting on z=0."""
    tris = []
    if len(data) >= 84 and 84 + 50 * struct.unpack_from("<I", data, 80)[0] == len(data):
        for i in range(struct.unpack_from("<I", data, 80)[0]):
            f = struct.unpack_from("<12f", data, 84 + 50 * i)
            tris.append([f[3:6], f[6:9], f[9:12]])
    else:
        v = [tuple(map(float, m)) for m in re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)]
        tris = [v[i : i + 3] for i in range(0, len(v) - 2, 3)]
    idx, vs, ts = {}, [], []
    for t in tris:
        row = []
        for p in t:
            k = tuple(round(c, 4) for c in p)
            if k not in idx:
                idx[k] = len(vs)
                vs.append(k)
            row.append(idx[k])
        ts.append(tuple(row))
    return centred({"name": name, "parts": [{"name": name, "verts": vs, "tris": ts, "paint": None}]})


def primitive(shape, size, name=None):
    """box / cylinder / sphere mesh (one part), centred in xy, sitting on z=0. size = [x, y, z] mm."""
    import math

    sx, sy, sz = (float(v) for v in size)
    vs, ts = [], []
    if shape == "box":
        vs = [(x * sx / 2, y * sy / 2, z * sz) for z in (0, 1) for y in (-1, 1) for x in (-1, 1)]
        ts = [
            (0, 2, 1),
            (1, 2, 3),
            (4, 5, 6),
            (5, 7, 6),
            (0, 1, 4),
            (1, 5, 4),
            (2, 6, 3),
            (3, 6, 7),
            (0, 4, 2),
            (2, 4, 6),
            (1, 3, 5),
            (3, 7, 5),
        ]
    elif shape == "cylinder":
        n = 64
        vs = [(0, 0, 0), (0, 0, sz)] + [
            (sx / 2 * math.cos(2 * math.pi * i / n), sy / 2 * math.sin(2 * math.pi * i / n), z)
            for i in range(n)
            for z in (0, sz)
        ]
        for i in range(n):
            a0, a1, b0, b1 = 2 + 2 * i, 3 + 2 * i, 2 + 2 * ((i + 1) % n), 3 + 2 * ((i + 1) % n)
            ts += [(0, b0, a0), (1, a1, b1), (a0, b0, a1), (a1, b0, b1)]
    elif shape == "sphere":
        nu, nv = 48, 24
        vs = [(0, 0, 0), (0, 0, sz)]
        for j in range(1, nv):
            th = math.pi * j / nv
            for i in range(nu):
                ph = 2 * math.pi * i / nu
                vs.append(
                    (
                        sx / 2 * math.sin(th) * math.cos(ph),
                        sy / 2 * math.sin(th) * math.sin(ph),
                        sz / 2 * (1 - math.cos(th)),
                    )
                )
        ring = lambda j, i: 2 + (j - 1) * nu + i % nu
        for i in range(nu):
            ts.append((0, ring(1, i + 1), ring(1, i)))
            ts.append((1, ring(nv - 1, i), ring(nv - 1, i + 1)))
            for j in range(1, nv - 1):
                ts += [
                    (ring(j, i), ring(j, i + 1), ring(j + 1, i)),
                    (ring(j + 1, i), ring(j, i + 1), ring(j + 1, i + 1)),
                ]
    else:
        raise ValueError(f"unknown shape '{shape}' (box, cylinder, sphere)")
    nm = name or shape.capitalize()
    return {"name": nm, "parts": [{"name": nm, "verts": vs, "tris": ts, "paint": None, "type": "normal_part"}]}


def centred(geo):
    allv = [v for p in geo["parts"] for v in p["verts"]]
    cx = (min(v[0] for v in allv) + max(v[0] for v in allv)) / 2
    cy = (min(v[1] for v in allv) + max(v[1] for v in allv)) / 2
    cz = min(v[2] for v in allv)
    for p in geo["parts"]:
        p["verts"] = [(x - cx, y - cy, z - cz) for x, y, z in p["verts"]]
    return geo


def build(cfg, geos, objects, wipe=None, mix=None, settings=None, plates=None):
    """objects: [{gid, name, m, ext:[per part], plate?}] -> 3MF bytes (template cfg = project settings dict).
    plates = number of plates for a multi-plate project file (objects in plate-local coords are offset into Orca's plate
    grid and listed in <plate> blocks); None = one plate (what we slice)."""
    cfg = dict(cfg)
    for k, v in (settings or {}).items():
        if k in SETTINGS and k in cfg:
            cfg[k] = [str(v)] * len(cfg[k]) if isinstance(cfg[k], list) else str(v)
    if (
        mix is not None
    ):  # Full Spectrum mixes: rows "a,b,enabled,custom,pctB" joined by ';'; virtual ids follow the physical ones
        cfg["mixed_filament_definitions"] = mix
    if wipe:
        cfg["wipe_tower_x"], cfg["wipe_tower_y"] = [str(wipe["x"])] * (plates or 1), [str(wipe["y"])] * (plates or 1)
    bed_ = bed(cfg)
    inst = {}
    model = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
        '<metadata name="Application">Snapmaker_Orca-2.4.1</metadata>',
        '<metadata name="Snapmaker_Orca:3mfVersion">1</metadata>',
        "<resources>",
    ]
    cf = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>"]
    build_, nid = [], 1
    for o in objects:
        geo = geos[o["gid"]]
        comps, pc = [], []
        pcfgs = o.get("pcfg") or [{}] * len(geo["parts"])
        for part, e, pcf in zip(geo["parts"], o["ext"], pcfgs):
            model.append(f'<object id="{nid}" type="model"><mesh><vertices>')
            model += [f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in part["verts"]]
            model.append("</vertices><triangles>")
            pa = part["paint"]
            model += [
                f'<triangle v1="{a}" v2="{b}" v3="{c}"' + (f' paint_color="{pa[i]}"' if pa and pa[i] else "") + "/>"
                for i, (a, b, c) in enumerate(part["tris"])
            ]
            model.append("</triangles></mesh></object>")
            comps.append(f'<component objectid="{nid}"/>')
            pmeta = "".join(
                f'\n   <metadata key="{k}" value="{_esc(_objval(cfg, k, v))}"/>'
                for k, v in (pcf or {}).items()
                if k in OBJ_SETTINGS
            )
            pc.append(
                f'  <part id="{nid}" subtype="{part.get("type", "normal_part")}">\n'
                f'   <metadata key="name" value="{_esc(part["name"])}"/>\n'
                f'   <metadata key="extruder" value="{e}"/>{pmeta}\n  </part>'
            )
            nid += 1
        model.append(f'<object id="{nid}" type="model"><components>{"".join(comps)}</components></object>')
        m = list(o["m"])
        if plates:
            ox, oy = plate_origin(o.get("plate", 1), plates, bed_)
            m[9] += ox
            m[10] += oy
            inst.setdefault(o.get("plate", 1), []).append(nid)
        build_.append(f'<item objectid="{nid}" transform="{" ".join(repr(float(x)) for x in m)}" printable="1"/>')
        cf += (
            [
                f' <object id="{nid}">',
                f'  <metadata key="name" value="{_esc(o["name"])}"/>',
                f'  <metadata key="extruder" value="{o["ext"][0]}"/>',
            ]
            + [
                f'  <metadata key="{k}" value="{_esc(_objval(cfg, k, v))}"/>'
                for k, v in (o.get("cfg") or {}).items()
                if k in OBJ_SETTINGS
            ]
            + pc
            + [" </object>"]
        )
        nid += 1
    model += ["</resources><build>"] + build_ + ["</build></model>"]
    for p in range(1, (plates or 0) + 1):
        cf += [
            " <plate>",
            f'  <metadata key="plater_id" value="{p}"/>',
            '  <metadata key="plater_name" value=""/>',
            '  <metadata key="locked" value="false"/>',
        ]
        for oid in inst.get(p, []):
            cf += [
                "  <model_instance>",
                f'   <metadata key="object_id" value="{oid}"/>',
                '   <metadata key="instance_id" value="0"/>',
                "  </model_instance>",
            ]
        cf.append(" </plate>")
    cf.append("</config>")
    ct = (
        '<?xml version="1.0" encoding="UTF-8"?><Types '
        'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="config" ContentType="text/xml"/></Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?><Relationships '
        'xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", "\n".join(model))
        z.writestr("Metadata/model_settings.config", "\n".join(cf))
        z.writestr("Metadata/project_settings.config", json.dumps(cfg, indent=4))
    return out.getvalue()


def _objval(cfg, k, v):
    return ",".join([str(v)] * len(cfg[k])) if isinstance(cfg.get(k), list) else str(v)


def _esc(s):
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


if __name__ == "__main__":  # self-check: python3 threemf.py file.3mf
    import sys

    d = open(sys.argv[1], "rb").read()
    ui, geos = parse(d)
    objs = [
        {"gid": o["gid"], "name": o["name"], "m": o["m"], "ext": [p["extruder"] for p in o["parts"]]}
        for o in ui["objects"]
    ]
    ui2, g2 = parse(build(ui["cfg"], geos, objs, {"x": 200, "y": 30}))
    assert len(ui2["objects"]) == len(ui["objects"]) and ui2["wipe"]["x"] == 200
    assert [[p["extruder"] for p in o["parts"]] for o in ui2["objects"]] == [
        [p["extruder"] for p in o["parts"]] for o in ui["objects"]
    ]
    assert sum(len(p["tris"]) for g in geos.values() for p in g["parts"]) == sum(
        len(p["tris"]) for g in g2.values() for p in g["parts"]
    )
    objs[0]["cfg"] = {"layer_height": "0.2", "wall_loops": "4", "outer_wall_speed": "40"}
    u3, _ = parse(build(ui["cfg"], geos, objs, settings={"sparse_infill_density": "30%", "inner_wall_speed": "120"}))
    assert u3["objects"][0]["cfg"] == {"layer_height": "0.2", "wall_loops": "4", "outer_wall_speed": "40"}, u3[
        "objects"
    ][0]["cfg"]
    assert u3["settings"]["sparse_infill_density"] == "30%" and u3["settings"]["inner_wall_speed"] == "120"
    for sh in (
        "box",
        "cylinder",
        "sphere",
    ):  # closed meshes: every edge used exactly twice, outward normals (positive volume)
        g = primitive(sh, [20, 20, 10])["parts"][0]
        edges = {}
        for a, b, c in g["tris"]:
            for e in ((a, b), (b, c), (c, a)):
                edges[e] = edges.get(e, 0) + 1
        assert all(edges.get((b, a)) == 1 for a, b in edges), sh
        V = g["verts"]
        vol = (
            sum(
                V[a][0] * (V[b][1] * V[c][2] - V[b][2] * V[c][1])
                - V[a][1] * (V[b][0] * V[c][2] - V[b][2] * V[c][0])
                + V[a][2] * (V[b][0] * V[c][1] - V[b][1] * V[c][0])
                for a, b, c in g["tris"]
            )
            / 6
        )
        assert vol > 0, (sh, vol)
    assert [plate_cols(n) for n in (1, 2, 3, 4, 5, 9, 10)] == [1, 2, 2, 2, 3, 3, 4]
    two = [dict(o, plate=1 + i % 2) for i, o in enumerate(objs)]
    u4, _ = parse(build(ui["cfg"], geos, two, plates=2))
    assert u4["plates"] == 2 and [o["plate"] for o in u4["objects"]] == [o["plate"] for o in two]
    assert all(abs(a["m"][9] - b["m"][9]) < 1e-6 for a, b in zip(u4["objects"], two))  # plate-local coords survive
    assert [paint_state(c) for c in ("4", "8", "0C", "1C", "", "88083")] == [1, 2, 3, 4, 0, 255]
    assert all(paint_state(paint_code(k)) == k for k in range(1, 12)) and paint_code(0) is None
    cube = primitive("box", [20, 20, 20])["parts"][0]
    cube["paint"] = ["8"] + [None] * 11
    n = subdivide(cube, 3)  # face diagonal 28.3 mm -> 4 passes to get <= 3 mm
    assert (
        n == 4
        and len(cube["tris"]) == 12 * 4**n
        and cube["paint"][: 4**n] == ["8"] * 4**n
        and cube["paint"][4**n] is None
    )
    edges = {}
    for a, b, c in cube["tris"]:
        for e in ((a, b), (b, c), (c, a)):
            edges[e] = edges.get(e, 0) + 1
    assert all(edges.get((b, a)) == 1 for a, b in edges), "subdivision must stay watertight"
    print("roundtrip ok", len(ui["objects"]), "objects")
