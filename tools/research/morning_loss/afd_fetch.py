"""L5 item 2: fetch NWS Area Forecast Discussions for the coastal WFOs from the free IEM AFOS archive.

Serial, polite (2 s between requests, identifying user agent), month-sized requests, nothing dated after
2026-09-29 (every request ends at 2026-09-30T00:00Z or earlier). Raw text lands in its own directory and is
never executed; a receipts.jsonl records url, bytes and sha256 per file.

    python tools/research/morning_loss/afd_fetch.py --out C:\\t\\l5\\afd\\raw
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import time
import urllib.request
from pathlib import Path

WFOS = {"san-francisco": "MTR", "los-angeles": "LOX", "seattle": "SEW", "nyc": "OKX", "miami": "MFL"}
LAST_END = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)
URL = ("https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=AFD{wfo}&sdate={s}&edate={e}"
       "&fmt=text&limit=9999")
UA = "weather-research/1.0 (github.com/michaelbooth1/weather; research fetch)"


def windows():
    for year in range(2021, 2026):
        for month in (7, 8, 9):
            yield dt.datetime(year, month, 1, tzinfo=dt.timezone.utc), \
                dt.datetime(year, month + 1, 1, tzinfo=dt.timezone.utc)
    yield dt.datetime(2026, 7, 1, tzinfo=dt.timezone.utc), dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc)
    yield dt.datetime(2026, 8, 1, tzinfo=dt.timezone.utc), dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
    yield dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc), LAST_END


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    receipts = out / "receipts.jsonl"
    done = set()
    if receipts.exists():
        done = {json.loads(l)["file"] for l in receipts.read_text().splitlines() if l.strip()}
    for wfo in WFOS.values():
        for s, e in windows():
            if e > LAST_END:
                raise SystemExit("refused: window past 2026-09-29")
            name = f"AFD{wfo}_{s:%Y-%m}.txt"
            if name in done:
                continue
            url = URL.format(wfo=wfo, s=s.strftime("%Y-%m-%dT%H:%MZ"), e=e.strftime("%Y-%m-%dT%H:%MZ"))
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=120) as r:
                        body = r.read()
                    break
                except Exception as exc:  # noqa: BLE001 - retry politely, then record the failure
                    err = repr(exc)
                    time.sleep(10 * (attempt + 1))
            else:
                with receipts.open("a") as f:
                    f.write(json.dumps({"file": name, "url": url, "error": err}) + "\n")
                continue
            (out / name).write_bytes(body)
            with receipts.open("a") as f:
                f.write(json.dumps({"file": name, "url": url, "bytes": len(body),
                                    "sha256": hashlib.sha256(body).hexdigest(),
                                    "fetched_utc": dt.datetime.now(dt.timezone.utc).isoformat()}) + "\n")
            print(name, len(body), flush=True)
            time.sleep(2)


if __name__ == "__main__":
    main()
