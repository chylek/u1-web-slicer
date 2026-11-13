"""Session operations end to end, without the Orca CLI: transforms, undo/redo, checkout, painting, colours, mixes,
profiles, plates, imports, filament presets, the prime tower and modifier objects."""

import io
import re
import zipfile

import pytest
from conftest import PALETTE

import colormix
import paintree
import session
import threemf

U1 = ["#E2DEDB", "#080A0D", "#F4C032", "#E72F1D"]  # white, black, yellow, red: a printer with yellow and black swapped


def test_transforms_and_scene_edits(new_session, project):
    s = new_session()
    s.open(project, "Coop.3mf")
    n0 = len(s.st["objects"])
    assert (s.st["wipe"]["x"], s.st["wipe"]["y"]) != (170.0, 140.0), "wipe tower should move off Roof_Front on open"
    p = s.obj("Perch")
    b0 = s.bbox(p)
    s.op({"op": "rotate", "id": "Perch", "deg": 90})
    b1 = s.bbox(p)
    assert abs((b0[1] - b0[0]) - (b1[3] - b1[2])) < 0.01
    s.op({"op": "set_object", "id": "Perch", "x": 100, "y": 100, "scale": 200})
    b2 = s.bbox(p)
    assert abs((b2[0] + b2[1]) / 2 - 100) < 0.01 and abs(b2[4]) < 1e-6 and abs(s.rot_scale(p)[1] - 2) < 1e-6
    m = list(p["m"])
    m[0:9] = [1, 0, 0, 0, 0, 1, 0, -1, 0]  # 90 degrees about X, lifted: drop must put it back on the bed
    m[11] = 50
    s.op({"op": "move", "id": "Perch", "m": m, "drop": True})
    b3 = s.bbox(p)
    assert abs(b3[4]) < 1e-6 and abs(b3[5] - b3[4] - 35) < 0.01, b3  # on the bed, 35 mm tall (was the Y extent)
    m = list(p["m"])
    m[11] += 12
    s.op({"op": "move", "id": "Perch", "m": m})
    assert abs(s.bbox(p)[4] - 12) < 1e-6  # a plain move may lift (or sink)
    s.op({"op": "drop", "id": "Perch"})
    assert abs(s.bbox(p)[4]) < 1e-6
    s.op({"op": "set_object", "id": "Perch", "rot": [90, 0, 30], "scale": [100, 150, 50], "z": 5})
    r_, s_ = s.decompose(p)
    assert max(abs(a - b) for a, b in zip(r_ + s_, [90, 0, 30, 1, 1.5, 0.5])) < 1e-6, (r_, s_)
    assert abs(s.bbox(p)[4] - 5) < 1e-6
    s.rotate(p, 45)
    assert abs(s.decompose(p)[0][2] - 75) < 1e-6 and abs(s.decompose(p)[0][0] - 90) < 1e-6  # Z turn only changes rz
    s.op({"op": "set_object", "id": "Perch", "rot": [0, 0, 0], "scale": 200, "z": 0})
    s.op({"op": "dup", "id": "Egg1", "count": 2})
    assert len(s.st["objects"]) == n0 + 2
    s.op({"op": "mix_add", "a": 1, "b": 3})
    s.op({"op": "set_ext", "id": "Body", "part": 3, "ext": 5})
    s.op({"op": "mix_del", "index": 0})
    assert s.obj("Body")["ext"][3] == 1  # the removed mix falls back to its main component
    s.op({"op": "set_object_settings", "id": "Perch", "settings": {"wall_loops": 4}})
    s.op({"op": "set_global", "settings": {"sparse_infill_density": "20%"}})
    s.op({"op": "arrange"})
    assert not s.off_bed()
    s2 = session.Session(s.jobs, s.art)  # persisted state survives a restart
    assert len(s2.st["objects"]) == n0 + 2 and s2.obj("Perch")["cfg"] == {"wall_loops": "4"}
    ui, _ = threemf.parse(s.build())
    assert len(ui["objects"]) == n0 + 2 and ui["settings"]["sparse_infill_density"] == "20%"
    r = s.op({"op": "add_part", "id": "Body", "kind": "modifier", "shape": "box"})
    body = s.obj("Body")
    s.op({"op": "set_part", "id": "Body", "part": r["part"], "cfg": {"sparse_infill_density": "80%"}})
    assert s.geos[body["gid"]]["parts"][-1]["type"] == "modifier_part"
    assert s.pcfg(body)[-1] == {"sparse_infill_density": "80%"}
    s.op({"op": "dup", "id": "Body", "arrange": False})
    copy = s.st["objects"][-1]
    s.op({"op": "add_part", "id": copy["id"], "kind": "negative", "shape": "cylinder", "size": [5, 5, 50]})
    assert copy["gid"] != body["gid"] and len(s.geos[body["gid"]]["parts"]) == 5  # copy-on-write kept the original
    s.op({"op": "add_primitive", "shape": "sphere", "size": [20, 20, 20]})
    ui, _ = threemf.parse(s.build())
    b = next(o for o in ui["objects"] if o["name"] == "Body")
    assert b["parts"][-1]["type"] == "modifier_part" and b["pcfg"][-1] == {"sparse_infill_density": "80%"}


