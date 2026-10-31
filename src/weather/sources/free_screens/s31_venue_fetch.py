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

Master ruling (a)+(c), 2026-10-31 (S31 Clarification 4):

- **Pre-cutoff Kalshi jobs.** ``kalshi_event_metadata`` (``/events/{t}/metadata``, allowlist M: market tickers
  only) and ``kalshi_historical_markets`` (``/historical/markets``, allowlist A) reach events whose markets settled
  before Kalshi's historical cutoff; ``kalshi_candles`` tier ``historical`` reads their candles (allowlist B) and
  is refused for a window starting at or after ``HISTORICAL_CUTOFF_UTC``. Every guard above applies unchanged.
- **ForecastEx staging.** ``fex_stations`` confirms twin stations from archived ForecastEx filing text only and
  writes ``fex_stations.json``; ``fex_pairs`` is refused before any request until that receipt exists and names a
  confirmed city. The first pairs file passes a staged V0.4 check (first row's ``pair_time`` and
  ``event_contract`` only) or FEX is refused for the run lineage. Rows of non-twin contracts are dropped before
  any of their other fields are parsed.
- **Resume.** A run reads the prior receipts under ``--out`` and skips completed jobs. A job that was started but
  not completed is re-fetched whole and its receipt names the partial runs; extract rows carry ``job`` and
  ``run_id`` so :func:`load_extract` keeps only rows of each job's completing run. Each run has a new ``run_id``
  and a new archive folder, created exclusively.
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
        re.compile(r"^/trade-api/v2/historical/markets$"),
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
# Allowlist M: Kalshi /events/{t}/metadata (market discovery, tickers only). Settlement sources, images and every
# other field are dropped.
ALLOW_M = ("event_ticker", "market_ticker")
# Kalshi /historical/cutoff ``market_settled_ts`` read on 2026-10-31 (S1 archive): markets settled before it are
# served only by /historical/*. A historical-tier candle window may not start at or after it.
HISTORICAL_CUTOFF_UTC = datetime(2026, 8, 31, 0, 0, tzinfo=timezone.utc)
# Our station per ForecastEx twin city (s0-s1 inventory twin table, same-station cities only). A fex_stations
# claim confirms a city only if an archived filing line names this station with the claimed region code.
FEX_TWIN_STATIONS = {"NYC": "KLGA", "ATL": "KATL", "AUS": "KAUS", "HOU": "KHOU", "LAX": "KLAX", "MIA": "KMIA",
                     "SFO": "KSFO", "SEA": "KSEA", "DEN": "KBKF"}
# Archived ForecastEx filing text a fex_stations job may read: ``pf_*`` / ``ptc*`` text extractions under the
# intake's ``forecastex`` folder. Notices to members, site pages and raw fetch bodies are never read.
_FEX_SPEC_NAME = re.compile(r"^(pf_|ptc)[A-Za-z0-9_.\- ]*\.txt$")
# event_contract decoding through the filing's product code ``[U|S][H|L|A]<region>`` plus target date and
# threshold. The exact remainder format is unverified; the staged V0.4 check refuses the file if it does not fit.
_FEX_CONTRACT = re.compile(r"^(?P<unit>[US])\s?(?P<kind>[HLA])\s?(?P<region>[A-Z]{3})[_\-\s]+"
                           r"(?P<date>\d{8}|\d{6})[_\-\s]+(?P<threshold>-?\d+(?:\.\d+)?)$")
_MINUTE_TIME = re.compile(r"[T ]\d{2}:\d{2}")
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


class OrderRefused(ValueError):
    """A FEX pairs read attempted before the station receipt exists, with no confirmed city, or after V0.4
    refused; raised before any request."""


