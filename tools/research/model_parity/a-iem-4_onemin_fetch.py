"""A-IEM-4: IEM 1-minute ASOS (asos1min.py) tmpf for the 11 swarm stations.

TRUTH / LABEL USE ONLY. 1-minute ASOS is NOT point in time (NCEI archive, 18-36 h+ delay);
it must never be a candidate input (DESIGN hard rule 1).

Window: local target days 2026-07-25..2026-09-29 per station time zone
(UTC request window = local midnight 07-25 .. local midnight 09-30, per station).
IEM lane politeness: one connection, sequential, >= 2 s between requests, back off on 429/503 or
"Too many requests" body text (60 s, doubling). Freeze at 04:30 local.
Run with C:\\swarm\\venv\\Scripts\\python.exe.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

OUT = Path(r"C:\swarm\data\iem\onemin")
RAW = OUT / "raw"
LOG = OUT / "fetch.log"
STOP = Path(r"C:\swarm\STOP")
STATIONS = json.loads(Path(r"C:\swarm\stations.json").read_text())["stations"]
BASE = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py"
URL_PATTERN = (BASE + "?station={iem_id}&vars=tmpf&sts={sts}&ets={ets}&sample=1min&what=download"
               "&tz=UTC&delim=comma&gis=no")
FIRST_DAY = datetime(2026, 7, 25)
LAST_DAY = datetime(2026, 9, 29)
SPACING_S = 2.0
NL = b"\n"
FREEZE = datetime.now().replace(hour=4, minute=30, second=0, microsecond=0)
if datetime.now().hour >= 12:  # started before midnight (not expected)
    FREEZE += timedelta(days=1)


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def chunks_for(st: dict):
    tz = ZoneInfo(st["tzname"])
    start = FIRST_DAY.replace(tzinfo=tz).astimezone(timezone.utc)
    end = (LAST_DAY + timedelta(days=1)).replace(tzinfo=tz).astimezone(timezone.utc)
    # split at UTC month starts
    cur = start
    while cur < end:
        nxt = datetime(cur.year + (cur.month == 12), cur.month % 12 + 1, 1, tzinfo=timezone.utc)
        nxt = min(nxt, end)
        yield cur, nxt
        cur = nxt


def fetch(url: str) -> bytes:
    backoff = 60
    for attempt in range(6):
        if STOP.exists():
            raise SystemExit("STOP file present")
        if datetime.now() >= FREEZE:
            raise TimeoutError("freeze reached")
        try:
            r = requests.get(url, timeout=300)
            body = r.content
            throttled = r.status_code in (429, 503) or b"Too many requests" in body[:500]
            if r.status_code == 200 and not throttled:
                return body
            log(f"  status={r.status_code} throttled={throttled} attempt={attempt}; sleep {backoff}s")
        except requests.RequestException as exc:
            log(f"  error {exc!r} attempt={attempt}; sleep {backoff}s")
        time.sleep(backoff)
        backoff *= 2
    raise RuntimeError(f"failed after retries: {url}")


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    jobs = []
    for icao, st in STATIONS.items():
        for a, b in chunks_for(st):
            jobs.append((icao, st, a, b))
    log(f"start: {len(jobs)} requests, freeze {FREEZE:%H:%M}")
    last = 0.0
    for i, (icao, st, a, b) in enumerate(jobs, 1):
        fn = RAW / f"{icao}_{a:%Y%m%d%H}_{b:%Y%m%d%H}.csv.gz"
        if fn.exists():
            continue
        url = URL_PATTERN.format(iem_id=st["iem_id"], sts=f"{a:%Y-%m-%dT%H:%MZ}", ets=f"{b:%Y-%m-%dT%H:%MZ}")
        wait = SPACING_S - (time.monotonic() - last)
        if wait > 0:
            time.sleep(wait)
        t0 = time.monotonic()
        try:
            body = fetch(url)
        except TimeoutError:
            log("freeze reached; stopping fetch")
            break
        last = time.monotonic()
        if not body.startswith(b"station,station_name,valid(UTC),tmpf"):
            log(f"[{i}/{len(jobs)}] {icao} unexpected body head {body[:120]!r}")
            continue
        tmp = fn.with_suffix(".tmp")
        with gzip.open(tmp, "wb") as fh:
            fh.write(body)
        os.replace(tmp, fn)
        log(f"[{i}/{len(jobs)}] {icao} {a:%Y-%m-%dT%HZ}..{b:%Y-%m-%dT%HZ} rows={body.count(NL) - 1} "
            f"bytes={len(body)} {time.monotonic() - t0:.1f}s url={url}")
    log("fetch loop done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
