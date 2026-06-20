"""Settlement-normalized live high helpers for bot and observation reports."""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timezone

from weather.market.market_microstructure_features import snapshot_band_key
from weather.units import round_half_up, to_float


RAW_LIVE_HIGH_KEYS = (
    ("wu_current_max_since_7am", "wu_current", "wu_current_time"),
    ("wu_current_temp", "wu_current", "wu_current_time"),
    ("metar_temp", "metar", "metar_report_time"),
    ("eccc_swob_max", "eccc_swob", "eccc_swob_latest_time"),
    ("eccc_swob_latest_temp", "eccc_swob", "eccc_swob_latest_time"),
)

SETTLEMENT_HIGH_KEYS = (
    ("wu_history_high", "wu_history", "wu_history_latest_time"),
    *RAW_LIVE_HIGH_KEYS,
)

REVISION_KEYS = {"wu_history_high", "wu_current_max_since_7am", "eccc_swob_max"}
CURRENT_MAX_RESET_HOUR = 7
CURRENT_MAX_GAP_THRESHOLD = 10.0

NORMALIZED_HIGH_FIELDS = (
    "raw_current_high",
    "raw_current_high_bucket",
    "settlement_current_high",
    "high_source",
    "high_source_key",
    "revision_state",
    "settlement_bin_key",
    "raw_current_high_bin_key",
    "probability_on_raw_current_high",
    "probability_on_settlement_current_high",
    "current_max_state",
    "current_max_disposition",
    "current_max_gap_to_wu_history",
    "current_max_gap_to_current_temp",
    "current_high_trusted",
    "current_high_guard_reason",
)


def _finite(value):
    number = to_float(value)
    if number is None or not math.isfinite(number):
        return None
    return number


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
    return parsed


def _capture_hour(current_observation):
    return (
        _parse_time(current_observation.get("captured_at_local"))
        or _parse_time(current_observation.get("captured_at_utc"))
    )


def _current_max_guard(values, current_observation, reset_hour=CURRENT_MAX_RESET_HOUR):
    values = values or {}
    current_max = _finite(values.get("wu_current_max_since_7am"))
    history_high = _finite(values.get("wu_history_high"))
    current_temp = _finite(values.get("wu_current_temp"))
    captured = _capture_hour(current_observation or {})
    cutoff_hour = captured.hour if captured else None
    pre_reset = cutoff_hour is not None and cutoff_hour < int(reset_hour)
    gap_to_history = None if current_max is None or history_high is None else current_max - history_high
    gap_to_current = None if current_max is None or current_temp is None else current_max - current_temp

    if current_max is None:
        state = "missing_current_max"
        disposition = "missing"
        reason = "missing_current_max"
    elif pre_reset and (history_high is None or current_max > history_high):
        state = "pre_reset_current_max_null"
        disposition = "null_before_reset"
        reason = "pre_reset_current_max_not_validated_by_wu_history"
    elif history_high is None:
        state = "missing_wu_history_high"
        disposition = "support_only"
        reason = "missing_wu_history_validation"
    elif gap_to_history is not None and gap_to_history >= CURRENT_MAX_GAP_THRESHOLD:
        state = "early_current_max_history_gap" if cutoff_hour is not None and cutoff_hour <= 12 else "current_max_history_gap"
        disposition = "support_only"
        reason = "current_max_above_wu_history"
    elif gap_to_history is not None and gap_to_history > 0:
        state = "current_max_above_history_minor_gap"
        disposition = "support_only"
        reason = "current_max_above_wu_history"
    else:
        state = "wu_history_validated_current_max"
        disposition = "validated"
        reason = "validated_by_wu_history"

    return {
        "current_max_state": state,
        "current_max_disposition": disposition,
        "current_max_gap_to_wu_history": gap_to_history,
        "current_max_gap_to_current_temp": gap_to_current,
        "current_max_reset_hour": int(reset_hour),
        "current_high_trusted": disposition in {"missing", "validated"},
        "current_high_guard_reason": reason,
    }


def _source_rows(values, keys, current_max_guard=None):
    rows = []
    values = values or {}
    for key, source, time_key in keys:
        raw = _finite(values.get(key))
        if raw is None:
            continue
        row = {
            "key": key,
            "source": source,
            "raw_value": raw,
            "settlement_value": round_half_up(raw),
            "observed_at": values.get(time_key),
            "feature_disposition": "validated",
        }
        if key == "wu_current_max_since_7am":
            row.update(current_max_guard or {})
            row["feature_disposition"] = row.get("current_max_disposition") or "support_only"
        rows.append(row)
    return rows