class HttpStop(RuntimeError):
    """A 429 or 5xx answer: the run stops (no retry at rate); the job stays incomplete for a later resume."""


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
        self._run_root = self.archive_root / "raw" / self.run_id
        self._run_root_made = False
        self._prior = self._load_prior()

    # -- resume ------------------------------------------------------------------------------------------
    def _load_prior(self):
        """Prior receipts and job starts under ``--out``: completed job ids and runs that left a job partial."""
        done, started = {}, {}
        for name, sink in (("receipts.jsonl", done), ("journal.jsonl", started)):
            path = self.out_dir / name
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row.get("run_id") == self.run_id:
                    raise ValueError(f"run_id {self.run_id} already used under --out")
                job = row.get("job")
                if not job:
                    continue
                if sink is done:
                    if row.get("complete"):
                        done[job] = row["run_id"]
                else:
                    started.setdefault(job, []).append(row["run_id"])
        return {"done": done, "started": started}

    def is_done(self, job_id):
        return job_id in self._prior["done"]

    def _partial_runs(self, job_id):
        return sorted(set(self._prior["started"].get(job_id, [])))

    def _start(self, job_id):
        self._append("journal.jsonl", {"job": job_id, "run_id": self.run_id,
                                        "started_at": datetime.now(timezone.utc).isoformat()})

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

    def _write_once(self, name, payload):
        with open(self._out_path(name), "x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, sort_keys=True, indent=1) + "\n")

    def _archive(self, label, body, quarantine, sub=None):
        if not self._run_root_made:
            self._run_root.mkdir(parents=True, exist_ok=False)  # a new run_id gets a new folder, never reused
            self._run_root_made = True
        self._seq += 1
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label)[:120]
        folder = self._run_root / (sub or ("_quarantine_late" if quarantine else ""))
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{self._seq:05d}_{safe}"
        with open(target, "xb") as stream:  # exclusive create: never overwrite
            stream.write(body)
        return str(target)

    # -- request -----------------------------------------------------------------------------------------
    def get(self, url, label, job_id=None):
        check_url(url)
        headers = request_headers()
        if set(headers) != {"User-Agent", "Accept"}:
            raise AuthRequired("refused: only User-Agent and Accept headers may be sent")
        if job_id:
            self._start(job_id)
        self.limiter.wait()
        status, resp_headers, body = self.transport(url, headers)
        body = body or b""
        receipt = {"url": url, "status": status, "raw_sha256": sha256_bytes(body), "raw_bytes": len(body),
                   "fetched_at": datetime.now(timezone.utc).isoformat(), "label": label, "run_id": self.run_id,
                   "complete": False}
        if job_id:
            receipt["job"] = job_id
            partial = self._partial_runs(job_id)
            if partial:
                receipt["refetched_after_partial"] = partial
        head = body[:2048].lower()
        if status in (401, 403) or (status != 200 and any(m in head for m in _AUTH_MARKERS)):
            receipt["archive"] = self._archive(label + ".auth", body, quarantine=True)
            receipt["stop"] = "auth_required"
            self._append("receipts.jsonl", receipt)
            raise AuthRequired(f"{url} answered {status}: authentication wanted; STOP and report")
        if status == 429 or status >= 500:
            receipt["archive"] = self._archive(label + f".http{status}", body, quarantine=True,
                                               sub="_quarantine_refused")
            receipt["stop"] = f"http_{status}"
            self._append("receipts.jsonl", receipt)
            raise HttpStop(f"{url} answered {status}; run stopped, job left incomplete")
        return status, body, receipt

    def parse_or_quarantine(self, receipt, body, parser, *args, **kwargs):
        """Run ``parser``; a refused or undecodable body is archived to ``_quarantine_refused`` (nothing reads
        it) and receipted before the refusal propagates as :class:`FormatRefused` (master F6)."""
        try:
            return parser(body, *args, **kwargs)
        except ValueError as err:  # FormatRefused, JSONDecodeError, UnicodeDecodeError, float() failures
            receipt["archive"] = self._archive(receipt["label"] + ".refused", body, quarantine=True,
                                               sub="_quarantine_refused")
            receipt["stop"] = "format_refused"
            receipt["refused"] = f"{type(err).__name__}: {err}"[:500]
            receipt["complete"] = True  # a refusal is the job's recorded outcome; resume does not refetch it
            self._append("receipts.jsonl", receipt)
            if isinstance(err, FormatRefused):
                raise
            raise FormatRefused(f"{receipt['url']}: body refused ({type(err).__name__})") from err

    def finish(self, receipt, body, dropped, extract_name, rows, extra=None):
        receipt["n_kept"] = len(rows)
        receipt["n_dropped_late"] = len(dropped)
        receipt["dropped_late"] = dropped
        receipt.update(extra or {})
        receipt["archive"] = self._archive(receipt["label"], body, quarantine=bool(dropped))
        receipt["extract"] = extract_name
        tag = {"job": receipt.get("job"), "run_id": self.run_id}
        for row in rows:
            self._append(extract_name, {**row, **tag})
        receipt["complete"] = status_complete(receipt["status"])
        self._append("receipts.jsonl", receipt)  # written last: a job without it is partial
        return rows

    # -- V0: Kalshi /markets and /historical/markets, allowlist A ----------------------------------------
    def _markets(self, event_ticker, historical):
        series_of(event_ticker)
        check_target(kalshi_ticker_date(event_ticker))
        path = "/trade-api/v2/historical/markets" if historical else "/trade-api/v2/markets"
        url = f"https://{KALSHI_HOST}{path}?" + urllib.parse.urlencode({"event_ticker": event_ticker, "limit": 100})
        prefix = "hist_markets" if historical else "markets"
        job = f"{prefix}:{event_ticker}"
        status, body, receipt = self.get(url, f"{prefix}_{event_ticker}.json", job)
        rows = self.parse_or_quarantine(receipt, body, parse_markets, event_ticker) if status == 200 else []
        return self.finish(receipt, body, [], "v0_markets_hist.jsonl" if historical else "v0_markets.jsonl", rows)

    def kalshi_markets(self, event_ticker):
        return self._markets(event_ticker, historical=False)

    def kalshi_historical_markets(self, event_ticker):
        return self._markets(event_ticker, historical=True)

    # -- Kalshi /events/{t}/metadata, allowlist M (market discovery) -------------------------------------
    def kalshi_event_metadata(self, event_ticker):
        series_of(event_ticker)
        check_target(kalshi_ticker_date(event_ticker))
        url = f"https://{KALSHI_HOST}/trade-api/v2/events/{event_ticker}/metadata"
        status, body, receipt = self.get(url, f"event_meta_{event_ticker}.json", f"event_meta:{event_ticker}")
        rows = (self.parse_or_quarantine(receipt, body, parse_event_metadata, event_ticker)
                if status == 200 else [])
        return self.finish(receipt, body, [], "event_markets.jsonl", rows)

    # -- Kalshi candles, allowlist B ---------------------------------------------------------------------
    def kalshi_candles(self, series, market_ticker, tz_name, tier):
        check_series_tz(series, market_ticker, tz_name)
        target = kalshi_ticker_date(market_ticker)
        win = candle_window(target, tz_name)
        query = urllib.parse.urlencode({"start_ts": win.start_ts, "end_ts": win.end_ts - 1, "period_interval": 1})
        if tier == "live":
            path = f"/trade-api/v2/series/{series}/markets/{market_ticker}/candlesticks"
        elif tier == "historical":
            if win.start_utc >= HISTORICAL_CUTOFF_UTC:
                raise WindowRefused(f"historical tier refused: window starts {win.start_utc.isoformat()}, "
                                    f"at or after the cutoff {HISTORICAL_CUTOFF_UTC.isoformat()}")
            path = f"/trade-api/v2/historical/markets/{market_ticker}/candlesticks"
        else:
            raise ValueError(f"tier {tier!r}")
        job = f"candles:{tier}:{market_ticker}"
        status, body, receipt = self.get(f"https://{KALSHI_HOST}{path}?{query}", f"candles_{market_ticker}.json", job)
        receipt.update(window_start=win.start_utc.isoformat(), window_end=win.end_utc.isoformat(), tier=tier)
        rows, dropped = (self.parse_or_quarantine(receipt, body, parse_candles, market_ticker, win.end_ts)
                         if status == 200 else ([], []))
        return self.finish(receipt, body, dropped, "kalshi_candles.jsonl", rows)

    # -- ForecastEx V0.3: station confirmation from archived filing text (no request) --------------------
    def fex_spec_root(self):
        return self.archive_root.parent / "forecastex"

    def fex_stations(self, sources, claims):
        """Confirm FEX twin stations from archived filing text and write ``fex_stations.json`` (once)."""
        if self.is_done("fex_stations") or (self.out_dir / "fex_stations.json").exists():
            raise OrderRefused("fex_stations already receipted under --out; it is never rewritten")
        spec_root = self.fex_spec_root()
        texts, src_rows = {}, []
        for src in sources:
            path = Path(src)
            if not _inside(path, spec_root) or not _FEX_SPEC_NAME.match(path.name) or "notice" in path.name.lower():
                raise EndpointRefused(f"station source {src!r} is not an archived ForecastEx filing text")
            data = path.read_bytes()
            texts[str(path)] = data.decode("utf-8", errors="replace").splitlines()
            src_rows.append({"path": str(path), "sha256": sha256_bytes(data), "bytes": len(data)})
        results = []
        for claim in claims:
            city, region, station = claim["city"], claim["region"], claim["station"]
            if city not in FEX_TWIN_STATIONS:
                raise ValueError(f"city {city!r} is not a ForecastEx twin candidate")
            if not re.fullmatch(r"[A-Z]{3}", region or "") or not re.fullmatch(r"K[A-Z]{3}", station or ""):
                raise ValueError(f"claim {claim!r} malformed")
            match = None
            for path, lines in texts.items():
                for no, line in enumerate(lines, start=1):
                    if re.search(rf"\b{station}\b", line) and re.search(rf"\b{region}\b", line):
                        match = {"path": path, "line": no}
                        break
                if match:
                    break
            same = station == FEX_TWIN_STATIONS[city]
            results.append({"city": city, "region": region, "station": station, "found_in": match,
                            "same_station": same, "confirmed": bool(match) and same})
        payload = {"run_id": self.run_id, "sources": src_rows, "claims": results,
                   "confirmed_regions": {r["region"]: r["city"] for r in results if r["confirmed"]},
                   "written_at": datetime.now(timezone.utc).isoformat()}
        self._write_once("fex_stations.json", payload)
        self._append("receipts.jsonl", {"job": "fex_stations", "run_id": self.run_id, "complete": True,
                                        "label": "fex_stations", "n_confirmed": len(payload["confirmed_regions"]),
                                        "extract": "fex_stations.json"})
        self._prior["done"]["fex_stations"] = self.run_id
        return payload

    def _fex_state(self, name):
        path = self.out_dir / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    # -- ForecastEx pairs, allowlist C -------------------------------------------------------------------
    def fex_pairs(self, file_date, pair_time_tz=None):
        check_fex_file_date(file_date)
        stations = self._fex_state("fex_stations.json")
        if stations is None:
            raise OrderRefused("fex_pairs refused: no fex_stations.json receipt under --out (V0.3 first)")
        twins = dict(stations.get("confirmed_regions") or {})
        if not twins:
            raise OrderRefused("fex_pairs refused: no ForecastEx city confirmed by V0.3")
        v04 = self._fex_state("fex_v04.json")
        if v04 is not None and not v04.get("passed"):
            raise OrderRefused("fex_pairs refused: the staged V0.4 check refused FEX for this run lineage")
        url = f"https://{FEX_HOST}/pairs/pairs_{file_date:%Y%m%d}.csv"
        status, body, receipt = self.get(url, f"pairs_{file_date:%Y%m%d}.csv", f"pairs:{file_date:%Y%m%d}")
        if status != 200:
            return self.finish(receipt, body, [], "fex_pairs.jsonl", [])
        if v04 is None:
            try:
                check = self.parse_or_quarantine(receipt, body, fex_v04_check, pair_time_tz)
            except FormatRefused as err:
                self._write_once("fex_v04.json", {"passed": False, "file": url, "run_id": self.run_id,
                                                  "reason": str(err)[:500]})
                raise
            self._write_once("fex_v04.json", {"passed": True, "file": url, "run_id": self.run_id, **check})
        result = self.parse_or_quarantine(receipt, body, parse_pairs, global_bound_utc(), pair_time_tz,
                                          twins=set(twins), with_counts=True)
        rows, dropped, counts = result
        return self.finish(receipt, body, dropped, "fex_pairs.jsonl", rows, extra=counts)


