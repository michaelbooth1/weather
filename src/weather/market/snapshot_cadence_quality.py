"""Snapshot cadence quality helpers for model and trading consumers."""

from __future__ import annotations

import math


DEFAULT_MAX_GAP_SECONDS = 15.0 * 60.0
DEFAULT_STALE_MODEL_SECONDS = 15.0 * 60.0
DEFAULT_CONFIDENCE_HAIRCUT = 0.75


def maybe_float(value, default=None):
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def maybe_int(value, default=0):
    number = maybe_float(value)
    if number is None:
        return default
    return int(number)


def bool_value(value, default=False):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ok", "pass"}


def first_present(row, *keys):
    for key in keys:
        value = (row or {}).get(key)
        if value not in (None, ""):
            return value
    return None


def clamp_probability(value):
    number = maybe_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def cadence_adjusted_probability(probability, anchor=None, multiplier=1.0):
    probability = clamp_probability(probability)
    if probability is None:
        return None
    anchor = clamp_probability(anchor)
    if anchor is None:
        anchor = 0.5
    multiplier = max(0.0, min(1.0, maybe_float(multiplier, 1.0)))
    return clamp_probability(anchor + ((probability - anchor) * multiplier))


def _normalized_state(value):
    state = str(value or "").strip().lower()
    aliases = {
        "ok": "clean",
        "pass": "clean",
        "within_cadence": "clean",
        "scheduled": "clean",
        "degraded": "gappy",
        "gap": "gappy",
        "gaps": "gappy",
        "cadence_gap": "gappy",
        "too_old": "stale",
    }
    return aliases.get(state, state)


def _seconds_from_minutes(row, *keys):
    value = first_present(row, *keys)
    if value in (None, ""):
        return None
    number = maybe_float(value)
    return None if number is None else number * 60.0


def snapshot_cadence_quality(row=None, config=None, *, now=None, cadence_proof=None):
    """Return normalized cadence quality fields for a snapshot/model row.

    Missing cadence metadata remains clean for backward compatibility. Explicit
    gap or stale metadata degrades confidence and, by default, trading
    permission.
    """

    del now  # Reserved for future wall-clock stale checks.
    row = dict(row or {})
    config = dict(config or {})
    if cadence_proof:
        row = {**cadence_proof, **row}
    enabled = bool_value(config.get("snapshot_cadence_quality_enabled"), True)
    cadence = str(first_present(row, "snapshot_cadence", "cadence") or "scheduled").strip().lower()
    threshold = maybe_float(
        config.get("max_snapshot_cadence_gap_seconds"),
        DEFAULT_MAX_GAP_SECONDS,
    )
    stale_model_seconds = maybe_float(
        config.get("snapshot_cadence_stale_model_seconds"),
        maybe_float(config.get("max_model_age_seconds"), DEFAULT_STALE_MODEL_SECONDS),
    )
    gap_count = maybe_int(first_present(
        row,
        "snapshot_cadence_gap_count",
        "cadence_gap_count",
        "gap_count",
        "gaps_over_threshold",
    ))
    max_gap_seconds = maybe_float(first_present(
        row,
        "snapshot_cadence_max_gap_seconds",
        "cadence_max_gap_seconds",
        "max_gap_seconds",
        "max_counted_gap_seconds",
    ))
    if max_gap_seconds is None:
        max_gap_seconds = _seconds_from_minutes(
            row,
            "snapshot_cadence_max_gap_minutes",
            "cadence_max_gap_minutes",
            "max_gap_minutes",
        )
    latest_age_seconds = maybe_float(first_present(
        row,
        "snapshot_cadence_last_model_age_seconds",
        "last_successful_model_row_age_seconds",
        "model_age_seconds",
    ))
    explicit_state = _normalized_state(first_present(
        row,
        "snapshot_cadence_quality_state",
        "cadence_quality_state",
    ))
    if not enabled:
        state = "disabled"
    elif explicit_state:
        state = explicit_state
    elif gap_count > 0 and max_gap_seconds is not None and max_gap_seconds > threshold:
        state = "gappy"
    elif latest_age_seconds is not None and latest_age_seconds > stale_model_seconds:
        state = "stale"
    elif cadence == "triggered":
        state = "triggered"
    else:
        state = "clean"

    degraded = state in {"gappy", "stale", "missing", "blocked"}
    permission = str(first_present(row, "snapshot_cadence_permission", "cadence_permission") or "").strip().lower()
    if not permission:
        permission = (
            str(config.get("snapshot_cadence_degraded_permission") or "deny").strip().lower()
            if degraded else
            "allow"
        )
    multiplier = maybe_float(first_present(
        row,
        "snapshot_cadence_confidence_multiplier",
        "cadence_confidence_multiplier",
    ))
    if multiplier is None:
        if degraded:
            multiplier = maybe_float(config.get("snapshot_cadence_confidence_haircut"), DEFAULT_CONFIDENCE_HAIRCUT)
        elif state == "triggered":
            multiplier = maybe_float(config.get("snapshot_cadence_triggered_confidence_multiplier"), 1.0)
        else:
            multiplier = 1.0
    multiplier = max(0.0, min(1.0, multiplier))
    size_multiplier = maybe_float(config.get("snapshot_cadence_quote_size_multiplier"), 0.5 if degraded else 1.0)
    quote_widen = maybe_float(config.get("snapshot_cadence_quote_widen_buffer"), 0.01 if degraded else 0.0)
    reason = first_present(row, "snapshot_cadence_reason", "cadence_quality_reason")
    if not reason:
        if state == "gappy":
            reason = f"snapshot cadence gap_count={gap_count} max_gap_seconds={max_gap_seconds}"
        elif state == "stale":
            reason = f"snapshot model row age {latest_age_seconds}s exceeds {stale_model_seconds}s"
        elif state == "triggered":
            reason = "snapshot came from triggered cadence"
        elif state == "disabled":
            reason = "snapshot cadence quality gate disabled"
        else:
            reason = "snapshot cadence clean"
    return {
        "snapshot_cadence": cadence,
        "snapshot_cadence_quality_state": state,
        "snapshot_cadence_gap_count": gap_count,
        "snapshot_cadence_max_gap_seconds": round(max_gap_seconds, 6) if max_gap_seconds is not None else None,
        "snapshot_cadence_last_model_age_seconds": (
            round(latest_age_seconds, 6) if latest_age_seconds is not None else None
        ),
        "snapshot_cadence_confidence_multiplier": round(multiplier, 6),
        "snapshot_cadence_permission": permission,
        "snapshot_cadence_quote_size_multiplier": round(max(0.0, min(1.0, size_multiplier)), 6),
        "snapshot_cadence_quote_widen_buffer": round(max(0.0, quote_widen), 6),
        "snapshot_cadence_reason": str(reason),
    }
