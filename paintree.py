"""Orca/PrusaSlicer TriangleSelector paint trees (the per-triangle `paint_color` hex string in 3MF).

A triangle's code is a bitstream of nibbles, stored as hex with the FIRST nibble LAST in the string. Node nibble:
  low 2 bits = number of split sides (0 = leaf), high 2 bits = special side (split) or state (leaf, 0-2; 3 = state >= 3,
  followed by nibbles: 0xF = +15 and continue, else value; state = 3 + 15*k + value).
Children of a split node follow depth-first in REVERSE child order. Child geometry = TriangleSelector::perform_split.
Lets us paint finer than the mesh without changing it — exactly what Orca does."""

import math

MAX_DEPTH = 10


# ---------- codec
def decode(code):
    if not code:
        return {"s": 0}
    it = iter(int(c, 16) for c in reversed(code))

    def node():
        c = next(it)
        n = c & 3
        if n:
            kids = [None] * (n + 1)
            for i in range(n, -1, -1):
                kids[i] = node()
            return {"n": n, "k": c >> 2, "c": kids}
        if c & 0b1100 == 0b1100:
            k, v = 0, next(it)
            while v == 15:
                k += 1
                v = next(it)
            return {"s": 3 + 15 * k + v}
        return {"s": c >> 2}

    return node()


def encode(node):
    """-> hex string, or None for an unpainted unsplit triangle"""
    nibs = []

    def put(nd):
        if "c" in nd:
            nibs.append(nd["n"] | (nd["k"] << 2))
            for i in range(nd["n"], -1, -1):
                put(nd["c"][i])
        elif nd["s"] < 3:
            nibs.append(nd["s"] << 2)
        else:
            nibs.append(0b1100)
            v = nd["s"] - 3
            while v >= 15:
                nibs.append(15)
                v -= 15
            nibs.append(v)

    if "c" not in node and node["s"] == 0:
        return None
    put(node)
    return "".join(f"{n:X}" for n in reversed(nibs))


# ---------- geometry
def _mid(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)


def children_tris(v, node):
    """child triangles of a split node, in child-index order (mirrors perform_split)"""
    k = node["k"]
    L = [v[(k + j) % 3] for j in range(3)]
    n = node["n"]
    if n == 1:
        L.insert(2, _mid(L[2], L[1]))
        return [(L[0], L[1], L[2]), (L[2], L[3], L[0])]
    if n == 2:
        L.insert(1, _mid(L[1], L[0]))
        L.insert(4, _mid(L[0], L[3]))
        return [(L[0], L[1], L[4]), (L[1], L[2], L[4]), (L[2], L[3], L[4])]
    L.insert(1, _mid(L[1], L[0]))
    L.insert(3, _mid(L[3], L[2]))
    L.insert(5, _mid(L[0], L[4]))
    return [(L[0], L[1], L[5]), (L[1], L[2], L[3]), (L[3], L[4], L[5]), (L[1], L[3], L[5])]


def leaves(node, v):
    """[(tri, state)] for a decoded tree on triangle v"""
    if "c" not in node:
        return [(v, node["s"])]
    out = []
    for cv, cn in zip(children_tris(v, node), node["c"]):
        out += leaves(cn, cv)
    return out


def _longest(v):
    return max(math.dist(v[0], v[1]), math.dist(v[1], v[2]), math.dist(v[2], v[0]))


def paint(node, v, classify, state, detail, depth=0):
    """Repaint a tree. classify(tri) -> 1 fully inside, 0 fully outside, -1 crosses the region border.
    Border triangles are split (3-side, like Orca's brush) until their longest edge <= detail. Returns the new node."""
    c = classify(v)
    if c == 0:
        return node
    if c == 1 or (c == -1 and (_longest(v) <= detail or depth >= MAX_DEPTH)):
        if c == -1 and "c" not in node:  # small border triangle: decide by its centre
            ce = tuple(sum(p[i] for p in v) / 3 for i in range(3))
            return {"s": state} if classify((ce, ce, ce)) == 1 else node
        if c == 1:
            return {"s": state}
    if "c" not in node:
        node = {"n": 3, "k": 0, "c": [{"s": node["s"]} for _ in range(4)]}
    kids = [paint(cn, cv, classify, state, detail, depth + 1) for cv, cn in zip(children_tris(v, node), node["c"])]
    if all("c" not in x for x in kids) and len({x["s"] for x in kids}) == 1:
        return {"s": kids[0]["s"]}  # merge uniform children
    return dict(node, c=kids)


