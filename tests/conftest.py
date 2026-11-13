"""Shared fixtures: synthetic multi-object / multi-filament 3MF projects built with threemf, so the tests need no
external model files. The filament palette (white, yellow, black, red) matches the colour-mapping expectations."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import session  # noqa: E402
import threemf  # noqa: E402

PALETTE = ["#E2DEDB", "#F4C032", "#080A0D", "#E72F1D"]  # filament 1-4 of the synthetic project
IDENTITY = [1, 0, 0, 0, 1, 0, 0, 0, 1]


def _at(x, y):
    return [*IDENTITY, x, y, 0]


def project_bytes():
    """6 objects on one plate: Perch (box 100 x 35 x 8), three eggs, Body (4 solid parts, one per filament) and
    Roof_Front, with the wipe tower deliberately placed on top of Roof_Front."""
    scene = threemf.new_scene()
    cfg = scene["cfg"]
    cfg["filament_colour"] = list(PALETTE)
    body = threemf.primitive("box", [20, 20, 20], "Body")
    base = body["parts"][0]
    body["parts"] = [
        {**base, "name": f"Body{i}", "verts": [(x + 22 * i, y, z) for x, y, z in base["verts"]]} for i in range(4)
    ]
    geos = {
        "g1": threemf.primitive("box", [100, 35, 8], "Perch"),
        "g2": threemf.primitive("sphere", [30, 30, 40], "Egg"),
        "g3": body,
        "g4": threemf.primitive("box", [80, 60, 20], "Roof_Front"),
    }
    objs = [
        {"gid": "g1", "name": "Perch", "m": _at(60, 30), "ext": [1]},
        {"gid": "g2", "name": "Egg1", "m": _at(150, 40), "ext": [2]},
        {"gid": "g2", "name": "Egg2", "m": _at(190, 40), "ext": [2]},
        {"gid": "g2", "name": "Egg3", "m": _at(230, 40), "ext": [3]},
        {"gid": "g3", "name": "Body", "m": _at(60, 120), "ext": [1, 2, 3, 4]},
        {"gid": "g4", "name": "Roof_Front", "m": _at(180, 150), "ext": [3]},
    ]
    return threemf.build(cfg, geos, objs, wipe={"x": 170, "y": 140})


def painted_bytes(tmp_path):
    """one yellow box (filament 2) whose top is painted black (filament 3) with Orca paint trees"""
    s = session.Session(tmp_path / "painted", tmp_path / "models")
    s.op({"op": "set_filaments", "filaments": [{"colour": c} for c in PALETTE]})
    s.op({"op": "add_primitive", "shape": "box", "size": [20, 20, 20], "ext": 2})
    s.op({"op": "paint_region", "id": "o1", "filament": 3, "facing": "up", "max_angle": 10})
    return s.build()


@pytest.fixture
def project():
    return project_bytes()


@pytest.fixture
def painted(tmp_path):
    return painted_bytes(tmp_path)


@pytest.fixture
def new_session(tmp_path):
    """factory: a fresh Session with its own data dir"""
    n = [0]

    def make():
        n[0] += 1
        return session.Session(tmp_path / f"s{n[0]}", tmp_path / "models")

    return make
