"""L48 S0 D: per-NBM-version parse check of candidate stations with the canonical parser v2 (outcome-free:
counts only whether a usable same-day v2 mean and stddev parse; no value is summarised).

Usage: python -I s0_nbp_parse_v1.py <repo_src> <dl_meta_dir> <held_2023_bulletin> <candidate_stations.json> <out_json>
"""
import json
import math
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import weather.sources.nbm_probabilistic_tmax as nbp_mod  # noqa: E402
from weather.sources.nbm_probabilistic_tmax import parse_nbp_station_tmax  # noqa: E402

META, P23, CANDS, OUT = Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]), Path(sys.argv[5])
HEADER = re.compile(r"^ ?([A-Z0-9]{3,6}) +NBM V\S+ +NBP +GUIDANCE", re.M)
files = {"2021_V4.0": (META / "nbp" / "nbptx_20210815_07.txt", date(2021, 8, 15)),
         "2023_V4.1": (P23, date(2023, 11, 17)),
         "2024_V4.2": (META / "nbp" / "nbptx_20241015_07.txt", date(2024, 10, 15)),
         "2025_V4.3": (META / "nbp" / "nbptx_20251015_07.txt", date(2025, 10, 15)),
         "2026_V5.0": (META / "nbp" / "nbptx_20260815_07.txt", date(2026, 8, 15))}
meta = json.loads(CANDS.read_text(encoding="utf-8"))
cands = sorted(k for k, v in meta.items() if v["state"] != "GM")
# research-only, in-process: give the parser each candidate's IEM zone (built-ins keep theirs)
for k in cands:
    nbp_mod.NBM_NBP_STATION_TIMEZONES.setdefault(k, meta[k]["tz"])
res = {"candidates_ex_gulf": len(cands), "by_version": {}}
for tag, (path, target) in files.items():
    text = path.read_text(encoding="ascii", errors="replace")
    heads = [(m.group(1), m.start()) for m in HEADER.finditer(text)]
    blocks = {sid: text[a: (heads[i + 1][1] if i + 1 < len(heads) else len(text))] for i, (sid, a) in enumerate(heads)}
    c = Counter()
    sizes = []
    for st in cands:
        blk = blocks.get(st)
        if blk is None:
            c["no_block"] += 1
            continue
        sizes.append(len(blk))
        try:
            out = parse_nbp_station_tmax(blk, st, target)
        except Exception as exc:  # noqa: BLE001
            c[f"error:{type(exc).__name__}"] += 1
            continue
        mean, sd = out.get("mean_native"), out.get("stddev_native")
        ok = mean is not None and sd is not None and math.isfinite(float(mean)) and math.isfinite(float(sd))
        c["usable_mean_sd" if ok and out.get("available") else f"unusable:{out.get('reason')}"] += 1
    sizes.sort()
    res["by_version"][tag] = {"counts": dict(c), "block_bytes_median": sizes[len(sizes) // 2] if sizes else None,
                              "file_bytes": path.stat().st_size}
OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
print(json.dumps(res, indent=1))

