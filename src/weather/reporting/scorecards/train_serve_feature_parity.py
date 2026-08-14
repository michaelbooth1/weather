"""Standalone field-level train/serve feature parity gate.

This is deliberately separate from replay/serve probability parity.  The
training and serving feature builders are invoked independently from one
captured case, then every feature is compared across value, unit, category,
missingness, cutoff availability, and provenance.

The module has no network client and is not wired into release or serving.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from weather.experiment_contract import finalize_self_hash
from weather.io import write_json_atomic
from weather.market.market_registry import all_specs, spec_for_id
from weather.model.feature_store import (
    CURRENT_MAX_TRUST_FEATURE_COLUMNS,
    FEATURE_COLUMNS,
    FORECAST_FEATURE_COLUMNS,
    FORECAST_PROFILE_COLUMNS,
    build_historical_feature_record,
)
from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import data_path
from weather.schema_registry import schema_version
from weather.sources.forecast_history import load_forecast_daily, load_forecast_profiles


REPORT_SCHEMA_VERSION = schema_version("train_serve_feature_parity")
CASE_SCHEMA_VERSION = schema_version("train_serve_feature_parity_case")
REPORT_HASH_FIELD = "report_sha256"

CATEGORICAL_FEATURES = frozenset({"wind_group", "cloud_group"})
OBSERVATION_FEATURES = frozenset({
    "high_so_far",
    "current_temp",
    "rise_from_7am",
    "warming_rate_2h",
    "hours_at_peak",
    "dewpoint_c",
    "humidity",
    "pressure",
    "pressure_trend_3h",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "wind_shift_3h_degrees",
    "onshore_flow",
    "onshore_wind_speed_kmh",
    "lake_breeze_proxy",
    "minutes_since_cutoff",
    "live_reading_temp",
    "live_reading_minus_high",
    *CURRENT_MAX_TRUST_FEATURE_COLUMNS,
    *CATEGORICAL_FEATURES,
})
DAILY_FORECAST_FEATURES = frozenset(
    feature for feature in FORECAST_FEATURE_COLUMNS
    if feature not in FORECAST_PROFILE_COLUMNS
)
WU_SURFACE_FEATURES = frozenset({
    "rise_from_7am",
    "warming_rate_2h",
    "hours_at_peak",
    "dewpoint_c",
    "humidity",
    "pressure",
    "pressure_trend_3h",
    "wind_speed_kmh",
    "wind_group",
    "cloud_group",
})
STATION_SURFACE_FEATURES = frozenset({
    *WU_SURFACE_FEATURES,
    "wind_gust_kmh",
    "wind_shift_3h_degrees",
    "onshore_flow",
    "onshore_wind_speed_kmh",
    "lake_breeze_proxy",
})

EXPECTED_DIMENSIONS = (
    "value",
    "unit",
    "category",
    "missingness",
    "availability",
    "provenance",
)
PROVENANCE_FAILURE_STATES = frozenset({
    "discarded",
    "missing",
    "stitched",
    "unverified",
})


class TrainServeFeatureParityError(RuntimeError):
    """The standalone gate input or output contract is invalid."""


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if value in (None, ""):
        raise TrainServeFeatureParityError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrainServeFeatureParityError(
            f"{field} must be an ISO timestamp: {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise TrainServeFeatureParityError(f"{field} must be timezone-aware")
    return parsed


def _is_missing(value: Any) -> bool:
    if value is None or value == "":
        return True
    try:
        return bool(math.isnan(value))
    except (TypeError, ValueError):
        return False


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    return left == right


def _feature_unit(feature: str, market_unit: str) -> str:
    if feature in CATEGORICAL_FEATURES:
        return "category"
    if feature == "hours_at_peak" or feature.endswith("_hours"):
        return "hours"
    if feature == "minutes_since_cutoff" or feature.endswith("_minutes"):
        return "minutes"
    if "pressure" in feature and "vapour" not in feature:
        return "inHg" if market_unit == "F" else "hPa"
    if "wind_speed" in feature or "wind_gust" in feature:
        return "mph" if market_unit == "F" else "km/h"
    if "wind_shift" in feature:
        return "degrees"
    if any(token in feature for token in (
        "humidity",
        "cloud",
        "probability",
        "direct_radiation_share",
    )):
        return "percent_or_fraction"
    if any(token in feature for token in (
        "temp",
        "high",
        "gap",
        "rise",
        "warming_rate",
        "lapse",
        "water_minus",
        "cooling_potential",
    )):
        return market_unit
    if "radiation" in feature:
        return "W/m2-derived"
    if "precipitation" in feature or "et0" in feature:
        return "mm-derived"
    if "visibility" in feature:
        return "source_distance"
    if "aerosol_optical_depth" in feature:
        return "dimensionless"
    if "pm2_5" in feature or "pm10" in feature or "dust" in feature:
        return "ug/m3"
    return "dimensionless"


def _feature_group(feature: str) -> str:
    if feature in WU_SURFACE_FEATURES:
        return "wu_surface"
    if feature in FORECAST_PROFILE_COLUMNS:
        return "forecast_profile"
    if feature in DAILY_FORECAST_FEATURES:
        return "forecast_daily"
    if feature in OBSERVATION_FEATURES:
        return "observation"
    return "other"


def _metadata_for_record(
    record: Mapping[str, Any],
    *,
    cutoff_at: datetime,
    observation: Mapping[str, Any],
    forecast: Mapping[str, Any],
    profile: Mapping[str, Any],
    overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    overrides = overrides or {}
    result: dict[str, dict[str, Any]] = {}
    deterministic = {
        "source_id": "deterministic_feature_contract",
        "available_at": cutoff_at.isoformat(),
        "issue_time": None,
        "issue_time_required": False,
        "provenance_state": "verified",
    }
    for feature in FEATURE_COLUMNS:
        if feature in OBSERVATION_FEATURES:
            metadata = dict(observation)
        elif feature in FORECAST_PROFILE_COLUMNS:
            metadata = dict(profile)
        elif feature in DAILY_FORECAST_FEATURES:
            metadata = dict(forecast)
        else:
            metadata = dict(deterministic)
        metadata.update(overrides.get(feature) or {})
        result[feature] = metadata
    return result


def _cell(
    feature: str,
    value: Any,
    *,
    market_unit: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    missing = _is_missing(value)
    return {
        "value": None if missing else value,
        "unit": metadata.get("unit") or _feature_unit(feature, market_unit),
        "category": (
            None
            if missing
            else metadata.get("category")
            or (str(value) if feature in CATEGORICAL_FEATURES else "numeric")
        ),
        "missing": missing,
        "available_at": metadata.get("available_at"),
        "issue_time": metadata.get("issue_time"),
        "issue_time_required": bool(metadata.get("issue_time_required")),
        "source_id": metadata.get("source_id"),
        "provenance_state": metadata.get("provenance_state", "verified"),
    }


def _direction(training: Any, serving: Any) -> str:
    return f"training={training!r}; serving={serving!r}"


def _finding(
    *,
    case: Mapping[str, Any],
    feature: str,
    dimension: str,
    training: Any,
    serving: Any,
    direction: str | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "case_kind": case["kind"],
        "market_id": case["market_id"],
        "cutoff_at": case["cutoff_at"],
        "field": feature,
        "field_group": _feature_group(feature),
        "dimension": dimension,
        "training": training,
        "serving": serving,
        "direction": direction or _direction(training, serving),
        "disposition": "BLOCK",
    }


def compare_feature_records(
    *,
    case: Mapping[str, Any],
    training_record: Mapping[str, Any],
    serving_record: Mapping[str, Any],
    training_metadata: Mapping[str, Mapping[str, Any]],
    serving_metadata: Mapping[str, Mapping[str, Any]],
    features: Sequence[str] = FEATURE_COLUMNS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return field findings and missing-key coverage blockers for one case."""

    cutoff_at = _parse_timestamp(case["cutoff_at"], field="cutoff_at")
    market_unit = str(case["market_unit"])
    findings: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for feature in features:
        for path_name, record in (
            ("training", training_record),
            ("serving", serving_record),
        ):
            if feature not in record:
                coverage.append({
                    "case_id": case["case_id"],
                    "market_id": case["market_id"],
                    "path": path_name,
                    "field": feature,
                    "reason": "feature_key_absent",
                })
        train = _cell(
            feature,
            training_record.get(feature),
            market_unit=market_unit,
            metadata=training_metadata.get(feature) or {},
        )
        serve = _cell(
            feature,
            serving_record.get(feature),
            market_unit=market_unit,
            metadata=serving_metadata.get(feature) or {},
        )
        if train["missing"] != serve["missing"]:
            findings.append(_finding(
                case=case,
                feature=feature,
                dimension="missingness",
                training="missing" if train["missing"] else "present",
                serving="missing" if serve["missing"] else "present",
            ))
        if train["missing"] or serve["missing"]:
            continue
        if not _values_equal(train["value"], serve["value"]):
            findings.append(_finding(
                case=case,
                feature=feature,
                dimension="value",
                training=train["value"],
                serving=serve["value"],
            ))
        if train["unit"] != serve["unit"]:
            findings.append(_finding(
                case=case,
                feature=feature,
                dimension="unit",
                training=train["unit"],
                serving=serve["unit"],
            ))
        if train["category"] != serve["category"]:
            findings.append(_finding(
                case=case,
                feature=feature,
                dimension="category",
                training=train["category"],
                serving=serve["category"],
            ))

        for path_name, cell in (("training", train), ("serving", serve)):
            available_at = cell.get("available_at")
            if not available_at:
                findings.append(_finding(
                    case=case,
                    feature=feature,
                    dimension="availability",
                    training=("unverifiable" if path_name == "training" else "not_evaluated"),
                    serving=("unverifiable" if path_name == "serving" else "not_evaluated"),
                    direction=f"{path_name} availability is missing at cutoff",
                ))
            else:
                try:
                    available = _parse_timestamp(
                        available_at,
                        field=f"{path_name}.{feature}.available_at",
                    )
                except TrainServeFeatureParityError:
                    available = None
                    findings.append(_finding(
                        case=case,
                        feature=feature,
                        dimension="availability",
                        training=("invalid" if path_name == "training" else "not_evaluated"),
                        serving=("invalid" if path_name == "serving" else "not_evaluated"),
                        direction=f"{path_name} availability timestamp is invalid",
                    ))
                if available is not None and available.astimezone(timezone.utc) > cutoff_at.astimezone(timezone.utc):
                    findings.append(_finding(
                        case=case,
                        feature=feature,
                        dimension="availability",
                        training=(available_at if path_name == "training" else cutoff_at.isoformat()),
                        serving=(available_at if path_name == "serving" else cutoff_at.isoformat()),
                        direction=(
                            f"{path_name} became knowable at {available_at}, after cutoff "
                            f"{cutoff_at.isoformat()}"
                        ),
                    ))

            provenance_state = str(cell.get("provenance_state") or "missing")
            source_id = str(cell.get("source_id") or "").strip()
            provenance_reasons = []
            if provenance_state in PROVENANCE_FAILURE_STATES:
                provenance_reasons.append(f"state={provenance_state}")
            if not source_id:
                provenance_reasons.append("source_identity_missing")
            issue_time = cell.get("issue_time")
            if cell.get("issue_time_required"):
                if not issue_time:
                    provenance_reasons.append("issue_time_missing")
                else:
                    try:
                        issued = _parse_timestamp(
                            issue_time,
                            field=f"{path_name}.{feature}.issue_time",
                        )
                    except TrainServeFeatureParityError:
                        provenance_reasons.append("issue_time_invalid")
                    else:
                        if issued.astimezone(timezone.utc) > cutoff_at.astimezone(timezone.utc):
                            provenance_reasons.append("issue_time_after_cutoff")
            if provenance_reasons:
                findings.append(_finding(
                    case=case,
                    feature=feature,
                    dimension="provenance",
                    training=(
                        {"source_id": source_id or None, "reasons": provenance_reasons}
                        if path_name == "training" else "verified_or_not_evaluated"
                    ),
                    serving=(
                        {"source_id": source_id or None, "reasons": provenance_reasons}
                        if path_name == "serving" else "verified_or_not_evaluated"
                    ),
                    direction=f"{path_name}: {', '.join(provenance_reasons)}",
                ))
    return findings, coverage


