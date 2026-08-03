"""Candidate-only per-market base-model fitting.

This module intentionally has no default paths and no CLI.  The operational
owner supplies verified, candidate-local destinations after all preflight
gates pass.  In particular, this code never calls the legacy ``feature_model``
CLI, whose output contract includes global ``artifacts/`` and ``data/`` paths.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from weather.calibration.feature_model import (
    FEATURE_MODEL_COEFS_SCHEMA_VERSION,
    FEATURE_MODEL_HGB_SCHEMA_VERSION,
    feature_model_frame,
    smoothed_dist,
)
from weather.calibration.feature_probability_calibration import (
    blend_distribution,
    fit_temperature_blend_grid,
    temperature_scale_distribution,
)
from weather.model.feature_store import FEATURE_SCHEMA_VERSION, NATIVE_NAN_FEATURE_COLUMNS
from weather.release_artifacts import sha256_file
from weather.schema_registry import schema_version


FIT_RECEIPT_SCHEMA_VERSION = schema_version("all_market_base_retrain_fit_receipt")
PROBABILITY_CALIBRATION_VERSION = schema_version(
    "all_market_base_retrain_probability_calibration"
)
LR_PARAMETERS = {"C": 0.5, "max_iter": 1000, "random_state": 42}


class BaseModelCandidateFitError(RuntimeError):
    """A market candidate cannot be fitted under the frozen parent contract."""


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finalize(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["payload_sha256"] = _canonical_sha256(result)
    return result


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise BaseModelCandidateFitError(
            f"immutable candidate output already exists: {path}"
        ) from exc


def _write_pickle_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            pickle.dump(dict(payload), handle)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise BaseModelCandidateFitError(
            f"immutable candidate output already exists: {path}"
        ) from exc


def read_hash_bound_records(path: str | Path, *, expected_sha256: str) -> list[dict[str, Any]]:
    """Read a frozen JSONL feature corpus after verifying its exact identity."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise BaseModelCandidateFitError(f"feature-record corpus is missing: {source}")
    if sha256_file(source) != str(expected_sha256):
        raise BaseModelCandidateFitError(
            f"feature-record corpus hash mismatch: {source}"
        )
    rows: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BaseModelCandidateFitError(
                    f"invalid JSONL feature record at {source}:{line_number}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise BaseModelCandidateFitError(
                    f"feature record must be an object at {source}:{line_number}"
                )
            rows.append(row)
    if not rows:
        raise BaseModelCandidateFitError(f"feature-record corpus is empty: {source}")
    if sha256_file(source) != str(expected_sha256):
        raise BaseModelCandidateFitError(
            f"feature-record corpus changed while it was read: {source}"
        )
    return rows


def contiguous_serving_support(
    labels: Sequence[int | float],
    forecast_highs: Sequence[int | float],
    *,
    unit: str,
) -> list[int]:
    """Return the predeclared native support, independent of estimator classes."""

    label_values = [int(value) for value in labels if value is not None]
    forecast_values = [float(value) for value in forecast_highs if value is not None]
    if not label_values:
        raise BaseModelCandidateFitError("serving support requires training labels")
    margin = 2 if str(unit).upper() == "C" else 4 if str(unit).upper() == "F" else None
    if margin is None:
        raise BaseModelCandidateFitError(f"unsupported native unit: {unit!r}")
    lower = min(label_values)
    upper_basis = max(
        max(label_values),
        math.ceil(max(forecast_values)) if forecast_values else max(label_values),
    )
    return list(range(lower, upper_basis + margin + 1))


def _validation_groups(records: Sequence[Mapping[str, Any]]) -> list[list[int]]:
    parsed_dates = [date.fromisoformat(str(row["target_date"])) for row in records]
    years = sorted({value.year for value in parsed_dates})
    if len(years) >= 2:
        groups = [
            [index for index, value in enumerate(parsed_dates) if value.year == year]
            for year in years
        ]
    else:
        groups = [
            [index for index, value in enumerate(parsed_dates) if value == target]
            for target in sorted(set(parsed_dates))
        ]
    return [group for group in groups if group]