def test_undo_redo_and_checkout(new_session):
    s = new_session()
    s.op({"op": "add_primitive", "shape": "box", "size": [20, 20, 20]})
    o = s.obj("o1")
    g0 = o["gid"]
    s.op({"op": "subdivide", "id": "o1", "part": 0, "max_edge": 5})
    g1 = s.obj("o1")["gid"]
    s.op({"op": "paint", "id": "o1", "part": 0, "set": {"2": [0, 1]}})
    g2 = s.obj("o1")["gid"]
    assert len({g0, g1, g2}) == 3 and s.geos[g1]["shape"] == s.geos[g2]["shape"]  # paint keeps the mesh, new gid
    assert s.geos[g1]["parts"][0]["paint"] is None and s.geos[g2]["parts"][0]["paint"][0] == "8"
    s.op({"op": "rotate", "id": "o1", "deg": 30})
    s.undo()
    assert abs(s.rot_scale(s.obj("o1"))[0]) < 1e-6
    s.undo()
    assert s.obj("o1")["gid"] == g1  # paint undone
    s.redo()
    assert s.obj("o1")["gid"] == g2
    s.op({"op": "set_ext", "id": "o1", "ext": 3})  # a new edit drops the redo branch
    with pytest.raises(ValueError):
        s.redo()
    assert s.state()["can_undo"] and not s.state()["can_redo"]
    s3 = session.Session(s.jobs, s.art)  # history survives a restart (+ blob gc)
    s3.undo()
    assert s3.obj("o1")["ext"] == [1]
    # checkout / checkin with a lock
    r = s3.op({"op": "checkout", "id": "o1"})
    tok = r["token"]
    with pytest.raises(ValueError, match="checked out"):
        s3.op({"op": "set_ext", "id": "o1", "ext": 2})
    s3.op({"op": "set_object_settings", "id": "o1", "settings": {"wall_loops": 5}, "token": tok})
    z = zipfile.ZipFile(r["path"])  # an external tool edits the file: every triangle painted with filament 4
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zo:
        for it in z.infolist():
            data = z.read(it.filename)
            if it.filename == "3D/3dmodel.model":
                data = re.sub(
                    rb'<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"[^/]*/>',
                    rb'<triangle v1="\1" v2="\2" v3="\3" paint_color="1C"/>',
                    data,
                )
            zo.writestr(it, data)
    open(r["path"], "wb").write(out.getvalue())
    s3.op({"op": "checkin", "id": "o1", "token": tok})
    o = s3.obj("o1")
    assert "lock" not in o and o["cfg"] == {"wall_loops": "5"}
    assert set(s3.geos[o["gid"]]["parts"][0]["paint"]) == {"1C"}
    s3.undo()
    assert "lock" not in s3.obj("o1")  # undo does not resurrect the lock