def _safe_case_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,119}", text):
        raise TrainServeFeatureParityError(f"unsafe case_id: {value!r}")
    return text


def _ok(data: Mapping[str, Any]) -> dict[str, Any]:
    return {"ok": True, "stale": False, "data": dict(data)}


def _cutoff_for(case: Mapping[str, Any], market_id: str) -> datetime:
    spec = spec_for_id(market_id)
    target = date.fromisoformat(str(case["target_date"]))
    cutoff_hour = int(case["cutoff_hour"])
    wall_offset = int(case.get("wall_offset_minutes") or 0)
    return datetime.combine(target, time(cutoff_hour), tzinfo=spec.tz) + timedelta(minutes=wall_offset)


def _relative_timestamp(cutoff_at: datetime, offset_minutes: Any) -> str | None:
    if offset_minutes is None:
        return None
    return (cutoff_at + timedelta(minutes=float(offset_minutes))).isoformat()


def _observation_rows(case: Mapping[str, Any], market_unit: str) -> list[dict[str, Any]]:
    rows_by_unit = case.get("observations_by_unit") or {}
    rows = rows_by_unit.get(market_unit)
    if not isinstance(rows, list) or not rows:
        raise TrainServeFeatureParityError(
            f"{case.get('case_id')} has no observations for unit {market_unit}"
        )
    result = []
    for raw in rows:
        row = dict(raw)
        row["temp_native"] = row.pop("temp")
        row["dewpoint_native"] = row.pop("dewpoint", None)
        result.append(row)
    return result


