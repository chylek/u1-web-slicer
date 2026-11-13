"""Runs each module's own `python3 module.py` self-check (they double as examples) and the 3MF round trip."""

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import project_bytes

ROOT = Path(__file__).resolve().parents[1]


def run(*args, env=None):
    r = subprocess.run(
        [sys.executable, *args], cwd=ROOT, capture_output=True, text=True, env=env, timeout=120, check=False
    )
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


@pytest.mark.parametrize("module", ["paintree.py", "colormix.py", "thumbs.py"])
def test_selfcheck(module):
    assert "ok" in run(module)


def test_threemf_roundtrip(tmp_path):
    f = tmp_path / "project.3mf"
    f.write_bytes(project_bytes())
    assert "roundtrip ok 6 objects" in run("threemf.py", str(f))


def test_gcodeprev(tmp_path):
    g = tmp_path / "t.gcode"
    g.write_text(
        ";Z:0.2\n;TYPE:Outer wall\nM83\nG1 X10 Y10 E1\nG1 X20 Y10 E1\nG2 X30 Y20 I10 J0 E2\n;Z:0.4\nG1 X0 Y0 E1\n"
    )
    out = run("gcodeprev.py", str(g))
    assert "segments 2 layers" in out and not out.startswith("0 ")


def test_printer_eta_blend():
    import os

    env = dict(os.environ, U1_HOST="")
    out = subprocess.run(
        [sys.executable, "printer.py"], cwd=ROOT, capture_output=True, text=True, env=env, timeout=60, check=False
    )
    assert "eta ok" in out.stdout or "U1_HOST is not set" in out.stderr  # the blend asserts run before the live call
