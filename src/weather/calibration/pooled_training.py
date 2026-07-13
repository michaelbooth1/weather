"""Implementation slice extracted from src/weather/calibration/pooled_feature_model.py."""

import hashlib
import json
import math
import pickle
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from weather.calibration.pooled_band_training import *  # noqa: F403
from weather.model.corpus_lineage import build_pooled_corpus_lineage
from weather.schema_registry import schema_version

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

POOLED_PIT_REQUIRED_STAGES = (
    "feature_selection",
    "scaling_imputation",
    "model",
    "calibration",
    "postprocessing",
    "regime_router",
)
POOLED_PIT_STAGE_IMPLEMENTATIONS = {
    "feature_selection": (
        "weather.calibration.pooled_feature_assembly.build_band_rows+"
        "weather.model.variant_prediction_runtime.band_feature_frame"
    ),
    "scaling_imputation": "sklearn.impute._base.SimpleImputer",
    "model": (
        "weather.calibration.pooled_band_training.train_band_hour_model+"
        "sklearn.ensemble._hist_gradient_boosting.gradient_boosting."
        "HistGradientBoostingClassifier"
    ),
    "calibration": (
        "weather.model.variant_prediction_runtime.temperature_scale_probability"
    ),
    "postprocessing": (
        "weather.model.variant_prediction_runtime.apply_band_postprocessing"
    ),
    "regime_router": (
        "weather.model.variant_prediction_runtime.pooled_band_regime_route"
    ),
}
POOLED_PIT_MAX_FOLD_SCOPES = 128
POOLED_PIT_MIN_STEP_DATES = 7
POOLED_PIT_MAX_MARKET_DAYS = 60
POOLED_PIT_MAX_LATEST_TARGET_AGE_DAYS = 7
POOLED_PIT_MAX_TRAINING_SOURCE_ROWS_PER_MARKET_DAY = 1_000
POOLED_PIT_MAX_NORMALIZED_TRAINING_SOURCE_ROWS = (
    POOLED_PIT_MAX_MARKET_DAYS
    * POOLED_PIT_MAX_TRAINING_SOURCE_ROWS_PER_MARKET_DAY
)
POOLED_PIT_STATIC_CONTEXT_FIELDS = (
    "climate_normal",
    "climate_std",
    *SOURCE_RELIABILITY_COLUMNS,
)
POOLED_PIT_EXTERNAL_SIDECAR_FIELDS = tuple(sorted({
    *REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
    *MARINE_WATER_CONTRAST_COLUMNS,
}))
POOLED_PIT_FIT_RECEIPT_SCHEMA_VERSION = schema_version(
    "point_in_time_fit_receipt"
)
POOLED_PIT_PRESELECTION_SCHEMA_VERSION = schema_version(
    "production_point_in_time_preselection"
)
POOLED_PIT_TRAINING_SCHEMA_VERSION = schema_version(
    "pooled_band_point_in_time_training"
)
POOLED_PIT_FINAL_REFIT_SCHEMA_VERSION = schema_version(
    "pooled_band_final_refit_receipt"
)
POOLED_NESTED_POSTPROCESS_SCHEMA_VERSION = schema_version(
    "pooled_nested_postprocess_fit_contract"
)
_POOLED_PIT_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _pooled_pit_jsonable(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _pooled_pit_jsonable(item)
            for key, item in value.items()
        }
    if isinstance(value, set):
        values = [_pooled_pit_jsonable(item) for item in value]
        return sorted(values, key=_pooled_pit_canonical_json)
    if isinstance(value, (list, tuple)):
        return [_pooled_pit_jsonable(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _pooled_pit_jsonable(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "tolist"):
        return _pooled_pit_jsonable(value.tolist())
    return str(value)


def _pooled_pit_canonical_json(value):
    return json.dumps(
        _pooled_pit_jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _pooled_pit_sha256(value):
    return hashlib.sha256(
        _pooled_pit_canonical_json(value).encode("utf-8")
    ).hexdigest()


def _pooled_pit_stable_object_state(value, _seen=None):
    """Return a pickle-round-trip-stable contract for fitted sklearn state."""

    if _seen is None:
        _seen = set()
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return {"float": "nan"}
        if math.isinf(value):
            return {"float": "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _pooled_pit_stable_object_state(value.item(), _seen)
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            return {
                "ndarray_dtype": value.dtype.descr,
                "ndarray_shape": list(value.shape),
                "ndarray_values": _pooled_pit_stable_object_state(
                    value.tolist(), _seen
                ),
            }
        contiguous = np.ascontiguousarray(value)
        return {
            "ndarray_dtype": value.dtype.descr
            if value.dtype.names
            else value.dtype.str,
            "ndarray_shape": list(value.shape),
            "ndarray_sha256": hashlib.sha256(
                contiguous.tobytes(order="C")
            ).hexdigest(),
        }
    if isinstance(value, np.dtype):
        return {"numpy_dtype": value.descr if value.names else value.str}
    if isinstance(value, Mapping):
        return {
            str(key): _pooled_pit_stable_object_state(item, _seen)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [
            _pooled_pit_stable_object_state(item, _seen) for item in value
        ]
    if isinstance(value, (set, frozenset)):
        items = [
            _pooled_pit_stable_object_state(item, _seen) for item in value
        ]
        return sorted(items, key=_pooled_pit_canonical_json)
    if isinstance(value, type):
        return {"python_type": f"{value.__module__}.{value.__qualname__}"}

    identity = id(value)
    class_name = f"{type(value).__module__}.{type(value).__qualname__}"
    if identity in _seen:
        return {"recursive_reference": class_name}
    _seen.add(identity)
    try:
        if isinstance(value, np.random.Generator):
            state = value.bit_generator.state
        else:
            try:
                state = vars(value)
            except TypeError:
                getstate = getattr(value, "__getstate__", None)
                state = getstate() if callable(getstate) else None
        return {
            "object_class": class_name,
            "object_state": _pooled_pit_stable_object_state(state, _seen),
        }
    finally:
        _seen.remove(identity)


def _pooled_pit_fitted_bundle_contract(model, imputer, feature_names):
    return {
        "model": _pooled_pit_stable_object_state(model),
        "imputer": _pooled_pit_stable_object_state(imputer),
        "feature_names": list(feature_names),
    }


def _pooled_pit_apply_production_feature_policy(records):
    output = []
    for source in records:
        row = dict(source)
        for field in POOLED_PIT_EXTERNAL_SIDECAR_FIELDS:
            row[field] = None
        output.append(row)
    return output


def _pooled_pit_static_context(records, preselection):
    markets = {}
    for market_id in sorted({str(row.get("market_id") or "") for row in records}):
        if not market_id:
            raise ValueError("production pooled row is missing market_id")
        market_rows = [
            row for row in records if str(row.get("market_id") or "") == market_id
        ]
        values = {}
        for field in POOLED_PIT_STATIC_CONTEXT_FIELDS:
            observed = {
                _pooled_pit_canonical_json(
                    _pooled_pit_jsonable(row.get(field))
                ): _pooled_pit_jsonable(row.get(field))
                for row in market_rows
            }
            if len(observed) != 1:
                raise ValueError(
                    "production pooled static context changes within market "
                    f"{market_id}: {field}"
                )
            values[field] = next(iter(observed.values()))
        markets[market_id] = values
    payload = {
        "artifact_type": "pooled_production_static_feature_context",
        "preselection_hash": preselection["preselection_hash"],
        "window_lock_id": preselection["window_lock"]["window_lock_id"],
        "prior_as_of_exclusive": preselection["selection_universe"][
            "fleet_dates"
        ][0],
        "context_fields": list(POOLED_PIT_STATIC_CONTEXT_FIELDS),
        "markets": markets,
        "external_sidecar_policy": {
            "reanalysis_synoptic": "disabled_unpinned",
            "marine_water_contrast": "disabled_unpinned",
        },
    }
    return _pooled_pit_finalize_hash(payload, "context_sha256")


def _pooled_pit_finalize_hash(payload, field="receipt_sha256"):
    output = dict(payload)
    output.pop(field, None)
    output[field] = _pooled_pit_sha256(output)
    return output


def _pooled_pit_verify_self_hash(payload, field):
    actual = str((payload or {}).get(field) or "")
    unhashed = dict(payload or {})
    unhashed.pop(field, None)
    if (
        not _POOLED_PIT_SHA256_RE.fullmatch(actual)
        or actual != _pooled_pit_sha256(unhashed)
    ):
        raise ValueError(f"invalid production point-in-time {field}")


def _pooled_pit_utc(value, field):
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _pooled_pit_target_date(row):
    value = row.get("target_date")
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("pooled training row target_date must be YYYY-MM-DD") from exc


def _pooled_pit_hash_rows(rows):
    digest = hashlib.sha256()
    count = 0
    dates = set()
    for row in rows:
        normalized = _pooled_pit_jsonable(row)
        digest.update(_pooled_pit_canonical_json(normalized).encode("utf-8"))
        digest.update(b"\n")
        dates.add(_pooled_pit_target_date(row))
        count += 1
    return digest.hexdigest(), count, dates


def load_production_point_in_time_preselection(path):
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"cannot read production point-in-time preselection lock: {source}"
        ) from exc
    return load_production_point_in_time_preselection_from_payload(payload)


def load_production_point_in_time_preselection_from_payload(payload):
    """Verify an already-read candidate-independent preselection lock."""

    if not isinstance(payload, dict):
        raise ValueError("production point-in-time preselection must be a JSON object")
    if (
        payload.get("schema_version") != POOLED_PIT_PRESELECTION_SCHEMA_VERSION
        or payload.get("artifact_type") != "production_point_in_time_preselection"
        or payload.get("status") != "PASS"
        or payload.get("candidate_selection_permission") != "forbidden"
        or payload.get("locked_before_candidate_training") is not True
    ):
        raise ValueError("production point-in-time preselection contract is incomplete")
    _pooled_pit_verify_self_hash(payload, "preselection_hash")
    locked_at = _pooled_pit_utc(
        payload.get("generated_at_utc"), "preselection.generated_at_utc"
    )
    if locked_at > datetime.now(timezone.utc):
        raise ValueError("production point-in-time preselection is future-dated")

    universe = payload.get("selection_universe")
    lock = payload.get("window_lock")
    if not isinstance(universe, Mapping) or not isinstance(lock, Mapping):
        raise ValueError("production point-in-time selection universe/window lock is missing")
    universe_sha = str(universe.get("sha256") or "")
    universe_dates = [str(value) for value in universe.get("fleet_dates") or ()]
    locked_dates = [str(value) for value in lock.get("target_dates") or ()]
    if universe_dates and lock.get("window_end") != universe_dates[-1]:
        raise ValueError(
            "production point-in-time evaluation lock must end on the most recent date"
        )
    if (
        not _POOLED_PIT_SHA256_RE.fullmatch(universe_sha)
        or int(universe.get("row_count") or 0) <= 0
        or not universe_dates
        or len(universe_dates) != len(set(universe_dates))
        or len(locked_dates) != 14
        or len(locked_dates) != len(set(locked_dates))
        or not set(locked_dates) <= set(universe_dates)
        or lock.get("status") != "PASS"
        or lock.get("candidate_selection_permission") != "forbidden"
        or lock.get("locked_before_scoring") is not True
        or lock.get("input_kind") != "selection_universe_sha256"
        or lock.get("input_sha256") != universe_sha
        or int(lock.get("window_days") or 0) != 14
        or list(lock.get("missing_calendar_dates") or ())
    ):
        raise ValueError("production point-in-time evaluation lock is incomplete")
    try:
        parsed_locked = [date.fromisoformat(value) for value in locked_dates]
        parsed_universe = [date.fromisoformat(value) for value in universe_dates]
    except ValueError as exc:
        raise ValueError("production point-in-time lock dates must be YYYY-MM-DD") from exc
    if parsed_universe != sorted(parsed_universe):
        raise ValueError(
            "production point-in-time selection universe dates are not canonical"
        )
    latest_target_age_days = (locked_at.date() - parsed_universe[-1]).days
    if not 0 <= latest_target_age_days <= POOLED_PIT_MAX_LATEST_TARGET_AGE_DAYS:
        raise ValueError(
            "production point-in-time selection universe has a stale or future "
            "latest target date"
        )
    expected_locked = [
        parsed_locked[0] + timedelta(days=offset) for offset in range(14)
    ]
    if parsed_locked != expected_locked:
        raise ValueError("production point-in-time lock must cover 14 contiguous days")
    lock_basis = {
        "input_sha256": universe_sha,
        "input_kind": "selection_universe_sha256",
        "window_start": locked_dates[0],
        "window_end": locked_dates[-1],
        "window_days": 14,
        "target_dates": locked_dates,
    }
    if lock.get("window_lock_id") != _pooled_pit_sha256(lock_basis):
        raise ValueError("production point-in-time window lock identity is invalid")
    if str(lock.get("generated_at_utc") or "") != str(
        payload.get("generated_at_utc") or ""
    ):
        raise ValueError("preselection and window lock timestamps do not match")
    return payload


def _pooled_pit_rolling_folds(
    fleet_dates,
    *,
    min_train_dates,
    validation_dates=1,
    embargo_days=3,
    step_dates=7,
):
    parsed = sorted({date.fromisoformat(str(value)) for value in fleet_dates})
    folds = []
    for start in range(0, len(parsed), int(step_dates)):
        validation = parsed[start : start + int(validation_dates)]
        if len(validation) != int(validation_dates):
            break
        first_validation = validation[0]
        train = [
            item
            for item in parsed[:start]
            if (first_validation - item).days > int(embargo_days)
        ]
        if len(train) < int(min_train_dates):
            continue
        embargo = [
            item
            for item in parsed[:start]
            if 0 < (first_validation - item).days <= int(embargo_days)
        ]
        folds.append({
            "fold_id": f"rolling_origin_{len(folds) + 1:03d}",
            "train_dates": [item.isoformat() for item in train],
            "embargo_dates": [item.isoformat() for item in embargo],
            "validation_dates": [item.isoformat() for item in validation],
            "embargo_days": int(embargo_days),
        })
    return folds


def _pooled_pit_nested_folds(
    preselection,
    *,
    outer_min_train_dates=14,
    inner_min_train_dates=7,
    embargo_days=3,
    step_dates=7,
    max_fold_scopes=POOLED_PIT_MAX_FOLD_SCOPES,
):
    if int(step_dates) < POOLED_PIT_MIN_STEP_DATES:
        raise ValueError(
            f"production point-in-time step_dates must be >= {POOLED_PIT_MIN_STEP_DATES}"
        )
    if not 3 <= int(embargo_days) <= 7:
        raise ValueError("production point-in-time embargo_days must be between 3 and 7")
    if not 0 < int(max_fold_scopes) <= POOLED_PIT_MAX_FOLD_SCOPES:
        raise ValueError(
            f"production point-in-time fold scope cap must be 1-{POOLED_PIT_MAX_FOLD_SCOPES}"
        )
    universe_dates = list(preselection["selection_universe"]["fleet_dates"])
    locked = set(preselection["window_lock"]["target_dates"])
    selection_dates = [value for value in universe_dates if value not in locked]
    outer = _pooled_pit_rolling_folds(
        selection_dates,
        min_train_dates=int(outer_min_train_dates),
        embargo_days=int(embargo_days),
        step_dates=int(step_dates),
    )
    nested = []
    for outer_fold in outer:
        inner = _pooled_pit_rolling_folds(
            outer_fold["train_dates"],
            min_train_dates=int(inner_min_train_dates),
            embargo_days=int(embargo_days),
            step_dates=int(step_dates),
        )
        if not inner:
            raise ValueError(
                f"production outer fold has no nested inner folds: {outer_fold['fold_id']}"
            )
        nested.append({"outer": outer_fold, "inner": inner})
    scope_count = sum(1 + len(row["inner"]) for row in nested)
    if not nested:
        raise ValueError("production point-in-time dates do not produce nested folds")
    if scope_count > int(max_fold_scopes):
        raise ValueError(
            f"production point-in-time plan needs {scope_count} scopes; "
            f"configured cap is {max_fold_scopes}"
        )
    return nested


def _pooled_pit_receipt(
    fold,
    *,
    fold_scope,
    stage_name,
    implementation_identity,
    fit_rows,
    validation_rows,
    fit_output_rows,
    validation_output_rows,
    stage_output_payload,
    preselection,
    upstream_stage_output_sha256=None,
    generated_at_utc=None,
):
    fit_input_sha, fit_count, fit_dates = _pooled_pit_hash_rows(fit_rows)
    validation_input_sha, validation_count, validation_dates = (
        _pooled_pit_hash_rows(validation_rows)
    )
    fit_output_sha, fit_output_count, fit_output_dates = _pooled_pit_hash_rows(
        fit_output_rows
    )
    validation_output_sha, validation_output_count, validation_output_dates = (
        _pooled_pit_hash_rows(validation_output_rows)
    )
    expected_train = set(fold["train_dates"])
    expected_validation = set(fold["validation_dates"])
    if (
        not fit_count
        or not validation_count
        or not fit_output_count
        or not validation_output_count
        or fit_dates != expected_train
        or fit_output_dates != expected_train
        or validation_dates != expected_validation
        or validation_output_dates != expected_validation
    ):
        raise ValueError(
            f"production point-in-time stage rows do not match {fold_scope}: {stage_name}"
        )
    lock = preselection["window_lock"]
    declared_input = {
        "kind": "training_only_stage_input",
        "stage_name": stage_name,
        "preselection_hash": preselection["preselection_hash"],
        "window_lock_id": lock["window_lock_id"],
        "locked_dates": list(lock["target_dates"]),
    }
    input_payload = {
        "fit_input_sha256": fit_input_sha,
        "validation_input_sha256": validation_input_sha,
        "fit_row_count": fit_count,
        "validation_row_count": validation_count,
        "train_dates": list(fold["train_dates"]),
        "validation_dates": list(fold["validation_dates"]),
        "upstream_stage_output_sha256": upstream_stage_output_sha256,
        "declared_stage_input": declared_input,
    }
    output_payload = {
        "fit_output_sha256": fit_output_sha,
        "validation_output_sha256": validation_output_sha,
        "fit_output_row_count": fit_output_count,
        "validation_output_row_count": validation_output_count,
        "train_dates": list(fold["train_dates"]),
        "validation_dates": list(fold["validation_dates"]),
        "declared_stage_output": _pooled_pit_jsonable(stage_output_payload),
    }
    return _pooled_pit_finalize_hash({
        "schema_version": POOLED_PIT_FIT_RECEIPT_SCHEMA_VERSION,
        "artifact_type": "training_only_fit_receipt",
        "generated_at_utc": generated_at_utc
        or datetime.now(timezone.utc).isoformat(),
        "fold_scope": str(fold_scope),
        "fold_id": str(fold["fold_id"]),
        "stage_name": str(stage_name),
        "implementation_identity": str(implementation_identity),
        "fit_scope": "training_only",
        "train_dates": list(fold["train_dates"]),
        "embargo_dates": list(fold["embargo_dates"]),
        "validation_dates": list(fold["validation_dates"]),
        "embargo_days": int(fold["embargo_days"]),
        "fit_row_count": fit_count,
        "validation_row_count": validation_count,
        "fit_input_sha256": fit_input_sha,
        "validation_input_sha256": validation_input_sha,
        "fit_output_row_count": fit_output_count,
        "validation_output_row_count": validation_output_count,
        "fit_output_sha256": fit_output_sha,
        "validation_output_sha256": validation_output_sha,
        "payload_hash_algorithm": "sha256",
        "payload_canonicalization": "canonical_json",
        "stage_input_payload": input_payload,
        "stage_input_sha256": _pooled_pit_sha256(input_payload),
        "stage_output_payload": output_payload,
        "stage_output_sha256": _pooled_pit_sha256(output_payload),
        "row_hash_canonicalization": "canonical_json_lines",
        "preselection_hash": preselection["preselection_hash"],
        "window_lock_id": lock["window_lock_id"],
        "locked_dates": list(lock["target_dates"]),
    })


def _pooled_pit_rows_by_hour(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[int(row["cutoff_hour"])].append(row)
    return {hour: grouped[hour] for hour in sorted(grouped)}


def _pooled_pit_feature_identity(row, *, feature_vector=None):
    output = {
        "target_date": _pooled_pit_target_date(row),
        "market_id": str(row.get("market_id") or ""),
        "cutoff_hour": int(row.get("cutoff_hour") or 0),
        "band_kind": str(row.get("band_kind") or ""),
        "band_value": row.get("band_value"),
        "band_value_hi": row.get("band_value_hi"),
        "outcome": int(row.get("outcome") or 0),
        "sample_weight": float(row.get("_sample_weight", 1.0)),
    }
    if feature_vector is not None:
        output["feature_vector_sha256"] = _pooled_pit_sha256(
            _pooled_pit_jsonable(feature_vector)
        )
    return output


def _pooled_pit_fit_imputers(
    fit_band_rows,
    validation_band_rows,
    *,
    feature_names,
    include_dynamic_source_state,
):
    fit_groups = _pooled_pit_rows_by_hour(fit_band_rows)
    validation_groups = _pooled_pit_rows_by_hour(validation_band_rows)
    missing_hours = set(validation_groups) - set(fit_groups)
    if missing_hours:
        raise ValueError(
            f"validation cutoff hours have no training rows: {sorted(missing_hours)}"
        )
    imputers = {}
    fit_outputs = []
    validation_outputs = []
    imputer_hashes = {}
    for hour, hour_rows in fit_groups.items():
        train_frame = band_feature_frame(
            hour_rows,
            feature_names=feature_names,
            include_dynamic_source_state=include_dynamic_source_state,
        )
        imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        fit_matrix = imputer.fit_transform(train_frame)
        validation_hour_rows = validation_groups.get(hour, [])
        if validation_hour_rows:
            validation_frame = band_feature_frame(
                validation_hour_rows,
                feature_names=feature_names,
                include_dynamic_source_state=include_dynamic_source_state,
            )
            validation_matrix = imputer.transform(validation_frame)
        else:
            validation_matrix = np.empty((0, len(feature_names)), dtype=float)
        imputers[hour] = imputer
        imputer_hashes[str(hour)] = hashlib.sha256(
            pickle.dumps(imputer, protocol=pickle.HIGHEST_PROTOCOL)
        ).hexdigest()
        fit_outputs.extend(
            _pooled_pit_feature_identity(row, feature_vector=vector.tolist())
            for row, vector in zip(hour_rows, fit_matrix)
        )
        validation_outputs.extend(
            _pooled_pit_feature_identity(row, feature_vector=vector.tolist())
            for row, vector in zip(validation_hour_rows, validation_matrix)
        )
    return imputers, fit_outputs, validation_outputs, imputer_hashes


def _pooled_pit_estimator_hash(model, imputer, feature_names):
    return _pooled_pit_sha256(
        _pooled_pit_fitted_bundle_contract(model, imputer, feature_names)
    )


def _pooled_pit_fit_models(
    fit_band_rows,
    validation_band_rows,
    *,
    imputers,
    feature_names,
    feature_fit_rows,
    feature_validation_rows,
    include_dynamic_source_state,
    feature_subset,
):
    fit_groups = _pooled_pit_rows_by_hour(fit_band_rows)
    validation_groups = _pooled_pit_rows_by_hour(validation_band_rows)
    fit_outputs = []
    validation_outputs = []
    model_hashes = {}
    metrics_by_hour = {}
    for hour, hour_rows in fit_groups.items():
        if len(hour_rows) < 200 or len({row["outcome"] for row in hour_rows}) < 2:
            raise ValueError(
                f"production fold hour {hour} lacks model training support"
            )
        model, imputer, fitted_feature_names, metrics = train_band_hour_model(
            hour_rows,
            feature_names=feature_names,
            include_dynamic_source_state=include_dynamic_source_state,
            feature_subset=feature_subset,
            prefit_imputer=imputers[hour],
        )
        validation_hour_rows = validation_groups.get(hour, [])
        fit_probabilities = predict_band_probabilities(
            model, imputer, fitted_feature_names, hour_rows, temperature=1.0
        )
        validation_probabilities = predict_band_probabilities(
            model,
            imputer,
            fitted_feature_names,
            validation_hour_rows,
            temperature=1.0,
        )
        model_hashes[str(hour)] = _pooled_pit_estimator_hash(
            model, imputer, fitted_feature_names
        )
        metrics_by_hour[str(hour)] = _pooled_pit_jsonable(metrics)
        fit_outputs.extend(
            {**_pooled_pit_feature_identity(row), "model_probability": probability}
            for row, probability in zip(hour_rows, fit_probabilities)
        )
        validation_outputs.extend(
            {**_pooled_pit_feature_identity(row), "model_probability": probability}
            for row, probability in zip(
                validation_hour_rows, validation_probabilities
            )
        )
    # The model stage input is the exact output of the independent imputation
    # stage.  The HGBs above consume the corresponding full band rows and the
    # same fitted imputer objects; these assertions keep receipt chaining exact.
    if not feature_fit_rows or not feature_validation_rows:
        raise ValueError("production fold imputation output is empty")
    if (
        len(feature_fit_rows) != len(fit_band_rows)
        or len(feature_validation_rows) != len(validation_band_rows)
    ):
        raise ValueError("production fold imputation/model row counts diverged")
    return fit_outputs, validation_outputs, model_hashes, metrics_by_hour


def _pooled_pit_records_by_date(records):
    grouped = defaultdict(list)
    for row in records:
        grouped[_pooled_pit_target_date(row)].append(row)
    return grouped


def _pooled_pit_rows_for_dates(rows_by_date, values):
    output = []
    for value in values:
        rows = rows_by_date.get(str(value), ())
        if not rows:
            raise ValueError(
                f"pooled training corpus has no rows for declared fleet date {value}"
            )
        output.extend(rows)
    return output


def _pooled_pit_prediction_stage_rows(rows, *, stage, postprocess_config):
    output = []
    for row in rows:
        if stage == "calibration":
            output.append({
                **row,
                "calibrated_probability": temperature_scale_probability(
                    row["model_probability"], temperature=1.0
                ),
            })
        elif stage == "postprocessing":
            output.append({
                **row,
                "postprocessed_probability": apply_band_postprocessing(
                    row["calibrated_probability"],
                    row,
                    config=postprocess_config,
                ),
            })
        elif stage == "regime_router":
            output.append({
                **row,
                "selected_route": pooled_band_regime_route(row),
            })
        else:
            raise ValueError(f"unknown pooled PIT prediction stage: {stage}")
    return output


def _run_pooled_pit_fold(
    fold,
    *,
    fold_scope,
    rows_by_date,
    preselection,
    family_unit,
    include_dynamic_source_state,
    feature_subset,
    postprocess_config,
    generated_at_utc,
):
    locked = set(preselection["window_lock"]["target_dates"])
    used_dates = set(
        fold["train_dates"]
        + fold["embargo_dates"]
        + fold["validation_dates"]
    )
    if locked & used_dates:
        raise ValueError(
            f"locked evaluation date escaped into pooled training fold {fold_scope}"
        )
    fit_source_rows = _pooled_pit_rows_for_dates(
        rows_by_date, fold["train_dates"]
    )
    validation_source_rows = _pooled_pit_rows_for_dates(
        rows_by_date, fold["validation_dates"]
    )
    # Support is derived from the fold's training partition only.  Neither
    # validation nor the locked window can influence synthetic band geometry.
    fold_support = band_training_support(
        fit_source_rows, family_unit=family_unit
    )
    fit_band_rows = build_band_rows(fit_source_rows, fold_support)
    validation_band_rows = build_band_rows(
        validation_source_rows, fold_support
    )
    if not fit_band_rows or not validation_band_rows:
        raise ValueError(f"production fold has no band rows: {fold_scope}")
    selected_frame = band_feature_frame(
        fit_band_rows,
        include_dynamic_source_state=include_dynamic_source_state,
    )
    feature_names = feature_names_for_subset(
        selected_frame.columns, feature_subset
    )
    if not feature_names:
        raise ValueError(f"production fold selected no features: {fold_scope}")

    receipts = []
    feature_receipt = _pooled_pit_receipt(
        fold,
        fold_scope=fold_scope,
        stage_name="feature_selection",
        implementation_identity=POOLED_PIT_STAGE_IMPLEMENTATIONS[
            "feature_selection"
        ],
        fit_rows=fit_source_rows,
        validation_rows=validation_source_rows,
        fit_output_rows=fit_band_rows,
        validation_output_rows=validation_band_rows,
        stage_output_payload={
            "binding_kind": "actual_pooled_band_training",
            "support": fold_support,
            "feature_names": list(feature_names),
            "feature_subset": feature_subset,
        },
        preselection=preselection,
        generated_at_utc=generated_at_utc,
    )
    receipts.append(feature_receipt)

    imputers, fit_feature_rows, validation_feature_rows, imputer_hashes = (
        _pooled_pit_fit_imputers(
            fit_band_rows,
            validation_band_rows,
            feature_names=feature_names,
            include_dynamic_source_state=include_dynamic_source_state,
        )
    )
    imputation_receipt = _pooled_pit_receipt(
        fold,
        fold_scope=fold_scope,
        stage_name="scaling_imputation",
        implementation_identity=POOLED_PIT_STAGE_IMPLEMENTATIONS[
            "scaling_imputation"
        ],
        fit_rows=fit_band_rows,
        validation_rows=validation_band_rows,
        fit_output_rows=fit_feature_rows,
        validation_output_rows=validation_feature_rows,
        stage_output_payload={
            "binding_kind": "actual_pooled_band_training",
            "scaling": "not_required_for_hist_gradient_boosting",
            "imputation": "training_fold_median_keep_empty_features",
            "imputer_sha256_by_hour": imputer_hashes,
            "feature_names": list(feature_names),
        },
        preselection=preselection,
        upstream_stage_output_sha256=feature_receipt["stage_output_sha256"],
        generated_at_utc=generated_at_utc,
    )
    receipts.append(imputation_receipt)

    (
        fit_model_rows,
        validation_model_rows,
        model_hashes,
        metrics_by_hour,
    ) = _pooled_pit_fit_models(
        fit_band_rows,
        validation_band_rows,
        imputers=imputers,
        feature_names=feature_names,
        feature_fit_rows=fit_feature_rows,
        feature_validation_rows=validation_feature_rows,
        include_dynamic_source_state=include_dynamic_source_state,
        feature_subset=feature_subset,
    )
    model_receipt = _pooled_pit_receipt(
        fold,
        fold_scope=fold_scope,
        stage_name="model",
        implementation_identity=POOLED_PIT_STAGE_IMPLEMENTATIONS["model"],
        fit_rows=fit_feature_rows,
        validation_rows=validation_feature_rows,
        fit_output_rows=fit_model_rows,
        validation_output_rows=validation_model_rows,
        stage_output_payload={
            "binding_kind": "actual_pooled_band_training",
            "model_sha256_by_hour": model_hashes,
            "training_metrics_by_hour": metrics_by_hour,
        },
        preselection=preselection,
        upstream_stage_output_sha256=imputation_receipt[
            "stage_output_sha256"
        ],
        generated_at_utc=generated_at_utc,
    )
    receipts.append(model_receipt)

    fit_calibrated = _pooled_pit_prediction_stage_rows(
        fit_model_rows,
        stage="calibration",
        postprocess_config=postprocess_config,
    )
    validation_calibrated = _pooled_pit_prediction_stage_rows(
        validation_model_rows,
        stage="calibration",
        postprocess_config=postprocess_config,
    )
    calibration_receipt = _pooled_pit_receipt(
        fold,
        fold_scope=fold_scope,
        stage_name="calibration",
        implementation_identity=POOLED_PIT_STAGE_IMPLEMENTATIONS["calibration"],
        fit_rows=fit_model_rows,
        validation_rows=validation_model_rows,
        fit_output_rows=fit_calibrated,
        validation_output_rows=validation_calibrated,
        stage_output_payload={
            "binding_kind": "actual_pooled_band_training",
            "method": "identity_temperature",
            "temperature": 1.0,
        },
        preselection=preselection,
        upstream_stage_output_sha256=model_receipt["stage_output_sha256"],
        generated_at_utc=generated_at_utc,
    )
    receipts.append(calibration_receipt)

    fit_postprocessed = _pooled_pit_prediction_stage_rows(
        fit_calibrated,
        stage="postprocessing",
        postprocess_config=postprocess_config,
    )
    validation_postprocessed = _pooled_pit_prediction_stage_rows(
        validation_calibrated,
        stage="postprocessing",
        postprocess_config=postprocess_config,
    )
    postprocess_receipt = _pooled_pit_receipt(
        fold,
        fold_scope=fold_scope,
        stage_name="postprocessing",
        implementation_identity=POOLED_PIT_STAGE_IMPLEMENTATIONS[
            "postprocessing"
        ],
        fit_rows=fit_calibrated,
        validation_rows=validation_calibrated,
        fit_output_rows=fit_postprocessed,
        validation_output_rows=validation_postprocessed,
        stage_output_payload={
            "binding_kind": "actual_pooled_band_training",
            "learned_parameter_policy": "identity_disabled",
            "serving_path": "canonical_band_postprocessing",
            "postprocess_config": _pooled_pit_jsonable(postprocess_config),
            "postprocess_config_sha256": _pooled_pit_sha256(
                postprocess_config
            ),
        },
        preselection=preselection,
        upstream_stage_output_sha256=calibration_receipt[
            "stage_output_sha256"
        ],
        generated_at_utc=generated_at_utc,
    )
    receipts.append(postprocess_receipt)

    fit_routed = _pooled_pit_prediction_stage_rows(
        fit_postprocessed,
        stage="regime_router",
        postprocess_config=postprocess_config,
    )
    validation_routed = _pooled_pit_prediction_stage_rows(
        validation_postprocessed,
        stage="regime_router",
        postprocess_config=postprocess_config,
    )
    router_receipt = _pooled_pit_receipt(
        fold,
        fold_scope=fold_scope,
        stage_name="regime_router",
        implementation_identity=POOLED_PIT_STAGE_IMPLEMENTATIONS[
            "regime_router"
        ],
        fit_rows=fit_postprocessed,
        validation_rows=validation_postprocessed,
        fit_output_rows=fit_routed,
        validation_output_rows=validation_routed,
        stage_output_payload={
            "binding_kind": "actual_pooled_band_training",
            "route": "pooled_band_default",
            "selection": "predeclared_single_route_no_fit",
            "serving_path": "canonical_pooled_band_regime_route",
            "locked_window_used": False,
        },
        preselection=preselection,
        upstream_stage_output_sha256=postprocess_receipt[
            "stage_output_sha256"
        ],
        generated_at_utc=generated_at_utc,
    )
    receipts.append(router_receipt)
    return receipts


def build_pooled_point_in_time_training_evidence(
    records,
    preselection,
    *,
    family_unit="F",
    include_dynamic_source_state=False,
    feature_subset=FEATURE_SUBSET_ALL,
    postprocess_config=None,
    outer_min_train_dates=14,
    inner_min_train_dates=7,
    embargo_days=3,
    step_dates=7,
    max_fold_scopes=POOLED_PIT_MAX_FOLD_SCOPES,
    private_memory_budget_bytes=4 * 1024**3,
):
    """Run every declared pooled outer/inner scope one at a time."""

    verified = load_production_point_in_time_preselection_from_payload(
        preselection
    )
    if not isinstance(postprocess_config, Mapping) or not postprocess_config:
        raise ValueError(
            "production pooled training requires the served postprocess config"
        )
    postprocess_config = _pooled_pit_jsonable(postprocess_config)
    budget = int(private_memory_budget_bytes)
    if not 0 < budget <= 8 * 1024**3:
        raise ValueError("production pooled training memory budget must be <= 8 GiB")
    locked = set(verified["window_lock"]["target_dates"])
    universe_dates = list(verified["selection_universe"]["fleet_dates"])
    if len(universe_dates) > POOLED_PIT_MAX_MARKET_DAYS:
        raise ValueError(
            "production point-in-time selection universe exceeds the 60-day bound"
        )
    rows_by_date = _pooled_pit_records_by_date(records)
    training_dates = sorted(set(universe_dates) - locked)
    overlap = locked & set(rows_by_date)
    if overlap:
        raise ValueError(
            f"locked dates remain in pooled production training rows: {sorted(overlap)}"
        )
    if set(rows_by_date) != set(training_dates):
        raise ValueError(
            "pooled production training rows differ from the prelocked training universe"
        )
    peak_source_rows = max(
        (len(rows) for rows in rows_by_date.values()), default=0
    )
    if peak_source_rows > POOLED_PIT_MAX_TRAINING_SOURCE_ROWS_PER_MARKET_DAY:
        raise ValueError(
            "pooled production source rows exceed the per-market-day bound"
        )
    folds = _pooled_pit_nested_folds(
        verified,
        outer_min_train_dates=outer_min_train_dates,
        inner_min_train_dates=inner_min_train_dates,
        embargo_days=embargo_days,
        step_dates=step_dates,
        max_fold_scopes=max_fold_scopes,
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    receipts = []
    for item in folds:
        outer = item["outer"]
        outer_scope = f"outer/{outer['fold_id']}"
        receipts.extend(_run_pooled_pit_fold(
            outer,
            fold_scope=outer_scope,
            rows_by_date=rows_by_date,
            preselection=verified,
            family_unit=family_unit,
            include_dynamic_source_state=include_dynamic_source_state,
            feature_subset=feature_subset,
            postprocess_config=postprocess_config,
            generated_at_utc=generated_at,
        ))
        for inner in item["inner"]:
            receipts.extend(_run_pooled_pit_fold(
                inner,
                fold_scope=f"{outer_scope}/inner/{inner['fold_id']}",
                rows_by_date=rows_by_date,
                preselection=verified,
                family_unit=family_unit,
                include_dynamic_source_state=include_dynamic_source_state,
                feature_subset=feature_subset,
                postprocess_config=postprocess_config,
                generated_at_utc=generated_at,
            ))
    scopes = sum(1 + len(item["inner"]) for item in folds)
    return {
        "schema_version": POOLED_PIT_TRAINING_SCHEMA_VERSION,
        "status": "PASS",
        "generated_at_utc": generated_at,
        "preselection_lock": {
            "preselection_hash": verified["preselection_hash"],
            "window_lock_id": verified["window_lock"]["window_lock_id"],
            "locked_at_utc": verified["generated_at_utc"],
            "locked_dates": list(verified["window_lock"]["target_dates"]),
            "selection_universe_sha256": verified["selection_universe"]["sha256"],
            "selection_universe_dates": universe_dates,
            "selection_universe_row_count": int(
                verified["selection_universe"]["row_count"]
            ),
            "training_universe_dates": training_dates,
            "training_universe_sha256": _pooled_pit_sha256(training_dates),
            "locked_dates_used_for_selection": False,
            "candidate_selection_permission": "forbidden",
        },
        "fold_config": {
            "outer_min_train_dates": int(outer_min_train_dates),
            "inner_min_train_dates": int(inner_min_train_dates),
            "outer_validation_dates": 1,
            "inner_validation_dates": 1,
            "embargo_days": int(embargo_days),
            "step_dates": int(step_dates),
        },
        "folds": folds,
        "fit_receipt_contract": {
            "fit_scope": "training_only",
            "required_stages": list(POOLED_PIT_REQUIRED_STAGES),
            "stage_order": list(POOLED_PIT_REQUIRED_STAGES),
            "scope_count": scopes,
            "max_fold_scopes": int(max_fold_scopes),
            "payload_binding_required": True,
            "payload_hash_algorithm": "sha256",
            "payload_canonicalization": "canonical_json",
        },
        "fit_receipts": receipts,
        "resource_contract": {
            "private_memory_budget_bytes": budget,
            "fold_execution": "one_scope_at_a_time",
            "fold_models_retained_after_receipt": False,
            "max_fold_scopes": int(max_fold_scopes),
            "step_dates_minimum": POOLED_PIT_MIN_STEP_DATES,
            "max_market_days": POOLED_PIT_MAX_MARKET_DAYS,
            "observed_market_days": len(universe_dates),
            "observed_training_dates": len(rows_by_date),
            "observed_training_source_rows": len(records),
            "max_training_source_rows_per_market_day": (
                POOLED_PIT_MAX_TRAINING_SOURCE_ROWS_PER_MARKET_DAY
            ),
            "observed_peak_training_source_rows_per_market_day": peak_source_rows,
            "raw_market_days_retained_at_once": 1,
            "corpus_read_mode": (
                "stream_market_day_then_retain_bounded_normalized_population"
            ),
            "normalized_training_population_retained": True,
            "max_normalized_training_source_rows": (
                POOLED_PIT_MAX_NORMALIZED_TRAINING_SOURCE_ROWS
            ),
        },
    }


def _pooled_pit_bundle_hash(bundle):
    return _pooled_pit_sha256(
        {
            "fitted_bundle": _pooled_pit_fitted_bundle_contract(
                bundle["model"],
                bundle["imputer"],
                bundle["feature_names"],
            ),
            "feature_schema_version": bundle.get("feature_schema_version"),
            "classes": list(bundle.get("classes") or ()),
            "temperature": bundle.get("temperature"),
            "postprocess": bundle.get("postprocess"),
        }
    )


def _pooled_pit_artifact_serving_contract(artifact):
    fit_contract = artifact.get("postprocess_fit_contract") or {}
    static_context = artifact.get("production_static_context") or {}
    return {
        "schema_version": artifact.get("schema_version"),
        "feature_schema_version": artifact.get("feature_schema_version"),
        "family_unit": artifact.get("family_unit"),
        "prediction_mode": artifact.get("prediction_mode"),
        "objective": artifact.get("objective"),
        "feature_subset": artifact.get("feature_subset"),
        "feature_subset_contract": artifact.get("feature_subset_contract"),
        "dynamic_source_state_enabled": artifact.get(
            "dynamic_source_state_enabled"
        ),
        "postprocess": artifact.get("postprocess"),
        "production_static_context_sha256": static_context.get(
            "context_sha256"
        ),
        "production_external_sidecar_policy": static_context.get(
            "external_sidecar_policy"
        ),
        "postprocess_fit_contract": {
            key: fit_contract.get(key)
            for key in (
                "schema_version",
                "status",
                "policy",
                "served_parameters",
                "preselection_hash",
                "window_lock_id",
                "locked_dates",
                "promotion_permission",
            )
            if key in fit_contract
        },
    }


def build_pooled_point_in_time_final_refit_receipt(
    records,
    artifact,
    evidence,
):
    """Bind the production artifact's real final HGB refit to its lock."""

    lock = evidence["preselection_lock"]
    locked = set(lock["locked_dates"])
    train_dates = sorted({_pooled_pit_target_date(row) for row in records})
    if locked & set(train_dates):
        raise ValueError("locked dates escaped into the pooled final refit")
    if not records or not artifact.get("models"):
        raise ValueError("pooled final refit did not produce any model bundles")
    fit_input_sha256, fit_row_count, _ = _pooled_pit_hash_rows(records)
    model_hashes = {
        str(hour): _pooled_pit_bundle_hash(bundle)
        for hour, bundle in sorted(
            artifact["models"].items(), key=lambda item: int(item[0])
        )
    }
    serving_contract = _pooled_pit_artifact_serving_contract(artifact)
    serving_contract_sha256 = _pooled_pit_sha256(serving_contract)
    model_payload_sha256 = _pooled_pit_sha256(
        {
            "model_sha256_by_hour": model_hashes,
            "artifact_serving_contract_sha256": serving_contract_sha256,
        }
    )
    parent_receipts_sha256 = _pooled_pit_sha256(sorted(
        str(receipt["receipt_sha256"])
        for receipt in evidence.get("fit_receipts") or ()
    ))
    stage_input = {
        "fit_input_sha256": fit_input_sha256,
        "fit_row_count": fit_row_count,
        "train_dates": train_dates,
        "locked_dates": sorted(locked),
        "preselection_hash": lock["preselection_hash"],
        "window_lock_id": lock["window_lock_id"],
        "parent_fit_receipts_sha256": parent_receipts_sha256,
    }
    stage_output = {
        "model_payload_sha256": model_payload_sha256,
        "model_sha256_by_hour": model_hashes,
        "artifact_serving_contract": serving_contract,
        "artifact_serving_contract_sha256": serving_contract_sha256,
        "model_count": len(model_hashes),
        "feature_schema_version": artifact.get("feature_schema_version"),
        "support_sha256": _pooled_pit_sha256(artifact.get("support")),
    }
    return _pooled_pit_finalize_hash({
        "schema_version": POOLED_PIT_FINAL_REFIT_SCHEMA_VERSION,
        "artifact_type": "pooled_band_final_refit_receipt",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fit_role": "prelock_excluded_final_refit",
        "fit_scope": "all_unlocked_training_rows",
        "fit_input_sha256": fit_input_sha256,
        "fit_row_count": fit_row_count,
        "train_dates": train_dates,
        "locked_dates": sorted(locked),
        "preselection_hash": lock["preselection_hash"],
        "window_lock_id": lock["window_lock_id"],
        "selection_universe_sha256": lock["selection_universe_sha256"],
        "parent_fit_receipts_sha256": parent_receipts_sha256,
        "model_payload_sha256": model_payload_sha256,
        "model_sha256_by_hour": model_hashes,
        "artifact_serving_contract_sha256": serving_contract_sha256,
        "payload_hash_algorithm": "sha256",
        "payload_canonicalization": "canonical_json",
        "stage_input_payload": stage_input,
        "stage_input_sha256": _pooled_pit_sha256(stage_input),
        "stage_output_payload": stage_output,
        "stage_output_sha256": _pooled_pit_sha256(stage_output),
    })


def finalize_pooled_point_in_time_training_evidence(
    records,
    artifact,
    evidence,
):
    finalized = dict(evidence)
    finalized["final_fit_receipt"] = (
        build_pooled_point_in_time_final_refit_receipt(
            records, artifact, finalized
        )
    )
    return _pooled_pit_finalize_hash(finalized, "evidence_sha256")


def verify_pooled_point_in_time_training_evidence(artifact):
    """Fail closed on the pooled lock -> folds -> final-refit evidence graph."""

    evidence = artifact.get("point_in_time_training")
    if not isinstance(evidence, Mapping):
        raise ValueError("pooled production point-in-time training evidence is missing")
    _pooled_pit_verify_self_hash(evidence, "evidence_sha256")
    if (
        evidence.get("schema_version")
        != POOLED_PIT_TRAINING_SCHEMA_VERSION
        or evidence.get("status") != "PASS"
    ):
        raise ValueError("pooled production point-in-time training evidence is invalid")
    lock = evidence.get("preselection_lock")
    if not isinstance(lock, Mapping):
        raise ValueError("pooled production preselection binding is missing")
    locked = set(str(value) for value in lock.get("locked_dates") or ())
    universe_dates = [
        str(value) for value in lock.get("selection_universe_dates") or ()
    ]
    training_dates = [
        str(value) for value in lock.get("training_universe_dates") or ()
    ]
    if (
        len(locked) != 14
        or lock.get("locked_dates_used_for_selection") is not False
        or lock.get("candidate_selection_permission") != "forbidden"
        or not _POOLED_PIT_SHA256_RE.fullmatch(
            str(lock.get("preselection_hash") or "")
        )
        or not _POOLED_PIT_SHA256_RE.fullmatch(
            str(lock.get("window_lock_id") or "")
        )
        or not _POOLED_PIT_SHA256_RE.fullmatch(
            str(lock.get("selection_universe_sha256") or "")
        )
        or not universe_dates
        or universe_dates != sorted(set(universe_dates))
        or not locked <= set(universe_dates)
        or training_dates != sorted(set(universe_dates) - locked)
        or lock.get("training_universe_sha256")
        != _pooled_pit_sha256(training_dates)
        or len(universe_dates) > POOLED_PIT_MAX_MARKET_DAYS
        or int(lock.get("selection_universe_row_count") or 0) <= 0
    ):
        raise ValueError("pooled production preselection binding is incomplete")
    try:
        parsed_locked = sorted(date.fromisoformat(value) for value in locked)
        for value in universe_dates:
            date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("pooled production lock dates are invalid") from exc
    if parsed_locked != [
        parsed_locked[0] + timedelta(days=offset) for offset in range(14)
    ]:
        raise ValueError("pooled production locked window is not contiguous")
    static_context = artifact.get("production_static_context")
    if not isinstance(static_context, Mapping):
        raise ValueError("pooled production static feature context is missing")
    _pooled_pit_verify_self_hash(static_context, "context_sha256")
    if (
        static_context.get("artifact_type")
        != "pooled_production_static_feature_context"
        or static_context.get("preselection_hash") != lock["preselection_hash"]
        or static_context.get("window_lock_id") != lock["window_lock_id"]
        or static_context.get("prior_as_of_exclusive") != universe_dates[0]
        or tuple(static_context.get("context_fields") or ())
        != POOLED_PIT_STATIC_CONTEXT_FIELDS
        or not isinstance(static_context.get("markets"), Mapping)
        or not static_context["markets"]
        or static_context.get("external_sidecar_policy")
        != {
            "reanalysis_synoptic": "disabled_unpinned",
            "marine_water_contrast": "disabled_unpinned",
        }
    ):
        raise ValueError("pooled production static feature context is invalid")
    folds = evidence.get("folds")
    if not isinstance(folds, list) or not folds:
        raise ValueError("pooled production nested folds are missing")
    scope_rows = {}
    for item in folds:
        outer = item["outer"]
        outer_scope = f"outer/{outer['fold_id']}"
        scope_rows[outer_scope] = outer
        for inner in item.get("inner") or ():
            scope_rows[f"{outer_scope}/inner/{inner['fold_id']}"] = inner
    contract = evidence.get("fit_receipt_contract") or {}
    resources = evidence.get("resource_contract") or {}
    config = evidence.get("fold_config") or {}
    if (
        tuple(contract.get("required_stages") or ())
        != POOLED_PIT_REQUIRED_STAGES
        or tuple(contract.get("stage_order") or ())
        != POOLED_PIT_REQUIRED_STAGES
        or int(contract.get("scope_count") or 0) != len(scope_rows)
        or not 0 < len(scope_rows) <= POOLED_PIT_MAX_FOLD_SCOPES
        or int(contract.get("max_fold_scopes") or 0)
        != int(resources.get("max_fold_scopes") or 0)
    ):
        raise ValueError("pooled production fit receipt contract is invalid")
    if (
        not 0 < int(resources.get("private_memory_budget_bytes") or 0)
        <= 8 * 1024**3
        or resources.get("fold_execution") != "one_scope_at_a_time"
        or resources.get("fold_models_retained_after_receipt") is not False
        or int(resources.get("step_dates_minimum") or 0)
        != POOLED_PIT_MIN_STEP_DATES
        or int(resources.get("max_market_days") or 0)
        != POOLED_PIT_MAX_MARKET_DAYS
        or int(resources.get("observed_market_days") or 0) != len(universe_dates)
        or not 0 < int(resources.get("observed_training_dates") or 0)
        <= len(universe_dates)
        or int(resources.get("observed_training_source_rows") or 0) <= 0
        or int(resources.get("max_training_source_rows_per_market_day") or 0)
        != POOLED_PIT_MAX_TRAINING_SOURCE_ROWS_PER_MARKET_DAY
        or not 0
        < int(
            resources.get("observed_peak_training_source_rows_per_market_day")
            or 0
        )
        <= POOLED_PIT_MAX_TRAINING_SOURCE_ROWS_PER_MARKET_DAY
        or int(resources.get("raw_market_days_retained_at_once") or 0) != 1
        or resources.get("normalized_training_population_retained") is not True
        or int(resources.get("max_normalized_training_source_rows") or 0)
        != POOLED_PIT_MAX_NORMALIZED_TRAINING_SOURCE_ROWS
        or int(resources.get("observed_training_source_rows") or 0)
        > POOLED_PIT_MAX_NORMALIZED_TRAINING_SOURCE_ROWS
        or resources.get("corpus_read_mode")
        != "stream_market_day_then_retain_bounded_normalized_population"
    ):
        raise ValueError("pooled production resource contract is invalid")
    expected_config = {
        "outer_min_train_dates": int(config.get("outer_min_train_dates") or 0),
        "inner_min_train_dates": int(config.get("inner_min_train_dates") or 0),
        "outer_validation_dates": 1,
        "inner_validation_dates": 1,
        "embargo_days": int(config.get("embargo_days") or 0),
        "step_dates": int(config.get("step_dates") or 0),
    }
    if dict(config) != expected_config:
        raise ValueError("pooled production fold configuration is invalid")
    regenerated = _pooled_pit_nested_folds(
        {
            "selection_universe": {"fleet_dates": universe_dates},
            "window_lock": {"target_dates": sorted(locked)},
        },
        outer_min_train_dates=expected_config["outer_min_train_dates"],
        inner_min_train_dates=expected_config["inner_min_train_dates"],
        embargo_days=expected_config["embargo_days"],
        step_dates=expected_config["step_dates"],
        max_fold_scopes=int(resources["max_fold_scopes"]),
    )
    if folds != regenerated:
        raise ValueError("pooled production nested folds do not match the locked universe")
    by_key = {}
    for receipt in evidence.get("fit_receipts") or ():
        if not isinstance(receipt, Mapping):
            raise ValueError("pooled production fit receipt is malformed")
        _pooled_pit_verify_self_hash(receipt, "receipt_sha256")
        key = (receipt.get("fold_scope"), receipt.get("stage_name"))
        fold = scope_rows.get(key[0])
        input_payload = receipt.get("stage_input_payload")
        output_payload = receipt.get("stage_output_payload")
        if (
            key in by_key
            or fold is None
            or receipt.get("schema_version")
            != POOLED_PIT_FIT_RECEIPT_SCHEMA_VERSION
            or receipt.get("artifact_type") != "training_only_fit_receipt"
            or receipt.get("fit_scope") != "training_only"
            or key[1] not in POOLED_PIT_REQUIRED_STAGES
            or receipt.get("implementation_identity")
            != POOLED_PIT_STAGE_IMPLEMENTATIONS.get(key[1])
            or receipt.get("fold_id") != fold["fold_id"]
            or list(receipt.get("train_dates") or ()) != fold["train_dates"]
            or list(receipt.get("embargo_dates") or ())
            != fold["embargo_dates"]
            or list(receipt.get("validation_dates") or ())
            != fold["validation_dates"]
            or locked
            & set(
                fold["train_dates"]
                + fold["embargo_dates"]
                + fold["validation_dates"]
            )
            or receipt.get("preselection_hash") != lock["preselection_hash"]
            or receipt.get("window_lock_id") != lock["window_lock_id"]
            or set(receipt.get("locked_dates") or ()) != locked
            or not isinstance(input_payload, Mapping)
            or not isinstance(output_payload, Mapping)
            or receipt.get("stage_input_sha256")
            != _pooled_pit_sha256(input_payload)
            or receipt.get("stage_output_sha256")
            != _pooled_pit_sha256(output_payload)
        ):
            raise ValueError(f"pooled production fit receipt is invalid: {key}")
        by_key[key] = receipt
    expected_keys = {
        (scope, stage)
        for scope in scope_rows
        for stage in POOLED_PIT_REQUIRED_STAGES
    }
    if set(by_key) != expected_keys:
        raise ValueError("pooled production fit receipt coverage is incomplete")
    served_postprocess = _pooled_pit_jsonable(artifact.get("postprocess") or {})
    served_postprocess_sha256 = _pooled_pit_sha256(served_postprocess)
    for scope in scope_rows:
        declarations = {
            stage: by_key[(scope, stage)]["stage_output_payload"][
                "declared_stage_output"
            ]
            for stage in POOLED_PIT_REQUIRED_STAGES
        }
        if any(
            declaration.get("binding_kind") != "actual_pooled_band_training"
            for declaration in declarations.values()
        ):
            raise ValueError(
                "pooled production fit receipt is not bound to actual training"
            )
        calibration = declarations["calibration"]
        postprocessing = declarations["postprocessing"]
        router = declarations["regime_router"]
        if (
            calibration.get("method") != "identity_temperature"
            or float(calibration.get("temperature") or 0.0) != 1.0
            or postprocessing.get("learned_parameter_policy")
            != "identity_disabled"
            or postprocessing.get("serving_path")
            != "canonical_band_postprocessing"
            or postprocessing.get("postprocess_config") != served_postprocess
            or postprocessing.get("postprocess_config_sha256")
            != served_postprocess_sha256
            or router.get("route") != "pooled_band_default"
            or router.get("selection")
            != "predeclared_single_route_no_fit"
            or router.get("serving_path")
            != "canonical_pooled_band_regime_route"
            or router.get("locked_window_used") is not False
        ):
            raise ValueError(
                "pooled production prediction-stage receipt is invalid"
            )
    for scope in scope_rows:
        prior = None
        for stage in POOLED_PIT_REQUIRED_STAGES:
            receipt = by_key[(scope, stage)]
            upstream = receipt["stage_input_payload"].get(
                "upstream_stage_output_sha256"
            )
            if prior is None:
                if upstream is not None:
                    raise ValueError("first pooled production stage has an upstream hash")
            elif (
                upstream != prior["stage_output_sha256"]
                or receipt["fit_input_sha256"] != prior["fit_output_sha256"]
                or receipt["validation_input_sha256"]
                != prior["validation_output_sha256"]
                or receipt["fit_row_count"] != prior["fit_output_row_count"]
                or receipt["validation_row_count"]
                != prior["validation_output_row_count"]
            ):
                raise ValueError("pooled production fit receipt chain is broken")
            prior = receipt

    final_receipt = evidence.get("final_fit_receipt")
    if not isinstance(final_receipt, Mapping):
        raise ValueError("pooled production final-refit receipt is missing")
    _pooled_pit_verify_self_hash(final_receipt, "receipt_sha256")
    model_hashes = {
        str(hour): _pooled_pit_bundle_hash(bundle)
        for hour, bundle in sorted(
            (artifact.get("models") or {}).items(),
            key=lambda item: int(item[0]),
        )
    }
    parent_receipts_sha256 = _pooled_pit_sha256(sorted(
        str(receipt["receipt_sha256"])
        for receipt in evidence.get("fit_receipts") or ()
    ))
    final_output = final_receipt.get("stage_output_payload") or {}
    serving_contract = _pooled_pit_artifact_serving_contract(artifact)
    serving_contract_sha256 = _pooled_pit_sha256(serving_contract)
    if (
        final_receipt.get("preselection_hash") != lock["preselection_hash"]
        or final_receipt.get("window_lock_id") != lock["window_lock_id"]
        or set(final_receipt.get("locked_dates") or ()) != locked
        or locked & set(final_receipt.get("train_dates") or ())
        or set(final_receipt.get("train_dates") or ()) != set(training_dates)
        or final_receipt.get("model_sha256_by_hour") != model_hashes
        or final_receipt.get("model_payload_sha256")
        != _pooled_pit_sha256(
            {
                "model_sha256_by_hour": model_hashes,
                "artifact_serving_contract_sha256": serving_contract_sha256,
            }
        )
        or final_receipt.get("artifact_serving_contract_sha256")
        != serving_contract_sha256
        or final_receipt.get("parent_fit_receipts_sha256")
        != parent_receipts_sha256
        or final_output.get("support_sha256")
        != _pooled_pit_sha256(artifact.get("support"))
        or final_output.get("feature_schema_version")
        != artifact.get("feature_schema_version")
        or final_output.get("artifact_serving_contract") != serving_contract
        or final_output.get("artifact_serving_contract_sha256")
        != serving_contract_sha256
        or final_receipt.get("stage_input_sha256")
        != _pooled_pit_sha256(final_receipt.get("stage_input_payload") or {})
        or final_receipt.get("stage_output_sha256")
        != _pooled_pit_sha256(final_receipt.get("stage_output_payload") or {})
    ):
        raise ValueError("pooled production final-refit receipt is invalid")
    return dict(evidence)

def train_pooled_models(records, holdout_year=None):
    by_hour = defaultdict(list)
    for row in records:
        by_hour[int(row["cutoff_hour"])].append(row)

    artifact = {
        "schema_version": "pooled_feature_hgb_v0.1",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": "F",
        "trained_at": datetime.now().isoformat(),
        "support": sorted({int(row["final_bucket"]) for row in records}),
        "blocked_validation": blocked_validation_audit(records),
        "models": {},
    }
    support = artifact["support"]
    validation_rows = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_rows = hour_rows
            eval_rows = []
        else:
            train_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        if len(train_rows) < 50:
            continue
        model, imputer, feature_names, train_metrics = train_hour_model(train_rows)
        eval_score = None
        market_scores = []
        if eval_rows:
            predictions = predict_rows(model, imputer, feature_names, eval_rows, support=support)
            eval_score = evaluate_distributions(eval_rows, predictions)
            for market_id in sorted({row["market_id"] for row in eval_rows}):
                market_eval = [row for row in eval_rows if row["market_id"] == market_id]
                market_predictions = [
                    pred for row, pred in zip(eval_rows, predictions)
                    if row["market_id"] == market_id
                ]
                score = evaluate_distributions(market_eval, market_predictions)
                if score:
                    market_scores.append({"market_id": market_id, **score})

        final_model, final_imputer, final_feature_names, final_metrics = train_hour_model(hour_rows)
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "classes": [int(value) for value in final_model.classes_],
            "train_rows": len(hour_rows),
            "training_metrics": final_metrics,
        }
        validation_rows.append({
            "hour": hour,
            "train_rows": len(train_rows),
            "eval_rows": len(eval_rows),
            "eval_score": eval_score,
            "market_scores": market_scores,
            "training_metrics": train_metrics,
            "blocked_validation": blocked_validation_audit(hour_rows),
        })
    return artifact, validation_rows


def default_band_postprocess(
    exact_winner_catchup_enabled=False,
    exact_winner_shadow_blend=True,
):
    config = {
        "hard_floor_enabled": True,
        "support_floor_enabled": True,
        "support_floor_one_below_cap": 0.08,
        "support_floor_decay": 0.25,
        "late_lockin_enabled": True,
        "late_lockin_max_strength": 0.85,
        "adjacent_calibration_enabled": True,
        "adjacent_calibration": {},
        "exact_winner_catchup_enabled": bool(exact_winner_catchup_enabled),
        "exact_winner_catchup": {},
        "forecast_centering_enabled": False,
        "forecast_centering_sigma": 1.25,
        "forecast_centering_default_alpha": 0.0,
        "forecast_centering_early_alpha": 0.0,
        "forecast_centering_alpha_by_hour": {},
        "market_bias_calibration_enabled": False,
        "market_bias_calibration": {},
        "partition_normalization_enabled": True,
        "partition_normalization_gamma": 1.25,
        "current_blend_enabled": True,
        "current_blend_default_alpha": 1.0,
        "current_blend_market_alpha": {
            "dallas": 0.0,
            "denver": 0.20,
            "houston": 0.20,
            "los-angeles": 0.20,
            "miami": 0.0,
            "nyc": 0.20,
            "san-francisco": 0.0,
            "seattle": 0.20,
        },
        "current_blend_context_alpha": [
            {
                "policy_id": "item232_current_max_trust_warm_tail_backoff_v0_1",
                "description": "Reduce warm-tail candidate weight when forecast-relative pressure is warm-side.",
                "forecast_bucket_pressure": "warm_side",
                "alpha": 0.35,
            },
            {
                "policy_id": "item232_current_max_trust_warm_tail_backoff_v0_1",
                "description": "Reduce warm-tail candidate weight when the band sits at least two degrees above the printed floor.",
                "band_mid_minus_high_so_far_min": 2.0,
                "alpha": 0.35,
            },
            {
                "policy_id": "item232_current_max_trust_warm_tail_backoff_v0_1",
                "description": "Use half candidate weight when current-max is support-only, quarantined, or pre-reset.",
                "current_max_disposition": ["support_only", "quarantined", "null_before_reset"],
                "alpha": 0.50,
            },
        ],
    }
    if exact_winner_catchup_enabled and exact_winner_shadow_blend:
        # Item 70 is a catch-up shadow lane. Keep incumbent blending disabled
        # except for markets that cleared paired full-replay guardrails.
        config["current_blend_default_alpha"] = 0.0
        config["current_blend_market_alpha"] = {
            "chicago": 0.10,
            "houston": 0.10,
            "nyc": 0.10,
            "seattle": 0.10,
        }
    return config


def apply_source_freshness_guardrail(
    artifact,
    policy_id="item35_all_fresh_only_candidate_v0_1",
):
    """Blend non-all-fresh replay rows fully back to incumbent serving."""
    postprocess = artifact.setdefault("postprocess", {})
    postprocess["current_blend_source_freshness_default_alpha"] = 0.0
    postprocess["current_blend_source_freshness_alpha"] = {
        "all_fresh": 1.0,
    }
    postprocess["source_freshness_guardrail_policy"] = policy_id
    for bundle in (artifact.get("models") or {}).values():
        bundle["postprocess"] = dict(postprocess)
    return artifact


def train_pooled_density_models(records, holdout_year=None, grid_step_f=0.1, min_sigma_validation_residuals=20):
    canonical_records = [
        row for row in canonical_density_records(records)
        if row.get("final_bucket_f") is not None
    ]
    by_hour = defaultdict(list)
    for row in canonical_records:
        by_hour[int(row["cutoff_hour"])].append(row)

    low_f, high_f = density_support_f(canonical_records)
    grid_f = canonical_grid_f(low_f, high_f, grid_step_f)
    artifact = {
        "schema_version": "pooled_continuous_density_hgb_v0.7",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": "all",
        "prediction_mode": "continuous_density_f",
        "objective": "canonical_f_density_shape_holdout_forecast_relative_band_postprocess",
        "trained_at": datetime.now().isoformat(),
        "grid_low_f": low_f,
        "grid_high_f": high_f,
        "grid_step_f": float(grid_step_f),
        "sigma_policy": {
            "preferred": "holdout_market_band_brier_grid_search",
            "fallback": "in_sample_residual_rmse",
            "min_validation_residuals": int(min_sigma_validation_residuals),
            "candidate_scales": list(DENSITY_SIGMA_TUNING_SCALES),
        },
        "density_shape_policy": {
            "preferred": "holdout_market_band_brier_shape_grid_search",
            "fallback": "gaussian_in_sample_residual_rmse",
            "candidate_shape_ids": [
                density_shape_id(row)
                for row in DENSITY_SHAPE_TUNING_CANDIDATES
            ],
        },
        "blocked_validation": blocked_validation_audit(canonical_records),
        "models": {},
    }
    validation_rows = []
    density_calibration_rows = []
    density_calibration_probabilities = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_rows = hour_rows
            eval_rows = []
        else:
            train_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        if len(train_rows) < 20:
            continue
        model, imputer, feature_names, residuals, train_metrics = train_density_hour_model(train_rows)
        sigma_f = residual_sigma_f(residuals)
        eval_score = None
        baseline_eval_score = None
        market_scores = []
        eval_residuals = []
        sigma_tuning = None
        shape_tuning = None
        if eval_rows:
            eval_means = predict_density_means(
                model,
                imputer,
                feature_names,
                eval_rows,
            )
            eval_residuals = density_residuals_from_means(eval_rows, eval_means)
            baseline_eval_score = evaluate_density_sigma(eval_rows, eval_means, grid_f, sigma_f)
            sigma_tuning = tune_density_sigma_f(eval_rows, eval_means, grid_f, sigma_f)
            shape_tuning = tune_density_shape_policy(eval_rows, eval_means, grid_f, sigma_f)
            tuned_sigma_f = (
                (shape_tuning or {}).get("selected_sigma_f")
                if len(eval_residuals) >= int(min_sigma_validation_residuals)
                else None
            )
            tuned_shape = (
                (shape_tuning or {}).get("selected_density_shape")
                if len(eval_residuals) >= int(min_sigma_validation_residuals)
                else None
            )
            eval_sigma_f = tuned_sigma_f if tuned_sigma_f is not None else sigma_f
            eval_shape = density_shape_config(tuned_shape)
            eval_score = evaluate_density_sigma(
                eval_rows,
                eval_means,
                grid_f,
                eval_sigma_f,
                shape_config=eval_shape,
            )
            post_rows, post_probabilities = density_projected_market_band_rows_and_probabilities(
                eval_rows,
                eval_means,
                grid_f,
                eval_sigma_f,
                shape_config=eval_shape,
            )
            density_calibration_rows.extend(post_rows)
            density_calibration_probabilities.extend(post_probabilities)
            for market_id in sorted({row["market_id"] for row in eval_rows}):
                subset = [
                    (row, mean)
                    for row, mean in zip(eval_rows, eval_means)
                    if row["market_id"] == market_id
                ]
                score = evaluate_density_sigma(
                    [row for row, _ in subset],
                    [mean for _, mean in subset],
                    grid_f,
                    eval_sigma_f,
                    shape_config=eval_shape,
                )
                if score:
                    market_scores.append({
                        "market_id": market_id,
                        "density_shape_id": eval_shape["id"],
                        **score,
                    })

        final_model, final_imputer, final_feature_names, final_residuals, final_metrics = train_density_hour_model(hour_rows)
        if len(eval_residuals) >= int(min_sigma_validation_residuals) and (shape_tuning or {}).get("selected_sigma_f"):
            final_sigma_source = "holdout_market_band_brier_shape_grid_search"
            final_sigma_residuals = eval_residuals
            final_sigma_f = float(shape_tuning["selected_sigma_f"])
            final_density_shape = density_shape_config(shape_tuning.get("selected_density_shape"))
            final_density_shape_source = "holdout_market_band_brier_shape_grid_search"
        else:
            final_sigma_source = "in_sample_residual_rmse"
            final_sigma_residuals = final_residuals
            final_sigma_f = residual_sigma_f(final_sigma_residuals)
            final_density_shape = density_shape_config(DENSITY_DEFAULT_SHAPE)
            final_density_shape_source = "gaussian_fallback"
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "train_rows": len(hour_rows),
            "sigma_f": final_sigma_f,
            "sigma_source": final_sigma_source,
            "sigma_residual_count": len(final_sigma_residuals),
            "density_shape_id": final_density_shape["id"],
            "density_shape": final_density_shape,
            "density_shape_source": final_density_shape_source,
            "sigma_tuning": sigma_tuning,
            "density_shape_tuning": shape_tuning,
            "training_metrics": final_metrics,
        }
        validation_rows.append({
            "hour": hour,
            "train_rows": len(train_rows),
            "eval_rows": len(eval_rows),
            "sigma_f": sigma_f,
            "final_sigma_f": final_sigma_f,
            "final_sigma_source": final_sigma_source,
            "final_sigma_residual_count": len(final_sigma_residuals),
            "final_density_shape_id": final_density_shape["id"],
            "final_density_shape_source": final_density_shape_source,
            "holdout_sigma_residual_count": len(eval_residuals),
            "eval_score": eval_score,
            "baseline_eval_score": baseline_eval_score,
            "sigma_tuning": sigma_tuning,
            "density_shape_tuning": shape_tuning,
            "market_scores": market_scores,
            "training_metrics": train_metrics,
            "blocked_validation": blocked_validation_audit(hour_rows),
        })
    if density_calibration_rows:
        artifact["density_postprocess"] = fit_density_market_band_postprocess(
            density_calibration_rows,
            density_calibration_probabilities,
        )
    else:
        artifact["density_postprocess"] = {
            "schema_version": "density_market_band_postprocess_v0.2",
            "enabled": False,
            "calibration_rows": 0,
            "reason": "no holdout market-band calibration rows",
        }
    return artifact, validation_rows


def train_pooled_band_models(
    records,
    holdout_year=None,
    exact_winner_catchup=False,
    dynamic_source_state=False,
    feature_subset=FEATURE_SUBSET_ALL,
    weak_family_disposition=None,
    reanalysis_promotion_lane=None,
    family_unit="F",
    source_freshness_guardrail=False,
    write_merge_payload=False,
    production_preselection=None,
    production_outer_min_train_dates=14,
    production_inner_min_train_dates=7,
    production_embargo_days=3,
    production_step_dates=7,
    production_max_fold_scopes=POOLED_PIT_MAX_FOLD_SCOPES,
    production_private_memory_budget_bytes=4 * 1024**3,
):
    if exact_winner_catchup and dynamic_source_state:
        raise ValueError("exact_winner_catchup and dynamic_source_state are separate shadow variants")
    feature_subset = feature_subset or FEATURE_SUBSET_ALL
    if feature_subset not in FEATURE_SUBSET_CHOICES:
        raise ValueError(f"Unknown pooled feature subset: {feature_subset}")
    if feature_subset != FEATURE_SUBSET_ALL and (exact_winner_catchup or dynamic_source_state):
        raise ValueError("feature subsets are separate candidate lanes from exact/dynamic source variants")
    records = list(records)
    verified_preselection = None
    production_static_context = None
    excluded_locked_row_count = 0
    if production_preselection is not None:
        verified_preselection = (
            load_production_point_in_time_preselection_from_payload(
                production_preselection
            )
        )
        locked_dates = set(
            verified_preselection["window_lock"]["target_dates"]
        )
        universe_dates = set(
            verified_preselection["selection_universe"]["fleet_dates"]
        )
        source_dates = {_pooled_pit_target_date(row) for row in records}
        training_dates = universe_dates - locked_dates
        if source_dates != training_dates:
            raise ValueError(
                "pooled production source rows differ from the prelocked training universe"
            )
        excluded_locked_row_count = 0
        if not records:
            raise ValueError(
                "no pooled training rows remain after excluding the locked window"
            )
        rows_per_date = Counter(
            _pooled_pit_target_date(row) for row in records
        )
        if max(rows_per_date.values(), default=0) > (
            POOLED_PIT_MAX_TRAINING_SOURCE_ROWS_PER_MARKET_DAY
        ):
            raise ValueError(
                "pooled production source rows exceed the per-market-day bound"
            )
        records = _pooled_pit_apply_production_feature_policy(records)
        production_static_context = _pooled_pit_static_context(
            records,
            verified_preselection,
        )
        if write_merge_payload:
            raise ValueError(
                "production point-in-time fitting cannot write legacy holdout merge payloads"
            )
    by_hour = defaultdict(list)
    for row in records:
        by_hour[int(row["cutoff_hour"])].append(row)

    support = band_training_support(records, family_unit=family_unit)
    all_market_band = str(family_unit or "").lower() == "all"
    schema_version = (
        "pooled_all_market_band_hgb_v0.1"
        if all_market_band else
        "pooled_feature_band_hgb_v0.3"
    )
    objective = (
        "binary_native_market_band_brier_all_market_source_reliability"
        if all_market_band else
        "binary_market_band_brier_source_reliability"
    )
    if exact_winner_catchup:
        schema_version = (
            "pooled_all_market_band_hgb_exact_winner_v0.1"
            if all_market_band else
            "pooled_feature_band_hgb_v0.4"
        )
        objective = (
            "binary_native_market_band_brier_all_market_exact_winner_catchup"
            if all_market_band else
            "binary_market_band_brier_source_reliability_exact_winner_catchup"
        )
    if dynamic_source_state:
        schema_version = "pooled_feature_band_hgb_v0.5"
        objective = "binary_market_band_brier_dynamic_source_state"
    if feature_subset == FEATURE_SUBSET_FORECAST_PROFILE:
        schema_version = "pooled_feature_band_hgb_forecast_profile_v0.1"
        objective = "binary_market_band_brier_forecast_profile_calibrated"
    if feature_subset == FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION:
        schema_version = "pooled_feature_band_hgb_forecast_radiation_v0.1"
        objective = "binary_market_band_brier_forecast_radiation_calibrated"
    if feature_subset == FEATURE_SUBSET_MARINE_WATER_CONTRAST:
        schema_version = "pooled_feature_band_hgb_marine_contrast_v0.1"
        objective = "binary_market_band_brier_marine_water_contrast"
    artifact = {
        "schema_version": schema_version,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": family_unit,
        "prediction_mode": "band_binary",
        "objective": objective,
        "feature_subset": feature_subset,
        "feature_subset_contract": feature_subset_contract(feature_subset),
        "dynamic_source_state_enabled": bool(dynamic_source_state),
        "dynamic_source_state_columns": (
            DYNAMIC_SOURCE_NUMERIC_COLUMNS + DYNAMIC_SOURCE_CATEGORICAL_COLUMNS
            if dynamic_source_state else []
        ),
        "trained_at": datetime.now().isoformat(),
        "support": support,
        "blocked_validation": blocked_validation_audit(records),
        "models": {},
        "postprocess": default_band_postprocess(
            exact_winner_catchup_enabled=exact_winner_catchup,
            exact_winner_shadow_blend=not all_market_band,
        ),
    }
    if production_static_context is not None:
        artifact["production_static_context"] = production_static_context
    # This legacy trainer has only one outer holdout.  Learned temperature,
    # adjacent, exact-winner, and market-bias transforms used to be fitted on
    # that same holdout and then reported on it.  Until a nested inner-OOF
    # implementation exists, the only honest served setting is identity.  The
    # standalone fit helpers remain available for explicitly diagnostic work,
    # but this artifact writer must never serialize their same-holdout output.
    artifact["postprocess"].update({
        "adjacent_calibration_enabled": False,
        "adjacent_calibration": {},
        "exact_winner_catchup_enabled": False,
        "exact_winner_catchup": {},
        "market_bias_calibration_enabled": False,
        "market_bias_calibration": {},
    })
    artifact["postprocess_fit_contract"] = {
        "schema_version": "legacy_pooled_postprocess_fit_contract_v1",
        "status": "PASS",
        "policy": "identity_until_nested_inner_oof",
        "outer_holdout_used_for_parameter_fit": False,
        "outer_holdout_fit_rows": 0,
        "served_parameters": {
            "temperature": 1.0,
            "adjacent_calibration": "identity_disabled",
            "exact_winner_catchup": "identity_disabled",
            "market_bias_calibration": "identity_disabled",
        },
        "requested_diagnostic_lanes": {
            "exact_winner_catchup": bool(exact_winner_catchup),
        },
        "promotion_permission": "forbidden_without_nested_inner_oof_receipts",
    }
    production_training_evidence = None
    if feature_subset == FEATURE_SUBSET_FORECAST_PROFILE:
        artifact["forecast_profile_calibration"] = {
            "schema_version": "forecast_profile_calibration_v0.1",
            "status": "shadow_candidate",
            "anchor_feature": "forecast_high",
            "feature_subset": feature_subset,
            "daily_first_replay_required": True,
            "promotion_blocker": (
                "Forecast-profile weighting cannot promote unless replay "
                "proves early-day lift, midday/late guardrails, and "
                "per-market high-disagreement safety."
            ),
        }
    if feature_subset == FEATURE_SUBSET_FORECAST_CLOUD_SOLAR_RADIATION:
        artifact["forecast_radiation_calibration"] = {
            "schema_version": "forecast_radiation_calibration_v0.1",
            "status": "shadow_candidate",
            "anchor_feature": "forecast_high",
            "feature_subset": feature_subset,
            "daily_first_replay_required": True,
            "promotion_blocker": (
                "Forecast-radiation weighting cannot promote unless replay "
                "proves early/midday lift, late guardrails, and market safety."
            ),
        }
    if feature_subset == FEATURE_SUBSET_MARINE_WATER_CONTRAST:
        artifact["marine_contrast_calibration"] = {
            "schema_version": "marine_contrast_calibration_v0.1",
            "status": "shadow_candidate",
            "anchor_feature": "marine_water_minus_forecast_high",
            "feature_subset": feature_subset,
            "onshore_breeze_replay_required": True,
            "promotion_blocker": (
                "Marine contrast cannot promote unless a scoped settlement "
                "replay proves onshore/breeze-slice lift with no aggregate "
                "regression."
            ),
        }
    if dynamic_source_state:
        artifact["postprocess"]["current_blend_source_freshness_default_alpha"] = 0.0
        artifact["postprocess"]["current_blend_source_freshness_alpha"] = {
            "all_fresh": 1.0,
            "failed:local_history": 1.0,
            "failed:metar,wu_history": 1.0,
            "failed:wu_history;stale:metar": 1.0,
            "stale:metar": 1.0,
            "failed:metar": 0.0,
            "failed:wu_history": 0.0,
        }
        artifact["postprocess"]["current_blend_market_alpha"] = {
            **(artifact["postprocess"].get("current_blend_market_alpha") or {}),
            "miami": 0.0,
        }
    if source_freshness_guardrail:
        apply_source_freshness_guardrail(artifact)
    apply_reanalysis_lane_metadata(artifact, reanalysis_promotion_lane)
    if verified_preselection is not None:
        production_training_evidence = (
            build_pooled_point_in_time_training_evidence(
                records,
                verified_preselection,
                family_unit=family_unit,
                include_dynamic_source_state=dynamic_source_state,
                feature_subset=feature_subset,
                postprocess_config=artifact["postprocess"],
                outer_min_train_dates=production_outer_min_train_dates,
                inner_min_train_dates=production_inner_min_train_dates,
                embargo_days=production_embargo_days,
                step_dates=production_step_dates,
                max_fold_scopes=production_max_fold_scopes,
                private_memory_budget_bytes=(
                    production_private_memory_budget_bytes
                ),
            )
        )
        production_training_evidence["locked_rows_excluded_before_support"] = (
            excluded_locked_row_count
        )
        artifact["postprocess_fit_contract"] = {
            **artifact["postprocess_fit_contract"],
            "schema_version": POOLED_NESTED_POSTPROCESS_SCHEMA_VERSION,
            "policy": "identity_parameters_with_real_nested_training_receipts",
            "fit_receipt_count": len(
                production_training_evidence["fit_receipts"]
            ),
            "preselection_hash": verified_preselection["preselection_hash"],
            "window_lock_id": verified_preselection["window_lock"][
                "window_lock_id"
            ],
            "locked_dates": list(
                verified_preselection["window_lock"]["target_dates"]
            ),
            "promotion_permission": (
                "requires_release_candidate_contract_verification"
            ),
        }
    validation_rows = []
    merge_payload_rows = []
    merge_payload_probabilities = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_source_rows = hour_rows
            eval_source_rows = []
        else:
            train_source_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_source_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        train_band_rows = build_band_rows(train_source_rows, support)
        if len(train_band_rows) < 200 or len({row["outcome"] for row in train_band_rows}) < 2:
            continue

        model, imputer, feature_names, train_metrics = train_band_hour_model(
            train_band_rows,
            include_dynamic_source_state=dynamic_source_state,
            feature_subset=feature_subset,
        )
        eval_score = None
        raw_eval_score = None
        temperature = 1.0
        tuned_brier = None
        market_scores = []
        eval_band_rows = []
        post_probs = []
        if eval_source_rows:
            eval_band_rows = build_band_rows(eval_source_rows, support)
            if eval_band_rows:
                raw_probs = predict_band_probabilities(
                    model,
                    imputer,
                    feature_names,
                    eval_band_rows,
                    temperature=1.0,
                )
                raw_eval_score = evaluate_band_predictions(eval_band_rows, raw_probs)
                # The outer holdout estimates performance only.  It never
                # selects a served transform.
                temperature = 1.0
                tuned_probs = [
                    temperature_scale_probability(probability, temperature=temperature)
                    for probability in raw_probs
                ]
                post_probs = [
                    apply_band_postprocessing(
                        probability,
                        row,
                        config=artifact["postprocess"],
                    )
                    for row, probability in zip(eval_band_rows, tuned_probs)
                ]
                if write_merge_payload:
                    merge_payload_rows.extend(eval_band_rows)
                    merge_payload_probabilities.extend(post_probs)
                eval_score = evaluate_band_predictions(eval_band_rows, post_probs)
                for market_id in sorted({row["market_id"] for row in eval_band_rows}):
                    subset = [
                        (row, probability)
                        for row, probability in zip(eval_band_rows, post_probs)
                        if row["market_id"] == market_id
                    ]
                    score = evaluate_band_predictions(
                        [row for row, _ in subset],
                        [probability for _, probability in subset],
                    )
                    if score:
                        market_scores.append({"market_id": market_id, **score})

        final_band_rows = build_band_rows(hour_rows, support)
        final_model, final_imputer, final_feature_names, final_metrics = train_band_hour_model(
            final_band_rows,
            include_dynamic_source_state=dynamic_source_state,
            feature_subset=feature_subset,
        )
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "classes": [int(value) for value in final_model.classes_],
            "train_rows": len(final_band_rows),
            "source_rows": len(hour_rows),
            "temperature": temperature,
            "postprocess": dict(artifact["postprocess"]),
            "training_metrics": final_metrics,
        }
        validation_rows.append({
            "hour": hour,
            "source_train_rows": len(train_source_rows),
            "band_train_rows": len(train_band_rows),
            "source_eval_rows": len(eval_source_rows),
            "temperature": temperature,
            "tuned_brier": tuned_brier,
            "raw_eval_score": raw_eval_score,
            "eval_score": eval_score,
            "market_scores": market_scores,
            "training_metrics": train_metrics,
            "blocked_validation": blocked_validation_audit(hour_rows),
            "postprocess_fit_contract": {
                "policy": "identity_until_nested_inner_oof",
                "outer_holdout_scored_rows": len(eval_band_rows),
                "outer_holdout_fit_rows": 0,
            },
        })
    for bundle in artifact["models"].values():
        bundle["postprocess"] = dict(artifact["postprocess"])
    model_feature_names = sorted({
        feature
        for bundle in artifact["models"].values()
        for feature in (bundle.get("feature_names") or [])
    })
    artifact["corpus_lineage"] = build_pooled_corpus_lineage(
        records,
        holdout_year=holdout_year,
        model_input_fields=model_feature_names,
    )
    artifact["weak_input_family_preflight"] = weak_input_training_preflight(
        model_feature_names,
        weak_family_disposition,
    )
    if write_merge_payload:
        artifact[BAND_MERGE_PAYLOAD_KEY] = {
            "holdout_year": holdout_year,
            "hours": sorted(int(hour) for hour in artifact["models"]),
            "rows": merge_payload_rows,
            "probabilities": merge_payload_probabilities,
        }
    if production_training_evidence is not None:
        artifact["point_in_time_training"] = (
            finalize_pooled_point_in_time_training_evidence(
                records,
                artifact,
                production_training_evidence,
            )
        )
        final_receipt = artifact["point_in_time_training"][
            "final_fit_receipt"
        ]
        artifact["postprocess_fit_contract"].update({
            "evidence_sha256": artifact["point_in_time_training"][
                "evidence_sha256"
            ],
            "final_fit_receipt_sha256": final_receipt["receipt_sha256"],
            "model_payload_sha256": final_receipt["model_payload_sha256"],
        })
        verify_pooled_point_in_time_training_evidence(artifact)
    return artifact, validation_rows


from weather.model.variant_prediction_runtime import predict_density_rows_for_bundle  # noqa: E402

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
