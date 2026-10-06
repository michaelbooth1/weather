"""T24 (spare): independent primary-source re-measurement of NBS (blend_nbstx) availability.

Development only; registers no rules, scores nothing. Anonymous HTTPS to the public NODD bucket
noaa-nbm-grib2-pds (no credentials, no boto3), sequential, <= ~6 req/s.

For every cycle 2026-07-25..09-29 00-23Z:
  1. ListObjectsV2 prefix blend.YYYYMMDD/HH/text/  -> LastModified/ETag/Size of every text product
     (sibling bulletins nbhtx/nbetx/nbxtx/nbptx... give an independent same-cycle publication clock).
  2. HEAD blend_nbstx.tHHz -> HTTP Last-Modified / ETag (independent of the A-NBH fetch).
For the anomalous dates in the A-NBH manifest plus two control dates, also list the whole cycle prefix
(core GRIB etc.) to see whether the whole cycle was late or only the text bulletins.
Run with C:\\swarm\\venv\\Scripts\\python.exe; output C:\\swarm\\out\\t24\\s3_remeasure.jsonl (resumable).
"""
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

BASE = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
OUT = Path(r"C:\swarm\out\t24\s3_remeasure.jsonl")
FULL_OUT = Path(r"C:\swarm\out\t24\s3_fullcycle.jsonl")
NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
FULL_DATES = {"2026-08-31", "2026-09-14", "2026-09-23", "2026-09-24", "2026-08-10", "2026-09-05"}
S = requests.Session()
MIN_GAP = 0.17


def stop():
    if Path(r"C:\swarm\STOP").exists():
        sys.exit("STOP present")


_last = [0.0]


def get(url, method="GET", **kw):
    for attempt in range(6):
        wait = MIN_GAP - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = S.request(method, url, timeout=60, **kw)
        except requests.RequestException:
            time.sleep(2 ** attempt)
            continue
        if r.status_code in (429, 500, 503):
            time.sleep(2 ** attempt * 2)
            continue
        return r
    raise RuntimeError(f"failed {url}")


def list_prefix(prefix):
    keys, token = [], None
    while True:
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        if token:
            params["continuation-token"] = token
        r = get(BASE + "/", params=params)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        for c in root.findall("s:Contents", NS):
            keys.append({"key": c.find("s:Key", NS).text, "lm": c.find("s:LastModified", NS).text,
                         "etag": c.find("s:ETag", NS).text.strip('"'), "size": int(c.find("s:Size", NS).text)})
        if root.find("s:IsTruncated", NS).text == "true":
            token = root.find("s:NextContinuationToken", NS).text
        else:
            return keys


def main():
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done.add((r["date"], r["cycle"]))
    fdone = set()
    if FULL_OUT.exists():
        for line in FULL_OUT.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            fdone.add((r["date"], r["cycle"]))
    d = date(2026, 7, 25)
    while d <= date(2026, 9, 29):
        for hh in range(24):
            stop()
            ds, ymd = d.isoformat(), d.strftime("%Y%m%d")
            if (ds, hh) not in done:
                text = list_prefix(f"blend.{ymd}/{hh:02d}/text/")
                key = f"blend.{ymd}/{hh:02d}/text/blend_nbstx.t{hh:02d}z"
                hr = get(f"{BASE}/{key}", method="HEAD")
                head = {"status": hr.status_code}
                if hr.status_code == 200:
                    head.update({"last_modified": parsedate_to_datetime(hr.headers["Last-Modified"]).isoformat(),
                                 "etag": hr.headers.get("ETag", "").strip('"'),
                                 "bytes": int(hr.headers.get("Content-Length", -1)),
                                 "date_hdr": hr.headers.get("Date")})
                rec = {"date": ds, "cycle": hh, "nbs_key": key, "head": head, "text_listing": text}
                with OUT.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
            if ds in FULL_DATES and (ds, hh) not in fdone:
                allk = list_prefix(f"blend.{ymd}/{hh:02d}/")
                by_dir = {}
                for k in allk:
                    sub = k["key"].split("/")[2] if k["key"].count("/") >= 3 else "."
                    b = by_dir.setdefault(sub, {"n": 0, "min_lm": k["lm"], "max_lm": k["lm"], "bytes": 0})
                    b["n"] += 1
                    b["bytes"] += k["size"]
                    b["min_lm"] = min(b["min_lm"], k["lm"])
                    b["max_lm"] = max(b["max_lm"], k["lm"])
                with FULL_OUT.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"date": ds, "cycle": hh, "n_keys": len(allk), "by_dir": by_dir}) + "\n")
        print(d, flush=True)
        d += timedelta(days=1)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