def test_rule_and_brush_painting(new_session):
    s = new_session()
    s.op({"op": "add_primitive", "shape": "box", "size": [20, 20, 20]})
    q = s.bbox(s.obj("o1"))
    r = s.op({"op": "paint_region", "id": "o1", "filament": 2, "facing": "up", "max_angle": 10})
    assert r["msg"].startswith("painted 2 "), r
    s.op({"op": "paint_region", "id": "o1", "filament": 3, "z_min": q[4] + 10})
    part = s.geos[s.obj("o1")["gid"]]["parts"][0]
    paint = part["paint"]
    assert len(part["tris"]) == 12  # geometry never changes
    assert "0C" in paint and "8" not in paint  # top solid filament 3, sides split at z = 10
    assert any(paintree.state_of(paintree.decode(c)) == 255 for c in paint if c)
    s.op({"op": "add_part", "id": "o1", "kind": "modifier", "shape": "box", "size": [8, 8, 6], "z": q[5] - 3})
    s.op({"op": "paint_region", "id": "o1", "part": 0, "filament": 4, "inside_part": 1})
    part = s.geos[s.obj("o1")["gid"]]["parts"][0]
    assert any(
        st == 4
        for t, c in enumerate(part["paint"])
        if c
        for _, st in paintree.leaves(paintree.decode(c), tuple(part["verts"][i] for i in part["tris"][t]))
    )
    cx = (q[0] + q[1]) / 2
    strokes = [{"center": [cx, q[2], q[4] + 5], "radius": 3}]  # a dot on the front side
    s.op({"op": "paint_brush", "id": "o1", "part": 0, "filament": 1, "strokes": strokes})
    assert len(s.geos[s.obj("o1")["gid"]]["parts"][0]["tris"]) == 12
    with pytest.raises(ValueError):
        s.op({"op": "paint_region", "id": "o1", "filament": 2, "z_min": 999})
    ui, _ = threemf.parse(s.build())
    assert ui["objects"][0]["parts"][0]["paint"]
    fils = [{"colour": "#112233"}, {"colour": "#445566"}, {"colour": "#778899"}, {"colour": "#AABBCC", "type": "PETG"}]
    s.op({"op": "set_filaments", "filaments": fils})
    assert s.st["filaments"][0]["colour"] == "#112233" and s.cfg["filament_colour"][3] == "#AABBCC"
    ui, _ = threemf.parse(s.build())
    assert ui["filaments"][0]["colour"] == "#112233"
    s.undo()
    assert s.st["filaments"][0]["colour"] != "#112233" and s.cfg["filament_colour"][0] != "#112233"  # profile too


def _paint_states(s):
    out = {}
    for o in s.st["objects"]:
        for p in s.geos[o["gid"]]["parts"]:
            for c in p.get("paint") or []:
                if c:
                    for st in paintree.used_states(c):
                        out[st] = out.get(st, 0) + 1
    return out


def test_colour_mapping_onto_the_printer(new_session, painted):
    s = new_session()
    s.open(painted, "Painted.3mf")
    plan = {p["id"]: p for p in s.colour_plan(U1)}
    assert plan[2]["best"]["kind"] == "phys" and plan[2]["best"]["ext"] == 3, plan[2]["best"]  # yellow -> slot 3
    assert plan[3]["best"]["ext"] == 2  # black -> slot 2
    before = _paint_states(s)
    s.op(
        {
            "op": "apply_colour_map",
            "filaments": [{"colour": c} for c in U1],
            "map": {str(k): v["best"] for k, v in plan.items()},
        }
    )
    after = _paint_states(s)
    assert after.get(3) == before.get(2) and after.get(2) == before.get(3), (
        before,
        after,
    )  # paint followed the colours
    assert [f["colour"] for f in s.st["filaments"]] == U1
    s.undo()
    assert _paint_states(s) == before
    # a model colour nothing matches -> a mix is created (orange from yellow + red)
    s = new_session()
    s.op({"op": "add_primitive", "shape": "box", "size": [10, 10, 10]})
    s.op(
        {"op": "apply_colour_map", "filaments": [{"colour": c} for c in U1], "map": {"1": colormix.best("#F28A27", U1)}}
    )
    assert s.st["mix"] and s.obj("o1")["ext"] == [5] and s.mix_colours()[0] == colormix.best("#F28A27", U1)["colour"]


def test_multi_component_mixes(new_session):
    s = new_session()
    s.op({"op": "add_primitive", "shape": "box", "size": [10, 10, 10]})
    s.op({"op": "mix_add", "ids": [2, 4, 3], "weights": [50, 30, 20]})
    assert "g243" in s.st["mix"] and "w50/30/20" in s.st["mix"], s.st["mix"]
    assert session.parse_mix_row(session.encode_mix((1, 2, 3, 4), (40, 30, 20, 10))) == ((1, 2, 3, 4), (40, 30, 20, 10))
    s.op({"op": "set_ext", "id": "o1", "ext": 5})
    ui, _ = threemf.parse(s.build())
    assert "g243" in ui["mix"]
    s.op({"op": "mix_del", "index": 0})
    assert s.obj("o1")["ext"] == [2]  # falls back to the main component
    n0 = len(s.mix_rows())
    s.op({"op": "mix_add", "a": 3, "b": 4, "pct": 25})
    r = s.op({"op": "mix_add", "a": 3, "b": 4, "pct": 25})
    assert len(s.mix_rows()) == n0 + 1 and "already" in r["msg"]  # an identical mix is not added twice
    s.st["mix"] += ";3,4,1,1,25"  # simulate an old duplicate that is in use
    s.obj("o1")["ext"] = [4 + len(s.mix_rows())]
    s.op({"op": "dedupe_mixes"})
    assert len(s.mix_rows()) == 1 and s.obj("o1")["ext"] == [5]