def _max_row(rows, value_key):
    candidates = [row for row in rows if row.get(value_key) is not None]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (float(row[value_key]), row.get("key") or ""))


def _trusted_rows(rows):
    return [
        row for row in rows or []
        if row.get("key") != "wu_current_max_since_7am" or row.get("feature_disposition") == "validated"
    ]


def _same_target(previous_ledger, current_observation):
    previous_ledger = previous_ledger or {}
    current_observation = current_observation or {}
    for key in ("target_date", "event_slug"):
        previous = previous_ledger.get(key)
        current = current_observation.get(key)
        if previous and current and previous != current:
            return False
    return True


def _revision_events(previous_observation, current_observation):
    previous_values = (previous_observation or {}).get("values") or {}
    current_values = (current_observation or {}).get("values") or {}
    events = []
    for key in sorted(REVISION_KEYS):
        previous = _finite(previous_values.get(key))
        current = _finite(current_values.get(key))
        if previous is None or current is None or current >= previous:
            continue
        events.append({
            "event": "source_high_decreased",
            "key": key,
            "source": "wu_current" if key.startswith("wu_current") else key.rsplit("_", 1)[0],
            "previous_raw_value": previous,
            "current_raw_value": current,
            "previous_settlement_value": round_half_up(previous),
            "current_settlement_value": round_half_up(current),
        })
    return events


def update_monotonic_high_ledger(previous_ledger=None, previous_observation=None, current_observation=None):
    current_observation = current_observation or {}
    values = current_observation.get("values") or {}
    current_max_guard = _current_max_guard(values, current_observation)
    raw_rows = _source_rows(values, RAW_LIVE_HIGH_KEYS, current_max_guard=current_max_guard)
    settlement_rows = _source_rows(values, SETTLEMENT_HIGH_KEYS, current_max_guard=current_max_guard)
    trusted_raw_rows = _trusted_rows(raw_rows)
    trusted_settlement_rows = _trusted_rows(settlement_rows)
    raw_row = _max_row(trusted_raw_rows, "raw_value")
    settlement_row = _max_row(trusted_settlement_rows, "settlement_value")
    previous_ledger = deepcopy(previous_ledger or {})
    if not _same_target(previous_ledger, current_observation):
        previous_ledger = {}
    previous_settlement = _finite(previous_ledger.get("settlement_current_high"))
    previous_raw = _finite(previous_ledger.get("monotonic_raw_high") or previous_ledger.get("raw_current_high"))

    raw_current_high = raw_row.get("raw_value") if raw_row else None
    raw_current_high_bucket = round_half_up(raw_current_high)
    settlement_current_high = settlement_row.get("settlement_value") if settlement_row else None
    high_source = settlement_row.get("source") if settlement_row else None
    high_source_key = settlement_row.get("key") if settlement_row else None
    high_observed_at = settlement_row.get("observed_at") if settlement_row else None

    if previous_settlement is not None and (
        settlement_current_high is None or previous_settlement > settlement_current_high
    ):
        settlement_current_high = previous_settlement
        high_source = previous_ledger.get("high_source")
        high_source_key = previous_ledger.get("high_source_key")
        high_observed_at = previous_ledger.get("high_observed_at")
    monotonic_raw = raw_current_high
    if previous_raw is not None and (monotonic_raw is None or previous_raw > monotonic_raw):
        monotonic_raw = previous_raw

    revision_events = _revision_events(previous_observation, current_observation)
    if revision_events:
        revision_state = "source_revision"
    elif previous_settlement is not None and settlement_current_high == previous_settlement:
        revision_state = "held_monotonic_high"
    else:
        revision_state = "current"

    bin_key = f"eq:{int(settlement_current_high)}" if settlement_current_high is not None else None
    return {
        "market_id": current_observation.get("market_id") or previous_ledger.get("market_id"),
        "event_slug": current_observation.get("event_slug") or previous_ledger.get("event_slug"),
        "target_date": current_observation.get("target_date") or previous_ledger.get("target_date"),
        "unit": current_observation.get("unit") or previous_ledger.get("unit"),
        "captured_at_utc": current_observation.get("captured_at_utc"),
        "raw_current_high": raw_current_high,
        "raw_current_high_bucket": raw_current_high_bucket,
        "monotonic_raw_high": monotonic_raw,
        "settlement_current_high": settlement_current_high,
        "high_source": high_source,
        "high_source_key": high_source_key,
        "high_observed_at": high_observed_at,
        "revision_state": revision_state,
        "revision_events": revision_events,
        **current_max_guard,
        "bin_key": bin_key,
        "settlement_bin_key": bin_key,
        "raw_sources": raw_rows,
        "settlement_sources": settlement_rows,
        "trusted_raw_sources": trusted_raw_rows,
        "trusted_settlement_sources": trusted_settlement_rows,
    }