def remap(code, f):
    """map every leaf state through f (0 = unpainted stays 0); returns a new code"""
    if not code:
        return code

    def m(nd):
        return dict(nd, c=[m(x) for x in nd["c"]]) if "c" in nd else {"s": f(nd["s"]) if nd["s"] else 0}

    return encode(m(decode(code)))


def used_states(code):
    nd = decode(code)
    out = set()

    def walk(x):
        if "c" in x:
            for y in x["c"]:
                walk(y)
        elif x["s"]:
            out.add(x["s"])

    walk(nd)
    return out


def state_of(node):
    """uniform state of a tree, or 255 when it is split"""
    return 255 if "c" in node else node["s"]


# ---------- region classifiers (triangle -> 1 inside / 0 outside / -1 border)
def closest_point_on_triangle(p, a, b, c):
    """Ericson, Real-Time Collision Detection 5.1.5"""
    sub = lambda x, y: (x[0] - y[0], x[1] - y[1], x[2] - y[2])
    dot = lambda x, y: x[0] * y[0] + x[1] * y[1] + x[2] * y[2]
    add = lambda x, y, s: (x[0] + y[0] * s, x[1] + y[1] * s, x[2] + y[2] * s)
    ab, ac, ap = sub(b, a), sub(c, a), sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return a
    bp = sub(p, b)
    d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        return add(a, ab, d1 / (d1 - d3))
    cp = sub(p, c)
    d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        return add(a, ac, d2 / (d2 - d6))
    va = d3 * d6 - d5 * d4
    if va <= 0 and d4 - d3 >= 0 and d5 - d6 >= 0:
        return add(b, sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6)))
    den = 1 / (va + vb + vc)
    v_, w_ = vb * den, vc * den
    return (a[0] + ab[0] * v_ + ac[0] * w_, a[1] + ab[1] * v_ + ac[1] * w_, a[2] + ab[2] * v_ + ac[2] * w_)


def sphere(center, r):
    def cl(v):
        if all(math.dist(p, center) <= r for p in v):
            return 1
        return 0 if math.dist(closest_point_on_triangle(center, *v), center) > r else -1

    return cl


def box(lo, hi):
    def cl(v):
        if all(all(lo[i] <= p[i] <= hi[i] for i in range(3)) for p in v):
            return 1
        if any(all(p[i] < lo[i] for p in v) or all(p[i] > hi[i] for p in v) for i in range(3)):
            return 0
        return -1  # ponytail: AABB overlap counts as border (conservative, just splits a bit more)

    return cl


def both(*cls):
    """AND of classifiers"""

    def cl(v):
        r = [f(v) for f in cls]
        return 0 if 0 in r else (1 if all(x == 1 for x in r) else -1)

    return cl


if __name__ == "__main__":  # self-check: python3 paintree.py [file.3mf]
    import re
    import sys
    import zipfile

    for code in ["4", "8", "0C", "1C", "2C", "0FC", "88083", "1C0C2C0C1C13"]:
        assert encode(decode(code)) == code, code
    if len(sys.argv) > 1:  # every code in a real Orca 3MF round-trips exactly
        z = zipfile.ZipFile(sys.argv[1])
        codes = set()
        for n in z.namelist():
            if n.endswith(".model"):
                codes |= set(re.findall(r'paint_color="([0-9A-F]+)"', z.read(n).decode()))
        bad = [c for c in codes if encode(decode(c)) != c]
        assert not bad, bad[:5]
        print(len(codes), "distinct codes round-trip")
    tri = ((0, 0, 0), (10, 0, 0), (0, 10, 0))
    nd = paint({"s": 0}, tri, sphere((0, 0, 0), 4), 2, 0.5)  # quarter disc at the corner
    lv = leaves(nd, tri)
    area = lambda v: abs((v[1][0] - v[0][0]) * (v[2][1] - v[0][1]) - (v[2][0] - v[0][0]) * (v[1][1] - v[0][1])) / 2
    painted = sum(area(v) for v, s in lv if s == 2)
    assert abs(painted - math.pi * 16 / 4) < 1.5, painted  # ~12.57 mm² of the 50 mm² triangle
    assert abs(sum(area(v) for v, _ in lv) - 50) < 1e-6  # leaves tile the triangle
    assert decode(encode(nd)) == nd
    assert paint(nd, tri, sphere((0, 0, 0), 100), 2, 0.5) == {"s": 2}  # covering everything merges back to one leaf
    print("paintree ok:", len(lv), "leaves, painted", round(painted, 2), "mm2")
