"""Read-only, fail-closed view model for the safest paper taker bets.

The homepage must never invent a recommendation from raw model/market edges.
This adapter only projects decisions already persisted by the paper taker after
its execution and risk gates ran.  It adds a deliberately stricter display
filter and never writes to a tape, ledger, release, or market endpoint.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from weather.market.market_registry import all_specs
from weather.market.taker_edge_permission import (
    PERMISSION_FIELDS,
    resolve_taker_edge_permission_record,
    taker_permission_dimensions,
)
from weather.paths import data_path
from weather.schema_registry import schema_version
from weather.time import age_seconds, parse_datetime, utc_now

from .safe_bets_evidence import (
    candidate_intent_blocker,
    candidate_lineage_blocker,
    expected_calibrated_fair,
    permission_binding_blocker,
)


DEFAULT_RUNS_ROOT = data_path("taker_runs")
DEFAULT_PERMISSION_MAP_PATH = data_path("backtest", "taker_edge_permission_map.json")
DEFAULT_RUN_MAX_AGE_SECONDS = 5 * 60
DEFAULT_PERMISSION_MAX_AGE_SECONDS = 36 * 60 * 60
DEFAULT_MIN_CONSERVATIVE_PROBABILITY = 0.70
DEFAULT_MIN_INDEPENDENT_DAYS = 3
DEFAULT_LIMIT = 3
DEFAULT_MAX_BOOK_AGE_SECONDS = 120.0
DEFAULT_MAX_MODEL_AGE_SECONDS = 900.0
DEFAULT_MAX_FUTURE_SKEW_SECONDS = 60.0
DISPLAY_TIMEZONE = ZoneInfo("America/Toronto")

RUN_SCHEMA_VERSION = schema_version("taker_bot_run")
PERMISSION_SCHEMA_VERSION = schema_version("taker_edge_permission_map")

_TRUE_VALUES = frozenset({"1", "true", "yes", "y", "ok", "pass", "active", "open", "trading"})
_FALSE_VALUES = frozenset({"0", "false", "no", "n", "deny", "blocked", "inactive", "closed"})
_PAPER_RUN_MODES = frozenset({"paper-taker", "paper-taker-multi-arm"})
_EVENT_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
def _now_utc(now: datetime | None) -> datetime:
    value = now or utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _target_date(value: str | date | datetime | None, now: datetime) -> str:
    if value is None:
        return now.astimezone(DISPLAY_TIMEZONE).date().isoformat()
    if isinstance(value, datetime):
        localized = value
        if localized.tzinfo is None:
            localized = localized.replace(tzinfo=DISPLAY_TIMEZONE)
        return localized.astimezone(DISPLAY_TIMEZONE).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _number(value: Any) -> float | None:
    if value in (None, ""):
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


def _boolean(value: Any, default: bool | None = None) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    normalized = str(value).strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def _normalized(value: Any) -> str:
    return str(value or "").strip().lower()


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _age(now: datetime, value: Any) -> float | None:
    seconds = age_seconds(now, value)
    if seconds is None or not math.isfinite(seconds):
        return None
    if seconds < -DEFAULT_MAX_FUTURE_SKEW_SECONDS:
        return None
    return max(0.0, seconds)


def _timestamp_is_far_future(now: datetime, value: Any) -> bool:
    seconds = age_seconds(now, value)
    return (
        seconds is not None
        and math.isfinite(seconds)
        and seconds < -DEFAULT_MAX_FUTURE_SKEW_SECONDS
    )


def _effective_age(value: Any, elapsed_seconds: float | None) -> float | None:
    age_at_evaluation = _number(value)
    if age_at_evaluation is None or age_at_evaluation < 0 or elapsed_seconds is None:
        return None
    return age_at_evaluation + max(0.0, elapsed_seconds)


def _numbers_match(left: Any, right: Any, *, tolerance: float = 1e-6) -> bool:
    left_number = _number(left)
    right_number = _number(right)
    return (
        left_number is not None
        and right_number is not None
        and math.isclose(left_number, right_number, rel_tol=tolerance, abs_tol=tolerance)
    )


def _strict_age_limit(value: Any, ceiling: float) -> float:
    configured = _number(value)
    if configured is None:
        return ceiling
    return min(ceiling, max(0.0, configured))


def _market_spec(market_id: Any):
    normalized = str(market_id or "").strip()
    return next((spec for spec in all_specs() if spec.id == normalized), None)


def _normalized_unit(value: Any) -> str:
    return str(value or "").strip().upper().replace("°", "")


def _range_label_unit(value: Any) -> str | None:
    label = str(value or "").upper()
    has_celsius = "°C" in label
    has_fahrenheit = "°F" in label
    if has_celsius and has_fahrenheit:
        return "INVALID"
    if not has_celsius and not has_fahrenheit:
        return None
    return "C" if has_celsius else "F"


def _base_payload(target_date: str, now: datetime) -> dict[str, Any]:
    return {
        "status": "NO_DATA",
        "status_message": "No current paper-taker run is available yet.",
        "generated_at_utc": now.isoformat(),
        "as_of_utc": None,
        "target_date": target_date,
        "paper_only": True,
        "actionable": False,
        "warnings": [],
        "recommendations": [],
        "recommendation_count": 0,
        "candidate_count": 0,
        "eligible_before_dedupe_count": 0,
        "eligible_unique_count": 0,
        "deduplicated_count": 0,
        "shortlist_truncated_count": 0,
        "blocker_counts": {},
        "run_blockers": [],
        "fund": {},
        "provenance": {},
    }


def _result(
    target_date: str,
    now: datetime,
    status: str,
    message: str,
    *,
    run_blockers: list[str] | None = None,
    provenance: Mapping[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    payload = _base_payload(target_date, now)
    payload.update({
        "status": status,
        "status_message": message,
        "run_blockers": list(run_blockers or []),
        "blocker_counts": dict(Counter(run_blockers or [])),
        "provenance": dict(provenance or {}),
        "warnings": list(warnings or []),
    })
    return payload


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _run_provenance(
    run: Mapping[str, Any],
    permission: Mapping[str, Any],
    *,
    run_path: str | Path | None,
    permission_map_path: str | Path | None,
    now: datetime,
) -> dict[str, Any]:
    generated = run.get("generated_at_utc")
    permission_generated = permission.get("generated_at_utc")
    return {
        "run_id": run.get("run_id"),
        "run_path": str(run_path) if run_path is not None else None,
        "run_schema_version": run.get("schema_version"),
        "run_generated_at_utc": generated,
        "run_age_seconds": _age(now, generated),
        "mode": run.get("mode"),
        "experiment_id": run.get("experiment_id"),
        "policy_version": _mapping(run.get("config")).get("policy_version"),
        "exchange_economics_snapshot_id": run.get("exchange_economics_snapshot_id"),
        "exchange_economics_hash": run.get("exchange_economics_hash"),
        "permission_map_path": (
            str(permission_map_path) if permission_map_path is not None else None
        ),
        "permission_map_schema_version": permission.get("schema_version"),
        "permission_map_generated_at_utc": permission_generated,
        "permission_map_age_seconds": _age(now, permission_generated),
        "permission_map_summary": dict(_mapping(permission.get("summary"))),
        "release_id": run.get("release_id"),
        "release_manifest_sha256": run.get("release_manifest_sha256"),
        "release_pointer_sha256": run.get("release_pointer_sha256"),
        "release_sequence": run.get("release_sequence"),
        "release_identity_status": run.get("release_identity_status"),
        "release_identity_reason": run.get("release_identity_reason"),
        "base_model_release_bound": run.get("base_model_release_bound"),
        "base_model_binding_reason": run.get("base_model_binding_reason"),
        "release_kind": run.get("release_kind"),
        "release_candidate_mode": run.get("release_candidate_mode"),
        "release_production_capable": run.get("release_production_capable"),
    }


def _run_gate_blockers(
    run: Mapping[str, Any],
    permission: Mapping[str, Any],
    *,
    target_date: str,
    now: datetime,
) -> tuple[list[str], list[str]]:
    """Return (blocking, stale) run-level reasons."""

    blocked: list[str] = []
    stale: list[str] = []
    if run.get("schema_version") != RUN_SCHEMA_VERSION:
        blocked.append("unsupported_run_schema")
    if not str(run.get("run_id") or "").strip():
        blocked.append("run_id_missing")
    if not str(run.get("experiment_id") or "").strip():
        blocked.append("run_experiment_missing")
    if str(run.get("target_date") or "") != target_date:
        blocked.append("run_target_date_mismatch")
    run_mode = _normalized(run.get("mode"))
    if run_mode not in _PAPER_RUN_MODES:
        blocked.append("run_not_paper_taker")
    config = _mapping(run.get("config"))
    if not str(config.get("policy_version") or "").strip():
        blocked.append("run_policy_version_missing")
    strategies = run.get("strategies")
    strategy_ids = (
        [str(item.get("strategy_id") or "").strip() for item in strategies]
        if isinstance(strategies, list)
        and strategies
        and all(isinstance(item, Mapping) for item in strategies)
        else []
    )
    if not strategy_ids or any(not strategy_id for strategy_id in strategy_ids):
        blocked.append("run_strategies_invalid")
    elif len(set(strategy_ids)) != len(strategy_ids):
        blocked.append("run_strategy_ids_duplicate")
    elif (run_mode == "paper-taker" and len(strategy_ids) != 1) or (
        run_mode == "paper-taker-multi-arm" and len(strategy_ids) <= 1
    ):
        blocked.append("run_strategy_mode_mismatch")

    run_age = _age(now, run.get("generated_at_utc"))
    if run_age is None:
        blocked.append(
            "run_timestamp_future"
            if _timestamp_is_far_future(now, run.get("generated_at_utc"))
            else "run_timestamp_missing"
        )

    tape = _mapping(run.get("tape_integrity"))
    if _normalized(tape.get("status")) != "pass":
        blocked.append("order_tape_integrity_not_pass")
    upstream = _mapping(run.get("upstream_dependency_status"))
    if _normalized(upstream.get("status")) != "pass":
        blocked.append("upstream_dependencies_not_pass")
    exchange = _mapping(run.get("exchange_economics_gate"))
    if (
        _normalized(exchange.get("status")) != "pass"
        or _boolean(exchange.get("ok"), False) is not True
    ):
        blocked.append("exchange_economics_not_pass")
    run_exchange_id = str(run.get("exchange_economics_snapshot_id") or "").strip()
    run_exchange_hash = str(run.get("exchange_economics_hash") or "").strip()
    gate_exchange_id = str(exchange.get("snapshot_id") or "").strip()
    gate_exchange_hash = str(
        exchange.get("snapshot_hash") or exchange.get("exchange_economics_hash") or ""
    ).strip()
    if not run_exchange_id:
        blocked.append("exchange_economics_snapshot_missing")
    if not run_exchange_hash:
        blocked.append("exchange_economics_hash_missing")
    if not gate_exchange_id or gate_exchange_id != run_exchange_id:
        blocked.append("exchange_economics_gate_snapshot_mismatch")
    if not gate_exchange_hash or gate_exchange_hash != run_exchange_hash:
        blocked.append("exchange_economics_gate_hash_mismatch")

    if permission.get("schema_version") != PERMISSION_SCHEMA_VERSION:
        blocked.append("unsupported_permission_map_schema")
    permission_age = _age(now, permission.get("generated_at_utc"))
    if permission_age is None:
        blocked.append(
            "permission_map_timestamp_future"
            if _timestamp_is_far_future(now, permission.get("generated_at_utc"))
            else "permission_map_timestamp_missing"
        )
    permission_summary = _mapping(permission.get("summary"))
    permission_records = permission.get("records")
    if not isinstance(permission_records, list) or not all(
        isinstance(record, Mapping) for record in permission_records
    ):
        blocked.append("permission_map_records_invalid")
        permission_records = []
    declared_record_count = _number(permission_summary.get("record_count"))
    if (
        declared_record_count is None
        or declared_record_count <= 0
        or not declared_record_count.is_integer()
    ):
        blocked.append("permission_map_empty")
    elif int(declared_record_count) != len(permission_records):
        blocked.append("permission_map_record_count_mismatch")

    return blocked, stale


def _run_warnings(run: Mapping[str, Any]) -> list[str]:
    if (
        run.get("base_model_release_bound") is not True
        or _normalized(run.get("release_identity_status"))
        != "verified_variant_serving_bundle"
    ):
        return ["Research-unbound evidence is diagnostic paper output only."]
    return []


def _candidate_blocker(
    row: Mapping[str, Any],
    *,
    run: Mapping[str, Any],
    permission_record: Mapping[str, Any] | None,
    target_date: str,
    max_book_age_seconds: float,
    max_model_age_seconds: float,
    max_no_book_age_seconds: float,
    min_independent_days: int,
    min_conservative_probability: float,
    active_market_policy_required: bool,
    effective_book_age_seconds: float | None,
    effective_model_age_seconds: float | None,
    effective_no_book_age_seconds: float | None,
) -> str | None:
    action = _normalized(row.get("action"))
    order_status = _normalized(row.get("order_status"))
    reason_code = str(row.get("reason_code") or "").strip().upper()
    if action != "buy" or order_status != "filled" or reason_code != "BUY_EDGE":
        return f"policy:{reason_code or 'NOT_FILLED_BUY_EDGE'}"
    lineage_blocker = candidate_lineage_blocker(row, run)
    if lineage_blocker:
        return lineage_blocker
    if str(row.get("target_date") or "") != target_date:
        return "candidate_target_date_mismatch"
    spec = _market_spec(row.get("market_id"))
    if spec is None:
        return "candidate_market_unknown"
    event_slug = str(row.get("event_slug") or "").strip().lower()
    if not event_slug:
        return "candidate_event_missing"
    if not _EVENT_SLUG.fullmatch(event_slug) or not event_slug.startswith(spec.slug_prefix.lower()):
        return "candidate_event_market_mismatch"
    range_label = str(row.get("range_label") or "").strip()
    if not range_label:
        return "candidate_range_label_missing"
    persisted_unit = _normalized_unit(row.get("display_unit"))
    range_unit = _range_label_unit(range_label)
    if (
        persisted_unit
        and persisted_unit != _normalized_unit(spec.display_unit)
    ) or (range_unit and range_unit != _normalized_unit(spec.display_unit)):
        return "candidate_native_unit_mismatch"

    side = _normalized(_first(row, "side", "taker_side"))
    if side not in {"yes_buy", "no_buy"}:
        return "candidate_side_invalid"
    side_token_field = "clob_no_token_id" if side == "no_buy" else "clob_yes_token_id"
    side_token = str(row.get(side_token_field) or "").strip()
    selected_token = str(row.get("clob_token_id") or "").strip()
    if not side_token or not selected_token or selected_token != side_token:
        return "candidate_side_token_mismatch"
    intent_blocker = candidate_intent_blocker(row)
    if intent_blocker:
        return intent_blocker

    market_state = _first(row, "market_status", "active")
    if market_state in (None, ""):
        # Canonical taker rows intentionally project a bounded field set and do
        # not persist ``market_status``.  A FILLED/BUY_EDGE row still proves the
        # active-market check ran when the persisted run config requires it.
        if not active_market_policy_required:
            return "market_activity_not_proven"
    elif _boolean(market_state, False) is not True:
        return "market_inactive"
    if _normalized(row.get("source_freshness_state")) != "all_fresh":
        return "source_not_all_fresh"
    cadence_permission = _normalized(row.get("snapshot_cadence_permission"))
    cadence_quality = _normalized(row.get("snapshot_cadence_quality_state"))
    if cadence_permission != "allow" or cadence_quality not in {"clean", "triggered"}:
        return "snapshot_cadence_not_allowed"
    if _normalized(row.get("taker_edge_permission")) != "edge_allowed":
        return "edge_not_permissioned"
    permission_blocker = permission_binding_blocker(row, permission_record)
    if permission_blocker:
        return permission_blocker
    independent_days = _number(permission_record.get("independent_target_day_count"))
    if independent_days is None or independent_days < min_independent_days:
        return "insufficient_independent_days"
    sample_size = _number(permission_record.get("settled_sample_size"))
    after_fee_skill = _number(permission_record.get("after_fee_model_minus_market_skill"))
    if sample_size is None or sample_size <= 0 or after_fee_skill is None or after_fee_skill <= 0:
        return "settlement_evidence_missing"
    if _normalized(row.get("market_benchmark_precondition")) == "no_trade":
        return "market_benchmark_no_trade"
    if _normalized(row.get("adverse_selection_status")) != "clear":
        return "adverse_selection_not_clear"

    if (
        effective_book_age_seconds is None
        or effective_book_age_seconds > max_book_age_seconds
    ):
        return "book_not_fresh"
    if (
        effective_model_age_seconds is None
        or effective_model_age_seconds > max_model_age_seconds
    ):
        return "model_not_fresh"

    executable_price = _probability(
        _first(row, "executable_fill_price", "fill_price", "best_ask")
    )
    if executable_price is None or executable_price <= 0:
        return "executable_price_invalid"
    calibrated = _probability(
        _first(row, "calibrated_fair_probability", "calibrated_fair")
    )
    # Executable fill price is the only side-normalized market bound persisted
    # for every arm.  NO projections can retain the YES-side permission-map
    # implied probability, so using that field here would suppress or mis-rank
    # otherwise valid NO paper fills.
    implied = executable_price
    if calibrated is None:
        return "calibrated_probability_missing"
    expected_fair = expected_calibrated_fair(row, permission_record)
    if not _numbers_match(calibrated, expected_fair, tolerance=2e-6):
        return "calibrated_fair_probability_mismatch"
    if min(calibrated, implied) < min_conservative_probability:
        return "below_safety_probability_floor"
    after_cost_ev = _number(
        _first(row, "after_cost_ev_per_share", "entry_ev_per_share")
    )
    if after_cost_ev is None or after_cost_ev <= 0:
        return "after_cost_ev_not_positive"
    if not math.isclose(
        after_cost_ev,
        calibrated - executable_price,
        rel_tol=1e-4,
        abs_tol=2e-5,
    ) and after_cost_ev > calibrated - executable_price:
        return "after_cost_ev_inconsistent"

    fill_size = _number(row.get("fill_size"))
    fill_notional = _number(row.get("fill_notional_usdc"))
    fee = _number(row.get("fee_usdc"))
    spent = _number(row.get("total_spent_usdc"))
    if (
        fill_size is None
        or fill_size <= 0
        or fill_notional is None
        or fill_notional <= 0
        or fee is None
        or fee < 0
        or spent is None
        or spent <= 0
    ):
        return "paper_fill_invalid"
    if not math.isclose(
        fill_notional,
        fill_size * executable_price,
        rel_tol=1e-5,
        abs_tol=1e-4,
    ) or not math.isclose(
        spent,
        fill_notional + fee,
        rel_tol=1e-5,
        abs_tol=1e-4,
    ):
        return "paper_fill_arithmetic_inconsistent"
    derived_after_cost_ev = calibrated - executable_price - (fee / fill_size)
    if not math.isclose(
        after_cost_ev,
        derived_after_cost_ev,
        rel_tol=1e-4,
        abs_tol=2e-5,
    ):
        return "after_cost_ev_inconsistent"

    if side == "no_buy":
        if (
            _normalized(row.get("no_book_source")) != "no_token_book"
            or _boolean(row.get("real_no_book_depth_eligible"), False) is not True
            or _boolean(row.get("no_book_fresh"), False) is not True
            or effective_no_book_age_seconds is None
            or effective_no_book_age_seconds > max_no_book_age_seconds
        ):
            return "no_side_real_book_not_safe"
    return None


def _market_metadata(row: Mapping[str, Any]) -> tuple[str, str | None]:
    spec = _market_spec(row.get("market_id"))
    if spec is None:
        return "Unknown market", None
    return spec.city_label, spec.display_unit


def _candidate_view(
    row: Mapping[str, Any],
    *,
    effective_book_age_seconds: float,
    effective_model_age_seconds: float,
    effective_no_book_age_seconds: float | None,
) -> dict[str, Any]:
    executable_price = _probability(
        _first(row, "executable_fill_price", "fill_price", "best_ask")
    )
    calibrated = _probability(
        _first(row, "calibrated_fair_probability", "calibrated_fair")
    )
    permission_market_implied = _probability(row.get("market_implied_probability"))
    implied = executable_price
    after_cost_ev = _number(
        _first(row, "after_cost_ev_per_share", "entry_ev_per_share")
    )
    fill_size = _number(row.get("fill_size")) or 0.0
    stake = _number(_first(row, "total_spent_usdc", "fill_notional_usdc")) or 0.0
    conservative = min(calibrated, implied)
    side = _normalized(_first(row, "side", "taker_side"))
    is_no = side == "no_buy"
    market_label, display_unit = _market_metadata(row)
    event_slug = str(row.get("event_slug") or "").strip()
    return {
        "market_id": str(row.get("market_id") or "").strip(),
        "market_label": market_label,
        "display_unit": display_unit,
        "target_date": str(row.get("target_date") or ""),
        "event_slug": event_slug,
        "market_url": f"https://polymarket.com/event/{event_slug}",
        "range_label": str(row.get("range_label") or ""),
        "side": "NO" if is_no else "YES",
        "side_label": "BUY NO" if is_no else "BUY YES",
        "executable_price": executable_price,
        "market_implied_probability": implied,
        "permission_market_implied_probability": permission_market_implied,
        "calibrated_probability": calibrated,
        "conservative_probability": conservative,
        "after_cost_ev_per_share": after_cost_ev,
        "expected_return_on_cost": (after_cost_ev * fill_size / stake) if stake > 0 else None,
        "paper_stake_usdc": stake,
        "max_loss_usdc": stake,
        "profit_if_right_usdc": max(0.0, fill_size - stake),
        "expected_profit_usdc": after_cost_ev * fill_size,
        "fill_size": fill_size,
        "fee_usdc": _number(row.get("fee_usdc")) or 0.0,
        "book_age_seconds": (
            effective_no_book_age_seconds
            if is_no and effective_no_book_age_seconds is not None
            else effective_book_age_seconds
        ),
        "model_age_seconds": effective_model_age_seconds,
        "no_book_age_seconds": effective_no_book_age_seconds,
        "source_freshness_state": row.get("source_freshness_state"),
        "snapshot_cadence_quality_state": row.get("snapshot_cadence_quality_state"),
        "independent_target_days": _number(
            row.get("taker_edge_permission_independent_days")
        ),
        "independent_days": _number(row.get("taker_edge_permission_independent_days")),
        "settled_sample_size": _number(row.get("taker_edge_permission_sample_size")),
        "sample_size": _number(row.get("taker_edge_permission_sample_size")),
        "after_fee_skill": _number(row.get("taker_edge_permission_after_fee_skill")),
        "historical_hit_rate": _probability(row.get("taker_edge_permission_hit_rate")),
        "strategy_id": row.get("strategy_id"),
        "strategy_family": row.get("strategy_family"),
        "strategy_status": row.get("strategy_status"),
        "snapshot_id": row.get("snapshot_id"),
        "captured_at_utc": row.get("captured_at_utc"),
        "clob_token_id": row.get("clob_token_id"),
        "release_id": row.get("release_id"),
        "release_identity_status": row.get("release_identity_status"),
        "paper_only": True,
    }


def _candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    book_age = candidate.get("book_age_seconds")
    model_age = candidate.get("model_age_seconds")
    return (
        -float(candidate.get("conservative_probability") or 0.0),
        -float(candidate.get("after_cost_ev_per_share") or 0.0),
        -float(candidate.get("independent_target_days") or 0.0),
        -float(candidate.get("settled_sample_size") or 0.0),
        -float(candidate.get("after_fee_skill") or 0.0),
        math.inf if book_age is None else float(book_age),
        math.inf if model_age is None else float(model_age),
        str(candidate.get("market_id") or ""),
        str(candidate.get("event_slug") or ""),
        str(candidate.get("range_label") or ""),
    )


def _fund_view(run: Mapping[str, Any]) -> dict[str, Any]:
    summary = _mapping(run.get("summary"))
    pnl_summary = _mapping(_mapping(run.get("pnl")).get("summary"))
    budget = _number(summary.get("budget_usdc"))
    spent = _number(summary.get("budget_spent_usdc"))
    remaining = _number(summary.get("budget_remaining_usdc"))
    if remaining is None and budget is not None and spent is not None:
        remaining = max(0.0, budget - spent)
    return {
        "budget_usdc": budget,
        "spent_usdc": spent,
        "remaining_usdc": remaining,
        "filled_orders": _number(
            _first(pnl_summary, "filled_order_count", "cumulative_filled_orders")
        ),
        "net_pnl_usdc": _number(
            _first(pnl_summary, "net_pnl_usdc", "cumulative_net_pnl_usdc")
        ),
        "mark_to_market_pnl_usdc": _number(pnl_summary.get("mark_to_market_pnl_usdc")),
        "settled_order_count": _number(pnl_summary.get("settled_order_count")),
        "unsettled_order_count": _number(pnl_summary.get("unsettled_order_count")),
    }


def build_safe_bets_payload(
    run_payload: Mapping[str, Any],
    permission_payload: Mapping[str, Any],
    *,
    now: datetime | None = None,
    target_date: str | date | datetime | None = None,
    run_path: str | Path | None = None,
    permission_map_path: str | Path | None = None,
    run_max_age_seconds: float = DEFAULT_RUN_MAX_AGE_SECONDS,
    permission_max_age_seconds: float = DEFAULT_PERMISSION_MAX_AGE_SECONDS,
    min_conservative_probability: float = DEFAULT_MIN_CONSERVATIVE_PROBABILITY,
    min_independent_days: int = DEFAULT_MIN_INDEPENDENT_DAYS,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Build a display-only shortlist from a persisted paper-taker decision."""

    now_utc = _now_utc(now)
    target = _target_date(target_date, now_utc)
    if not isinstance(run_payload, Mapping) or not isinstance(permission_payload, Mapping):
        return _result(
            target,
            now_utc,
            "LOADING",
            "The current paper artifacts are incomplete while local data is syncing.",
            run_blockers=["artifact_payload_incomplete"],
        )

    run = run_payload
    permission = permission_payload
    provenance = _run_provenance(
        run,
        permission,
        run_path=run_path,
        permission_map_path=permission_map_path,
        now=now_utc,
    )
    warnings = _run_warnings(run)
    blocked, stale = _run_gate_blockers(
        run,
        permission,
        target_date=target,
        now=now_utc,
    )
    run_age = provenance.get("run_age_seconds")
    permission_age = provenance.get("permission_map_age_seconds")
    if run_age is not None and run_age > float(run_max_age_seconds):
        stale.append("paper_run_stale")
    if permission_age is not None and permission_age > float(permission_max_age_seconds):
        stale.append("permission_map_stale")
    if stale:
        return _result(
            target,
            now_utc,
            "STALE",
            "Paper evidence is stale, so no shortlist is shown.",
            run_blockers=stale + blocked,
            provenance=provenance,
            warnings=warnings,
        )
    if blocked:
        return _result(
            target,
            now_utc,
            "BLOCKED",
            "The latest paper run did not clear every required safety gate.",
            run_blockers=blocked,
            provenance=provenance,
            warnings=warnings,
        )

    config = _mapping(run.get("config"))
    max_book_age = _strict_age_limit(
        config.get("max_book_age_seconds"), DEFAULT_MAX_BOOK_AGE_SECONDS
    )
    max_model_age = _strict_age_limit(
        config.get("max_model_age_seconds"), DEFAULT_MAX_MODEL_AGE_SECONDS
    )
    max_no_book_age = _strict_age_limit(
        config.get("two_sided_real_no_book_max_age_seconds"),
        DEFAULT_MAX_BOOK_AGE_SECONDS,
    )
    active_market_policy_required = (
        _boolean(config.get("require_active_market"), False) is True
    )
    latest_orders = run.get("latest_orders")
    if not isinstance(latest_orders, list):
        return _result(
            target,
            now_utc,
            "LOADING",
            "The current paper run is incomplete while local data is syncing.",
            run_blockers=["latest_orders_incomplete"],
            provenance=provenance,
            warnings=warnings,
        )

    blocker_counts: Counter[str] = Counter()
    eligible: list[dict[str, Any]] = []
    permission_records = permission.get("records")
    permission_cache: dict[tuple[Any, ...], Mapping[str, Any] | None] = {}
    for raw_row in latest_orders:
        if not isinstance(raw_row, Mapping):
            blocker_counts["candidate_malformed"] += 1
            continue
        evaluated_at = raw_row.get("generated_at_utc")
        if _timestamp_is_far_future(now_utc, evaluated_at):
            blocker_counts["candidate_timestamp_future"] += 1
            continue
        elapsed_since_evaluation = _age(now_utc, evaluated_at)
        if elapsed_since_evaluation is None:
            blocker_counts["candidate_timestamp_missing"] += 1
            continue
        effective_book_age = _effective_age(
            raw_row.get("book_age_seconds"), elapsed_since_evaluation
        )
        effective_model_age = _effective_age(
            raw_row.get("model_age_seconds"), elapsed_since_evaluation
        )
        effective_no_book_age = _effective_age(
            raw_row.get("no_book_age_seconds"), elapsed_since_evaluation
        )
        permission_dimensions = taker_permission_dimensions(raw_row)
        permission_cache_key = (
            *(permission_dimensions.get(field) for field in PERMISSION_FIELDS),
            _number(_first(raw_row, "fair_probability", "model_probability", "candidate_p")),
        )
        if permission_cache_key not in permission_cache:
            permission_cache[permission_cache_key] = resolve_taker_edge_permission_record(
                raw_row,
                permission_records,
            )
        permission_record = permission_cache[permission_cache_key]
        blocker = _candidate_blocker(
            raw_row,
            run=run,
            permission_record=permission_record,
            target_date=target,
            max_book_age_seconds=max_book_age,
            max_model_age_seconds=max_model_age,
            max_no_book_age_seconds=max_no_book_age,
            min_independent_days=int(min_independent_days),
            min_conservative_probability=float(min_conservative_probability),
            active_market_policy_required=active_market_policy_required,
            effective_book_age_seconds=effective_book_age,
            effective_model_age_seconds=effective_model_age,
            effective_no_book_age_seconds=effective_no_book_age,
        )
        if blocker:
            blocker_counts[blocker] += 1
            continue
        eligible.append(
            _candidate_view(
                raw_row,
                effective_book_age_seconds=effective_book_age,
                effective_model_age_seconds=effective_model_age,
                effective_no_book_age_seconds=effective_no_book_age,
            )
        )

    eligible.sort(key=_candidate_sort_key)
    unique_candidates: list[dict[str, Any]] = []
    seen_events: set[str] = set()
    for candidate in eligible:
        event_key = str(candidate.get("event_slug") or "").strip()
        if not event_key:
            event_key = f"{candidate.get('market_id')}:{target}"
        if event_key in seen_events:
            blocker_counts["duplicate_event"] += 1
            continue
        seen_events.add(event_key)
        unique_candidates.append(candidate)
    recommendations = unique_candidates[: max(0, int(limit))]
    duplicate_count = len(eligible) - len(unique_candidates)

    payload = _base_payload(target, now_utc)
    payload.update({
        "as_of_utc": run.get("generated_at_utc"),
        "candidate_count": len(latest_orders),
        "eligible_before_dedupe_count": len(eligible),
        "eligible_unique_count": len(unique_candidates),
        "deduplicated_count": duplicate_count,
        "shortlist_truncated_count": max(0, len(unique_candidates) - len(recommendations)),
        "recommendations": recommendations,
        "recommendation_count": len(recommendations),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "fund": _fund_view(run),
        "provenance": provenance,
        "warnings": warnings,
    })
    if recommendations:
        payload.update({
            "status": "READY",
            "status_message": "Current paper candidates cleared every display safety gate.",
        })
    else:
        payload.update({
            "status": "NO_BETS",
            "status_message": "No bets clear every safety gate right now.",
        })
    return payload


