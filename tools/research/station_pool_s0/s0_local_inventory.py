"""L48 S0: local, outcome-free inventory (light). Reads only already-held files; no network.

1. Station ids in one held NBP 07Z bulletin (C:\\t\\l9\\nbm_dl\\probe\\nbptx_20231117_07.txt).
2. ASOS network station metadata held from lane L6 (data\\research\\upstream_obs\\networks\\*.geojson).
3. Column list, station count and per-station row counts of L6's IEM obs.parquet (no values summarised).
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r"C:\Users\Michael\Documents\github\weather\data\research\upstream_obs")
PROBE = Path(r"C:\t\l9\nbm_dl\probe\nbptx_20231117_07.txt")
OUT = Path(r"C:\t\l48\s0_local_inventory.json")
HEADER = re.compile(r"^ ?([A-Z0-9]{3,6}) +NBM (V\S+) +NBP +GUIDANCE", re.M)

text = PROBE.read_text(encoding="ascii", errors="replace")
ids = [(m.group(1), m.group(2)) for m in HEADER.finditer(text)]
nbp_ids = sorted({i for i, _ in ids})
versions = Counter(v for _, v in ids)
prefix = Counter(i[0] if len(i) == 4 else f"len{len(i)}" for i in nbp_ids)

asos = {}
for f in sorted((ROOT / "networks").glob("*.geojson")):
    gj = json.loads(f.read_text(encoding="utf-8"))
    for feat in gj.get("features", []):
        p = feat.get("properties", {})
        sid = p.get("sid") or p.get("id")
        if not sid:
            continue
        asos[sid] = {"network": p.get("network") or f.stem, "archive_begin": p.get("archive_begin"),
                     "archive_end": p.get("archive_end"), "online": p.get("online"), "name": p.get("sname")}
asos_k = {("K" + s if len(s) == 3 else s): v for s, v in asos.items()}
both = sorted(set(nbp_ids) & set(asos_k))
begun_2021 = [s for s in both if (asos_k[s]["archive_begin"] or "9999") <= "2021-01-01"
              and (asos_k[s]["archive_end"] in (None, "") )]

res = {
    "probe_file": str(PROBE), "probe_bytes": PROBE.stat().st_size,
    "nbp_station_blocks": len(ids), "nbp_unique_ids": len(nbp_ids), "nbp_versions": dict(versions),
    "nbp_id_first_char_or_len": dict(prefix.most_common(30)),
    "network_files": len(list((ROOT / "networks").glob("*.geojson"))),
    "network_stations": len(asos), "network_names": dict(Counter(v["network"] for v in asos.values())),
    "nbp_and_held_asos": len(both), "nbp_and_held_asos_archive_from_2021_still_open": len(begun_2021),
}
try:
    import pandas as pd
    df = pd.read_parquet(ROOT / "obs.parquet")
    res["obs_columns"] = list(df.columns)
    res["obs_rows"] = int(len(df))
    key = "station" if "station" in df.columns else df.columns[0]
    res["obs_station_count"] = int(df[key].nunique())
except Exception as exc:  # noqa: BLE001
    res["obs_error"] = repr(exc)
OUT.write_text(json.dumps(res, indent=1, sort_keys=True), encoding="utf-8")
(Path(r"C:\t\l48\nbp_ids_20231117_07.txt")).write_text("\n".join(nbp_ids), encoding="utf-8")
(Path(r"C:\t\l48\nbp_and_asos_open_2021.txt")).write_text("\n".join(begun_2021), encoding="utf-8")
print(json.dumps({k: v for k, v in res.items() if k != "obs_columns"}, indent=1))
print("obs_columns:", res.get("obs_columns"))
