"""S31 cross-venue twin-price fetch (lane L14; ledger row 99, rule ``rule_s31_p0.md`` sha256 ``d50112cc…``).

Read-only, unauthenticated, light-rate fetch of Kalshi metadata and candles and ForecastEx pairs files for the
S31 market-residual P0. Master's conditions (relayed 2026-10-31), each enforced in code:

- **Dev dates only.** Every request window is hard-bounded to target dates 2026-08-01..2026-09-29 (ForecastEx
  pairs files from 2026-07-30, for fills before a target date). A window's end must be at or before local
  midnight ending 2026-09-29 in its market's time zone; anything else raises :class:`WindowRefused` before a
  request is made.
- **Late-timestamp guard.** A returned candle or fill timestamped after its window end (or a pairs row whose
  contract expires after 2026-09-29) is dropped without its price fields being read, and recorded.
- **R13 archive.** Every raw response body is archived, exclusive-create and never overwritten or deleted, under
  ``--archive-root`` (default ``C:\\archive\\ruled-out\\_s31-intake\\s2_fetch``). A body holding any dropped
  late item goes to a ``_quarantine_late`` sub-folder that nothing reads; a body a parser refuses (bad shape,
  undecodable JSON) goes to ``_quarantine_refused`` with a receipt row (master F6). This archive is the one
  permitted write root besides ``--out`` (S31 Clarification 3). Scratch and extracts go under
  ``--out``, which must lie outside the archive root.
- **Global bound and series zones (master F5).** A candle window also ends at or before ``GLOBAL_BOUND_UTC``
  (2026-09-30T04:00Z, the earliest city end), and each Kalshi series is bound to its city zone in code; a plan
  declaring another zone is refused before any request.
- **No auth.** Requests carry only ``User-Agent`` and ``Accept``. A 401/403, or a body asking for
  authentication, raises :class:`AuthRequired` and the run stops.
- **Metadata and data endpoints only, through field allowlists A/B/C.** Hosts and paths are allowlisted; no
  venue page is ever requested.
- **At most 1 request per second**, serial.
- **No network unless ``--network`` is passed.** Tests inject a fake transport.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.sources.free_screens.common import DEV_LAST, local_day_end_utc, sha256_bytes

DEV_FIRST = date(2026, 8, 1)
FEX_FILE_FIRST = date(2026, 7, 30)
MIN_INTERVAL_S = 1.0
USER_AGENT = "weather-research-s31-venue-fetch/1 (serial, read-only; github michaelbooth1/weather)"
DEFAULT_ARCHIVE_ROOT = Path(r"C:\archive\ruled-out\_s31-intake\s2_fetch")

KALSHI_HOST = "api.elections.kalshi.com"
FEX_HOST = "forecastex-public-data.s3.amazonaws.com"
_TICKER = r"[A-Z0-9][A-Z0-9.\-]{0,63}"
ALLOWED_PATHS = {
    KALSHI_HOST: (
        re.compile(r"^/trade-api/v2/markets$"),
        re.compile(rf"^/trade-api/v2/events/{_TICKER}/metadata$"),
        re.compile(rf"^/trade-api/v2/series/{_TICKER}/markets/{_TICKER}/candlesticks$"),
        re.compile(rf"^/trade-api/v2/historical/markets/{_TICKER}/candlesticks$"),
    ),
    FEX_HOST: (
        re.compile(r"^/$"),
        re.compile(r"^/pairs/pairs_\d{8}\.csv$"),
    ),
}
TIMEZONES = frozenset({"America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"})
# The earliest local end of 2026-09-29 among the market zones (EDT midnight). Every candle window ends at or
# before it whatever zone a plan declares (master F5, 2026-10-31): never the latest city end.
GLOBAL_BOUND_UTC = datetime(2026, 9, 30, 4, 0, tzinfo=timezone.utc)
# Each Kalshi twin series is bound to its city's zone in code (s0-s1 inventory table). A plan that declares a
# different zone, or a ticker outside these series, is refused before any request (master F5).
SERIES_TZ = {
    "KXHIGHNY": "America/New_York",      # NYC
    "KXHIGHCHI": "America/Chicago",      # Chicago
    "KXHIGHTATL": "America/New_York",    # Atlanta
    "KXHIGHAUS": "America/Chicago",      # Austin
    "KXHIGHTDAL": "America/Chicago",     # Dallas
    "KXHIGHDEN": "America/Denver",       # Denver
    "KXHIGHTHOU": "America/Chicago",     # Houston
    "KXHIGHLAX": "America/Los_Angeles",  # Los Angeles
    "KXHIGHMIA": "America/New_York",     # Miami
    "KXHIGHTSFO": "America/Los_Angeles",  # San Francisco
    "KXHIGHTSEA": "America/Los_Angeles",  # Seattle
}

# Allowlist A: Kalshi /markets (V0 only). Everything else, including every price, volume, open-interest,
# result and settlement field, is dropped.
ALLOW_A = ("ticker", "event_ticker", "strike_type", "floor_strike", "cap_strike", "rules_primary",
           "rules_secondary", "open_time", "close_time")
# Allowlist B: Kalshi candlesticks. The quote close is ``close_dollars`` on the live tier, ``close`` on the
# historical tier; both are normalised to one field.
ALLOW_B = ("end_period_ts", "yes_bid_close", "yes_ask_close")
# Allowlist C: ForecastEx pairs CSV columns kept. ``quantity`` and ``no_price`` are dropped.
ALLOW_C = ("event_contract", "expiration_date", "yes_price", "pair_time")
FEX_HEADER = ("pair_id", "event_contract", "expiration_date", "quantity", "yes_price", "no_price", "pair_time")
_AUTH_MARKERS = (b"unauthorized", b"authentication", b"api key", b"access denied", b"accessdenied")
_KALSHI_DATE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})(?:-|$)")
_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), start=1)}


class WindowRefused(ValueError):
    """A request or target date outside the dev window; raised before any request."""


class AuthRequired(RuntimeError):
    """An endpoint asked for authentication: the run stops (master: STOP and report)."""


class EndpointRefused(ValueError):
    """A host or path outside the allowlist (no venue pages)."""


class FormatRefused(ValueError):
    """A response whose shape breaks the rule (e.g. an unexpected pairs header or pair_time format)."""


class SeriesRefused(WindowRefused):
    """A ticker outside the bound series, or a declared zone that differs from the series' city zone."""


