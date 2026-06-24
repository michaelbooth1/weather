"""Taker settlement calibration and per-slice edge permission helpers."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.io import read_csv_rows
from weather.market.market_registry import spec_for_id
from weather.paths import data_path
from weather.schema_registry import schema_version


TAKER_EDGE_PERMISSION_SCHEMA_VERSION = schema_version("taker_edge_permission_map")
DEFAULT_TAKER_EDGE_PERMISSION_MAP = data_path() / "backtest" / "taker_edge_permission_map.json"

PERMISSION_FIELDS = (
    "market_id",
    "hour_local",
    "hour_bucket",
    "band_distance_bucket",
    "source_freshness_state",
    "current_high_trust_state",
    "snapshot_cadence_quality_state",
    "model_variant_id",
    "side",
)


def _maybe_float(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _compact_float(value, digits=6):
    number = _maybe_float(value)
    if number is None:
        return None
    return round(number, digits)


def _clamp_probability(value):
    number = _maybe_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def _bool_value(value, default=False):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ok", "pass"}


def _normalize(value):
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    number = _maybe_float(value)
    if number is not None and number.is_integer():
        return str(int(number))
    return str(value).strip().lower()


def _wildcard(value):
    return _normalize(value) in {"", "*", "any", "all"}


def _parse_time(value):
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


def _first_present(row, *keys):
    for key in keys:
        value = (row or {}).get(key)
        if value not in (None, ""):
            return value
    return None


def _row_local_hour(row):
    hour = _maybe_float((row or {}).get("capture_hour_local"))
    if hour is not None:
        return int(hour)
    parsed = _parse_time(_first_present(row, "captured_at_utc", "generated_at_utc"))
    if parsed is None:
        return None
    try:
        return parsed.astimezone(spec_for_id((row or {}).get("market_id") or "").tz).hour
    except Exception:  # noqa: BLE001 - unknown market should fail closed, not crash.
        return parsed.hour


def hour_bucket(hour):
    if hour is None:
        return "missing"
    hour = int(hour)
    if 0 <= hour <= 8:
        return "early_00_08"
    if 9 <= hour <= 14:
        return "midday_09_14"
    if 15 <= hour <= 19:
        return "late_15_19"
    if 20 <= hour <= 23:
        return "closing_20_23"
    return "missing"


def band_distance_bucket(distance):
    value = _maybe_float(distance)
    if value is None:
        return "missing"
    if value <= 0:
        return "distance_0"
    if value <= 1:
        return "distance_1"
    if value <= 2:
        return "distance_2"
    return "distance_3_plus"


def current_high_trust_state(row):
    if "current_high_trusted" not in (row or {}) and "current_high_trust_state_present" not in (row or {}):
        return "missing_current_high"
    return "trusted_current_high" if _bool_value((row or {}).get("current_high_trusted"), True) else "untrusted_current_high"


def market_implied_probability(row):
    direct = _clamp_probability(_first_present(row, "market_implied_probability", "market_mid", "clob_midpoint", "midpoint"))
    if direct is not None:
        return direct
    bid = _clamp_probability(_first_present(row, "best_bid", "clob_best_bid", "gamma_best_bid"))
    ask = _clamp_probability(_first_present(row, "best_ask", "clob_best_ask", "gamma_best_ask"))
    if bid is not None and ask is not None and ask >= bid:
        return (bid + ask) / 2.0
    if ask is not None:
        return ask
    return _clamp_probability((row or {}).get("market_yes"))


def taker_permission_dimensions(row):
    local_hour = _row_local_hour(row)
    source_state = _normalize(_first_present(row, "source_freshness_state", "known_edge_source_freshness_state"))
    if not source_state:
        source_state = "all_fresh" if _bool_value((row or {}).get("source_fresh"), False) else "unknown"
    cadence = _normalize(_first_present(row, "snapshot_cadence_quality_state", "snapshot_cadence_permission"))
    return {
        "market_id": _normalize((row or {}).get("market_id")) or "unknown_market",
        "hour_local": str(local_hour) if local_hour is not None else "missing",
        "hour_bucket": hour_bucket(local_hour),
        "band_distance_bucket": band_distance_bucket((row or {}).get("current_high_band_distance")),
        "source_freshness_state": source_state,
        "current_high_trust_state": current_high_trust_state(row),
        "snapshot_cadence_quality_state": cadence or "clean",
        "model_variant_id": _normalize(_first_present(row, "model_variant_id", "model_version")) or "served_current",
        "side": _normalize(_first_present(row, "side", "taker_side")) or "yes_buy",
    }


def taker_permission_record_key(record):
    return "|".join(_normalize((record or {}).get(field)) or "*" for field in PERMISSION_FIELDS)


def _record_matches_probability(record, row):
    served = _clamp_probability(_first_present(row, "fair_probability", "model_probability", "candidate_p"))
    low = _maybe_float(_first_present(record, "served_probability_min", "fair_probability_min"))
    high = _maybe_float(_first_present(record, "served_probability_max", "fair_probability_max"))
    if served is None or (low is None and high is None):
        return True
    if low is not None and served < low:
        return False
    if high is not None and served > high:
        return False
    return True


def _record_matches_dimensions(record, dimensions):
    for field in PERMISSION_FIELDS:
        value = (record or {}).get(field)
        if _wildcard(value):
            continue
        row_value = dimensions.get(field)
        if not row_value or _normalize(value) != _normalize(row_value):
            return False
    return True


def _record_specificity(record):
    score = 0
    for field in PERMISSION_FIELDS:
        value = _normalize((record or {}).get(field))
        if value and value not in {"*", "any", "all"}:
            score += 1
    for field in ("served_probability_min", "served_probability_max"):
        if (record or {}).get(field) not in (None, ""):
            score += 1
    return score


def _permission_rank(record):
    ranks = {"deny": 0, "observe": 1, "edge_research": 2, "edge_allowed": 3}
    return ranks.get(_normalize((record or {}).get("permission")), 0)


def load_taker_edge_permission_map(path=DEFAULT_TAKER_EDGE_PERMISSION_MAP):
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


def resolve_taker_edge_permission_record(row, records):
    dimensions = taker_permission_dimensions(row)
    matches = [
        record
        for record in records or []
        if _record_matches_dimensions(record, dimensions)
        and _record_matches_probability(record, row)
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda record: (-_record_specificity(record), -_permission_rank(record)))[0]


def _explicit_permission_record(row):
    permission = _first_present(row, "taker_edge_permission", "edge_permission")
    if permission in (None, ""):
        return None
    return {
        "permission": permission,
        "reason": _first_present(row, "taker_edge_permission_reason", "edge_permission_reason") or "row_supplied_permission",
        "taker_skill_weight": _first_present(row, "taker_skill_weight", "skill_weight"),
        "calibrated_model_probability": _first_present(
            row,
            "calibrated_model_probability",
            "calibrated_probability",
            "historical_hit_rate",
        ),
        "historical_hit_rate": _first_present(row, "taker_edge_permission_hit_rate", "historical_hit_rate"),
        "settled_sample_size": _first_present(row, "taker_edge_permission_sample_size", "settled_sample_size"),
        "independent_target_day_count": _first_present(
            row,
            "taker_edge_permission_independent_days",
            "independent_target_day_count",
        ),
        "market_count": _first_present(row, "taker_edge_permission_market_count", "market_count"),
        "after_fee_model_minus_market_skill": _first_present(
            row,
            "taker_edge_permission_after_fee_skill",
            "after_fee_model_minus_market_skill",
        ),
        "market_benchmark_recommendation": _first_present(row, "market_benchmark_recommendation"),
        "_explicit_record": True,
    }


def _skill_weight_from_record(record, permission):
    value = _maybe_float(_first_present(record, "taker_skill_weight", "skill_weight"))
    if value is not None:
        return max(0.0, min(1.0, value))
    if permission != "edge_allowed":
        return 0.0
    skill = _maybe_float(_first_present(record, "after_fee_model_minus_market_skill", "model_minus_market_skill"))
    if skill is None:
        return 1.0
    return max(0.0, min(1.0, skill))


def _calibrated_model_probability(row, record):
    value = _clamp_probability(_first_present(
        record,
        "calibrated_model_probability",
        "calibrated_probability",
        "historical_hit_rate",
        "hit_rate",
    ))
    if value is not None:
        return value
    return _clamp_probability(_first_present(row, "fair_probability", "model_probability", "candidate_p"))


def _market_no_trade_recommendation(record, row):
    recommendation = _normalize(_first_present(record, "market_benchmark_recommendation", "market_recommendation"))
    if not recommendation:
        recommendation = _normalize(_first_present(row, "market_benchmark_recommendation", "market_recommendation"))
    if _bool_value(_first_present(record, "market_no_trade_recommended", "no_trade_recommended"), False):
        recommendation = recommendation or "no_trade"
    return recommendation


def apply_taker_edge_permission(row, *, records=None, map_loaded=False, config=None):
    """Annotate a taker candidate with calibrated fair value and permission.

    Missing evidence is intentionally fail-closed when the feature is enabled:
    skill weight becomes 0, fair value collapses to the market, and the entry
    gate can reject the row deterministically.
    """

    config = config or {}
    out = dict(row or {})
    explicit = _explicit_permission_record(out)
    record = explicit or resolve_taker_edge_permission_record(out, records or [])
    permission = _normalize((record or {}).get("permission")) or "deny"
    if permission == "edge_research":
        permission = "observe"
    evidence_status = "matched" if record else ("map_missing" if not map_loaded else "missing_cell")
    if record is None:
        record = {"permission": "deny", "reason": "missing_taker_edge_permission_cell"}
    market_probability = market_implied_probability(out)
    raw_fair = _clamp_probability(_first_present(out, "fair_probability", "model_probability", "candidate_p"))
    calibrated_model = _calibrated_model_probability(out, record)
    if calibrated_model is None:
        calibrated_model = raw_fair
    skill_weight = _skill_weight_from_record(record, permission)
    if permission != "edge_allowed":
        skill_weight = 0.0
    if market_probability is None:
        market_probability = _clamp_probability(_first_present(out, "best_ask", "clob_best_ask"))
    calibrated_fair = None
    if market_probability is not None and calibrated_model is not None:
        calibrated_fair = market_probability + skill_weight * (calibrated_model - market_probability)
    elif calibrated_model is not None:
        calibrated_fair = calibrated_model * skill_weight
    calibrated_fair = _clamp_probability(calibrated_fair)
    best_ask = _clamp_probability(_first_present(out, "best_ask", "clob_best_ask"))
    calibrated_edge = (
        calibrated_fair - best_ask
        if calibrated_fair is not None and best_ask is not None
        else None
    )
    hit_rate = _clamp_probability(_first_present(record, "historical_hit_rate", "hit_rate"))
    recommendation = _market_no_trade_recommendation(record, out)
    out.update({
        "taker_edge_permission": permission,
        "taker_edge_permission_reason": (record or {}).get("reason") or evidence_status,
        "taker_edge_permission_record_key": (
            "row_supplied_permission"
            if (record or {}).get("_explicit_record")
            else taker_permission_record_key(record)
            if record
            else ""
        ),
        "taker_edge_permission_evidence_status": evidence_status,
        "taker_edge_permission_sample_size": _compact_float(_first_present(record, "settled_sample_size", "sample_size"), 0),
        "taker_edge_permission_independent_days": _compact_float(
            _first_present(record, "independent_target_day_count", "independent_days"),
            0,
        ),
        "taker_edge_permission_market_count": _compact_float(_first_present(record, "market_count", "markets"), 0),
        "taker_edge_permission_after_fee_skill": _compact_float(
            _first_present(record, "after_fee_model_minus_market_skill", "model_minus_market_skill")
        ),
        "taker_edge_permission_hit_rate": _compact_float(hit_rate),
        "calibrated_model_probability": _compact_float(calibrated_model),
        "market_implied_probability": _compact_float(market_probability),
        "calibrated_fair_probability": _compact_float(calibrated_fair),
        "calibrated_fair": _compact_float(calibrated_fair),
        "taker_skill_weight": _compact_float(skill_weight),
        "calibrated_edge": _compact_float(calibrated_edge),
        "calibrated_expected_profit_per_share": _compact_float(calibrated_edge),
        "market_benchmark_recommendation": recommendation,
        "market_benchmark_precondition": (
            "no_trade"
            if recommendation.startswith("no_trade") or recommendation in {"deny", "block"}
            else "allow"
            if recommendation
            else ""
        ),
    })
    return out


def adverse_selection_state(row, config=None):
    config = config or {}
    state = {
        "adverse_selection_status": "clear",
        "adverse_selection_reason": "",
        "adverse_selection_edge_cap": _compact_float(config.get("adverse_selection_edge_cap")),
    }
    if not _bool_value(config.get("adverse_selection_edge_cap_enabled"), True):
        state["adverse_selection_status"] = "disabled"
        return state
    raw_edge = _maybe_float((row or {}).get("edge"))
    cap = _maybe_float(config.get("adverse_selection_edge_cap"))
    if raw_edge is None or cap is None or cap <= 0 or raw_edge <= cap:
        return state
    skill = _maybe_float((row or {}).get("taker_skill_weight")) or 0.0
    min_skill = _maybe_float(config.get("adverse_selection_cap_min_skill_weight"))
    if min_skill is None:
        min_skill = 0.5
    if skill >= min_skill and _normalize((row or {}).get("taker_edge_permission")) == "edge_allowed":
        state.update({
            "adverse_selection_status": "warn",
            "adverse_selection_reason": f"raw_edge:{_compact_float(raw_edge)} exceeds cap:{_compact_float(cap)} but skill is permissioned",
        })
        return state
    state.update({
        "adverse_selection_status": "blocked",
        "adverse_selection_reason": f"raw_edge:{_compact_float(raw_edge)} exceeds cap:{_compact_float(cap)} without proven skill",
    })
    return state


def after_cost_ev_per_share(row, config=None, *, price=None):
    config = config or {}
    fair = _clamp_probability(_first_present(row, "calibrated_fair_probability", "calibrated_fair", "fair_probability"))
    fill_price = _clamp_probability(price if price is not None else _first_present(row, "best_ask", "clob_best_ask"))
    if fair is None or fill_price is None:
        return None
    fee_rate = max(0.0, _maybe_float(config.get("taker_fee_rate")) or 0.0)
    fee_model = str(config.get("taker_fee_model") or "").strip()
    if fee_rate <= 0:
        fee_per_share = 0.0
    elif fee_model == "polymarket_symmetric_price_v1":
        fee_per_share = fee_rate * fill_price * (1.0 - fill_price)
    elif fee_model == "flat_notional_v1":
        fee_per_share = fee_rate * fill_price
    else:
        fee_per_share = 0.0
    return fair - fill_price - fee_per_share


def _cell_key(row):
    dims = taker_permission_dimensions(row)
    return tuple(dims[field] for field in PERMISSION_FIELDS)


def _one_share_market_net(row, config=None):
    outcome = _maybe_float((row or {}).get("settlement_outcome"))
    market_price = market_implied_probability(row)
    if outcome is None or market_price is None:
        return None
    return after_cost_ev_per_share(
        {**row, "calibrated_fair_probability": outcome},
        config=config,
        price=market_price,
    )


def _brier(probability, outcome):
    probability = _clamp_probability(probability)
    outcome = _maybe_float(outcome)
    if probability is None or outcome is None:
        return None
    return (probability - outcome) ** 2


def build_taker_edge_permission_map(
    rows,
    *,
    now=None,
    min_settled_orders=5,
    min_independent_days=3,
    min_after_fee_skill=0.0,
    policy_config=None,
    source_artifacts=None,
):
    now = _parse_time(now) or datetime.now(timezone.utc)
    policy_config = policy_config or {}
    buckets = defaultdict(list)
    for row in rows or []:
        if _maybe_float((row or {}).get("settlement_outcome")) is None:
            continue
        buckets[_cell_key(row)].append(dict(row))
    records = []
    for key, group in sorted(buckets.items()):
        dims = dict(zip(PERMISSION_FIELDS, key))
        model_briers = []
        market_briers = []
        after_fee_values = []
        market_values = []
        outcomes = []
        target_days = set()
        markets = set()
        for row in group:
            outcome = _maybe_float(row.get("settlement_outcome"))
            if outcome is None:
                continue
            outcomes.append(outcome)
            target_days.add(row.get("target_date") or "")
            markets.add(row.get("market_id") or "")
            raw_fair = _clamp_probability(_first_present(row, "fair_probability", "model_probability"))
            market_probability = market_implied_probability(row)
            model_brier = _brier(raw_fair, outcome)
            market_brier = _brier(market_probability, outcome)
            if model_brier is not None:
                model_briers.append(model_brier)
            if market_brier is not None:
                market_briers.append(market_brier)
            after_fee = after_cost_ev_per_share(
                {**row, "calibrated_fair_probability": outcome},
                config=policy_config,
                price=_first_present(row, "best_ask", "fill_price"),
            )
            market_net = _one_share_market_net(row, policy_config)
            if after_fee is not None:
                after_fee_values.append(after_fee)
            if market_net is not None:
                market_values.append(market_net)
        sample = len(outcomes)
        hit_rate = sum(outcomes) / sample if sample else None
        model_brier_mean = sum(model_briers) / len(model_briers) if model_briers else None
        market_brier_mean = sum(market_briers) / len(market_briers) if market_briers else None
        model_market_skill = (
            market_brier_mean - model_brier_mean
            if model_brier_mean is not None and market_brier_mean is not None
            else None
        )
        after_fee_mean = sum(after_fee_values) / len(after_fee_values) if after_fee_values else None
        market_mean = sum(market_values) / len(market_values) if market_values else None
        after_fee_skill = model_market_skill
        independent_days = len({day for day in target_days if day})
        permission = "edge_allowed" if (
            sample >= int(min_settled_orders)
            and independent_days >= int(min_independent_days)
            and (after_fee_skill is not None and after_fee_skill > float(min_after_fee_skill))
            and (after_fee_mean is None or after_fee_mean >= 0.0)
        ) else ("observe" if sample > 0 else "deny")
        weight = 0.0
        if permission == "edge_allowed" and model_market_skill is not None:
            denominator = abs(market_brier_mean or 0.0) or 1e-9
            weight = max(0.0, min(1.0, model_market_skill / denominator))
        records.append({
            **dims,
            "permission": permission,
            "reason": (
                "settlement_scored_model_beats_market"
                if permission == "edge_allowed"
                else "insufficient_settlement_scored_skill"
            ),
            "settled_sample_size": sample,
            "independent_target_day_count": independent_days,
            "market_count": len({market for market in markets if market}),
            "historical_hit_rate": _compact_float(hit_rate),
            "calibrated_model_probability": _compact_float(hit_rate),
            "taker_skill_weight": _compact_float(weight),
            "model_brier": _compact_float(model_brier_mean),
            "market_brier": _compact_float(market_brier_mean),
            "model_minus_market_brier_skill": _compact_float(model_market_skill),
            "after_fee_model_minus_market_skill": _compact_float(after_fee_skill),
            "mean_after_fee_ev_per_share": _compact_float(after_fee_mean),
            "mean_market_net_per_share": _compact_float(market_mean),
            "last_refresh_utc": now.isoformat(),
        })
    return {
        "schema_version": TAKER_EDGE_PERMISSION_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "summary": {
            "record_count": len(records),
            "edge_allowed_count": sum(1 for row in records if row.get("permission") == "edge_allowed"),
            "observe_count": sum(1 for row in records if row.get("permission") == "observe"),
            "deny_count": sum(1 for row in records if row.get("permission") == "deny"),
            "min_settled_orders": int(min_settled_orders),
            "min_independent_days": int(min_independent_days),
            "min_after_fee_skill": float(min_after_fee_skill),
        },
        "source_artifacts": source_artifacts or [],
        "records": records,
    }


def write_taker_edge_permission_map(out_json, rows=None, **kwargs):
    payload = build_taker_edge_permission_map(rows or [], **kwargs)
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    payload["output_json_path"] = str(out_json)
    return payload


def rows_from_order_tapes(paths):
    rows = []
    for path in paths or []:
        rows.extend(read_csv_rows(path, attach_diagnostics=True))
    return rows


def build_taker_edge_permission_map_from_tapes(paths, **kwargs):
    return build_taker_edge_permission_map(rows_from_order_tapes(paths), **kwargs)


__all__ = [name for name in globals() if not name.startswith("__")]
