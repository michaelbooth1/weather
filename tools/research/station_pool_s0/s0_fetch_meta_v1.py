"""L48 S0 sample fetch A (free, official, small): IEM ASOS network metadata for every US state + DC,
and three full NBM NBP 07Z bulletins (V4.0 2021, V4.2 2024, V4.3 2025, V5.0 2026 dev-input only) to count
station blocks per version. No observation or label value is read. Serial, polite, receipts with sha256.

Usage: python -I s0_fetch_meta_v1.py <out_dir>
"""
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path(sys.argv[1])
NET = "https://mesonet.agron.iastate.edu/geojson/network/{net}.geojson"
NBP = "https://noaa-nbm-grib2-pds.s3.amazonaws.com/blend.{d}/07/text/blend_nbptx.t07z"
STATES = ("AK AL AR AZ CA CO CT DC DE FL GA HI IA ID IL IN KS KY LA MA MD ME MI MN MO MS MT NC ND NE NH NJ NM NV "
          "NY OH OK OR PA RI SC SD TN TX UT VA VT WA WI WV WY").split()
NBP_DATES = ("20210815", "20241015", "20251015", "20260815")


def get(s, url):
    for attempt in range(4):
        try:
            r = s.get(url, timeout=120)
            if r.status_code in (200, 404):
                return r
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    raise RuntimeError(url)


def main():
    (OUT / "networks").mkdir(parents=True, exist_ok=True)
    (OUT / "nbp").mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    receipts = (OUT / "receipts.jsonl").open("a", encoding="utf-8")
    jobs = [(NET.format(net=f"{st}_ASOS"), OUT / "networks" / f"{st}_ASOS.geojson") for st in STATES]
    jobs += [(NBP.format(d=d), OUT / "nbp" / f"nbptx_{d}_07.txt") for d in NBP_DATES]
    for url, path in jobs:
        if path.exists():
            continue
        r = get(s, url)
        body = r.content if r.status_code == 200 else b""
        if body:
            path.write_bytes(body)
        rec = {"url": url, "status": r.status_code, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
               "file": str(path), "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        receipts.write(json.dumps(rec) + "\n")
        receipts.flush()
        print(rec["status"], rec["bytes"], url, flush=True)
        time.sleep(1.0)


if __name__ == "__main__":
    main()