# ----------------------------------------------------------------------------------------------- date guards

def global_bound_utc():
    """The earliest local end of 2026-09-29 among the US market time zones (Eastern): the strictest bound."""
    bound = min(local_day_end_utc(tz, DEV_LAST) for tz in TIMEZONES)
    if bound != GLOBAL_BOUND_UTC:
        raise WindowRefused(f"computed bound {bound.isoformat()} disagrees with GLOBAL_BOUND_UTC")
    return GLOBAL_BOUND_UTC


def series_of(ticker):
    """The bound series of an event or market ticker (the part before the first ``-``)."""
    series = (ticker or "").split("-", 1)[0]
    if series not in SERIES_TZ:
        raise SeriesRefused(f"ticker {ticker!r} is not in a bound Kalshi twin series")
    return series


def check_series_tz(series, market_ticker, tz_name):
    """The plan's series, the market ticker's series and the declared zone must all agree with SERIES_TZ."""
    if series_of(market_ticker) != series:
        raise SeriesRefused(f"market {market_ticker!r} is not in series {series!r}")
    if SERIES_TZ[series] != tz_name:
        raise SeriesRefused(f"series {series} is bound to {SERIES_TZ[series]}, plan declared {tz_name!r}")
    return tz_name


def check_target(day):
    if not isinstance(day, date) or not (DEV_FIRST <= day <= DEV_LAST):
        raise WindowRefused(f"target date {day} outside {DEV_FIRST}..{DEV_LAST}")
    return day


def kalshi_ticker_date(ticker):
    """Target date from a Kalshi event or market ticker (``KXHIGHNY-26SEP15`` or ``…-26SEP15-B72.5``)."""
    m = _KALSHI_DATE.search(ticker or "")
    if not m or m.group(2) not in _MONTHS:
        raise WindowRefused(f"no target date in ticker {ticker!r}")
    return date(2000 + int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)))


@dataclass(frozen=True)
class Window:
    start_utc: datetime
    end_utc: datetime  # exclusive

    @property
    def start_ts(self):
        return int(self.start_utc.timestamp())

    @property
    def end_ts(self):
        return int(self.end_utc.timestamp())


def candle_window(target, tz_name, days_before=2):
    """[local midnight of target − days_before, local midnight ending target), bounded to the dev window."""
    check_target(target)
    if tz_name not in TIMEZONES:
        raise WindowRefused(f"time zone {tz_name!r} not a US market zone")
    zone = ZoneInfo(tz_name)
    start = datetime.combine(target - timedelta(days=days_before), dtime(0, 0), tzinfo=zone).astimezone(timezone.utc)
    end = min(local_day_end_utc(tz_name, target), global_bound_utc())
    if end > local_day_end_utc(tz_name, DEV_LAST) or end <= start:
        raise WindowRefused(f"window end {end.isoformat()} after local end of {DEV_LAST}")
    return Window(start, end)