def status_complete(status):
    """A 200 or 404 answer completes a job; anything else leaves it for a resume."""
    return status in (200, 404)


def load_extract(out_dir, extract_name):
    """Rows of ``extract_name`` from each job's completing run only (partial runs' rows are ignored)."""
    out_dir = Path(out_dir)
    done = {}
    receipts_path = out_dir / "receipts.jsonl"
    if receipts_path.exists():
        for line in receipts_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("complete") and row.get("job") and row.get("extract") == extract_name:
                done[row["job"]] = row["run_id"]
    path = out_dir / extract_name
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if done.get(row.get("job")) == row.get("run_id"):
            rows.append(row)
    return rows


JOB_IDS = {
    "kalshi_markets": lambda j: f"markets:{j['event_ticker']}",
    "kalshi_historical_markets": lambda j: f"hist_markets:{j['event_ticker']}",
    "kalshi_event_metadata": lambda j: f"event_meta:{j['event_ticker']}",
    "kalshi_candles": lambda j: f"candles:{j['tier']}:{j['market_ticker']}",
    "fex_stations": lambda j: "fex_stations",
    "fex_pairs": lambda j: f"pairs:{date.fromisoformat(j['file_date']):%Y%m%d}",
}


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


def parse_event_metadata(body, event_ticker):
    """Allowlist M: the market tickers of one event. Settlement sources and every other field are dropped."""
    payload = json.loads(body.decode("utf-8"))
    details = payload.get("market_details")
    if not isinstance(details, list):
        raise FormatRefused(f"event metadata for {event_ticker} has no market_details list")
    rows = []
    for item in details:
        ticker = item.get("market_ticker") if isinstance(item, dict) else None
        if not isinstance(ticker, str) or not ticker.startswith(event_ticker + "-"):
            raise FormatRefused(f"market {ticker!r} not in event {event_ticker}")
        rows.append({"event_ticker": event_ticker, "market_ticker": ticker})
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


