"""Step 1: outcome-free inventory of International Polymarket closed-event price history.

COUNTS ONLY. For each market: earliest admitted closed event date, number of admitted closed event
dates, and CLOB ``/prices-history`` points per token-day at fidelity 1 and 60 minutes from a small
probe. No price level, outcome or resolution is printed or written: discovery keeps only slugs,
dates, market counts and Yes-token ids, and the probe reads only point timestamps (``t``) and drops
``p`` unread. Guards (``guards.py``) refuse in code before any price request for an event.

Public endpoints only, unauthenticated GETs, wire rate capped at 4 MiB/s with request pacing and
429/5xx backoff. International Polymarket only.

Usage (from the repository root):
    python -m tools.research.pm_price_history.inventory --out data/research/pm_price_history/step1
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import statistics
import sys
import time
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from tools.research.pm_price_history import guards
from weather.market.market_registry import BUILTIN_SPECS
from weather.paths import CONFIG_ROOT, REPO_ROOT

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
MAX_RATE_BYTES_PER_S = 4 * 1024 * 1024
DEFAULT_MIN_INTERVAL_S = 0.25
USER_AGENT = "weather-research-inventory/0.1 (public read-only)"
PAGE_LIMIT = 100

# Server-side endDate windows: they keep guarded events out of discovery replies where the venue's
# endDate (12:00Z on the target date) allows; the code guard still runs on every event.
DISCOVERY_WINDOWS = (
    (None, "2026-05-27T00:00:00Z"),
    ("2026-07-31T00:00:00Z", "2026-09-30T00:00:00Z"),
)
PRE_PANEL_LAST = date(2026, 5, 26)

# R1 = config/capture_families.json core_recorder_only rows; R2 = DECISION_LOG 2026-10-23
# phase-2 plan ("R2 adds Munich, Madrid, Beijing, Wellington and Hong Kong recorder-only").
R1_IDS = ("london", "paris", "seoul", "tokyo", "shanghai")
R2_IDS = ("munich", "madrid", "beijing", "wellington", "hong-kong")

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4,
    "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9,
    "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
SLUG_DATE_RE = re.compile(r"-on-([a-z]+)-(\d{1,2})(?:-(\d{4}|\d{2}))?$")


# --------------------------------------------------------------------------- HTTP

class RateLimiter:
    """Wire-byte rate cap plus a minimum gap between request starts."""

    def __init__(self, max_bps=MAX_RATE_BYTES_PER_S, min_interval=DEFAULT_MIN_INTERVAL_S,
                 clock=time.monotonic, sleep=time.sleep):
        if max_bps <= 0 or max_bps > MAX_RATE_BYTES_PER_S:
            raise guards.GuardRefusal(f"rate cap must be in (0, {MAX_RATE_BYTES_PER_S}] bytes/s")
        self.max_bps = float(max_bps)
        self.min_interval = float(min_interval)
        self.clock, self.sleep = clock, sleep
        self.t0 = None
        self.total_bytes = 0
        self.last_start = None

    def wait(self):
        now = self.clock()
        if self.t0 is None:
            self.t0 = now
        ready = self.t0 + self.total_bytes / self.max_bps
        if self.last_start is not None:
            ready = max(ready, self.last_start + self.min_interval)
        if ready > now:
            self.sleep(ready - now)
            now = self.clock()
        self.last_start = now

    def record(self, nbytes):
        self.total_bytes += int(nbytes)


@dataclass
class HttpStats:
    requests: int = 0
    wire_bytes: int = 0
    decoded_bytes: int = 0
    retries: int = 0
    status_429: int = 0


class PublicClient:
    """Unauthenticated GET-only client for the allowed public endpoints."""

    def __init__(self, session=None, limiter=None, max_attempts=6, timeout=60, sleep=time.sleep):
        import requests  # local import keeps the guards importable without requests

        self.session = session or requests.Session()
        self.session.headers.clear()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Encoding": "gzip",
                                     "Accept": "application/json"})
        self.limiter = limiter or RateLimiter()
        self.max_attempts = int(max_attempts)
        self.timeout = timeout
        self.sleep = sleep
        self.stats = HttpStats()

    def get_json(self, url, params=None):
        full = url + ("?" + urlencode(params) if params else "")
        guards.require_public_endpoint(full, self.session.headers)
        for attempt in range(self.max_attempts):
            self.limiter.wait()
            self.stats.requests += 1
            try:
                resp = self.session.get(full, timeout=self.timeout, stream=True)
                wire = resp.raw.read(decode_content=False) if resp.raw is not None else resp.content
            except Exception:  # noqa: BLE001 - connection error: back off and retry
                self.stats.retries += 1
                self.sleep(min(60, 2 ** attempt))
                continue
            self.limiter.record(len(wire))
            self.stats.wire_bytes += len(wire)
            status = resp.status_code
            if status == 429 or status >= 500:
                self.stats.retries += 1
                self.stats.status_429 += int(status == 429)
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt + 1)
                self.sleep(min(120.0, delay))
                continue
            if status != 200:
                raise RuntimeError(f"HTTP {status} for {url}")
            body = _decode(wire, resp.headers.get("Content-Encoding", ""))
            self.stats.decoded_bytes += len(body)
            return json.loads(body)
        raise RuntimeError(f"gave up after {self.max_attempts} attempts: {url}")


def _decode(wire: bytes, encoding: str) -> bytes:
    encoding = (encoding or "").lower().strip()
    if encoding == "gzip":
        return gzip.decompress(wire)
    if encoding == "deflate":
        return zlib.decompress(wire)
    if encoding in ("", "identity"):
        return wire
    raise RuntimeError(f"unexpected Content-Encoding {encoding!r}")


# --------------------------------------------------------------------------- markets

@dataclass(frozen=True)
class Market:
    id: str
    role: str
    slug_prefix: str
    series_slug: str


def market_universe(config_root=CONFIG_ROOT):
    payload = json.loads((Path(config_root) / "location_market_events.json").read_text(encoding="utf-8"))
    by_prefix = {row["event_slug_prefix"]: row for row in payload["locations"]}
    by_id = {row["location_id"]: row for row in payload["locations"]}
    markets = []
    for spec in BUILTIN_SPECS:
        row = by_prefix[spec.slug_prefix]
        markets.append(Market(spec.id, "builtin", spec.slug_prefix, row["series_slug"]))
    for role, ids in (("R1", R1_IDS), ("R2", R2_IDS)):
        for location_id in ids:
            row = by_id[location_id]
            markets.append(Market(location_id, role, row["event_slug_prefix"], row["series_slug"]))
    return markets


# --------------------------------------------------------------------------- discovery

def slug_date(slug: str, end_date: date | None) -> date | None:
    """Target date from an event slug; a missing or two-digit year is completed from endDate."""
    match = SLUG_DATE_RE.search(str(slug or "").lower())
    if not match:
        return None
    month = MONTHS.get(match.group(1))
    if not month:
        return None
    day, year_text = int(match.group(2)), match.group(3)
    candidates = []
    if year_text:
        candidates = [int(year_text) + (2000 if len(year_text) == 2 else 0)]
    elif end_date is not None:
        candidates = [end_date.year - 1, end_date.year, end_date.year + 1]
    best = None
    for year in candidates:
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if best is None or (end_date and abs((d - end_date).days) < abs((best - end_date).days)):
            best = d
    return best


def event_target_date(event) -> tuple[date | None, str]:
    """Return (local target date, how it was inferred). None means unreadable (refused)."""
    end_text = str(event.get("endDate") or "")
    end_date = None
    if len(end_text) >= 10:
        try:
            end_date = date.fromisoformat(end_text[:10])
        except ValueError:
            end_date = None
    from_slug = slug_date(event.get("slug"), end_date)
    explicit = event.get("eventDate")
    if explicit:
        try:
            explicit_date = date.fromisoformat(str(explicit)[:10])
        except ValueError:
            explicit_date = None
        if explicit_date and (from_slug is None or from_slug == explicit_date):
            return explicit_date, "eventDate"
        return None, "eventDate_slug_mismatch"
    if from_slug is None:
        return None, "slug_unparsed"
    if end_date is None:
        return None, "no_endDate"
    offset = (end_date - from_slug).days
    if offset == 0:
        return from_slug, "slug_eq_endDate"
    if abs(offset) == 1:
        return from_slug, f"slug_endDate_offset_{offset:+d}"
    return None, "slug_endDate_mismatch"


def _yes_token(market) -> str | None:
    try:
        tokens = json.loads(market.get("clobTokenIds") or "[]")
        outcomes = json.loads(market.get("outcomes") or "[]")
    except (TypeError, ValueError):
        return None
    if len(tokens) != 2:
        return None
    index = outcomes.index("Yes") if "Yes" in outcomes else 0
    return str(tokens[index])


def strip_event(event) -> dict:
    """Keep only identity, dates, market count and Yes-token ids. Prices and resolutions are dropped."""
    markets = event.get("markets") or []
    starts = [m.get("startDate") or m.get("createdAt") for m in markets]
    starts = sorted(s for s in starts if s)
    return {
        "slug": event.get("slug"),
        "end_date_utc": event.get("endDate"),
        "start_utc": event.get("startDate") or (starts[0] if starts else None),
        "n_markets": len(markets),
        "yes_tokens": [t for t in (_yes_token(m) for m in markets) if t],
    }


@dataclass
class Discovery:
    market: Market
    series_id: str | None = None
    admitted: list = field(default_factory=list)
    refused: dict = field(default_factory=dict)
    inference: dict = field(default_factory=dict)
    non_highest: int = 0
    unreadable_slugs: list = field(default_factory=list)


def discover(client: PublicClient, market: Market) -> Discovery:
    out = Discovery(market)
    series = client.get_json(f"{GAMMA}/series", {"slug": market.series_slug})
    if not series:
        return out
    out.series_id = str(series[0]["id"])
    del series
    seen = set()
    for end_min, end_max in DISCOVERY_WINDOWS:
        offset = 0
        while True:
            params = {"series_id": out.series_id, "closed": "true", "limit": PAGE_LIMIT, "offset": offset,
                      "order": "endDate", "ascending": "true"}
            if end_min:
                params["end_date_min"] = end_min
            if end_max:
                params["end_date_max"] = end_max
            page = client.get_json(f"{GAMMA}/events", params)
            for raw in page:
                slug = raw.get("slug")
                if slug in seen:
                    continue
                seen.add(slug)
                if "highest-temperature" not in str(slug):
                    out.non_highest += 1
                    continue
                target, how = event_target_date(raw)
                out.inference[how] = out.inference.get(how, 0) + 1
                reason = guards.refusal_reason(target)
                if reason is not None:
                    out.refused[reason] = out.refused.get(reason, 0) + 1
                    if reason == "unreadable_event_date" and len(out.unreadable_slugs) < 25:
                        out.unreadable_slugs.append({"slug": slug, "end_date_utc": raw.get("endDate"), "how": how})
                    continue
                kept = strip_event(raw)
                kept["event_date"] = target.isoformat()
                out.admitted.append(kept)
            n = len(page)
            del page
            if n < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
    return out


# --------------------------------------------------------------------------- probe

def price_history_window(event: dict) -> tuple[int, int]:
    end = datetime.fromisoformat(str(event["end_date_utc"]).replace("Z", "+00:00"))
    start_text = event.get("start_utc")
    start = (datetime.fromisoformat(str(start_text).replace("Z", "+00:00")) if start_text
             else end - timedelta(days=3))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    start = max(start - timedelta(hours=1), end - timedelta(days=10))
    return int(start.timestamp()), int((end + timedelta(days=1)).timestamp())


def probe_token(client: PublicClient, event: dict, token: str, fidelity: int) -> dict:
    guards.require_admitted(event["event_date"])  # before any price request for this event
    start_ts, end_ts = price_history_window(event)
    before = client.stats.wire_bytes
    payload = client.get_json(f"{CLOB}/prices-history",
                              {"market": token, "startTs": start_ts, "endTs": end_ts, "fidelity": fidelity})
    wire = client.stats.wire_bytes - before
    stamps = sorted(int(point["t"]) for point in (payload or {}).get("history") or [] if "t" in point)
    del payload  # price levels are never read
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    span_days = (stamps[-1] - stamps[0]) / 86400 if len(stamps) > 1 else 0.0
    return {
        "event_date": event["event_date"],
        "fidelity_min": fidelity,
        "points": len(stamps),
        "span_days": round(span_days, 3),
        "points_per_day": round(len(stamps) / span_days, 1) if span_days > 0 else None,
        "median_gap_s": statistics.median(gaps) if gaps else None,
        "max_gap_s": max(gaps) if gaps else None,
        "regular_grid_share": (round(sum(1 for g in gaps if abs(g - 60 * fidelity) <= 5) / len(gaps), 3)
                               if gaps else None),
        "wire_bytes": wire,
    }


def sample_events(admitted: list, k: int) -> list:
    ordered = sorted(admitted, key=lambda e: e["event_date"])
    if len(ordered) <= k:
        return ordered
    picks = sorted({round(i * (len(ordered) - 1) / (k - 1)) for i in range(k)}) if k > 1 else [0]
    return [ordered[i] for i in picks]


# --------------------------------------------------------------------------- summary

def summarize(disc: Discovery, probes: list) -> dict:
    dates = sorted({e["event_date"] for e in disc.admitted})
    pre = [d for d in dates if date.fromisoformat(d) <= PRE_PANEL_LAST]
    tokens = sum(len(e["yes_tokens"]) for e in disc.admitted)
    by_fid = {}
    for fid in (1, 60):
        rows = [p for p in probes if p["fidelity_min"] == fid]
        nonempty = [p for p in rows if p["points"] > 1]
        by_fid[str(fid)] = {
            "probes": len(rows),
            "nonempty": len(nonempty),
            "median_points_per_day": (statistics.median(p["points_per_day"] for p in nonempty)
                                      if nonempty else None),
            "median_gap_s": statistics.median(p["median_gap_s"] for p in nonempty) if nonempty else None,
            "median_wire_bytes_per_token": statistics.median(p["wire_bytes"] for p in rows) if rows else None,
            "regular_grid_share_min": min((p["regular_grid_share"] for p in nonempty), default=None),
        }
    hourly_ok = bool(by_fid["60"]["nonempty"]) and by_fid["60"]["nonempty"] == by_fid["60"]["probes"] \
        and (by_fid["60"]["median_gap_s"] or 1e9) <= 3600
    return {
        "market": disc.market.id,
        "role": disc.market.role,
        "series_slug": disc.market.series_slug,
        "series_id": disc.series_id,
        "admitted_events": len(disc.admitted),
        "admitted_dates": len(dates),
        "dates_pre_panel_le_2026_05_26": len(pre),
        "dates_2026_07_31_to_09_29": len(dates) - len(pre),
        "earliest_date": dates[0] if dates else None,
        "latest_admitted_date": dates[-1] if dates else None,
        "yes_tokens": tokens,
        "mean_markets_per_event": round(tokens / len(disc.admitted), 2) if disc.admitted else None,
        "refused_events_by_reason": disc.refused,
        "date_inference": disc.inference,
        "non_highest_events_skipped": disc.non_highest,
        "unreadable_slugs_sample": disc.unreadable_slugs,
        "probe": by_fid,
        "hourly_or_better": hourly_ok,
    }


def go_verdict(rows: list) -> dict:
    ok = [r for r in rows if r["hourly_or_better"] and r["admitted_dates"] > 0]
    market_dates = sum(r["admitted_dates"] for r in ok)
    ge150 = [r["market"] for r in ok if r["admitted_dates"] >= 150]
    return {
        "markets_with_hourly_history": len(ok),
        "market_dates_at_hourly": market_dates,
        "go_pooled": market_dates >= 150 and len(ok) >= 8,
        "markets_with_ge_150_dates": len(ge150),
        "go_per_market": len(ge150) >= 8,
    }


def step2_estimate(rows: list, max_bps=MAX_RATE_BYTES_PER_S, min_interval=DEFAULT_MIN_INTERVAL_S) -> dict:
    out = {}
    for fid in ("1", "60"):
        total_bytes, total_requests = 0, 0
        for r in rows:
            per_token = r["probe"][fid]["median_wire_bytes_per_token"] or 0
            total_bytes += per_token * r["yes_tokens"]
            total_requests += r["yes_tokens"]
        out[f"fidelity_{fid}_yes_only"] = {
            "requests": total_requests,
            "wire_bytes": int(total_bytes),
            "runtime_s_lower_bound": round(max(total_requests * min_interval, total_bytes / max_bps), 1),
        }
    return out


def print_table(rows: list, verdict: dict, estimate: dict) -> None:
    head = f"{'market':14} {'role':7} {'earliest':10} {'dates':>5} {'<=05-26':>7} {'07-31+':>6} " \
           f"{'mkts/ev':>7} {'pts/d@1':>7} {'pts/d@60':>8} {'gap@60':>6} hourly"
    print(head)
    for r in rows:
        p1, p60 = r["probe"]["1"], r["probe"]["60"]
        print(f"{r['market']:14} {r['role']:7} {str(r['earliest_date']):10} {r['admitted_dates']:>5} "
              f"{r['dates_pre_panel_le_2026_05_26']:>7} {r['dates_2026_07_31_to_09_29']:>6} "
              f"{str(r['mean_markets_per_event']):>7} {str(p1['median_points_per_day']):>7} "
              f"{str(p60['median_points_per_day']):>8} {str(p60['median_gap_s']):>6} {r['hourly_or_better']}")
    print(json.dumps({"verdict": verdict, "step2_estimate": estimate}, indent=1))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="data/research/pm_price_history/step1")
    parser.add_argument("--markets", default="", help="comma-separated market ids (default: all 22)")
    parser.add_argument("--probe-events", type=int, default=3)
    parser.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL_S)
    args = parser.parse_args(argv)
    if args.min_interval < 0.2:
        raise guards.GuardRefusal("request pacing below 0.2 s is refused")
    wanted = {m for m in args.markets.split(",") if m}
    markets = [m for m in market_universe() if not wanted or m.id in wanted]
    client = PublicClient(limiter=RateLimiter(min_interval=args.min_interval))
    started = time.monotonic()
    rows = []
    for market in markets:
        disc = discover(client, market)
        probes = []
        for event in sample_events(disc.admitted, args.probe_events):
            if not event["yes_tokens"]:
                continue
            for fid in (1, 60):
                probes.append(probe_token(client, event, event["yes_tokens"][0], fid))
        rows.append(summarize(disc, probes))
        print(f"[{time.monotonic() - started:6.1f}s] {market.id}: {len(disc.admitted)} admitted events, "
              f"{client.stats.wire_bytes / 1e6:.1f} MB wire so far", file=sys.stderr)
    verdict = go_verdict(rows)
    estimate = step2_estimate(rows, min_interval=args.min_interval)
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "schema": "pm_price_history_step1_inventory_v1",
        "generated_at_utc": stamp,
        "counts_only": True,
        "guards": {"last_admitted": guards.LAST_ADMITTED.isoformat(),
                   "sealed_panel": [guards.SEALED_PANEL_FIRST.isoformat(), guards.SEALED_PANEL_LAST.isoformat()],
                   "mg1_refused_from": guards.mg1.MG1_FLOOR.isoformat()},
        "http": vars(client.stats),
        "elapsed_s": round(time.monotonic() - started, 1),
        "markets": rows,
        "verdict": verdict,
        "step2_estimate": estimate,
    }
    path = out_dir / f"inventory-{stamp}.json"
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print_table(rows, verdict, estimate)
    print(f"wrote {path}  http={vars(client.stats)}  elapsed={report['elapsed_s']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
