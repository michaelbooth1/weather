"""Leakage-safe training and nested evaluation for ``ResidualDistributionV1``.

This module intentionally does not extend the legacy pooled density trainer.
Every learned stage is fitted inside whole-fleet-date rolling-origin folds:
the encoder/imputer/scaler and pooled Ridge residual mean, the residual width,
and the sole global simplex temperature.  Outer validation dates never
participate in arm, alpha, width, or calibration selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from weather.artifacts import (
    DEFAULT_CANDIDATE_ARTIFACT_ROOT,
    DEFAULT_IMMUTABLE_RELEASE_ROOT,
    training_artifact_output_policy,
)
from weather.calibration.simplex_calibration import (
    apply_simplex_calibrator,
    fit_global_simplex_temperature,
    score_probability_rows,
)
from weather.experiment_contract import canonical_json, finalize_self_hash
from weather.model.continuous_density import f_to_native
from weather.model.residual_distribution_v1 import (
    ARTIFACT_SCHEMA_VERSION,
    PREDICTION_MODE,
    SOURCE_STATES,
    default_feature_contract,
    gaussian_residual_density,
    project_density_to_bands,
    residual_band_key,
    truncate_at_printed_observed_high,
    validate_artifact,
)
from weather.reporting.validation.point_in_time_evaluation import (
    RollingOriginFold,
    build_fit_receipt,
    build_nested_rolling_origin_folds,
    build_rolling_origin_folds,
)


TRAINING_SCHEMA_VERSION = "residual_distribution_requalification_v0.1"
OOF_RECEIPT_SCHEMA_VERSION = "residual_distribution_oof_fit_receipt_v0.1"
FINAL_FIT_RECEIPT_SCHEMA_VERSION = "residual_distribution_final_fit_receipt_v0.1"
IMPLEMENTATION_IDENTITY = "weather.calibration.residual_distribution_v1"
DEFAULT_ALPHA_GRID = (0.25, 1.0, 4.0, 16.0)
DEFAULT_GRID_LOW_F = -40.0
DEFAULT_GRID_HIGH_F = 130.0
DEFAULT_GRID_STEP_F = 0.1
DEFAULT_SIGMA_FLOOR = 0.50
DEFAULT_SIGMA_CAP = 10.0
DEFAULT_NONINFERIORITY = 0.002


class ResidualTrainingError(ValueError):
    """The corpus or validation design cannot support a valid V1 fit."""


@dataclass(frozen=True)
class ResidualAblationSpec:
    arm_id: str
    include_observations: bool = False
    include_forecast_context: bool = False
    include_source_health: bool = False
    include_market_effects: bool = False
    deterministic_noise: bool = False
    target_permutation: bool = False
    eligible_for_selection: bool = True
    complexity: int = 1


PREDECLARED_ABLATIONS = (
    ResidualAblationSpec("anchor_only", complexity=1),
    ResidualAblationSpec(
        "anchor_observations",
        include_observations=True,
        complexity=2,
    ),
    ResidualAblationSpec(
        "anchor_source_health",
        include_forecast_context=True,
        include_source_health=True,
        complexity=3,
    ),
    ResidualAblationSpec(
        "anchor_observations_source_health",
        include_observations=True,
        include_forecast_context=True,
        include_source_health=True,
        complexity=4,
    ),
    ResidualAblationSpec(
        "anchor_observations_source_health_market",
        include_observations=True,
        include_forecast_context=True,
        include_source_health=True,
        include_market_effects=True,
        complexity=5,
    ),
    ResidualAblationSpec(
        "negative_deterministic_noise",
        include_observations=True,
        include_forecast_context=True,
        include_source_health=True,
        include_market_effects=True,
        deterministic_noise=True,
        eligible_for_selection=False,
        complexity=90,
    ),
    ResidualAblationSpec(
        "negative_whole_date_target_permutation",
        include_observations=True,
        include_forecast_context=True,
        include_source_health=True,
        include_market_effects=True,
        target_permutation=True,
        eligible_for_selection=False,
        complexity=99,
    ),
)

ANCHOR_FEATURES = (
    "forecast_high",
    "forecast_high_available",
    "forecast_high_missing",
    "cutoff_hour",
    "cutoff_hour_available",
    "cutoff_hour_missing",
)
OBSERVATION_BASE_FEATURES = (
    "high_so_far",
    "current_temp",
    "rise_from_7am",
    "warming_rate_2h",
    "hours_at_peak",
    "live_reading_temp",
    "live_reading_minus_high",
    "minutes_since_cutoff",
    "startup_feature_quarantined_flag",
)
FORECAST_CONTEXT_BASE_FEATURES = (
    "forecast_gap",
    "forecast_source_count",
    "forecast_disagreement",
    "guidance_impossible_source_count",
)


def _identity(row: Mapping[str, Any]) -> tuple[str, str, int, str]:
    return (
        str(row.get("target_date") or ""),
        str(row.get("market_id") or ""),
        int(row.get("cutoff_hour") or 0),
        str(row.get("snapshot_id") or ""),
    )


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ResidualTrainingError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ResidualTrainingError(f"{field} must be finite")
    return number


def validate_training_examples(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        raise ResidualTrainingError("at least one residual training example is required")
    output: list[dict[str, Any]] = []
    seen = set()
    feature_schemas = set()
    for raw in rows:
        row = dict(raw)
        identity = _identity(row)
        if not all(identity[:3]):
            raise ResidualTrainingError("every row requires target_date, market_id, and cutoff_hour")
        if identity in seen:
            raise ResidualTrainingError(f"duplicate residual checkpoint: {identity}")
        seen.add(identity)
        if not isinstance(row.get("features"), Mapping):
            raise ResidualTrainingError("every row requires a canonical features mapping")
        if not isinstance(row.get("market_bands"), list) or len(row["market_bands"]) < 2:
            raise ResidualTrainingError("every row requires a complete market-band partition")
        if not isinstance(row.get("winning_band"), Mapping):
            raise ResidualTrainingError("every row requires its winning market band")
        _finite(row.get("forecast_anchor_f"), "forecast_anchor_f")
        _finite(row.get("residual_target_f"), "residual_target_f")
        schema = str(row.get("feature_schema_version") or "").strip()
        if not schema:
            raise ResidualTrainingError("every row requires feature_schema_version")
        feature_schemas.add(schema)
        output.append(row)
    if len(feature_schemas) != 1:
        raise ResidualTrainingError(
            "training examples must share one feature schema: " + ", ".join(sorted(feature_schemas))
        )
    return sorted(output, key=_identity)


def hierarchical_checkpoint_weights(rows: Sequence[Mapping[str, Any]]) -> list[float]:
    """Return equal fleet-date -> market-day -> cutoff -> snapshot weights."""

    if not rows:
        return []
    by_date: dict[str, dict[str, dict[int, list[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for index, row in enumerate(rows):
        by_date[str(row.get("target_date"))][str(row.get("market_id"))][
            int(row.get("cutoff_hour"))
        ].append(index)
    date_count = len(by_date)
    weights = [0.0] * len(rows)
    for markets in by_date.values():
        market_count = len(markets)
        for cutoffs in markets.values():
            cutoff_count = len(cutoffs)
            for indexes in cutoffs.values():
                value = 1.0 / date_count / market_count / cutoff_count / len(indexes)
                for index in indexes:
                    weights[index] = value
    if not math.isclose(math.fsum(weights), 1.0, rel_tol=0.0, abs_tol=1e-12):
        raise AssertionError("hierarchical checkpoint weights do not sum to one")
    return weights


def _with_availability(base_names: Iterable[str]) -> list[str]:
    output: list[str] = []
    for name in base_names:
        output.extend((name, f"{name}_available", f"{name}_missing"))
    return output


def feature_names_for_ablation(
    spec: ResidualAblationSpec,
    contract: Mapping[str, Any],
) -> list[str]:
    generated = set(contract.get("feature_names") or [])
    selected = list(ANCHOR_FEATURES)
    if spec.include_observations:
        selected.extend(_with_availability(OBSERVATION_BASE_FEATURES))
    if spec.include_forecast_context:
        selected.extend(_with_availability(FORECAST_CONTEXT_BASE_FEATURES))
    if spec.include_source_health:
        selected.extend(name for name in generated if name.startswith("source_"))
    if spec.include_market_effects:
        selected.append("market_id")
    if spec.deterministic_noise:
        selected.append("deterministic_noise")
    return list(dict.fromkeys(name for name in selected if name in generated or name == "deterministic_noise"))


def _deterministic_noise(row: Mapping[str, Any]) -> float:
    digest = hashlib.sha256("|".join(map(str, _identity(row))).encode("utf-8")).digest()
    integer = int.from_bytes(digest[:8], "big")
    return (integer / (2**64 - 1)) * 2.0 - 1.0


def feature_frame(rows: Sequence[Mapping[str, Any]], feature_names: Sequence[str]) -> pd.DataFrame:
    records = []
    for row in rows:
        features = dict(row.get("features") or {})
        features.setdefault("market_id", row.get("market_id"))
        features["deterministic_noise"] = _deterministic_noise(row)
        records.append({name: features.get(name) for name in feature_names})
    frame = pd.DataFrame(records, columns=list(feature_names))
    for name in feature_names:
        if name != "market_id":
            frame[name] = pd.to_numeric(frame[name], errors="coerce")
    return frame


def build_residual_pipeline(feature_names: Sequence[str], alpha: float) -> Pipeline:
    names = list(feature_names)
    categorical = [name for name in names if name == "market_id"]
    numeric = [name for name in names if name not in categorical]
    transformers = []
    if numeric:
        transformers.append((
            "numeric",
            Pipeline([
                ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
                ("scale", StandardScaler()),
            ]),
            numeric,
        ))
    if categorical:
        transformers.append((
            "categorical",
            Pipeline([
                ("imputer", SimpleImputer(strategy="constant", fill_value="unknown")),
                ("one_hot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
            ]),
            categorical,
        ))
    if not transformers:
        raise ResidualTrainingError("an ablation must retain at least one feature")
    return Pipeline([
        ("preprocess", ColumnTransformer(transformers, remainder="drop")),
        ("ridge", Ridge(alpha=float(alpha), fit_intercept=True)),
    ])


def _training_targets(
    rows: Sequence[Mapping[str, Any]],
    *,
    target_permutation: bool,
) -> np.ndarray:
    values = np.asarray([_finite(row.get("residual_target_f"), "residual_target_f") for row in rows])
    if not target_permutation or len(values) <= 1:
        return values
    # Rotate complete fleet dates inside the current fit scope, retaining the
    # market/cutoff key where it exists.  This destroys the day-label link
    # without letting any validation or outer-fold label enter the fit.
    dates = sorted({str(row.get("target_date")) for row in rows})
    rotated_date = {
        current: dates[(index + 1) % len(dates)]
        for index, current in enumerate(dates)
    }
    by_key = {
        (
            str(row.get("target_date")),
            str(row.get("market_id")),
            int(row.get("cutoff_hour")),
        ): _finite(row.get("residual_target_f"), "residual_target_f")
        for row in rows
    }
    by_date = defaultdict(list)
    for (target_date, _market_id, _cutoff), value in by_key.items():
        by_date[target_date].append(value)
    date_means = {
        target_date: math.fsum(items) / len(items)
        for target_date, items in by_date.items()
    }
    return np.asarray([
        by_key.get(
            (
                rotated_date[str(row.get("target_date"))],
                str(row.get("market_id")),
                int(row.get("cutoff_hour")),
            ),
            date_means[rotated_date[str(row.get("target_date"))]],
        )
        for row in rows
    ])


def fit_fold_pipeline(
    rows: Sequence[Mapping[str, Any]],
    *,
    feature_names: Sequence[str],
    alpha: float,
    target_permutation: bool = False,
) -> Pipeline:
    if not rows:
        raise ResidualTrainingError("cannot fit a residual pipeline without rows")
    pipeline = build_residual_pipeline(feature_names, alpha)
    weights = np.asarray(hierarchical_checkpoint_weights(rows), dtype=float)
    pipeline.fit(
        feature_frame(rows, feature_names),
        _training_targets(rows, target_permutation=target_permutation),
        ridge__sample_weight=weights,
    )
    return pipeline


def predict_residual_means(
    pipeline: Pipeline,
    rows: Sequence[Mapping[str, Any]],
    feature_names: Sequence[str],
) -> list[float]:
    if not rows:
        return []
    values = pipeline.predict(feature_frame(rows, feature_names))
    return [float(value) for value in values]


def _weighted_sigma(errors: Sequence[float], weights: Sequence[float]) -> float:
    if not errors:
        raise ResidualTrainingError("OOF residual width requires prediction errors")
    weight_sum = math.fsum(weights)
    mse = math.fsum(weight * error * error for error, weight in zip(errors, weights)) / weight_sum
    return max(DEFAULT_SIGMA_FLOOR, min(DEFAULT_SIGMA_CAP, math.sqrt(mse)))


def _probability_row(
    row: Mapping[str, Any],
    predicted_residual_f: float,
    sigma_f: float,
    *,
    grid_low_f: float = DEFAULT_GRID_LOW_F,
    grid_high_f: float = DEFAULT_GRID_HIGH_F,
    grid_step_f: float = DEFAULT_GRID_STEP_F,
) -> dict[str, Any]:
    anchor_f = _finite(row.get("forecast_anchor_f"), "forecast_anchor_f")
    mean_f = anchor_f + float(predicted_residual_f)
    grid = np.arange(grid_low_f, grid_high_f + grid_step_f * 0.5, grid_step_f)
    density = gaussian_residual_density(mean_f, sigma_f, grid)
    unit = str(row.get("native_unit") or "F").upper()
    high_so_far_f = (row.get("features") or {}).get("high_so_far")
    high_so_far_native = None
    if high_so_far_f is not None:
        try:
            high_so_far_native = f_to_native(float(high_so_far_f), unit)
        except (TypeError, ValueError):
            high_so_far_native = None
    density, _floor_bucket, _threshold = truncate_at_printed_observed_high(
        density,
        printed_high_native=high_so_far_native,
        unit=unit,
    )
    probabilities = project_density_to_bands(
        density,
        unit=unit,
        band_rows=row.get("market_bands") or [],
    )
    winner_key = residual_band_key(row.get("winning_band") or {})
    if winner_key not in probabilities:
        raise ResidualTrainingError(
            f"winning band {winner_key!r} is not in the complete market partition"
        )
    return {
        "row": row,
        "probabilities": probabilities,
        "winner_key": winner_key,
        "predicted_residual_f": float(predicted_residual_f),
        "residual_error_f": _finite(row.get("residual_target_f"), "residual_target_f")
        - float(predicted_residual_f),
        "mean_f": mean_f,
    }


def _attach_probability_weights(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_rows = [item["row"] for item in rows]
    for item, weight in zip(rows, hierarchical_checkpoint_weights(source_rows)):
        item["sample_weight"] = weight
    return rows


def build_oof_fit_receipt(
    *,
    outer_fold: RollingOriginFold,
    oof_rows: Sequence[Mapping[str, Any]],
    parent_receipt_sha256s: Sequence[str],
    stage_name: str,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    oof_dates = sorted({str((item.get("row") or item).get("target_date") or "") for item in oof_rows})
    if not oof_dates or not set(oof_dates) <= set(outer_fold.train_dates):
        raise ResidualTrainingError("OOF calibration dates must be a subset of outer training dates")
    if set(oof_dates) & set(outer_fold.validation_dates):
        raise ResidualTrainingError("OOF calibration dates overlap outer validation dates")
    parents = sorted({str(value) for value in parent_receipt_sha256s if value})
    if not parents:
        raise ResidualTrainingError("OOF receipt requires parent inner-model receipts")
    hash_rows = [{
        "identity": _identity(item.get("row") or item),
        "predicted_residual_f": item.get("predicted_residual_f"),
        "residual_error_f": item.get("residual_error_f"),
        "probabilities": item.get("probabilities"),
    } for item in oof_rows]
    return finalize_self_hash({
        "schema_version": OOF_RECEIPT_SCHEMA_VERSION,
        "artifact_type": "training_oof_fit_receipt",
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "fit_role": "training_oof",
        "outer_fold_id": outer_fold.fold_id,
        "stage_name": stage_name,
        "oof_dates": oof_dates,
        "outer_train_dates": list(outer_fold.train_dates),
        "outer_validation_dates": list(outer_fold.validation_dates),
        "parent_receipt_sha256s": parents,
        "oof_row_count": len(oof_rows),
        "oof_payload_sha256": hashlib.sha256(canonical_json(hash_rows).encode("utf-8")).hexdigest(),
    }, hash_field="receipt_sha256")


def _rows_for_dates(rows: Sequence[Mapping[str, Any]], dates: Sequence[str]) -> list[dict[str, Any]]:
    allowed = set(dates)
    return [dict(row) for row in rows if str(row.get("target_date")) in allowed]


def generate_oof_predictions(
    rows: Sequence[Mapping[str, Any]],
    folds: Sequence[RollingOriginFold],
    *,
    spec: ResidualAblationSpec,
    feature_names: Sequence[str],
    alpha: float,
    fold_scope_prefix: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    oof: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for fold in folds:
        train_rows = _rows_for_dates(rows, fold.train_dates)
        validation_rows = _rows_for_dates(rows, fold.validation_dates)
        if not train_rows or not validation_rows:
            continue
        pipeline = fit_fold_pipeline(
            train_rows,
            feature_names=feature_names,
            alpha=alpha,
            target_permutation=spec.target_permutation,
        )
        predictions = predict_residual_means(pipeline, validation_rows, feature_names)
        receipt = build_fit_receipt(
            fold,
            fold_scope=f"{fold_scope_prefix}/{fold.fold_id}",
            stage_name=f"{spec.arm_id}:preprocess_and_residual_mean",
            implementation_identity=IMPLEMENTATION_IDENTITY,
            fit_rows=train_rows,
            validation_rows=validation_rows,
        )
        receipts.append(receipt)
        for row, prediction in zip(validation_rows, predictions):
            oof.append({
                "row": row,
                "predicted_residual_f": prediction,
                "residual_error_f": _finite(row.get("residual_target_f"), "residual_target_f")
                - prediction,
                "parent_receipt_sha256": receipt["receipt_sha256"],
            })
    return oof, receipts


def tune_inner_oof(
    rows: Sequence[Mapping[str, Any]],
    folds: Sequence[RollingOriginFold],
    *,
    outer_fold: RollingOriginFold,
    spec: ResidualAblationSpec,
    feature_names: Sequence[str],
    alpha_grid: Sequence[float] = DEFAULT_ALPHA_GRID,
) -> dict[str, Any]:
    candidates = []
    for alpha in alpha_grid:
        raw_oof, receipts = generate_oof_predictions(
            rows,
            folds,
            spec=spec,
            feature_names=feature_names,
            alpha=float(alpha),
            fold_scope_prefix=f"outer/{outer_fold.fold_id}/inner",
        )
        if not raw_oof:
            continue
        source_rows = [item["row"] for item in raw_oof]
        weights = hierarchical_checkpoint_weights(source_rows)
        sigma_f = _weighted_sigma(
            [float(item["residual_error_f"]) for item in raw_oof],
            weights,
        )
        probability_rows = _attach_probability_weights([
            _probability_row(item["row"], item["predicted_residual_f"], sigma_f)
            for item in raw_oof
        ])
        calibrator = fit_global_simplex_temperature(probability_rows)
        calibrated_rows = [
            {
                **item,
                "probabilities": apply_simplex_calibrator(
                    item["probabilities"], calibrator
                ),
            }
            for item in probability_rows
        ]
        score = score_probability_rows(calibrated_rows)
        oof_receipt = build_oof_fit_receipt(
            outer_fold=outer_fold,
            oof_rows=probability_rows,
            parent_receipt_sha256s=[row["receipt_sha256"] for row in receipts],
            stage_name=f"{spec.arm_id}:residual_scale_and_simplex_calibration",
        )
        candidates.append({
            "alpha": float(alpha),
            "sigma_f": sigma_f,
            "calibrator": calibrator,
            "score": score,
            "fit_receipts": receipts,
            "oof_receipt": oof_receipt,
            "oof_rows": probability_rows,
        })
    if not candidates:
        raise ResidualTrainingError(
            f"arm {spec.arm_id!r} produced no inner OOF predictions for {outer_fold.fold_id}"
        )
    selected = min(
        candidates,
        key=lambda item: (
            item["score"]["log_loss"],
            item["score"]["brier"],
            item["alpha"],
        ),
    )
    selected["candidate_scores"] = [
        {
            "alpha": item["alpha"],
            "sigma_f": item["sigma_f"],
            "temperature": item["calibrator"]["temperature"],
            **item["score"],
        }
        for item in candidates
    ]
    return selected


def _select_simplest_noninferior(
    arm_results: Sequence[Mapping[str, Any]],
    margin: float,
) -> dict[str, Any]:
    eligible = [row for row in arm_results if row["spec"].eligible_for_selection]
    if not eligible:
        raise ResidualTrainingError("nested evaluation has no selectable ablation arms")
    best = min(eligible, key=lambda row: (row["inner"]["score"]["log_loss"], row["inner"]["score"]["brier"]))
    best_score = best["inner"]["score"]
    noninferior = [
        row for row in eligible
        if row["inner"]["score"]["log_loss"] <= best_score["log_loss"] + margin
        and row["inner"]["score"]["brier"] <= best_score["brier"] + margin
    ]
    return min(noninferior, key=lambda row: (row["spec"].complexity, row["spec"].arm_id))


def _score_outer_arm(
    train_rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
    *,
    spec: ResidualAblationSpec,
    feature_names: Sequence[str],
    inner_result: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pipeline = fit_fold_pipeline(
        train_rows,
        feature_names=feature_names,
        alpha=float(inner_result["alpha"]),
        target_permutation=spec.target_permutation,
    )
    predictions = predict_residual_means(pipeline, validation_rows, feature_names)
    partitions = _attach_probability_weights([
        _probability_row(row, prediction, float(inner_result["sigma_f"]))
        for row, prediction in zip(validation_rows, predictions)
    ])
    calibrated = [
        {
            **item,
            "probabilities": apply_simplex_calibrator(
                item["probabilities"], inner_result["calibrator"]
            ),
        }
        for item in partitions
    ]
    return calibrated, score_probability_rows(calibrated)


def _aggregate_partition_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, float] | None:
    if not rows:
        return None
    copies = [dict(row) for row in rows]
    for item, weight in zip(copies, hierarchical_checkpoint_weights([item["row"] for item in copies])):
        item["sample_weight"] = weight
    return score_probability_rows(copies)


def run_nested_evaluation(
    rows: Sequence[Mapping[str, Any]],
    *,
    ablations: Sequence[ResidualAblationSpec] = PREDECLARED_ABLATIONS,
    alpha_grid: Sequence[float] = DEFAULT_ALPHA_GRID,
    outer_min_train_dates: int = 14,
    inner_min_train_dates: int = 7,
    embargo_days: int = 3,
    noninferiority_margin: float = DEFAULT_NONINFERIORITY,
) -> dict[str, Any]:
    examples = validate_training_examples(rows)
    dates = sorted({row["target_date"] for row in examples})
    nested = build_nested_rolling_origin_folds(
        dates,
        outer_min_train_dates=int(outer_min_train_dates),
        inner_min_train_dates=int(inner_min_train_dates),
        embargo_days=int(embargo_days),
    )
    usable_nested = [item for item in nested if item.inner]
    if not usable_nested:
        raise ResidualTrainingError("the corpus does not produce a nested rolling-origin fold")
    feature_schema = examples[0]["feature_schema_version"]
    contract = default_feature_contract(feature_schema)
    outer_results = []
    by_arm_partitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selected_partitions: list[dict[str, Any]] = []
    for nested_fold in usable_nested:
        outer = nested_fold.outer
        train_rows = _rows_for_dates(examples, outer.train_dates)
        validation_rows = _rows_for_dates(examples, outer.validation_dates)
        arm_results = []
        for spec in ablations:
            names = feature_names_for_ablation(spec, contract)
            inner = tune_inner_oof(
                train_rows,
                nested_fold.inner,
                outer_fold=outer,
                spec=spec,
                feature_names=names,
                alpha_grid=alpha_grid,
            )
            partitions, score = _score_outer_arm(
                train_rows,
                validation_rows,
                spec=spec,
                feature_names=names,
                inner_result=inner,
            )
            by_arm_partitions[spec.arm_id].extend(partitions)
            arm_results.append({
                "spec": spec,
                "feature_names": names,
                "inner": inner,
                "outer_partitions": partitions,
                "outer_score": score,
            })
        selected = _select_simplest_noninferior(arm_results, float(noninferiority_margin))
        selected_partitions.extend(selected["outer_partitions"])
        outer_results.append({
            "fold_id": outer.fold_id,
            "train_dates": list(outer.train_dates),
            "embargo_dates": list(outer.embargo_dates),
            "validation_dates": list(outer.validation_dates),
            "selected_arm": selected["spec"].arm_id,
            "selected_alpha": selected["inner"]["alpha"],
            "selected_sigma_f": selected["inner"]["sigma_f"],
            "selected_temperature": selected["inner"]["calibrator"]["temperature"],
            "selected_outer_score": selected["outer_score"],
            "arms": [{
                "arm_id": arm["spec"].arm_id,
                "eligible_for_selection": arm["spec"].eligible_for_selection,
                "complexity": arm["spec"].complexity,
                "feature_names": arm["feature_names"],
                "selected_alpha": arm["inner"]["alpha"],
                "inner_sigma_f": arm["inner"]["sigma_f"],
                "inner_temperature": arm["inner"]["calibrator"]["temperature"],
                "inner_score": arm["inner"]["score"],
                "outer_score": arm["outer_score"],
                "oof_receipt": arm["inner"]["oof_receipt"],
                "fit_receipts": arm["inner"]["fit_receipts"],
            } for arm in arm_results],
        })
    arm_scores = {
        arm_id: _aggregate_partition_rows(partitions)
        for arm_id, partitions in by_arm_partitions.items()
    }
    selected_score = _aggregate_partition_rows(selected_partitions)
    anchor_score = arm_scores.get("anchor_only")
    negative_scores = {
        arm_id: score
        for arm_id, score in arm_scores.items()
        if arm_id.startswith("negative_")
    }
    market_deltas = {}
    for market_id in sorted({row["market_id"] for row in examples}):
        selected_market = [item for item in selected_partitions if item["row"]["market_id"] == market_id]
        anchor_market = [item for item in by_arm_partitions.get("anchor_only", []) if item["row"]["market_id"] == market_id]
        selected_market_score = _aggregate_partition_rows(selected_market)
        anchor_market_score = _aggregate_partition_rows(anchor_market)
        if selected_market_score and anchor_market_score:
            market_deltas[market_id] = {
                "brier_delta": selected_market_score["brier"] - anchor_market_score["brier"],
                "log_loss_delta": selected_market_score["log_loss"] - anchor_market_score["log_loss"],
            }
    selected_counts = Counter(row["selected_arm"] for row in outer_results)
    criteria = {
        "minimum_outer_fleet_dates": len({date for row in outer_results for date in row["validation_dates"]}) >= 14,
        "brier_improves_anchor_by_0_002": bool(
            selected_score and anchor_score
            and selected_score["brier"] <= anchor_score["brier"] - 0.002
        ),
        "log_loss_improves_anchor_by_0_005": bool(
            selected_score and anchor_score
            and selected_score["log_loss"] <= anchor_score["log_loss"] - 0.005
        ),
        "no_market_brier_regression_over_0_01": all(
            row["brier_delta"] <= 0.01 for row in market_deltas.values()
        ),
        "negative_controls_do_not_beat_selected": all(
            score is None or selected_score is None
            or score["log_loss"] >= selected_score["log_loss"]
            for score in negative_scores.values()
        ),
    }
    return {
        "schema_version": TRAINING_SCHEMA_VERSION,
        "artifact_type": "residual_distribution_nested_requalification",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if all(criteria.values()) else "BLOCK",
        "candidate_id": PREDICTION_MODE,
        "feature_schema_version": feature_schema,
        "fold_contract": {
            "unit": "whole_fleet_target_date",
            "outer_min_train_dates": int(outer_min_train_dates),
            "inner_min_train_dates": int(inner_min_train_dates),
            "embargo_days": int(embargo_days),
            "outer_fold_count": len(outer_results),
            "outer_validation_dates": sorted({date for row in outer_results for date in row["validation_dates"]}),
        },
        "weighting_contract": "equal_fleet_date_then_market_day_then_cutoff_then_snapshot",
        "selection_contract": {
            "primary": "inner_oof_categorical_log_loss",
            "secondary": "inner_oof_categorical_brier",
            "simplest_noninferiority_margin": float(noninferiority_margin),
            "selected_arm_counts": dict(sorted(selected_counts.items())),
        },
        "selected_outer_score": selected_score,
        "anchor_outer_score": anchor_score,
        "arm_outer_scores": arm_scores,
        "market_deltas_vs_anchor": market_deltas,
        "qualification_criteria": criteria,
        "outer_results": outer_results,
    }


def _chosen_final_spec(
    evaluation: Mapping[str, Any],
    ablations: Sequence[ResidualAblationSpec],
) -> ResidualAblationSpec:
    counts = (evaluation.get("selection_contract") or {}).get("selected_arm_counts") or {}
    by_id = {spec.arm_id: spec for spec in ablations}
    eligible = [by_id[arm_id] for arm_id in counts if arm_id in by_id and by_id[arm_id].eligible_for_selection]
    if not eligible:
        raise ResidualTrainingError("nested evaluation did not select an eligible final arm")
    return min(eligible, key=lambda spec: (-int(counts[spec.arm_id]), spec.complexity, spec.arm_id))


def _observed_source_states(rows: Sequence[Mapping[str, Any]], source: str) -> list[str]:
    aliases = {
        "fresh": "fresh",
        "ok": "fresh",
        "healthy": "fresh",
        "stale": "stale",
        "stale_cache": "stale",
        "degraded": "stale",
        "failed": "failed",
        "failure": "failed",
        "error": "failed",
    }
    states = set()
    for row in rows:
        for item in row.get("source_health") or []:
            if str(item.get("source") or "") != source:
                continue
            states.add(aliases.get(str(item.get("status") or "").lower(), "unknown"))
    return sorted(states or {"unknown"})


def _safe_lineage_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "target_date": row.get("target_date"),
        "market_id": row.get("market_id"),
        "cutoff_hour": row.get("cutoff_hour"),
        "snapshot_id": row.get("snapshot_id"),
        "feature_sha256": row.get("feature_sha256"),
        "replay_input_sha256": row.get("replay_input_sha256"),
        "settlement_sha256": row.get("settlement_sha256"),
    } for row in rows]


def _final_fit_receipt(
    rows: Sequence[Mapping[str, Any]],
    *,
    locked_dates: Sequence[str],
    pipeline: Pipeline,
) -> dict[str, Any]:
    lineage_rows = _safe_lineage_rows(rows)
    train_dates = sorted({str(row.get("target_date")) for row in rows})
    locked = sorted({str(value) for value in locked_dates})
    if set(train_dates) & set(locked):
        raise ResidualTrainingError("final fit receipt overlaps the locked evaluation window")
    return finalize_self_hash({
        "schema_version": FINAL_FIT_RECEIPT_SCHEMA_VERSION,
        "artifact_type": "residual_distribution_final_fit_receipt",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fit_role": "prelock_final_refit",
        "train_dates": train_dates,
        "locked_dates": locked,
        "fit_row_count": len(rows),
        "fit_input_sha256": hashlib.sha256(
            canonical_json(lineage_rows).encode("utf-8")
        ).hexdigest(),
        "model_payload_sha256": hashlib.sha256(
            pickle.dumps(pipeline, protocol=pickle.HIGHEST_PROTOCOL)
        ).hexdigest(),
    }, hash_field="receipt_sha256")


def fit_final_candidate(
    rows: Sequence[Mapping[str, Any]],
    evaluation: Mapping[str, Any],
    *,
    candidate_id: str = PREDICTION_MODE,
    ablations: Sequence[ResidualAblationSpec] = PREDECLARED_ABLATIONS,
    alpha_grid: Sequence[float] = DEFAULT_ALPHA_GRID,
    min_train_dates: int = 7,
    embargo_days: int = 3,
    grid_low_f: float = DEFAULT_GRID_LOW_F,
    grid_high_f: float = DEFAULT_GRID_HIGH_F,
    grid_step_f: float = DEFAULT_GRID_STEP_F,
    locked_dates: Sequence[str] = (),
) -> dict[str, Any]:
    locked = {str(value) for value in locked_dates}
    examples = [
        row for row in validate_training_examples(rows)
        if str(row.get("target_date")) not in locked
    ]
    if not examples:
        raise ResidualTrainingError("no training rows remain after excluding locked dates")
    spec = _chosen_final_spec(evaluation, ablations)
    schema = examples[0]["feature_schema_version"]
    template = default_feature_contract(schema)
    feature_names = feature_names_for_ablation(spec, template)
    dates = sorted({row["target_date"] for row in examples})
    folds = build_rolling_origin_folds(
        dates,
        min_train_dates=int(min_train_dates),
        embargo_days=int(embargo_days),
    )
    if not folds:
        raise ResidualTrainingError("final OOF calibration requires at least one rolling fold")
    pseudo_outer = RollingOriginFold(
        fold_id="final_oof_scope",
        train_dates=tuple(sorted({date for fold in folds for date in fold.validation_dates})),
        embargo_dates=(),
        validation_dates=("9999-12-31",),
        embargo_days=int(embargo_days),
    )
    final_oof = tune_inner_oof(
        examples,
        folds,
        outer_fold=pseudo_outer,
        spec=spec,
        feature_names=feature_names,
        alpha_grid=alpha_grid,
    )
    pipeline = fit_fold_pipeline(
        examples,
        feature_names=feature_names,
        alpha=float(final_oof["alpha"]),
        target_permutation=False,
    )
    required_sources = list(template["source_health_policy"]["required_sources"])
    allowed_states = sorted({
        state
        for source in required_sources
        for state in _observed_source_states(examples, source)
        if state in SOURCE_STATES
    }) or ["unknown"]
    calibrator_method = (
        "identity" if math.isclose(float(final_oof["calibrator"]["temperature"]), 1.0)
        else "simplex_temperature"
    )
    lineage_rows = _safe_lineage_rows(examples)
    final_fit_receipt = _final_fit_receipt(
        examples,
        locked_dates=sorted(locked),
        pipeline=pipeline,
    )
    promotion_countable_rows = sum(
        1 for row in examples if row.get("promotion_training_countable")
    )
    qualification_status = (
        evaluation.get("status")
        if promotion_countable_rows > 0
        else "BLOCK"
    )
    artifact = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "artifact_type": "residual_distribution_model",
        "candidate_id": str(candidate_id),
        "model_version": str(candidate_id),
        "prediction_mode": PREDICTION_MODE,
        "canonical_unit": "F",
        "family_unit": "all",
        "objective": "canonical_f_point_in_time_forecast_residual_density",
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "feature_schema_version": schema,
        "feature_names": feature_names,
        "feature_contract": template["feature_contract"],
        "feature_contract_sha256": hashlib.sha256(
            canonical_json(template["feature_contract"]).encode("utf-8")
        ).hexdigest(),
        "source_health_policy": {
            "required_sources": required_sources,
            "allowed_states": allowed_states,
            "support_source": "observed_training_rows",
        },
        "pipeline": pipeline,
        "ridge_alpha": float(final_oof["alpha"]),
        "residual_sigma_f": float(final_oof["sigma_f"]),
        "grid_low_f": float(grid_low_f),
        "grid_high_f": float(grid_high_f),
        "grid_step_f": float(grid_step_f),
        "calibration": {
            "method": calibrator_method,
            "temperature": float(final_oof["calibrator"]["temperature"]),
            "fit_source": "rolling_origin_oof_complete_partitions",
            "selection": final_oof["calibrator"]["selection"],
            "oof_receipt_sha256": final_oof["oof_receipt"]["receipt_sha256"],
            "model_payload_sha256": final_fit_receipt["model_payload_sha256"],
        },
        "selected_ablation": asdict(spec),
        "missingness_policy": "preserve_null_plus_explicit_available_and_missing_indicators",
        "settlement_constraint_policy": "printed_observed_high_bucket_floor_only",
        "fallback_policy": "named_abstention_no_substitution",
        "training_lineage": {
            "corpus_sha256": hashlib.sha256(canonical_json(lineage_rows).encode("utf-8")).hexdigest(),
            "validation_plan_sha256": hashlib.sha256(canonical_json({
                "fold_contract": evaluation.get("fold_contract") or {},
                "selection_contract": evaluation.get("selection_contract") or {},
            }).encode("utf-8")).hexdigest(),
            "train_dates": dates,
            "locked_dates": sorted(locked),
            "train_rows": len(examples),
            "research_only_rows": sum(
                1 for row in examples if row.get("training_evidence_class") == "research_only"
            ),
            "promotion_training_countable_rows": promotion_countable_rows,
            "oof_receipt": final_oof["oof_receipt"],
            "fit_receipts": final_oof["fit_receipts"],
            "final_fit_receipt": final_fit_receipt,
            "nested_requalification_status": evaluation.get("status"),
        },
        "qualification": {
            "status": qualification_status,
            "criteria": {
                **(evaluation.get("qualification_criteria") or {}),
                "has_release_bound_training_evidence": promotion_countable_rows > 0,
            },
            "outer_validation_dates": (evaluation.get("fold_contract") or {}).get("outer_validation_dates") or [],
        },
    }
    return validate_artifact(artifact)


def train_residual_distribution_v1(
    rows: Sequence[Mapping[str, Any]],
    *,
    locked_dates: Sequence[str] = (),
    candidate_id: str = PREDICTION_MODE,
    **evaluation_options: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    locked = {str(value) for value in locked_dates}
    development_rows = [
        row for row in rows if str(row.get("target_date")) not in locked
    ]
    evaluation = run_nested_evaluation(development_rows, **evaluation_options)
    final_options = {
        key: evaluation_options[key]
        for key in ("ablations", "alpha_grid", "embargo_days")
        if key in evaluation_options
    }
    if "inner_min_train_dates" in evaluation_options:
        final_options["min_train_dates"] = evaluation_options["inner_min_train_dates"]
    artifact = fit_final_candidate(
        rows,
        evaluation,
        candidate_id=candidate_id,
        locked_dates=sorted(locked),
        **final_options,
    )
    return artifact, evaluation


def write_candidate_artifact(
    artifact: Mapping[str, Any],
    path: str | Path,
    *,
    candidates_root: str | Path = DEFAULT_CANDIDATE_ARTIFACT_ROOT,
    releases_root: str | Path = DEFAULT_IMMUTABLE_RELEASE_ROOT,
) -> dict[str, Any]:
    validated = validate_artifact(artifact)
    policy = training_artifact_output_policy(
        path,
        candidates_root=candidates_root,
        releases_root=releases_root,
    )
    output = Path(policy["path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = pickle.dumps(validated, protocol=pickle.HIGHEST_PROTOCOL)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, output)
    return {
        **policy,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "qualification_status": (validated.get("qualification") or {}).get("status"),
        "promotion_eligible": (
            (validated.get("qualification") or {}).get("status") == "PASS"
        ),
    }


def load_candidate_artifact(path: str | Path) -> dict[str, Any]:
    with Path(path).open("rb") as handle:
        artifact = pickle.load(handle)
    return validate_artifact(artifact)


def load_training_corpus_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ResidualTrainingError(
                    f"{path}:{line_number} contains invalid JSON"
                ) from exc
            if not isinstance(row, dict):
                raise ResidualTrainingError(f"{path}:{line_number} must be a JSON object")
            rows.append(row)
    return validate_training_examples(rows)


def write_evaluation_report(report: Mapping[str, Any], path: str | Path) -> Path:
    def json_safe(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(item) for item in value]
        if isinstance(value, (float, np.floating)) and not math.isfinite(float(value)):
            return None
        if isinstance(value, np.generic):
            return value.item()
        return value

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(json_safe(report), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, output)
    return output


def _read_locked_dates(path: str | Path | None) -> list[str]:
    if not path:
        return []
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [line.strip() for line in text.splitlines() if line.strip()]
    if isinstance(payload, list):
        return [str(value) for value in payload]
    if isinstance(payload, dict):
        return [str(value) for value in payload.get("target_dates") or payload.get("locked_dates") or []]
    raise ResidualTrainingError("locked-date file must be a JSON list/object or one date per line")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train the shadow-only ResidualDistributionV1 candidate from a PIT JSONL corpus."
    )
    parser.add_argument("--corpus", required=True)
    parser.add_argument(
        "--artifact",
        default=str(DEFAULT_CANDIDATE_ARTIFACT_ROOT / "residual_distribution_v1" / "model.pkl"),
    )
    parser.add_argument(
        "--report",
        default="data/backtest/residual_distribution_v1_requalification.json",
    )
    parser.add_argument("--candidate-id", default=PREDICTION_MODE)
    parser.add_argument("--locked-dates-file", default="")
    parser.add_argument("--outer-min-train-dates", type=int, default=14)
    parser.add_argument("--inner-min-train-dates", type=int, default=7)
    parser.add_argument("--embargo-days", type=int, choices=range(3, 8), default=3)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    rows = load_training_corpus_jsonl(args.corpus)
    locked_dates = _read_locked_dates(args.locked_dates_file)
    artifact, report = train_residual_distribution_v1(
        rows,
        candidate_id=args.candidate_id,
        locked_dates=locked_dates,
        outer_min_train_dates=args.outer_min_train_dates,
        inner_min_train_dates=args.inner_min_train_dates,
        embargo_days=args.embargo_days,
    )
    artifact_result = write_candidate_artifact(artifact, args.artifact)
    report = {
        **report,
        "candidate_artifact": artifact_result,
        "locked_dates": locked_dates,
    }
    report_path = write_evaluation_report(report, args.report)
    print(
        f"ResidualDistributionV1: status={report['status']} "
        f"rows={len(rows)} artifact={artifact_result['path']} report={report_path}"
    )


__all__ = [name for name in globals() if not name.startswith("_")]


if __name__ == "__main__":
    main()
