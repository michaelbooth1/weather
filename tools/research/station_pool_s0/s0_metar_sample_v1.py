"""L48 S0 C: small IEM METAR availability sample (free, official). 12 candidate stations chosen by a fixed
outcome-free rule (sorted ICAO, markets and Gulf platforms excluded, every k-th), UTC 2023-08-01..2024-01-01 12Z,
routine (report_type=3) and special (=4) fetched separately with raw text, as the venue_rule_labels layout does.
Measures only availability: bytes, report counts, label-complete local days (no gap > 180 min, midnight to
midnight), routine T-group share. No temperature value is summarised.

Usage: python -I s0_metar_sample_v1.py <candidate_stations.json> <out_dir>
"""
import csv
import hashlib
import io
import json
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

CANDS, OUT = Path(sys.argv[1]), Path(sys.argv[2])
URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
MARKETS = {"KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO"}
STS, ETS = datetime(2023, 8, 1, tzinfo=timezone.utc), datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
FIRST, LAST = date(2023, 8, 1), date(2023, 12, 31)
TGROUP = re.compile(r"\bT[01]\d{3}([01]\d{3})?\b")
N = 12

stations = json.loads(CANDS.read_text(encoding="utf-8"))
pool = [k for k in sorted(stations) if k not in MARKETS and stations[k]["state"] != "GM"]
step = len(pool) // N
sample = [pool[i * step + step // 2] for i in range(N)]


def fetch(s, sid, rtype):
    params = [("station", sid), ("data", "tmpf"), ("data", "metar"), ("tz", "Etc/UTC"), ("format", "onlycomma"),
              ("latlon", "no"), ("missing", "M"), ("trace", "T"), ("direct", "no"), ("report_type", str(rtype)),
              ("sts", STS.strftime("%Y-%m-%dT%H:%MZ")), ("ets", ETS.strftime("%Y-%m-%dT%H:%MZ"))]
    url = f"{URL}?{urlencode(params)}"
    for attempt in range(4):
        try:
            r = s.get(url, timeout=180)
            if r.status_code == 200:
                return url, r.content
        except requests.RequestException:
            pass
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(url)


def main():
    (OUT / "raw").mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    receipts = (OUT / "receipts.jsonl").open("a", encoding="utf-8")
    summary = {"sample": sample, "pool": len(pool), "window_utc": [STS.isoformat(), ETS.isoformat()], "stations": {}}
    for icao in sample:
        st = stations[icao]
        tz = ZoneInfo(st["tz"])
        per = {}
        rows_by_type = {}
        for rtype in (3, 4):
            path = OUT / "raw" / f"{icao}_rt{rtype}_2023.csv"
            if path.exists():
                body = path.read_bytes()
                url = "(cached)"
            else:
                url, body = fetch(s, st["sid"], rtype)
                path.write_bytes(body)
                receipts.write(json.dumps({"url": url, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                                           "file": str(path),
                                           "fetched_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")
                receipts.flush()
                time.sleep(5)
            rows = [r for r in csv.DictReader(io.StringIO(body.decode("utf-8", "replace"))) if r.get("valid")]
            rows_by_type[rtype] = rows
            per[f"rt{rtype}_bytes"] = len(body)
            per[f"rt{rtype}_rows"] = len(rows)
        routine = rows_by_type[3]
        per["rt3_tmpf_missing"] = sum(1 for r in routine if r.get("tmpf") in ("M", "", None))
        per["rt3_tgroup_share"] = round(sum(1 for r in routine if TGROUP.search(r.get("metar") or "")) / max(1, len(routine)), 4)
        per["rt3_minute_mode"] = max(set(r["valid"][14:16] for r in routine), key=[r["valid"][14:16] for r in routine].count) if routine else None
        per["rt3_rows_with_SPECI_prefix"] = sum(1 for r in routine if (r.get("metar") or "").startswith("SPECI"))
        # label-complete local days: routine reports with a temperature, max gap <= 180 min midnight to midnight
        times = sorted(datetime.strptime(r["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).astimezone(tz)
                       for r in routine if r.get("tmpf") not in ("M", "", None))
        by_day = {}
        for t in times:
            by_day.setdefault(t.date(), []).append(t)
        complete = 0
        d = FIRST
        while d <= LAST:
            ts = by_day.get(d, [])
            if ts:
                start = datetime(d.year, d.month, d.day, tzinfo=tz)
                end = start + timedelta(days=1)
                edges = [start] + ts + [end]
                gap = max((b - a).total_seconds() / 60 for a, b in zip(edges, edges[1:]))
                complete += gap <= 180 and len(ts) >= 18
            d += timedelta(days=1)
        per["local_days"] = (LAST - FIRST).days + 1
        per["label_complete_days"] = complete
        per["state"], per["reset_minute"] = st["state"], st["reset_minute"]
        summary["stations"][icao] = per
        print(icao, json.dumps(per), flush=True)
    tot = summary["stations"].values()
    summary["totals"] = {"bytes": sum(v["rt3_bytes"] + v["rt4_bytes"] for v in tot),
                         "complete_days": sum(v["label_complete_days"] for v in tot),
                         "local_days": sum(v["local_days"] for v in tot)}
    (OUT / "s0_metar_sample.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary["totals"]))


if __name__ == "__main__":
    main()
