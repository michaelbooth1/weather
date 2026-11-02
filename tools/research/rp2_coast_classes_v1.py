"""R-P2 outcome-blind classes: distance to Natural Earth 10m coastline (plain-Python shapefile reader).

Usage: python -I rp2_coast_classes_v1.py <ne_10m_coastline.zip> <stations_meta.json> <station_set.json> <out.json>
Reads only station metadata (IEM lat/lon) and the coastline geometry. No label, residual or score is read.
"""
import json, math, struct, sys, zipfile
from collections import defaultdict

MARKETS = {"KATL": "atlanta", "KAUS": "austin", "KORD": "chicago", "KDAL": "dallas", "KBKF": "denver",
           "KHOU": "houston", "KLAX": "los-angeles", "KMIA": "miami", "KLGA": "nyc", "KSFO": "san-francisco",
           "KSEA": "seattle"}
THRESH_KM = 25.0
R_KM = 6371.0088


def read_polylines(zpath):
    with zipfile.ZipFile(zpath) as z:
        name = [n for n in z.namelist() if n.endswith(".shp")][0]
        data = z.read(name)
    assert struct.unpack(">i", data[0:4])[0] == 9994
    shape_type = struct.unpack("<i", data[32:36])[0]
    assert shape_type == 3, shape_type
    pos, lines = 100, []
    while pos < len(data):
        _, clen = struct.unpack(">ii", data[pos:pos + 8])
        rec = data[pos + 8: pos + 8 + clen * 2]
        pos += 8 + clen * 2
        st = struct.unpack("<i", rec[0:4])[0]
        if st == 0:
            continue
        nparts, npts = struct.unpack("<ii", rec[36:44])
        parts = list(struct.unpack(f"<{nparts}i", rec[44:44 + 4 * nparts])) + [npts]
        off = 44 + 4 * nparts
        pts = struct.unpack(f"<{2 * npts}d", rec[off:off + 16 * npts])
        for a, b in zip(parts, parts[1:]):
            lines.append([(pts[2 * i], pts[2 * i + 1]) for i in range(a, b)])
    return lines


def index_segments(lines):
    grid = defaultdict(list)
    for line in lines:
        for p, q in zip(line, line[1:]):
            for cx in range(math.floor(min(p[0], q[0])), math.floor(max(p[0], q[0])) + 1):
                for cy in range(math.floor(min(p[1], q[1])), math.floor(max(p[1], q[1])) + 1):
                    grid[(cx, cy)].append((p, q))
    return grid


def coast_km(lat, lon, grid):
    best = float("inf")
    for radius in (1, 2, 4, 8):
        kx = 111.195 * math.cos(math.radians(lat))
        ky = 111.195
        seen = 0
        for cx in range(math.floor(lon) - radius, math.floor(lon) + radius + 1):
            for cy in range(math.floor(lat) - radius, math.floor(lat) + radius + 1):
                for p, q in grid.get((cx, cy), ()):
                    seen += 1
                    ax, ay = (p[0] - lon) * kx, (p[1] - lat) * ky
                    bx, by = (q[0] - lon) * kx, (q[1] - lat) * ky
                    dx, dy = bx - ax, by - ay
                    L = dx * dx + dy * dy
                    t = 0.0 if L == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L))
                    d = math.hypot(ax + t * dx, ay + t * dy)
                    best = min(best, d)
        # a hit inside the searched box is final only if it is closer than the box's inner half-width
        if best <= radius * 111.195 * math.cos(math.radians(abs(lat) + radius)):
            return best
    return best


def main():
    zpath, meta_path, set_path, out_path = sys.argv[1:5]
    meta = json.load(open(meta_path, encoding="utf-8"))
    station_set = json.load(open(set_path, encoding="utf-8"))
    pool, dose = station_set["survivors"], set(station_set["dose_subset"])
    grid = index_segments(read_polylines(zpath))
    stations = {}
    for icao in list(MARKETS) + pool:
        km = coast_km(float(meta[icao]["lat"]), float(meta[icao]["lon"]), grid)
        stations[icao] = {"coast_km": round(km, 2), "class": "marine" if km <= THRESH_KM else "continental",
                          "near_threshold_20_30km": 20.0 <= km <= 30.0}
    counts = {c: sum(1 for s in pool if stations[s]["class"] == c) for c in ("marine", "continental")}
    counts100 = {c: sum(1 for s in pool if s in dose and stations[s]["class"] == c) for c in ("marine", "continental")}
    markets = {}
    for icao, name in MARKETS.items():
        c = stations[icao]["class"]
        markets[name] = {"icao": icao, "coast_km": stations[icao]["coast_km"], "class": c,
                         "pool_stations_rp": 300, "pool_stations_rp2": counts[c], "change": counts[c] - 300,
                         "pool100_rp2": counts100[c]}
    out = {"threshold_km": THRESH_KM, "pool_counts": counts, "pool100_counts": counts100, "markets": markets,
           "pool_near_threshold": sorted(s for s in pool if stations[s]["near_threshold_20_30km"]),
           "stations": stations}
    json.dump(out, open(out_path, "w", encoding="utf-8"), indent=1, sort_keys=True)
    print(json.dumps({k: out[k] for k in ("pool_counts", "pool100_counts", "markets", "pool_near_threshold")}, indent=1))


if __name__ == "__main__":
    main()