def _fit_hgb(params: Mapping[str, Any], matrix: np.ndarray, labels: pd.Series):
    allowed = HistGradientBoostingClassifier().get_params()
    frozen = {key: value for key, value in dict(params).items() if key in allowed}
    model = HistGradientBoostingClassifier(**frozen)
    model.fit(matrix, labels)
    return model


def _fit_market_hour(
    records: Sequence[Mapping[str, Any]],
    *,
    feature_names: Sequence[str],
    all_wind_groups: Sequence[str],
    all_cloud_groups: Sequence[str],
    hgb_parameters: Mapping[str, Any],
    numeric_feature_count: int,
    unit: str,
) -> dict[str, Any]:
    frame, _current_feature_names = feature_model_frame(
        records,
        list(all_wind_groups),
        list(all_cloud_groups),
    )
    names = [str(value) for value in feature_names]
    missing_columns = [name for name in names if name not in frame]
    if missing_columns:
        raise BaseModelCandidateFitError(
            f"frozen parent features are absent from the corpus: {missing_columns}"
        )
    matrix_frame = frame[names].copy()
    labels = frame["final_bucket"].astype(int)
    if len(set(labels)) < 2:
        raise BaseModelCandidateFitError("base fitting requires at least two label classes")
    native_nan_indices = [
        names.index(name) for name in NATIVE_NAN_FEATURE_COLUMNS if name in names
    ]
    oof_rows: list[tuple[dict[int, float], dict[int, float], int]] = []
    fold_receipts: list[dict[str, Any]] = []
    for validation_indices in _validation_groups(records):
        validation = set(validation_indices)
        training_indices = [index for index in range(len(records)) if index not in validation]
        if not training_indices or len(set(labels.iloc[training_indices])) < 2:
            continue
        train_frame = matrix_frame.iloc[training_indices]
        validation_frame = matrix_frame.iloc[validation_indices]
        imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        train_matrix = imputer.fit_transform(train_frame)
        validation_matrix = imputer.transform(validation_frame)
        if native_nan_indices:
            train_matrix[:, native_nan_indices] = train_frame.iloc[
                :, native_nan_indices
            ].to_numpy(dtype=float)
            validation_matrix[:, native_nan_indices] = validation_frame.iloc[
                :, native_nan_indices
            ].to_numpy(dtype=float)
        model = _fit_hgb(hgb_parameters, train_matrix, labels.iloc[training_indices])
        fold_labels = [int(labels.iloc[index]) for index in training_indices]
        fold_forecasts = [
            records[index].get("forecast_high") for index in training_indices
        ]
        support = contiguous_serving_support(fold_labels, fold_forecasts, unit=unit)
        prior = smoothed_dist(fold_labels, support, alpha=0.10)
        predicted = model.predict_proba(validation_matrix)
        for offset, validation_index in enumerate(validation_indices):
            raw = {
                int(bucket): float(probability)
                for bucket, probability in zip(model.classes_, predicted[offset])
            }
            oof_rows.append((prior, raw, int(labels.iloc[validation_index])))
        fold_receipts.append(
            {
                "validation_dates": sorted(
                    {str(records[index]["target_date"]) for index in validation_indices}
                ),
                "training_row_count": len(training_indices),
                "validation_row_count": len(validation_indices),
                "serving_support": support,
                "observed_model_classes": [int(value) for value in model.classes_],
            }
        )
    if not oof_rows:
        raise BaseModelCandidateFitError(
            "no blocked OOF rows were available for candidate calibration"
        )
    calibration = fit_temperature_blend_grid(
        oof_rows,
        blend_weights=[0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.97],
    )
    served_oof_rows = [
        (
            {},
            blend_distribution(
                prior,
                temperature_scale_distribution(raw, calibration["temperature"]),
                calibration["blend_weight"],
            ),
            actual,
        )
        for prior, raw, actual in oof_rows
    ]
    exact_calibration = fit_temperature_blend_grid(
        served_oof_rows,
        blend_weights=[1.0],
    )

    final_imputer = SimpleImputer(strategy="median", keep_empty_features=True)
    final_imputed = final_imputer.fit_transform(matrix_frame)
    final_hgb_matrix = final_imputed.copy()
    if native_nan_indices:
        final_hgb_matrix[:, native_nan_indices] = matrix_frame.iloc[
            :, native_nan_indices
        ].to_numpy(dtype=float)
    final_hgb = _fit_hgb(hgb_parameters, final_hgb_matrix, labels)

    scaler = StandardScaler()
    final_lr_matrix = final_imputed.copy()
    numeric_feature_count = int(numeric_feature_count)
    if numeric_feature_count <= 0 or numeric_feature_count > len(names):
        raise BaseModelCandidateFitError("parent LR numeric feature count is invalid")
    final_lr_matrix[:, :numeric_feature_count] = scaler.fit_transform(
        final_imputed[:, :numeric_feature_count]
    )
    final_lr = LogisticRegression(**LR_PARAMETERS)
    final_lr.fit(final_lr_matrix, labels)

    label_values = [int(value) for value in labels]
    forecast_values = [row.get("forecast_high") for row in records]
    support = contiguous_serving_support(label_values, forecast_values, unit=unit)
    prior = smoothed_dist(label_values, support, alpha=0.10)
    return {
        "hgb": final_hgb,
        "lr": final_lr,
        "imputer": final_imputer,
        "scaler": scaler,
        "numeric_feature_count": numeric_feature_count,
        "feature_names": names,
        "all_wind_groups": list(all_wind_groups),
        "all_cloud_groups": list(all_cloud_groups),
        "hgb_parameters": dict(hgb_parameters),
        "serving_support": support,
        "target_date_aligned_prior": {str(key): value for key, value in prior.items()},
        "probability_temperature": float(calibration["temperature"]),
        "exact_probability_temperature": float(exact_calibration["temperature"]),
        "blend_weight": float(calibration["blend_weight"]),
        "folds": fold_receipts,
        "row_count": len(records),
        "label_counts": {
            str(key): int(value) for key, value in sorted(Counter(label_values).items())
        },
    }


