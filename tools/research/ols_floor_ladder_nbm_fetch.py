"""Lane L9: fetch a point-in-time NBM NBP station archive for 2021-2025 (offline research).

Source: NOAA open data on AWS, ``noaa-nbm-grib2-pds`` (anonymous HTTPS, free, official), the
national NBP text bulletin ``blend.YYYYMMDD/HH/text/blend_nbptx.tHHz`` that MG-1 consumes through
``weather.sources.nbm_probabilistic_tmax.parse_nbp_station_tmax`` (parser v2).

The bulletin is 27-35 MB, but its station blocks are sorted by station id with fixed-width lines,
so this fetcher reads only each wanted station's block with HTTP Range requests (binary search on
the byte offset, seeded by the previous file's offsets). Per (date, cycle) it records the S3
LastModified (the PIT availability instant), the object size and ETag, and the raw station block.

Serial and polite (one request at a time, a short pause), resumable (finished (date, cycle) keys are
skipped), and refuses any date after 2026-09-29. Run it directly with the venv python, never
through the heavy wrapper. It writes only under ``--out-dir``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

BUCKET = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
LAST_ALLOWED = date(2026, 9, 29)
STATIONS = ("KATL", "KAUS", "KBKF", "KDAL", "KHOU", "KLAX", "KLGA", "KMIA", "KORD", "KSEA", "KSFO")
HEADER_RE = re.compile(rb"^ ?([A-Z0-9]{3,6}) +NBM V\S+ +NBP +GUIDANCE", re.M)
PROBE = 6000
WINDOW = 60000
PAUSE = 0.05
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def season_dates(years, windows):
    for year in years:
        for (m1, d1), (m2, d2) in windows:
            day, last = date(year, m1, d1), date(year, m2, d2)
            while day <= last:
                if day > LAST_ALLOWED:
                    raise SystemExit(f"refusing date after {LAST_ALLOWED}: {day}")
                yield day
                day += timedelta(days=1)


class Fetcher:
    def __init__(self, session):
        self.s = session
        self.requests = 0
        self.bytes = 0

    def _get(self, url, **kw):
        for attempt in range(5):
            try:
                self.requests += 1
                r = self.s.get(url, timeout=60, **kw)
                if r.status_code in (200, 206, 404, 416):
                    self.bytes += len(r.content)
                    time.sleep(PAUSE)
                    return r
            except Exception:  # transient network error: back off and retry
                pass
            time.sleep(2 ** attempt)
        raise RuntimeError(f"GET failed after retries: {url}")

    def head_listing(self, key):
        r = self._get(BUCKET + "/", params={"list-type": "2", "prefix": key})
        root = ET.fromstring(r.content)
        for c in root.findall(f"{NS}Contents"):
            if c.findtext(f"{NS}Key") == key:
                return {"last_modified": c.findtext(f"{NS}LastModified"),
                        "size": int(c.findtext(f"{NS}Size")),
                        "etag": (c.findtext(f"{NS}ETag") or "").strip('"')}
        return None

    def read(self, key, start, length, size):
        start = max(0, int(start))
        end = min(size - 1, start + length - 1)
        if start > end:
            return b""
        r = self._get(f"{BUCKET}/{key}", headers={"Range": f"bytes={start}-{end}"})
        return r.content

    def first_header_at_or_after(self, key, offset, size):
        """(station_id, absolute offset) of the first header line starting at or after offset."""
        pos = max(0, offset)
        while pos < size:
            chunk = self.read(key, pos, PROBE, size)
            if not chunk:
                return None, None
            # Only a header that starts at a line start counts.
            search_from = 0 if pos == 0 else (chunk.find(b"\n") + 1 if b"\n" in chunk else len(chunk))
            m = HEADER_RE.search(chunk, search_from)
            if m:
                return m.group(1).decode(), pos + m.start()
            pos += PROBE - 200
        return None, None

    def block(self, key, header_offset, size):
        data = b""
        pos = header_offset
        while True:
            chunk = self.read(key, pos, 8192, size)
            if not chunk:
                break
            data += chunk
            nxt = HEADER_RE.search(data, 10)
            if nxt:
                return data[: nxt.start()].decode("ascii", "replace")
            pos += len(chunk)
            if pos >= size:
                return data.decode("ascii", "replace")

    def find_station(self, key, station, size, guess=None):
        """Binary search over byte offsets for the station's header line."""
        if guess is not None:
            # One read of +-WINDOW bytes around the previous file's offset usually holds the
            # header (the station list changes by a few blocks between days).
            start = max(0, guess - WINDOW)
            chunk = self.read(key, start, 2 * WINDOW, size)
            for m in HEADER_RE.finditer(chunk):
                at_line_start = start + m.start() == 0 or chunk[m.start() - 1:m.start()] == b"\n"
                if m.group(1).decode() == station and at_line_start:
                    return start + m.start()
        lo, hi = 0, size
        for _ in range(40):
            mid = (lo + hi) // 2
            sid, off = self.first_header_at_or_after(key, mid, size)
            if sid == station:
                return off
            if sid is None or sid > station:
                hi = mid
            else:
                lo = off + 1
            if hi - lo < PROBE // 2:
                sid, off = self.first_header_at_or_after(key, lo, size)
                return off if sid == station else None
        return None


def main(argv=None):
    import requests

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--years", default="2021,2022,2023,2024,2025")
    ap.add_argument("--cycles", default="07")
    ap.add_argument("--dates-file", help="optional: one ISO date per line (overrides the windows)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows_path = out / "nbp_station_blocks.jsonl"
    done = set()
    if rows_path.exists():
        for line in rows_path.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done.add((rec["utc_date"], rec["cycle"]))
    years = [int(y) for y in args.years.split(",")]
    windows = [((8, 1), (9, 29)), ((10, 3), (12, 16))]
    if args.dates_file:
        dates = [date.fromisoformat(x.strip()) for x in Path(args.dates_file).read_text().split() if x.strip()]
        if any(d > LAST_ALLOWED for d in dates):
            raise SystemExit("refusing a date after 2026-09-29")
    else:
        dates = list(season_dates(years, windows))
    f = Fetcher(requests.Session())
    guesses = {}
    n = 0
    with rows_path.open("a", encoding="utf-8") as sink:
        for day in dates:
            for cycle in args.cycles.split(","):
                if (day.isoformat(), cycle) in done:
                    continue
                key = f"blend.{day:%Y%m%d}/{cycle}/text/blend_nbptx.t{cycle}z"
                meta = f.head_listing(key)
                rec = {"utc_date": day.isoformat(), "cycle": cycle, "key": key, "object": meta,
                       "stations": {}}
                if meta:
                    g = guesses.get(meta["size"], {})
                    newg = {}
                    for st in STATIONS:
                        off = f.find_station(key, st, meta["size"], g.get(st))
                        if off is None:
                            rec["stations"][st] = None
                            continue
                        newg[st] = off
                        rec["stations"][st] = {"offset": off, "block": f.block(key, off, meta["size"])}
                    guesses[meta["size"]] = newg
                sink.write(json.dumps(rec, sort_keys=True) + "\n")
                sink.flush()
                n += 1
                if n % 25 == 0:
                    print(f"{day} {cycle} n={n} requests={f.requests} MB={f.bytes / 1e6:.1f}", flush=True)
                if args.limit and n >= args.limit:
                    print(f"limit reached; requests={f.requests} MB={f.bytes / 1e6:.2f}")
                    return 0
    print(f"done n={n} requests={f.requests} MB={f.bytes / 1e6:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