def decode_event_contract(text):
    """``(unit, kind, region, target_date, threshold)`` from an event_contract through the filing's product code,
    or ``None`` if it does not decode."""
    m = _FEX_CONTRACT.match((text or "").strip())
    if not m:
        return None
    raw = m.group("date")
    try:
        day = (datetime.strptime(raw, "%Y%m%d") if len(raw) == 8 else datetime.strptime(raw, "%y%m%d")).date()
    except ValueError:
        return None
    return m.group("unit"), m.group("kind"), m.group("region"), day, float(m.group("threshold"))


def fex_v04_check(body, pair_time_tz=None):
    """Staged V0.4 (rule §3.4): on the first pairs file, read only the first data row's ``pair_time`` and
    ``event_contract``. Refuse unless ``pair_time`` has at most 1-minute resolution and an explicit or documented
    zone, and ``event_contract`` decodes to (city code, target date, threshold)."""
    reader = csv.reader(io.StringIO(body.decode("utf-8-sig")))
    header = tuple(next(reader, ()))
    if header != FEX_HEADER:
        raise FormatRefused(f"unexpected pairs header {header!r}")
    col = {name: i for i, name in enumerate(header)}
    first = next(reader, None)
    if first is None or len(first) != len(header):
        raise FormatRefused("V0.4: no complete first data row")
    text = first[col["pair_time"]]
    if not _MINUTE_TIME.search(text):
        raise FormatRefused(f"V0.4: pair_time {text!r} lacks minute resolution")
    parse_pair_time(text, pair_time_tz)  # refuses a naive value without a documented zone
    aware = datetime.fromisoformat(text.strip().replace("Z", "+00:00")).tzinfo is not None
    decoded = decode_event_contract(first[col["event_contract"]])
    if decoded is None:
        raise FormatRefused(f"V0.4: event_contract {first[col['event_contract']]!r} does not decode")
    return {"pair_time_zone": "explicit" if aware else f"documented:{pair_time_tz}",
            "first_region": decoded[2], "first_unit_kind": decoded[0] + decoded[1]}


