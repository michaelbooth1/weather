"""Pure shadow market-making policy and quote-intent tape writer.

This module has no execution adapter and no private-key dependency. It turns
latest fair values, promotion state, book freshness, observation-trigger
health, and risk caps into auditable quote or no-quote intents.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.market.market_microstructure_features import snapshot_band_key
from weather.market.market_registry import REGISTRY, spec_for_slug


SCHEMA_VERSION = "mm_quote_intent_v0.1"
POLICY_VERSION = "mm_policy_v0.1"
DEFAULT_PROMOTION_REFRESH = Path("data") / "backtest" / "f_family_promotion_refresh.json"
DEFAULT_KNOWN_EDGE_MAP = Path("data") / "backtest" / "mm_known_edge_map.json"
DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"
DEFAULT_OBSERVATION_STATUS = DEFAULT_SNAPSHOTS_ROOT / "observation_trigger_status.json"
DEFAULT_OUT = Path("data") / "backtest" / "quotes_long.csv"
DEFAULT_JSON_OUT = Path("data") / "backtest" / "mm_policy_shadow.json"

DEFAULT_POLICY_CONFIG = {
    "policy_version": POLICY_VERSION,
    "tick_size": 0.001,
    "min_price": 0.001,
    "max_price": 0.999,
    "quote_size": 5.0,
    "harvest_half_spread": 0.01,
    "max_book_age_seconds": 120.0,
    "max_model_age_seconds": 600.0,
    "max_watcher_age_seconds": 120.0,
    "max_harvest_spread": 0.08,
    "max_edge_spread": 0.12,
    "min_depth_1pct_total": 1.0,
    "shadow_disagreement_stand_down": 0.08,
    "edge_min_advantage": 0.03,
    "edge_fee_buffer": 0.005,
    "adverse_selection_buffer": 0.01,
    "max_event_notional": 25.0,
    "max_band_notional": 10.0,
    "max_daily_loss": 25.0,
}

QUOTE_COLUMNS = [
    "schema_version",
    "generated_at_utc",
    "policy_version",
    "policy_hash",
    "shadow_mode",
    "live_trade_permission",
    "quote_permission",
    "action",
    "regime",
    "side",
    "reason_code",
    "reason_detail",
    "market_id",
    "event_slug",
    "snapshot_id",
    "captured_at_utc",
    "model_version",
    "promotion_state",
    "known_edge_taxonomy",
    "known_edge_allowed",
    "known_edge_permission",
    "known_edge_reason",
    "known_edge_record_key",
    "range_label",
    "bin_kind",
    "bin_value",
    "bin_value_hi",
    "clob_token_id",
    "condition_id",
    "fair_probability",
    "market_mid",
    "market_yes",
    "uncertainty",
    "edge",
    "bid_price",
    "bid_size",
    "ask_price",
    "ask_size",
    "inventory_notional",
    "event_notional",
    "band_notional",
    "event_risk_remaining",
    "book_spread",
    "book_depth_1pct_total",
    "book_imbalance_1pct",
    "book_age_seconds",
    "model_age_seconds",
    "watcher_age_seconds",
    "source_fresh",
    "source_freshness_state",
    "heartbeat_ok",
    "latency_budget_status",
    "expected_reward_score",
    "expected_rebate_value",
    "adverse_selection_buffer",
    "final_size_limiter",
]


def maybe_float(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def first_present(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def clamp_probability(value):
    number = maybe_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_now(value=None):
    parsed = parse_time(value)
    return parsed or datetime.now(timezone.utc)


def bool_value(value, default=False):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ok", "pass"}


def policy_hash(config):
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def age_seconds(timestamp, now):
    parsed = parse_time(timestamp)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def promotion_state_from_action(action, verdict=None):
    action = str(action or "").upper()
    verdict = str(verdict or "").upper()
    if action == "PROMOTE_CANDIDATE" or verdict == "PASS":
        return "PASS"
    if action == "BLOCK_CANDIDATE" or verdict == "BLOCK":
        return "BLOCK"
    if action == "KEEP_SHADOW" or verdict == "SHADOW":
        return "SHADOW"
    return "BLOCK"


def normalize_token(value):
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip().lower()


def load_known_edge_map(path=DEFAULT_KNOWN_EDGE_MAP):
    path = Path(path) if path else None
    if path is None:
        return [], {"path": None, "exists": False, "record_count": 0}
    if not path.exists():
        return [], {"path": str(path), "exists": False, "record_count": 0}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    records = payload.get("records") or []
    return records, {
        "path": str(path),
        "exists": True,
        "schema_version": payload.get("schema_version"),
        "record_count": len(records),
        "summary": payload.get("summary") or {},
    }


def known_edge_record_key(record):
    fields = [
        "market_id",
        "cutoff",
        "hour_utc",
        "band_distance_bucket",
        "band_type",
        "casebook_taxonomy",
        "regime",
        "source_fresh",
        "source_freshness_state",
        "book_imbalance_bucket",
    ]
    return "|".join(normalize_token(record.get(field)) or "*" for field in fields)


def _wildcard(value):
    return normalize_token(value) in {"", "*", "any", "all"}


def _row_hour_utc(row):
    value = first_present(row, "hour_utc", "utc_hour")
    if value not in (None, ""):
        return normalize_token(value)
    parsed = parse_time(first_present(row, "captured_at_utc", "generated_at_utc"))
    if parsed is None:
        return ""
    return str(parsed.hour)


def _row_cutoff(row):
    return normalize_token(first_present(row, "cutoff", "cutoff_hour", "effective_cutoff_hour"))


def _row_source_fresh(row):
    if "source_fresh" not in row:
        return ""
    return "true" if bool_value(row.get("source_fresh"), False) else "false"


def _row_source_freshness_state(row):
    value = first_present(row, "source_freshness_state", "known_edge_source_freshness_state")
    if value not in (None, ""):
        return normalize_token(value)
    source_fresh = _row_source_fresh(row)
    if source_fresh == "true":
        return "all_fresh"
    if source_fresh == "false":
        return "stale_or_failed"
    return ""


def known_edge_row_dimensions(row):
    return {
        "market_id": normalize_token(row.get("market_id")),
        "cutoff": _row_cutoff(row),
        "hour_utc": _row_hour_utc(row),
        "band_distance_bucket": normalize_token(row.get("band_distance_bucket")),
        "band_type": normalize_token(first_present(row, "band_type", "bin_kind", "bin_type")),
        "casebook_taxonomy": normalize_token(first_present(row, "casebook_taxonomy", "known_edge_taxonomy")),
        "regime": normalize_token(row.get("regime")),
        "source_fresh": _row_source_fresh(row),
        "source_freshness_state": _row_source_freshness_state(row),
        "book_imbalance_bucket": normalize_token(row.get("book_imbalance_bucket")),
    }


def _record_matches_dimensions(record, dimensions):
    market_id = normalize_token(record.get("market_id"))
    if market_id not in {"*", dimensions.get("market_id")}:
        return False
    for field in (
        "hour_utc",
        "band_distance_bucket",
        "band_type",
        "casebook_taxonomy",
        "regime",
        "source_fresh",
        "source_freshness_state",
        "book_imbalance_bucket",
    ):
        record_value = record.get(field)
        if _wildcard(record_value):
            continue
        row_value = dimensions.get(field)
        if not row_value or normalize_token(record_value) != row_value:
            return False
    cutoff = normalize_token(record.get("cutoff"))
    if cutoff and cutoff not in {"*", "paper_slice"}:
        row_cutoff = dimensions.get("cutoff")
        if not row_cutoff or cutoff != row_cutoff:
            return False
    return True


def _record_specificity(record):
    fields = [
        "market_id",
        "cutoff",
        "hour_utc",
        "band_distance_bucket",
        "band_type",
        "casebook_taxonomy",
        "regime",
        "source_fresh",
        "source_freshness_state",
        "book_imbalance_bucket",
    ]
    score = 0
    for field in fields:
        value = normalize_token(record.get(field))
        if value and value not in {"*", "paper_slice"}:
            score += 1
    return score


def _permission_rank(record):
    ranks = {
        "no_quote": 0,
        "harvest_only": 1,
        "edge_research": 2,
        "edge_allowed": 3,
    }
    return ranks.get(normalize_token(record.get("permission")), 0)


def resolve_known_edge_record(row, records):
    dimensions = known_edge_row_dimensions(row)
    matches = [
        record for record in records
        if _record_matches_dimensions(record, dimensions)
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda record: (-_record_specificity(record), _permission_rank(record)))[0]


def apply_known_edge_permission(row, record=None, map_loaded=False):
    out = dict(row)
    if record is None:
        if map_loaded:
            out.update({
                "known_edge_allowed": False,
                "known_edge_permission": "no_quote",
                "known_edge_reason": "missing_known_edge_record",
                "known_edge_record_key": "",
            })
        else:
            out.update({
                "known_edge_allowed": False,
                "known_edge_permission": "harvest_only",
                "known_edge_reason": "known_edge_map_missing",
                "known_edge_record_key": "",
            })
        return out
    permission = normalize_token(record.get("permission")) or "no_quote"
    taxonomy = record.get("casebook_taxonomy")
    out.update({
        "known_edge_allowed": permission == "edge_allowed",
        "known_edge_permission": permission,
        "known_edge_reason": record.get("reason") or "",
        "known_edge_record_key": known_edge_record_key(record),
    })
    if not _wildcard(taxonomy):
        out["known_edge_taxonomy"] = taxonomy
    return out


def known_edge_allowed_from_row(row):
    permission = normalize_token(row.get("known_edge_permission"))
    if permission:
        return permission == "edge_allowed"
    return bool_value(row.get("known_edge_allowed"), False)


def load_promotion_states(path=DEFAULT_PROMOTION_REFRESH):
    path = Path(path)
    if not path.exists():
        return {}, {"path": str(path), "exists": False}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    states = {}
    for row in ((payload.get("decisions") or {}).get("markets") or []):
        market_id = row.get("market_id")
        if not market_id:
            continue
        states[market_id] = {
            "promotion_state": promotion_state_from_action(row.get("action"), row.get("verdict")),
            "action": row.get("action"),
            "verdict": row.get("verdict"),
            "reason": row.get("reason"),
        }
    micro_gate = (((payload.get("candidate") or {}).get("microstructure") or {}).get("gate") or {})
    return states, {
        "path": str(path),
        "exists": True,
        "market_count": len(states),
        "microstructure_gate": micro_gate,
    }


def load_observation_status(path=DEFAULT_OBSERVATION_STATUS, now=None, config=None):
    config = {**DEFAULT_POLICY_CONFIG, **(config or {})}
    now = utc_now(now)
    path = Path(path)
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "fresh": False,
            "heartbeat_ok": False,
            "watcher_age_seconds": None,
            "reason": "missing observation watcher status",
        }
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    watcher_age = age_seconds(payload.get("last_heartbeat"), now)
    consecutive_errors = int(payload.get("consecutive_errors") or 0)
    fresh = (
        watcher_age is not None
        and watcher_age <= float(config["max_watcher_age_seconds"])
        and consecutive_errors == 0
    )
    return {
        "path": str(path),
        "exists": True,
        "fresh": fresh,
        "heartbeat_ok": fresh,
        "watcher_age_seconds": watcher_age,
        "last_heartbeat": payload.get("last_heartbeat"),
        "consecutive_errors": consecutive_errors,
        "reason": "fresh" if fresh else "stale or erroring observation watcher",
    }


def _midpoint(row):
    for key in ("market_mid", "clob_midpoint"):
        value = clamp_probability(row.get(key))
        if value is not None:
            return value
    bid = clamp_probability(first_present(row, "clob_best_bid", "best_bid"))
    ask = clamp_probability(first_present(row, "clob_best_ask", "best_ask"))
    if bid is not None and ask is not None and ask >= bid:
        return (bid + ask) / 2.0
    return clamp_probability(row.get("market_yes"))


def _book_spread(row):
    spread = maybe_float(first_present(row, "book_spread", "clob_spread"))
    if spread is not None:
        return max(0.0, spread)
    bid = clamp_probability(first_present(row, "clob_best_bid", "best_bid"))
    ask = clamp_probability(first_present(row, "clob_best_ask", "best_ask"))
    if bid is not None and ask is not None and ask >= bid:
        return ask - bid
    return None


def _book_age(row, now):
    for key in ("book_age_seconds", "clob_book_age_seconds"):
        value = maybe_float(row.get(key))
        if value is not None:
            return max(0.0, value)
    return age_seconds(row.get("clob_book_captured_at_utc"), now)


def _risk_limited_size(row, config, price):
    desired = float(config["quote_size"])
    price = max(float(config["min_price"]), min(float(config["max_price"]), float(price or 0.0)))
    current_event = maybe_float(row.get("event_notional")) or 0.0
    current_band = maybe_float(row.get("band_notional")) or 0.0
    daily_loss = maybe_float(row.get("daily_loss")) or 0.0
    event_remaining = max(0.0, float(config["max_event_notional"]) - current_event)
    band_remaining = max(0.0, float(config["max_band_notional"]) - current_band)
    loss_remaining = max(0.0, float(config["max_daily_loss"]) + daily_loss)
    candidates = [
        ("configured_size", desired),
        ("event_notional_cap", event_remaining / price),
        ("band_notional_cap", band_remaining / price),
        ("daily_loss_cap", loss_remaining / price),
    ]
    limiter, size = min(candidates, key=lambda item: item[1])
    return max(0.0, size), limiter, event_remaining


def _base_output(row, config, now, reason_code, reason_detail):
    fair = clamp_probability(first_present(row, "fair_probability", "model_probability", "candidate_p"))
    mid = _midpoint(row)
    edge = fair - mid if fair is not None and mid is not None else None
    uncertainty = maybe_float(row.get("uncertainty"))
    if uncertainty is None and fair is not None:
        uncertainty = math.sqrt(max(0.0, fair * (1.0 - fair)))
    book_age = _book_age(row, now)
    model_age = maybe_float(row.get("model_age_seconds"))
    if model_age is None:
        model_age = age_seconds(row.get("captured_at_utc"), now)
    watcher_age = maybe_float(row.get("watcher_age_seconds"))
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "policy_version": config.get("policy_version", POLICY_VERSION),
        "policy_hash": policy_hash(config),
        "shadow_mode": True,
        "live_trade_permission": False,
        "quote_permission": False,
        "action": "NO_QUOTE",
        "regime": "none",
        "side": "-",
        "reason_code": reason_code,
        "reason_detail": reason_detail,
        "market_id": row.get("market_id") or "",
        "event_slug": row.get("event_slug") or "",
        "snapshot_id": row.get("snapshot_id") or "",
        "captured_at_utc": row.get("captured_at_utc") or "",
        "model_version": row.get("model_version") or "",
        "promotion_state": row.get("promotion_state") or "BLOCK",
        "known_edge_taxonomy": row.get("known_edge_taxonomy") or row.get("casebook_taxonomy") or "",
        "known_edge_allowed": known_edge_allowed_from_row(row),
        "known_edge_permission": row.get("known_edge_permission") or "",
        "known_edge_reason": row.get("known_edge_reason") or "",
        "known_edge_record_key": row.get("known_edge_record_key") or "",
        "range_label": row.get("range_label") or "",
        "bin_kind": row.get("bin_kind") or row.get("bin_type") or "",
        "bin_value": row.get("bin_value") or row.get("bin_value_c") or "",
        "bin_value_hi": row.get("bin_value_hi") or "",
        "clob_token_id": row.get("clob_token_id") or row.get("clob_yes_token_id") or "",
        "condition_id": row.get("condition_id") or "",
        "fair_probability": fair,
        "market_mid": mid,
        "market_yes": clamp_probability(row.get("market_yes")),
        "uncertainty": uncertainty,
        "edge": edge,
        "bid_price": None,
        "bid_size": 0.0,
        "ask_price": None,
        "ask_size": 0.0,
        "inventory_notional": maybe_float(row.get("inventory_notional")) or 0.0,
        "event_notional": maybe_float(row.get("event_notional")) or 0.0,
        "band_notional": maybe_float(row.get("band_notional")) or 0.0,
        "event_risk_remaining": max(0.0, float(config["max_event_notional"]) - (maybe_float(row.get("event_notional")) or 0.0)),
        "book_spread": _book_spread(row),
        "book_depth_1pct_total": maybe_float(first_present(row, "book_depth_1pct_total", "clob_depth_1pct_total")),
        "book_imbalance_1pct": maybe_float(first_present(row, "book_imbalance_1pct", "clob_imbalance_1pct")),
        "book_age_seconds": book_age,
        "model_age_seconds": model_age,
        "watcher_age_seconds": watcher_age,
        "source_fresh": bool_value(row.get("source_fresh"), False),
        "source_freshness_state": row.get("source_freshness_state") or "",
        "heartbeat_ok": bool_value(row.get("heartbeat_ok"), False),
        "latency_budget_status": "blocked",
        "expected_reward_score": 0.0,
        "expected_rebate_value": 0.0,
        "adverse_selection_buffer": float(config["adverse_selection_buffer"]),
        "final_size_limiter": "-",
    }


def _no_quote(row, config, now, reason_code, reason_detail):
    return _base_output(row, config, now, reason_code, reason_detail)


def _quote(row, config, now, regime, side, reason_code, bid_price=None, ask_price=None):
    output = _base_output(row, config, now, reason_code, "quote permitted by shadow policy")
    price_for_size = bid_price if bid_price is not None else ask_price
    size, limiter, event_remaining = _risk_limited_size(row, config, price_for_size)
    if size <= 0:
        return _no_quote(row, config, now, "NO_QUOTE_RISK_CAP", f"{limiter} leaves no quote size")
    output.update({
        "quote_permission": True,
        "action": "QUOTE",
        "regime": regime,
        "side": side,
        "bid_price": bid_price,
        "bid_size": size if bid_price is not None else 0.0,
        "ask_price": ask_price,
        "ask_size": size if ask_price is not None else 0.0,
        "event_risk_remaining": event_remaining,
        "latency_budget_status": "ok",
        "expected_reward_score": min(1.0, max(0.0, (output.get("book_depth_1pct_total") or 0.0) / 1000.0)),
        "final_size_limiter": limiter,
    })
    return output


def decide_quote(row, config=None, now=None):
    """Pure policy function: one input band -> one quote/no-quote intent."""
    config = {**DEFAULT_POLICY_CONFIG, **(config or {})}
    now = utc_now(now)
    promotion_state = str(row.get("promotion_state") or "BLOCK").upper()
    known_edge_permission = normalize_token(row.get("known_edge_permission"))
    if known_edge_permission == "no_quote":
        return _no_quote(
            row,
            config,
            now,
            "NO_QUOTE_KNOWN_EDGE_PERMISSION",
            row.get("known_edge_reason") or "known-edge map permission is no_quote",
        )
    if promotion_state == "BLOCK":
        return _no_quote(row, config, now, "NO_QUOTE_BLOCKED_PROMOTION", "promotion state is BLOCK")
    if not bool_value(row.get("heartbeat_ok"), False):
        return _no_quote(row, config, now, "NO_QUOTE_STALE_WATCHER", "observation watcher heartbeat is stale")
    if not bool_value(row.get("source_fresh"), False):
        return _no_quote(row, config, now, "NO_QUOTE_SOURCE_STALE", "source freshness gate is false")
    if bool_value(row.get("near_decisive_window"), False):
        return _no_quote(row, config, now, "NO_QUOTE_NEAR_DECISIVE_WINDOW", "decisive observation window")
    if str(row.get("market_status") or "active").lower() not in {"active", "open", ""}:
        return _no_quote(row, config, now, "NO_QUOTE_MARKET_INACTIVE", "market is not active")

    fair = clamp_probability(first_present(row, "fair_probability", "model_probability", "candidate_p"))
    mid = _midpoint(row)
    spread = _book_spread(row)
    book_age = _book_age(row, now)
    model_age = maybe_float(row.get("model_age_seconds"))
    if model_age is None:
        model_age = age_seconds(row.get("captured_at_utc"), now)
    watcher_age = maybe_float(row.get("watcher_age_seconds"))
    depth = maybe_float(first_present(row, "book_depth_1pct_total", "clob_depth_1pct_total")) or 0.0
    if fair is None:
        return _no_quote(row, config, now, "NO_QUOTE_MISSING_FAIR", "missing fair probability")
    if mid is None:
        return _no_quote(row, config, now, "NO_QUOTE_MISSING_BOOK", "missing book midpoint")
    if spread is None:
        return _no_quote(row, config, now, "NO_QUOTE_MISSING_BOOK", "missing book spread")
    if book_age is None or book_age > float(config["max_book_age_seconds"]):
        return _no_quote(row, config, now, "NO_QUOTE_STALE_BOOK", "book age exceeds latency budget")
    if model_age is None or model_age > float(config["max_model_age_seconds"]):
        return _no_quote(row, config, now, "NO_QUOTE_STALE_MODEL", "model age exceeds latency budget")
    if watcher_age is None or watcher_age > float(config["max_watcher_age_seconds"]):
        return _no_quote(row, config, now, "NO_QUOTE_STALE_WATCHER", "watcher age exceeds latency budget")
    if depth < float(config["min_depth_1pct_total"]):
        return _no_quote(row, config, now, "NO_QUOTE_THIN_DEPTH", "book depth below minimum")

    edge = fair - mid
    tick = float(config["tick_size"])
    min_price = float(config["min_price"])
    max_price = float(config["max_price"])
    known_edge_allowed = known_edge_allowed_from_row(row)
    edge_threshold = (
        float(config["edge_min_advantage"])
        + float(config["edge_fee_buffer"])
        + float(config["adverse_selection_buffer"])
    )

    if promotion_state == "PASS" and known_edge_allowed and abs(edge) >= edge_threshold:
        if spread > float(config["max_edge_spread"]):
            return _no_quote(row, config, now, "NO_QUOTE_WIDE_SPREAD", "spread too wide for edge mode")
        best_bid = clamp_probability(first_present(row, "clob_best_bid", "best_bid"))
        best_ask = clamp_probability(first_present(row, "clob_best_ask", "best_ask"))
        if edge > 0:
            ceiling = (best_ask - tick) if best_ask is not None else max_price
            bid_price = max(min_price, min(ceiling, fair - float(config["adverse_selection_buffer"])))
            if best_ask is not None and bid_price >= best_ask:
                return _no_quote(row, config, now, "NO_QUOTE_POST_ONLY_CROSS", "edge bid would cross ask")
            if best_bid is not None and bid_price <= best_bid:
                return _no_quote(row, config, now, "NO_QUOTE_EDGE_TOO_SMALL", "edge does not improve resting bid")
            return _quote(row, config, now, "edge", "YES_BID", "QUOTE_EDGE_MODEL", bid_price=bid_price)
        floor = (best_bid + tick) if best_bid is not None else min_price
        ask_price = min(max_price, max(floor, fair + float(config["adverse_selection_buffer"])))
        if best_bid is not None and ask_price <= best_bid:
            return _no_quote(row, config, now, "NO_QUOTE_POST_ONLY_CROSS", "edge ask would cross bid")
        if best_ask is not None and ask_price >= best_ask:
            return _no_quote(row, config, now, "NO_QUOTE_EDGE_TOO_SMALL", "edge does not improve resting ask")
        return _quote(row, config, now, "edge", "YES_ASK", "QUOTE_EDGE_MODEL", ask_price=ask_price)

    if abs(edge) >= float(config["shadow_disagreement_stand_down"]):
        return _no_quote(row, config, now, "NO_QUOTE_DISAGREEMENT_SHADOW", "model-market disagreement exceeds harvest veto")
    if spread > float(config["max_harvest_spread"]):
        return _no_quote(row, config, now, "NO_QUOTE_WIDE_SPREAD", "spread too wide for harvest mode")
    half_spread = float(config["harvest_half_spread"])
    bid_price = max(min_price, min(mid - tick, mid - half_spread))
    ask_price = min(max_price, max(mid + tick, mid + half_spread))
    if bid_price >= ask_price:
        return _no_quote(row, config, now, "NO_QUOTE_POST_ONLY_CROSS", "harvest quote would cross")
    return _quote(row, config, now, "harvest", "TWO_SIDED", "QUOTE_HARVEST_MID", bid_price=bid_price, ask_price=ask_price)


def _band_key(row):
    kind, value, value_hi = snapshot_band_key(row)
    token = row.get("clob_token_id") or row.get("clob_yes_token_id") or ""
    return (row.get("snapshot_id"), kind, value, value_hi, str(token))


def _band_key_without_token(row):
    kind, value, value_hi = snapshot_band_key(row)
    return (row.get("snapshot_id"), kind, value, value_hi)


def source_status_kind(item):
    item = item or {}
    status = normalize_token(item.get("status"))
    ok = None
    if item.get("ok") not in (None, ""):
        ok = bool_value(item.get("ok"), None)
    stale = None
    if item.get("stale") not in (None, ""):
        stale = bool_value(item.get("stale"), None)
    if ok is False or status in {"failed", "error", "missing"}:
        return "failed"
    if stale is True or status in {"stale", "stale_cache", "expired"}:
        return "stale"
    if ok is True or status in {"fresh", "ok", "available"}:
        return "fresh"
    return "unknown"


def source_list_label(sources, limit=3):
    names = sorted(str(source) for source in sources if source not in (None, ""))
    if len(names) <= limit:
        return ",".join(names)
    head = ",".join(names[:limit])
    return f"{head},+{len(names) - limit}"


def source_freshness_state_from_rows(rows):
    if not rows:
        return "missing_sources"
    by_state = {}
    for row in rows:
        source = row.get("source") or "unknown"
        state = source_status_kind(row)
        if state == "fresh":
            continue
        by_state.setdefault(state, []).append(source)
    parts = []
    for state in ("failed", "stale", "unknown"):
        if by_state.get(state):
            parts.append(f"{state}:{source_list_label(by_state[state])}")
    return ";".join(parts) if parts else "all_fresh"


def load_latest_snapshot_rows(folder):
    path = Path(folder) / "snapshots_long.csv"
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return []
    latest = max(rows, key=lambda row: parse_time(row.get("captured_at_utc")) or datetime.min.replace(tzinfo=timezone.utc))
    latest_snapshot_id = latest.get("snapshot_id")
    return [row for row in rows if row.get("snapshot_id") == latest_snapshot_id]


def load_clob_feature_index(folder):
    path = Path(folder) / "clob_features_long.csv"
    by_token = {}
    by_band = {}
    if not path.exists():
        return by_token, by_band
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            by_token[_band_key(row)] = row
            by_band[_band_key_without_token(row)] = row
    return by_token, by_band


def load_source_status_rows(folder, snapshot_id):
    path = Path(folder) / "source_status_long.csv"
    if not path.exists() or not snapshot_id:
        return []
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("snapshot_id") == snapshot_id:
                rows.append(row)
    return rows


def latest_folders_by_market(root=DEFAULT_SNAPSHOTS_ROOT, markets=None):
    root = Path(root)
    wanted = set(markets or REGISTRY.keys())
    latest = {}
    if not root.exists():
        return latest
    for child in root.iterdir():
        if not child.is_dir() or not (child / "snapshots_long.csv").exists():
            continue
        spec = spec_for_slug(child.name)
        if not spec or spec.id not in wanted:
            continue
        current = latest.get(spec.id)
        if current is None or child.stat().st_mtime > current.stat().st_mtime:
            latest[spec.id] = child
    return latest


def assemble_policy_inputs(
    promotion_states,
    observation_status,
    known_edge_records=None,
    known_edge_map_loaded=False,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    markets=None,
    now=None,
):
    now = utc_now(now)
    rows = []
    for market_id, folder in sorted(latest_folders_by_market(snapshots_root, markets=markets).items()):
        snapshot_rows = load_latest_snapshot_rows(folder)
        snapshot_id = snapshot_rows[0].get("snapshot_id") if snapshot_rows else None
        source_freshness_state = source_freshness_state_from_rows(
            load_source_status_rows(folder, snapshot_id)
        )
        clob_by_token, clob_by_band = load_clob_feature_index(folder)
        promotion = promotion_states.get(market_id, {"promotion_state": "BLOCK"})
        for snapshot_row in snapshot_rows:
            clob_row = clob_by_token.get(_band_key(snapshot_row)) or clob_by_band.get(_band_key_without_token(snapshot_row)) or {}
            merged = dict(snapshot_row)
            merged.update({key: value for key, value in clob_row.items() if value not in (None, "")})
            merged["market_id"] = market_id
            merged["promotion_state"] = promotion.get("promotion_state", "BLOCK")
            merged["fair_probability"] = merged.get("model_probability")
            merged["market_mid"] = merged.get("clob_midpoint") or merged.get("market_yes")
            merged["book_spread"] = merged.get("clob_spread") or (
                (maybe_float(merged.get("best_ask")) or 0.0) - (maybe_float(merged.get("best_bid")) or 0.0)
                if maybe_float(merged.get("best_ask")) is not None and maybe_float(merged.get("best_bid")) is not None
                else ""
            )
            merged["book_age_seconds"] = merged.get("clob_book_age_seconds")
            merged["watcher_age_seconds"] = observation_status.get("watcher_age_seconds")
            merged["heartbeat_ok"] = observation_status.get("heartbeat_ok", False)
            merged["source_fresh"] = observation_status.get("fresh", False)
            merged["source_freshness_state"] = source_freshness_state
            record = resolve_known_edge_record(merged, known_edge_records or [])
            merged = apply_known_edge_permission(
                merged,
                record=record,
                map_loaded=known_edge_map_loaded,
            )
            rows.append(merged)
    return rows


def write_quote_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUOTE_COLUMNS, extrasaction="ignore", restval="")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return str(path)


def run_policy_snapshot(
    promotion_refresh=DEFAULT_PROMOTION_REFRESH,
    known_edge_map=DEFAULT_KNOWN_EDGE_MAP,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    observation_status_path=DEFAULT_OBSERVATION_STATUS,
    out=DEFAULT_OUT,
    json_out=DEFAULT_JSON_OUT,
    markets=None,
    config=None,
    now=None,
):
    config = {**DEFAULT_POLICY_CONFIG, **(config or {})}
    now = utc_now(now)
    promotion_states, promotion_diag = load_promotion_states(promotion_refresh)
    known_edge_records, known_edge_diag = load_known_edge_map(known_edge_map)
    observation = load_observation_status(observation_status_path, now=now, config=config)
    inputs = assemble_policy_inputs(
        promotion_states,
        observation,
        known_edge_records=known_edge_records,
        known_edge_map_loaded=known_edge_diag.get("exists", False),
        snapshots_root=snapshots_root,
        markets=markets,
        now=now,
    )
    quote_rows = [decide_quote(row, config=config, now=now) for row in inputs]
    csv_path = write_quote_csv(out, quote_rows)
    reason_counts = Counter(row.get("reason_code") for row in quote_rows)
    regime_counts = Counter(row.get("regime") for row in quote_rows)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "policy_version": config.get("policy_version", POLICY_VERSION),
        "policy_hash": policy_hash(config),
        "shadow_mode": True,
        "promotion": promotion_diag,
        "known_edge_map": known_edge_diag,
        "observation_status": observation,
        "snapshots_root": str(snapshots_root),
        "csv_out": csv_path,
        "row_count": len(quote_rows),
        "quote_permission_rows": sum(1 for row in quote_rows if row.get("quote_permission")),
        "live_trade_permission_rows": sum(1 for row in quote_rows if row.get("live_trade_permission")),
        "reason_counts": dict(sorted(reason_counts.items())),
        "regime_counts": dict(sorted(regime_counts.items())),
        "rows": quote_rows,
    }
    json_out = Path(json_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    payload["json_out"] = str(json_out)
    return payload


def parse_config_overrides(items):
    config = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --config override {item!r}; expected key=value")
        key, value = item.split("=", 1)
        if key not in DEFAULT_POLICY_CONFIG:
            raise SystemExit(f"Unknown policy config key {key!r}")
        default = DEFAULT_POLICY_CONFIG[key]
        if isinstance(default, bool):
            config[key] = bool_value(value)
        elif isinstance(default, (int, float)):
            config[key] = float(value)
        else:
            config[key] = value
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description="Write keyless shadow market-making quote intents.")
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--known-edge-map", default=str(DEFAULT_KNOWN_EDGE_MAP))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--observation-status", default=str(DEFAULT_OBSERVATION_STATUS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--markets", default="all", help="'all' or comma-separated market ids.")
    parser.add_argument("--now", default=None, help="Override policy timestamp for replay/testing.")
    parser.add_argument("--config", action="append", default=[], help="Policy config override, key=value.")
    args = parser.parse_args(argv)

    markets = None
    if args.markets != "all":
        markets = [item.strip() for item in args.markets.split(",") if item.strip()]
    payload = run_policy_snapshot(
        promotion_refresh=args.promotion_refresh,
        known_edge_map=args.known_edge_map,
        snapshots_root=args.snapshots_root,
        observation_status_path=args.observation_status,
        out=args.out,
        json_out=args.json_out,
        markets=markets,
        config=parse_config_overrides(args.config),
        now=args.now,
    )
    print(
        "MM policy shadow: "
        f"{payload['quote_permission_rows']} quote rows, "
        f"{payload['row_count'] - payload['quote_permission_rows']} no-quote rows -> "
        f"{payload['csv_out']}"
    )
    return payload


if __name__ == "__main__":
    main()
