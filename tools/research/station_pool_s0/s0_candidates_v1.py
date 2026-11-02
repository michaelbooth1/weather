"""L48 S0 B: candidate station counts (outcome-free; metadata and NBP station headers only).

Usage: python -I s0_candidates_v1.py <dl_meta_dir> <held_probe_2023_bulletin> <out_dir>
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

META, PROBE23, OUT = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
HEADER = re.compile(r"^ ?([A-Z0-9]{3,6}) +NBM (V\S+) +NBP +GUIDANCE", re.M)
MARKETS = {"KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO"}
NON_CONUS = {"AK", "HI"}

bulletins = {"2021_V4.0": META / "nbp" / "nbptx_20210815_07.txt", "2023_V4.1": PROBE23,
             "2024_V4.2": META / "nbp" / "nbptx_20241015_07.txt", "2025_V4.3": META / "nbp" / "nbptx_20251015_07.txt",
             "2026_V5.0": META / "nbp" / "nbptx_20260815_07.txt"}
nbp = {}
versions = {}
for tag, p in bulletins.items():
    t = p.read_text(encoding="ascii", errors="replace")
    hits = [(m.group(1), m.group(2)) for m in HEADER.finditer(t)]
    nbp[tag] = {i for i, _ in hits}
    versions[tag] = dict(Counter(v for _, v in hits))

stations = {}
for f in sorted((META / "networks").glob("*_ASOS.geojson")):
    for feat in json.loads(f.read_text(encoding="utf-8"))["features"]:
        p = feat["properties"]
        sid = p["sid"]
        icao = "K" + sid if len(sid) == 3 and p.get("state") not in NON_CONUS else sid
        lon, lat = feat["geometry"]["coordinates"][:2]
        stations[icao] = {"sid": sid, "state": p.get("state"), "network": p.get("network"), "lat": lat, "lon": lon,
                          "elev_m": p.get("elevation"), "tz": p.get("tzname"), "begin": p.get("archive_begin"),
                          "end": p.get("archive_end"), "online": bool(p.get("online")),
                          "is_awos": str((p.get("attributes") or {}).get("IS_AWOS", "0")) == "1",
                          "reset_minute": (p.get("attributes") or {}).get("METAR_RESET_MINUTE")}

all5 = set.intersection(*nbp.values())
tiers = Counter()
cands = []
for icao, s in stations.items():
    tiers["iem_asos_network_rows"] += 1
    if s["state"] in NON_CONUS:
        continue
    tiers["a_conus"] += 1
    if not (icao.startswith("K") and len(icao) == 4):
        continue
    tiers["b_k_icao"] += 1
    if not (s["online"] and not s["end"]):
        continue
    tiers["c_online_open"] += 1
    if not (s["begin"] and s["begin"] <= "2021-01-01"):
        continue
    tiers["d_archive_from_2021"] += 1
    if icao not in nbp["2021_V4.0"]:
        continue
    tiers["e_in_nbp_v4.0_2021"] += 1
    if icao not in all5:
        continue
    tiers["f_in_all_5_nbp_versions"] += 1
    if s["is_awos"]:
        tiers["f_awos_flagged"] += 1
        continue
    tiers["g_not_awos"] += 1
    cands.append(icao)

res = {"nbp_unique_ids": {k: len(v) for k, v in nbp.items()}, "nbp_versions": versions,
       "nbp_k_ids": {k: sum(1 for i in v if i.startswith("K") and len(i) == 4) for k, v in nbp.items()},
       "nbp_ids_in_all_5": len(all5), "tiers": dict(tiers), "candidates": len(cands),
       "markets_in_candidates": sorted(MARKETS & set(cands)), "markets_missing": sorted(MARKETS - set(cands)),
       "candidates_by_state": dict(Counter(stations[c]["state"] for c in cands).most_common()),
       "candidates_reset_minute": dict(Counter(str(stations[c]["reset_minute"]) for c in cands).most_common(8))}
for m in sorted(MARKETS - set(cands)):
    s = stations.get(m)
    res.setdefault("market_reasons", {})[m] = None if s is None else {
        k: s[k] for k in ("online", "end", "begin", "is_awos")} | {"nbp_all5": m in all5}
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "s0_candidates.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
(OUT / "s0_candidate_stations.json").write_text(json.dumps({c: stations[c] for c in sorted(cands)}, indent=1),
                                                encoding="utf-8")
print(json.dumps(res, indent=1))
