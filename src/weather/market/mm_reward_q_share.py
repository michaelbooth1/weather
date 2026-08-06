"""Exact sampled maker reward Q-share from retained full-depth order books."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from weather.market.mm_policy import parse_time
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("mm_reward_q_share")


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _levels(book, side):
    values = (book or {}).get("bids" if side == "YES_BID" else "asks") or []
    rows = []
    for value in values:
        if isinstance(value, dict):
            price = _number(value.get("price"))
            size = _number(value.get("size"))
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            price, size = _number(value[0]), _number(value[1])
        else:
            continue
        if price is not None and size is not None and size > 0:
            rows.append((price, size))
    return rows


def _ticks_from_best(side, price, best, tick_size):
    distance = best - price if side == "YES_BID" else price - best
    return int(math.ceil(max(0.0, distance / tick_size - 1e-9)))


def score_leg_against_book(leg, record, *, discount_factor, default_tick_size=None, default_min_order_size=0.0):
    """Score our hypothetical leg and every retained competitor level."""

    side = str(leg.get("side") or "").upper()
    if side not in {"YES_BID", "YES_ASK"}:
        return None, "unsupported_side"
    book = record.get("book") or {}
    raw_levels = _levels(book, side)
    quote_price = _number(leg.get("quote_price"))
    quote_size = _number(leg.get("quote_size"))
    tick_size = _number(leg.get("tick_size")) or _number(book.get("tick_size")) or _number(default_tick_size)
    min_order_size = _number(leg.get("min_order_size"))
    if min_order_size is None:
        min_order_size = _number(book.get("min_order_size"))
    if min_order_size is None:
        min_order_size = float(default_min_order_size or 0.0)
    if quote_price is None or quote_size is None or quote_size <= 0:
        return None, "invalid_quote_price_or_size"
    if tick_size is None or tick_size <= 0:
        return None, "missing_tick_size"
    if discount_factor is None or not 0 < float(discount_factor) <= 1:
        return None, "missing_or_invalid_discount_factor"
    if not raw_levels:
        return None, "empty_full_depth_side"
    if quote_size < min_order_size:
        own_q = 0.0
    else:
        own_q = quote_size
    raw_best = (max(price for price, _ in raw_levels) if side == "YES_BID" else min(price for price, _ in raw_levels))
    effective_best = max(raw_best, quote_price) if side == "YES_BID" else min(raw_best, quote_price)
    own_q *= float(discount_factor) ** _ticks_from_best(side, quote_price, effective_best, tick_size)
    competitor_q = sum(
        size * float(discount_factor) ** _ticks_from_best(side, price, effective_best, tick_size)
        for price, size in raw_levels
        if size >= min_order_size
    )
    denominator = own_q + competitor_q
    canonical = json.dumps(book, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "own_q": own_q,
        "competitor_q": competitor_q,
        "denominator_q": denominator,
        "sampled_q_share": own_q / denominator if denominator > 0 else None,
        "effective_best_price": effective_best,
        "raw_best_price": raw_best,
        "full_depth_level_count": len(raw_levels),
        "tick_size": tick_size,
        "min_order_size": min_order_size,
        "book_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }, None


def _iter_book_records(path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = parse_time(record.get("captured_at_utc"))
            if timestamp is None:
                continue
            yield timestamp, record


def _event_slugs(legs):
    event_slugs = getattr(legs, "event_slugs", None)
    if callable(event_slugs):
        return event_slugs()
    return sorted({str(leg.get("event_slug") or "") for leg in legs if leg.get("event_slug")})


def _event_legs(legs, event_slug):
    iterator = getattr(legs, "iter_event_sorted", None)
    if callable(iterator):
        yield from iterator(event_slug)
        return
    rows = [leg for leg in legs if str(leg.get("event_slug") or "") == event_slug]
    yield from sorted(rows, key=lambda row: (row["quote_time"], str(row.get("leg_id") or "")))


def build_sampled_reward_q_share(
    legs,
    snapshots_root,
    *,
    discount_factor,
    default_tick_size=None,
    default_min_order_size=0.0,
    max_book_age_seconds=120.0,
):
    quoted_leg_count = len(legs or [])
    if quoted_leg_count <= 0:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "NOT_APPLICABLE",
            "reason": "no_quote_legs",
            "exact_sampled": True,
            "quoted_legs": 0,
            "sampled_legs": 0,
            "blockers": [],
            "samples": [],
        }
    samples = []
    blocker_counts = Counter()
    blocker_examples = []
    sample_binding_hash = hashlib.sha256()
    by_target_date = defaultdict(lambda: {
        "quoted_legs": 0,
        "sampled_legs": 0,
        "own_q": 0.0,
        "competitor_q": 0.0,
        "blocker_counts": Counter(),
        "sample_binding_hash": hashlib.sha256(),
    })
    for leg in legs:
        target_date = str(leg.get("target_date") or "")
        if target_date:
            by_target_date[target_date]["quoted_legs"] += 1
    sample_count = 0
    own_q = 0.0
    competitor_q = 0.0

    def block(reason, leg_id=None, target_date=None):
        blocker_counts[reason] += 1
        if target_date:
            by_target_date[str(target_date)]["blocker_counts"][reason] += 1
        if len(blocker_examples) < 100:
            blocker_examples.append(f"{reason}:{leg_id}" if leg_id else reason)

    for event_slug in _event_slugs(legs):
        path = Path(snapshots_root) / event_slug / "order_books.jsonl"
        if not path.exists():
            block(f"full_depth_book_tape_missing:{event_slug}")
        leg_iterator = iter(_event_legs(legs, event_slug))
        leg = next(leg_iterator, None)
        latest_by_token = {}

        def score_current(selected):
            nonlocal sample_count, own_q, competitor_q
            leg_id = str(leg.get("leg_id") or "unknown")
            target_date = str(leg.get("target_date") or "")
            token = str(leg.get("clob_token_id") or "")
            if selected is None:
                block("book_sample_missing", leg_id, target_date)
                return
            captured_at, record = selected
            age = (leg["quote_time"] - captured_at).total_seconds()
            if age < 0 or age > float(max_book_age_seconds):
                block("book_sample_stale", leg_id, target_date)
                return
            scored, reason = score_leg_against_book(
                leg,
                record,
                discount_factor=discount_factor,
                default_tick_size=default_tick_size,
                default_min_order_size=default_min_order_size,
            )
            if reason:
                block(reason, leg_id, target_date)
                return
            sample = {
                "leg_id": leg.get("leg_id"),
                "quote_id": leg.get("quote_id"),
                "target_date": leg.get("target_date"),
                "event_slug": event_slug,
                "market_id": leg.get("market_id"),
                "clob_token_id": token,
                "side": leg.get("side"),
                "quote_time_utc": leg["quote_time"].isoformat(),
                "book_captured_at_utc": captured_at.isoformat(),
                "book_age_seconds": round(age, 6),
                "source_path": str(path),
                "capture_id": record.get("capture_id"),
                **scored,
            }
            sample_count += 1
            own_q += scored["own_q"]
            competitor_q += scored["competitor_q"]
            canonical = json.dumps(sample, sort_keys=True, separators=(",", ":"), default=str)
            sample_binding_hash.update(canonical.encode("utf-8"))
            sample_binding_hash.update(b"\n")
            if target_date:
                target = by_target_date[target_date]
                target["sampled_legs"] += 1
                target["own_q"] += scored["own_q"]
                target["competitor_q"] += scored["competitor_q"]
                target["sample_binding_hash"].update(canonical.encode("utf-8"))
                target["sample_binding_hash"].update(b"\n")
            if len(samples) < 100:
                samples.append(sample)

        for captured_at, record in _iter_book_records(path) or []:
            while leg is not None and leg["quote_time"] < captured_at:
                token = str(leg.get("clob_token_id") or "")
                score_current(latest_by_token.get(token))
                leg = next(leg_iterator, None)
            token = str(record.get("clob_token_id") or (record.get("book") or {}).get("asset_id") or "")
            latest_by_token[token] = (captured_at, record)
        while leg is not None:
            token = str(leg.get("clob_token_id") or "")
            score_current(latest_by_token.get(token))
            leg = next(leg_iterator, None)

    denominator = own_q + competitor_q
    complete = sample_count == quoted_leg_count and not blocker_counts
    blockers = [f"{reason}={count}" for reason, count in sorted(blocker_counts.items())]
    target_summaries = {}
    for target_date, target in sorted(by_target_date.items()):
        target_denominator = target["own_q"] + target["competitor_q"]
        target_complete = (
            target["sampled_legs"] == target["quoted_legs"]
            and not target["blocker_counts"]
        )
        target_summaries[target_date] = {
            "status": "PASS" if target_complete else "BLOCK",
            "exact_sampled": target_complete,
            "quoted_legs": target["quoted_legs"],
            "sampled_legs": target["sampled_legs"],
            "sample_coverage_fraction": (
                target["sampled_legs"] / target["quoted_legs"]
                if target["quoted_legs"] else 1.0
            ),
            "own_q": target["own_q"],
            "competitor_q": target["competitor_q"],
            "denominator_q": target_denominator,
            "sampled_q_share": (
                target["own_q"] / target_denominator
                if target_denominator > 0 else None
            ),
            "blockers": [
                f"{reason}={count}"
                for reason, count in sorted(target["blocker_counts"].items())
            ],
            "sample_binding_sha256": target["sample_binding_hash"].hexdigest(),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if complete else "BLOCK",
        "exact_sampled": complete,
        "denominator_source": "retained_full_depth_order_books_jsonl",
        "quoted_legs": quoted_leg_count,
        "sampled_legs": sample_count,
        "sample_coverage_fraction": sample_count / quoted_leg_count,
        "own_q": own_q,
        "competitor_q": competitor_q,
        "denominator_q": denominator,
        "sampled_q_share": own_q / denominator if denominator > 0 else None,
        "max_book_age_seconds": float(max_book_age_seconds),
        "blockers": blockers,
        "blocker_examples": blocker_examples,
        "sample_binding_sha256": sample_binding_hash.hexdigest(),
        "retained_sample_limit": 100,
        "samples": samples,
        "by_target_date": target_summaries,
    }
