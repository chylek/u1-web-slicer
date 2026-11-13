"""Colour mixing for Snapmaker Full Spectrum: FilamentMixer pigment blend (same model Snapmaker Orca uses for mixed
filament colours), CIEDE2000 distance, and best recipe search (physical filament or 2-filament mix)."""

import json
import math
from pathlib import Path

_M = json.loads((Path(__file__).parent / "static/mixer.json").read_text())
_P, _C, _I = _M["powers"], _M["coef"], _M["intercept"]


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def rgb2hex(c):
    return f"#{c[0]:02X}{c[1]:02X}{c[2]:02X}"


def lerp(c1, c2, t):
    """FilamentMixer::lerp on hex colours; t = share of c2 (0..1). Integer truncation like the C++ version."""
    a, b = hex2rgb(c1), hex2rgb(c2)
    if t <= 0:
        return rgb2hex(a)
    if t >= 1:
        return rgb2hex(b)
    x = (*a, *b, t)
    out = []
    feats = []
    for pw in _P:
        v = 1.0
        for j, e in enumerate(pw):
            if e:
                v *= x[j] ** e
        feats.append(v)
    for c in range(3):
        s = _I[c] + sum(f * _C[i][c] for i, f in enumerate(feats))
        out.append(max(0, min(255, int(s))))
    return rgb2hex(out)


def lerp_multi(colours, weights):
    """Orca blend_color_multi: weighted pairwise FilamentMixer accumulation in the given order"""
    cw = [(c, w) for c, w in zip(colours, weights) if w > 0]
    if not cw:
        return "#000000"
    acc, tot = cw[0][0], cw[0][1]
    for c, w in cw[1:]:
        acc = lerp(acc, c, w / (tot + w))
        tot += w
    return acc.upper()


def norm(ids, weights):
    """canonical recipe: components sorted by weight desc (then id), weights summing to 100"""
    t = sum(weights) or 1
    w = [round(100 * x / t) for x in weights]
    w[0] += 100 - sum(w)
    pairs = sorted(zip(ids, w), key=lambda p: (-p[1], p[0]))
    return tuple(p[0] for p in pairs), tuple(p[1] for p in pairs)


def recipe_colour(physical, ids, weights):
    ids, weights = norm(ids, weights)
    return lerp_multi([physical[i - 1] for i in ids], weights)


