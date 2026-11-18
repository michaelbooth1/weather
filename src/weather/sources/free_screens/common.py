"""Shared helpers for the free-source screens: dev date bound, polite resumable fetch, receipts."""
from __future__ import annotations

import gzip
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.paths import data_path

DEV_LAST = date(2026, 9, 29)
DEFAULT_ROOT = data_path("research", "free_sources")
USER_AGENT = "weather-research-free-source-screen/1 (serial, polite; contact via github michaelbooth1/weather)"


@dataclass(frozen=True)
class Station:
    market: str
    icao: str
    timezone: str
    lat: float
    lon: float


def us_stations():
    """The US settlement stations of the built-in market registry (Toronto excluded), sorted by market."""
    from weather.market.market_registry import REGISTRY

    return tuple(sorted((Station(s.id, s.icao, s.timezone, float(s.lat), float(s.lon))
                         for s in REGISTRY.values() if str(s.icao).startswith("K")), key=lambda s: s.market))


# KBKF (Buckley SFB, military) publishes no 1-minute archive at IEM; KDEN is fetched alongside it.
DENVER_PROXY = Station("denver", "KDEN", "America/Denver", 39.8561, -104.6737)


def local_day_end_utc(tz_name, day=DEV_LAST):
    """UTC instant of local midnight ending ``day`` (exclusive upper bound of every request)."""
    end_local = datetime.combine(day + timedelta(days=1), dtime(0, 0), tzinfo=ZoneInfo(tz_name))
    return end_local.astimezone(timezone.utc)


def month_windows(start_utc, end_utc):
    """Split [start, end) at UTC month starts."""
    out, cursor = [], start_utc
    while cursor < end_utc:
        nxt = datetime(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1, tzinfo=timezone.utc)
        out.append((cursor, min(nxt, end_utc)))
        cursor = nxt
    return out


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


class ReceiptLog:
    """Append-only jsonl of stored files; a key whose file still matches its sha is not fetched again."""

    def __init__(self, source_dir):
        self.dir = Path(source_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "receipts.jsonl"
        self.done = {}
        if self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self.done[row["key"]] = row

    def is_done(self, key):
        row = self.done.get(key)
        if not row:
            return False
        target = self.dir / row["file"]
        return target.is_file() and sha256_bytes(target.read_bytes()) == row["sha256"]

    def record(self, row):
        with open(self.path, "a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
        self.done[row["key"]] = row


def polite_get(session, url, spacing_s=2.0, timeout=120, max_tries=6, _last=[0.0]):
    """Serial GET with >= ``spacing_s`` between requests and doubling backoff on 429/5xx."""
    wait = 60.0
    for attempt in range(max_tries):
        gap = time.monotonic() - _last[0]
        if gap < spacing_s:
            time.sleep(spacing_s - gap)
        _last[0] = time.monotonic()
        try:
            resp = session.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        except Exception:  # network error: back off and retry
            if attempt == max_tries - 1:
                raise
            time.sleep(wait)
            wait *= 2
            continue
        if resp.status_code == 200 and b"Too many requests" not in resp.content[:200]:
            return resp
        if resp.status_code == 404:
            return resp
        if attempt == max_tries - 1:
            resp.raise_for_status()
        time.sleep(wait)
        wait *= 2
    raise RuntimeError(f"unreachable: {url}")


def store_gzip(source_dir, name, body):
    """Write ``body`` gzipped (mtime 0, so the bytes are deterministic); returns (relative name, sha256)."""
    raw = gzip.compress(body, mtime=0)
    target = Path(source_dir) / "raw" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return f"raw/{name}", sha256_bytes(raw)


def utc_stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%MZ")