def parse_pairs(body, bound_utc, pair_time_tz=None, twins=None, with_counts=False):
    """Allowlist C. Per row, ``event_contract`` is read first when ``twins`` is given: a row that is not a
    Fahrenheit daily-high contract (``U H``) of a confirmed twin region is dropped before any other field of it
    is parsed. Then ``expiration_date`` and ``pair_time`` are read; a row expiring after 2026-09-29 or filled
    at/after ``bound_utc`` is dropped without its price being read. A naive ``pair_time`` is tested on its
    conservative (latest, Pacific) UTC reading, and both readings are recorded (master F8)."""
    reader = csv.reader(io.StringIO(body.decode("utf-8-sig")))
    header = tuple(next(reader, ()))
    if header != FEX_HEADER:
        raise FormatRefused(f"unexpected pairs header {header!r}")
    col = {name: i for i, name in enumerate(header)}
    rows, dropped, non_twin, undecodable = [], [], 0, 0
    for line_no, rec in enumerate(reader, start=2):
        if len(rec) != len(header):
            raise FormatRefused(f"pairs line {line_no}: {len(rec)} fields")
        if twins is not None:
            decoded = decode_event_contract(rec[col["event_contract"]])
            if decoded is None:
                undecodable += 1
                continue
            if decoded[0] != "U" or decoded[1] != "H" or decoded[2] not in twins:
                non_twin += 1
                continue
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
    if with_counts:
        return rows, dropped, {"n_dropped_non_twin": non_twin, "n_dropped_undecodable": undecodable}
    return rows, dropped


