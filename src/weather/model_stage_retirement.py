"""E3/E4 evidence gate for retiring the incumbent weather serving stack.

The gate is intentionally non-mutating.  It consumes immutable evaluation
evidence, computes dispositions, and emits a self-hashed register.  Registry
and serving changes are separate operations that may consume a verified PASS
register only after explicit review.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.experiment_contract import canonical_json, finalize_self_hash
from weather.paths import REPO_ROOT


ABLATION_SCHEMA_VERSION = "served_calibration_stage_ablation_v1"
REGISTER_SCHEMA_VERSION = "weather_model_stage_retirement_register_v1"
ABLATION_HASH_FIELD = "evidence_sha256"
REGISTER_HASH_FIELD = "register_sha256"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

MINIMUM_PAIRED_FLEET_DATES = 14
BRIER_NONINFERIORITY_MARGIN = 0.001
LOG_LOSS_NONINFERIORITY_MARGIN = 0.005
MAX_ECE_REGRESSION = 0.01
MAX_MARKET_BRIER_REGRESSION = 0.01

REQUIRED_EXPERIMENT_TYPES = frozenset(
    {"remove_one", "cumulative_removal", "order_interaction"}
)
REQUIRED_SAFETY_INVARIANTS = frozenset(
    {
        "probability_simplex",
        "settlement_support",
        "observation_floor",
        "named_abstention_on_source_failure",
        "no_silent_model_fallback",
    }
)
REQUIRED_CALIBRATION_ARMS = frozenset(
    {
        "identity",
        "literal_served_power_temperature",
        "coherent_simplex_temperature_or_shrinkage",
        "current_taper_to_identity",
        "literal_current_served_transform",
    }
)
ALLOWED_SELECTED_CALIBRATORS = frozenset(
    {"identity", "simplex_temperature", "coherent_ordinal_simplex_shrinkage"}
)

REQUIRED_REQUALIFICATION_CRITERIA = frozenset(
    {
        "nested_requalification_pass",
        "all_nested_criteria_pass",
        "minimum_outer_fleet_dates",
        "preselection_lock_registered_before_evaluation",
        "corpus_manifest_verified",
        "corpus_manifest_input_contract_pass",
        "preselection_lock_binds_corpus_manifest",
        "minimum_locked_fleet_dates",
        "locked_window_pass",
        "development_fleet_coverage_complete",
        "locked_fleet_coverage_complete",
        "all_rows_release_bound_and_countable",
        "singular_nonmissing_release_id",
        "singular_nonmissing_runtime_identity",
        "source_health_rows_match_serving_permission",
        "output_bound_training_receipts_verified",
    }
)

INCUMBENT_STAGES = (
    {
        "stage_id": "binary_market_calibration_selector",
        "category": "calibration",
        "replacement": "one coherent global V1 calibrator",
    },
    {
        "stage_id": "legacy_exact_distribution_calibration",
        "category": "calibration",
        "replacement": "one coherent global V1 calibrator",
    },
    {
        "stage_id": "legacy_continuous_density_calibration",
        "category": "calibration",
        "replacement": "one coherent global V1 calibrator",
    },
    {
        "stage_id": "legacy_served_power_normalization",
        "category": "calibration",
        "replacement": "OOF-fitted identity or simplex temperature",
    },
    {
        "stage_id": "forecast_floor",
        "category": "distribution_postprocess",
        "replacement": "pooled residual distribution",
    },
    {
        "stage_id": "forecast_pull",
        "category": "distribution_postprocess",
        "replacement": "pooled residual distribution",
    },
    {
        "stage_id": "warm_tail_falsification",
        "category": "distribution_postprocess",
        "replacement": "pooled residual distribution",
    },
    {
        "stage_id": "bucket_transition",
        "category": "distribution_postprocess",
        "replacement": "pooled residual distribution",
    },
    {
        "stage_id": "afternoon_residual_centering",
        "category": "distribution_postprocess",
        "replacement": "pooled residual distribution",
    },
    {
        "stage_id": "observation_support_floor",
        "category": "distribution_postprocess",
        "replacement": "settlement-valid truncation",
    },
    {
        "stage_id": "upper_tail_cap",
        "category": "distribution_postprocess",
        "replacement": "pooled residual distribution",
    },
    {
        "stage_id": "continuation_adjustment",
        "category": "distribution_postprocess",
        "replacement": "pooled residual distribution",
    },
    {
        "stage_id": "late_day_lockin",
        "category": "distribution_postprocess",
        "replacement": "PIT residual features and settlement truncation",
    },
    {
        "stage_id": "hard_floor_postprocess",
        "category": "band_postprocess",
        "replacement": "settlement-valid truncation",
    },
    {
        "stage_id": "support_floor_postprocess",
        "category": "band_postprocess",
        "replacement": "settlement-valid truncation",
    },
    {
        "stage_id": "adjacent_band_calibration",
        "category": "band_postprocess",
        "replacement": "one coherent global V1 calibrator",
    },
    {
        "stage_id": "exact_winner_catchup",
        "category": "band_postprocess",
        "replacement": "one coherent global V1 calibrator",
    },
    {
        "stage_id": "forecast_centering",
        "category": "band_postprocess",
        "replacement": "pooled residual distribution",
    },
    {
        "stage_id": "market_bias_calibration",
        "category": "band_postprocess",
        "replacement": "pooled residual distribution",
    },
    {
        "stage_id": "partition_normalization",
        "category": "band_postprocess",
        "replacement": "direct coherent partition projection",
    },
    {
        "stage_id": "current_incumbent_blend",
        "category": "band_postprocess",
        "replacement": "single V1 prediction",
    },
    {
        "stage_id": "cutoff_hour_model_router",
        "category": "router",
        "replacement": "one pooled residual model",
    },
    {
        "stage_id": "dynamic_source_state_router",
        "category": "router",
        "replacement": "explicit source-health features and abstention",
    },
    {
        "stage_id": "silent_model_family_fallback_router",
        "category": "router",
        "replacement": "named abstention",
    },
    {
        "stage_id": "unknown_market_toronto_fallback_router",
        "category": "router",
        "replacement": "named unknown-market abstention",
    },
)

STAGE_BY_ID = {row["stage_id"]: row for row in INCUMBENT_STAGES}

V1_GRAPH_TARGETS = (
    (
        "src/weather/model/residual_distribution_v1.py",
        "predict_residual_distribution_v1",
    ),
    (
        "src/weather/collection/live_variant_predictions.py",
        "_residual_distribution_v1_payload",
    ),
    (
        "src/weather/calibration/pooled_candidate_replay.py",
        "residual_distribution_v1_replay_payload",
    ),
    (
        "src/weather/calibration/pooled_candidate_replay.py",
        "attach_residual_distribution_v1_probabilities",
    ),
)

FORBIDDEN_BINARY_SELECTOR_CALLS = frozenset(
    {
        "calibrate_market_probability",
        "load_probability_calibration",
        "apply_exact_distribution_calibration",
    }
)
FORBIDDEN_LEGACY_POSTPROCESS_CALLS = frozenset(
    {
        "apply_continuous_density_calibration",
        "apply_density_band_postprocessing",
        "apply_band_postprocessing",
        "apply_adjacent_calibration",
        "apply_market_bias_calibration",
        "apply_current_blend_guardrail",
        "_apply_current_blend",
        "normalize_partition_probabilities",
        "_normalize_probability_partition",
        "predict_density_rows_for_bundle",
        "predict_band_rows_for_bundle",
    }
)
FORBIDDEN_ROUTER_CALLS = frozenset(
    {
        "predict_variant_distribution",
        "TorontoHighTempModel",
        "regime_router",
        "model_family_router",
        "fallback_model",
    }
)


class StageRetirementGateError(ValueError):
    """Retirement evidence or a register is malformed or inconsistent."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _payload_source(value: Mapping[str, Any] | str | Path, label: str) -> tuple[dict[str, Any], str]:
    if isinstance(value, Mapping):
        payload = dict(value)
        return payload, _sha256_bytes(canonical_json(payload).encode("utf-8"))
    path = Path(value)
    if path.is_symlink() or not path.exists() or not path.is_file():
        raise StageRetirementGateError(f"{label} is missing or invalid: {path}")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StageRetirementGateError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(payload, Mapping):
        raise StageRetirementGateError(f"{label} must be a JSON object")
    return dict(payload), _sha256_bytes(raw)


