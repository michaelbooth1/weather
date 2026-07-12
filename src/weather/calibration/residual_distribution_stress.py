"""Bounded E5/E6/E7 stress evaluation for ``ResidualDistributionV1``.

The evaluator is intentionally side-effect free by default.  It scores a
bounded caller-supplied casebook through the pure V1 runtime, runs predeclared
negative controls and metamorphic checks, and returns a self-hashed JSON-ready
report.  A caller must explicitly provide ``output_path`` to write anything.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from weather.experiment_contract import (
    canonical_json,
    finalize_self_hash,
    verify_self_hash,
)
from weather.model.residual_distribution_v1 import (
    canonical_candidate_features,
    predict_residual_distribution_v1,
    residual_band_key,
    validate_artifact,
)
from weather.units import round_half_up


SCHEMA_VERSION = "residual_distribution_stress_evaluation_v1"
DEFAULT_SEEDS = (11, 23, 37, 53, 71)
MAX_CASES = 250
MAX_MONTE_CARLO_DRAWS = 500
PROBABILITY_TOLERANCE = 1e-10
FORBIDDEN_FEATURE_TOKENS = (
    "settlement",
    "winning_band",
    "outcome",
    "final_bucket",
    "final_high",
    "label_proxy",
    "hashed_label",
    "market_yes",
    "market_no",
    "edge",
)


class ResidualStressError(ValueError):
    """The requested stress run is malformed or exceeds its bounded budget."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def _parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _control(status: str, *, criteria: Mapping[str, Any], **evidence: Any) -> dict[str, Any]:
    if status not in {"PASS", "BLOCK", "INCONCLUSIVE"}:
        raise ValueError(f"unsupported stress-control status {status!r}")
    return {
        "status": status,
        "criteria": _json_safe(criteria),
        **_json_safe(evidence),
    }


def _case_id(case: Mapping[str, Any], index: int) -> str:
    return str(case.get("case_id") or case.get("snapshot_id") or f"case-{index:04d}")


