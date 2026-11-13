#!/usr/bin/env python3
"""Generate static/schema.json (print settings: Orca pages -> groups -> options, types, enums, help texts;
LANG = "cs" uses the Czech .po)
from a Snapmaker Orca source tree.  Usage: python3 tools/gen_schema.py ~/src/snapmaker-orca"""

import json
import re
import sys
from pathlib import Path

src = Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / "src/snapmaker-orca")
tab = (src / "src/slic3r/GUI/Tab.cpp").read_text()
pc = (src / "src/libslic3r/PrintConfig.cpp").read_text()
hpp = (src / "src/libslic3r/PrintConfig.hpp").read_text()
po = (src / "localization/i18n/cs/Snapmaker_Orca_cs.po").read_text()

# Czech translations (msgid -> msgstr, multi-line strings joined)
cs = {}
for m in re.finditer(r'msgid ((?:"(?:[^"\\]|\\.)*"\s*)+)msgstr ((?:"(?:[^"\\]|\\.)*"\s*)+)', po):
    j = lambda s: "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', s)).replace('\\"', '"').replace("\\n", "\n")
    if j(m[2]):
        cs[j(m[1])] = j(m[2])
LANG = "en"  # UI is English (2026-11-08); set "cs" for the Czech .po labels
tr = (lambda s: cs.get(s, s) if s else s) if LANG == "cs" else (lambda s: s)  # "" maps to the .po header

# page / group / option layout of the Print tab
body = tab[tab.index("void TabPrint::build()") :]
body = body[: body.index("\nvoid TabPrint::reload_config")]
pages, page, group = [], None, None
for m in re.finditer(
    r'add_options_page\(L\("([^"]+)"|new_optgroup\(L\("([^"]+)"|(?:append_single_option_line|get_option)\("([^"]+)"',
    body,
):
    if m[1]:
        page = {"name": tr(m[1]), "groups": []}
        pages.append(page)
        group = None
    elif m[2]:
        group = {"name": tr(m[2]), "opts": []}
        page["groups"].append(group)
    elif group is not None and m[3] not in group["opts"]:
        group["opts"].append(m[3].split("#")[0])

# per-object capable keys = PrintObjectConfig + PrintRegionConfig
objkeys = set()
for cls in ("PrintObjectConfig", "PrintRegionConfig"):
    i = hpp.index("    " + cls + ",")
    blk = hpp[i : hpp.index("\n)", i)]
    objkeys |= set(re.findall(r"\(\(ConfigOption\w+,\s*(\w+)\)\)", blk))


# option definitions
def lit(d, field):
    """def->field = L("a" "b"\n "c") -> joined, unescaped text (tooltips are often split over several literals)"""
    m = re.search(r"def\s*->\s*" + field + r'\s*=\s*L\(\s*((?:"(?:[^"\\]|\\.)*"\s*)+)\)', d)
    if not m:
        return ""
    return (
        "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', m[1])).replace('\\"', '"').replace("\\n", "\n").replace("\\t", " ")
    )


defs = {}
for m in re.finditer(
    r'def\s*=\s*this->add(?:_nullable)?\("(\w+)",\s*co(\w+)\);(.*?)(?=def\s*=\s*this->add|\Z)', pc, re.S
):
    k, t, d = m[1], m[2], m[3]
    g = lambda pat: (re.search(pat, d) or [None, None])[1]
    defs.setdefault(
        k,
        {
            "type": t,
            "label": tr(lit(d, "label") or k),
            "tip": tr(lit(d, "tooltip")),
            "side": tr(g(r'def\s*->\s*sidetext\s*=\s*(?:L\()?"([^"]*)"') or ""),
            "min": g(r"def\s*->\s*min\s*=\s*(-?[\d.]+)"),
            "max": g(r"def\s*->\s*max\s*=\s*(-?[\d.]+)"),
            "mode": g(r"def\s*->\s*mode\s*=\s*com(\w+)") or "Simple",
            "enum": re.findall(r'enum_values\.(?:push_back|emplace_back)\("([^"]*)"\)', d),
            "enum_labels": [tr(x) for x in re.findall(r'enum_labels\.(?:push_back|emplace_back)\(L?\(?"([^"]*)"', d)],
        },
    )

ROOT = Path(__file__).resolve().parents[1]
base = json.loads((ROOT / "base_project_settings.config").read_text())
# Orca has no tooltip for these
EXTRA_TIPS = {
    f"overhang_{i}_4_speed": f"Print speed for overhangs where {r} of the line width hangs over the layer below. "
    "Absolute mm/s or % of the wall speed; 0 = no slowdown."
    for i, r in [(1, "10-25 %"), (2, "25-50 %"), (3, "50-75 %"), (4, "75-100 %")]
}
SCALAR = {"Bool", "Int", "Float", "Percent", "FloatOrPercent", "Enum", "String"}
VEC = {
    "Bools": "Bool",
    "Ints": "Int",
    "Floats": "Float",
    "Percents": "Percent",
    "FloatsOrPercents": "FloatOrPercent",
}  # per-nozzle lists: one value in the UI
ok = lambda k: (
    k in defs
    and defs[k]["mode"] != "Develop"
    and (
        (defs[k]["type"] in SCALAR and isinstance(base.get(k), str))
        or (defs[k]["type"].replace("Nullable", "") in VEC and isinstance(base.get(k), list) and len(set(base[k])) == 1)
    )
)
opts, out_pages = {}, []
for p in pages:
    gs = []
    for gp in p["groups"]:
        keep = [k for k in gp["opts"] if ok(k)]
        for k in keep:
            d = defs[k]
            e = (
                list(zip(d["enum"], d["enum_labels"]))
                if len(d["enum_labels"]) == len(d["enum"])
                else [(v, v) for v in d["enum"]]
            )
            t = d["type"].replace("Nullable", "")
            opts[k] = {
                "label": d["label"]
                if d["label"] != k
                else k.replace("overhang_", "Overhang speed ").replace("_4_speed", "/4").replace("_", " "),
                "tip": d["tip"] or EXTRA_TIPS.get(k, ""),
                "type": VEC.get(t, t),
                "vec": isinstance(base.get(k), list),
                "side": d["side"],
                "min": d["min"],
                "max": d["max"],
                "enum": e or None,
                "obj": k in objkeys,
                "adv": d["mode"] != "Simple",
            }
        if keep:
            gs.append({"name": gp["name"], "opts": keep})
    if gs:
        out_pages.append({"name": p["name"], "groups": gs})

json.dump(
    {"pages": out_pages, "opts": opts},
    open(ROOT / "static/schema.json", "w"),
    ensure_ascii=False,
    separators=(",", ":"),
)
n_obj = sum(o["obj"] for o in opts.values())
assert len(opts) > 150 and n_obj > 100, (len(opts), n_obj)
print(
    len(out_pages),
    "pages",
    len(opts),
    "options,",
    n_obj,
    "per-object;",
    sum(not o["tip"] for o in opts.values()),
    "without help;",
    sum(o["adv"] for o in opts.values()),
    "advanced",
)
