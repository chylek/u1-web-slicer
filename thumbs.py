"""G-code thumbnails without OpenGL: software-render the plate (Pillow, painter's algorithm, flat shading) and inject
Orca-style `; thumbnail begin WxH LEN` blocks (Snapmaker U1 profile wants 48x48 and 300x300 PNG)."""

import base64
import io
import math

from PIL import Image, ImageDraw

AZ, EL = math.radians(-35), math.radians(32)  # camera: front-left, looking down a bit (like Orca's plate view)


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def render(tris, size=300, ss=2):
    """tris: [((x,y,z),(x,y,z),(x,y,z), '#rrggbb')] in world mm -> RGBA PNG bytes, object fills ~90 % of the square"""
    if not tris:
        return None
    ca, sa, ce, se = math.cos(AZ), math.sin(AZ), math.cos(EL), math.sin(EL)
    R = (ca, -sa, 0.0)
    U = (sa * se, ca * se, ce)  # screen right / up in world space
    T = (R[1] * U[2] - R[2] * U[1], R[2] * U[0] - R[0] * U[2], R[0] * U[1] - R[1] * U[0])  # R x U = towards the viewer

    def view(p):
        return (
            sum(p[i] * R[i] for i in range(3)),
            sum(p[i] * U[i] for i in range(3)),
            sum(p[i] * T[i] for i in range(3)),
        )

    light = (
        T[0] - 0.5 * R[0] + 0.6 * U[0],
        T[1] - 0.5 * R[1] + 0.6 * U[1],
        T[2] - 0.5 * R[2] + 0.6 * U[2],
    )  # from upper-left of the camera ln = math.sqrt(sum(c * c for c in light)); light = tuple(c / ln for c in light)
    P = []
    for a, b, c, col in tris:
        u = [b[i] - a[i] for i in range(3)]
        w = [c[i] - a[i] for i in range(3)]
        n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        nl = math.sqrt(sum(x * x for x in n))
        if nl == 0:
            continue
        n = tuple(x / nl for x in n)
        if sum(n[i] * T[i] for i in range(3)) <= 0:
            continue  # back face (closed meshes)
        va, vb, vc = view(a), view(b), view(c)
        shade = 0.42 + 0.58 * max(0.0, sum(n[i] * light[i] for i in range(3)))
        P.append(
            ((va[2] + vb[2] + vc[2]) / 3, (va[:2], vb[:2], vc[:2]), tuple(min(255, int(x * shade)) for x in _hex(col)))
        )
    if not P:
        return None
    xs = [q[0] for _, t, _ in P for q in t]
    ys = [q[1] for _, t, _ in P for q in t]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    S = size * ss
    k = 0.9 * S / max(x1 - x0, y1 - y0, 1e-6)
    ox = (S - (x1 - x0) * k) / 2
    oy = (S - (y1 - y0) * k) / 2
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for _, t, col in sorted(P, key=lambda q: q[0]):  # far to near
        d.polygon([(ox + (x - x0) * k, S - (oy + (y - y0) * k)) for x, y in t], fill=col + (255,))
    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def block(png, w, h):
    enc = base64.b64encode(png).decode()
    rows = [enc[i : i + 78] for i in range(0, len(enc), 78)]
    return (
        f"; THUMBNAIL_BLOCK_START\n\n;\n; thumbnail begin {w}x{h} {len(enc)}\n"
        + "".join(f"; {r}\n" for r in rows)
        + "; thumbnail end\n; THUMBNAIL_BLOCK_END\n\n"
    )


def inject(gcode_path, tris, sizes=((48, 48), (300, 300))):
    """insert thumbnails after the header block (skips files that already have one). Returns the 300 px PNG."""
    with open(gcode_path, errors="ignore") as f:
        head = f.read(4096)
    if "; thumbnail begin" in head:
        return None
    pngs = {s: render(tris, s[0]) for s in sizes}
    if not all(pngs.values()):
        return None
    blocks = "".join(block(pngs[s], *s) for s in sizes)
    data = open(gcode_path, errors="ignore").read()
    i = data.find("; HEADER_BLOCK_END\n")
    i = i + len("; HEADER_BLOCK_END\n") if i >= 0 else 0
    with open(gcode_path, "w") as f:
        f.write(data[:i] + "\n" + blocks + data[i:])
    return pngs[sizes[-1]]


if __name__ == "__main__":  # self-check: a red cube renders and round-trips as a thumbnail block
    import os
    import re
    import tempfile

    cube = [((0, 0, 0), (10, 0, 0), (10, 10, 0)), ((0, 0, 10), (10, 10, 10), (10, 0, 10))]
    from threemf import primitive

    g = primitive("box", [20, 20, 20])["parts"][0]
    tris = [tuple(g["verts"][i] for i in t) + ("#E72F1D",) for t in g["tris"]]
    png = render(tris, 48)
    im = Image.open(io.BytesIO(png))
    assert im.size == (48, 48) and im.getpixel((24, 24))[3] == 255 and im.getpixel((0, 0))[3] == 0
    p = os.path.join(tempfile.mkdtemp(), "t.gcode")
    open(p, "w").write("; HEADER_BLOCK_START\n; x\n; HEADER_BLOCK_END\n\nG1 X0\n")
    inject(p, tris)
    s = open(p).read()
    m = re.search(r"; thumbnail begin 300x300 (\d+)\n((?:; .*\n)+?); thumbnail end", s)
    enc = "".join(ln[2:] for ln in m.group(2).splitlines())
    assert len(enc) == int(m.group(1))
    assert Image.open(io.BytesIO(base64.b64decode(enc))).size == (300, 300) and s.index(
        "thumbnail begin 48x48"
    ) < s.index("G1 X0")
    open("/tmp/thumb-test.png", "wb").write(base64.b64decode(enc))
    print("thumbs ok")
