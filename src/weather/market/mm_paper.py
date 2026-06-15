"""Paper-trading scorer for market-making quote-intent runs.

The scorer is intentionally offline and evidence-first. Conservative fills are
only credited when recorded trade evidence proves a passive quote was traded
strictly through, with size evidence present. A queue-aware companion uses book
delta evidence to estimate fills/misses, but never replaces the conservative
gate used for promotion.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from .mm_policy import bool_value, maybe_float, parse_time
except ImportError:  # pragma: no cover - compatibility-wrapper execution
    from weather.market.mm_policy import bool_value, maybe_float, parse_time

try:
    from ..backtesting.settlement_ledger import ledger_label_for_slug, resolve_outcome
except ImportError:  # pragma: no cover - compatibility-wrapper execution
    from weather.backtesting.settlement_ledger import ledger_label_for_slug, resolve_outcome



try:
    from .mm_paper_constants import (  # noqa: E402
        DEFAULT_BACKTEST_ROOT,
        DEFAULT_CASEBOOK,
        DEFAULT_CONFIG,
        DEFAULT_FILLS_OUT,
        DEFAULT_JSON_OUT,
        DEFAULT_KNOWN_EDGE_OUT,
        DEFAULT_KNOWN_EDGE_REPORT_OUT,
        DEFAULT_PROMOTION_REFRESH,
        DEFAULT_REPORT_OUT,
        DEFAULT_RUNS_ROOT,
        DEFAULT_SNAPSHOTS_ROOT,
        FILL_COLUMNS,
        KNOWN_EDGE_SCHEMA_VERSION,
        MARKOUT_HORIZONS,
        SCHEMA_VERSION,
    )
except ImportError:  # pragma: no cover - direct src compatibility
    from weather.market.mm_paper_constants import (  # noqa: E402
        DEFAULT_BACKTEST_ROOT,
        DEFAULT_CASEBOOK,
        DEFAULT_CONFIG,
        DEFAULT_FILLS_OUT,
        DEFAULT_JSON_OUT,
        DEFAULT_KNOWN_EDGE_OUT,
        DEFAULT_KNOWN_EDGE_REPORT_OUT,
        DEFAULT_PROMOTION_REFRESH,
        DEFAULT_REPORT_OUT,
        DEFAULT_RUNS_ROOT,
        DEFAULT_SNAPSHOTS_ROOT,
        FILL_COLUMNS,
        KNOWN_EDGE_SCHEMA_VERSION,
        MARKOUT_HORIZONS,
        SCHEMA_VERSION,
    )


def utc_now():
    return datetime.now(timezone.utc)


def generated_at_iso(now=None):
    parsed = parse_time(now) if now is not None else None
    return (parsed or utc_now()).astimezone(timezone.utc).isoformat()


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv(path, fieldnames, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return str(path)


def read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def finite_float(value, default=None):
    number = maybe_float(value)
    return default if number is None else number


def clamp01(value):
    number = maybe_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def iso_or_blank(value):
    parsed = parse_time(value)
    return parsed.isoformat() if parsed else ""


def compact_float(value, digits=6):
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, digits)


def label_numbers(label):
    import re

    return [int(value) for value in re.findall(r"-?\d+", str(label or ""))]


def band_key(row):
    kind = str(row.get("bin_kind") or row.get("winning_band_kind") or "").strip().lower()
    value = row.get("bin_value")
    if value in (None, ""):
        value = row.get("bin_value_c") or row.get("winning_band_value")
    value_hi = row.get("bin_value_hi") or row.get("winning_band_value_hi")
    value = int(float(value)) if maybe_float(value) is not None else None
    value_hi = int(float(value_hi)) if maybe_float(value_hi) is not None else None
    nums = label_numbers(row.get("range_label") or row.get("winning_band"))
    if value is None and nums:
        value = nums[0]
    if value_hi is None and nums:
        value_hi = nums[-1]
    if value_hi is None:
        value_hi = value
    if not kind:
        text = str(row.get("range_label") or row.get("winning_band") or "").lower()
        if "above" in text or "higher" in text:
            kind = "gte"
        elif "below" in text or "under" in text:
            kind = "lte"
        else:
            kind = "eq"
    return kind, value, value_hi


def band_key_text(row):
    kind, value, value_hi = band_key(row)
    if value is None:
        return ""
    if kind == "eq" and value_hi not in (None, value):
        return f"{kind}:{value}-{value_hi}"
    return f"{kind}:{value}"


def band_distance_bucket(row):
    value = finite_float(row.get("bin_value"))
    if value is None:
        nums = label_numbers(row.get("range_label"))
        value = float(nums[0]) if nums else None
    market_mid = finite_float(row.get("market_mid"))
    fair = finite_float(row.get("fair_probability"))
    if market_mid is not None and fair is not None:
        distance = abs(fair - market_mid)
        if distance < 0.01:
            return "edge_lt_1c"
        if distance < 0.03:
            return "edge_1c_3c"
        if distance < 0.08:
            return "edge_3c_8c"
        return "edge_ge_8c"
    if value is None:
        return "unknown"
    return band_key_text(row) or "unknown"


def book_imbalance_bucket(value):
    number = finite_float(value)
    if number is None:
        return "unknown"
    if number <= -0.25:
        return "ask_heavy"
    if number >= 0.25:
        return "bid_heavy"
    return "balanced"


def hour_bucket(value):
    parsed = parse_time(value)
    return f"{parsed.hour:02d}:00Z" if parsed else "unknown"


def discover_run_folders(runs_root=DEFAULT_RUNS_ROOT, run_folders=None):
    if run_folders:
        return [Path(item) for item in run_folders]
    root = Path(runs_root)
    if not root.exists():
        return []
    return sorted(
        [folder for folder in root.glob("*/*") if folder.is_dir() and (folder / "quote_intents_long.csv").exists()],
        key=lambda path: str(path),
    )


COMPATIBLE_RUN_SCHEMA_VERSIONS = {"mm_run_v0.2"}


def run_folder_eligibility(folder):
    folder = Path(folder)
    summary = read_json(folder / "run_summary.json", {}) or {}
    run_config = read_json(folder / "run_config.json", {}) or {}
    schema_version = summary.get("schema_version") or run_config.get("schema_version")
    reasons = []
    if schema_version and schema_version not in COMPATIBLE_RUN_SCHEMA_VERSIONS:
        reasons.append(f"incompatible_schema:{schema_version}")
    remediation = summary.get("preflight_remediation")
    if remediation is None:
        remediation = read_json(folder / "preflight_remediation.json", {}) or {}
    counts_toward_gate = None
    if remediation:
        counts_toward_gate = bool_value(remediation.get("counts_toward_live_forward_gate"), False)
    elif summary.get("preflight_status"):
        counts_toward_gate = summary.get("preflight_status") == "PASS"
    return {
        "run_folder": str(folder),
        "schema_version": schema_version or "unknown",
        "scoreable": not reasons,
        "live_forward_gate_counts": bool(counts_toward_gate) if counts_toward_gate is not None else True,
        "non_scoreable_reasons": reasons,
        "preflight_status": summary.get("preflight_status"),
        "remediation_counts_toward_live_forward_gate": counts_toward_gate,
        "policy_hash": summary.get("policy_hash") or run_config.get("policy_hash"),
        "run_id": summary.get("run_id") or run_config.get("run_id") or folder.name,
    }


def split_run_folders_by_eligibility(run_folders):
    eligibility = {str(Path(folder)): run_folder_eligibility(folder) for folder in run_folders}
    scoreable = [Path(folder) for folder in run_folders if eligibility[str(Path(folder))]["scoreable"]]
    excluded = [
        item
        for item in eligibility.values()
        if not item.get("scoreable")
    ]
    return scoreable, eligibility, excluded


def quote_id(row, index):
    digest = hashlib.sha1(
        "|".join([
            str(row.get("run_id") or ""),
            str(row.get("event_slug") or ""),
            str(row.get("clob_token_id") or ""),
            str(row.get("range_label") or ""),
            str(row.get("generated_at_utc") or ""),
            str(index),
        ]).encode("utf-8")
    ).hexdigest()[:12]
    return f"quote_{digest}"


def load_quote_rows(run_folders, eligibility_by_folder=None):
    rows = []
    run_configs = {}
    eligibility_by_folder = eligibility_by_folder or {}
    for folder in run_folders:
        folder = Path(folder)
        run_config = read_json(folder / "run_config.json", {}) or {}
        run_configs[str(folder)] = run_config
        eligibility = eligibility_by_folder.get(str(folder)) or run_folder_eligibility(folder)
        for index, row in enumerate(read_csv_rows(folder / "quote_intents_long.csv")):
            row = dict(row)
            row["_run_folder"] = str(folder)
            row["_quote_row_index"] = index
            row["_quote_id"] = quote_id(row, index)
            row["_run_config"] = run_config
            row["_run_schema_version"] = eligibility.get("schema_version")
            row["_run_live_forward_gate_counts"] = eligibility.get("live_forward_gate_counts", True)
            rows.append(row)
    return rows, run_configs


def quote_permission(row):
    return bool_value(row.get("quote_permission"), False)


def quote_legs(quote_rows, config):
    legs = []
    for row in quote_rows:
        if not quote_permission(row):
            continue
        quote_time = parse_time(row.get("generated_at_utc") or row.get("captured_at_utc"))
        if quote_time is None:
            continue
        common = {
            "quote_row": row,
            "quote_id": row["_quote_id"],
            "run_id": row.get("run_id") or (row.get("_run_config") or {}).get("run_id") or "",
            "run_folder": row.get("_run_folder") or "",
            "run_mode": row.get("run_mode") or (row.get("_run_config") or {}).get("mode") or "",
            "policy_hash": row.get("policy_hash") or (row.get("_run_config") or {}).get("policy_hash") or "",
            "event_slug": row.get("event_slug") or "",
            "market_id": row.get("market_id") or "",
            "target_date": row.get("target_date") or (row.get("_run_config") or {}).get("target_date") or "",
            "range_label": row.get("range_label") or "",
            "bin_kind": row.get("bin_kind") or "",
            "bin_value": row.get("bin_value") or row.get("bin_value_c") or "",
            "bin_value_hi": row.get("bin_value_hi") or "",
            "clob_token_id": row.get("clob_token_id") or row.get("asset_id") or "",
            "quote_time": quote_time,
            "market_mid": clamp01(row.get("market_mid") or row.get("market_yes")),
            "regime": row.get("regime") or "",
            "source_fresh": bool_value(row.get("source_fresh"), False),
            "source_freshness_state": row.get("source_freshness_state") or "",
            "book_imbalance_bucket": book_imbalance_bucket(row.get("book_imbalance_1pct")),
            "band_distance_bucket": band_distance_bucket(row),
            "quote_age_seconds": None,
            "reward_estimate_usdc": 0.0,
            "reward_q_min": 0.0,
            "reward_normalized_share": 0.0,
        }
        captured = parse_time(row.get("captured_at_utc"))
        if captured is not None:
            common["quote_age_seconds"] = max(0.0, (quote_time - captured).total_seconds())
        bid = clamp01(row.get("bid_price"))
        bid_size = finite_float(row.get("bid_size"), 0.0) or 0.0
        ask = clamp01(row.get("ask_price"))
        ask_size = finite_float(row.get("ask_size"), 0.0) or 0.0
        if bid is not None and bid_size > 0:
            leg = dict(common)
            leg.update({
                "leg_id": f"{common['quote_id']}:YES_BID",
                "side": "YES_BID",
                "direction": 1.0,
                "quote_price": bid,
                "quote_size": bid_size,
            })
            legs.append(leg)
        if ask is not None and ask_size > 0:
            leg = dict(common)
            leg.update({
                "leg_id": f"{common['quote_id']}:YES_ASK",
                "side": "YES_ASK",
                "direction": -1.0,
                "quote_price": ask,
                "quote_size": ask_size,
            })
            legs.append(leg)
    attach_expiry(legs, config)
    attach_reward_estimates(legs, config)
    return legs


def attach_expiry(legs, config):
    ttl = float(config["quote_ttl_seconds"])
    grouped = defaultdict(list)
    for leg in legs:
        grouped[(leg["run_id"], leg["event_slug"], leg["clob_token_id"], leg["side"])].append(leg)
    for group in grouped.values():
        group.sort(key=lambda leg: leg["quote_time"])
        for index, leg in enumerate(group):
            ttl_expiry = leg["quote_time"] + timedelta(seconds=ttl)
            next_time = group[index + 1]["quote_time"] if index + 1 < len(group) else None
            if next_time and next_time > leg["quote_time"]:
                leg["quote_expires_at"] = min(ttl_expiry, next_time)
            else:
                leg["quote_expires_at"] = ttl_expiry


def reward_leg_score(price, size, mid, min_order_size, threshold):
    if price is None or mid is None or size <= 0 or size < min_order_size:
        return 0.0
    distance = abs(float(price) - float(mid))
    if distance > threshold:
        return 0.0
    return float(size) * max(0.0, 1.0 - distance / max(threshold, 1e-9))


def attach_reward_estimates(legs, config):
    by_quote = defaultdict(list)
    for leg in legs:
        by_quote[leg["quote_id"]].append(leg)
    for quote_legs_ in by_quote.values():
        row = quote_legs_[0]["quote_row"]
        mid = quote_legs_[0].get("market_mid")
        min_order = finite_float(row.get("min_order_size"), 0.0) or 0.0
        threshold = float(config["reward_distance_threshold"])
        campaign_pool = float(config["reward_campaign_pool_usdc"])
        competitor_q = max(0.0, float(config["reward_competitor_q"]))
        scores = {}
        for leg in quote_legs_:
            scores[leg["side"]] = reward_leg_score(
                leg["quote_price"],
                leg["quote_size"],
                mid,
                min_order,
                threshold,
            )
        q_one = scores.get("YES_BID", 0.0)
        q_two = scores.get("YES_ASK", 0.0)
        c = max(1.0, float(config["reward_c"]))
        q_min = max(min(q_one, q_two), max(q_one / c, q_two / c))
        qualifying_size = max(0.0, q_min)
        normalized_share = q_min / (q_min + competitor_q) if q_min > 0 else 0.0
        estimate = campaign_pool * normalized_share
        if estimate < float(config["reward_min_payout_usdc"]):
            estimate = 0.0
        total_size = sum(leg["quote_size"] for leg in quote_legs_) or 1.0
        for leg in quote_legs_:
            leg["reward_estimate_usdc"] = estimate * (leg["quote_size"] / total_size)
            leg["reward_q_min"] = q_min
            leg["reward_qualifying_size"] = qualifying_size
            leg["reward_normalized_share"] = normalized_share
            leg["reward_formula"] = "q_min=max(min(q_one,q_two),max(q_one/c,q_two/c)); normalized=q_min/(q_min+competition_q)"


def load_trade_rows(folder):
    folder = Path(folder)
    rows = []
    missing_size_count = 0

    def add_trade(raw, source, index):
        nonlocal missing_size_count
        ts = parse_time(
            raw.get("trade_time_utc")
            or raw.get("timestamp_utc")
            or raw.get("received_at_utc")
            or raw.get("captured_at_utc")
            or raw.get("time")
        )
        token = raw.get("clob_token_id") or raw.get("asset_id") or raw.get("token_id") or raw.get("assetId")
        price = clamp01(raw.get("price") or raw.get("trade_price") or raw.get("last_trade_price"))
        size = finite_float(
            raw.get("size")
            or raw.get("trade_size")
            or raw.get("shares")
            or raw.get("amount")
            or raw.get("matched_amount")
            or raw.get("maker_amount")
        )
        if ts is None or not token or price is None:
            return
        if size is None or size <= 0:
            missing_size_count += 1
            size = None
        rows.append({
            "trade_id": f"{source}:{index}",
            "time": ts,
            "clob_token_id": str(token),
            "price": float(price),
            "size": float(size) if size is not None else None,
            "side": raw.get("side") or raw.get("taker_side") or "",
            "source": source,
            "raw": raw,
        })

    for filename in ("trades_long.csv", "market_trades.csv", "market_ws_events.csv"):
        for index, row in enumerate(read_csv_rows(folder / filename)):
            add_trade(row, filename, index)

    jsonl_index = 0
    for raw in read_jsonl(folder / "market_ws.jsonl"):
        candidates = [raw]
        payload = raw.get("payload") if isinstance(raw, dict) else None
        if isinstance(payload, dict):
            candidates.append(payload)
            for key in ("price_changes", "trades", "fills"):
                values = payload.get(key)
                if isinstance(values, list):
                    candidates.extend(item for item in values if isinstance(item, dict))
        for key in ("price_changes", "trades", "fills"):
            values = raw.get(key) if isinstance(raw, dict) else None
            if isinstance(values, list):
                candidates.extend(item for item in values if isinstance(item, dict))
        for candidate in candidates:
            if "received_at_utc" not in candidate and isinstance(raw, dict):
                candidate = {**candidate, "received_at_utc": raw.get("received_at_utc")}
            add_trade(candidate, "market_ws.jsonl", jsonl_index)
            jsonl_index += 1

    rows.sort(key=lambda row: (row["time"], row["trade_id"]))
    return rows, {"trade_rows": len(rows), "missing_size_trade_rows": missing_size_count}


def strict_trade_through(side, trade_price, quote_price):
    if side == "YES_BID":
        return trade_price < quote_price
    if side == "YES_ASK":
        return trade_price > quote_price
    return False


def load_book_rows(folder):
    rows = []
    for row in read_csv_rows(Path(folder) / "order_books_summary.csv"):
        token = row.get("clob_token_id") or row.get("asset_id") or ""
        ts = parse_time(row.get("captured_at_utc") or row.get("book_time_utc") or row.get("captured_at_local"))
        if not token or ts is None:
            continue
        best_bid = clamp01(row.get("best_bid"))
        best_ask = clamp01(row.get("best_ask"))
        midpoint = clamp01(row.get("midpoint"))
        if midpoint is None and best_bid is not None and best_ask is not None and best_ask >= best_bid:
            midpoint = (best_bid + best_ask) / 2.0
        rows.append({
            "time": ts,
            "event_slug": row.get("event_slug") or Path(folder).name,
            "market_id": row.get("market_id") or "",
            "range_label": row.get("range_label") or "",
            "bin_kind": row.get("bin_kind") or "",
            "bin_value": row.get("bin_value") or "",
            "bin_value_hi": row.get("bin_value_hi") or "",
            "clob_token_id": str(token),
            "best_bid": best_bid,
            "best_ask": best_ask,
            "midpoint": midpoint,
            "last_trade_price": clamp01(row.get("last_trade_price") or row.get("gamma_last_trade_price")),
            "bid_size_at_best": finite_float(row.get("bid_size_at_best"), 0.0) or 0.0,
            "ask_size_at_best": finite_float(row.get("ask_size_at_best"), 0.0) or 0.0,
            "bid_depth_1pct": finite_float(row.get("bid_depth_1pct"), 0.0) or 0.0,
            "ask_depth_1pct": finite_float(row.get("ask_depth_1pct"), 0.0) or 0.0,
            "tick_size": finite_float(row.get("tick_size"), 0.001) or 0.001,
            "raw": row,
        })
    rows.sort(key=lambda row: (row["clob_token_id"], row["time"]))
    return rows


def group_by_token(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["clob_token_id"]].append(row)
    for values in grouped.values():
        values.sort(key=lambda row: row["time"])
    return grouped


def nearest_row_before(rows, timestamp):
    if not rows or timestamp is None:
        return None
    times = [row["time"] for row in rows]
    pos = bisect.bisect_right(times, timestamp)
    return rows[pos - 1] if pos > 0 else None


def rows_between(rows, start, end):
    if not rows:
        return []
    times = [row["time"] for row in rows]
    lo = bisect.bisect_right(times, start)
    hi = bisect.bisect_right(times, end)
    return rows[lo:hi]


def queue_ahead_for_leg(leg, book_row):
    if not book_row:
        return None, "missing_initial_book"
    tick = max(1e-9, float(book_row.get("tick_size") or 0.001))
    price = leg["quote_price"]
    if leg["side"] == "YES_BID":
        best = book_row.get("best_bid")
        if best is None:
            return None, "missing_best_bid"
        if price > best + tick / 2.0:
            return 0.0, "improves_best_bid"
        if abs(price - best) <= tick / 2.0:
            return float(book_row.get("bid_size_at_best") or 0.0), "joins_best_bid"
        return float(book_row.get("bid_depth_1pct") or book_row.get("bid_size_at_best") or 0.0), "behind_best_bid"
    best = book_row.get("best_ask")
    if best is None:
        return None, "missing_best_ask"
    if price < best - tick / 2.0:
        return 0.0, "improves_best_ask"
    if abs(price - best) <= tick / 2.0:
        return float(book_row.get("ask_size_at_best") or 0.0), "joins_best_ask"
    return float(book_row.get("ask_depth_1pct") or book_row.get("ask_size_at_best") or 0.0), "behind_best_ask"


def queue_simulate_leg(leg, book_by_token, trades_by_token):
    books = book_by_token.get(leg["clob_token_id"]) or []
    start_row = nearest_row_before(books, leg["quote_time"])
    ahead, position = queue_ahead_for_leg(leg, start_row)
    if ahead is None:
        return {
            "leg_id": leg["leg_id"],
            "status": "missing_book",
            "estimated_fill_size": 0.0,
            "initial_queue_ahead": None,
            "depleted_ahead": 0.0,
            "reason": position,
        }
    candidates = rows_between(books, leg["quote_time"], leg["quote_expires_at"])
    max_depletion = 0.0
    touched = False
    through = False
    for row in candidates:
        if leg["side"] == "YES_BID":
            best = row.get("best_bid")
            current_size = float(row.get("bid_size_at_best") or 0.0)
            if best is not None and abs(best - leg["quote_price"]) <= float(row.get("tick_size") or 0.001) / 2.0:
                touched = True
                max_depletion = max(max_depletion, max(0.0, ahead - current_size))
            if best is not None and best < leg["quote_price"]:
                through = True
                max_depletion = max(max_depletion, ahead + leg["quote_size"])
        else:
            best = row.get("best_ask")
            current_size = float(row.get("ask_size_at_best") or 0.0)
            if best is not None and abs(best - leg["quote_price"]) <= float(row.get("tick_size") or 0.001) / 2.0:
                touched = True
                max_depletion = max(max_depletion, max(0.0, ahead - current_size))
            if best is not None and best > leg["quote_price"]:
                through = True
                max_depletion = max(max_depletion, ahead + leg["quote_size"])
    missing_size_through = any(
        strict_trade_through(leg["side"], trade["price"], leg["quote_price"]) and trade.get("size") is None
        for trade in rows_between(trades_by_token.get(leg["clob_token_id"]) or [], leg["quote_time"], leg["quote_expires_at"])
    )
    if through:
        status = "estimated_full_fill"
        estimated = leg["quote_size"]
        reason = "book_moved_through_quote_price"
    elif max_depletion > 0:
        status = "estimated_partial_or_ahead_cancellation"
        ratio = min(1.0, max_depletion / max(ahead, leg["quote_size"], 1e-9))
        estimated = leg["quote_size"] * ratio
        reason = "best_queue_size_declined"
    elif missing_size_through:
        status = "missed_missing_trade_size"
        estimated = 0.0
        reason = "strict_trade_through_seen_without_size"
    elif touched:
        status = "missed_queue_ahead"
        estimated = 0.0
        reason = "quote_price_touched_without_queue_depletion"
    else:
        status = "no_touch"
        estimated = 0.0
        reason = "book_never_reached_quote_price"
    return {
        "leg_id": leg["leg_id"],
        "status": status,
        "estimated_fill_size": compact_float(estimated) or 0.0,
        "initial_queue_ahead": compact_float(ahead),
        "depleted_ahead": compact_float(max_depletion) or 0.0,
        "reason": f"{position}; {reason}",
    }


def load_mark_rows(folder):
    folder = Path(folder)
    marks = []

    def add_mark(raw, source, token_key="clob_token_id", time_keys=("point_time_utc", "captured_at_utc", "received_at_utc")):
        token = raw.get(token_key) or raw.get("asset_id") or raw.get("token_id") or raw.get("assetId")
        ts = None
        for key in time_keys:
            ts = parse_time(raw.get(key))
            if ts is not None:
                break
        price = clamp01(raw.get("midpoint") or raw.get("price") or raw.get("last_trade_price") or raw.get("gamma_last_trade_price"))
        if price is None:
            bid = clamp01(raw.get("best_bid"))
            ask = clamp01(raw.get("best_ask"))
            if bid is not None and ask is not None and ask >= bid:
                price = (bid + ask) / 2.0
        if token and ts is not None and price is not None:
            marks.append({
                "time": ts,
                "clob_token_id": str(token),
                "price": float(price),
                "source": source,
            })

    for row in read_csv_rows(folder / "price_history.csv"):
        add_mark(row, "price_history.csv", time_keys=("point_time_utc", "timestamp_utc", "captured_at_utc"))
    for row in read_csv_rows(folder / "order_books_summary.csv"):
        add_mark(row, "order_books_summary.csv", time_keys=("captured_at_utc", "book_time_utc", "captured_at_local"))
    for row in read_csv_rows(folder / "market_ws_events.csv"):
        add_mark(row, "market_ws_events.csv", time_keys=("received_at_utc", "timestamp_utc", "captured_at_utc"))
    marks.sort(key=lambda row: (row["clob_token_id"], row["time"]))
    return marks


def mark_at(mark_by_token, token, target_time):
    rows = mark_by_token.get(str(token)) or []
    if not rows:
        return None
    times = [row["time"] for row in rows]
    pos = bisect.bisect_left(times, target_time)
    if pos < len(rows):
        return rows[pos]
    return None


def settlement_for_folder(folder, event_slug, ledger_root=None):
    folder = Path(folder)
    local = read_json(folder / "settlement.json", None)
    if local:
        return local
    try:
        return ledger_label_for_slug(event_slug, ledger_root=ledger_root)
    except TypeError:
        return ledger_label_for_slug(event_slug)


def settlement_outcome_for_leg(leg, settlement):
    if not settlement:
        return None
    bucket = finite_float(settlement.get("settlement_bucket"))
    kind, value, value_hi = band_key(leg)
    if bucket is None or value is None:
        return None
    try:
        return 1.0 if resolve_outcome(kind, value, bucket, value_hi=value_hi) else 0.0
    except TypeError:
        return 1.0 if resolve_outcome(kind, value, bucket, value_hi) else 0.0


def load_casebook_index(path):
    payload = read_json(path, {}) or {}
    index = defaultdict(list)
    for case in payload.get("cases") or []:
        event_slug = case.get("event_slug") or ""
        market_id = case.get("market_id") or ""
        label = case.get("range_label") or ""
        key = (event_slug, market_id, label)
        start = parse_time(case.get("start_time_utc") or case.get("start_time_local"))
        end = parse_time(case.get("end_time_utc") or case.get("end_time_local"))
        index[key].append({
            "case_id": case.get("case_id") or "",
            "taxonomy": case.get("taxonomy") or "",
            "start": start,
            "end": end,
        })
    return index


def casebook_for_fill(leg, fill_time, casebook_index):
    keys = [
        (leg.get("event_slug") or "", leg.get("market_id") or "", leg.get("range_label") or ""),
        (leg.get("event_slug") or "", "", leg.get("range_label") or ""),
    ]
    for key in keys:
        for case in casebook_index.get(key) or []:
            start = case.get("start")
            end = case.get("end")
            if start and end and start <= fill_time <= end:
                return case
            if start is None and end is None:
                return case
    for case in casebook_index.get(keys[0]) or []:
        return case
    return {"case_id": "", "taxonomy": ""}


def fee_equivalent(size, price, fee_rate):
    return max(0.0, float(size)) * max(0.0, float(fee_rate)) * max(0.0, float(price)) * max(0.0, 1.0 - float(price))


def compute_fill_financials(leg, fill, mark_by_token, settlement, config):
    fill_time = fill["fill_time"]
    price = fill["fill_price"]
    size = fill["fill_size"]
    direction = leg["direction"]
    mid = leg.get("market_mid")
    if mid is None:
        mid = price
    markouts = {}
    for label, seconds in MARKOUT_HORIZONS:
        mark = mark_at(mark_by_token, leg["clob_token_id"], fill_time + timedelta(seconds=seconds))
        future = mark.get("price") if mark else None
        markouts[label] = (direction * (future - price)) if future is not None else None
    mark_30m = markouts.get("30m")
    adverse_30m = None
    mark_30m_row = mark_at(mark_by_token, leg["clob_token_id"], fill_time + timedelta(seconds=1800))
    if mark_30m_row and mid is not None:
        adverse_30m = direction * (mark_30m_row["price"] - mid) * size
    outcome = settlement_outcome_for_leg(leg, settlement)
    settlement_markout = direction * (outcome - price) if outcome is not None else None
    settlement_pnl = settlement_markout * size if settlement_markout is not None else None
    if leg["side"] == "YES_BID":
        spread_capture = (mid - price) * size
    else:
        spread_capture = (price - mid) * size
    maker_fee_equiv = fee_equivalent(size, price, config["maker_fee_rate"])
    maker_rebate = maker_fee_equiv * float(config["maker_rebate_pool_share"])
    flatten_fee = fee_equivalent(size, price, config["flattening_fee_rate"])
    reward = float(leg.get("reward_estimate_usdc") or 0.0) * (size / max(leg["quote_size"], 1e-9))
    if settlement_pnl is not None:
        net = settlement_pnl + maker_rebate + reward - flatten_fee
    elif mark_30m is not None:
        net = mark_30m * size + maker_rebate + reward - flatten_fee
    else:
        net = maker_rebate + reward - flatten_fee
    return {
        "markouts": markouts,
        "settlement_outcome": outcome,
        "settlement_markout": settlement_markout,
        "settlement_pnl": settlement_pnl,
        "spread_capture": spread_capture,
        "adverse_30m": adverse_30m,
        "maker_fee_equiv": maker_fee_equiv,
        "maker_rebate": maker_rebate,
        "reward": reward,
        "flatten_fee": flatten_fee,
        "net": net,
    }


def simulate_conservative_fills(legs, snapshots_root, casebook_index, config, ledger_root=None):
    folders = {}
    diagnostics = defaultdict(lambda: {
        "trade_rows": 0,
        "missing_size_trade_rows": 0,
        "book_rows": 0,
        "mark_rows": 0,
        "settlement_available": False,
    })
    for leg in legs:
        event_slug = leg["event_slug"]
        if event_slug not in folders:
            folder = Path(snapshots_root) / event_slug
            trades, trade_diag = load_trade_rows(folder)
            books = load_book_rows(folder)
            marks = load_mark_rows(folder)
            settlement = settlement_for_folder(folder, event_slug, ledger_root=ledger_root)
            folders[event_slug] = {
                "folder": folder,
                "trades": trades,
                "trades_by_token": group_by_token(trades),
                "books": books,
                "books_by_token": group_by_token(books),
                "marks": marks,
                "marks_by_token": group_by_token(marks),
                "settlement": settlement,
            }
            diagnostics[event_slug].update(trade_diag)
            diagnostics[event_slug]["book_rows"] = len(books)
            diagnostics[event_slug]["mark_rows"] = len(marks)
            diagnostics[event_slug]["settlement_available"] = bool(settlement)

    queue_by_leg = {}
    for leg in legs:
        bundle = folders.get(leg["event_slug"]) or {}
        queue_by_leg[leg["leg_id"]] = queue_simulate_leg(
            leg,
            bundle.get("books_by_token") or {},
            bundle.get("trades_by_token") or {},
        )

    trade_remaining = {}
    for bundle in folders.values():
        for trade in bundle["trades"]:
            if trade.get("size") is not None:
                trade_remaining[trade["trade_id"]] = float(trade["size"])

    fill_rows = []
    leg_fill_sizes = Counter()
    legs_sorted = sorted(legs, key=lambda leg: (leg["quote_time"], leg["leg_id"]))
    for leg in legs_sorted:
        bundle = folders.get(leg["event_slug"]) or {}
        trade_rows = rows_between(
            (bundle.get("trades_by_token") or {}).get(leg["clob_token_id"]) or [],
            leg["quote_time"],
            leg["quote_expires_at"],
        )
        remaining_leg = float(leg["quote_size"])
        for trade in trade_rows:
            if remaining_leg <= 1e-9:
                break
            if not strict_trade_through(leg["side"], trade["price"], leg["quote_price"]):
                continue
            if trade.get("size") is None:
                continue
            remaining_trade = trade_remaining.get(trade["trade_id"], 0.0)
            if remaining_trade <= 1e-9:
                continue
            fill_size = min(remaining_leg, remaining_trade)
            if fill_size <= 1e-9:
                continue
            trade_remaining[trade["trade_id"]] = remaining_trade - fill_size
            remaining_leg -= fill_size
            leg_fill_sizes[leg["leg_id"]] += fill_size
            fill = {
                "fill_time": trade["time"],
                "fill_price": leg["quote_price"],
                "fill_size": fill_size,
                "through_trade_price": trade["price"],
                "through_trade_size": trade["size"],
                "trade_source": trade["source"],
            }
            financials = compute_fill_financials(
                leg,
                fill,
                bundle.get("marks_by_token") or {},
                bundle.get("settlement"),
                config,
            )
            case = casebook_for_fill(leg, trade["time"], casebook_index)
            queue = queue_by_leg.get(leg["leg_id"], {})
            fill_id = f"fill_{hashlib.sha1((leg['leg_id'] + trade['trade_id'] + str(leg_fill_sizes[leg['leg_id']])).encode('utf-8')).hexdigest()[:12]}"
            row = {
                "paper_schema_version": SCHEMA_VERSION,
                "run_id": leg["run_id"],
                "run_folder": leg["run_folder"],
                "run_mode": leg["run_mode"],
                "policy_hash": leg["policy_hash"],
                "quote_id": leg["quote_id"],
                "leg_id": leg["leg_id"],
                "fill_id": fill_id,
                "fill_time_utc": trade["time"].isoformat(),
                "event_slug": leg["event_slug"],
                "market_id": leg["market_id"],
                "target_date": leg["target_date"],
                "range_label": leg["range_label"],
                "bin_kind": leg["bin_kind"],
                "bin_value": leg["bin_value"],
                "bin_value_hi": leg["bin_value_hi"],
                "clob_token_id": leg["clob_token_id"],
                "side": leg["side"],
                "quote_time_utc": leg["quote_time"].isoformat(),
                "quote_expires_at_utc": leg["quote_expires_at"].isoformat(),
                "quote_age_seconds": compact_float(leg.get("quote_age_seconds")),
                "quote_price": compact_float(leg["quote_price"]),
                "quote_size": compact_float(leg["quote_size"]),
                "fill_price": compact_float(fill["fill_price"]),
                "fill_size": compact_float(fill_size),
                "through_trade_price": compact_float(trade["price"]),
                "through_trade_size": compact_float(trade.get("size")),
                "trade_source": trade["source"],
                "conservative_fill_rule": "strict_trade_through_price_and_recorded_size",
                "queue_status": queue.get("status"),
                "queue_fill_size": compact_float(queue.get("estimated_fill_size")),
                "queue_initial_ahead": compact_float(queue.get("initial_queue_ahead")),
                "queue_depleted_ahead": compact_float(queue.get("depleted_ahead")),
                "queue_reason": queue.get("reason"),
                "market_mid": compact_float(leg.get("market_mid")),
                "spread_capture_usdc": compact_float(financials["spread_capture"]),
                "adverse_selection_30m_usdc": compact_float(financials["adverse_30m"]),
                "settlement_pnl_usdc": compact_float(financials["settlement_pnl"]),
                "maker_fee_equivalent_usdc": compact_float(financials["maker_fee_equiv"]),
                "maker_rebate_estimate_usdc": compact_float(financials["maker_rebate"]),
                "liquidity_reward_estimate_usdc": compact_float(financials["reward"]),
                "flattening_fee_estimate_usdc": compact_float(financials["flatten_fee"]),
                "net_pnl_after_fees_incentives_usdc": compact_float(financials["net"]),
                "settlement_markout_per_share": compact_float(financials["settlement_markout"]),
                "settlement_outcome": compact_float(financials["settlement_outcome"]),
                "regime": leg["regime"],
                "source_fresh": leg["source_fresh"],
                "source_freshness_state": leg.get("source_freshness_state") or "",
                "book_imbalance_bucket": leg["book_imbalance_bucket"],
                "band_distance_bucket": leg["band_distance_bucket"],
                "casebook_taxonomy": case.get("taxonomy") or "",
                "casebook_case_id": case.get("case_id") or "",
            }
            for horizon, _seconds in MARKOUT_HORIZONS:
                row[f"markout_{horizon}_per_share"] = compact_float(financials["markouts"].get(horizon))
            fill_rows.append(row)
    queue_rows = list(queue_by_leg.values())
    return fill_rows, queue_rows, dict(diagnostics), leg_fill_sizes


def mean(values):
    values = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not values:
        return None
    return sum(values) / len(values)


def ci_bounds(values, z=1.96):
    values = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not values:
        return None, None
    avg = sum(values) / len(values)
    if len(values) < 2:
        return avg, avg
    stderr = statistics.stdev(values) / math.sqrt(len(values))
    return avg - z * stderr, avg + z * stderr


def sum_field(rows, key):
    return sum(finite_float(row.get(key), 0.0) or 0.0 for row in rows)


def summarize_pnl(fill_rows):
    return {
        "spread_capture_usdc": compact_float(sum_field(fill_rows, "spread_capture_usdc")),
        "adverse_selection_30m_usdc": compact_float(sum_field(fill_rows, "adverse_selection_30m_usdc")),
        "settlement_pnl_usdc": compact_float(sum_field(fill_rows, "settlement_pnl_usdc")),
        "maker_fee_equivalent_usdc": compact_float(sum_field(fill_rows, "maker_fee_equivalent_usdc")),
        "maker_rebate_estimate_usdc": compact_float(sum_field(fill_rows, "maker_rebate_estimate_usdc")),
        "liquidity_reward_estimate_usdc": compact_float(sum_field(fill_rows, "liquidity_reward_estimate_usdc")),
        "flattening_fee_estimate_usdc": compact_float(sum_field(fill_rows, "flattening_fee_estimate_usdc")),
        "net_pnl_after_fees_incentives_usdc": compact_float(sum_field(fill_rows, "net_pnl_after_fees_incentives_usdc")),
    }


def slice_key(row):
    return (
        row.get("market_id") or "unknown",
        hour_bucket(row.get("fill_time_utc")),
        row.get("band_distance_bucket") or "unknown",
        row.get("bin_kind") or "unknown",
        row.get("regime") or "unknown",
        str(row.get("source_fresh")),
        row.get("source_freshness_state") or "unknown",
        row.get("book_imbalance_bucket") or "unknown",
        row.get("casebook_taxonomy") or "unmatched",
    )


def build_markout_slices(fill_rows, config):
    grouped = defaultdict(list)
    for row in fill_rows:
        grouped[slice_key(row)].append(row)
    z = float(config["confidence_z"])
    adjustment_count = max(1, len(grouped))
    slices = []
    for key, rows in grouped.items():
        values_30m = [finite_float(row.get("markout_30m_per_share")) for row in rows]
        ci_low, ci_high = ci_bounds(values_30m, z=z)
        settlement_values = [finite_float(row.get("settlement_markout_per_share")) for row in rows]
        set_low, set_high = ci_bounds(settlement_values, z=z)
        market_id, hour, band_distance, band_type, regime, source_fresh, source_freshness_state, imbalance, taxonomy = key
        slices.append({
            "market_id": market_id,
            "hour_utc": hour,
            "band_distance_bucket": band_distance,
            "band_type": band_type,
            "regime": regime,
            "source_fresh": source_fresh,
            "source_freshness_state": source_freshness_state,
            "book_imbalance_bucket": imbalance,
            "casebook_taxonomy": taxonomy,
            "fill_count": len(rows),
            "share_count": compact_float(sum_field(rows, "fill_size")),
            "mean_markout_30m_per_share": compact_float(mean(values_30m)),
            "markout_30m_ci_low": compact_float(ci_low),
            "markout_30m_ci_high": compact_float(ci_high),
            "mean_settlement_markout_per_share": compact_float(mean(settlement_values)),
            "settlement_markout_ci_low": compact_float(set_low),
            "settlement_markout_ci_high": compact_float(set_high),
            "net_pnl_after_fees_incentives_usdc": compact_float(sum_field(rows, "net_pnl_after_fees_incentives_usdc")),
            "settlement_pnl_usdc": compact_float(sum_field(rows, "settlement_pnl_usdc")),
            "multiple_test_adjustment": "bonferroni_conservative",
            "multiple_test_family_size": adjustment_count,
            "deflated_markout_30m_per_share": compact_float(ci_low),
            "example_fill_ids": [row.get("fill_id") for row in rows[:5]],
        })
    slices.sort(key=lambda row: (row["market_id"], row["hour_utc"], row["band_distance_bucket"], row["casebook_taxonomy"]))
    return slices


def anti_overfit_summary(quote_rows, run_configs):
    run_days = sorted({row.get("target_date") for row in quote_rows if row.get("target_date")})
    policy_hashes = sorted({row.get("policy_hash") for row in quote_rows if row.get("policy_hash")})
    modes = Counter(row.get("run_mode") or (row.get("_run_config") or {}).get("mode") or "unknown" for row in quote_rows)
    split = max(1, int(math.ceil(len(run_days) * 0.7))) if run_days else 0
    return {
        "frozen_replay_days": run_days[:split],
        "heldout_validation_days": run_days[split:],
        "live_forward_days": [
            day for day in run_days
            if any(
                (
                    row.get("target_date") == day
                    and (row.get("run_mode") or (row.get("_run_config") or {}).get("mode")) == "paper-live-forward"
                    and bool_value(row.get("_run_live_forward_gate_counts"), True)
                )
                for row in quote_rows
            )
        ],
        "run_count": len(run_configs),
        "run_modes": dict(sorted(modes.items())),
        "policy_hashes": policy_hashes,
        "locked_policy_params": len(policy_hashes) == 1 if policy_hashes else False,
        "confidence_interval_method": "normal_approximation_by_slice",
        "multiple_test_adjustment": "bonferroni_conservative_ci_floor",
    }


def quote_uptime_summary(quote_rows, legs):
    quoted_ids = {leg["quote_id"] for leg in legs}
    no_quote_reasons = Counter(row.get("reason_code") or "unknown" for row in quote_rows if row["_quote_id"] not in quoted_ids)
    quote_times = [parse_time(row.get("generated_at_utc")) for row in quote_rows]
    quote_times = [ts for ts in quote_times if ts is not None]
    uptime = len(quoted_ids) / len(quote_rows) if quote_rows else 0.0
    return {
        "quote_rows": len(quote_rows),
        "quote_permission_rows": len(quoted_ids),
        "quote_uptime_fraction": compact_float(uptime),
        "first_quote_time_utc": min(quote_times).isoformat() if quote_times else None,
        "last_quote_time_utc": max(quote_times).isoformat() if quote_times else None,
        "stale_input_pulls": no_quote_reasons.get("NO_QUOTE_STALE_INPUT", 0)
            + no_quote_reasons.get("NO_QUOTE_STALE_BOOK", 0)
            + no_quote_reasons.get("NO_QUOTE_STALE_MODEL", 0)
            + no_quote_reasons.get("NO_QUOTE_STALE_WATCHER", 0),
        "no_quote_reason_counts": dict(sorted(no_quote_reasons.items())),
    }


def decisive_resting_check(legs, diagnostics):
    unresolved = []
    for leg in legs:
        event_diag = diagnostics.get(leg["event_slug"]) or {}
        if event_diag.get("settlement_available") and leg["quote_expires_at"] > leg["quote_time"]:
            continue
        if not event_diag.get("settlement_available"):
            unresolved.append({
                "leg_id": leg["leg_id"],
                "event_slug": leg["event_slug"],
                "market_id": leg["market_id"],
                "reason": "settlement_missing_for_resting_quote_audit",
            })
    return {
        "unresolved_resting_quote_count": len(unresolved),
        "unresolved_resting_quotes": unresolved[:50],
    }


def build_paper_payload(
    runs_root=DEFAULT_RUNS_ROOT,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    run_folders=None,
    casebook_path=DEFAULT_CASEBOOK,
    promotion_refresh=DEFAULT_PROMOTION_REFRESH,
    config=None,
    now=None,
    ledger_root=None,
):
    config = {**DEFAULT_CONFIG, **(config or {})}
    candidate_run_folders = discover_run_folders(runs_root, run_folders=run_folders)
    run_folders, eligibility_by_folder, excluded_run_folders = split_run_folders_by_eligibility(candidate_run_folders)
    quote_rows, run_configs = load_quote_rows(run_folders, eligibility_by_folder=eligibility_by_folder)
    legs = quote_legs(quote_rows, config)
    casebook_index = load_casebook_index(casebook_path)
    fill_rows, queue_rows, diagnostics, leg_fill_sizes = simulate_conservative_fills(
        legs,
        snapshots_root,
        casebook_index,
        config,
        ledger_root=ledger_root,
    )
    queue_summary = Counter(row.get("status") for row in queue_rows)
    slices = build_markout_slices(fill_rows, config)
    anti_overfit = anti_overfit_summary(quote_rows, run_configs)
    summary = {
        "run_folders": len(run_folders),
        "candidate_run_folders": len(candidate_run_folders),
        "excluded_run_folders": len(excluded_run_folders),
        "quote_rows": len(quote_rows),
        "quote_legs": len(legs),
        "conservative_fills": len(fill_rows),
        "conservative_filled_shares": compact_float(sum_field(fill_rows, "fill_size")),
        "queue_estimated_fill_legs": sum(1 for row in queue_rows if (finite_float(row.get("estimated_fill_size"), 0.0) or 0.0) > 0),
        "queue_estimated_filled_shares": compact_float(sum(finite_float(row.get("estimated_fill_size"), 0.0) or 0.0 for row in queue_rows)),
        "queue_status_counts": dict(sorted(queue_summary.items())),
        "trade_evidence_gaps": {
            "missing_size_trade_rows": sum(row.get("missing_size_trade_rows", 0) for row in diagnostics.values()),
            "events_without_trade_rows": sorted(
                key for key, row in diagnostics.items() if row.get("trade_rows", 0) == 0
            ),
        },
        "pnl": summarize_pnl(fill_rows),
        "anti_overfit": anti_overfit,
        "quote_uptime": quote_uptime_summary(quote_rows, legs),
        "decisive_resting_audit": decisive_resting_check(legs, diagnostics),
        "gate_status": "OPEN" if len(anti_overfit.get("live_forward_days") or []) < int(config["min_edge_allowed_live_days"]) else "PAPER_DAYS_READY",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_iso(now),
        "runs_root": str(runs_root),
        "snapshots_root": str(snapshots_root),
        "backtest_root": str(backtest_root),
        "promotion_refresh": str(promotion_refresh),
        "casebook_path": str(casebook_path),
        "config": config,
        "summary": summary,
        "event_diagnostics": diagnostics,
        "run_configs": run_configs,
        "run_folder_eligibility": eligibility_by_folder,
        "excluded_run_folders": excluded_run_folders,
        "markout_slices": slices,
        "queue_companion": queue_rows,
        "fills": fill_rows,
    }



try:
    from .mm_paper_reports import (  # noqa: E402
        build_known_edge_map,
        fmt_num,
        load_promotion_records,
        markdown_table,
        permission_for_record,
        promotion_state_from_action,
        render_known_edge_report,
        render_paper_report,
        source_freshness_gap_records,
    )
except ImportError:  # pragma: no cover - direct src compatibility
    from weather.market.mm_paper_reports import (  # noqa: E402
        build_known_edge_map,
        fmt_num,
        load_promotion_records,
        markdown_table,
        permission_for_record,
        promotion_state_from_action,
        render_known_edge_report,
        render_paper_report,
        source_freshness_gap_records,
    )


def write_outputs(
    paper_payload,
    json_out=DEFAULT_JSON_OUT,
    report_out=DEFAULT_REPORT_OUT,
    fills_out=DEFAULT_FILLS_OUT,
    known_edge_out=DEFAULT_KNOWN_EDGE_OUT,
    known_edge_report_out=DEFAULT_KNOWN_EDGE_REPORT_OUT,
    promotion_refresh=DEFAULT_PROMOTION_REFRESH,
):
    report_out = Path(report_out)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(render_paper_report(paper_payload), encoding="utf-8")
    fills_path = write_csv(fills_out, FILL_COLUMNS, paper_payload.get("fills") or [])
    known_edge = build_known_edge_map(
        paper_payload,
        promotion_refresh=promotion_refresh,
        config=paper_payload.get("config") or DEFAULT_CONFIG,
    )
    known_json = write_json(known_edge_out, known_edge)
    known_report_out = Path(known_edge_report_out)
    known_report_out.parent.mkdir(parents=True, exist_ok=True)
    known_report_out.write_text(render_known_edge_report(known_edge), encoding="utf-8")
    paper_payload["outputs"] = {
        "json": str(Path(json_out)),
        "report": str(report_out),
        "fills_csv": str(fills_path),
        "known_edge_json": str(known_json),
        "known_edge_report": str(known_report_out),
    }
    json_path = write_json(json_out, paper_payload)
    paper_payload["outputs"]["json"] = str(json_path)
    return paper_payload, known_edge


def parse_config_overrides(items):
    config = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --config override {item!r}; expected key=value.")
        key, value = item.split("=", 1)
        if key not in DEFAULT_CONFIG:
            raise SystemExit(f"Unknown paper config key {key!r}.")
        default = DEFAULT_CONFIG[key]
        if isinstance(default, bool):
            config[key] = bool_value(value)
        elif isinstance(default, int):
            config[key] = int(float(value))
        elif isinstance(default, float):
            config[key] = float(value)
        else:
            config[key] = value
    return config


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Score market-making paper quote-intent runs.")
    parser.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--run-folder", action="append", default=[], help="Explicit run folder; may be passed more than once.")
    parser.add_argument("--casebook", default=str(DEFAULT_CASEBOOK))
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--fills-out", default=str(DEFAULT_FILLS_OUT))
    parser.add_argument("--known-edge-out", default=str(DEFAULT_KNOWN_EDGE_OUT))
    parser.add_argument("--known-edge-report-out", default=str(DEFAULT_KNOWN_EDGE_REPORT_OUT))
    parser.add_argument("--ledger-root", default=None)
    parser.add_argument("--now", default=None)
    parser.add_argument("--config", action="append", default=[], help="Paper config override, key=value.")
    return parser


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    backtest_root = Path(args.backtest_root)
    config = parse_config_overrides(args.config)
    payload = build_paper_payload(
        runs_root=Path(args.runs_root),
        snapshots_root=Path(args.snapshots_root),
        backtest_root=backtest_root,
        run_folders=args.run_folder,
        casebook_path=Path(args.casebook),
        promotion_refresh=Path(args.promotion_refresh),
        config=config,
        now=parse_time(args.now) if args.now else None,
        ledger_root=Path(args.ledger_root) if args.ledger_root else None,
    )
    payload, _known_edge = write_outputs(
        payload,
        json_out=Path(args.json_out),
        report_out=Path(args.report_out),
        fills_out=Path(args.fills_out),
        known_edge_out=Path(args.known_edge_out),
        known_edge_report_out=Path(args.known_edge_report_out),
        promotion_refresh=Path(args.promotion_refresh),
    )
    summary = payload["summary"]
    print(
        "MM paper: "
        f"{summary['conservative_fills']} conservative fills, "
        f"{summary['queue_estimated_fill_legs']} queue-estimated fill legs, "
        f"gate {summary['gate_status']} -> {args.report_out}"
    )
    return payload


if __name__ == "__main__":
    main()