def fit_market_candidate(
    *,
    market_id: str,
    unit: str,
    target_date: str,
    parent_release_id: str,
    training_as_of: str,
    feature_contract_id: str,
    runtime_id: str,
    corpus_manifest_sha256: str,
    pit_forecast_corpus_manifest_sha256: str,
    pit_forecast_preflight_sha256: str,
    records: Sequence[Mapping[str, Any]],
    parent_hgb: Mapping[str, Any],
    parent_lr: Mapping[str, Any],
    hgb_path: str | Path,
    lr_path: str | Path,
    probability_calibration_path: str | Path,
    receipt_path: str | Path,
    report_path: str | Path,
) -> dict[str, Any]:
    """Fit one market and publish only the five supplied immutable outputs."""

    by_hour: dict[str, list[Mapping[str, Any]]] = {}
    for row in records:
        hour = str(int(row["cutoff_hour"]))
        by_hour.setdefault(hour, []).append(row)
    parent_hours = sorted(key for key in parent_hgb if str(key).isdigit())
    if sorted(by_hour) != parent_hours:
        raise BaseModelCandidateFitError(
            f"corpus/parent cutoff hours differ for {market_id}: "
            f"corpus={sorted(by_hour)}, parent={parent_hours}"
        )

    hgb_output: dict[str, Any] = {
        "schema_version": FEATURE_MODEL_HGB_SCHEMA_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "trained_at": training_as_of,
        "target_date": target_date,
        "parent_release_id": parent_release_id,
        "feature_contract_id": feature_contract_id,
        "runtime_id": runtime_id,
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "pit_forecast_corpus_manifest_sha256": (
            pit_forecast_corpus_manifest_sha256
        ),
        "pit_forecast_preflight_sha256": pit_forecast_preflight_sha256,
        "market_id": market_id,
        "unit": unit,
    }
    lr_output: dict[str, Any] = {
        "schema_version": FEATURE_MODEL_COEFS_SCHEMA_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "trained_at": training_as_of,
        "target_date": target_date,
        "parent_release_id": parent_release_id,
        "feature_contract_id": feature_contract_id,
        "runtime_id": runtime_id,
        "corpus_manifest_sha256": corpus_manifest_sha256,
        "pit_forecast_corpus_manifest_sha256": (
            pit_forecast_corpus_manifest_sha256
        ),
        "pit_forecast_preflight_sha256": pit_forecast_preflight_sha256,
        "market_id": market_id,
        "unit": unit,
    }
    temperature_by_hour: dict[str, float] = {}
    hour_receipts: dict[str, Any] = {}
    for hour in parent_hours:
        parent_hour = parent_hgb.get(hour)
        parent_lr_hour = parent_lr.get(hour)
        if not isinstance(parent_hour, Mapping) or not isinstance(parent_lr_hour, Mapping):
            raise BaseModelCandidateFitError(
                f"parent HGB/LR contract is incomplete for {market_id} hour {hour}"
            )
        parent_model = parent_hour.get("model")
        if not isinstance(parent_model, HistGradientBoostingClassifier):
            raise BaseModelCandidateFitError(
                f"parent HGB estimator is incompatible for {market_id} hour {hour}"
            )
        names = [str(value) for value in parent_hour.get("feature_names") or []]
        if names != [str(value) for value in parent_lr_hour.get("feature_names") or []]:
            raise BaseModelCandidateFitError(
                f"parent HGB/LR feature order differs for {market_id} hour {hour}"
            )
        fitted = _fit_market_hour(
            by_hour[hour],
            feature_names=names,
            all_wind_groups=parent_hour.get("all_wind_groups") or [],
            all_cloud_groups=parent_hour.get("all_cloud_groups") or [],
            hgb_parameters=parent_model.get_params(),
            numeric_feature_count=len(parent_lr_hour.get("scaler_mean") or []),
            unit=unit,
        )
        hgb_output[hour] = {
            "model": fitted["hgb"],
            "imputer": fitted["imputer"],
            "feature_schema_version": parent_hour.get("feature_schema_version"),
            "feature_names": fitted["feature_names"],
            "all_wind_groups": fitted["all_wind_groups"],
            "all_cloud_groups": fitted["all_cloud_groups"],
            "blend_weight": fitted["blend_weight"],
            "probability_temperature": fitted["probability_temperature"],
            "probability_calibration": {
                "method": "temperature",
                "temperature": fitted["probability_temperature"],
            },
            "target_date_aligned_prior": fitted["target_date_aligned_prior"],
            "serving_support": fitted["serving_support"],
            "ordinal_smoothing": dict(
                parent_hour.get("ordinal_smoothing")
                or {"enabled": False, "source": "parent_contract"}
            ),
        }
        lr_model = fitted["lr"]
        numeric_count = fitted["numeric_feature_count"]
        lr_output[hour] = {
            "feature_schema_version": parent_lr_hour.get("feature_schema_version"),
            "feature_names": fitted["feature_names"],
            "classes": [int(value) for value in lr_model.classes_],
            "coef": lr_model.coef_.tolist(),
            "intercept": lr_model.intercept_.tolist(),
            "scaler_mean": fitted["scaler"].mean_[:numeric_count].tolist(),
            "scaler_scale": fitted["scaler"].scale_[:numeric_count].tolist(),
            "imputer_median": fitted["imputer"].statistics_.tolist(),
            "blend_weight": fitted["blend_weight"],
            "target_date_aligned_prior": fitted["target_date_aligned_prior"],
            "serving_support": fitted["serving_support"],
            "ordinal_smoothing": dict(
                parent_lr_hour.get("ordinal_smoothing")
                or {"enabled": False, "source": "parent_contract"}
            ),
        }
        hour_receipts[hour] = {
            "row_count": fitted["row_count"],
            "label_counts": fitted["label_counts"],
            "observed_hgb_classes": [int(value) for value in fitted["hgb"].classes_],
            "observed_lr_classes": [int(value) for value in fitted["lr"].classes_],
            "serving_support": fitted["serving_support"],
            "feature_names": fitted["feature_names"],
            "feature_names_sha256": hashlib.sha256(
                "\n".join(fitted["feature_names"]).encode("utf-8")
            ).hexdigest(),
            "blocked_oof_folds": fitted["folds"],
            "parent_hgb_parameters": fitted["hgb_parameters"],
            "probability_temperature": fitted["probability_temperature"],
            "exact_probability_temperature": fitted[
                "exact_probability_temperature"
            ],
            "blend_weight": fitted["blend_weight"],
        }
        temperature_by_hour[hour] = fitted["exact_probability_temperature"]

    calibration = _finalize(
        {
            "schema_version": PROBABILITY_CALIBRATION_VERSION,
            "version": PROBABILITY_CALIBRATION_VERSION,
            "generated_at_utc": training_as_of,
            "market_id": market_id,
            "unit": unit,
            "target_date": target_date,
            "parent_release_id": parent_release_id,
            "feature_contract_id": feature_contract_id,
            "runtime_id": runtime_id,
            "corpus_manifest_sha256": corpus_manifest_sha256,
            "pit_forecast_corpus_manifest_sha256": (
                pit_forecast_corpus_manifest_sha256
            ),
            "pit_forecast_preflight_sha256": pit_forecast_preflight_sha256,
            "exact_distribution": {
                "enabled": True,
                "method": "temperature",
                "temperature": 1.0,
                "temperature_by_hour": temperature_by_hour,
                "prior_weight": 0.0,
                "fit_scope": "candidate_blocked_oof",
            },
            "market_bin": {
                "enabled": False,
                "preserve_distribution_coherence": True,
                "reason": "base-retrain has no candidate market-bin scoring scope",
            },
        }
    )
    receipt = _finalize(
        {
            "schema_version": FIT_RECEIPT_SCHEMA_VERSION,
            "status": "PASS",
            "market_id": market_id,
            "unit": unit,
            "target_date": target_date,
            "parent_release_id": parent_release_id,
            "training_as_of": training_as_of,
            "feature_contract_id": feature_contract_id,
            "runtime_id": runtime_id,
            "corpus_manifest_sha256": corpus_manifest_sha256,
            "pit_forecast_corpus_manifest_sha256": (
                pit_forecast_corpus_manifest_sha256
            ),
            "pit_forecast_preflight_sha256": pit_forecast_preflight_sha256,
            "statistical_change": "target_date_aligned_prior_and_contiguous_support",
            "parent_hgb_parameters_frozen": True,
            "parent_lr_parameters": LR_PARAMETERS,
            "hours": hour_receipts,
        }
    )
    report_lines = [
        f"# Base-model candidate fit: {market_id}",
        "",
        f"- Unit: `{unit}`",
        f"- Target date: `{target_date}`",
        f"- Training as-of: `{training_as_of}`",
        f"- Feature contract: `{feature_contract_id}`",
        f"- Runtime ID: `{runtime_id}`",
        f"- Cutoff hours: {', '.join(parent_hours)}",
        "- Output scope: immutable candidate only",
        "",
    ]

    _write_pickle_exclusive(Path(hgb_path), hgb_output)
    _write_json_exclusive(Path(lr_path), lr_output)
    _write_json_exclusive(Path(probability_calibration_path), calibration)
    _write_json_exclusive(Path(receipt_path), receipt)
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    try:
        with report.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(report_lines))
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise BaseModelCandidateFitError(
            f"immutable candidate output already exists: {report}"
        ) from exc

    outputs = {
        "feature_hgb": Path(hgb_path),
        "feature_lr_coefficients": Path(lr_path),
        "probability_calibration": Path(probability_calibration_path),
        "fit_receipt": Path(receipt_path),
        "fit_report": report,
    }
    return {
        "status": "PASS",
        "market_id": market_id,
        "unit": unit,
        "outputs": {
            role: {
                "path": str(path),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
            for role, path in outputs.items()
        },
        "hours": hour_receipts,
    }