def _iso_utc(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise StageRetirementGateError("generated_at_utc must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise StageRetirementGateError("generated_at_utc must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _value_set(value: Any) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return set()
    return {str(item) for item in value}


def _mapping_copy(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _valid_sha256(value: Any) -> bool:
    return bool(SHA256_RE.fullmatch(str(value or "")))


def _self_hash_valid(payload: Mapping[str, Any], field: str) -> bool:
    if not _valid_sha256(payload.get(field)):
        return False
    expected = finalize_self_hash(
        {key: value for key, value in payload.items() if key != field},
        hash_field=field,
    )
    return payload.get(field) == expected.get(field)


def _dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _function_graph(path: Path, function_name: str) -> dict[str, Any]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(matches) != 1:
        raise StageRetirementGateError(
            f"expected exactly one function {function_name!r} in {path}, found {len(matches)}"
        )
    function = matches[0]
    local_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def calls_for(node: ast.AST) -> set[str]:
        return {
            _dotted_name(item.func)
            for item in ast.walk(node)
            if isinstance(item, ast.Call) and _dotted_name(item.func)
        }

    direct_calls = calls_for(function)
    closure_names = {function_name}
    pending = [function_name]
    closure_calls: set[str] = set()
    while pending:
        current_name = pending.pop()
        current = local_functions.get(current_name)
        if current is None:
            continue
        current_calls = calls_for(current)
        closure_calls.update(current_calls)
        for call in current_calls:
            terminal = call.rsplit(".", 1)[-1]
            if terminal in local_functions and terminal not in closure_names:
                closure_names.add(terminal)
                pending.append(terminal)
    calls = sorted(direct_calls)
    all_calls = sorted(closure_calls)
    terminals = {name.rsplit(".", 1)[-1] for name in all_calls}
    segment = ast.get_source_segment(source, function) or ""
    return {
        "path": path.as_posix(),
        "function": function_name,
        "function_sha256": _sha256_bytes(segment.encode("utf-8")),
        "calls": calls,
        "local_closure_functions": sorted(closure_names),
        "closure_calls": all_calls,
        "binary_selector_calls": sorted(terminals & FORBIDDEN_BINARY_SELECTOR_CALLS),
        "legacy_postprocess_calls": sorted(terminals & FORBIDDEN_LEGACY_POSTPROCESS_CALLS),
        "router_or_fallback_calls": sorted(
            (terminals & FORBIDDEN_ROUTER_CALLS)
            | {name for name in terminals if "router" in name.lower() or "fallback" in name.lower()}
        ),
    }


def audit_residual_distribution_v1_graph(
    repo_root: str | Path = REPO_ROOT,
) -> dict[str, Any]:
    """Statically verify only the V1 core and its live/replay adapter functions."""

    root = Path(repo_root).resolve()
    rows = []
    errors = []
    for relative, function_name in V1_GRAPH_TARGETS:
        path = root / relative
        try:
            row = _function_graph(path, function_name)
            row["path"] = relative
            rows.append(row)
        except (OSError, UnicodeError, SyntaxError, StageRetirementGateError) as exc:
            errors.append(f"{relative}:{function_name}: {type(exc).__name__}: {exc}")
    by_function = {row["function"]: row for row in rows}
    core_calls = set(by_function.get("predict_residual_distribution_v1", {}).get("calls") or [])
    live_calls = set(by_function.get("_residual_distribution_v1_payload", {}).get("calls") or [])
    replay_calls = set(by_function.get("residual_distribution_v1_replay_payload", {}).get("calls") or [])
    attach_calls = set(by_function.get("attach_residual_distribution_v1_probabilities", {}).get("calls") or [])

    def has_terminal(calls: set[str], expected: str) -> bool:
        return any(value.rsplit(".", 1)[-1] == expected for value in calls)

    criteria = {
        "all_graph_functions_found": len(rows) == len(V1_GRAPH_TARGETS) and not errors,
        "live_adapter_calls_v1_core": has_terminal(live_calls, "predict_residual_distribution_v1"),
        "replay_adapter_calls_v1_core": has_terminal(replay_calls, "predict_residual_distribution_v1"),
        "replay_attachment_calls_v1_adapter": has_terminal(
            attach_calls, "residual_distribution_v1_replay_payload"
        ),
        "core_uses_only_coherent_calibrator": (
            has_terminal(core_calls, "simplex_temperature")
            and not has_terminal(core_calls, "calibrate_market_probability")
        ),
        "no_dead_binary_selector_calls": not any(row["binary_selector_calls"] for row in rows),
        "no_legacy_postprocess_calls": not any(row["legacy_postprocess_calls"] for row in rows),
        "no_router_or_fallback_calls": not any(row["router_or_fallback_calls"] for row in rows),
    }
    return {
        "status": "PASS" if all(criteria.values()) else "BLOCK",
        "criteria": criteria,
        "functions": rows,
        "errors": errors,
        "binary_selector_call_count": sum(len(row["binary_selector_calls"]) for row in rows),
        "legacy_postprocess_call_count": sum(len(row["legacy_postprocess_calls"]) for row in rows),
        "router_or_fallback_call_count": sum(len(row["router_or_fallback_calls"]) for row in rows),
    }


def _requalification_gate(payload: Mapping[str, Any]) -> dict[str, Any]:
    qualification = payload.get("qualification")
    criteria = qualification.get("criteria") if isinstance(qualification, Mapping) else None
    criteria_mapping = dict(criteria) if isinstance(criteria, Mapping) else {}
    missing = sorted(REQUIRED_REQUALIFICATION_CRITERIA - set(criteria_mapping))
    failed = sorted(
        key
        for key in REQUIRED_REQUALIFICATION_CRITERIA
        if criteria_mapping.get(key) is not True
    )
    artifact = payload.get("candidate_artifact")
    checks = {
        "report_status_offline_pass": payload.get("status") == "OFFLINE_PASS",
        "qualification_status_offline_pass": (
            isinstance(qualification, Mapping)
            and qualification.get("status") == "OFFLINE_PASS"
            and qualification.get("offline_status") == "PASS"
            and qualification.get("forward_status") == "BLOCK"
        ),
        "required_criteria_present": not missing,
        "all_criteria_pass": bool(criteria_mapping) and not failed,
        "candidate_id_present": bool(str(payload.get("candidate_id") or "").strip()),
        "artifact_hash_bound": (
            isinstance(artifact, Mapping) and _valid_sha256(artifact.get("sha256"))
        ),
        "artifact_qualification_offline_pass": (
            isinstance(artifact, Mapping)
            and artifact.get("qualification_status") == "OFFLINE_PASS"
            and artifact.get("offline_qualification_status") == "PASS"
            and artifact.get("forward_qualification_status") == "BLOCK"
        ),
        "artifact_not_promotion_eligible_before_forward_attestation": (
            isinstance(artifact, Mapping) and artifact.get("promotion_eligible") is False
        ),
    }
    return {
        "status": "PASS" if all(checks.values()) else "BLOCK",
        "checks": checks,
        "missing_criteria": missing,
        "failed_criteria": failed,
        "candidate_id": str(payload.get("candidate_id") or ""),
        "artifact_sha256": artifact.get("sha256") if isinstance(artifact, Mapping) else None,
    }


def _metric_structure(row: Any) -> tuple[float | None, float | None]:
    if not isinstance(row, Mapping):
        return None, None
    return _finite(row.get("mean")), _finite(row.get("ci95_upper"))


def _calibration_gate(
    payload: Any,
    *,
    paired_date_count: int,
    paired_dates_sha256: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {
            "status": "BLOCK",
            "disposition": "BLOCK",
            "checks": {"calibration_evidence_present": False},
            "blockers": ["calibration evidence is missing"],
            "quarantine_reasons": [],
        }
    brier_mean, brier_upper = _metric_structure(payload.get("delta_brier"))
    log_mean, log_upper = _metric_structure(payload.get("delta_log_loss"))
    ece_delta = _finite(payload.get("ece_delta"))
    ece_upper = _finite(payload.get("ece_delta_ci95_upper"))
    max_market = _finite(payload.get("max_market_brier_delta"))
    invariants = payload.get("simplex_invariants")
    invariant_keys = {
        "partition_sum_one",
        "probabilities_finite",
        "probabilities_nonnegative",
        "served_transform_parity",
    }
    structural = {
        "literal_served_transform_executed": payload.get("literal_served_transform_executed")
        is True,
        "literal_current_comparator": payload.get("comparator_arm")
        == "literal_current_served_transform",
        "required_arms_evaluated": REQUIRED_CALIBRATION_ARMS
        <= _value_set(payload.get("arms_evaluated")),
        "selected_calibrator_is_coherent": payload.get("selected_arm")
        in ALLOWED_SELECTED_CALIBRATORS,
        "paired_unit_is_fleet_date": payload.get("paired_unit") == "fleet_target_date",
        "paired_date_count_matches": payload.get("paired_date_count") == paired_date_count,
        "paired_date_hash_matches": payload.get("paired_dates_sha256")
        == paired_dates_sha256,
        "paired_date_minimum": paired_date_count >= MINIMUM_PAIRED_FLEET_DATES,
        "all_embargo_sensitivities_run": _value_set(
            payload.get("embargo_days_evaluated")
        )
        == {"3", "5", "7"},
        "multiple_seeds_run": (_integer(payload.get("seed_count")) or 0) >= 3,
        "calibration_receipt_bound": _valid_sha256(payload.get("evaluation_receipt_sha256")),
        "primary_metrics_present": None not in {brier_mean, brier_upper, log_mean, log_upper},
        "calibration_safety_metrics_present": None not in {ece_delta, ece_upper, max_market},
        "simplex_invariant_set_complete": isinstance(invariants, Mapping)
        and set(invariants) == invariant_keys,
        "calibration_parity_vectors_pass": (
            isinstance(payload.get("parity_vectors"), Mapping)
            and payload["parity_vectors"].get("status") == "PASS"
        ),
    }
    safety = {
        "outer_brier_improves": brier_mean is not None and brier_mean < 0,
        "outer_brier_ci_improves": brier_upper is not None and brier_upper <= 0,
        "outer_log_loss_improves": log_mean is not None and log_mean < 0,
        "outer_log_loss_ci_improves": log_upper is not None and log_upper <= 0,
        "ece_regression_within_limit": ece_delta is not None and ece_delta <= MAX_ECE_REGRESSION,
        "ece_ci_within_limit": ece_upper is not None and ece_upper <= MAX_ECE_REGRESSION,
        "market_regression_within_limit": max_market is not None
        and max_market <= MAX_MARKET_BRIER_REGRESSION,
        "simplex_invariants_pass": isinstance(invariants, Mapping)
        and all(value == "PASS" for value in invariants.values()),
    }
    blockers = sorted(key for key, value in structural.items() if not value)
    quarantine = sorted(key for key, value in safety.items() if not value)
    if blockers:
        status = "BLOCK"
        disposition = "BLOCK"
    elif quarantine:
        status = "QUARANTINE"
        disposition = "QUARANTINE"
    else:
        status = "PASS"
        disposition = "SUPERSEDE_LEGACY_CALIBRATION"
    return {
        "status": status,
        "disposition": disposition,
        "checks": {**structural, **safety},
        "blockers": blockers,
        "quarantine_reasons": quarantine,
        "selected_arm": payload.get("selected_arm"),
        "comparator_arm": payload.get("comparator_arm"),
        "arms_evaluated": sorted(_value_set(payload.get("arms_evaluated"))),
        "paired_unit": payload.get("paired_unit"),
        "paired_date_count": payload.get("paired_date_count"),
        "paired_dates_sha256": payload.get("paired_dates_sha256"),
        "embargo_days_evaluated": sorted(
            _value_set(payload.get("embargo_days_evaluated"))
        ),
        "seed_count": _integer(payload.get("seed_count")),
        "delta_brier": _mapping_copy(payload.get("delta_brier")),
        "delta_log_loss": _mapping_copy(payload.get("delta_log_loss")),
        "ece_delta": ece_delta,
        "max_market_brier_delta": max_market,
        "simplex_invariants": _mapping_copy(invariants),
        "parity_vectors": _mapping_copy(payload.get("parity_vectors")),
    }


def _stage_gate(
    descriptor: Mapping[str, Any],
    evidence: Any,
    *,
    paired_date_count: int,
    paired_dates_sha256: str,
) -> dict[str, Any]:
    stage_id = str(descriptor["stage_id"])
    base = {
        **dict(descriptor),
        "decision": "BLOCK",
        "checks": {},
        "blockers": [],
        "quarantine_reasons": [],
    }
    if not isinstance(evidence, Mapping):
        base["blockers"] = ["stage evidence is missing"]
        return base
    brier_mean, brier_upper = _metric_structure(evidence.get("delta_brier"))
    log_mean, log_upper = _metric_structure(evidence.get("delta_log_loss"))
    max_market = _finite(evidence.get("max_market_brier_delta"))
    invariants = evidence.get("safety_invariants")
    structural = {
        "stage_id_matches": evidence.get("stage_id") == stage_id,
        "category_matches": evidence.get("category") == descriptor.get("category"),
        "required_experiment_types_present": REQUIRED_EXPERIMENT_TYPES
        <= _value_set(evidence.get("experiment_types")),
        "paired_unit_is_fleet_date": evidence.get("paired_unit") == "fleet_target_date",
        "paired_date_count_matches": evidence.get("paired_date_count") == paired_date_count,
        "paired_date_hash_matches": evidence.get("paired_dates_sha256")
        == paired_dates_sha256,
        "paired_date_minimum": paired_date_count >= MINIMUM_PAIRED_FLEET_DATES,
        "evaluation_receipt_bound": _valid_sha256(evidence.get("evaluation_receipt_sha256")),
        "primary_metrics_present": None not in {brier_mean, brier_upper, log_mean, log_upper},
        "market_safety_metric_present": max_market is not None,
        "safety_invariant_set_complete": isinstance(invariants, Mapping)
        and set(invariants) == REQUIRED_SAFETY_INVARIANTS,
    }
    noninferiority = {
        "brier_mean_noninferior": brier_mean is not None
        and brier_mean <= BRIER_NONINFERIORITY_MARGIN,
        "brier_ci_noninferior": brier_upper is not None
        and brier_upper <= BRIER_NONINFERIORITY_MARGIN,
        "log_loss_mean_noninferior": log_mean is not None
        and log_mean <= LOG_LOSS_NONINFERIORITY_MARGIN,
        "log_loss_ci_noninferior": log_upper is not None
        and log_upper <= LOG_LOSS_NONINFERIORITY_MARGIN,
        "market_regression_within_limit": max_market is not None
        and max_market <= MAX_MARKET_BRIER_REGRESSION,
        "all_safety_invariants_pass": isinstance(invariants, Mapping)
        and all(value == "PASS" for value in invariants.values()),
    }
    blockers = sorted(key for key, value in structural.items() if not value)
    quarantine = sorted(key for key, value in noninferiority.items() if not value)
    if blockers:
        decision = "BLOCK"
    elif quarantine:
        decision = "QUARANTINE"
    else:
        decision = "RETIRE"
    return {
        **base,
        "decision": decision,
        "checks": {**structural, **noninferiority},
        "blockers": blockers,
        "quarantine_reasons": quarantine,
        "delta_brier": _mapping_copy(evidence.get("delta_brier")),
        "delta_log_loss": _mapping_copy(evidence.get("delta_log_loss")),
        "max_market_brier_delta": max_market,
        "evaluation_receipt_sha256": evidence.get("evaluation_receipt_sha256"),
        "experiment_types": sorted(_value_set(evidence.get("experiment_types"))),
        "paired_unit": evidence.get("paired_unit"),
        "paired_date_count": evidence.get("paired_date_count"),
        "paired_dates_sha256": evidence.get("paired_dates_sha256"),
        "safety_invariants": _mapping_copy(invariants),
    }


def build_stage_retirement_register(
    requalification_report: Mapping[str, Any] | str | Path,
    served_calibration_ablation: Mapping[str, Any] | str | Path,
    *,
    repo_root: str | Path = REPO_ROOT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Evaluate E3/E4 evidence and return a self-hashed, non-mutating register."""

    report, report_sha = _payload_source(requalification_report, "requalification report")
    evidence, evidence_file_sha = _payload_source(
        served_calibration_ablation,
        "served calibration/stage ablation",
    )
    requalification = _requalification_gate(report)
    graph = audit_residual_distribution_v1_graph(repo_root)
    envelope_checks = {
        "schema_version": evidence.get("schema_version") == ABLATION_SCHEMA_VERSION,
        "artifact_type": evidence.get("artifact_type")
        == "served_calibration_stage_ablation",
        "self_hash": _self_hash_valid(evidence, ABLATION_HASH_FIELD),
        "status_pass": evidence.get("status") == "PASS",
        "requalification_hash_bound": evidence.get("requalification_report_sha256")
        == report_sha,
        "candidate_id_matches": evidence.get("candidate_id")
        == requalification.get("candidate_id"),
        "candidate_artifact_hash_bound": evidence.get("candidate_artifact_sha256")
        == requalification.get("artifact_sha256"),
        "frozen_full_stack_bound": bool(
            str(evidence.get("frozen_full_stack_id") or "").strip()
        ),
        "candidate_graph_bound": evidence.get("candidate_graph_id")
        == requalification.get("candidate_id"),
        "independent_unit_is_fleet_date": evidence.get("independent_unit")
        == "fleet_target_date",
        "cluster_unit_is_fleet_date": evidence.get("cluster_unit")
        == "fleet_target_date",
        "paired_dates_hash_valid": _valid_sha256(evidence.get("paired_dates_sha256")),
    }
    try:
        paired_date_count = int(evidence.get("paired_date_count") or 0)
    except (TypeError, ValueError):
        paired_date_count = 0
    envelope_checks["paired_date_minimum"] = paired_date_count >= MINIMUM_PAIRED_FLEET_DATES
    envelope_blockers = sorted(key for key, value in envelope_checks.items() if not value)
    paired_dates_sha256 = str(evidence.get("paired_dates_sha256") or "")

    calibration = _calibration_gate(
        evidence.get("calibration"),
        paired_date_count=paired_date_count,
        paired_dates_sha256=paired_dates_sha256,
    )
    evidence_rows = evidence.get("stage_ablations")
    rows = list(evidence_rows) if isinstance(evidence_rows, Sequence) and not isinstance(
        evidence_rows, (str, bytes)
    ) else []
    by_stage: dict[str, Any] = {}
    duplicate_stage_ids = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        stage_id = str(row.get("stage_id") or "")
        if stage_id in by_stage:
            duplicate_stage_ids.append(stage_id)
        else:
            by_stage[stage_id] = row
    extra_stage_ids = sorted(set(by_stage) - set(STAGE_BY_ID))
    stages = [
        _stage_gate(
            descriptor,
            by_stage.get(str(descriptor["stage_id"])),
            paired_date_count=paired_date_count,
            paired_dates_sha256=paired_dates_sha256,
        )
        for descriptor in INCUMBENT_STAGES
    ]
    if duplicate_stage_ids:
        envelope_blockers.append("duplicate_stage_ids")
    if extra_stage_ids:
        envelope_blockers.append("unexpected_stage_ids")

    structural_blockers = list(envelope_blockers)
    if requalification["status"] != "PASS":
        structural_blockers.append("requalification_not_pass")
    if graph["status"] != "PASS":
        structural_blockers.append("v1_graph_contains_legacy_or_router_calls")
    if calibration["status"] == "BLOCK":
        structural_blockers.append("calibration_ablation_incomplete")
    if any(row["decision"] == "BLOCK" for row in stages):
        structural_blockers.append("stage_ablation_incomplete")
    quarantine_reasons = []
    if calibration["status"] == "QUARANTINE":
        quarantine_reasons.append("calibration_ablation_failed_safety_or_improvement")
    if any(row["decision"] == "QUARANTINE" for row in stages):
        quarantine_reasons.append("stage_removal_failed_noninferiority_or_safety")
    if structural_blockers:
        status = "BLOCK"
    elif quarantine_reasons:
        status = "QUARANTINE"
    else:
        status = "PASS"

    register = {
        "schema_version": REGISTER_SCHEMA_VERSION,
        "artifact_type": "weather_model_stage_retirement_register",
        "generated_at_utc": _iso_utc(generated_at_utc),
        "status": status,
        "candidate_id": requalification.get("candidate_id"),
        "retirement_permission": (
            "AUTHORIZED_BY_EVIDENCE_REGISTER" if status == "PASS" else "FORBIDDEN"
        ),
        "mutation_performed": False,
        "thresholds": {
            "minimum_paired_fleet_dates": MINIMUM_PAIRED_FLEET_DATES,
            "brier_noninferiority_margin": BRIER_NONINFERIORITY_MARGIN,
            "log_loss_noninferiority_margin": LOG_LOSS_NONINFERIORITY_MARGIN,
            "max_ece_regression": MAX_ECE_REGRESSION,
            "max_market_brier_regression": MAX_MARKET_BRIER_REGRESSION,
        },
        "source_bindings": {
            "requalification_report_sha256": report_sha,
            "served_calibration_ablation_file_sha256": evidence_file_sha,
            "served_calibration_ablation_payload_sha256": evidence.get(
                ABLATION_HASH_FIELD
            ),
        },
        "requalification": requalification,
        "ablation_envelope": {
            "status": "PASS" if not envelope_blockers else "BLOCK",
            "checks": envelope_checks,
            "blockers": sorted(set(envelope_blockers)),
            "duplicate_stage_ids": sorted(set(duplicate_stage_ids)),
            "extra_stage_ids": extra_stage_ids,
            "paired_date_count": paired_date_count,
            "paired_dates_sha256": paired_dates_sha256,
            "frozen_full_stack_id": evidence.get("frozen_full_stack_id"),
            "candidate_graph_id": evidence.get("candidate_graph_id"),
        },
        "calibration": calibration,
        "stages": stages,
        "v1_graph_audit": graph,
        "blockers": sorted(set(structural_blockers)),
        "quarantine_reasons": sorted(set(quarantine_reasons)),
        "summary": {
            "incumbent_stage_count": len(INCUMBENT_STAGES),
            "retire_count": sum(row["decision"] == "RETIRE" for row in stages),
            "quarantine_count": sum(row["decision"] == "QUARANTINE" for row in stages),
            "block_count": sum(row["decision"] == "BLOCK" for row in stages),
            "binary_selector_call_count": graph["binary_selector_call_count"],
            "legacy_postprocess_call_count": graph["legacy_postprocess_call_count"],
            "router_or_fallback_call_count": graph["router_or_fallback_call_count"],
        },
    }
    return finalize_self_hash(register, hash_field=REGISTER_HASH_FIELD)


def verify_stage_retirement_register(
    register: Mapping[str, Any],
    requalification_report: Mapping[str, Any] | str | Path,
    served_calibration_ablation: Mapping[str, Any] | str | Path,
    *,
    repo_root: str | Path = REPO_ROOT,
) -> dict[str, Any]:
    """Rebuild the register from bound inputs and reject any semantic tampering."""

    if register.get("schema_version") != REGISTER_SCHEMA_VERSION:
        raise StageRetirementGateError("retirement register schema mismatch")
    if not _self_hash_valid(register, REGISTER_HASH_FIELD):
        raise StageRetirementGateError("retirement register self-hash mismatch")
    expected = build_stage_retirement_register(
        requalification_report,
        served_calibration_ablation,
        repo_root=repo_root,
        generated_at_utc=str(register.get("generated_at_utc") or ""),
    )
    if canonical_json(dict(register)) != canonical_json(expected):
        raise StageRetirementGateError(
            "retirement register does not match bound evidence or current V1 graph"
        )
    return dict(register)


def write_stage_retirement_register(
    register: Mapping[str, Any],
    path: str | Path,
) -> Path:
    """Write one verified-shape register without overwriting prior evidence."""

    if not _self_hash_valid(register, REGISTER_HASH_FIELD):
        raise StageRetirementGateError("cannot write a register with an invalid self-hash")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(register), indent=2, sort_keys=True, allow_nan=False) + "\n"
    try:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise StageRetirementGateError(f"retirement register already exists: {output}") from exc
    return output


__all__ = [name for name in globals() if not name.startswith("_")]