def load_safe_bets_payload(
    *,
    now: datetime | None = None,
    target_date: str | date | datetime | None = None,
    runs_root: str | Path | None = None,
    permission_map_path: str | Path | None = None,
    run_max_age_seconds: float = DEFAULT_RUN_MAX_AGE_SECONDS,
    permission_max_age_seconds: float = DEFAULT_PERMISSION_MAX_AGE_SECONDS,
    min_conservative_probability: float = DEFAULT_MIN_CONSERVATIVE_PROBABILITY,
    min_independent_days: int = DEFAULT_MIN_INDEPENDENT_DAYS,
    limit: int = DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Load the newest current-day paper run through the bounded IO adapter."""

    from .safe_bets_io import load_safe_bets_payload as load_from_artifacts

    return load_from_artifacts(
        now=now,
        target_date=target_date,
        runs_root=runs_root,
        permission_map_path=permission_map_path,
        run_max_age_seconds=run_max_age_seconds,
        permission_max_age_seconds=permission_max_age_seconds,
        min_conservative_probability=min_conservative_probability,
        min_independent_days=min_independent_days,
        limit=limit,
    )


__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_MIN_CONSERVATIVE_PROBABILITY",
    "DEFAULT_MIN_INDEPENDENT_DAYS",
    "DEFAULT_PERMISSION_MAP_PATH",
    "DEFAULT_PERMISSION_MAX_AGE_SECONDS",
    "DEFAULT_RUNS_ROOT",
    "DEFAULT_RUN_MAX_AGE_SECONDS",
    "build_safe_bets_payload",
    "load_safe_bets_payload",
]