def band_key_text(row):
    kind, value, value_hi = snapshot_band_key(row)
    if kind is None or value is None:
        return None
    if value_hi is None or value_hi == value:
        return f"{kind}:{value}"
    return f"{kind}:{value}-{value_hi}"


def band_contains_value(row, value):
    value = _finite(value)
    if value is None:
        return False
    kind, low, high = snapshot_band_key(row)
    if low is None:
        return False
    high = low if high is None else high
    if kind == "lte":
        return value <= low
    if kind == "gte":
        return value >= low
    return low <= value <= high


def probability_for_value(rows, value, probability_key="model_probability"):
    total = 0.0
    matched_key = None
    for row in rows or []:
        if not band_contains_value(row, value):
            continue
        probability = _finite(row.get(probability_key) or row.get("fair_probability") or row.get("candidate_p"))
        if probability is None:
            continue
        total += probability
        matched_key = matched_key or band_key_text(row)
    return min(1.0, max(0.0, total)), matched_key


def current_high_probability_summary(snapshot_rows, ledger):
    ledger = ledger or {}
    raw_probability, raw_key = probability_for_value(snapshot_rows, ledger.get("raw_current_high"))
    settlement_probability, settlement_key = probability_for_value(
        snapshot_rows,
        ledger.get("settlement_current_high"),
    )
    top = None
    for row in snapshot_rows or []:
        probability = _finite(row.get("model_probability") or row.get("fair_probability") or row.get("candidate_p"))
        if probability is None:
            continue
        if top is None or probability > top["probability"]:
            top = {
                "probability": probability,
                "bin_key": band_key_text(row),
                "range_label": row.get("range_label"),
            }
    return {
        "raw_current_high": ledger.get("raw_current_high"),
        "raw_current_high_bucket": ledger.get("raw_current_high_bucket"),
        "settlement_current_high": ledger.get("settlement_current_high"),
        "high_source": ledger.get("high_source"),
        "high_source_key": ledger.get("high_source_key"),
        "revision_state": ledger.get("revision_state"),
        "revision_events": ledger.get("revision_events") or [],
        "current_max_state": ledger.get("current_max_state"),
        "current_max_disposition": ledger.get("current_max_disposition"),
        "current_max_gap_to_wu_history": ledger.get("current_max_gap_to_wu_history"),
        "current_max_gap_to_current_temp": ledger.get("current_max_gap_to_current_temp"),
        "current_high_trusted": ledger.get("current_high_trusted"),
        "current_high_guard_reason": ledger.get("current_high_guard_reason"),
        "raw_current_high_bin_key": raw_key,
        "settlement_bin_key": settlement_key or ledger.get("settlement_bin_key"),
        "probability_on_raw_current_high": round(raw_probability, 6),
        "probability_on_settlement_current_high": round(settlement_probability, 6),
        "top_bin_key": (top or {}).get("bin_key"),
        "top_range_label": (top or {}).get("range_label"),
        "top_probability": round((top or {}).get("probability"), 6) if top else None,
    }


def normalized_high_for_market(observation_status, market_id):
    markets = (observation_status or {}).get("market_normalization") or {}
    if market_id in markets:
        return markets.get(market_id) or {}
    market_state = ((observation_status or {}).get("markets") or {}).get(market_id) or {}
    return (
        market_state.get("monotonic_high_ledger")
        or ((market_state.get("last_observation") or {}).get("settlement_normalization"))
        or {}
    )


def normalized_high_fields(assessment):
    assessment = assessment or {}
    return {field: assessment.get(field) for field in NORMALIZED_HIGH_FIELDS}
