"""Evidence-lineage checks for safest-bets candidate projections."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from weather.market.taker_bot_strategy_registry import (
    DEFAULT_CONTROL_STRATEGY_ID,
    compact_float,
    selected_strategy_specs,
)
from weather.market.taker_bot_tape_io import order_key
from weather.market.taker_edge_permission import (
    market_implied_probability,
    taker_permission_record_key,
)


_NUMERIC_EVIDENCE_FIELDS = (
    ("taker_edge_permission_sample_size", "settled_sample_size"),
    ("taker_edge_permission_independent_days", "independent_target_day_count"),
    ("taker_edge_permission_market_count", "market_count"),
    ("taker_edge_permission_after_fee_skill", "after_fee_model_minus_market_skill"),
    ("taker_edge_permission_hit_rate", "historical_hit_rate"),
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _probability(value: Any) -> float | None:
    number = _number(value)
    if number is None or number < 0.0 or number > 1.0:
        return None
    return number


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _numbers_match(left: Any, right: Any, *, tolerance: float = 2e-6) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    return (
        left_number is not None
        and right_number is not None
        and math.isclose(
            left_number,
            right_number,
            rel_tol=1e-6,
            abs_tol=tolerance,
        )
    )


def _calibrated_model_probability(
    row: Mapping[str, Any],
    record: Mapping[str, Any],
) -> float | None:
    value = _probability(
        _first(
            record,
            "calibrated_model_probability",
            "calibrated_probability",
            "historical_hit_rate",
            "hit_rate",
        )
    )
    if value is not None:
        return value
    return _probability(_first(row, "fair_probability", "model_probability", "candidate_p"))


def _skill_weight(record: Mapping[str, Any]) -> float | None:
    value = _number(_first(record, "taker_skill_weight", "skill_weight"))
    if value is None:
        value = _number(
            _first(
                record,
                "after_fee_model_minus_market_skill",
                "model_minus_market_skill",
            )
        )
    if value is None:
        value = 1.0
    return max(0.0, min(1.0, value))


def expected_calibrated_fair(
    row: Mapping[str, Any],
    record: Mapping[str, Any],
) -> float | None:
    """Recompute the canonical market-shrunk fair value from current evidence."""

    calibrated_model = _calibrated_model_probability(row, record)
    weight = _skill_weight(record)
    market_probability = _probability(market_implied_probability(row))
    if calibrated_model is None or weight is None:
        return None
    if market_probability is None:
        value = calibrated_model * weight
    else:
        value = market_probability + weight * (calibrated_model - market_probability)
    return max(0.0, min(1.0, value))


def permission_binding_blocker(
    row: Mapping[str, Any],
    record: Mapping[str, Any] | None,
) -> str | None:
    if _text(row.get("taker_edge_permission_evidence_status")).lower() != "matched":
        return "permission_evidence_not_matched"
    if not isinstance(record, Mapping):
        return "permission_record_not_found"
    if _text(record.get("permission")).lower() != "edge_allowed":
        return "permission_record_not_allowed"
    persisted_key = _text(row.get("taker_edge_permission_record_key"))
    if not persisted_key or persisted_key != taker_permission_record_key(record):
        return "permission_record_key_mismatch"
    if any(
        not _numbers_match(row.get(row_field), record.get(record_field))
        for row_field, record_field in _NUMERIC_EVIDENCE_FIELDS
    ):
        return "permission_record_evidence_mismatch"
    if not _numbers_match(
        row.get("calibrated_model_probability"),
        _calibrated_model_probability(row, record),
    ) or not _numbers_match(row.get("taker_skill_weight"), _skill_weight(record)):
        return "permission_record_evidence_mismatch"
    return None


def candidate_lineage_blocker(
    row: Mapping[str, Any],
    run: Mapping[str, Any],
) -> str | None:
    """Bind a candidate to its exact run and strategy-specific policy."""

    strategy_id = _text(row.get("strategy_id"))
    if not strategy_id:
        return "candidate_strategy_missing"
    run_strategies = run.get("strategies")
    if not isinstance(run_strategies, list):
        return "candidate_strategy_not_in_run"
    matches = [
        item
        for item in run_strategies
        if isinstance(item, Mapping) and _text(item.get("strategy_id")) == strategy_id
    ]
    if len(matches) != 1:
        return "candidate_strategy_not_in_run"
    parent_strategy = dict(matches[0])
    try:
        [expected_strategy] = selected_strategy_specs(
            [strategy_id],
            base_config=dict(_mapping(run.get("config"))),
            registry={strategy_id: parent_strategy},
        )
    except (KeyError, TypeError, ValueError, SystemExit):
        return "run_strategy_config_invalid"
    if (
        _text(parent_strategy.get("policy_hash"))
        != _text(expected_strategy.get("policy_hash"))
        or _text(parent_strategy.get("strategy_config_hash"))
        != _text(expected_strategy.get("strategy_config_hash"))
    ):
        return "run_strategy_config_mismatch"

    strategy_config = _mapping(expected_strategy.get("config"))
    expected = (
        ("schema_version", run.get("schema_version"), "candidate_schema_mismatch"),
        ("run_id", run.get("run_id"), "candidate_run_id_mismatch"),
        ("experiment_id", run.get("experiment_id"), "candidate_experiment_mismatch"),
        (
            "policy_version",
            strategy_config.get("policy_version"),
            "candidate_policy_version_mismatch",
        ),
        (
            "policy_hash",
            expected_strategy.get("policy_hash"),
            "candidate_policy_hash_mismatch",
        ),
        (
            "strategy_config_hash",
            expected_strategy.get("strategy_config_hash"),
            "candidate_strategy_config_hash_mismatch",
        ),
        (
            "strategy_family",
            expected_strategy.get("strategy_family"),
            "candidate_strategy_family_mismatch",
        ),
        (
            "strategy_status",
            expected_strategy.get("status"),
            "candidate_strategy_status_mismatch",
        ),
        (
            "assignment_rule",
            expected_strategy.get("assignment_rule"),
            "candidate_assignment_rule_mismatch",
        ),
        (
            "control_strategy_id",
            expected_strategy.get("control_strategy_id"),
            "candidate_control_strategy_mismatch",
        ),
        (
            "exchange_economics_snapshot_id",
            run.get("exchange_economics_snapshot_id"),
            "candidate_exchange_snapshot_mismatch",
        ),
        (
            "exchange_economics_hash",
            run.get("exchange_economics_hash"),
            "candidate_exchange_hash_mismatch",
        ),
    )
    for field, parent_value, blocker in expected:
        if parent_value in (None, "") or _text(row.get(field)) != _text(parent_value):
            return blocker
    return None


def candidate_intent_blocker(row: Mapping[str, Any]) -> str | None:
    """Rebuild the producer's immutable order identity from persisted fields."""

    if not _text(row.get("snapshot_id")) or not _text(row.get("captured_at_utc")):
        return "candidate_intent_evidence_missing"
    if _number(row.get("fair_probability")) is None or _number(row.get("best_ask")) is None:
        return "candidate_intent_evidence_missing"
    intent_payload = {
        "experiment_id": row.get("experiment_id") or "",
        "strategy_id": row.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "run_id": row.get("run_id") or "",
        "target_date": row.get("target_date") or "",
        "market_id": row.get("market_id") or "",
        "event_slug": row.get("event_slug") or "",
        "snapshot_id": row.get("snapshot_id") or "",
        "captured_at_utc": row.get("captured_at_utc") or "",
        "clob_token_id": row.get("clob_token_id") or "",
        "model_variant_id": (
            row.get("model_variant_id")
            or row.get("variant_id")
            or "served_current"
        ),
        "range_label": row.get("range_label") or "",
        "fair_probability": compact_float(row.get("fair_probability")),
        "best_ask": compact_float(row.get("best_ask")),
    }
    expected_intent = order_key(intent_payload)
    if _text(row.get("intent_key")) != expected_intent:
        return "candidate_intent_key_mismatch"
    if _text(row.get("order_id")) != f"taker_{expected_intent}":
        return "candidate_order_id_mismatch"
    return None


__all__ = [
    "candidate_intent_blocker",
    "candidate_lineage_blocker",
    "expected_calibrated_fair",
    "permission_binding_blocker",
]
