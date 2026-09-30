"""Read-only liquidity-reward opportunity scanner; places, cancels and signs nothing.

Runbook: docs/operations/reward-scan.md. For each active weather market in
``config/location_market_events.json`` (plus explicit ``--condition`` ids) it reads
the public CLOB reward terms and YES book, and the owner's pool percentages through
the wallet-reader client CLI in a child process, so no reader, credential, signing
or order module is ever imported here. Output is owner-discretionary research.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from weather.market.reward_share_estimate import best_prices, parse_levels
from weather.paths import config_path, data_path
from weather.schema_registry import schema_version

CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"
CONDITION = re.compile(r"0x[0-9a-fA-F]{64}\Z")
TOKEN = re.compile(r"[0-9]{1,78}\Z")
CAMPAIGN = "owner-discretionary"
MID_BAND = (0.10, 0.90)
ONE_SIDED_DIVISOR = 3
DEFAULT_TICK = 0.01
MAX_BODY = 2_000_000
REWARD_PAGES = 3


class ScanRefused(RuntimeError):
    """A request outside the public GET allow-list; raised before any socket opens."""


def check_public_get(method, host, path, params):
    """The single allow-list: exact hosts, paths and query names, GET only."""
    if method != "GET" or not isinstance(params, dict):
        raise ScanRefused("method_or_params_refused")
    if host == CLOB and path == "/book":
        allowed = {"token_id"} == set(params) and TOKEN.fullmatch(str(params["token_id"]))
    elif host == CLOB and path.startswith("/rewards/markets/") and CONDITION.fullmatch(path[17:]):
        allowed = set(params) <= {"next_cursor"} and all(
            isinstance(v, str) and 0 < len(v) <= 256 and v.isprintable() for v in params.values())
    elif host == GAMMA and path == "/markets":
        ids = params.get("condition_ids")
        allowed = (set(params) == {"condition_ids", "limit"} and isinstance(ids, list)
                   and 1 <= len(ids) <= 20 and all(isinstance(i, str) and CONDITION.fullmatch(i) for i in ids)
                   and params["limit"] == len(ids))
    else:
        allowed = False
    if not allowed:
        raise ScanRefused("public_request_refused")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PublicReader:
    """Paced, budgeted, unauthenticated GETs; no proxies, redirects or retries."""

    def __init__(self, *, opener=None, max_gets=2000, min_interval=0.2, deadline_seconds=780,
                 clock=time.monotonic, sleep=time.sleep):
        self.opener = opener if opener is not None else build_opener(ProxyHandler({}), _NoRedirect())
        self.max_gets, self.min_interval = max_gets, min_interval
        self.clock, self.sleep = clock, sleep
        self.deadline = clock() + deadline_seconds
        self.used, self.failed, self._last = 0, 0, None

    def remaining(self):
        return 0 if self.clock() >= self.deadline else max(0, self.max_gets - self.used)

    def get(self, host, path, params=None):
        params = {} if params is None else dict(params)
        check_public_get("GET", host, path, params)
        if self.remaining() <= 0:
            raise ScanRefused("budget_exhausted")
        if self._last is not None:
            wait = self.min_interval - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        url = host + path + ("?" + urlencode(sorted(params.items()), doseq=True) if params else "")
        self.used += 1
        self._last = self.clock()
        request = Request(url, method="GET", headers={"Accept": "application/json",
                                                       "User-Agent": "weather-reward-scan/1"})
        try:
            with self.opener.open(request, timeout=max(0.5, min(5.0, self.deadline - self.clock()))) as response:
                raw = response.read(MAX_BODY + 1)
                if response.status != 200 or response.geturl() != url or len(raw) > MAX_BODY:
                    raise ValueError("response_refused")
                value = json.loads(raw)
        except HTTPError as exc:
            exc.close()
            self.failed += 1
            raise ScanRefused(f"http_{exc.code}") from None
        except Exception:
            self.failed += 1
            raise ScanRefused("upstream_unavailable") from None
        if not isinstance(value, (dict, list)):
            self.failed += 1
            raise ScanRefused("upstream_shape_refused")
        return value


def _num(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _r(value, digits=6):
    return None if value is None else round(value, digits)


def active_markets(events_config, now_utc):
    """Order-book-enabled, open markets of events that have not ended, nearest first."""
    found = []
    for location in events_config.get("locations", []):
        for event in location.get("active_events", []):
            end = event.get("end_date")
            try:
                if datetime.fromisoformat(str(end).replace("Z", "+00:00")) <= now_utc:
                    continue
            except ValueError:
                continue
            for market in event.get("markets", []):
                tokens = market.get("outcome_tokens") or {}
                if (market.get("active") is True and market.get("closed") is False
                        and market.get("enable_order_book") is True
                        and CONDITION.fullmatch(str(market.get("condition_id", "")))
                        and set(tokens) == {"Yes", "No"} and all(TOKEN.fullmatch(str(t)) for t in tokens.values())):
                    found.append(dict(source="location_market_events", location_id=location.get("location_id"),
                                      event_slug=event.get("event_slug"), event_date=event.get("event_date"),
                                      condition_id=market["condition_id"], question=market.get("question"),
                                      yes_token=tokens["Yes"], no_token=tokens["No"]))
    found.sort(key=lambda m: (str(m["event_date"]), m["condition_id"]))
    return found


def extra_markets(reader, conditions):
    """Explicit binary conditions (e.g. YouTube view markets) resolved through Gamma."""
    found, errors = [], {}
    for start in range(0, len(conditions), 20):
        chunk = conditions[start:start + 20]
        try:
            batch = reader.get(GAMMA, "/markets", {"condition_ids": chunk, "limit": len(chunk)})
        except ScanRefused as exc:
            errors.update({c: str(exc) for c in chunk})
            continue
        by_id = {str(m.get("conditionId", "")).lower(): m for m in batch if isinstance(m, dict)}
        for condition in chunk:
            market = by_id.get(condition.lower())
            try:
                tokens = market["clobTokenIds"]
                outcomes = market["outcomes"]
                tokens = json.loads(tokens) if isinstance(tokens, str) else tokens
                outcomes = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
                if len(tokens) != 2 or len(outcomes) != 2 or not all(TOKEN.fullmatch(str(t)) for t in tokens):
                    raise ValueError
                if market.get("closed") is True or market.get("active") is not True:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                errors[condition] = "extra_market_unreadable_or_closed"
                continue
            found.append(dict(source="explicit_condition", location_id=None, event_slug=market.get("slug"),
                              event_date=str(market.get("endDate", ""))[:10] or None, condition_id=condition,
                              question=market.get("question"), yes_token=str(tokens[0]), no_token=str(tokens[1]),
                              outcome_names=[str(o) for o in outcomes]))
    return found, errors


def reward_terms(reader, condition, day):
    """Bounded cursor walk of the public per-market reward record."""
    rows, cursor, seen = [], None, set()
    for _ in range(REWARD_PAGES):
        page = reader.get(CLOB, "/rewards/markets/" + condition, {"next_cursor": cursor} if cursor else {})
        if not isinstance(page, dict) or not isinstance(page.get("data"), list):
            raise ScanRefused("reward_page_unreadable")
        rows.extend(r for r in page["data"] if isinstance(r, dict))
        cursor = page.get("next_cursor")
        if not cursor or cursor in ("LTE=", "-1"):
            break
        if cursor in seen:
            raise ScanRefused("reward_cursor_repeated")
        seen.add(cursor)
    else:
        raise ScanRefused("reward_pagination_incomplete")
    matching = [r for r in rows if str(r.get("condition_id", "")).lower() == condition.lower()]
    if len(matching) > 1:
        raise ScanRefused("reward_condition_ambiguous")
    if not matching:
        return None
    record = matching[0]
    rate = 0.0
    for config in record.get("rewards_config") or []:
        if str(config.get("start_date", ""))[:10] <= day <= str(config.get("end_date", "9999"))[:10]:
            value = _num(config.get("rate_per_day"))
            if value is None or value < 0:
                raise ScanRefused("reward_rate_unreadable")
            rate += value
    return dict(daily_rate=rate, max_spread_cents=_num(record.get("rewards_max_spread")),
                min_size=_num(record.get("rewards_min_size")))


def outcome_view(bids, asks, terms, tick):
    """Per-outcome reward geometry against the displayed, pre-quote book."""
    view = dict(best_bid=None, best_ask=None, mid=None, spread=None, mid_in_reward_band=None,
                one_sided_score_factor=None, resting_bid_size_in_band=None, resting_ask_size_in_band=None,
                tightest_eligible_bid=None, tightest_eligible_distance_cents=None, cash_needed_pusd=None,
                status="observed")
    raw_bid, raw_ask = best_prices(bids, asks)
    view.update(best_bid=raw_bid, best_ask=raw_ask,
                spread=_r(raw_ask - raw_bid) if raw_bid is not None and raw_ask is not None else None)
    max_spread, min_size = terms["max_spread_cents"], terms["min_size"]
    if not max_spread or max_spread <= 0 or min_size is None or min_size < 0:
        view["status"] = "reward_terms_incomplete"
        return view
    # Venue midpoint ignores levels below min size; approximated from displayed levels.
    bid, ask = best_prices(bids, asks, size_cutoff=min_size)
    if bid is None or ask is None or bid > ask:
        view["status"] = "two_sided_mid_unavailable"
        return view
    mid = (bid + ask) / 2
    inside = MID_BAND[0] <= mid <= MID_BAND[1]
    band = max_spread / 100
    view.update(mid=_r(mid), mid_in_reward_band=inside, one_sided_score_factor=_r(1 / ONE_SIDED_DIVISOR) if inside else 0.0,
                resting_bid_size_in_band=_r(sum(s for p, s in bids if s >= min_size and mid - p < band)),
                resting_ask_size_in_band=_r(sum(s for p, s in asks if s >= min_size and p - mid < band)))
    price = round(math.floor(mid / tick + 1e-9) * tick, 9)
    if raw_ask is not None and price >= raw_ask:
        price = round(raw_ask - tick, 9)
    distance = (mid - price) * 100
    if price >= tick - 1e-12 and distance < max_spread:
        view.update(tightest_eligible_bid=_r(price), tightest_eligible_distance_cents=_r(distance, 4),
                    cash_needed_pusd=_r(max(min_size, 0) * price, 4))
    else:
        view["status"] = "no_eligible_bid_inside_band"
    return view


def mirrored(levels):
    """The NO book is the YES book reflected: a YES ask at q is a NO bid at 1 - q."""
    return [(round(1 - p, 9), s) for p, s in levels]


def scan_market(reader, market, day, pool):
    base = {k: market.get(k) for k in ("source", "location_id", "event_slug", "event_date", "condition_id", "question")}
    base.update(daily_reward_rate=None, max_spread_cents=None, min_size=None, tick_size=None,
                our_pool_percentage=pool.get(market["condition_id"].lower()), errors=[])
    names = market.get("outcome_names") or ["Yes", "No"]
    def rows(status, views=(None, None)):
        return [dict(base, outcome=name, token_id=token, status=(view or {}).get("status", status),
                     **{k: v for k, v in (view or {}).items() if k != "status"})
                for name, token, view in zip(names, (market["yes_token"], market["no_token"]), views)]
    try:
        terms = reward_terms(reader, market["condition_id"], day)
    except ScanRefused as exc:
        base["errors"].append("reward_terms:" + str(exc))
        return rows("budget_deferred" if str(exc) == "budget_exhausted" else "reward_terms_unavailable")
    if terms is None or terms["daily_rate"] <= 0:
        base["daily_reward_rate"] = 0.0 if terms else None
        return rows("no_active_reward")
    base.update(daily_reward_rate=_r(terms["daily_rate"]), max_spread_cents=terms["max_spread_cents"],
                min_size=terms["min_size"])
    try:
        book = reader.get(CLOB, "/book", {"token_id": market["yes_token"]})
        if (not isinstance(book, dict) or str(book.get("asset_id", book.get("token_id"))) != market["yes_token"]
                or str(book.get("market", "")).lower() != market["condition_id"].lower()):
            raise ScanRefused("book_identity_refused")
        bids, bad_bids = parse_levels(book.get("bids"))
        asks, bad_asks = parse_levels(book.get("asks"))
        if bad_bids or bad_asks:
            raise ScanRefused("book_levels_malformed")
    except ScanRefused as exc:
        base["errors"].append("book:" + str(exc))
        return rows("budget_deferred" if str(exc) == "budget_exhausted" else "book_unavailable")
    tick = _num(book.get("tick_size")) or DEFAULT_TICK
    base["tick_size"] = tick
    return rows("observed", (outcome_view(bids, asks, terms, tick),
                             outcome_view(mirrored(asks), mirrored(bids), terms, tick)))


def pool_percentages(payload):
    """Condition -> our pool percentage from the reader /rewards response, tolerant of shape."""
    found = {}
    value = payload.get("percentages") if isinstance(payload, dict) else None
    if isinstance(value, dict):
        value = value.get("data", value)
    if isinstance(value, dict):
        found = {str(k).lower(): _num(v) for k, v in value.items() if CONDITION.fullmatch(str(k))}
    elif isinstance(value, list):
        for row in value:
            if isinstance(row, dict) and CONDITION.fullmatch(str(row.get("condition_id", ""))):
                found[row["condition_id"].lower()] = _num(row.get("percentage", row.get("percent")))
    return found


def read_reader_rewards(day, *, timeout=60):
    """Invoke the GET-only wallet-reader client CLI; its modules never load in this process."""
    command = [sys.executable, "-m", "weather.market.wallet_reader_client", "rewards", "--date", day, "--timeout", "20"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        payload = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        return None, "reader_client_unavailable"
    if result.returncode != 0 or not isinstance(payload, dict) or "error" in payload:
        reason = payload.get("reason") if isinstance(payload, dict) else None
        return None, "reader_" + (reason if isinstance(reason, str) and re.fullmatch(r"[a-z0-9_]{1,24}", reason) else "failed")
    return payload, None


def run_scan(*, reader, events_config, conditions=(), reader_rewards=None, now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    day = now_utc.date().isoformat()
    payload, pool_error = (reader_rewards(day) if reader_rewards is not None else (None, "reader_not_requested"))
    pool = pool_percentages(payload) if payload is not None else {}
    markets = active_markets(events_config, now_utc)
    extras, extra_errors = extra_markets(reader, sorted(set(conditions))) if conditions else ([], {})
    known = {m["condition_id"].lower() for m in markets}
    markets += [m for m in extras if m["condition_id"].lower() not in known]
    outcomes = []
    for market in markets:
        outcomes.extend(scan_market(reader, market, day, pool))
    counts = {}
    for row in outcomes:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return dict(schema_version=schema_version("reward_scan"), campaign=CAMPAIGN,
                captured_at_utc=now_utc.isoformat(), reward_day_utc=day,
                config_generated_at_utc=events_config.get("generated_at_utc"),
                markets_considered=len(markets), outcome_count=len(outcomes), status_counts=counts,
                pool_percentage_status="observed" if payload is not None else pool_error,
                explicit_condition_errors=extra_errors,
                public_gets=dict(used=reader.used, failed=reader.failed, max=reader.max_gets),
                notes=["read_only_no_orders", "mid_is_size_cutoff_approximation_from_displayed_levels",
                       "no_book_is_mirrored_yes_book", "distance_measured_against_pre_quote_mid",
                       "cash_needed_is_min_size_times_tightest_eligible_bid"],
                outcomes=outcomes)


def write_atomic(path, value):
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, allow_nan=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="One read-only scan; writes a timestamped file and latest.json")
    scan.add_argument("--out", type=Path, default=data_path("reward_scan"), help="Output directory (default data/reward_scan)")
    scan.add_argument("--condition", action="append", default=[], help="Extra condition id (repeatable)")
    scan.add_argument("--events-config", type=Path, default=config_path("location_market_events.json"))
    scan.add_argument("--no-reader", action="store_true", help="Skip the wallet-reader pool percentage read")
    scan.add_argument("--max-gets", type=int, default=2000, help="Public GET budget per scan (default 2000)")
    scan.add_argument("--min-interval", type=float, default=0.2, help="Seconds between public GETs (default 0.2)")
    scan.add_argument("--deadline-seconds", type=float, default=780, help="Stop opening GETs after this (default 780)")
    args = parser.parse_args(argv)
    if (any(not CONDITION.fullmatch(c) for c in args.condition) or not 1 <= args.max_gets <= 10_000
            or not 0.05 <= args.min_interval <= 10 or not 10 <= args.deadline_seconds <= 3600):
        print(json.dumps({"error": "reward_scan_arguments_refused"}))
        return 2
    events = json.loads(args.events_config.read_text(encoding="utf-8"))
    reader = PublicReader(max_gets=args.max_gets, min_interval=args.min_interval, deadline_seconds=args.deadline_seconds)
    result = run_scan(reader=reader, events_config=events, conditions=args.condition,
                      reader_rewards=None if args.no_reader else read_reader_rewards)
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(result["captured_at_utc"]).strftime("%Y%m%dT%H%M%SZ")
    write_atomic(args.out / f"reward_scan_{stamp}.json", result)
    write_atomic(args.out / "latest.json", result)
    print(json.dumps({"out": str(args.out / f"reward_scan_{stamp}.json"), "outcomes": result["outcome_count"],
                      "status_counts": result["status_counts"], "public_gets": result["public_gets"],
                      "pool_percentage_status": result["pool_percentage_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