def _lab(h):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(c) for c in hex2rgb(h))
    X = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    Y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    Z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(X), f(Y), f(Z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def de2000(h1, h2):
    """CIEDE2000 colour difference (1 ~ just noticeable, <3 close, >10 clearly different)"""
    L1, a1, b1 = _lab(h1)
    L2, a2, b2 = _lab(h2)
    C1, C2 = math.hypot(a1, b1), math.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - math.sqrt(Cb**7 / (Cb**7 + 25**7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360
    h2p = math.degrees(math.atan2(b2, a2p)) % 360
    dL, dC = L2 - L1, C2p - C1p
    dh = (
        0
        if C1p * C2p == 0
        else (h2p - h1p if abs(h2p - h1p) <= 180 else h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360)
    )
    dH = 2 * math.sqrt(C1p * C2p) * math.sin(math.radians(dh / 2))
    Lb, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hb = (
        h1p + h2p
        if C1p * C2p == 0
        else (
            (h1p + h2p) / 2
            if abs(h1p - h2p) <= 180
            else (h1p + h2p + 360) / 2
            if h1p + h2p < 360
            else (h1p + h2p - 360) / 2
        )
    )
    T = (
        1
        - 0.17 * math.cos(math.radians(hb - 30))
        + 0.24 * math.cos(math.radians(2 * hb))
        + 0.32 * math.cos(math.radians(3 * hb + 6))
        - 0.2 * math.cos(math.radians(4 * hb - 63))
    )
    SL = 1 + 0.015 * (Lb - 50) ** 2 / math.sqrt(20 + (Lb - 50) ** 2)
    SC = 1 + 0.045 * Cbp
    SH = 1 + 0.015 * Cbp * T
    RT = -2 * math.sqrt(Cbp**7 / (Cbp**7 + 25**7)) * math.sin(math.radians(60 * math.exp(-(((hb - 275) / 25) ** 2))))
    return math.sqrt((dL / SL) ** 2 + (dC / SC) ** 2 + (dH / SH) ** 2 + RT * (dC / SC) * (dH / SH))


def mixes(physical, step=5, lo=10, hi=90, multi_step=10):
    """recipes: pairs every `step` %, plus 3- and 4-filament mixes every `multi_step` % (each component >= 10 %)"""
    import itertools

    n = len(physical)
    out = []
    for a in range(1, n + 1):
        for b in range(a + 1, n + 1):
            for p in range(lo, hi + 1, step):
                out.append(((a, b), (100 - p, p)))
    for k in (3, 4):
        for ids in itertools.combinations(range(1, n + 1), k):
            for ws in itertools.product(range(10, 100, multi_step), repeat=k - 1):
                last = 100 - sum(ws)
                if last >= 10:
                    out.append((ids, ws + (last,)))
    seen, res = set(), []
    for ids, ws in out:
        key = norm(ids, ws)
        if key in seen:
            continue
        seen.add(key)
        res.append((*key, recipe_colour(physical, *key)))
    return res


def _opt(ids, ws, colour, de):
    o = {"kind": "mix", "ids": list(ids), "weights": list(ws), "colour": colour, "de": de}
    if len(ids) == 2:
        o.update(a=ids[0], b=ids[1], pct=ws[1])  # pair fields (old clients / readable)
    return o


def candidates(target, physical, _cache={}):  # noqa: B006 - deliberate one-entry memo
    """ranked options for a target colour: physical filaments and mixes (2-4 components) with CIEDE2000 dE"""
    key = tuple(physical)
    if key not in _cache:
        _cache.clear()
        _cache[key] = mixes(physical)
    out = [
        {"kind": "phys", "ext": i + 1, "colour": c.upper(), "de": round(de2000(target, c), 1)}
        for i, c in enumerate(physical)
    ]
    out += [_opt(ids, ws, c, round(de2000(target, c), 1)) for ids, ws, c in _cache[key]]
    out.sort(key=lambda o: o["de"])
    return out


def best(target, physical, same_colour=12.0, min_gain=5.0, per_extra=1.5):
    """Pure filaments print cleaner than mixes: keep the closest filament while it is the 'same colour, other shade'
    (dE <= same_colour); otherwise take the best mix if clearly closer (min_gain). Each extra component beyond two costs
    `per_extra` dE in the ranking (more tool changes / coarser cycle)."""
    c = candidates(target, physical)
    phys = min((o for o in c if o["kind"] == "phys"), key=lambda o: o["de"])
    mixes_ = [o for o in c if o["kind"] == "mix"]
    m = min(mixes_, key=lambda o: o["de"] + per_extra * (len(o["ids"]) - 2)) if mixes_ else None
    if not m or phys["de"] <= same_colour or m["de"] > phys["de"] - min_gain:
        return phys
    return m


def palette(physical, n=16, min_de=8.0):
    """distinct, useful mixable colours (each >= min_de from the filaments and from each other): pairs 25/50/75 % first,
    then 3-filament mixes"""
    import itertools

    cand = [
        ((a, b), (100 - p, p))
        for a in range(1, len(physical) + 1)
        for b in range(a + 1, len(physical) + 1)
        for p in (25, 50, 75)
    ]
    for ids in itertools.combinations(range(1, len(physical) + 1), 3):
        cand += [(ids, (34, 33, 33)), (ids, (50, 25, 25)), (ids, (25, 50, 25)), (ids, (25, 25, 50))]
    chosen = []
    for ids, ws in cand:
        ids, ws = norm(ids, ws)
        c = recipe_colour(physical, ids, ws)
        if all(de2000(c, f) >= min_de for f in physical) and all(de2000(c, x["colour"]) >= min_de for x in chosen):
            chosen.append(_opt(ids, ws, c, 0) | {"colour": c})
    return chosen[:n]


if __name__ == "__main__":
    assert lerp("#002185", "#FCD300", 0.5) == "#2F8D38", lerp(
        "#002185", "#FCD300", 0.5
    )  # library example: blue + yellow -> (47,141,56)
    assert de2000("#FFFFFF", "#FFFFFF") == 0 and 99 < de2000("#000000", "#FFFFFF") < 101
    phys = ["#E2DEDB", "#080A0D", "#F4C032", "#E72F1D"]  # white, black, yellow, red (the U1 right now)
    o = best("#F28A27", phys)
    assert o["kind"] == "mix" and set(o["ids"]) == {3, 4}, o  # orange = yellow + red
    assert recipe_colour(phys, (3, 4), (75, 25)) == lerp(phys[2], phys[3], 0.25)  # a pair is the 2-component case
    assert any(len(x[0]) == 3 for x in mixes(phys)) and any(len(x[0]) == 4 for x in mixes(phys))
    brown = best("#7B4A2A", phys)
    print("brown ->", brown)
    assert (
        best("#E5E0DD", phys)["ext"] == 1 and best("#F0D50F", phys)["ext"] == 3
    )  # other shade of yellow stays the yellow filament
    assert best("#2E7D32", phys)["kind"] == "mix"  # green only exists as a mix
    print("colormix ok; orange ->", o, "; palette:", [x["colour"] for x in palette(phys)])