def _historical_rows(model: TorontoHighTempModel, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for raw in rows:
        row = dict(raw)
        row["minute_of_day"] = model.minute_of_day(row.get("time"))
        result.append(row)
    return result


def _forecast_high(case: Mapping[str, Any], unit: str) -> float:
    values = case.get("forecast_high_by_unit") or {}
    try:
        return float(values[unit])
    except (KeyError, TypeError, ValueError) as exc:
        raise TrainServeFeatureParityError(
            f"{case.get('case_id')} has no forecast high for unit {unit}"
        ) from exc


def _base_training_record(
    *,
    case: Mapping[str, Any],
    model: TorontoHighTempModel,
    rows: Sequence[Mapping[str, Any]],
    forecast_high: float,
    forecast_profile_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    historical = _historical_rows(model, rows)
    record = build_historical_feature_record(
        local_date=str(case["target_date"]),
        rows=historical,
        daily={"bucket": max(model.row_temp_native(row) for row in historical)},
        cutoff_hour=int(case["cutoff_hour"]),
        forecast_high=forecast_high,
        forecast_profile_rows=forecast_profile_rows,
        wind_group_fn=model.wind_group,
        cloud_group_fn=model.cloud_group,
        microclimate_feature_fn=model.microclimate_features,
        wall_minute=int(case["cutoff_hour"]) * 60 + int(case.get("wall_offset_minutes") or 0),
        unit=model.spec.display_unit,
    )
    if record is None:
        raise TrainServeFeatureParityError(f"training builder returned no record for {case['case_id']}")
    return record


def _wu_sources(
    *,
    rows: Sequence[Mapping[str, Any]],
    forecast_high: float,
    profile_rows: Sequence[Mapping[str, Any]] | None = None,
    current_temp: float | None = None,
) -> dict[str, Any]:
    latest = dict(rows[-1])
    high = max(float(row["temp_native"]) for row in rows)
    current_temp = high if current_temp is None else current_temp
    open_meteo_rows = list(profile_rows or [])
    return {
        "wu_history": _ok({"rows": list(rows), "max_native": high}),
        "wu_current": _ok({
            "temp_native": current_temp,
            "max_since_7am_native": max(high, current_temp),
        }),
        "open_meteo": _ok({
            "rows": open_meteo_rows,
            "day_rows": open_meteo_rows,
            "day_max_native": forecast_high,
        }),
        "weather_forecast": _ok({"rows": []}),
        "eccc_citypage": _ok({}),
        "station_observations": _ok({
            "temp_native": latest.get("temp_native"),
            "max_since_7am_native": high,
        }),
    }


def _station_sources(
    *,
    rows: Sequence[Mapping[str, Any]],
    forecast_high: float,
) -> dict[str, Any]:
    latest = dict(rows[-1])
    high = max(float(row["temp_native"]) for row in rows)
    return {
        "metar": _ok({
            "rows": list(rows),
            "latest": latest,
            "temp_native": latest.get("temp_native"),
            "max_since_7am_native": high,
        }),
        "open_meteo": _ok({"rows": [], "day_rows": [], "day_max_native": forecast_high}),
        "weather_forecast": _ok({"rows": [{"condition": latest.get("condition") or "Fair"}]}),
        "eccc_citypage": _ok({}),
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise TrainServeFeatureParityError("cannot materialize an empty training projection")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({str(key) for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _build_case(
    raw_case: Mapping[str, Any],
    *,
    market_id: str,
    run_root: Path,
) -> dict[str, Any]:
    case = copy.deepcopy(dict(raw_case))
    base_id = _safe_case_id(case.get("case_id"))
    if case.get("market_ids") == "all_registered":
        case["case_id"] = f"{base_id}-{market_id}"
    else:
        case["case_id"] = base_id
    case["market_id"] = market_id
    spec = spec_for_id(market_id)
    case["market_unit"] = spec.display_unit
    cutoff_at = _cutoff_for(case, market_id)
    case["cutoff_at"] = cutoff_at.isoformat()
    rows = _observation_rows(case, spec.display_unit)
    forecast_high = _forecast_high(case, spec.display_unit)
    model = TorontoHighTempModel(
        target_date=str(case["target_date"]),
        market_id=market_id,
    )

    obs_available = _relative_timestamp(
        cutoff_at,
        case.get("observation_available_offset_minutes", -5),
    )
    forecast_available = _relative_timestamp(
        cutoff_at,
        case.get("forecast_available_offset_minutes", -60),
    )
    forecast_issue = _relative_timestamp(
        cutoff_at,
        case.get("forecast_issue_offset_minutes", -360),
    )
    observation_train = {
        "source_id": "wu_history_training_archive",
        "available_at": obs_available,
        "issue_time": None,
        "issue_time_required": False,
        "provenance_state": "verified",
    }
    observation_serve = {
        "source_id": "wu_history",
        "available_at": obs_available,
        "issue_time": None,
        "issue_time_required": False,
        "provenance_state": "verified",
    }
    forecast_train = {
        "source_id": "open_meteo_historical_forecast",
        "available_at": forecast_available,
        "issue_time": forecast_issue,
        "issue_time_required": True,
        "provenance_state": "verified",
    }
    forecast_serve = {
        "source_id": "open_meteo",
        "available_at": forecast_available,
        "issue_time": forecast_issue,
        "issue_time_required": True,
        "provenance_state": "verified",
    }
    profile_train = dict(forecast_train)
    profile_serve = dict(forecast_serve)
    kind = str(case.get("kind") or "")
    feature_scope: Sequence[str] = FEATURE_COLUMNS

    if kind == "baseline_full_contract":
        training = _base_training_record(
            case=case,
            model=model,
            rows=rows,
            forecast_high=forecast_high,
        )
        serving = model.extract_live_features(
            _wu_sources(rows=rows, forecast_high=forecast_high),
            int(case["cutoff_hour"]),
            now=cutoff_at,
        )
    elif kind == "station_surface_contract":
        training = _base_training_record(
            case=case,
            model=model,
            rows=rows,
            forecast_high=forecast_high,
        )
        serving = model.extract_live_features(
            _station_sources(rows=rows, forecast_high=forecast_high),
            int(case["cutoff_hour"]),
            now=cutoff_at,
        )
        observation_serve["source_id"] = "metar"
        feature_scope = sorted(STATION_SURFACE_FEATURES)
    elif kind == "wu_surface_availability":
        training = _base_training_record(
            case=case,
            model=model,
            rows=rows,
            forecast_high=forecast_high,
        )
        serving = model.extract_live_features(
            _wu_sources(rows=rows, forecast_high=forecast_high),
            int(case["cutoff_hour"]),
            now=cutoff_at,
        )
        future_available = _relative_timestamp(
            cutoff_at,
            case.get("observation_available_offset_minutes", 1_415),
        )
        observation_train["available_at"] = future_available
        observation_serve["available_at"] = future_available
        feature_scope = sorted(WU_SURFACE_FEATURES)
    elif kind == "forecast_daily_contract":
        daily_path = run_root / "_inputs" / f"{case['case_id']}-forecast-daily.csv"
        _write_csv(daily_path, [{
            "local_date": case["target_date"],
            "forecast_high_native": forecast_high,
            "source": "stitched_continuous_archive",
        }])
        loaded_high = load_forecast_daily(daily_path).get(str(case["target_date"]))
        training = _base_training_record(
            case=case,
            model=model,
            rows=rows,
            forecast_high=loaded_high,
        )
        serving = model.extract_live_features(
            _wu_sources(rows=rows, forecast_high=forecast_high),
            int(case["cutoff_hour"]),
            now=cutoff_at,
        )
        forecast_train = {
            "source_id": "stitched_continuous_archive",
            "available_at": None,
            "issue_time": None,
            "issue_time_required": True,
            "provenance_state": "stitched",
        }
        feature_scope = ("forecast_high", "forecast_gap")
    elif kind == "forecast_profile_contract":
        raw_profile = []
        for row in case.get("forecast_profile_rows") or []:
            item = dict(row)
            item.setdefault("target_date", case["target_date"])
            item.setdefault("source", "open_meteo_historical_forecast")
            item.setdefault("source_model", "gfs_seamless")
            item.setdefault("issue_time", forecast_issue)
            item.setdefault("issue_time_basis", "provider_run")
            item.setdefault("payload_sha256", "a" * 64)
            raw_profile.append(item)
        profile_path = run_root / "_inputs" / f"{case['case_id']}-forecast-profile.csv"
        _write_csv(profile_path, raw_profile)
        loaded_by_date = load_forecast_profiles(profile_path)
        loaded_profile = loaded_by_date.get(str(case["target_date"])) or []
        training = _base_training_record(
            case=case,
            model=model,
            rows=rows,
            forecast_high=forecast_high,
            forecast_profile_rows=loaded_profile,
        )
        live_profile = []
        for raw in raw_profile:
            live_profile.append({
                "time": raw.get("valid_time"),
                "temp_native": raw.get("target_temp_native"),
                "cloud_cover": raw.get("cloud_cover"),
                "low_cloud": raw.get("low_cloud"),
                "mid_cloud": raw.get("mid_cloud"),
                "high_cloud": raw.get("high_cloud"),
                "solar": raw.get("shortwave_radiation"),
                "direct_radiation": raw.get("direct_radiation"),
                "diffuse_radiation": raw.get("diffuse_radiation"),
            })
        serving = model.extract_live_features(
            _wu_sources(
                rows=rows,
                forecast_high=forecast_high,
                profile_rows=live_profile,
            ),
            int(case["cutoff_hour"]),
            now=cutoff_at,
        )
        first_loaded = loaded_profile[0] if loaded_profile else {}
        profile_train = {
            "source_id": first_loaded.get("source"),
            "available_at": first_loaded.get("retrieved_at_utc"),
            "issue_time": first_loaded.get("issue_time"),
            "issue_time_required": True,
            "provenance_state": "discarded",
        }
        profile_serve = {
            "source_id": raw_profile[0].get("source") if raw_profile else None,
            "available_at": forecast_available,
            "issue_time": raw_profile[0].get("issue_time") if raw_profile else None,
            "issue_time_required": True,
            "provenance_state": "verified",
        }
        feature_scope = tuple(FORECAST_PROFILE_COLUMNS)
    elif kind == "trusted_floor_exception":
        training = _base_training_record(
            case=case,
            model=model,
            rows=rows,
            forecast_high=forecast_high,
        )
        floor_sources = _station_sources(rows=rows, forecast_high=forecast_high)
        floor_value = max(float(row["temp_native"]) for row in rows) + float(
            case.get("floor_lead_native") or 1.0
        )
        floor_sources["metar"]["data"]["latest"]["temp_native"] = floor_value
        floor_sources["metar"]["data"]["temp_native"] = floor_value
        floor_sources["metar"]["data"]["max_since_7am_native"] = floor_value
        serving = model.extract_live_features(
            floor_sources,
            int(case["cutoff_hour"]),
            now=cutoff_at,
        )
        observation_serve["source_id"] = "metar"
        feature_scope = ("high_so_far",)
    else:
        raise TrainServeFeatureParityError(f"unsupported case kind: {kind!r}")
    if not isinstance(serving, Mapping):
        raise TrainServeFeatureParityError(f"serving builder returned no record for {case['case_id']}")

    training_metadata = _metadata_for_record(
        training,
        cutoff_at=cutoff_at,
        observation=observation_train,
        forecast=forecast_train,
        profile=profile_train,
    )
    serving_metadata = _metadata_for_record(
        serving,
        cutoff_at=cutoff_at,
        observation=observation_serve,
        forecast=forecast_serve,
        profile=profile_serve,
    )
    return {
        "case": case,
        "training_record": dict(training),
        "serving_record": dict(serving),
        "training_metadata": training_metadata,
        "serving_metadata": serving_metadata,
        "feature_scope": tuple(feature_scope),
    }


def _rule_matches(rule: Mapping[str, Any], finding: Mapping[str, Any]) -> bool:
    if rule.get("case_kind") and rule["case_kind"] != finding.get("case_kind"):
        return False
    if rule.get("dimension") and rule["dimension"] != finding.get("dimension"):
        return False
    if rule.get("dimensions") and finding.get("dimension") not in set(rule["dimensions"]):
        return False
    if rule.get("fields") and finding.get("field") not in set(rule["fields"]):
        return False
    if rule.get("field_group") and rule["field_group"] != finding.get("field_group"):
        return False
    return True


def _valid_exception(row: Mapping[str, Any]) -> bool:
    required = {
        "case_id",
        "market_id",
        "field",
        "dimension",
        "reason",
        "owner",
        "evidence",
        "review_after",
    }
    if not required.issubset(row):
        return False
    exact = (row["case_id"], row["market_id"], row["field"], row["dimension"])
    if any(value in (None, "", "*") for value in exact):
        return False
    try:
        date.fromisoformat(str(row["review_after"]))
    except ValueError:
        return False
    return True


def _apply_exceptions(
    findings: list[dict[str, Any]],
    exceptions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    invalid = [dict(row) for row in exceptions if not _valid_exception(row)]
    if invalid:
        raise TrainServeFeatureParityError(
            "exceptions must be exact, owned, evidenced, and review-dated"
        )
    by_key = {
        (row["case_id"], row["market_id"], row["field"], row["dimension"]): row
        for row in exceptions
    }
    for finding in findings:
        key = (
            finding["case_id"],
            finding["market_id"],
            finding["field"],
            finding["dimension"],
        )
        exception = by_key.get(key)
        if exception:
            finding["disposition"] = "EXCEPTED"
            finding["exception"] = dict(exception)
    return findings


def _classify_ground_truth(
    findings: list[dict[str, Any]],
    rules: Sequence[Mapping[str, Any]],
    expected_market_ids: Sequence[str],
) -> list[dict[str, Any]]:
    results = []
    for rule in rules:
        matched = [finding for finding in findings if _rule_matches(rule, finding)]
        for finding in matched:
            finding.setdefault("known_defect_id", rule.get("defect_id"))
        required_fields = set(rule.get("required_fields") or [])
        found_fields = {finding["field"] for finding in matched}
        required_markets = (
            set(expected_market_ids)
            if rule.get("required_market_coverage") == "all_registered"
            else set(rule.get("required_markets") or [])
        )
        found_markets = {finding["market_id"] for finding in matched}
        minimum = int(rule.get("minimum_findings") or 1)
        rediscovered = (
            len(matched) >= minimum
            and required_fields.issubset(found_fields)
            and required_markets.issubset(found_markets)
        )
        results.append({
            "defect_id": rule.get("defect_id"),
            "rediscovered": rediscovered,
            "finding_count": len(matched),
            "required_fields": sorted(required_fields),
            "found_fields": sorted(found_fields),
            "required_markets": sorted(required_markets),
            "found_markets": sorted(found_markets),
        })
    return results


def evaluate_manifest(
    payload: Mapping[str, Any],
    *,
    run_root: str | Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Run the standalone gate from one deterministic captured-case manifest."""

    if payload.get("schema_version") != CASE_SCHEMA_VERSION:
        raise TrainServeFeatureParityError(
            f"case manifest must use {CASE_SCHEMA_VERSION}"
        )
    root = Path(run_root).resolve()
    data_root = data_path().resolve()
    if root == data_root or data_root in root.parents:
        raise TrainServeFeatureParityError("run_root must be outside data/")
    root.mkdir(parents=True, exist_ok=True)
    expected_market_ids = sorted(spec.id for spec in all_specs())
    built_cases = []
    defaults = dict(payload.get("case_defaults") or {})
    for declared_case in payload.get("cases") or []:
        raw_case = {**defaults, **dict(declared_case)}
        market_selector = raw_case.get("market_ids")
        if market_selector == "all_registered":
            market_ids = expected_market_ids
        elif isinstance(market_selector, list):
            market_ids = [str(value) for value in market_selector]
        else:
            market_ids = [str(raw_case.get("market_id") or "")]
        for market_id in market_ids:
            if market_id not in expected_market_ids:
                raise TrainServeFeatureParityError(
                    f"case references unregistered market: {market_id!r}"
                )
            built_cases.append(_build_case(raw_case, market_id=market_id, run_root=root))

    findings: list[dict[str, Any]] = []
    coverage_blockers: list[dict[str, Any]] = []
    covered_markets = set()
    compared_features = set()
    compared_cells = 0
    both_missing_cells = 0
    for built in built_cases:
        case = built["case"]
        covered_markets.add(case["market_id"])
        scope = built["feature_scope"]
        compared_features.update(scope)
        compared_cells += len(scope)
        both_missing_cells += sum(
            _is_missing(built["training_record"].get(feature))
            and _is_missing(built["serving_record"].get(feature))
            for feature in scope
        )
        case_findings, case_coverage = compare_feature_records(
            case=case,
            training_record=built["training_record"],
            serving_record=built["serving_record"],
            training_metadata=built["training_metadata"],
            serving_metadata=built["serving_metadata"],
            features=scope,
        )
        findings.extend(case_findings)
        coverage_blockers.extend(case_coverage)

    missing_markets = sorted(set(expected_market_ids) - covered_markets)
    # Every-feature coverage is established only by cases that compare the
    # complete schema, not by a specialized subset case.
    full_schema_markets = {
        built["case"]["market_id"]
        for built in built_cases
        if tuple(built["feature_scope"]) == tuple(FEATURE_COLUMNS)
    }
    missing_full_schema_markets = sorted(set(expected_market_ids) - full_schema_markets)
    if missing_markets:
        coverage_blockers.append({"reason": "registered_markets_missing", "markets": missing_markets})
    if missing_full_schema_markets:
        coverage_blockers.append({
            "reason": "full_feature_schema_market_coverage_missing",
            "markets": missing_full_schema_markets,
        })

    findings = _apply_exceptions(findings, payload.get("exceptions") or [])
    ground_truth = _classify_ground_truth(
        findings,
        payload.get("ground_truth") or [],
        expected_market_ids,
    )
    known_ids = {row["defect_id"] for row in ground_truth}
    classified_ids = {
        finding.get("known_defect_id")
        for finding in findings
        if finding.get("known_defect_id")
    }
    unexpected = [
        finding for finding in findings
        if finding.get("disposition") == "BLOCK"
        and not finding.get("known_defect_id")
    ]
    blocking = [finding for finding in findings if finding.get("disposition") == "BLOCK"]
    exceptions = [finding for finding in findings if finding.get("disposition") == "EXCEPTED"]
    generated_at = generated_at or datetime.now(timezone.utc)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "report_type": "train_serve_feature_parity",
        "generated_at_utc": generated_at.astimezone(timezone.utc).isoformat(),
        "mode": "standalone_no_network_no_fit_no_release_binding",
        "status": "BLOCK" if blocking or coverage_blockers else "PASS",
        "summary": {
            "case_count": len(built_cases),
            "registered_market_count": len(expected_market_ids),
            "covered_market_count": len(covered_markets),
            "feature_count": len(FEATURE_COLUMNS),
            "compared_feature_count": len(compared_features),
            "compared_cells": compared_cells,
            "both_missing_cells": both_missing_cells,
            "finding_count": len(findings),
            "blocking_finding_count": len(blocking),
            "exception_count": len(exceptions),
            "unexpected_blocking_finding_count": len(unexpected),
            "coverage_blocker_count": len(coverage_blockers),
            "known_defect_count": len(known_ids),
            "known_defects_rediscovered": sum(row["rediscovered"] for row in ground_truth),
            "all_known_defects_rediscovered": bool(ground_truth) and all(
                row["rediscovered"] for row in ground_truth
            ),
        },
        "coverage": {
            "expected_market_ids": expected_market_ids,
            "covered_market_ids": sorted(covered_markets),
            "full_schema_market_ids": sorted(full_schema_markets),
            "feature_names": list(FEATURE_COLUMNS),
            "dimensions": list(EXPECTED_DIMENSIONS),
            "blockers": coverage_blockers,
        },
        "known_defect_proof": ground_truth,
        "unexpected_findings": unexpected,
        "false_positive_characterization": {
            "explicit_exception_findings": exceptions,
            "both_missing_cells": both_missing_cells,
            "note": (
                "Both-missing cells are reported as unobserved coverage, not equality proof. "
                "Only exact, owned, evidenced, review-dated exceptions are suppressible."
            ),
        },
        "finding_counts_by_dimension": dict(sorted(Counter(
            finding["dimension"] for finding in findings
        ).items())),
        "finding_counts_by_field": dict(sorted(Counter(
            finding["field"] for finding in findings
        ).items())),
        "findings": findings,
        "input_identity": {
            "case_schema_version": payload.get("schema_version"),
            "declared_name": payload.get("name"),
            "case_manifest_sha256": _canonical_sha256(payload),
            "ground_truth_ids": sorted(known_ids),
            "classified_ground_truth_ids": sorted(classified_ids),
        },
        "binding_proposal": {
            "initial_severity": "advisory",
            "blocking_transition": (
                "Block active-artifact fields after one representative capture cycle per "
                "registered market/cutoff and review of unexpected findings; provenance or "
                "future-known failures on populated forecast fields should then block immediately."
            ),
            "exception_semantics": (
                "Exact case/market/field/dimension only; named owner, contract evidence, reason, "
                "and review date required. Wildcards and exceptions for discarded provenance or "
                "future-known inputs are invalid."
            ),
        },
    }
    return finalize_self_hash(report, hash_field=REPORT_HASH_FIELD)


def render_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    unexpected = report.get("unexpected_findings") or []
    lines = [
        "# Train/serve feature parity gate",
        "",
        "## Previously unknown findings",
        "",
    ]
    if unexpected:
        for finding in unexpected[:30]:
            lines.append(
                "- `{market_id}` `{field}` at `{cutoff_at}`: **{dimension}** â€” {direction}".format(
                    **finding
                )
            )
        if len(unexpected) > 30:
            lines.append(f"- â€¦ {len(unexpected) - 30} additional rows are in the JSON report.")
    else:
        lines.append("No previously unknown blocking defect was established by this deterministic proof.")
    lines.extend([
        "",
        "## Verdict",
        "",
        f"**{report.get('status')}** â€” {summary.get('blocking_finding_count', 0)} blocking findings; "
        f"{summary.get('known_defects_rediscovered', 0)} / {summary.get('known_defect_count', 0)} "
        "known defects rediscovered.",
        "",
        "This is standalone evidence only: no fit, retrain, candidate, network, serving, or release-path action occurred.",
        "",
        "## Coverage",
        "",
        "| Cases | Registered markets | Full-schema markets | Features | Cells | Both missing |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        "| {case_count} | {covered_market_count}/{registered_market_count} | {full_schema}/{registered_market_count} | "
        "{compared_feature_count}/{feature_count} | {compared_cells} | {both_missing_cells} |".format(
            full_schema=len((report.get("coverage") or {}).get("full_schema_market_ids") or []),
            **summary,
        ),
        "",
        "## Known-defect proof",
        "",
        "| Defect | Rediscovered | Findings | Fields found | Markets found |",
        "| --- | --- | ---: | ---: | ---: |",
    ])
    for row in report.get("known_defect_proof") or []:
        lines.append(
            f"| `{row.get('defect_id')}` | {'YES' if row.get('rediscovered') else 'NO'} | "
            f"{row.get('finding_count')} | {len(row.get('found_fields') or [])} | "
            f"{len(row.get('found_markets') or [])} |"
        )
    lines.extend([
        "",
        "## Findings by dimension",
        "",
        "| Dimension | Findings |",
        "| --- | ---: |",
    ])
    for dimension, count in (report.get("finding_counts_by_dimension") or {}).items():
        lines.append(f"| {dimension} | {count} |")
    false_positive = report.get("false_positive_characterization") or {}
    lines.extend([
        "",
        "## False-positive characterization",
        "",
        f"- Explicit legitimate exceptions exercised: {len(false_positive.get('explicit_exception_findings') or [])}.",
        f"- Both-missing cells kept as unobserved rather than counted as proof: {false_positive.get('both_missing_cells', 0)}.",
        f"- Unexpected blocking rows: {summary.get('unexpected_blocking_finding_count', 0)}.",
        f"- {false_positive.get('note')}",
        "",
        "## Binding proposal",
        "",
        f"- Initial severity: **{(report.get('binding_proposal') or {}).get('initial_severity')}**.",
        f"- Transition: {(report.get('binding_proposal') or {}).get('blocking_transition')}",
        f"- Exceptions: {(report.get('binding_proposal') or {}).get('exception_semantics')}",
        "",
        f"Report SHA-256: `{report.get(REPORT_HASH_FIELD)}`.",
        "",
    ])
    return "\n".join(lines)


def write_outputs(
    report: Mapping[str, Any],
    *,
    run_root: str | Path,
) -> tuple[Path, Path]:
    root = Path(run_root)
    json_path = root / "train-serve-feature-parity.json"
    markdown_path = root / "train-serve-feature-parity.md"
    write_json_atomic(json_path, dict(report), trailing_newline=True)
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Captured-case JSON manifest")
    parser.add_argument("--run-root", required=True, help="Declared output root outside data/")
    parser.add_argument(
        "--proof-mode",
        action="store_true",
        help="Exit zero when every declared known defect is rediscovered and coverage is complete",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    report = evaluate_manifest(payload, run_root=args.run_root)
    json_path, markdown_path = write_outputs(report, run_root=args.run_root)
    print(json.dumps({
        "status": report["status"],
        "summary": report["summary"],
        "json": str(json_path),
        "markdown": str(markdown_path),
        REPORT_HASH_FIELD: report[REPORT_HASH_FIELD],
    }, indent=2, sort_keys=True))
    if args.proof_mode:
        return 0 if (
            report["summary"]["all_known_defects_rediscovered"]
            and report["summary"]["coverage_blocker_count"] == 0
            and report["summary"]["unexpected_blocking_finding_count"] == 0
        ) else 2
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CASE_SCHEMA_VERSION",
    "EXPECTED_DIMENSIONS",
    "REPORT_SCHEMA_VERSION",
    "TrainServeFeatureParityError",
    "compare_feature_records",
    "evaluate_manifest",
    "render_markdown",
    "write_outputs",
]