# ---------------------------------------------------------------------------------------------------- CLI

def run_plan(fetcher, jobs):
    """Run ``jobs`` in order, skipping jobs a prior run under the same ``--out`` completed (resume)."""
    summary = {"run_id": fetcher.run_id, "jobs": len(jobs), "skipped_done": 0, "run": 0}
    try:
        for job in jobs:
            kind = job["kind"]
            if kind not in JOB_IDS:
                raise ValueError(f"unknown job kind {kind!r}")
            if fetcher.is_done(JOB_IDS[kind](job)):
                summary["skipped_done"] += 1
                continue
            summary["run"] += 1
            if kind == "kalshi_markets":
                fetcher.kalshi_markets(job["event_ticker"])
            elif kind == "kalshi_historical_markets":
                fetcher.kalshi_historical_markets(job["event_ticker"])
            elif kind == "kalshi_event_metadata":
                fetcher.kalshi_event_metadata(job["event_ticker"])
            elif kind == "kalshi_candles":
                fetcher.kalshi_candles(job["series"], job["market_ticker"], job["tz"], job["tier"])
            elif kind == "fex_stations":
                fetcher.fex_stations(job["sources"], job["claims"])
            else:
                fetcher.fex_pairs(date.fromisoformat(job["file_date"]), job.get("pair_time_tz"))
    finally:
        summary["ended_at"] = datetime.now(timezone.utc).isoformat()
        fetcher._append("runs.jsonl", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--plan", required=True, help="JSON list of jobs (see JOB_IDS for the kinds)")
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
    except HttpStop as err:
        print(f"STOP: {err}", file=sys.stderr)
        return 4
    except ValueError as err:  # Window/Series/Endpoint/Format/OrderRefused, bad plan values
        print(f"REFUSED: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
