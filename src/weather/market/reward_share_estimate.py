"""Bounded estimate of the liquidity-reward SHARE a small capped quoter could win.

Offline, read-only analysis. It places no orders, creates no venue evidence, and
is not a receivable: no paid reward has ever been observed by this project.

Formula (Polymarket liquidity-rewards documentation, as recorded by
``exchange_economics`` and ``docs/research/MARKET_MAKING_PLAN.md``):

* per order ``S(v, s) = ((v - s) / v) ** 2 * size`` where ``v`` is the band's max
  spread in cents (``rewards_max_spread_cents``) and ``s`` the order's distance in
  cents from the size-cutoff-adjusted midpoint; an order below
  ``rewards_min_size`` or at/beyond ``v`` scores 0;
* ``Q_one`` = bids on the YES book + asks on the complement, ``Q_two`` = asks on
  the YES book + bids on the complement;
* midpoint inside [0.10, 0.90]: ``Q_min = max(min(Q_one, Q_two),
  max(Q_one / c, Q_two / c))`` with ``c = 3``; outside that interval
  ``Q_min = min(Q_one, Q_two)`` (two-sided required);
* a maker's share of one sample = its ``Q_min`` / sum of ALL makers' ``Q_min``;
  samples are taken every minute; reward = mean share over the day x daily rate.

WHAT IS NOT OBSERVABLE, AND HOW IT IS BOUNDED
The per-maker decomposition of competing depth is NOT observable from public
books: a displayed level is an aggregate of unknown makers, and ``Q_min`` is
non-linear per maker. Two assumptions are therefore reported side by side:

(a) ``single``: all displayed qualifying depth belongs to ONE two-sided
    competitor, so the competing score is ``Q_min(Q_one, Q_two)`` (c-rule inside
    [0.10, 0.90], plain ``min`` outside).
(b) ``many``: each side's depth belongs to many makers who are each perfectly
    two-sided, so the competing score is ``mean(Q_one, Q_two)``.

For any split of the displayed depth among makers, sum(Q_min) <= mean(Q_one,
Q_two), so (b) is the largest competing score the DISPLAYED book allows and (a)
is smaller. (a) is not a strict floor: depth fragmented among one-sided makers
scores lower still. The truth is between the two or WORSE than both, because of
everything the displayed book does not carry: the venue's exact size-cutoff
midpoint, its own sampling instants, any per-market multiplier, competitors
reacting to a new quote, and our quote being filled rather than resting.

APPROXIMATIONS, ALL RECORDED IN THE OUTPUT
* The midpoint is (best bid + best ask) / 2 from the displayed YES book. The
  venue's size-cutoff-adjusted midpoint is approximated; ``--min-size-for-mid``
  ignores levels smaller than the band's min size when picking best bid/ask.
* A level qualifies when its DISPLAYED size >= min size. Displayed level size
  aggregates makers, so a level made only of sub-minimum orders is counted as
  qualifying: competition is overstated, never understated, by this rule.
* Only YES-token books are read. On this venue the NO book mirrors the YES book
  (a NO bid at q is displayed as a YES ask at 1 - q), so YES bids carry Q_one and
  YES asks carry Q_two. Reading both tokens would double count.
* Our hypothetical quote is N shares per side at d cents from the midpoint,
  snapped OUTWARD to the tick, implemented as a YES bid at ``p_bid`` plus a NO
  bid at ``1 - p_ask`` (no naked asks exist). Capital = N * p_bid + N * (1 - p_ask).
* At most one sample per condition per UTC minute is used (the first captured).
* Days-to-event uses the capture's LOCAL date; one cell = one local calendar day
  = 1,440 minutes. The venue pays per UTC day; the two are not reconciled here.
* NOTHING IS EXTRAPOLATED SILENTLY. ``reward_per_day_*`` is mean share over
  scored samples x daily rate and is only valid if unsampled minutes resemble
  sampled ones; ``reward_sampled_minutes_only_*`` counts every unsampled minute
  as zero. Coverage is printed next to both.

Book source: the closed-day raw tape ``order_books.jsonl.gz`` in each event
folder ``<snapshots-root>/<event_slug>/`` (one record per token per capture, all
levels inline, ~2.5x smaller on disk than ``order_books_long.csv.gz``), falling
back to the gzip long projection. Files are streamed line by line; un-gzipped
(possibly still being written) files are refused unless ``--allow-live-files``.

Scoring names mirror ``weather.market.maker_incentive_feasibility`` (``_order_score``
and ``_q_min``); see the attribution comments below.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import sys
import zlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from weather.paths import DATA_ROOT


SCHEMA_VERSION = "reward_share_estimate.v1"
RATES_SCHEMA_VERSION = "reward_share_rates.v1"

# Same names as weather.market.order_book_tape (asserted equal in the tests);
# kept local so this module imports nothing beyond the standard library.
RAW_BOOK_FILENAME = "order_books.jsonl"
RAW_BOOK_GZIP_FILENAME = "order_books.jsonl.gz"
GZIP_LONG_FILENAME = "order_books_long.csv.gz"
LONG_FILENAME = "order_books_long.csv"

# (representation, filename, is_live_file). Cheapest closed representation first.
SOURCE_PREFERENCE = (
    ("raw_jsonl_gzip", RAW_BOOK_GZIP_FILENAME, False),
    ("gzip_csv", GZIP_LONG_FILENAME, False),
    ("raw_jsonl", RAW_BOOK_FILENAME, True),
    ("csv", LONG_FILENAME, True),
)

SINGLE_SIDED_MIDRANGE_DIVISOR = 3.0
TWO_SIDED_REQUIRED_OUTSIDE = (0.10, 0.90)
QUOTE_SIZES = (20.0, 100.0)
QUOTE_DISTANCES_CENTS = (1.0, 2.0, 3.0)
DEFAULT_CAP_PUSD = 10.0
REPORT_CAPS_PUSD = (50.0, 200.0)
MINUTES_PER_DAY = 1440
DEFAULT_TICK = 0.01
DEFAULT_MAX_ROWS = 2_000_000
DEFAULT_MAX_EVENTS = 24
DTE_CLASS_NAMES = {0: "same_day", 1: "T+1", 2: "T+2"}

JSON_OUTPUT_NAME = "reward_share_estimate.json"
MARKDOWN_OUTPUT_NAME = "reward_share_estimate.md"

_NO_OUTCOME_MARKER = '"outcome": "No"'
_YES_OUTCOME_MARKER = '"outcome": "Yes"'
_CONDITION_MARKER = '"condition_id": "'
_CAPTURED_MARKER = '"captured_at_utc": "'


class OutputLocationRefused(ValueError):
    """The requested output path is inside a protected data directory."""


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def order_score(size, distance_cents, max_spread_cents, min_size, multiplier=1.0):
    """S(v, s) = ((v - s) / v)^2 * size; 0 below min size or at/beyond v.

    Float port of ``maker_incentive_feasibility._order_score`` (PR 55 /
    ``codex/48h-maker-integration-20260912``). That version takes a BuyQuote and
    Decimal market terms and measures distance in probability units; this one
    takes the distance directly, in cents. Same zero conditions, same quadratic.
    """

    if size is None or distance_cents is None:
        return 0.0
    if not max_spread_cents or max_spread_cents <= 0:
        return 0.0
    if size <= 0 or size < min_size:
        return 0.0
    distance = abs(distance_cents)
    if distance >= max_spread_cents:
        return 0.0
    return size * ((max_spread_cents - distance) / max_spread_cents) ** 2 * multiplier


def q_min(
    q_one,
    q_two,
    midpoint,
    divisor=SINGLE_SIDED_MIDRANGE_DIVISOR,
    interval=TWO_SIDED_REQUIRED_OUTSIDE,
):
    """Float port of ``maker_incentive_feasibility._q_min`` (inclusive interval)."""

    both = min(q_one, q_two)
    if interval[0] <= midpoint <= interval[1]:
        return max(both, max(q_one, q_two) / divisor)
    return both


def share_of(own_q, competing_q):
    if own_q <= 0:
        return 0.0
    return own_q / (own_q + max(competing_q, 0.0))


def _num(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def parse_levels(raw_levels):
    """Return ([(price, size), ...], malformed_level_count)."""

    levels = []
    malformed = 0
    if not isinstance(raw_levels, (list, tuple)):
        return levels, (0 if raw_levels is None else 1)
    for level in raw_levels:
        if not isinstance(level, dict):
            malformed += 1
            continue
        price = _num(level.get("price"))
        size = _num(level.get("size"))
        if price is None or size is None or not (0.0 < price < 1.0) or size <= 0:
            malformed += 1
            continue
        levels.append((price, size))
    return levels, malformed


def best_prices(bids, asks, size_cutoff=0.0):
    bid_prices = [price for price, size in bids if size >= size_cutoff]
    ask_prices = [price for price, size in asks if size >= size_cutoff]
    return (max(bid_prices) if bid_prices else None, min(ask_prices) if ask_prices else None)


def side_score(levels, midpoint, max_spread_cents, min_size):
    """Competing qualifying score and qualifying displayed size on one side."""

    total = 0.0
    qualifying_size = 0.0
    for price, size in levels:
        score = order_score(size, (price - midpoint) * 100.0, max_spread_cents, min_size)
        if score > 0:
            total += score
            qualifying_size += size
    return total, qualifying_size


def _floor_to_tick(value, tick):
    return round(math.floor(value / tick + 1e-9) * tick, 9)


def _ceil_to_tick(value, tick):
    return round(math.ceil(value / tick - 1e-9) * tick, 9)


def hypothetical_quote(midpoint, distance_cents, tick=DEFAULT_TICK):
    """Two-sided quote at >= ``distance_cents`` from mid, snapped outward to tick.

    A side that cannot be priced inside (0, 1) is absent (price None).
    """

    tick = tick if tick and tick > 0 else DEFAULT_TICK
    bid = _floor_to_tick(midpoint - distance_cents / 100.0, tick)
    ask = _ceil_to_tick(midpoint + distance_cents / 100.0, tick)
    if bid < tick - 1e-12:
        bid = None
    if ask > 1.0 - tick + 1e-12:
        ask = None
    return {
        "bid_price": bid,
        "ask_price": ask,
        "bid_distance_cents": None if bid is None else round((midpoint - bid) * 100.0, 9),
        "ask_distance_cents": None if ask is None else round((ask - midpoint) * 100.0, 9),
    }


def quote_capital(size, bid_price, ask_price):
    """YES bid costs N * p_bid; the ask-equivalent NO bid costs N * (1 - p_ask)."""

    capital = 0.0
    if bid_price is not None:
        capital += size * bid_price
    if ask_price is not None:
        capital += size * (1.0 - ask_price)
    return capital


def evaluate_sample(
    bids,
    asks,
    *,
    max_spread_cents,
    min_size,
    tick=DEFAULT_TICK,
    sizes=QUOTE_SIZES,
    distances_cents=QUOTE_DISTANCES_CENTS,
    min_size_for_mid=False,
):
    """Score one displayed YES book and our hypothetical quotes against it."""

    cutoff = min_size if min_size_for_mid else 0.0
    best_bid, best_ask = best_prices(bids, asks, cutoff)
    if best_bid is None or best_ask is None:
        return {"status": "one_sided_book"}
    if best_bid >= best_ask:
        return {"status": "crossed_book"}
    midpoint = (best_bid + best_ask) / 2.0
    comp_one, size_one = side_score(bids, midpoint, max_spread_cents, min_size)
    comp_two, size_two = side_score(asks, midpoint, max_spread_cents, min_size)
    competing_single = q_min(comp_one, comp_two, midpoint)
    competing_many = (comp_one + comp_two) / 2.0
    quotes = {}
    for size in sizes:
        if size < min_size:
            continue
        for distance in distances_cents:
            quote = hypothetical_quote(midpoint, distance, tick)
            own_one = order_score(size, quote["bid_distance_cents"], max_spread_cents, min_size)
            own_two = order_score(size, quote["ask_distance_cents"], max_spread_cents, min_size)
            own_q = q_min(own_one, own_two, midpoint)
            quotes[(float(size), float(distance))] = {
                **quote,
                "own_q_min": own_q,
                "share_single": share_of(own_q, competing_single),
                "share_many": share_of(own_q, competing_many),
                "capital_pusd": quote_capital(size, quote["bid_price"], quote["ask_price"]),
                "two_sided": quote["bid_price"] is not None and quote["ask_price"] is not None,
            }
    return {
        "status": "ok",
        "midpoint": midpoint,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "competing_q_one": comp_one,
        "competing_q_two": comp_two,
        "competing_single": competing_single,
        "competing_many": competing_many,
        "qualifying_size_one": size_one,
        "qualifying_size_two": size_two,
        "quotes": quotes,
    }


# --------------------------------------------------------------------------
# Output-location guard
# --------------------------------------------------------------------------

def ensure_outside_data(path, *, extra_protected=()):
    """Refuse any path inside a ``data`` directory; return the resolved path."""

    resolved = Path(path).resolve()
    if any(part.lower() == "data" for part in resolved.parts):
        raise OutputLocationRefused(f"refusing to write under a data directory: {resolved}")
    for root in (DATA_ROOT, *extra_protected):
        if root is None:
            continue
        protected = Path(root).resolve()
        if resolved == protected or protected in resolved.parents:
            raise OutputLocationRefused(f"refusing to write under protected root {protected}: {resolved}")
    return resolved


# --------------------------------------------------------------------------
# Rates
# --------------------------------------------------------------------------

def _iso_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def extract_rates(snapshot_paths, *, dates=None, include_unrewarded=False):
    """Build condition_id -> band terms from exchange-economics snapshots.

    A snapshot records the rate in force when it was taken, and rates step up as
    the event approaches, so each rate is filed under its days-to-event at the
    snapshot's target date. ``rate`` is the rate at the smallest non-negative
    days-to-event seen.
    """

    wanted = {str(value) for value in (dates or [])}
    mapping = {}
    sources = []
    for snapshot_path in snapshot_paths:
        snapshot_path = Path(snapshot_path)
        with snapshot_path.open("r", encoding="utf-8-sig") as handle:
            payload = json.load(handle)
        target = _iso_date(payload.get("verified_for_target_date") or payload.get("target_date"))
        markets = payload.get("markets") or []
        sources.append({
            "path": str(snapshot_path),
            "target_date": target.isoformat() if target else None,
            "verified_at_utc": payload.get("verified_at_utc"),
            "market_count": len(markets),
        })
        for market in markets:
            if not isinstance(market, dict):
                continue
            condition_id = str(market.get("condition_id") or "").lower()
            event_date = _iso_date(market.get("event_date"))
            if not condition_id or event_date is None:
                continue
            if wanted and event_date.isoformat() not in wanted:
                continue
            rewards = market.get("liquidity_rewards") or {}
            rate = _num(rewards.get("current_daily_rate_usdc")) or 0.0
            entry = mapping.setdefault(condition_id, {
                "rate": 0.0,
                "min_size": None,
                "max_spread_cents": None,
                "event_date": event_date.isoformat(),
                "location_id": str(market.get("location_id") or ""),
                "event_slug": str(market.get("event_slug") or ""),
                "question": str(market.get("question") or ""),
                "rates_by_days_to_event": {},
            })
            min_size = _num(rewards.get("rewards_min_size"))
            max_spread = _num(rewards.get("rewards_max_spread_cents"))
            if min_size is not None:
                entry["min_size"] = min_size
            if max_spread is not None:
                entry["max_spread_cents"] = max_spread
            days = (event_date - target).days if target else None
            key = "unknown" if days is None else str(days)
            entry["rates_by_days_to_event"][key] = rate
    for condition_id in list(mapping):
        entry = mapping[condition_id]
        by_days = entry["rates_by_days_to_event"]
        known = sorted(int(key) for key in by_days if key != "unknown" and int(key) >= 0)
        if known:
            entry["rate"] = by_days[str(known[0])]
            entry["rate_days_to_event"] = known[0]
        else:
            entry["rate"] = max(by_days.values()) if by_days else 0.0
            entry["rate_days_to_event"] = None
        if not include_unrewarded and not any(value > 0 for value in by_days.values()):
            del mapping[condition_id]
    return {
        "_meta": {
            "schema_version": RATES_SCHEMA_VERSION,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "snapshots": sources,
            "note": (
                "rates_by_days_to_event is keyed by (event_date - snapshot target date); "
                "a same-day rate is only known if a snapshot was taken on the event date."
            ),
        },
        **dict(sorted(mapping.items())),
    }


def load_rates(path, counters=None):
    """Load the condition_id -> terms mapping; invalid entries are counted."""

    counters = counters if counters is not None else {}
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("rates JSON must be an object mapping condition_id to terms")
    bands = {}
    for key, raw in payload.items():
        if str(key).startswith("_"):
            continue
        if not isinstance(raw, dict):
            _bump(counters, "bands_invalid")
            continue
        rate = _num(raw.get("rate"))
        min_size = _num(raw.get("min_size"))
        max_spread = _num(raw.get("max_spread_cents"))
        event_date = _iso_date(raw.get("event_date"))
        location_id = str(raw.get("location_id") or "")
        if rate is None or min_size is None or max_spread is None or max_spread <= 0 or event_date is None or not location_id:
            _bump(counters, "bands_invalid")
            continue
        by_days = {}
        for days_key, value in (raw.get("rates_by_days_to_event") or {}).items():
            parsed = _num(value)
            if parsed is not None:
                by_days[str(days_key)] = parsed
        bands[str(key).lower()] = {
            "condition_id": str(key).lower(),
            "rate": rate,
            "rate_days_to_event": raw.get("rate_days_to_event"),
            "rates_by_days_to_event": by_days,
            "min_size": min_size,
            "max_spread_cents": max_spread,
            "event_date": event_date.isoformat(),
            "location_id": location_id,
            "event_slug": str(raw.get("event_slug") or ""),
            "question": str(raw.get("question") or ""),
        }
    return bands


def rate_for(band, days_to_event):
    """(rate, basis). ``fallback`` means no snapshot recorded that days-to-event."""

    by_days = band.get("rates_by_days_to_event") or {}
    key = str(days_to_event)
    if key in by_days:
        return by_days[key], "exact_days_to_event"
    if not by_days and band.get("rate_days_to_event") is None:
        return band["rate"], "unqualified_rate"
    return band["rate"], "fallback_other_days_to_event"


def _event_slug(band, counters):
    if band.get("event_slug"):
        return band["event_slug"]
    try:
        from weather.market.market_config import event_slug_for_date

        return event_slug_for_date(band["event_date"], band["location_id"])
    except Exception:  # registry miss or import failure: count, do not die
        _bump(counters, "bands_without_event_slug")
        return None


# --------------------------------------------------------------------------
# Streaming book readers
# --------------------------------------------------------------------------

def _bump(counters, name, amount=1):
    counters[name] = counters.get(name, 0) + amount


def _take_row(budget):
    if budget["rows_read"] >= budget["max_rows"]:
        budget["truncated"] = True
        return False
    budget["rows_read"] += 1
    return True


def _hint(text, marker):
    start = text.find(marker)
    if start < 0:
        return None
    start += len(marker)
    end = text.find('"', start)
    if end < 0:
        return None
    return text[start:end]


def _open_text(path):
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8-sig", errors="replace", newline="")
    return path.open("r", encoding="utf-8-sig", errors="replace", newline="")


def resolve_book_source(folder, *, allow_live_files=False):
    folder = Path(folder)
    for representation, filename, is_live in SOURCE_PREFERENCE:
        if is_live and not allow_live_files:
            continue
        candidate = folder / filename
        if candidate.is_file():
            return representation, candidate
    return None, None


def sample_from_raw_record(record, counters):
    if not isinstance(record, dict) or not isinstance(record.get("book"), dict):
        return None
    book = record["book"]
    token = record.get("token") if isinstance(record.get("token"), dict) else {}
    condition_id = str(book.get("market") or token.get("condition_id") or "").lower()
    captured_at = record.get("captured_at_utc") or token.get("captured_at_utc")
    if not condition_id or not captured_at:
        return None
    bids, bad_bids = parse_levels(book.get("bids"))
    asks, bad_asks = parse_levels(book.get("asks"))
    if bad_bids or bad_asks:
        _bump(counters, "malformed_levels", bad_bids + bad_asks)
    return {
        "condition_id": condition_id,
        "captured_at_utc": str(captured_at),
        "captured_at_local": str(token.get("captured_at_local") or ""),
        "outcome": str(token.get("outcome") or record.get("outcome") or "").strip().lower(),
        "bids": bids,
        "asks": asks,
        "tick": _num(book.get("tick_size")),
    }


def iter_raw_samples(path, *, wanted_conditions, seen_minutes, counters, budget) -> Iterator[dict]:
    """Stream the raw tape; skip cheaply before JSON parsing where provable."""

    with _open_text(path) as handle:
        for line in handle:
            if not _take_row(budget):
                return
            text = line.strip()
            if not text:
                continue
            if _NO_OUTCOME_MARKER in text and _YES_OUTCOME_MARKER not in text:
                _bump(counters, "records_skipped_no_outcome")
                continue
            condition_hint = _hint(text, _CONDITION_MARKER)
            if condition_hint is not None:
                if condition_hint.lower() not in wanted_conditions:
                    _bump(counters, "records_skipped_unrewarded_condition")
                    continue
                captured_hint = _hint(text, _CAPTURED_MARKER)
                if captured_hint and (condition_hint.lower(), captured_hint[:16]) in seen_minutes:
                    _bump(counters, "records_skipped_same_minute")
                    continue
            try:
                record = json.loads(text)
            except ValueError:
                _bump(counters, "malformed_rows")
                continue
            sample = sample_from_raw_record(record, counters)
            if sample is None:
                _bump(counters, "malformed_rows")
                continue
            yield sample


def iter_long_csv_samples(path, *, counters, budget) -> Iterator[dict]:
    """Stream the long projection, grouping contiguous rows by capture_id."""

    current = None
    with _open_text(path) as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not _take_row(budget):
                break
            capture_id = (row.get("capture_id") or "").strip()
            price = _num(row.get("price"))
            size = _num(row.get("size"))
            side = (row.get("side") or "").strip().lower()
            condition_id = (row.get("condition_id") or "").strip().lower()
            captured_at = (row.get("captured_at_utc") or "").strip()
            if (
                not capture_id or not condition_id or not captured_at or side not in ("bid", "ask")
                or price is None or size is None or not (0.0 < price < 1.0) or size <= 0
            ):
                _bump(counters, "malformed_rows")
                continue
            if current is None or current["capture_id"] != capture_id:
                if current is not None:
                    yield current
                current = {
                    "capture_id": capture_id,
                    "condition_id": condition_id,
                    "captured_at_utc": captured_at,
                    "captured_at_local": (row.get("captured_at_local") or "").strip(),
                    "outcome": (row.get("outcome") or "").strip().lower(),
                    "bids": [],
                    "asks": [],
                    "tick": None,
                }
            current["bids" if side == "bid" else "asks"].append((price, size))
    if current is not None:
        yield current


def _minute_key(captured_at_utc):
    text = str(captured_at_utc or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M")


def _days_to_event(sample, band, counters):
    event_date = _iso_date(band["event_date"])
    local_date = _iso_date(sample.get("captured_at_local"))
    if local_date is None:
        _bump(counters, "samples_local_date_fallback_to_utc")
        local_date = _iso_date(sample.get("captured_at_utc"))
    if event_date is None or local_date is None:
        return None
    return (event_date - local_date).days


# --------------------------------------------------------------------------
# Accumulation
# --------------------------------------------------------------------------

class _Cell:
    """Running sums for one (condition, days-to-event) local calendar day."""

    __slots__ = (
        "minutes_with_book", "scored", "status_counts", "midpoint_sum", "comp_one_sum",
        "comp_two_sum", "size_one_sum", "size_two_sum", "quotes",
    )

    def __init__(self):
        self.minutes_with_book = 0
        self.scored = 0
        self.status_counts = {}
        self.midpoint_sum = 0.0
        self.comp_one_sum = 0.0
        self.comp_two_sum = 0.0
        self.size_one_sum = 0.0
        self.size_two_sum = 0.0
        self.quotes = {}

    def add(self, result):
        self.minutes_with_book += 1
        status = result["status"]
        self.status_counts[status] = self.status_counts.get(status, 0) + 1
        if status != "ok":
            return
        self.scored += 1
        self.midpoint_sum += result["midpoint"]
        self.comp_one_sum += result["competing_q_one"]
        self.comp_two_sum += result["competing_q_two"]
        self.size_one_sum += result["qualifying_size_one"]
        self.size_two_sum += result["qualifying_size_two"]
        for key, quote in result["quotes"].items():
            sums = self.quotes.setdefault(key, [0.0, 0.0, 0.0, 0.0, 0])
            sums[0] += quote["share_single"]
            sums[1] += quote["share_many"]
            sums[2] += quote["capital_pusd"]
            sums[3] += quote["own_q_min"]
            sums[4] += 0 if quote["two_sided"] else 1


def _dte_class(days):
    return DTE_CLASS_NAMES.get(days, f"other({days})")


def _min_size_class(min_size):
    return f"min_size_{int(round(min_size))}"


def _caps(cap_pusd):
    return sorted({float(cap_pusd), *REPORT_CAPS_PUSD})


def _cap_key(cap):
    return f"{cap:g}"


def band_rows(cells, bands, caps):
    rows = []
    for (condition_id, days), cell in sorted(cells.items(), key=lambda item: (bands[item[0][0]]["event_date"], bands[item[0][0]]["location_id"], item[0][0], item[0][1])):
        band = bands[condition_id]
        rate, rate_basis = rate_for(band, days)
        scored = cell.scored
        base = {
            "condition_id": condition_id,
            "location_id": band["location_id"],
            "event_date": band["event_date"],
            "question": band["question"],
            "days_to_event": days,
            "days_to_event_class": _dte_class(days),
            "min_size": band["min_size"],
            "min_size_class": _min_size_class(band["min_size"]),
            "max_spread_cents": band["max_spread_cents"],
            "daily_rate": rate,
            "rate_basis": rate_basis,
            "minutes_with_book_sample": cell.minutes_with_book,
            "scored_samples": scored,
            "coverage_pct_of_1440_minutes": 100.0 * cell.minutes_with_book / MINUTES_PER_DAY,
            "scored_pct_of_1440_minutes": 100.0 * scored / MINUTES_PER_DAY,
            "sample_status_counts": dict(sorted(cell.status_counts.items())),
            "mean_midpoint": cell.midpoint_sum / scored if scored else None,
            "mean_competing_q_one": cell.comp_one_sum / scored if scored else None,
            "mean_competing_q_two": cell.comp_two_sum / scored if scored else None,
            "mean_qualifying_size_bid_side": cell.size_one_sum / scored if scored else None,
            "mean_qualifying_size_ask_side": cell.size_two_sum / scored if scored else None,
        }
        if not cell.quotes:
            rows.append({**base, "quote_size": None, "quote_distance_cents": None, "note": "no scored sample or no quote size >= min size"})
            continue
        for (size, distance), sums in sorted(cell.quotes.items()):
            mean_single = sums[0] / scored
            mean_many = sums[1] / scored
            capital = sums[2] / scored
            reward_single = mean_single * rate
            reward_many = mean_many * rate
            rows.append({
                **base,
                "quote_size": size,
                "quote_distance_cents": distance,
                "mean_own_q_min": sums[3] / scored,
                "samples_quote_not_two_sided": sums[4],
                "mean_share_single": mean_single,
                "mean_share_many": mean_many,
                "reward_per_day_single": reward_single,
                "reward_per_day_many": reward_many,
                "reward_sampled_minutes_only_single": sums[0] / MINUTES_PER_DAY * rate,
                "reward_sampled_minutes_only_many": sums[1] / MINUTES_PER_DAY * rate,
                "mean_capital_pusd": capital,
                "reward_per_day_per_100_pusd_single": (reward_single / capital * 100.0) if capital > 0 else None,
                "reward_per_day_per_100_pusd_many": (reward_many / capital * 100.0) if capital > 0 else None,
                "exceeds_cap": {_cap_key(cap): capital > cap for cap in caps},
            })
    return rows


_SUM_FIELDS = (
    "daily_rate",
    "reward_per_day_single",
    "reward_per_day_many",
    "reward_sampled_minutes_only_single",
    "reward_sampled_minutes_only_many",
    "mean_capital_pusd",
)


def _new_total(caps):
    total = {"bands": 0, "scored_samples": 0, "minutes_with_book_sample": 0, "bands_rate_not_exact_days_to_event": 0}
    total.update({field: 0.0 for field in _SUM_FIELDS})
    total["within_cap"] = {
        _cap_key(cap): {"bands": 0, "bands_flagged_over_cap": 0, **{field: 0.0 for field in _SUM_FIELDS}}
        for cap in caps
    }
    return total


def totals(rows, caps, *, by_location):
    """Sum band rows per (event_date, [location], min-size class, dte class, N, d)."""

    grouped = {}
    for row in rows:
        if row.get("quote_size") is None:
            continue
        key = (
            row["event_date"],
            row["location_id"] if by_location else "ALL",
            row["min_size_class"],
            row["days_to_event_class"],
            row["quote_size"],
            row["quote_distance_cents"],
        )
        total = grouped.setdefault(key, _new_total(caps))
        total["bands"] += 1
        total["scored_samples"] += row["scored_samples"]
        total["minutes_with_book_sample"] += row["minutes_with_book_sample"]
        total["bands_rate_not_exact_days_to_event"] += 0 if row["rate_basis"] == "exact_days_to_event" else 1
        for field in _SUM_FIELDS:
            total[field] += row[field]
        for cap in caps:
            bucket = total["within_cap"][_cap_key(cap)]
            if row["exceeds_cap"][_cap_key(cap)]:
                bucket["bands_flagged_over_cap"] += 1
                continue
            bucket["bands"] += 1
            for field in _SUM_FIELDS:
                bucket[field] += row[field]
    output = []
    for key, total in sorted(grouped.items()):
        bands = total["bands"]
        capital = total["mean_capital_pusd"]
        output.append({
            "event_date": key[0],
            "location_id": key[1],
            "min_size_class": key[2],
            "days_to_event_class": key[3],
            "quote_size": key[4],
            "quote_distance_cents": key[5],
            **total,
            "mean_coverage_pct_of_1440_minutes": (
                100.0 * total["minutes_with_book_sample"] / (bands * MINUTES_PER_DAY) if bands else None
            ),
            "reward_per_day_per_100_pusd_single": (total["reward_per_day_single"] / capital * 100.0) if capital > 0 else None,
            "reward_per_day_per_100_pusd_many": (total["reward_per_day_many"] / capital * 100.0) if capital > 0 else None,
        })
    return output


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

def _parse_dates(values):
    parsed = []
    for value in values or []:
        for piece in str(value).split(","):
            piece = piece.strip()
            if not piece:
                continue
            parsed.append(date.fromisoformat(piece).isoformat())
    return sorted(set(parsed))


def run_estimate(
    *,
    rates_json,
    snapshots_root,
    dates,
    output_dir,
    cap_pusd=DEFAULT_CAP_PUSD,
    max_events=DEFAULT_MAX_EVENTS,
    max_rows=DEFAULT_MAX_ROWS,
    min_size_for_mid=False,
    allow_live_files=False,
    locations=None,
    sizes=QUOTE_SIZES,
    distances_cents=QUOTE_DISTANCES_CENTS,
):
    snapshots_root = Path(snapshots_root)
    protected = [snapshots_root]
    protected.extend(parent for parent in snapshots_root.resolve().parents if parent.name.lower() == "data")
    output_dir = ensure_outside_data(output_dir, extra_protected=protected)
    dates = _parse_dates(dates)
    if not dates:
        raise ValueError("--dates is required (event dates, YYYY-MM-DD)")
    counters: dict[str, int] = {}
    all_bands = load_rates(rates_json, counters)
    wanted_locations = {str(value).strip().lower() for value in (locations or []) if str(value).strip()}
    bands = {
        condition_id: band
        for condition_id, band in all_bands.items()
        if band["event_date"] in dates
        and (not wanted_locations or band["location_id"].lower() in wanted_locations)
    }
    events = {}
    for condition_id, band in bands.items():
        slug = _event_slug(band, counters)
        if slug:
            events.setdefault(slug, (band["event_date"], band["location_id"]))
    ordered = sorted(events, key=lambda slug: (events[slug], slug))
    selected = ordered[: max(0, int(max_events))]
    caps = _caps(cap_pusd)
    budget = {"rows_read": 0, "max_rows": int(max_rows), "truncated": False}
    cells: dict[tuple[str, int], _Cell] = {}
    sources = []
    wanted_conditions = set(bands)
    for slug in selected:
        if budget["truncated"]:
            sources.append({"event_slug": slug, "status": "not_read_max_rows_reached"})
            continue
        representation, path = resolve_book_source(snapshots_root / slug, allow_live_files=allow_live_files)
        if path is None:
            sources.append({"event_slug": slug, "status": "no_closed_book_source"})
            continue
        source = {"event_slug": slug, "status": "read", "representation": representation, "path": str(path)}
        sources.append(source)
        seen_minutes: set[tuple[str, str]] = set()
        rows_before = budget["rows_read"]
        if representation in ("raw_jsonl_gzip", "raw_jsonl"):
            samples = iter_raw_samples(
                path, wanted_conditions=wanted_conditions, seen_minutes=seen_minutes,
                counters=counters, budget=budget,
            )
        else:
            samples = iter_long_csv_samples(path, counters=counters, budget=budget)
        try:
            for sample in samples:
                _bump(counters, "records_parsed")
                if sample["outcome"] != "yes":
                    _bump(counters, "records_skipped_no_outcome")
                    continue
                band = bands.get(sample["condition_id"])
                if band is None:
                    _bump(counters, "records_skipped_unrewarded_condition")
                    continue
                minute = _minute_key(sample["captured_at_utc"])
                if minute is None:
                    _bump(counters, "malformed_rows")
                    continue
                minute_key = (sample["condition_id"], minute)
                if minute_key in seen_minutes:
                    _bump(counters, "records_skipped_same_minute")
                    continue
                seen_minutes.add(minute_key)
                days = _days_to_event(sample, band, counters)
                if days is None:
                    _bump(counters, "malformed_rows")
                    continue
                result = evaluate_sample(
                    sample["bids"], sample["asks"],
                    max_spread_cents=band["max_spread_cents"], min_size=band["min_size"],
                    tick=sample.get("tick") or DEFAULT_TICK, sizes=sizes,
                    distances_cents=distances_cents, min_size_for_mid=min_size_for_mid,
                )
                cells.setdefault((sample["condition_id"], days), _Cell()).add(result)
                _bump(counters, "minute_samples_used")
        except (OSError, EOFError, zlib.error, csv.Error) as exc:
            source["status"] = "read_error_partial"
            source["error"] = f"{type(exc).__name__}: {exc}"
            _bump(counters, "unreadable_files")
        source["rows_read"] = budget["rows_read"] - rows_before
    rows = band_rows(cells, bands, caps)
    bands_with_samples = {condition_id for condition_id, _days in cells}
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "rates_json": str(rates_json),
            "snapshots_root": str(snapshots_root),
            "event_dates": dates,
            "locations": sorted(wanted_locations),
            "cap_pusd": float(cap_pusd),
            "caps_reported": caps,
            "max_events": int(max_events),
            "max_rows": int(max_rows),
            "min_size_for_mid": bool(min_size_for_mid),
            "allow_live_files": bool(allow_live_files),
            "quote_sizes": [float(size) for size in sizes],
            "quote_distances_cents": [float(distance) for distance in distances_cents],
        },
        "assumptions": {
            "single": "all displayed qualifying depth is ONE two-sided competitor: competing Q = Q_min(Q_one, Q_two)",
            "many": "each side's depth is many perfectly two-sided makers: competing Q = mean(Q_one, Q_two)",
            "truth": "between the two or WORSE; per-maker decomposition is not observable from public books",
            "midpoint": "best bid/ask midpoint of the displayed YES book; venue size-cutoff adjustment approximated",
            "level_size": "displayed level size aggregates makers; level size >= min size overstates competition",
            "extrapolation": "none applied; reward_per_day_* assumes unsampled minutes resemble sampled ones and says so; reward_sampled_minutes_only_* treats them as zero",
            "day": "one local calendar day of 1,440 minutes per (condition, days-to-event); venue pays per UTC day",
            "receivable": "NOT a receivable; no paid reward has been observed; rate unit unconfirmed against a paid epoch",
        },
        "bounds": {
            "rows_read": budget["rows_read"],
            "truncated_by_max_rows": budget["truncated"],
            "events_available": len(ordered),
            "events_selected": len(selected),
            "events_dropped_by_max_events": ordered[len(selected):],
        },
        "counters": dict(sorted(counters.items())),
        "coverage": {
            "rewarded_bands_in_scope": len(bands),
            "rewarded_bands_with_any_sample": len(bands_with_samples),
            "rewarded_bands_without_any_sample": sorted(set(bands) - bands_with_samples),
        },
        "sources": sources,
        "fleet_totals": totals(rows, caps, by_location=False),
        "location_totals": totals(rows, caps, by_location=True),
        "bands": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / JSON_OUTPUT_NAME
    markdown_path = output_dir / MARKDOWN_OUTPUT_NAME
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    report["output_paths"] = {"json": str(json_path), "markdown": str(markdown_path)}
    return report


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def _fmt(value, digits=2):
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def _totals_table(rows, caps, *, with_location):
    header = ["event date"]
    if with_location:
        header.append("location")
    header += [
        "min size", "days to event", "N", "d (c)", "bands", "pool/day", "coverage %",
        "reward/day (a) single", "reward/day (b) many", "sampled-only (a)", "sampled-only (b)",
        "capital", "per 100 (a)", "per 100 (b)",
    ]
    for cap in caps:
        header += [f"cap {_cap_key(cap)}: bands in/over", f"cap {_cap_key(cap)}: (a)", f"cap {_cap_key(cap)}: (b)"]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows:
        cells = [row["event_date"]]
        if with_location:
            cells.append(row["location_id"])
        cells += [
            row["min_size_class"], row["days_to_event_class"], _fmt(row["quote_size"], 0),
            _fmt(row["quote_distance_cents"], 0), str(row["bands"]), _fmt(row["daily_rate"]),
            _fmt(row["mean_coverage_pct_of_1440_minutes"], 1),
            _fmt(row["reward_per_day_single"]), _fmt(row["reward_per_day_many"]),
            _fmt(row["reward_sampled_minutes_only_single"]), _fmt(row["reward_sampled_minutes_only_many"]),
            _fmt(row["mean_capital_pusd"]), _fmt(row["reward_per_day_per_100_pusd_single"]),
            _fmt(row["reward_per_day_per_100_pusd_many"]),
        ]
        for cap in caps:
            bucket = row["within_cap"][_cap_key(cap)]
            cells += [
                f"{bucket['bands']}/{bucket['bands_flagged_over_cap']}",
                _fmt(bucket["reward_per_day_single"]), _fmt(bucket["reward_per_day_many"]),
            ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render_markdown(report):
    inputs = report["inputs"]
    bounds = report["bounds"]
    coverage = report["coverage"]
    caps = inputs["caps_reported"]
    lines = [
        "# Reward-share estimate (hypothetical quotes, displayed books)",
        "",
        f"Generated {report['generated_at_utc']}. Event dates: {', '.join(inputs['event_dates'])}.",
        "",
        "**Not a receivable.** No paid reward has been observed by this project. Share is bounded, not measured:",
        "",
    ]
    lines += [f"- **{name}**: {text}" for name, text in report["assumptions"].items()]
    lines += [
        "",
        "## Bounds and coverage",
        "",
        f"- rows read: {bounds['rows_read']:,} (max {inputs['max_rows']:,}); "
        f"**truncated by max-rows: {_fmt(bounds['truncated_by_max_rows'])}**",
        f"- events selected: {bounds['events_selected']} of {bounds['events_available']}; "
        f"dropped by max-events: {len(bounds['events_dropped_by_max_events'])}",
        f"- rewarded bands in scope: {coverage['rewarded_bands_in_scope']}; with any sample: "
        f"{coverage['rewarded_bands_with_any_sample']}; WITHOUT any sample: "
        f"{len(coverage['rewarded_bands_without_any_sample'])}",
        "- coverage % = minutes with a book sample / 1,440. Where it is below 100 the reward/day columns rest on the "
        "assumption that unsampled minutes look like sampled ones; the sampled-only columns make no such assumption.",
        "- a band whose mean capital exceeds a cap is excluded from that cap's columns and counted as 'over'.",
        "",
        "### Counters",
        "",
    ]
    lines += [f"- {name}: {value:,}" for name, value in report["counters"].items()] or ["- (none)"]
    lines += ["", "### Sources", ""]
    for source in report["sources"]:
        lines.append(
            f"- {source['event_slug']}: {source['status']}"
            + (f" ({source.get('representation')}, {source.get('rows_read', 0):,} rows)" if source.get("representation") else "")
            + (f" ERROR {source['error']}" if source.get("error") else "")
        )
    if not report["sources"]:
        lines.append("- (no events selected)")
    lines += ["", "## Fleet totals per event date", ""]
    lines += _totals_table(report["fleet_totals"], caps, with_location=False) if report["fleet_totals"] else ["(no scored samples)"]
    lines += ["", "## Per location", ""]
    lines += _totals_table(report["location_totals"], caps, with_location=True) if report["location_totals"] else ["(no scored samples)"]
    lines += ["", f"Per-band rows are in `{JSON_OUTPUT_NAME}` under `bands`.", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="python -m weather.market.reward_share_estimate",
        description="Bounded liquidity-reward share estimate from captured books (offline, read-only).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    estimate = commands.add_parser("estimate", help="stream closed book tapes and write JSON + markdown")
    estimate.add_argument("--rates-json", required=True, help="condition_id -> terms mapping (see extract-rates)")
    estimate.add_argument("--snapshots-root", required=True, help="folder holding one <event_slug>/ folder per event")
    estimate.add_argument("--dates", required=True, nargs="+", help="EVENT dates, YYYY-MM-DD (space or comma separated)")
    estimate.add_argument("--output-dir", required=True, help="must be outside any data directory")
    estimate.add_argument("--cap-pusd", type=float, default=DEFAULT_CAP_PUSD)
    estimate.add_argument("--max-events", type=int, default=DEFAULT_MAX_EVENTS)
    estimate.add_argument("--max-rows", type=int, default=DEFAULT_MAX_ROWS, help="hard stop on tape lines/rows read")
    estimate.add_argument("--locations", nargs="*", default=None)
    estimate.add_argument("--min-size-for-mid", action="store_true", help="ignore levels below the band's min size when picking best bid/ask")
    estimate.add_argument("--allow-live-files", action="store_true", help="also read un-gzipped tapes that may still be written")

    rates = commands.add_parser("extract-rates", help="write the condition_id -> terms mapping from snapshots")
    rates.add_argument("--snapshot", required=True, action="append", help="exchange_economics_snapshot.json (repeatable)")
    rates.add_argument("--output", required=True, help="rates JSON path; must be outside any data directory")
    rates.add_argument("--dates", nargs="*", default=None, help="keep only these EVENT dates")
    rates.add_argument("--include-unrewarded", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "extract-rates":
            output = ensure_outside_data(args.output)
            mapping = extract_rates(
                args.snapshot, dates=_parse_dates(args.dates), include_unrewarded=args.include_unrewarded,
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8")
            print(f"wrote {len(mapping) - 1} conditions to {output}")
            return 0
        report = run_estimate(
            rates_json=args.rates_json, snapshots_root=args.snapshots_root, dates=args.dates,
            output_dir=args.output_dir, cap_pusd=args.cap_pusd, max_events=args.max_events,
            max_rows=args.max_rows, min_size_for_mid=args.min_size_for_mid,
            allow_live_files=args.allow_live_files, locations=args.locations,
        )
    except OutputLocationRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {report['output_paths']['json']}")
    print(f"wrote {report['output_paths']['markdown']}")
    if report["bounds"]["truncated_by_max_rows"]:
        print("TRUNCATED: --max-rows reached; totals are partial", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
