"""Orca G-code -> compact toolpath for the web preview. Stdlib only.
Binary record per extrusion segment (12 B, little endian):
x0,y0,x1,y1 int16 in 0.01 mm, layer uint16, tool uint8, type uint8."""

import math
import re
import struct

TYPES = [
    "Outer wall",
    "Inner wall",
    "Overhang wall",
    "Sparse infill",
    "Internal solid infill",
    "Top surface",
    "Bottom surface",
    "Bridge",
    "Internal Bridge",
    "Gap infill",
    "Support",
    "Support interface",
    "Prime tower",
    "Skirt",
    "Brim",
    "Ironing",
    "Custom",
]
TIX = {t: i for i, t in enumerate(TYPES)}
PT = TIX["Prime tower"]
NUM = re.compile(r"([XYZEIJ])(-?\d*\.?\d+)")


def parse(path):
    recs, zs = bytearray(), []
    x = y = z = 0.0
    tool, typ, rel_e, layer = 0, len(TYPES) - 1, True, -1
    q = lambda v: max(-32768, min(32767, int(round(v * 100))))

    tx, ty = [], []  # prime tower extents (layers > 5) -> real footprint for the UI

    def seg(x0, y0, x1, y1):
        recs.extend(struct.pack("<4hHBB", q(x0), q(y0), q(x1), q(y1), max(layer, 0), tool, typ))
        if typ == PT and layer > 5:
            tx.extend((x0, x1))
            ty.extend((y0, y1))

    with open(path, errors="ignore") as f:
        for line in f:
            c = line[0]
            if c == ";":
                if line.startswith(";Z:"):
                    z = float(line[3:])
                    zs.append(z)
                    layer = len(zs) - 1
                elif line.startswith(";TYPE:"):
                    typ = TIX.get(line[6:].strip(), len(TYPES) - 1)
                continue
            if c == "T" and line[1:2].isdigit():
                tool = int(line[1:].split()[0])
                continue
            if c == "M":
                if line.startswith("M83"):
                    rel_e = True
                elif line.startswith("M82"):
                    rel_e = False
                continue
            if c != "G":
                continue
            cmd = line.split(";", 1)[0].split()
            if not cmd:
                continue
            g = cmd[0]
            if g not in ("G0", "G1", "G2", "G3"):
                continue
            a = {k: float(v) for k, v in NUM.findall(" ".join(cmd[1:]))}
            nx, ny = a.get("X", x), a.get("Y", y)
            e = a.get("E", 0.0)
            ext = "E" in a and (e > 0 if rel_e else True) and g != "G0" and layer >= 0
            if ext and g == "G1":
                seg(x, y, nx, ny)
            elif ext:  # arc: tessellate around centre (I,J relative to start)
                cx, cy = x + a.get("I", 0), y + a.get("J", 0)
                r = math.hypot(x - cx, y - cy)
                a0, a1 = math.atan2(y - cy, x - cx), math.atan2(ny - cy, nx - cx)
                if g == "G2" and a1 >= a0:
                    a1 -= 2 * math.pi
                if g == "G3" and a1 <= a0:
                    a1 += 2 * math.pi
                n = max(2, int(abs(a1 - a0) * r / 1.0))
                px, py = x, y
                for i in range(1, n + 1):
                    t = a0 + (a1 - a0) * i / n
                    qx, qy = (cx + r * math.cos(t), cy + r * math.sin(t)) if i < n else (nx, ny)
                    seg(px, py, qx, qy)
                    px, py = qx, qy
            x, y = nx, ny
            if "Z" in a:
                z = a["Z"]
    pc = lambda a, p: sorted(a)[int((len(a) - 1) * p)]
    tower = [pc(tx, 0.01), pc(tx, 0.99), pc(ty, 0.01), pc(ty, 0.99)] if tx else None
    return {"layers": zs, "types": TYPES, "count": len(recs) // 12, "tower": tower}, bytes(recs)


if __name__ == "__main__":
    import sys
    import time

    t = time.time()
    meta, b = parse(sys.argv[1])
    assert meta["count"] > 0 and len(b) == meta["count"] * 12 and meta["layers"] == sorted(meta["layers"])
    print(meta["count"], "segments", len(meta["layers"]), "layers", round(time.time() - t, 1), "s")
