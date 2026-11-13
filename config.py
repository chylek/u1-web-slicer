"""Runtime configuration: environment variables, optionally seeded from a `.env` file next to this module.

Variables (all optional):
  U1WEB_DATA               working data: slicing jobs, session state, history, user presets
                           (default ~/.local/share/u1web)
  U1WEB_MODELS             folder whose first-level subfolders hold 3MF/STL models; saved projects go to <models>/u1web/
                           (default <data>/models)
  U1WEB_PORT               HTTP port of server.py (default 3060)
  U1WEB_URL                where mcp_server.py reaches the server (default http://127.0.0.1:<port>)
  U1WEB_ORCA_CONTAINER     docker container that has the Snapmaker Orca CLI; empty = run the CLI directly
                           (default orca-web)
  U1WEB_ORCA_USER          user inside the container (default abc, the linuxserver.io convention)
  U1WEB_ORCA_BIN           slicer executable (default /opt/orca/bin/snapmaker-orca)
  U1WEB_DATA_IN_CONTAINER  path under which U1WEB_DATA is mounted inside the container (default /jobs)
  U1_HOST                  Moonraker host:port of the printer (no default: printer features stay off until set)
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent

_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("\"'"))

DATA = Path(os.environ.get("U1WEB_DATA") or Path.home() / ".local/share/u1web").expanduser()
MODELS = Path(os.environ.get("U1WEB_MODELS") or DATA / "models").expanduser()
PORT = int(os.environ.get("U1WEB_PORT") or 3060)
URL = os.environ.get("U1WEB_URL") or f"http://127.0.0.1:{PORT}"
ORCA_CONTAINER = os.environ.get("U1WEB_ORCA_CONTAINER", "orca-web")
ORCA_USER = os.environ.get("U1WEB_ORCA_USER") or "abc"
ORCA_BIN = os.environ.get("U1WEB_ORCA_BIN") or "/opt/orca/bin/snapmaker-orca"
DATA_IN_CONTAINER = os.environ.get("U1WEB_DATA_IN_CONTAINER") or ("/jobs" if ORCA_CONTAINER else str(DATA))
PRINTER_HOST = os.environ.get("U1_HOST", "")


def orca_command(args):
    """Command line that runs the Orca CLI with `args` (paths already translated with `in_container`)."""
    if not ORCA_CONTAINER:
        return [ORCA_BIN, *args]
    return [
        "docker",
        "exec",
        "-u",
        ORCA_USER,
        "-e",
        "DISPLAY=:1",
        "-e",
        f"HOME={DATA_IN_CONTAINER}/.home",
        ORCA_CONTAINER,
        ORCA_BIN,
        *args,
    ]


def in_container(path):
    """Path of something under U1WEB_DATA as the slicer process sees it."""
    rel = Path(path).relative_to(DATA)
    return DATA_IN_CONTAINER if rel == Path(".") else f"{DATA_IN_CONTAINER}/{rel}"
