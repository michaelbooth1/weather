"""Execute the bounded E3/E4 calibration and serving-stage experiment matrix.

The retirement gate intentionally validates evidence rather than running the
incumbent stack.  This module supplies the missing execution layer: callers
provide captured, untouched cases and one runtime adapter that can evaluate a
predeclared experiment configuration.  The module owns the complete matrix,
proper scoring, whole-fleet-date clustering, safety aggregation, receipts, and
self-hashed evidence envelope.  A predictor cannot silently omit a stage or
experiment arm because the matrix is generated here.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
import random
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.experiment_contract import canonical_json, finalize_self_hash
from weather.model_stage_retirement import (
    ABLATION_HASH_FIELD,
    ABLATION_SCHEMA_VERSION,
    ALLOWED_SELECTED_CALIBRATORS,
    INCUMBENT_STAGES,
    MINIMUM_PAIRED_FLEET_DATES,
    REQUIRED_CALIBRATION_ARMS,
    REQUIRED_EXPERIMENT_TYPES,
    REQUIRED_SAFETY_INVARIANTS,
)


MAX_CASES = 250
MAX_BOOTSTRAP_ITERATIONS = 500
MAX_BOOTSTRAP_SEEDS = 5
DEFAULT_BOOTSTRAP_SEEDS = (17, 31, 47, 73, 101)
DEFAULT_EVALUATION_SEEDS = (101, 211, 307)
MAX_EVALUATION_SEEDS = 5
MAX_EXECUTION_CALLS = 20_000
PARITY_ABSOLUTE_TOLERANCE = 1e-12
PAYLOAD_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CONCRETE_COHERENT_CALIBRATION_ARMS = (
    "simplex_temperature",
    "coherent_ordinal_simplex_shrinkage",
)
SENSITIVE_PREDICTOR_INPUT_TOKENS = (
    "winner",
    "outcome",
    "settlement",
    "label",
    "resolved",
    "resolution",
    "final_bucket",
    "actual_bucket",
    "actual_value",
    "target_value",
)


class StageAblationExecutionError(ValueError):
    """A captured case, runtime result, or experiment contract is invalid."""


def _iso_utc(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise StageAblationExecutionError("generated_at_utc must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise StageAblationExecutionError("generated_at_utc must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _sha256_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def probability_vector_sha256(probabilities: Mapping[str, Any] | None) -> str:
    """Hash one ordered probability vector using the evaluator's contract."""

    rows = []
    if probabilities is not None:
        if not isinstance(probabilities, Mapping):
            raise StageAblationExecutionError("probability vector must be an object")
        for band, probability in probabilities.items():
            try:
                value = float(probability)
            except (TypeError, ValueError, OverflowError) as exc:
                raise StageAblationExecutionError(
                    "probability vector values must be numeric"
                ) from exc
            if not math.isfinite(value):
                raise StageAblationExecutionError(
                    "probability vector values must be finite"
                )
            rows.append({"band": str(band), "probability": value})
    return _sha256_payload(rows)


def _predictor_adapter_contract(predictor: Callable[..., Any]) -> dict[str, str]:
    identity = f"{getattr(predictor, '__module__', '')}:{getattr(predictor, '__qualname__', '')}"
    if identity in {":", ""}:
        raise StageAblationExecutionError("predictor adapter identity is unavailable")
    try:
        source = inspect.getsource(inspect.unwrap(predictor))
    except (OSError, TypeError) as exc:
        raise StageAblationExecutionError(
            "predictor adapter source is unavailable for hashing"
        ) from exc
    return {
        "identity": identity,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
    }


def _sensitive_input_key(key: Any) -> bool:
    normalized = str(key or "").strip().lower()
    if normalized == "target_date":
        return False
    return any(token in normalized for token in SENSITIVE_PREDICTOR_INPUT_TOKENS)


def _sanitize_predictor_input(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_predictor_input(item)
            for key, item in value.items()
            if not _sensitive_input_key(key)
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_sanitize_predictor_input(item) for item in value]
    return value


def _contains_sensitive_input_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _sensitive_input_key(key) or _contains_sensitive_input_key(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_sensitive_input_key(item) for item in value)
    return False


def _captured_input_contract(case: Mapping[str, Any]) -> tuple[str, str]:
    captured_input = case.get("captured_input")
    if not isinstance(captured_input, Mapping):
        raise StageAblationExecutionError("case captured_input must be an object")
    declared = str(case.get("captured_input_sha256") or "").lower()
    actual = _sha256_payload(dict(captured_input))
    if not PAYLOAD_SHA256_RE.fullmatch(declared) or declared != actual:
        raise StageAblationExecutionError(
            "case captured_input_sha256 does not bind captured_input"
        )
    sanitized = _sanitize_predictor_input(case)
    if _contains_sensitive_input_key(sanitized):
        raise StageAblationExecutionError("predictor input still contains outcome fields")
    return declared, _sha256_payload(sanitized)