def _bands(case: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = case.get("band_rows") or case.get("market_bands") or []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _diagnostics(case: Mapping[str, Any]) -> Any:
    value = case.get("source_diagnostics")
    if value is None:
        value = case.get("source_health")
    return copy.deepcopy(value)


def _feature_vector(case: Mapping[str, Any]) -> dict[str, Any]:
    value = case.get("feature_vector")
    if value is None:
        value = case.get("features")
    return copy.deepcopy(dict(value or {}))


def _predict(artifact: Mapping[str, Any], case: Mapping[str, Any], **overrides: Any) -> dict[str, Any]:
    return predict_residual_distribution_v1(
        artifact=artifact,
        feature_vector=overrides.get("feature_vector", _feature_vector(case)),
        source_diagnostics=overrides.get("source_diagnostics", _diagnostics(case)),
        market_id=str(overrides.get("market_id", case.get("market_id") or "")),
        unit=overrides.get("unit", case.get("unit") or case.get("native_unit")),
        band_rows=overrides.get("band_rows", _bands(case)),
    )


def _band_parts(band: Mapping[str, Any]) -> tuple[str, float | None, float | None]:
    kind = str(band.get("bin_kind") or band.get("kind") or "eq").lower()
    raw_value = band.get("bin_value_c", band.get("value", band.get("bin_value")))
    raw_hi = band.get("bin_value_hi_c", band.get("value_hi", band.get("bin_value_hi")))
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = None
    try:
        value_hi = float(raw_hi) if raw_hi not in (None, "") else value
    except (TypeError, ValueError):
        value_hi = None
    return kind, value, value_hi


def _winning_band_key(case: Mapping[str, Any], bucket: Any = None) -> str | None:
    if bucket is None:
        bucket = case.get("settlement_bucket")
    try:
        bucket = int(float(bucket))
    except (TypeError, ValueError):
        return None
    winners = []
    for band in _bands(case):
        kind, value, value_hi = _band_parts(band)
        if value is None:
            continue
        won = (
            bucket <= value
            if kind == "lte"
            else bucket >= value
            if kind == "gte"
            else value <= bucket <= (value if value_hi is None else value_hi)
        )
        if won:
            winners.append(residual_band_key(band))
    return winners[0] if len(winners) == 1 else None


def _logloss(probabilities: Mapping[str, float], winner: str) -> float:
    probability = max(1e-15, min(1.0, float(probabilities.get(winner, 0.0))))
    return -math.log(probability)


def _brier(probabilities: Mapping[str, float], winner: str) -> float:
    return sum(
        (float(probability) - (1.0 if key == winner else 0.0)) ** 2
        for key, probability in probabilities.items()
    )


def _same_probabilities(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    if set(left) != set(right):
        return False
    return all(
        math.isclose(float(left[key]), float(right[key]), rel_tol=0.0, abs_tol=PROBABILITY_TOLERANCE)
        for key in left
    )


def _l1(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    return sum(abs(float(left.get(key, 0.0)) - float(right.get(key, 0.0))) for key in set(left) | set(right))


def _score_base(artifact: Mapping[str, Any], cases: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = []
    terminals = defaultdict(int)
    blockers = []
    for index, case in enumerate(cases):
        result = _predict(artifact, case)
        status = str(result.get("status") or "unknown")
        terminals[status] += 1
        winner = _winning_band_key(case)
        if status == "failed":
            blockers.append({
                "case_id": _case_id(case, index),
                "reason": result.get("failure_reason"),
                "detail": result.get("failure_detail"),
            })
        if status != "predicted" or winner is None:
            continue
        probabilities = dict(result.get("probabilities") or {})
        if winner not in probabilities:
            blockers.append({"case_id": _case_id(case, index), "reason": "winning_band_not_scored"})
            continue
        rows.append({
            "case_index": index,
            "case_id": _case_id(case, index),
            "target_date": str(case.get("target_date") or ""),
            "market_id": str(case.get("market_id") or ""),
            "cutoff_hour": case.get("cutoff_hour") or _feature_vector(case).get("cutoff_hour"),
            "band_signature": canonical_json(_json_safe(_bands(case))),
            "winner": winner,
            "probabilities": probabilities,
            "logloss": _logloss(probabilities, winner),
            "brier": _brier(probabilities, winner),
            "result": result,
        })
    status = "BLOCK" if blockers else "PASS" if rows else "INCONCLUSIVE"
    return _control(
        status,
        criteria={
            "PASS": "at least one settlement-scored prediction and no runtime failures",
            "BLOCK": "any base-case runtime failure or missing winning-band probability",
            "INCONCLUSIVE": "no settlement-scored predicted rows",
        },
        case_count=len(cases),
        scored_case_count=len(rows),
        terminal_status_counts=dict(sorted(terminals.items())),
        mean_logloss=float(np.mean([row["logloss"] for row in rows])) if rows else None,
        mean_brier=float(np.mean([row["brier"] for row in rows])) if rows else None,
        blockers=blockers,
    ), rows


def _sentinel_control(
    artifact: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    base_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    declared = set(artifact.get("feature_names") or []) | set(
        (artifact.get("feature_contract") or {}).get("features") or {}
    )
    declared_forbidden = sorted(
        name for name in declared
        if any(token in str(name).lower() for token in FORBIDDEN_FEATURE_TOKENS)
    )
    observed_forbidden = []
    future_timestamps = []
    malformed_timestamps = []
    for index, case in enumerate(cases):
        case_id = _case_id(case, index)
        observed_forbidden.extend(
            {"case_id": case_id, "field": name}
            for name in _feature_vector(case)
            if any(token in str(name).lower() for token in FORBIDDEN_FEATURE_TOKENS)
        )
        captured = _parse_timestamp(case.get("captured_at") or case.get("captured_at_utc"))
        for name, raw in dict(case.get("provider_timestamps") or {}).items():
            parsed = _parse_timestamp(raw)
            if parsed is None:
                malformed_timestamps.append({"case_id": case_id, "field": name, "value": raw})
            elif captured is not None and parsed > captured:
                future_timestamps.append({
                    "case_id": case_id,
                    "field": name,
                    "provider_timestamp": parsed.isoformat(),
                    "captured_at": captured.isoformat(),
                })

    placebo_mismatches = []
    for row in base_rows[:25]:
        case = cases[row["case_index"]]
        injected = _feature_vector(case)
        injected.update({
            "settlement_bucket": case.get("settlement_bucket", 999),
            "winning_band": row["winner"],
            "hashed_label_proxy": "future-label-proxy",
            "future_observation_timestamp": "2999-01-01T00:00:00+00:00",
        })
        result = _predict(artifact, case, feature_vector=injected)
        if result.get("status") != "predicted" or not _same_probabilities(
            row["probabilities"], result.get("probabilities") or {}
        ):
            placebo_mismatches.append(row["case_id"])
    blockers = bool(
        declared_forbidden
        or observed_forbidden
        or future_timestamps
        or malformed_timestamps
        or placebo_mismatches
    )
    return _control(
        "BLOCK" if blockers else "PASS",
        criteria={
            "PASS": "no forbidden declared/observed features, no provider time after capture, and injected future/label sentinels are prediction-invariant",
            "BLOCK": "any forbidden feature, malformed/future provider time, or sentinel changes a prediction",
        },
        declared_forbidden_features=declared_forbidden,
        observed_forbidden_features=observed_forbidden,
        malformed_provider_timestamps=malformed_timestamps,
        future_provider_timestamps=future_timestamps,
        injected_sentinel_mismatch_case_ids=placebo_mismatches,
    )


def _date_permutation_control(
    base_rows: Sequence[Mapping[str, Any]],
    seeds: Sequence[int],
    improvement_tolerance: float,
) -> dict[str, Any]:
    grouped: dict[tuple[str, Any, str], dict[str, list[Mapping[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in base_rows:
        signature = (row["market_id"], row["cutoff_hour"], row["band_signature"])
        grouped[signature][row["target_date"]].append(row)
    eligible = {
        signature: blocks
        for signature, blocks in grouped.items()
        if len(blocks) >= 2 and all(date for date in blocks)
    }
    eligible_rows = sum(len(rows) for blocks in eligible.values() for rows in blocks.values())
    if eligible_rows < 4:
        return _control(
            "INCONCLUSIVE",
            criteria={"minimum_eligible_rows": 4, "seed_count": 5},
            eligible_rows=eligible_rows,
            reason="fewer than four rows across date-permutable matched groups",
        )
    baseline = float(np.mean([
        row["logloss"]
        for blocks in eligible.values()
        for rows in blocks.values()
        for row in rows
    ]))
    seed_rows = []
    for seed in seeds:
        rng = random.Random(int(seed))
        losses = []
        for blocks in eligible.values():
            target_dates = sorted(blocks)
            source_dates = list(target_dates)
            rng.shuffle(source_dates)
            if source_dates == target_dates and len(source_dates) > 1:
                source_dates = source_dates[1:] + source_dates[:1]
            for target_date, source_date in zip(target_dates, source_dates):
                targets = sorted(blocks[target_date], key=lambda row: row["case_id"])
                outcomes = sorted(blocks[source_date], key=lambda row: row["case_id"])
                for offset, target in enumerate(targets):
                    winner = outcomes[offset % len(outcomes)]["winner"]
                    if winner in target["probabilities"]:
                        losses.append(_logloss(target["probabilities"], winner))
        seed_rows.append({
            "seed": int(seed),
            "logloss": float(np.mean(losses)) if losses else None,
            "n": len(losses),
        })
    valid = [row for row in seed_rows if row["logloss"] is not None]
    mean_permuted = float(np.mean([row["logloss"] for row in valid])) if valid else None
    improvement = baseline - mean_permuted if mean_permuted is not None else None
    improved_seed_count = sum(
        baseline - row["logloss"] > improvement_tolerance for row in valid
    )
    status = (
        "INCONCLUSIVE"
        if len(valid) != len(seeds)
        else "BLOCK"
        if improvement is not None
        and (improvement > improvement_tolerance or improved_seed_count >= 2)
        else "PASS"
    )
    return _control(
        status,
        criteria={
            "seed_count": 5,
            "PASS": "mean permuted log loss does not improve by more than tolerance and fewer than two seeds improve beyond tolerance",
            "BLOCK": "permuted outcomes improve mean score beyond tolerance or do so in at least two seeds",
            "improvement_tolerance": improvement_tolerance,
        },
        baseline_logloss=baseline,
        mean_permuted_logloss=mean_permuted,
        apparent_improvement=improvement,
        improved_seed_count=improved_seed_count,
        eligible_rows=eligible_rows,
        seeds=seed_rows,
    )


def _noise_control(
    artifact: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    base_rows: Sequence[Mapping[str, Any]],
    seeds: Sequence[int],
    improvement_tolerance: float,
) -> dict[str, Any]:
    if len(base_rows) < 4:
        return _control(
            "INCONCLUSIVE",
            criteria={"minimum_scored_rows": 4, "seed_count": 5},
            scored_rows=len(base_rows),
        )
    specs = (artifact.get("feature_contract") or {}).get("features") or {}
    baseline = float(np.mean([row["logloss"] for row in base_rows]))
    seed_rows = []
    for seed in seeds:
        rng = random.Random(int(seed))
        losses = []
        failures = []
        for row in base_rows:
            case = cases[row["case_index"]]
            features = _feature_vector(case)
            for name, kind in specs.items():
                raw = features.get(name)
                if kind == "categorical" or raw in (None, "") or isinstance(raw, bool):
                    continue
                try:
                    number = float(raw)
                except (TypeError, ValueError):
                    continue
                scale = 0.5 if kind == "absolute_temperature" else 0.25 if kind == "temperature_delta" else 0.05 * (abs(number) + 1.0)
                features[name] = number + rng.gauss(0.0, scale)
            result = _predict(artifact, case, feature_vector=features)
            if result.get("status") != "predicted":
                failures.append(row["case_id"])
                continue
            losses.append(_logloss(result["probabilities"], row["winner"]))
        seed_rows.append({
            "seed": int(seed),
            "logloss": float(np.mean(losses)) if losses else None,
            "n": len(losses),
            "failed_case_ids": failures,
        })
    valid = [row for row in seed_rows if row["logloss"] is not None and not row["failed_case_ids"]]
    mean_noisy = float(np.mean([row["logloss"] for row in valid])) if valid else None
    improvement = baseline - mean_noisy if mean_noisy is not None else None
    improved_seed_count = sum(
        baseline - row["logloss"] > improvement_tolerance for row in valid
    )
    status = (
        "INCONCLUSIVE"
        if len(valid) != len(seeds)
        else "BLOCK"
        if improvement is not None
        and (improvement > improvement_tolerance or improved_seed_count >= 2)
        else "PASS"
    )
    return _control(
        status,
        criteria={
            "seed_count": 5,
            "PASS": "deterministic noise does not improve mean score beyond tolerance in aggregate or at least two seeds",
            "BLOCK": "noise behaves like a useful signal beyond tolerance",
            "improvement_tolerance": improvement_tolerance,
        },
        baseline_logloss=baseline,
        mean_noisy_logloss=mean_noisy,
        apparent_improvement=improvement,
        improved_seed_count=improved_seed_count,
        seeds=seed_rows,
    )


def _market_copy_control(
    artifact: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    base_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    mismatches = []
    tested = 0
    for row in base_rows:
        case = cases[row["case_index"]]
        market = dict(case.get("market_probabilities") or {})
        if not market:
            market = {key: probability for key, probability in row["probabilities"].items()}
        features = _feature_vector(case)
        features.update({
            "market_yes": max(market.values()) if market else 0.5,
            "market_no": 1.0 - max(market.values()) if market else 0.5,
            "market_copy_distribution": market,
            "edge": 0.99,
        })
        result = _predict(artifact, case, feature_vector=features)
        tested += 1
        if result.get("status") != "predicted" or not _same_probabilities(
            row["probabilities"], result.get("probabilities") or {}
        ):
            mismatches.append(row["case_id"])
    return _control(
        "PASS" if tested and not mismatches else "BLOCK" if mismatches else "INCONCLUSIVE",
        criteria={
            "PASS": "injected market copy fields are undeclared and prediction-invariant",
            "BLOCK": "market copy fields change any prediction",
        },
        tested_case_count=tested,
        mismatch_case_ids=mismatches,
    )


def _expected_source_terminal(result: Mapping[str, Any], allowed: bool) -> bool:
    if allowed:
        return result.get("status") == "predicted"
    return (
        result.get("status") == "skipped"
        and result.get("failure_reason") == "abstain_source_state"
    )


def _provider_fault_control(
    artifact: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    base_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    required = list((artifact.get("source_health_policy") or {}).get("required_sources") or [])
    allowed = set((artifact.get("source_health_policy") or {}).get("allowed_states") or [])
    if not required or not base_rows:
        return _control(
            "INCONCLUSIVE",
            criteria={"required_sources": "at least one", "base_prediction": "required"},
            required_sources=required,
        )
    representative = cases[base_rows[0]["case_index"]]
    baseline_probabilities = base_rows[0]["probabilities"]
    fresh = [
        {"source": source, "status": "fresh", "age_minutes": 1.0, "ttl_minutes": 60.0}
        for source in required
    ]
    checks = []
    for source in required:
        diagnostics = copy.deepcopy(fresh)
        next(row for row in diagnostics if row["source"] == source)["status"] = "failed"
        result = _predict(artifact, representative, source_diagnostics=diagnostics)
        checks.append({
            "case": f"single_outage:{source}",
            "status": "PASS" if _expected_source_terminal(result, "failed" in allowed) else "BLOCK",
            "terminal": result.get("status"),
            "reason": result.get("failure_reason"),
        })

    correlated = [{**row, "status": "failed"} for row in fresh]
    result = _predict(artifact, representative, source_diagnostics=correlated)
    checks.append({
        "case": "correlated_outage",
        "status": "PASS" if _expected_source_terminal(result, "failed" in allowed) else "BLOCK",
        "terminal": result.get("status"),
        "reason": result.get("failure_reason"),
    })

    stale = [{**row, "status": "stale", "age_minutes": 120.0} for row in fresh]
    result = _predict(artifact, representative, source_diagnostics=stale)
    stale_ok = _expected_source_terminal(result, "stale" in allowed)
    checks.append({
        "case": "stale_diagnostics",
        "status": "PASS" if stale_ok else "BLOCK",
        "terminal": result.get("status"),
        "reason": result.get("failure_reason"),
    })

    delayed = [{**row, "status": "fresh", "age_minutes": 600.0, "ttl_minutes": 60.0} for row in fresh]
    result = _predict(artifact, representative, source_diagnostics=delayed)
    delayed_probabilities = result.get("probabilities") or {}
    delayed_safe = (
        result.get("status") == "skipped"
        and result.get("failure_reason") == "abstain_source_state"
    ) or (
        result.get("status") == "predicted"
        and not _same_probabilities(baseline_probabilities, delayed_probabilities)
        and max(delayed_probabilities.values()) <= max(baseline_probabilities.values()) + PROBABILITY_TOLERANCE
    )
    checks.append({
        "case": "delayed_fresh_beyond_ttl",
        "status": "PASS" if delayed_safe else "BLOCK",
        "terminal": result.get("status"),
        "reason": result.get("failure_reason"),
        "detail": "must abstain or explicitly change-and-not-sharpen the distribution",
    })

    result = _predict(artifact, representative, source_diagnostics="malformed")
    checks.append({
        "case": "malformed_diagnostics",
        "status": "PASS" if _expected_source_terminal(result, False) else "BLOCK",
        "terminal": result.get("status"),
        "reason": result.get("failure_reason"),
    })
    partial = fresh[:-1]
    result = _predict(artifact, representative, source_diagnostics=partial)
    checks.append({
        "case": "partial_required_diagnostics",
        "status": "PASS" if _expected_source_terminal(result, "unknown" in allowed) else "BLOCK",
        "terminal": result.get("status"),
        "reason": result.get("failure_reason"),
    })
    return _control(
        "BLOCK" if any(row["status"] == "BLOCK" for row in checks) else "PASS",
        criteria={
            "PASS": "single/correlated/stale/malformed/partial states obey the artifact policy; delayed-fresh input abstains or changes without sharpening",
            "BLOCK": "any provider fault fails open, crashes, or silently preserves/sharpens a beyond-TTL prediction",
        },
        required_sources=required,
        allowed_states=sorted(allowed),
        checks=checks,
    )


def _convert_feature_units(
    features: Mapping[str, Any],
    specs: Mapping[str, str],
    source_unit: str,
    target_unit: str,
) -> dict[str, Any]:
    output = copy.deepcopy(dict(features))
    for name, kind in specs.items():
        raw = output.get(name)
        if raw in (None, "") or kind not in {"absolute_temperature", "temperature_delta"}:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if source_unit == target_unit:
            converted = value
        elif source_unit == "C" and target_unit == "F":
            converted = value * 9.0 / 5.0 + (32.0 if kind == "absolute_temperature" else 0.0)
        elif source_unit == "F" and target_unit == "C":
            converted = (value - (32.0 if kind == "absolute_temperature" else 0.0)) * 5.0 / 9.0
        else:
            continue
        output[name] = converted
    output["unit"] = target_unit
    output["display_unit"] = target_unit
    return output


def _canonical_rows_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if set(left) != set(right):
        return False
    for key in left:
        a, b = left[key], right[key]
        if isinstance(a, float) and isinstance(b, float):
            if math.isnan(a) and math.isnan(b):
                continue
            if not math.isclose(a, b, rel_tol=0.0, abs_tol=1e-9):
                return False
        elif a != b:
            return False
    return True


def _metamorphic_control(
    artifact: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    base_rows: Sequence[Mapping[str, Any]],
    max_clock_skew_l1: float,
) -> dict[str, Any]:
    if not base_rows:
        return _control("INCONCLUSIVE", criteria={"base_prediction": "required"})
    checks = []
    base_by_id = {row["case_id"]: row for row in base_rows}
    reversed_rows = list(reversed(base_rows))
    cadence_ok = all(
        _same_probabilities(
            row["probabilities"],
            _predict(artifact, cases[row["case_index"]]).get("probabilities") or {},
        )
        for row in reversed_rows
    )
    downsampled = base_rows[::2]
    downsample_ok = all(
        _same_probabilities(
            base_by_id[row["case_id"]]["probabilities"],
            _predict(artifact, cases[row["case_index"]]).get("probabilities") or {},
        )
        for row in downsampled
    )
    checks.extend([
        {"case": "cadence_reorder_duplicate", "status": "PASS" if cadence_ok else "BLOCK"},
        {"case": "downsampling_retained_rows", "status": "PASS" if downsample_ok else "BLOCK"},
    ])

    representative_row = base_rows[0]
    representative = cases[representative_row["case_index"]]
    reversed_bands = list(reversed(_bands(representative)))
    reordered = _predict(artifact, representative, band_rows=reversed_bands)
    reorder_ok = reordered.get("status") == "predicted" and _same_probabilities(
        representative_row["probabilities"], reordered.get("probabilities") or {}
    )
    checks.append({"case": "band_order_invariance", "status": "PASS" if reorder_ok else "BLOCK"})

    malformed_bands = copy.deepcopy(_bands(representative))
    if malformed_bands:
        malformed_bands[0]["bin_kind"] = "eq"
        malformed_bands[0]["kind"] = "eq"
    malformed = _predict(artifact, representative, band_rows=malformed_bands)
    malformed_ok = (
        malformed.get("status") == "failed"
        and malformed.get("failure_reason") == "invalid_band_partition"
    )
    checks.append({"case": "malformed_band_partition", "status": "PASS" if malformed_ok else "BLOCK"})

    expected_unit = str(representative.get("unit") or representative.get("native_unit") or "").upper()
    wrong_unit = "F" if expected_unit == "C" else "C"
    mismatched = _predict(artifact, representative, unit=wrong_unit)
    unit_mismatch_ok = (
        mismatched.get("status") == "skipped"
        and mismatched.get("failure_reason") == "abstain_unit_mismatch"
    )
    checks.append({"case": "unit_mismatch_abstention", "status": "PASS" if unit_mismatch_ok else "BLOCK"})

    specs = (artifact.get("feature_contract") or {}).get("features") or {}
    try:
        original_canonical = canonical_candidate_features(
            artifact=artifact,
            feature_vector=_feature_vector(representative),
            source_diagnostics=_diagnostics(representative),
            market_id=str(representative.get("market_id") or ""),
            unit=expected_unit,
        )
        converted_features = _convert_feature_units(
            _feature_vector(representative), specs, expected_unit, wrong_unit
        )
        converted_canonical = canonical_candidate_features(
            artifact=artifact,
            feature_vector=converted_features,
            source_diagnostics=_diagnostics(representative),
            market_id=str(representative.get("market_id") or ""),
            unit=wrong_unit,
        )
        unit_conversion_ok = _canonical_rows_equal(original_canonical, converted_canonical)
    except Exception:  # contained as a failed metamorphic check
        unit_conversion_ok = False
    checks.append({"case": "canonical_unit_conversion", "status": "PASS" if unit_conversion_ok else "BLOCK"})

    clock_features = _feature_vector(representative)
    clock_value = clock_features.get("minutes_since_cutoff")
    if clock_value in (None, ""):
        checks.append({"case": "clock_skew_plus_minus_5m", "status": "INCONCLUSIVE"})
    else:
        clock_l1 = []
        for delta in (-5.0, 5.0):
            shifted = copy.deepcopy(clock_features)
            shifted["minutes_since_cutoff"] = float(clock_value) + delta
            result = _predict(artifact, representative, feature_vector=shifted)
            if result.get("status") != "predicted":
                clock_l1.append(float("inf"))
            else:
                clock_l1.append(_l1(representative_row["probabilities"], result["probabilities"]))
        clock_ok = max(clock_l1) <= max_clock_skew_l1
        checks.append({
            "case": "clock_skew_plus_minus_5m",
            "status": "PASS" if clock_ok else "BLOCK",
            "l1_distances": clock_l1,
            "maximum_l1": max_clock_skew_l1,
        })

    captured = _parse_timestamp(representative.get("captured_at") or representative.get("captured_at_utc"))
    if captured is None:
        checks.append({"case": "timezone_equivalent_instant", "status": "INCONCLUSIVE"})
    else:
        shifted_text = captured.astimezone(timezone(timedelta(hours=9))).isoformat()
        timezone_ok = _parse_timestamp(shifted_text) == captured
        checks.append({
            "case": "timezone_equivalent_instant",
            "status": "PASS" if timezone_ok else "BLOCK",
            "equivalent_timestamp": shifted_text,
        })

    status = "BLOCK" if any(row["status"] == "BLOCK" for row in checks) else "PASS"
    return _control(
        status,
        criteria={
            "PASS": "reorder/downsample and band order are invariant; malformed bands and units fail closed; canonical C/F conversion agrees; clock skew stays within L1 bound",
            "BLOCK": "any required metamorphic property fails",
            "clock_skew_max_l1": max_clock_skew_l1,
            "timezone_without_timestamp": "reported INCONCLUSIVE without blocking other metamorphic checks",
        },
        checks=checks,
    )


def _rounding_control(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = []
    blockers = []
    for index, case in enumerate(cases):
        high = case.get("settlement_high")
        if high in (None, ""):
            continue
        try:
            high = float(high)
        except (TypeError, ValueError):
            blockers.append({"case_id": _case_id(case, index), "reason": "non_numeric_high"})
            continue
        rounded = round_half_up(high)
        declared = case.get("settlement_bucket")
        if declared not in (None, "") and int(float(declared)) != rounded:
            blockers.append({
                "case_id": _case_id(case, index),
                "settlement_high": high,
                "declared_bucket": declared,
                "round_half_up_bucket": rounded,
            })
        lower = math.floor(high)
        rows.append({
            "case_id": _case_id(case, index),
            "settlement_high": high,
            "rounded_bucket": rounded,
            "boundary_probe": {
                "below_half": round_half_up(lower + 0.5 - 1e-9),
                "at_half": round_half_up(lower + 0.5),
                "above_half": round_half_up(lower + 0.5 + 1e-9),
            },
        })
    return _control(
        "BLOCK" if blockers else "PASS" if rows else "INCONCLUSIVE",
        criteria={
            "PASS": "declared settlement bucket equals half-up rounding and boundary probes are recorded",
            "BLOCK": "non-numeric high or declared bucket disagrees with half-up rounding",
            "INCONCLUSIVE": "no raw settlement_high values",
        },
        evaluated_case_count=len(rows),
        rows=rows,
        blockers=blockers,
    )


def _revision_monte_carlo_control(
    cases: Sequence[Mapping[str, Any]],
    base_rows: Sequence[Mapping[str, Any]],
    seeds: Sequence[int],
    draws: int,
    max_logloss_spread: float,
) -> dict[str, Any]:
    base_by_index = {row["case_index"]: row for row in base_rows}
    eligible = []
    blockers = []
    for index, case in enumerate(cases):
        revisions = case.get("settlement_revision_buckets") or []
        if not revisions or index not in base_by_index:
            continue
        normalized = []
        for value in revisions:
            try:
                bucket = int(float(value))
            except (TypeError, ValueError):
                blockers.append({"case_id": _case_id(case, index), "reason": "invalid_revision_bucket"})
                continue
            winner = _winning_band_key(case, bucket)
            if winner is None or winner not in base_by_index[index]["probabilities"]:
                blockers.append({
                    "case_id": _case_id(case, index),
                    "reason": "revision_bucket_not_uniquely_mapped",
                    "bucket": bucket,
                })
                continue
            normalized.append((bucket, winner))
        if normalized:
            eligible.append((index, normalized))
    if blockers:
        return _control(
            "BLOCK",
            criteria={"BLOCK": "any revision bucket is malformed or does not map to exactly one market band"},
            blockers=blockers,
        )
    if not eligible:
        return _control(
            "INCONCLUSIVE",
            criteria={"INCONCLUSIVE": "no settlement_revision_buckets on scored cases"},
            eligible_case_count=0,
        )
    seed_rows = []
    for seed in seeds:
        rng = random.Random(int(seed))
        losses = []
        briers = []
        for _ in range(draws):
            for index, revisions in eligible:
                _bucket, winner = revisions[rng.randrange(len(revisions))]
                probabilities = base_by_index[index]["probabilities"]
                losses.append(_logloss(probabilities, winner))
                briers.append(_brier(probabilities, winner))
        seed_rows.append({
            "seed": int(seed),
            "mean_logloss": float(np.mean(losses)),
            "mean_brier": float(np.mean(briers)),
            "drawn_outcomes": len(losses),
        })
    logloss_spread = max(row["mean_logloss"] for row in seed_rows) - min(
        row["mean_logloss"] for row in seed_rows
    )
    return _control(
        "PASS" if logloss_spread <= max_logloss_spread else "BLOCK",
        criteria={
            "PASS": "five-seed Monte Carlo completes and seed mean-logloss spread stays within bound",
            "BLOCK": "revision mapping fails or Monte Carlo sensitivity exceeds bound",
            "maximum_seed_mean_logloss_spread": max_logloss_spread,
            "draws_per_seed": draws,
        },
        eligible_case_count=len(eligible),
        seed_mean_logloss_spread=logloss_spread,
        seeds=seed_rows,
    )


def _regime_tags(case: Mapping[str, Any], winner: str | None) -> set[str]:
    tags = {str(tag) for tag in case.get("regime_tags") or [] if str(tag)}
    if case.get("rare_regime"):
        tags.add("rare_regime")
    for band in _bands(case):
        if residual_band_key(band) == winner and _band_parts(band)[0] in {"lte", "gte"}:
            tags.add("tail_outcome")
    high = case.get("settlement_high")
    try:
        fraction = abs(float(high) - math.floor(float(high)))
        if abs(fraction - 0.5) <= 0.05:
            tags.add("rounding_boundary")
    except (TypeError, ValueError):
        pass
    diagnostics = _diagnostics(case)
    if isinstance(diagnostics, Sequence) and not isinstance(diagnostics, (str, bytes)):
        if any(
            isinstance(row, Mapping)
            and str(row.get("status") or "").lower() not in {"fresh", "ok", "healthy"}
            for row in diagnostics
        ):
            tags.add("source_degraded")
    return tags


def _rare_regime_control(
    cases: Sequence[Mapping[str, Any]],
    base_rows: Sequence[Mapping[str, Any]],
    min_cases: int,
    max_excess_logloss: float,
) -> dict[str, Any]:
    by_tag = defaultdict(list)
    for row in base_rows:
        for tag in _regime_tags(cases[row["case_index"]], row["winner"]):
            by_tag[tag].append(row)
    eligible = {tag: rows for tag, rows in by_tag.items() if len(rows) >= min_cases}
    if not eligible:
        return _control(
            "INCONCLUSIVE",
            criteria={"minimum_cases_per_slice": min_cases},
            observed_slice_counts={tag: len(rows) for tag, rows in sorted(by_tag.items())},
        )
    overall = float(np.mean([row["logloss"] for row in base_rows]))
    slices = []
    for tag, rows in sorted(eligible.items()):
        mean_loss = float(np.mean([row["logloss"] for row in rows]))
        slices.append({
            "regime": tag,
            "n": len(rows),
            "mean_logloss": mean_loss,
            "mean_brier": float(np.mean([row["brier"] for row in rows])),
            "excess_logloss_vs_all": mean_loss - overall,
        })
    blockers = [row for row in slices if row["excess_logloss_vs_all"] > max_excess_logloss]
    return _control(
        "BLOCK" if blockers else "PASS",
        criteria={
            "PASS": "every sufficiently populated rare-regime slice is finite and within excess-logloss bound",
            "BLOCK": "any slice exceeds the declared bound",
            "minimum_cases_per_slice": min_cases,
            "maximum_excess_logloss_vs_all": max_excess_logloss,
        },
        overall_logloss=overall,
        slices=slices,
        blocking_slices=blockers,
    )


def write_stress_report(report: Mapping[str, Any], path: str | Path) -> Path:
    """Explicitly persist a previously self-hashed report."""

    verify_self_hash(report, hash_field="report_sha256")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def evaluate_residual_distribution_stress(
    *,
    artifact: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    seeds: Sequence[int] = DEFAULT_SEEDS,
    monte_carlo_draws: int = 100,
    negative_control_improvement_tolerance: float = 0.02,
    max_clock_skew_l1: float = 0.50,
    max_revision_logloss_spread: float = 0.50,
    rare_regime_min_cases: int = 2,
    rare_regime_max_excess_logloss: float = 1.00,
    candidate_id: str | None = None,
    candidate_artifact_sha256: str | None = None,
    requalification_report_sha256: str | None = None,
    generated_at_utc: str | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the bounded E5/E6/E7 evaluator and return a self-hashed report."""

    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise ResidualStressError("cases must be a sequence of mappings")
    if not cases or len(cases) > MAX_CASES:
        raise ResidualStressError(f"cases must contain between 1 and {MAX_CASES} rows")
    if any(not isinstance(case, Mapping) for case in cases):
        raise ResidualStressError("every case must be a mapping")
    ids = [_case_id(case, index) for index, case in enumerate(cases)]
    if len(set(ids)) != len(ids):
        raise ResidualStressError("case ids must be unique")
    seeds = tuple(int(seed) for seed in seeds)
    if len(seeds) != 5 or len(set(seeds)) != 5:
        raise ResidualStressError("exactly five unique seeds are required")
    draws = int(monte_carlo_draws)
    if draws <= 0 or draws > MAX_MONTE_CARLO_DRAWS:
        raise ResidualStressError(
            f"monte_carlo_draws must be between 1 and {MAX_MONTE_CARLO_DRAWS}"
        )
    try:
        normalized_artifact = validate_artifact(artifact)
        artifact_control = _control(
            "PASS",
            criteria={"PASS": "artifact satisfies the strict V1 runtime contract"},
            schema_version=normalized_artifact.get("schema_version"),
            model_version=normalized_artifact.get("model_version"),
        )
    except Exception as exc:
        normalized_artifact = dict(artifact or {})
        if not isinstance(normalized_artifact.get("feature_names"), (list, tuple)):
            normalized_artifact["feature_names"] = []
        if not isinstance(normalized_artifact.get("feature_contract"), Mapping):
            normalized_artifact["feature_contract"] = {"features": {}, "required": []}
        if not isinstance(normalized_artifact.get("source_health_policy"), Mapping):
            normalized_artifact["source_health_policy"] = {
                "required_sources": [],
                "allowed_states": [],
            }
        artifact_control = _control(
            "BLOCK",
            criteria={"BLOCK": "artifact fails strict V1 validation"},
            error=f"{type(exc).__name__}: {exc}",
        )

    base_control, base_rows = _score_base(normalized_artifact, cases)
    controls = {
        "artifact_contract": artifact_control,
        "base_case_scoring": base_control,
        "e5_forbidden_future_label_sentinels": _sentinel_control(
            normalized_artifact, cases, base_rows
        ),
        "e5_grouped_date_permutation": _date_permutation_control(
            base_rows, seeds, float(negative_control_improvement_tolerance)
        ),
        "e5_deterministic_noise": _noise_control(
            normalized_artifact,
            cases,
            base_rows,
            seeds,
            float(negative_control_improvement_tolerance),
        ),
        "e5_market_copy_placebo": _market_copy_control(
            normalized_artifact, cases, base_rows
        ),
        "e6_provider_fault_matrix": _provider_fault_control(
            normalized_artifact, cases, base_rows
        ),
        "e6_cadence_time_unit_band_metamorphic": _metamorphic_control(
            normalized_artifact,
            cases,
            base_rows,
            float(max_clock_skew_l1),
        ),
        "e7_settlement_rounding": _rounding_control(cases),
        "e7_settlement_revision_monte_carlo": _revision_monte_carlo_control(
            cases,
            base_rows,
            seeds,
            draws,
            float(max_revision_logloss_spread),
        ),
        "e7_rare_regime_slices": _rare_regime_control(
            cases,
            base_rows,
            int(rare_regime_min_cases),
            float(rare_regime_max_excess_logloss),
        ),
    }
    required = (
        "artifact_contract",
        "base_case_scoring",
        "e5_forbidden_future_label_sentinels",
        "e5_grouped_date_permutation",
        "e5_deterministic_noise",
        "e5_market_copy_placebo",
        "e6_provider_fault_matrix",
        "e6_cadence_time_unit_band_metamorphic",
    )
    all_statuses = {name: row["status"] for name, row in controls.items()}
    status = (
        "BLOCK"
        if any(value == "BLOCK" for value in all_statuses.values())
        else "INCONCLUSIVE"
        if any(controls[name]["status"] == "INCONCLUSIVE" for name in required)
        else "PASS"
    )
    generated = generated_at_utc or datetime.now(timezone.utc).isoformat()
    parsed_generated = _parse_timestamp(generated)
    if parsed_generated is None:
        raise ResidualStressError("generated_at_utc must be a timezone-aware ISO timestamp")
    input_payload = _json_safe([dict(case) for case in cases])
    normalized_candidate = str(
        candidate_id
        or normalized_artifact.get("candidate_id")
        or normalized_artifact.get("model_version")
        or ""
    ).strip()
    artifact_sha = str(candidate_artifact_sha256 or "").strip().lower()
    requalification_sha = str(requalification_report_sha256 or "").strip().lower()
    for field_name, value in (
        ("candidate_artifact_sha256", artifact_sha),
        ("requalification_report_sha256", requalification_sha),
    ):
        if value and (
            len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ResidualStressError(f"{field_name} must be a SHA-256 hex digest")
    report = finalize_self_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": parsed_generated.isoformat(),
            "status": status,
            "candidate_id": normalized_candidate,
            "candidate_artifact_sha256": artifact_sha,
            "requalification_report_sha256": requalification_sha,
            "criteria": {
                "PASS": "all required controls pass and no optional control blocks",
                "BLOCK": "any required or optional control blocks",
                "INCONCLUSIVE": "no controls block, but at least one required control lacks sufficient evidence",
                "required_controls": list(required),
                "optional_data_dependent_controls": [
                    "e7_settlement_rounding",
                    "e7_settlement_revision_monte_carlo",
                    "e7_rare_regime_slices",
                ],
                "maximum_cases": MAX_CASES,
                "seeds": list(seeds),
                "monte_carlo_draws_per_seed": draws,
            },
            "input": {
                "case_count": len(cases),
                "casebook_sha256": hashlib.sha256(
                    canonical_json(input_payload).encode("utf-8")
                ).hexdigest(),
                "artifact_schema_version": normalized_artifact.get("schema_version"),
                "artifact_model_version": normalized_artifact.get("model_version"),
            },
            "control_statuses": all_statuses,
            "controls": controls,
        },
        hash_field="report_sha256",
    )
    if output_path is not None:
        write_stress_report(report, output_path)
    return report


__all__ = [
    "DEFAULT_SEEDS",
    "MAX_CASES",
    "MAX_MONTE_CARLO_DRAWS",
    "ResidualStressError",
    "SCHEMA_VERSION",
    "evaluate_residual_distribution_stress",
    "write_stress_report",
]
