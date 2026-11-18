"""Candy-cane stripes on the live u1web server: erase paint on a part, then paint diagonal bands (slab selector).
usage: candy_stripes.py OBJ PART FILAMENT LO HI PERIOD WIDTH NX NY NZ
(LO..HI = d range along the unit normal, world mm)"""

import json
import math
import sys
import urllib.request


def post(o):
    r = urllib.request.Request(
        "http://127.0.0.1:3060/api/op", json.dumps(o).encode(), {"Content-Type": "application/json"}
    )
    try:
        return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e:
        return {"msg": e.read().decode()}


obj, part, fil = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
lo, hi, per, w = (float(x) for x in sys.argv[4:8])
n = [float(x) for x in sys.argv[8:11]]
ln = math.hypot(*n)
n = [c / ln for c in n]
print(
    post({"op": "paint_region", "id": obj, "part": part, "filament": 0, "box": {"min": [-1e4] * 3, "max": [1e4] * 3}})
)
d = lo
while d < hi:
    print(
        post(
            {
                "op": "paint_region",
                "id": obj,
                "part": part,
                "filament": fil,
                "slab": {"normal": n, "d_min": d, "d_max": d + w},
            }
        )["msg"]
    )
    d += per