def test_profiles(new_session):
    s = new_session()
    s.op({"op": "add_primitive", "shape": "box", "size": [10, 10, 10]})
    s.op({"op": "apply_profile", "kind": "global", "name": "0.20mm Standard"})
    assert s.st["overrides"].get("layer_height") == "0.2" and s.st["profile"] == "0.20mm Standard"
    s.op({"op": "set_global", "settings": {"wall_loops": "5", "wall_filament": "3"}})
    assert "profile" not in s.st
    s.profile_save("global", "Strong")
    s.op({"op": "apply_profile", "kind": "global", "name": "0.08mm Standard"})
    s.op({"op": "apply_profile", "kind": "global", "name": "Strong"})
    ov = s.st["overrides"]
    assert ov["wall_loops"] == "5" and ov["layer_height"] == "0.2" and "wall_filament" not in ov
    s.op(
        {"op": "set_object_settings", "id": "o1", "settings": {"enable_support": "1", "support_threshold_angle": "40"}}
    )
    s.profile_save("object", "Tree supports", "o1")
    s.op({"op": "dup", "id": "o1", "arrange": False})
    o2 = s.st["objects"][-1]["id"]
    s.op({"op": "set_object_settings", "id": o2, "settings": {"enable_support": None, "support_threshold_angle": None}})
    s.op({"op": "apply_profile", "kind": "object", "name": "Tree supports", "id": o2})
    assert s.obj(o2)["cfg"]["support_threshold_angle"] == "40"
    assert any(p["name"] == "Strong" for p in s.profiles()["global"])
    s.profile_delete("global", "Strong")
    assert not any(p["name"] == "Strong" for p in s.profiles()["global"])


def test_slice_result_goes_stale(new_session, painted):
    s = new_session()
    s.op({"op": "add_primitive", "shape": "box", "size": [10, 10, 10]})
    s.st["result"] = {"ok": True, "job": "x"}
    s.op({"op": "rotate", "id": "o1", "deg": 10})
    assert s.st["result"]["stale"]
    s.st["result"] = {"ok": True, "job": "y"}
    s.undo()
    assert s.st["result"]["stale"]
    s.st["result"] = {"ok": True, "job": "z"}
    s.add(painted, "p.3mf")
    assert s.st["result"]["stale"]
    s.op({"op": "clear_result"})
    assert s.st["result"] is None  # the user discards the slice
    s.new()
    assert s.st["result"] is None


def test_multiple_plates(new_session):
    s = new_session()
    for _ in range(6):
        s.op({"op": "add_primitive", "shape": "box", "size": [120, 120, 20]})
    s.op({"op": "arrange", "all": True})
    plates = [o["plate"] for o in s.st["objects"]]
    assert s.nplates() >= 2 and max(plates) == s.nplates() and not s.off_bed() and not s.overlaps()
    per = {p: len(s.on_plate(p)) for p in range(1, s.nplates() + 1)}
    assert all(1 <= n <= 4 for n in per.values()), per
    ui, _ = threemf.parse(s.build())
    assert ui["plates"] == s.nplates() and [o["plate"] for o in ui["objects"]] == plates
    u1, _ = threemf.parse(s.build(plate=2))
    assert len(u1["objects"]) == per[2] and u1["plates"] == 1
    s.op({"op": "set_plate", "id": "o1", "plate": s.nplates() + 1})
    assert s.obj("o1")["plate"] == s.nplates()
    n0 = s.nplates()
    s.op({"op": "del_plate", "plate": n0})
    assert s.nplates() == n0 - 1 and len(s.st["objects"]) == 5


def test_zip_import_is_one_undo_step(new_session, painted):
    s = new_session()
    n = len(threemf.parse(painted)[0]["objects"])
    ids = s.add(None, "kit.zip", files=[(painted, "a.3mf"), (b"junk", "b.stl"), (painted, "c.3mf")])
    assert len(ids) == 2 * n and [name for name, _ in s.add_skipped] == ["b.stl"]
    s.undo()
    assert not s.st["objects"]