def check_fex_file_date(day):
    if not isinstance(day, date) or not (FEX_FILE_FIRST <= day <= DEV_LAST):
        raise WindowRefused(f"pairs file date {day} outside {FEX_FILE_FIRST}..{DEV_LAST}")
    return day


# ------------------------------------------------------------------------------------------------ transport

class RateLimiter:
    """Serial spacing of at least ``min_interval`` seconds between requests."""

    def __init__(self, min_interval=MIN_INTERVAL_S, clock=time.monotonic, sleep=time.sleep):
        if min_interval < MIN_INTERVAL_S:
            raise ValueError("at most 1 request per second")
        self.min_interval, self.clock, self.sleep, self.last = float(min_interval), clock, sleep, None

    def wait(self):
        now = self.clock()
        if self.last is not None and now - self.last < self.min_interval:
            self.sleep(self.min_interval - (now - self.last))
            now = self.clock()
        self.last = now


def check_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password:
        raise EndpointRefused(f"refused URL {url!r}")
    patterns = ALLOWED_PATHS.get(parts.hostname or "")
    if not patterns or not any(p.match(parts.path) for p in patterns):
        raise EndpointRefused(f"host/path not allowlisted: {parts.hostname}{parts.path}")
    return parts


def request_headers():
    return {"User-Agent": USER_AGENT, "Accept": "application/json, text/csv, application/xml"}