def _sha256_source(value: Mapping[str, Any] | str | Path) -> tuple[dict[str, Any], str]:
    if isinstance(value, Mapping):
        payload = dict(value)
        return payload, _sha256_payload(payload)
    path = Path(value)
    if path.is_symlink() or not path.is_file():
        raise StageAblationExecutionError(f"requalification report is invalid: {path}")
    raw = path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise StageAblationExecutionError("requalification report is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise StageAblationExecutionError("requalification report must be an object")
    return dict(payload), hashlib.sha256(raw).hexdigest()


def _case_key(case: Mapping[str, Any]) -> tuple[str, str, int]:
    target_date = str(case.get("target_date") or "").strip()
    market_id = str(case.get("market_id") or "").strip()
    try:
        cutoff_hour = int(case.get("cutoff_hour"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise StageAblationExecutionError("case cutoff_hour must be an integer") from exc
    if not target_date or not market_id or cutoff_hour < 0 or cutoff_hour > 23:
        raise StageAblationExecutionError("case identity is incomplete")
    return target_date, market_id, cutoff_hour


def _normalize_result(
    result: Mapping[str, Any],
    *,
    winner_key: str,
    expected_bands: tuple[str, ...] | None,
    candidate_id: str,
    allowed_band_keys: Sequence[str] | None,
    impossible_band_keys: Sequence[str] | None,
    require_served_reference: bool,
) -> dict[str, Any]:
    if result.get("prediction_status") != "predicted":
        raise StageAblationExecutionError("normal predictor call did not return predicted")
    if result.get("model_family") != candidate_id:
        raise StageAblationExecutionError("predictor used an unexpected model family")
    if result.get("failure_reason") not in (None, ""):
        raise StageAblationExecutionError("predicted result contains a failure reason")
    probabilities = result.get("probabilities")
    if not isinstance(probabilities, Mapping) or not probabilities:
        raise StageAblationExecutionError("predictor result has no probability partition")
    bands = tuple(str(key) for key in probabilities)
    if len(set(bands)) != len(bands):
        raise StageAblationExecutionError("predictor result contains duplicate bands")
    if expected_bands is not None and bands != expected_bands:
        raise StageAblationExecutionError("experiment changed the ordered market partition")
    values = []
    for band in bands:
        try:
            value = float(probabilities[band])
        except (TypeError, ValueError, OverflowError) as exc:
            raise StageAblationExecutionError("probabilities must be numeric") from exc
        if not math.isfinite(value) or value < 0.0:
            raise StageAblationExecutionError("probabilities must be finite and nonnegative")
        values.append(value)
    if winner_key not in bands:
        raise StageAblationExecutionError("winner_key is absent from the partition")
    if not math.isclose(math.fsum(values), 1.0, abs_tol=1e-9, rel_tol=0.0):
        raise StageAblationExecutionError("probability partition does not sum to one")
    allowed = (
        {str(value) for value in allowed_band_keys}
        if allowed_band_keys is not None
        else set(bands)
    )
    impossible = {str(value) for value in impossible_band_keys or ()}
    if not allowed <= set(bands) or not impossible <= set(bands):
        raise StageAblationExecutionError(
            "case support constraints reference absent market bands"
        )
    probability_by_band = dict(zip(bands, values))
    support_valid = all(
        probability_by_band[band] <= 1e-12
        for band in set(bands) - allowed
    )
    observation_floor_valid = all(
        probability_by_band[band] <= 1e-12 for band in impossible
    )
    vector_sha256 = probability_vector_sha256(probabilities)
    served_reference_error = None
    served_reference_sha256 = None
    if require_served_reference:
        reference = result.get("served_reference_probabilities")
        if not isinstance(reference, Mapping):
            raise StageAblationExecutionError(
                "literal served comparator omitted served reference probabilities"
            )
        reference_bands = tuple(str(key) for key in reference)
        if reference_bands != bands:
            raise StageAblationExecutionError(
                "served reference changed the ordered market partition"
            )
        reference_values = []
        for band in bands:
            try:
                reference_value = float(reference[band])
            except (TypeError, ValueError, OverflowError) as exc:
                raise StageAblationExecutionError(
                    "served reference probabilities must be numeric"
                ) from exc
            if not math.isfinite(reference_value) or reference_value < 0.0:
                raise StageAblationExecutionError(
                    "served reference probabilities must be finite and nonnegative"
                )
            reference_values.append(reference_value)
        if not math.isclose(
            math.fsum(reference_values), 1.0, abs_tol=1e-9, rel_tol=0.0
        ):
            raise StageAblationExecutionError(
                "served reference probability partition does not sum to one"
            )
        served_reference_error = max(
            abs(left - right)
            for left, right in zip(values, reference_values)
        )
        served_reference_sha256 = probability_vector_sha256(reference)
    winner_index = bands.index(winner_key)
    brier = math.fsum(
        (value - (1.0 if index == winner_index else 0.0)) ** 2
        for index, value in enumerate(values)
    )
    log_loss = -math.log(max(values[winner_index], 1e-15))
    top_index = min(range(len(values)), key=lambda index: (-values[index], index))
    return {
        "bands": bands,
        "values": values,
        "brier": brier,
        "log_loss": log_loss,
        "top_confidence": values[top_index],
        "top_correct": 1.0 if top_index == winner_index else 0.0,
        "probability_vector_sha256": vector_sha256,
        "served_reference_probability_vector_sha256": served_reference_sha256,
        "served_reference_max_abs_delta": served_reference_error,
        "support_valid": support_valid,
        "observation_floor_valid": observation_floor_valid,
        "model_family_valid": True,
        "prediction_status": "predicted",
    }


def _expected_stage_execution(experiment: Mapping[str, Any]) -> dict[str, str]:
    disabled = {str(value) for value in experiment.get("disabled_stages") or ()}
    known = {str(row["stage_id"]) for row in INCUMBENT_STAGES}
    if not disabled <= known:
        raise StageAblationExecutionError("experiment disables an unknown stage")
    return {
        stage_id: ("disabled" if stage_id in disabled else "executed")
        for stage_id in sorted(known)
    }


def _execution_config_template(
    experiment: Mapping[str, Any],
    *,
    embargo_days: int,
    evaluation_seed: int,
    probe_type: str,
    predictor_adapter: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": "served_stage_ablation_predictor_config_v1",
        "experiment": dict(experiment),
        "embargo_days": int(embargo_days),
        "evaluation_seed": int(evaluation_seed),
        "probe_type": str(probe_type),
        "predictor_adapter": dict(predictor_adapter),
        "expected_stage_execution": _expected_stage_execution(experiment),
    }


def _bound_execution_config(
    template: Mapping[str, Any],
    *,
    case_key: Sequence[Any],
    captured_input_sha256: str,
    predictor_input: Mapping[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    template_payload = dict(template)
    template_sha256 = _sha256_payload(template_payload)
    call_binding = {
        "case_key": list(case_key),
        "captured_input_sha256": captured_input_sha256,
        "predictor_input_sha256": _sha256_payload(dict(predictor_input)),
    }
    config_sha256 = _sha256_payload({
        "template_sha256": template_sha256,
        "call_binding": call_binding,
    })
    return (
        {
            **template_payload,
            "template_sha256": template_sha256,
            "call_binding": call_binding,
            "experiment_config_sha256": config_sha256,
        },
        template_sha256,
        call_binding,
    )


def _expected_execution_proof(
    config: Mapping[str, Any],
    *,
    probability_vector_sha256_value: str,
    prediction_status: str,
    failure_reason: str,
) -> dict[str, Any]:
    experiment = config.get("experiment") or {}
    adapter = config.get("predictor_adapter") or {}
    binding = config.get("call_binding") or {}
    return {
        "experiment_config_sha256": config.get("experiment_config_sha256"),
        "experiment_id": experiment.get("experiment_id"),
        "executed_disabled_stages": list(experiment.get("disabled_stages") or []),
        "executed_order_override": list(experiment.get("order_override") or []),
        "executed_calibration_arm": experiment.get("calibration_arm"),
        "executed_stage_execution": dict(config.get("expected_stage_execution") or {}),
        "embargo_days": config.get("embargo_days"),
        "evaluation_seed": config.get("evaluation_seed"),
        "probe_type": config.get("probe_type"),
        "predictor_adapter_identity": adapter.get("identity"),
        "predictor_adapter_source_sha256": adapter.get("source_sha256"),
        "captured_input_sha256": binding.get("captured_input_sha256"),
        "predictor_input_sha256": binding.get("predictor_input_sha256"),
        "probability_vector_sha256": probability_vector_sha256_value,
        "prediction_status": prediction_status,
        "failure_reason": failure_reason,
    }


def _validate_execution_proof(
    result: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    probability_vector_sha256_value: str,
    prediction_status: str,
    failure_reason: str,
) -> str:
    proof = result.get("execution_proof")
    if not isinstance(proof, Mapping):
        raise StageAblationExecutionError("predictor omitted execution_proof")
    expected = _expected_execution_proof(
        config,
        probability_vector_sha256_value=probability_vector_sha256_value,
        prediction_status=prediction_status,
        failure_reason=failure_reason,
    )
    if canonical_json(dict(proof)) != canonical_json(expected):
        raise StageAblationExecutionError(
            "predictor execution_proof does not match the executed stage config"
        )
    return _sha256_payload(expected)


def _normalize_probe_result(
    result: Mapping[str, Any],
    *,
    probe_type: str,
    candidate_id: str,
) -> dict[str, Any]:
    expected_reason = {
        "source_failure": "required_source_failure",
        "unknown_market": "unknown_market",
    }[probe_type]
    if result.get("prediction_status") != "abstained":
        raise StageAblationExecutionError(
            f"{probe_type} probe did not produce named abstention"
        )
    if result.get("failure_reason") != expected_reason:
        raise StageAblationExecutionError(
            f"{probe_type} probe returned the wrong failure reason"
        )
    if result.get("probabilities") not in (None, {}, []):
        raise StageAblationExecutionError(
            f"{probe_type} probe silently returned fallback probabilities"
        )
    if result.get("model_family") not in (None, "", candidate_id):
        raise StageAblationExecutionError(
            f"{probe_type} probe named an unexpected fallback model family"
        )
    return {
        "prediction_status": "abstained",
        "failure_reason": expected_reason,
        "probability_vector_sha256": probability_vector_sha256(None),
        "named_abstention": True,
        "no_silent_fallback": True,
    }


def _execution_receipt(
    *,
    call_id: int,
    case_key: Sequence[Any],
    experiment_id: str,
    probe_type: str,
    template_sha256: str,
    call_binding: Mapping[str, Any],
    experiment_config_sha256: str,
    probability_vector_sha256_value: str,
    served_reference_probability_vector_sha256: str | None,
    execution_proof_sha256: str,
    prediction_status: str,
    failure_reason: str,
) -> dict[str, Any]:
    return finalize_self_hash(
        {
            "call_id": int(call_id),
            "case_key": list(case_key),
            "experiment_id": experiment_id,
            "probe_type": probe_type,
            "template_sha256": template_sha256,
            "call_binding": dict(call_binding),
            "experiment_config_sha256": experiment_config_sha256,
            "probability_vector_sha256": probability_vector_sha256_value,
            "served_reference_probability_vector_sha256": (
                served_reference_probability_vector_sha256
            ),
            "execution_proof_sha256": execution_proof_sha256,
            "prediction_status": prediction_status,
            "failure_reason": failure_reason,
        },
        hash_field="receipt_sha256",
    )


def _probe_predictor_input(
    base: Mapping[str, Any],
    *,
    probe_type: str,
) -> dict[str, Any]:
    payload = _sanitize_predictor_input(base)
    payload["execution_probe"] = {"probe_type": probe_type}
    if probe_type == "source_failure":
        payload["source_health"] = {
            "required_source_status": "failed",
            "serving_permission": False,
        }
        captured = payload.get("captured_input")
        if isinstance(captured, dict):
            captured["source_health"] = dict(payload["source_health"])
    elif probe_type == "unknown_market":
        payload["market_id"] = "__unknown_market__"
    else:
        raise StageAblationExecutionError(f"unsupported execution probe: {probe_type}")
    return payload


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise StageAblationExecutionError("cannot take a percentile of no values")
    position = (len(ordered) - 1) * probability
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _clustered_delta(
    baseline: Sequence[Mapping[str, Any]],
    challenger: Sequence[Mapping[str, Any]],
    metric: str,
    *,
    seeds: Sequence[int],
    iterations: int,
) -> dict[str, Any]:
    if len(baseline) != len(challenger) or not baseline:
        raise StageAblationExecutionError("paired metric rows are incomplete")
    by_date: dict[str, list[float]] = defaultdict(list)
    for left, right in zip(baseline, challenger):
        if left["key"] != right["key"]:
            raise StageAblationExecutionError("paired metric row identity mismatch")
        by_date[str(left["key"][0])].append(float(right[metric]) - float(left[metric]))
    date_deltas = {
        target_date: math.fsum(values) / len(values)
        for target_date, values in sorted(by_date.items())
    }
    observed = math.fsum(date_deltas.values()) / len(date_deltas)
    dates = tuple(date_deltas)
    bootstrap = []
    for seed in seeds:
        generator = random.Random(int(seed))
        for _ in range(iterations):
            sample = [generator.choice(dates) for _ in dates]
            bootstrap.append(
                math.fsum(date_deltas[target_date] for target_date in sample)
                / len(sample)
            )
    return {
        "mean": observed,
        "ci95_lower": _percentile(bootstrap, 0.025),
        "ci95_upper": _percentile(bootstrap, 0.975),
        "fleet_dates": len(dates),
        "cluster_unit": "fleet_target_date",
        "bootstrap_iterations_per_seed": iterations,
        "bootstrap_seeds": [int(seed) for seed in seeds],
    }


def _clustered_date_values(
    values: Mapping[str, float],
    *,
    seeds: Sequence[int],
    iterations: int,
) -> dict[str, float]:
    if not values:
        raise StageAblationExecutionError("clustered values require fleet dates")
    dates = tuple(sorted(values))
    observed = math.fsum(float(values[target_date]) for target_date in dates) / len(dates)
    bootstrap = []
    for seed in seeds:
        generator = random.Random(int(seed))
        for _ in range(iterations):
            sample = [generator.choice(dates) for _ in dates]
            bootstrap.append(
                math.fsum(float(values[target_date]) for target_date in sample)
                / len(sample)
            )
    return {
        "mean": observed,
        "ci95_lower": _percentile(bootstrap, 0.025),
        "ci95_upper": _percentile(bootstrap, 0.975),
    }


def _ece(rows: Sequence[Mapping[str, Any]]) -> float:
    if not rows:
        raise StageAblationExecutionError("ECE requires rows")
    total = len(rows)
    value = 0.0
    for index in range(10):
        low = index / 10.0
        high = (index + 1) / 10.0
        bucket = [
            row for row in rows
            if row["top_confidence"] >= low
            and (row["top_confidence"] < high or (index == 9 and row["top_confidence"] <= high))
        ]
        if bucket:
            confidence = math.fsum(row["top_confidence"] for row in bucket) / len(bucket)
            accuracy = math.fsum(row["top_correct"] for row in bucket) / len(bucket)
            value += (len(bucket) / total) * abs(confidence - accuracy)
    return value


def _max_market_delta(
    baseline: Sequence[Mapping[str, Any]],
    challenger: Sequence[Mapping[str, Any]],
    metric: str = "brier",
) -> float:
    by_market: dict[str, list[float]] = defaultdict(list)
    for left, right in zip(baseline, challenger):
        if left["key"] != right["key"]:
            raise StageAblationExecutionError("market delta identities do not match")
        by_market[str(left["key"][1])].append(float(right[metric]) - float(left[metric]))
    return max(math.fsum(values) / len(values) for values in by_market.values())


def _safety_status(
    results: Sequence[Mapping[str, Any]],
    probes: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    source_probes = [row for row in probes if row.get("probe_type") == "source_failure"]
    unknown_probes = [row for row in probes if row.get("probe_type") == "unknown_market"]
    statuses = {
        "probability_simplex": "PASS" if bool(results) else "BLOCK",
        "settlement_support": (
            "PASS" if results and all(row.get("support_valid") is True for row in results) else "BLOCK"
        ),
        "observation_floor": (
            "PASS"
            if results and all(row.get("observation_floor_valid") is True for row in results)
            else "BLOCK"
        ),
        "named_abstention_on_source_failure": (
            "PASS"
            if source_probes
            and all(row.get("named_abstention") is True for row in source_probes)
            else "BLOCK"
        ),
        "no_silent_model_fallback": (
            "PASS"
            if results
            and all(row.get("model_family_valid") is True for row in results)
            and source_probes
            and unknown_probes
            and all(
                row.get("no_silent_fallback") is True
                for row in [*source_probes, *unknown_probes]
            )
            else "BLOCK"
        ),
    }
    if set(statuses) != set(REQUIRED_SAFETY_INVARIANTS):
        raise StageAblationExecutionError(
            "executable safety checks do not cover the retirement invariant set"
        )
    return statuses


def experiment_matrix() -> list[dict[str, Any]]:
    """Return the complete, deterministic E3/E4 runtime experiment matrix."""

    rows: list[dict[str, Any]] = [
        {
            "experiment_id": "full_stack",
            "kind": "full_stack",
            "experiment_type": "full_stack",
            "disabled_stages": [],
        }
    ]
    calibration_arms = sorted(
        set(REQUIRED_CALIBRATION_ARMS)
        | set(CONCRETE_COHERENT_CALIBRATION_ARMS)
    )
    rows.extend(
        {
            "experiment_id": f"calibration:{arm}",
            "kind": "calibration_arm",
            "experiment_type": "calibration_arm",
            "calibration_arm": arm,
            "disabled_stages": [],
        }
        for arm in calibration_arms
    )
    stage_ids = [str(row["stage_id"]) for row in INCUMBENT_STAGES]
    for index, stage_id in enumerate(stage_ids):
        interaction_peer = stage_ids[index - 1] if index else stage_ids[1]
        rows.extend(
            [
                {
                    "experiment_id": f"remove_one:{stage_id}",
                    "kind": "stage_ablation",
                    "stage_id": stage_id,
                    "experiment_type": "remove_one",
                    "disabled_stages": [stage_id],
                },
                {
                    "experiment_id": f"cumulative_removal:{stage_id}",
                    "kind": "stage_ablation",
                    "stage_id": stage_id,
                    "experiment_type": "cumulative_removal",
                    "disabled_stages": stage_ids[: index + 1],
                },
                {
                    "experiment_id": f"order_interaction:{stage_id}",
                    "kind": "stage_ablation",
                    "stage_id": stage_id,
                    "experiment_type": "order_interaction",
                    "disabled_stages": [],
                    "order_override": [stage_id, interaction_peer],
                },
            ]
        )
    return rows


def blocked_stage_ablation_evidence(
    requalification_report: Mapping[str, Any] | str | Path,
    *,
    candidate_id: str,
    candidate_artifact_sha256: str,
    reason: str,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Emit an honest BLOCK envelope when no paired execution exists."""

    _report, report_sha = _sha256_source(requalification_report)
    payload = {
        "schema_version": ABLATION_SCHEMA_VERSION,
        "artifact_type": "served_calibration_stage_ablation",
        "status": "BLOCK",
        "block_reason": str(reason),
        "candidate_id": str(candidate_id),
        "generated_at_utc": _iso_utc(generated_at_utc),
        "requalification_report_sha256": report_sha,
        "candidate_artifact_sha256": str(candidate_artifact_sha256),
        "independent_unit": "fleet_target_date",
        "cluster_unit": "fleet_target_date",
        "paired_date_count": 0,
        "paired_dates_sha256": _sha256_payload([]),
        "frozen_full_stack_id": "",
        "candidate_graph_id": str(candidate_id),
        "execution_contract": {
            "case_count": 0,
            "experiment_count": len(experiment_matrix()),
            "prediction_count": 0,
            "matrix_sha256": _sha256_payload(experiment_matrix()),
            "selection_from_scored_rows": False,
        },
        "calibration": {},
        "stage_ablations": [],
    }
    return finalize_self_hash(payload, hash_field=ABLATION_HASH_FIELD)


def execute_served_calibration_stage_ablation(
    cases: Sequence[Mapping[str, Any]],
    predictor: Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]],
    requalification_report: Mapping[str, Any] | str | Path,
    *,
    candidate_id: str,
    candidate_artifact_sha256: str,
    frozen_full_stack_id: str,
    selected_calibrator: str,
    embargo_days_evaluated: Sequence[int] = (3, 5, 7),
    evaluation_seeds: Sequence[int] = DEFAULT_EVALUATION_SEEDS,
    bootstrap_seeds: Sequence[int] = DEFAULT_BOOTSTRAP_SEEDS,
    bootstrap_iterations: int = MAX_BOOTSTRAP_ITERATIONS,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Execute all E3/E4 arms and return gate-ready, self-hashed evidence."""

    rows = [dict(case) for case in cases]
    if not rows or len(rows) > MAX_CASES:
        raise StageAblationExecutionError(f"cases must contain 1..{MAX_CASES} rows")
    keys = [_case_key(case) for case in rows]
    if len(keys) != len(set(keys)):
        raise StageAblationExecutionError("cases contain duplicate date/market/cutoff rows")
    bootstrap_seed_values = tuple(int(seed) for seed in bootstrap_seeds)
    if (
        not bootstrap_seed_values
        or len(bootstrap_seed_values) > MAX_BOOTSTRAP_SEEDS
        or len(set(bootstrap_seed_values)) != len(bootstrap_seed_values)
    ):
        raise StageAblationExecutionError("bootstrap seeds must be unique and bounded")
    evaluation_seed_values = tuple(int(seed) for seed in evaluation_seeds)
    if (
        len(evaluation_seed_values) < 3
        or len(evaluation_seed_values) > MAX_EVALUATION_SEEDS
        or len(set(evaluation_seed_values)) != len(evaluation_seed_values)
    ):
        raise StageAblationExecutionError(
            "evaluation seeds require 3..5 unique predeclared values"
        )
    iterations = int(bootstrap_iterations)
    if iterations < 1 or iterations > MAX_BOOTSTRAP_ITERATIONS:
        raise StageAblationExecutionError("bootstrap iterations exceed the bounded contract")
    if selected_calibrator not in ALLOWED_SELECTED_CALIBRATORS:
        raise StageAblationExecutionError("selected_calibrator is not coherent")
    embargo_values = tuple(sorted({int(value) for value in embargo_days_evaluated}))
    if embargo_values != (3, 5, 7):
        raise StageAblationExecutionError("E3/E4 requires embargo sensitivities 3, 5, and 7")
    report, report_sha = _sha256_source(requalification_report)
    report_candidate = str(report.get("candidate_id") or "")
    artifact_receipt = report.get("candidate_artifact") or {}
    if report_candidate != str(candidate_id):
        raise StageAblationExecutionError("requalification candidate_id mismatch")
    if not isinstance(artifact_receipt, Mapping) or artifact_receipt.get("sha256") != candidate_artifact_sha256:
        raise StageAblationExecutionError("requalification artifact hash mismatch")

    matrix = experiment_matrix()
    normal_call_count = (
        len(rows) * len(matrix) * len(embargo_values) * len(evaluation_seed_values)
    )
    probe_call_count = len(matrix) * 2
    if normal_call_count + probe_call_count > MAX_EXECUTION_CALLS:
        raise StageAblationExecutionError(
            "served-stage execution matrix exceeds the bounded call budget"
        )
    predictor_adapter = _predictor_adapter_contract(predictor)
    case_contracts = []
    for case, key in zip(rows, keys):
        winner_key = str(case.get("winner_key") or "")
        if not winner_key:
            raise StageAblationExecutionError("case winner_key is required")
        captured_input_sha256, sanitized_input_sha256 = _captured_input_contract(case)
        predictor_input = _sanitize_predictor_input(case)
        if "winner_key" in predictor_input or _contains_sensitive_input_key(predictor_input):
            raise StageAblationExecutionError(
                "winner/outcome fields reached the predictor input"
            )
        if _sha256_payload(predictor_input) != sanitized_input_sha256:
            raise StageAblationExecutionError("sanitized predictor input hash changed")
        case_contracts.append({
            "case": case,
            "key": key,
            "winner_key": winner_key,
            "captured_input_sha256": captured_input_sha256,
            "predictor_input": predictor_input,
            "allowed_band_keys": case.get("allowed_band_keys"),
            "impossible_band_keys": case.get("impossible_band_keys"),
        })

    results: dict[str, list[dict[str, Any]]] = {
        row["experiment_id"]: [] for row in matrix
    }
    results_by_sensitivity: dict[
        tuple[int, int], dict[str, list[dict[str, Any]]]
    ] = {
        (embargo_days, evaluation_seed): {
            row["experiment_id"]: [] for row in matrix
        }
        for embargo_days in embargo_values
        for evaluation_seed in evaluation_seed_values
    }
    probes: dict[str, list[dict[str, Any]]] = {
        row["experiment_id"]: [] for row in matrix
    }
    config_templates: dict[str, dict[str, Any]] = {}
    receipts: list[dict[str, Any]] = []
    expected_bands_by_case: dict[tuple[str, str, int], tuple[str, ...]] = {}
    call_id = 0

    for embargo_days in embargo_values:
        for evaluation_seed in evaluation_seed_values:
            sensitivity = results_by_sensitivity[(embargo_days, evaluation_seed)]
            for case_contract in case_contracts:
                key = case_contract["key"]
                for experiment in matrix:
                    experiment_id = str(experiment["experiment_id"])
                    template = _execution_config_template(
                        experiment,
                        embargo_days=embargo_days,
                        evaluation_seed=evaluation_seed,
                        probe_type="none",
                        predictor_adapter=predictor_adapter,
                    )
                    config, template_sha256, call_binding = _bound_execution_config(
                        template,
                        case_key=key,
                        captured_input_sha256=case_contract["captured_input_sha256"],
                        predictor_input=case_contract["predictor_input"],
                    )
                    config_templates.setdefault(template_sha256, template)
                    try:
                        raw = predictor(case_contract["predictor_input"], config)
                    except Exception as exc:  # noqa: BLE001 - bind exact failed call
                        raise StageAblationExecutionError(
                            f"predictor failed for {experiment_id} at {key}: "
                            f"{type(exc).__name__}: {exc}"
                        ) from exc
                    if not isinstance(raw, Mapping):
                        raise StageAblationExecutionError("predictor must return an object")
                    normalized = _normalize_result(
                        raw,
                        winner_key=case_contract["winner_key"],
                        expected_bands=expected_bands_by_case.get(key),
                        candidate_id=str(candidate_id),
                        allowed_band_keys=case_contract["allowed_band_keys"],
                        impossible_band_keys=case_contract["impossible_band_keys"],
                        require_served_reference=(
                            experiment_id
                            == "calibration:literal_current_served_transform"
                        ),
                    )
                    expected_bands_by_case.setdefault(key, normalized["bands"])
                    proof_sha256 = _validate_execution_proof(
                        raw,
                        config,
                        probability_vector_sha256_value=normalized[
                            "probability_vector_sha256"
                        ],
                        prediction_status="predicted",
                        failure_reason="",
                    )
                    call_id += 1
                    receipts.append(_execution_receipt(
                        call_id=call_id,
                        case_key=key,
                        experiment_id=experiment_id,
                        probe_type="none",
                        template_sha256=template_sha256,
                        call_binding=call_binding,
                        experiment_config_sha256=config[
                            "experiment_config_sha256"
                        ],
                        probability_vector_sha256_value=normalized[
                            "probability_vector_sha256"
                        ],
                        served_reference_probability_vector_sha256=normalized[
                            "served_reference_probability_vector_sha256"
                        ],
                        execution_proof_sha256=proof_sha256,
                        prediction_status="predicted",
                        failure_reason="",
                    ))
                    result_key = (*key, embargo_days, evaluation_seed)
                    result_row = {"key": result_key, **normalized}
                    results[experiment_id].append(result_row)
                    sensitivity[experiment_id].append(result_row)

    probe_base = case_contracts[0]
    for experiment in matrix:
        experiment_id = str(experiment["experiment_id"])
        for probe_type in ("source_failure", "unknown_market"):
            predictor_input = _probe_predictor_input(
                probe_base["predictor_input"],
                probe_type=probe_type,
            )
            template = _execution_config_template(
                experiment,
                embargo_days=3,
                evaluation_seed=evaluation_seed_values[0],
                probe_type=probe_type,
                predictor_adapter=predictor_adapter,
            )
            config, template_sha256, call_binding = _bound_execution_config(
                template,
                case_key=probe_base["key"],
                captured_input_sha256=probe_base["captured_input_sha256"],
                predictor_input=predictor_input,
            )
            config_templates.setdefault(template_sha256, template)
            try:
                raw = predictor(predictor_input, config)
            except Exception as exc:  # noqa: BLE001 - bind exact failed probe
                raise StageAblationExecutionError(
                    f"predictor failed {probe_type} probe for {experiment_id}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            if not isinstance(raw, Mapping):
                raise StageAblationExecutionError("predictor probe must return an object")
            normalized_probe = _normalize_probe_result(
                raw,
                probe_type=probe_type,
                candidate_id=str(candidate_id),
            )
            proof_sha256 = _validate_execution_proof(
                raw,
                config,
                probability_vector_sha256_value=normalized_probe[
                    "probability_vector_sha256"
                ],
                prediction_status="abstained",
                failure_reason=normalized_probe["failure_reason"],
            )
            call_id += 1
            receipts.append(_execution_receipt(
                call_id=call_id,
                case_key=probe_base["key"],
                experiment_id=experiment_id,
                probe_type=probe_type,
                template_sha256=template_sha256,
                call_binding=call_binding,
                experiment_config_sha256=config["experiment_config_sha256"],
                probability_vector_sha256_value=normalized_probe[
                    "probability_vector_sha256"
                ],
                served_reference_probability_vector_sha256=None,
                execution_proof_sha256=proof_sha256,
                prediction_status="abstained",
                failure_reason=normalized_probe["failure_reason"],
            ))
            probes[experiment_id].append({
                "probe_type": probe_type,
                **normalized_probe,
            })

    baseline = results["full_stack"]
    selected_arm = selected_calibrator
    selected = results[f"calibration:{selected_arm}"]
    comparator = results["calibration:literal_current_served_transform"]
    dates = sorted({key[0] for key in keys})
    paired_dates_sha256 = _sha256_payload(dates)
    calibration_brier = _clustered_delta(
        comparator,
        selected,
        "brier",
        seeds=bootstrap_seed_values,
        iterations=iterations,
    )
    calibration_log = _clustered_delta(
        comparator,
        selected,
        "log_loss",
        seeds=bootstrap_seed_values,
        iterations=iterations,
    )
    ece_by_date = {
        target_date: (
            _ece([row for row in selected if row["key"][0] == target_date])
            - _ece([row for row in comparator if row["key"][0] == target_date])
        )
        for target_date in dates
    }
    ece_delta = _clustered_date_values(
        ece_by_date,
        seeds=bootstrap_seed_values,
        iterations=iterations,
    )
    parity_errors = [
        float(row["served_reference_max_abs_delta"])
        for row in comparator
        if row.get("served_reference_max_abs_delta") is not None
    ]
    parity_max_abs_delta = max(parity_errors) if parity_errors else math.inf
    parity_status = (
        "PASS"
        if len(parity_errors) == len(comparator)
        and parity_max_abs_delta <= PARITY_ABSOLUTE_TOLERANCE
        else "BLOCK"
    )

    def _sensitivity_metrics(
        left_id: str,
        right_id: str,
    ) -> dict[str, Any]:
        by_embargo = {}
        by_seed = {}
        for embargo_days in embargo_values:
            left = [
                row for row in results[left_id] if int(row["key"][3]) == embargo_days
            ]
            right = [
                row for row in results[right_id] if int(row["key"][3]) == embargo_days
            ]
            by_embargo[str(embargo_days)] = {
                "delta_brier": _clustered_delta(
                    left,
                    right,
                    "brier",
                    seeds=bootstrap_seed_values,
                    iterations=iterations,
                ),
                "delta_log_loss": _clustered_delta(
                    left,
                    right,
                    "log_loss",
                    seeds=bootstrap_seed_values,
                    iterations=iterations,
                ),
            }
        for evaluation_seed in evaluation_seed_values:
            left = [
                row
                for row in results[left_id]
                if int(row["key"][4]) == evaluation_seed
            ]
            right = [
                row
                for row in results[right_id]
                if int(row["key"][4]) == evaluation_seed
            ]
            by_seed[str(evaluation_seed)] = {
                "delta_brier": _clustered_delta(
                    left,
                    right,
                    "brier",
                    seeds=bootstrap_seed_values,
                    iterations=iterations,
                ),
                "delta_log_loss": _clustered_delta(
                    left,
                    right,
                    "log_loss",
                    seeds=bootstrap_seed_values,
                    iterations=iterations,
                ),
            }
        return {"embargo_days": by_embargo, "evaluation_seeds": by_seed}

    calibration_receipts = [
        row["receipt_sha256"]
        for row in receipts
        if str(row.get("experiment_id") or "").startswith("calibration:")
    ]
    calibration = {
        "literal_served_transform_executed": bool(comparator),
        "comparator_arm": "literal_current_served_transform",
        "arms_evaluated": sorted(
            set(REQUIRED_CALIBRATION_ARMS)
            | set(CONCRETE_COHERENT_CALIBRATION_ARMS)
        ),
        "selected_arm": selected_calibrator,
        "paired_unit": "fleet_target_date",
        "paired_date_count": len(dates),
        "paired_dates_sha256": paired_dates_sha256,
        "embargo_days_evaluated": list(embargo_values),
        "seed_count": len(evaluation_seed_values),
        "evaluation_seeds": list(evaluation_seed_values),
        "evaluation_receipt_sha256": _sha256_payload({
            "experiment": "calibration",
            "execution_receipt_sha256s": calibration_receipts,
            "selected_arm": selected_arm,
            "matrix_sha256": _sha256_payload(matrix),
        }),
        "delta_brier": calibration_brier,
        "delta_log_loss": calibration_log,
        "ece_delta": ece_delta["mean"],
        "ece_delta_ci95_upper": ece_delta["ci95_upper"],
        "ece_delta_clustered": ece_delta,
        "max_market_brier_delta": _max_market_delta(comparator, selected),
        "simplex_invariants": {
            "partition_sum_one": "PASS",
            "probabilities_finite": "PASS",
            "probabilities_nonnegative": "PASS",
            "served_transform_parity": parity_status,
        },
        "parity_vectors": {
            "status": parity_status,
            "max_abs_delta": parity_max_abs_delta,
            "absolute_tolerance": PARITY_ABSOLUTE_TOLERANCE,
            "compared_vector_count": len(parity_errors),
            "served_vector_hashes_sha256": _sha256_payload([
                row["served_reference_probability_vector_sha256"]
                for row in comparator
            ]),
            "replayed_vector_hashes_sha256": _sha256_payload([
                row["probability_vector_sha256"] for row in comparator
            ]),
        },
        "sensitivity": _sensitivity_metrics(
            "calibration:literal_current_served_transform",
            f"calibration:{selected_arm}",
        ),
    }

    stage_rows = []
    for descriptor in INCUMBENT_STAGES:
        stage_id = str(descriptor["stage_id"])
        by_type = {
            experiment_type: results[f"{experiment_type}:{stage_id}"]
            for experiment_type in REQUIRED_EXPERIMENT_TYPES
        }
        primary = by_type["remove_one"]
        brier_summaries = {
            name: _clustered_delta(
                baseline,
                values,
                "brier",
                seeds=bootstrap_seed_values,
                iterations=iterations,
            )
            for name, values in by_type.items()
        }
        log_summaries = {
            name: _clustered_delta(
                baseline,
                values,
                "log_loss",
                seeds=bootstrap_seed_values,
                iterations=iterations,
            )
            for name, values in by_type.items()
        }
        primary_brier = dict(brier_summaries["remove_one"])
        primary_log = dict(log_summaries["remove_one"])
        primary_brier["ci95_upper"] = max(row["ci95_upper"] for row in brier_summaries.values())
        primary_log["ci95_upper"] = max(row["ci95_upper"] for row in log_summaries.values())
        all_stage_results = [row for values in by_type.values() for row in values]
        stage_experiment_ids = [
            f"{experiment_type}:{stage_id}"
            for experiment_type in REQUIRED_EXPERIMENT_TYPES
        ]
        stage_receipts = [
            row["receipt_sha256"]
            for row in receipts
            if row.get("experiment_id") in stage_experiment_ids
        ]
        stage_probes = [
            probe
            for experiment_id in stage_experiment_ids
            for probe in probes[experiment_id]
        ]
        stage_rows.append({
            "stage_id": stage_id,
            "category": descriptor["category"],
            "experiment_types": sorted(REQUIRED_EXPERIMENT_TYPES),
            "paired_unit": "fleet_target_date",
            "paired_date_count": len(dates),
            "paired_dates_sha256": paired_dates_sha256,
            "evaluation_receipt_sha256": _sha256_payload({
                "stage_id": stage_id,
                "execution_receipt_sha256s": stage_receipts,
                "experiment_types": sorted(REQUIRED_EXPERIMENT_TYPES),
                "matrix_sha256": _sha256_payload(matrix),
            }),
            "delta_brier": primary_brier,
            "delta_log_loss": primary_log,
            "max_market_brier_delta": max(
                _max_market_delta(baseline, values) for values in by_type.values()
            ),
            "safety_invariants": _safety_status(all_stage_results, stage_probes),
            "sensitivity": {
                "experiment_types": {
                    name: {
                        "delta_brier": brier_summaries[name],
                        "delta_log_loss": log_summaries[name],
                    }
                    for name in sorted(REQUIRED_EXPERIMENT_TYPES)
                },
                **_sensitivity_metrics(
                    "full_stack",
                    f"remove_one:{stage_id}",
                ),
            },
        })

    all_normal_results = [row for values in results.values() for row in values]
    all_probe_results = [row for values in probes.values() for row in values]
    executable_safety = _safety_status(all_normal_results, all_probe_results)
    complete = len(dates) >= MINIMUM_PAIRED_FLEET_DATES
    complete = complete and all(
        value == "PASS"
        for value in calibration["simplex_invariants"].values()
    )
    complete = complete and all(
        all(value == "PASS" for value in row["safety_invariants"].values())
        for row in stage_rows
    )
    complete = complete and all(value == "PASS" for value in executable_safety.values())
    template_rows = [
        {"template_sha256": digest, "template": config_templates[digest]}
        for digest in sorted(config_templates)
    ]
    captured_input_sha256s = sorted({
        row["captured_input_sha256"] for row in case_contracts
    })
    evidence = {
        "schema_version": ABLATION_SCHEMA_VERSION,
        "artifact_type": "served_calibration_stage_ablation",
        "status": "PASS" if complete else "BLOCK",
        "candidate_id": str(candidate_id),
        "generated_at_utc": _iso_utc(generated_at_utc),
        "requalification_report_sha256": report_sha,
        "candidate_artifact_sha256": str(candidate_artifact_sha256),
        "independent_unit": "fleet_target_date",
        "cluster_unit": "fleet_target_date",
        "paired_date_count": len(dates),
        "paired_dates_sha256": paired_dates_sha256,
        "frozen_full_stack_id": str(frozen_full_stack_id),
        "candidate_graph_id": str(candidate_id),
        "execution_contract": {
            "case_count": len(rows),
            "experiment_count": len(matrix),
            "prediction_count": call_id,
            "normal_prediction_count": normal_call_count,
            "probe_prediction_count": probe_call_count,
            "matrix_sha256": _sha256_payload(matrix),
            "predictor_adapter": predictor_adapter,
            "captured_input_sha256s": captured_input_sha256s,
            "captured_input_hashes_sha256": _sha256_payload(
                captured_input_sha256s
            ),
            "embargo_days_evaluated": list(embargo_values),
            "evaluation_seeds": list(evaluation_seed_values),
            "experiment_config_templates": template_rows,
            "experiment_config_templates_sha256": _sha256_payload(
                template_rows
            ),
            "execution_receipts": receipts,
            "execution_receipts_sha256": _sha256_payload(receipts),
            "result_vector_hashes_sha256": _sha256_payload([
                row["probability_vector_sha256"] for row in receipts
            ]),
            "bounded_max_cases": MAX_CASES,
            "bounded_max_bootstrap_iterations": MAX_BOOTSTRAP_ITERATIONS,
            "bounded_max_execution_calls": MAX_EXECUTION_CALLS,
            "selection_from_scored_rows": False,
            "selected_calibrator_predeclared": selected_calibrator,
        },
        "executable_safety": executable_safety,
        "calibration": calibration,
        "stage_ablations": stage_rows,
    }
    return finalize_self_hash(evidence, hash_field=ABLATION_HASH_FIELD)


def write_served_stage_ablation_evidence(
    evidence: Mapping[str, Any],
    path: str | Path,
) -> Path:
    """Atomically persist a self-hashed evaluator result."""

    if evidence.get("schema_version") != ABLATION_SCHEMA_VERSION:
        raise StageAblationExecutionError("stage ablation evidence schema mismatch")
    expected = finalize_self_hash(
        {key: value for key, value in evidence.items() if key != ABLATION_HASH_FIELD},
        hash_field=ABLATION_HASH_FIELD,
    )
    if evidence.get(ABLATION_HASH_FIELD) != expected.get(ABLATION_HASH_FIELD):
        raise StageAblationExecutionError("stage ablation evidence self-hash mismatch")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(evidence), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    return output


__all__ = [name for name in globals() if not name.startswith("_")]