def test_filament_presets(new_session, project):
    s = new_session()
    s.open(project, "Coop.3mf")
    c0 = dict(s.cfg)
    s.op({"op": "set_filament_preset", "filament": 3, "preset": "Snapmaker TPU 90A @U1"})
    c = s.cfg
    tot = sum(map(int, c["filament_flow_step_size"]))
    assert c["filament_type"][2] == "TPU" and all(len(c[k]) == tot for k in session.FLOW_KEYS if k in c)
    assert s.fil_info()[2]["nozzle"] == "230"
    s.op({"op": "set_filament_preset", "filament": 3, "preset": "Snapmaker PLA SnapSpeed @U1"})
    assert all(s.cfg[k] == c0[k] for k in c0), [k for k in c0 if s.cfg[k] != c0[k]]  # back to the original 1:1
    tpu = {"colour": "#FFFFFF", "type": "TPU", "vendor": "Generic", "sub_type": "90A"}
    s.op({"op": "set_filaments", "filaments": [{}, {}, tpu, {}]})
    assert s.fil_info()[2]["preset"] == "Generic TPU" and s.fil_info()[2]["type"] == "TPU"
    s.op({"op": "set_filament_preset", "filament": 3, "preset": "Snapmaker TPU 90A @U1"})
    vals = {"filament_max_volumetric_speed": "3.5", "filament_retraction_length": "0.8"}
    s.op({"op": "set_filament_values", "filament": 3, "values": vals})
    s.filament_save(3, "TPU mine")
    fi = s.fil_info()[2]
    assert fi["preset"] == "TPU mine" and fi["vals"]["filament_max_volumetric_speed"] == "3.5"
    assert s.fil_presets()["TPU mine"]["filament_retraction_length"] == ["0.8"]


def test_prime_tower_follows_filament_use(new_session, project):
    s = new_session()
    s.open(project, "Coop.3mf")
    for o in s.st["objects"]:
        for i in range(len(o["ext"])):
            s.op({"op": "set_ext", "id": o["id"], "part": i, "ext": 1})
    assert not s.st["wipe"]["enabled"]
    pos = [s.bbox(o) for o in s.st["objects"]]
    first = s.st["objects"][0]["id"]
    s.op({"op": "set_ext", "id": first, "part": 0, "ext": 2})
    assert s.st["wipe"]["enabled"] and [s.bbox(o) for o in s.st["objects"]] == pos  # objects never move
    s.op({"op": "set_ext", "id": first, "part": 0, "ext": 1})
    assert not s.st["wipe"]["enabled"]


def test_modifier_objects_and_replace_colour(new_session):
    s = new_session()
    s.op({"op": "add_primitive", "shape": "box", "size": [20, 20, 20], "x": 50, "y": 50})
    a = s.st["objects"][0]["id"]
    r = s.op({"op": "add_part", "id": a, "kind": "modifier", "shape": "box", "size": [5, 5, 5]})
    s.op({"op": "move_part", "id": a, "part": r["part"], "x": 55, "y": 45, "z": 3})
    g = s.geos[s.obj(a)["gid"]]["parts"][r["part"]]["verts"]
    t = s.obj(a)["m"]
    assert (
        abs(sum(v[0] for v in g) / len(g) + t[9] - 55) < 0.01 and abs(sum(v[2] for v in g) / len(g) + t[11] - 3) < 0.01
    )
    s.op({"op": "add_primitive", "shape": "box", "size": [8, 8, 8], "x": 50, "y": 50})
    m = s.st["objects"][1]["id"]
    s.op({"op": "set_object", "id": m, "x": 50, "y": 50})
    s.op({"op": "set_role", "id": m, "role": "modifier_part"})
    s.op({"op": "dup", "id": a})
    s.op({"op": "arrange", "all": True})
    geos, objs = s._merged(s.st["objects"])
    assert len(objs) == 2 and [p["type"] for p in geos[objs[0]["gid"]]["parts"]][-1] == "modifier_part"
    assert len(objs[0]["ext"]) == 3
    # replace_colour: a painted colour -> another filament, scoped to one object, undoable
    o0 = s.st["objects"][0]["id"]
    s.op({"op": "paint_region", "id": o0, "filament": 3, "facing": "up", "max_angle": 10})
    assert 3 in s.used_ids([s.obj(o0)])
    s.op({"op": "replace_colour", "id": o0, "from": 3, "to": 1})
    assert 3 not in s.used_ids([s.obj(o0)])
    with pytest.raises(ValueError):
        s.op({"op": "replace_colour", "id": o0, "from": 3, "to": 1})
    s.undo()
    assert 3 in s.used_ids([s.obj(o0)])


def test_palette_fixture_matches_expectations():
    assert colormix.best(PALETTE[1], U1)["ext"] == 3 and colormix.best(PALETTE[2], U1)["ext"] == 2