def urllib_transport(url, headers, timeout=60):
    """Default network transport: (status, response headers, body). Never sends credentials."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers.items()) if err.headers else {}, err.read() or b""


def refuse_network(url, headers):
    raise RuntimeError("network disabled: pass --network only after master's review (coordinator 2026-10-31)")


# ------------------------------------------------------------------------------------------------- fetcher

def _inside(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


@dataclass
class Fetcher:
    out_dir: Path
    archive_root: Path = DEFAULT_ARCHIVE_ROOT
    transport: object = refuse_network
    limiter: RateLimiter = field(default_factory=RateLimiter)
    run_id: str = ""

    def __post_init__(self):
        self.out_dir, self.archive_root = Path(self.out_dir), Path(self.archive_root)
        if _inside(self.out_dir, self.archive_root) or _inside(self.archive_root, self.out_dir):
            raise ValueError("--out and the archive root must not contain each other (scratch stays outside)")
        self.run_id = self.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._seq = 0

    # -- writes ------------------------------------------------------------------------------------------
    def _out_path(self, name):
        target = (self.out_dir / name).resolve()
        if not _inside(target, self.out_dir):
            raise ValueError(f"refused write outside --out: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def _append(self, name, row):
        with open(self._out_path(name), "a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")

    def _archive(self, label, body, quarantine, sub=None):
        self._seq += 1
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label)[:120]
        folder = self.archive_root / "raw" / self.run_id / (sub or ("_quarantine_late" if quarantine else ""))
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{self._seq:05d}_{safe}"
        with open(target, "xb") as stream:  # exclusive create: never overwrite
            stream.write(body)
        return str(target)

    # -- request -----------------------------------------------------------------------------------------
    def get(self, url, label):
        check_url(url)
        headers = request_headers()
        if set(headers) != {"User-Agent", "Accept"}:
            raise AuthRequired("refused: only User-Agent and Accept headers may be sent")
        self.limiter.wait()
        status, resp_headers, body = self.transport(url, headers)
        body = body or b""
        receipt = {"url": url, "status": status, "raw_sha256": sha256_bytes(body), "raw_bytes": len(body),
                   "fetched_at": datetime.now(timezone.utc).isoformat(), "label": label}
        head = body[:2048].lower()
        if status in (401, 403) or (status != 200 and any(m in head for m in _AUTH_MARKERS)):
            receipt["archive"] = self._archive(label + ".auth", body, quarantine=True)
            receipt["stop"] = "auth_required"
            self._append("receipts.jsonl", receipt)
            raise AuthRequired(f"{url} answered {status}: authentication wanted; STOP and report")
        return status, body, receipt

    def parse_or_quarantine(self, receipt, body, parser, *args):
        """Run ``parser``; a refused or undecodable body is archived to ``_quarantine_refused`` (nothing reads
        it) and receipted before the refusal propagates as :class:`FormatRefused` (master F6)."""
        try:
            return parser(body, *args)
        except ValueError as err:  # FormatRefused, JSONDecodeError, UnicodeDecodeError, float() failures
            receipt["archive"] = self._archive(receipt["label"] + ".refused", body, quarantine=True,
                                               sub="_quarantine_refused")
            receipt["stop"] = "format_refused"
            receipt["refused"] = f"{type(err).__name__}: {err}"[:500]
            self._append("receipts.jsonl", receipt)
            if isinstance(err, FormatRefused):
                raise
            raise FormatRefused(f"{receipt['url']}: body refused ({type(err).__name__})") from err

    def finish(self, receipt, body, dropped, extract_name, rows):
        receipt["n_kept"] = len(rows)
        receipt["n_dropped_late"] = len(dropped)
        receipt["dropped_late"] = dropped
        receipt["archive"] = self._archive(receipt["label"], body, quarantine=bool(dropped))
        receipt["extract"] = extract_name
        for row in rows:
            self._append(extract_name, row)
        self._append("receipts.jsonl", receipt)
        return rows

    # -- V0: Kalshi /markets, allowlist A ----------------------------------------------------------------
    def kalshi_markets(self, event_ticker):
        series_of(event_ticker)
        check_target(kalshi_ticker_date(event_ticker))
        url = (f"https://{KALSHI_HOST}/trade-api/v2/markets?"
               + urllib.parse.urlencode({"event_ticker": event_ticker, "limit": 100}))
        status, body, receipt = self.get(url, f"markets_{event_ticker}.json")
        rows = self.parse_or_quarantine(receipt, body, parse_markets, event_ticker) if status == 200 else []
        return self.finish(receipt, body, [], "v0_markets.jsonl", rows)

    # -- Kalshi candles, allowlist B ---------------------------------------------------------------------
    def kalshi_candles(self, series, market_ticker, tz_name, tier):
        check_series_tz(series, market_ticker, tz_name)
        target = kalshi_ticker_date(market_ticker)
        win = candle_window(target, tz_name)
        query = urllib.parse.urlencode({"start_ts": win.start_ts, "end_ts": win.end_ts - 1, "period_interval": 1})
        if tier == "live":
            path = f"/trade-api/v2/series/{series}/markets/{market_ticker}/candlesticks"
        elif tier == "historical":
            path = f"/trade-api/v2/historical/markets/{market_ticker}/candlesticks"
        else:
            raise ValueError(f"tier {tier!r}")
        status, body, receipt = self.get(f"https://{KALSHI_HOST}{path}?{query}", f"candles_{market_ticker}.json")
        receipt.update(window_start=win.start_utc.isoformat(), window_end=win.end_utc.isoformat(), tier=tier)
        rows, dropped = (self.parse_or_quarantine(receipt, body, parse_candles, market_ticker, win.end_ts)
                         if status == 200 else ([], []))
        return self.finish(receipt, body, dropped, "kalshi_candles.jsonl", rows)

    # -- ForecastEx pairs, allowlist C -------------------------------------------------------------------
    def fex_pairs(self, file_date, pair_time_tz=None):
        check_fex_file_date(file_date)
        url = f"https://{FEX_HOST}/pairs/pairs_{file_date:%Y%m%d}.csv"
        status, body, receipt = self.get(url, f"pairs_{file_date:%Y%m%d}.csv")
        rows, dropped = (self.parse_or_quarantine(receipt, body, parse_pairs, global_bound_utc(), pair_time_tz)
                         if status == 200 else ([], []))
        return self.finish(receipt, body, dropped, "fex_pairs.jsonl", rows)


# ------------------------------------------------------------------------------------------------ parsers

def parse_markets(body, event_ticker):
    payload = json.loads(body.decode("utf-8"))
    rows = []
    for market in payload.get("markets") or []:
        row = {k: market.get(k) for k in ALLOW_A}
        if row["event_ticker"] != event_ticker:
            raise FormatRefused(f"market {row['ticker']} not in event {event_ticker}")
        rows.append(row)
    return rows


def _close(dist):
    if not isinstance(dist, dict):
        return None
    value = dist.get("close_dollars", dist.get("close"))
    return None if value is None else float(value)


def parse_candles(body, market_ticker, end_ts_exclusive):
    """Allowlist B. A candle whose ``end_period_ts`` is missing or at/after the window end is dropped before any
    price field of it is read."""
    payload = json.loads(body.decode("utf-8"))
    rows, dropped = [], []
    for candle in payload.get("candlesticks") or []:
        ts = candle.get("end_period_ts") if isinstance(candle, dict) else None
        if not isinstance(ts, int) or ts >= end_ts_exclusive:
            dropped.append({"ticker": market_ticker, "end_period_ts": ts if isinstance(ts, int) else None})
            continue
        rows.append({"ticker": market_ticker, "end_period_ts": ts,
                     "yes_bid_close": _close(candle.get("yes_bid")), "yes_ask_close": _close(candle.get("yes_ask"))})
    return rows, dropped


def parse_pair_time(text, tz_name=None):
    """ISO-8601 ``pair_time`` as ``(declared_utc, conservative_utc)``.

    Naive values need an explicit ``tz_name`` (documented zone), else refuse. For a naive value the
    conservative UTC is the latest-UTC reading among the US market zones (Pacific), whatever zone is declared,
    so a mis-declared zone cannot admit a fill past the bound (master F8). For an aware value both are equal.
    """
    try:
        value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError as err:
        raise FormatRefused(f"pair_time {text!r} is not ISO-8601; file refused") from err
    if value.tzinfo is not None:
        utc = value.astimezone(timezone.utc)
        return utc, utc
    if not tz_name:
        raise FormatRefused(f"pair_time {text!r} has no time zone and none was documented")
    declared = value.replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
    conservative = max(value.replace(tzinfo=ZoneInfo(tz)).astimezone(timezone.utc) for tz in TIMEZONES)
    return declared, max(declared, conservative)


def parse_pairs(body, bound_utc, pair_time_tz=None):
    """Allowlist C. Per row, ``expiration_date`` and ``pair_time`` are read first; a row expiring after
    2026-09-29 or filled at/after ``bound_utc`` is dropped without its price being read. A naive ``pair_time``
    is tested on its conservative (latest, Pacific) UTC reading, and both readings are recorded (master F8)."""
    reader = csv.reader(io.StringIO(body.decode("utf-8-sig")))
    header = tuple(next(reader, ()))
    if header != FEX_HEADER:
        raise FormatRefused(f"unexpected pairs header {header!r}")
    col = {name: i for i, name in enumerate(header)}
    rows, dropped = [], []
    for line_no, rec in enumerate(reader, start=2):
        if len(rec) != len(header):
            raise FormatRefused(f"pairs line {line_no}: {len(rec)} fields")
        try:
            expiry = date.fromisoformat(rec[col["expiration_date"]].strip()[:10])
        except ValueError as err:
            raise FormatRefused(f"pairs line {line_no}: expiration_date unparseable") from err
        filled, conservative = parse_pair_time(rec[col["pair_time"]], pair_time_tz)
        times = {"pair_time_utc": filled.isoformat()}
        if conservative != filled:
            times["pair_time_utc_conservative"] = conservative.isoformat()
        if expiry > DEV_LAST or conservative >= bound_utc:
            dropped.append({"line": line_no, "expiration_date": expiry.isoformat(), **times})
            continue
        rows.append({"event_contract": rec[col["event_contract"]], "expiration_date": expiry.isoformat(),
                     "yes_price": float(rec[col["yes_price"]]), **times})
    return rows, dropped


# ---------------------------------------------------------------------------------------------------- CLI

def run_plan(fetcher, jobs):
    for job in jobs:
        kind = job["kind"]
        if kind == "kalshi_markets":
            fetcher.kalshi_markets(job["event_ticker"])
        elif kind == "kalshi_candles":
            fetcher.kalshi_candles(job["series"], job["market_ticker"], job["tz"], job["tier"])
        elif kind == "fex_pairs":
            fetcher.fex_pairs(date.fromisoformat(job["file_date"]), job.get("pair_time_tz"))
        else:
            raise ValueError(f"unknown job kind {kind!r}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--plan", required=True, help="JSON list of jobs (kalshi_markets | kalshi_candles | fex_pairs)")
    parser.add_argument("--out", required=True, help="extracts and receipts (outside the archive root)")
    parser.add_argument("--archive-root", default=str(DEFAULT_ARCHIVE_ROOT))
    parser.add_argument("--network", action="store_true", help="allow real requests (only after master's review)")
    args = parser.parse_args(argv)
    try:
        jobs = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        fetcher = Fetcher(Path(args.out), Path(args.archive_root),
                          transport=urllib_transport if args.network else refuse_network)
        run_plan(fetcher, jobs)
    except AuthRequired as err:
        print(f"STOP: {err}", file=sys.stderr)
        return 3
    except ValueError as err:  # WindowRefused, SeriesRefused, EndpointRefused, FormatRefused, bad plan values
        print(f"REFUSED: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
