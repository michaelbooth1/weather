"""L48 S0: NBP 07Z object availability per year from lane L9's held fetch log (metadata only; no forecast values read)."""
import json
import re
from collections import defaultdict
from pathlib import Path

SRC = Path(r"C:\t\l9\nbm_dl\nbp07\nbp_station_blocks.jsonl")
VER = re.compile(r"NBM (V\S+) +NBP")
by_year = defaultdict(lambda: {"dates": 0, "object": 0, "station_blocks": 0, "station_missing": 0,
                               "sizes": [], "versions": defaultdict(int)})
for line in SRC.read_text(encoding="utf-8").splitlines():
    r = json.loads(line)
    y = by_year[r["utc_date"][:4]]
    y["dates"] += 1
    if r.get("object"):
        y["object"] += 1
        y["sizes"].append(r["object"]["size"])
    for st, blk in (r.get("stations") or {}).items():
        if blk:
            y["station_blocks"] += 1
            m = VER.search(blk["block"][:200])
            if m:
                y["versions"][m.group(1)] += 1
        else:
            y["station_missing"] += 1
out = {}
for k, v in sorted(by_year.items()):
    s = sorted(v.pop("sizes"))
    v["size_mb_min_med_max"] = [round(s[0] / 1e6, 1), round(s[len(s) // 2] / 1e6, 1), round(s[-1] / 1e6, 1)] if s else None
    v["versions"] = dict(v["versions"])
    out[k] = v
print(json.dumps(out, indent=1))
Path(r"C:\t\l48\s0_l9_availability.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
