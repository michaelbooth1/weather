"""Immutable, training-only point-in-time forecast corpus machinery.

This module intentionally has no HTTP client.  It plans request units, accepts
raw response bytes supplied by a separately authorized collector, verifies
request-keyed staging, materializes only a complete cutoff-safe field matrix,
and atomically publishes a content-addressed corpus outside the active forecast
archive.  The legacy ``forecast_history`` paths are never consulted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from weather.io import sha256_file, write_json_atomic
from weather.market.market_registry import all_specs
from weather.paths import data_path
from weather.schema_registry import schema_version
from weather.sources.daily_summary import native_to_c
from weather.units import to_float


PLAN_SCHEMA_VERSION = schema_version("pit_forecast_corpus_plan")
STAGED_RESPONSE_SCHEMA_VERSION = schema_version("pit_forecast_staged_response")
ROW_SCHEMA_VERSION = schema_version("pit_forecast_corpus_row")
COVERAGE_SCHEMA_VERSION = schema_version("pit_forecast_corpus_coverage")
MANIFEST_SCHEMA_VERSION = schema_version("pit_forecast_corpus_manifest")
FAILURE_SCHEMA_VERSION = schema_version("pit_forecast_failure")

PROVIDER = "open_meteo"
PREVIOUS_RUNS_ENDPOINT = "https://previous-runs-api.open-meteo.com/v1/forecast"
NORMALIZER_VERSION = schema_version("pit_forecast_normalizer")
ISSUE_EVIDENCE_KIND = "fixed_lead_offset"
REJECTED_ISSUE_EVIDENCE_KINDS = {
    "",
    "empty",
    "stitched",
    "stitched_continuous_archive",
}
DEFAULT_MODEL = "gfs_seamless"
DEFAULT_YEARS = tuple(range(2021, 2026))
DEFAULT_TARGET_YEAR = 2026
DEFAULT_SEASON_START = (5, 10)
DEFAULT_SEASON_END = (8, 31)
DEFAULT_CUTOFF_HOURS = tuple(range(7, 21))
DEFAULT_LEAD_DAYS = 1
DEFAULT_PUBLISH_ROOT = data_path("training", "pit_forecast_corpus")
ACTIVE_FORECAST_ARCHIVE_ROOT = data_path("forecast_history")


SOURCE_FIELD_SPECS = {
    "temperature_2m": {"normalized_field": "target_temp_native", "unit": "native_temperature"},
    "cloud_cover": {"normalized_field": "cloud_cover", "unit": "percent"},
    "cloud_cover_low": {"normalized_field": "low_cloud", "unit": "percent"},
    "cloud_cover_mid": {"normalized_field": "mid_cloud", "unit": "percent"},
    "cloud_cover_high": {"normalized_field": "high_cloud", "unit": "percent"},
    "shortwave_radiation": {"normalized_field": "shortwave_radiation", "unit": "W/m2"},
    "wind_speed_10m": {"normalized_field": "wind_speed_kmh", "unit": "km/h"},
    "cape": {"normalized_field": "cape", "unit": "J/kg"},
    "temperature_925hPa": {"normalized_field": "temperature_925hpa", "unit": "native_temperature"},
    "temperature_850hPa": {"normalized_field": "temperature_850hpa", "unit": "native_temperature"},
    "geopotential_height_500hPa": {
        "normalized_field": "geopotential_height_500hpa",
        "unit": "m",
    },
    "direct_radiation": {"normalized_field": "direct_radiation", "unit": "W/m2"},
    "diffuse_radiation": {"normalized_field": "diffuse_radiation", "unit": "W/m2"},
    "wind_gusts_10m": {"normalized_field": "wind_gust_kmh", "unit": "km/h"},
    "visibility": {"normalized_field": "visibility", "unit": "m"},
    "precipitation_probability": {
        "normalized_field": "precipitation_probability",
        "unit": "percent",
    },
    "precipitation": {"normalized_field": "precipitation", "unit": "mm"},
    "soil_temperature_0cm": {
        "normalized_field": "soil_temperature_0cm",
        "unit": "native_temperature",
    },
    "soil_moisture_0_to_1cm": {
        "normalized_field": "soil_moisture_0_to_1cm",
        "unit": "m3/m3",
    },
    "vapour_pressure_deficit": {
        "normalized_field": "vapour_pressure_deficit",
        "unit": "kPa",
    },
    "et0_fao_evapotranspiration": {
        "normalized_field": "et0_fao_evapotranspiration",
        "unit": "mm",
    },
}

# Direct probes and a complete 12-market staged corpus established that these
# fields are available from the free Previous Runs endpoint with genuine
# issue-time provenance.  The remaining schema-known fields are deliberately
# excluded below: asking the corpus gate to require them made the honest PIT
# lane impossible to satisfy and encouraged substitution from the stitched
# settled archive.
FREE_PIT_SOURCE_FIELDS = (
    "temperature_2m",
    "cloud_cover",
    "shortwave_radiation",
    "wind_speed_10m",
    "cape",
    "direct_radiation",
    "diffuse_radiation",
    "wind_gusts_10m",
    "precipitation_probability",
    "precipitation",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
)
UNAVAILABLE_PIT_SOURCE_FIELDS = {
    "cloud_cover_low": "free Previous Runs responses are all-null",
    "cloud_cover_mid": "free Previous Runs responses are all-null",
    "cloud_cover_high": "free Previous Runs responses are all-null",
    "visibility": "free Previous Runs responses are all-null",
    "soil_temperature_0cm": "free Previous Runs responses are all-null",
    "soil_moisture_0_to_1cm": "free Previous Runs responses are all-null",
    "temperature_925hPa": "free Previous Runs endpoint rejects this field",
    "temperature_850hPa": "free Previous Runs endpoint rejects this field",
    "geopotential_height_500hPa": "free Previous Runs endpoint rejects this field",
}
DEFAULT_SOURCE_FIELDS = FREE_PIT_SOURCE_FIELDS

if set(FREE_PIT_SOURCE_FIELDS) & set(UNAVAILABLE_PIT_SOURCE_FIELDS):
    raise RuntimeError("PIT source-field availability contract overlaps")
if set(FREE_PIT_SOURCE_FIELDS) | set(UNAVAILABLE_PIT_SOURCE_FIELDS) != set(
    SOURCE_FIELD_SPECS
):
    raise RuntimeError("PIT source-field availability contract is incomplete")


PROFILE_FEATURE_SOURCE_FIELDS = {
    "forecast_peak_hour": ("temperature_2m",),
    "forecast_peak_after_cutoff_hours": ("temperature_2m",),
    "forecast_temp_12": ("temperature_2m",),
    "forecast_temp_13": ("temperature_2m",),
    "forecast_temp_14": ("temperature_2m",),
    "forecast_temp_15": ("temperature_2m",),
    "forecast_temp_16": ("temperature_2m",),
    "forecast_afternoon_slope": ("temperature_2m",),
    "forecast_remaining_degree_hours": ("temperature_2m",),
    "forecast_remaining_solar_sum": ("shortwave_radiation",),
    "forecast_next_3h_solar_mean": ("shortwave_radiation",),
    "forecast_total_cloud_mean": ("cloud_cover",),
    "forecast_total_cloud_max": ("cloud_cover",),
    "forecast_cloud_trend_3h": ("cloud_cover",),
    "forecast_remaining_direct_radiation_sum": ("direct_radiation",),
    "forecast_remaining_diffuse_radiation_sum": ("diffuse_radiation",),
    "forecast_next_3h_direct_radiation_mean": ("direct_radiation",),
    "forecast_next_3h_diffuse_radiation_mean": ("diffuse_radiation",),
    "forecast_remaining_direct_radiation_share": (
        "direct_radiation",
        "diffuse_radiation",
    ),
    "forecast_next_3h_direct_radiation_share": (
        "direct_radiation",
        "diffuse_radiation",
    ),
    "forecast_remaining_precipitation_sum": ("precipitation",),
    "forecast_next_3h_precipitation_sum": ("precipitation",),
    "forecast_next_3h_precipitation_probability_max": (
        "precipitation_probability",
    ),
    "forecast_remaining_cape_mean": ("cape",),
    "forecast_next_3h_cape_max": ("cape",),
    "forecast_cape_trend_3h": ("cape",),
    "forecast_wind_gust_max": ("wind_gusts_10m",),
    "forecast_vapour_pressure_deficit_mean": ("vapour_pressure_deficit",),
    "forecast_et0_fao_evapotranspiration_sum": (
        "et0_fao_evapotranspiration",
    ),
}
EXCLUDED_PROFILE_FEATURES = {
    "forecast_low_cloud_mean": (
        "cloud_cover_low is unavailable from the free PIT endpoint"
    ),
    "forecast_low_cloud_max": (
        "cloud_cover_low is unavailable from the free PIT endpoint"
    ),
    "forecast_mid_cloud_mean": (
        "cloud_cover_mid is unavailable from the free PIT endpoint"
    ),
    "forecast_high_cloud_mean": (
        "cloud_cover_high is unavailable from the free PIT endpoint"
    ),
    "forecast_temperature_925hpa_mean": (
        "temperature_925hPa is unavailable from the free PIT endpoint"
    ),
    "forecast_temperature_850hpa_mean": (
        "temperature_850hPa is unavailable from the free PIT endpoint"
    ),
    "forecast_surface_to_925_lapse_proxy": (
        "temperature_925hPa is unavailable from the free PIT endpoint"
    ),
    "forecast_925_to_850_lapse_proxy": (
        "pressure-level temperatures are unavailable from the free PIT endpoint"
    ),
    "forecast_geopotential_height_500hpa_mean": (
        "geopotential_height_500hPa is unavailable from the free PIT endpoint"
    ),
    "forecast_visibility_min": (
        "visibility is unavailable from the free PIT endpoint"
    ),
    "forecast_soil_temperature_0cm_mean": (
        "soil_temperature_0cm is unavailable from the free PIT endpoint"
    ),
    "forecast_soil_moisture_0_to_1cm_mean": (
        "soil_moisture_0_to_1cm is unavailable from the free PIT endpoint"
    ),
    "forecast_remaining_aerosol_optical_depth_mean": "air-quality history is not in this endpoint contract",
    "forecast_next_3h_aerosol_optical_depth_mean": "air-quality history is not in this endpoint contract",
    "forecast_remaining_pm2_5_mean": "air-quality history is not in this endpoint contract",
    "forecast_next_3h_pm2_5_mean": "air-quality history is not in this endpoint contract",
    "forecast_remaining_pm10_mean": "air-quality history is not in this endpoint contract",
    "forecast_remaining_dust_mean": "air-quality history is not in this endpoint contract",
    "forecast_smoke_suppression_flag": "air-quality history is not in this endpoint contract",
    "forecast_global_ensemble_spread": "ensemble history is not in this endpoint contract",
    "forecast_next_3h_ensemble_spread": "ensemble history is not in this endpoint contract",
    "forecast_global_ensemble_high_p10": "ensemble history is not in this endpoint contract",
    "forecast_global_ensemble_high_p90": "ensemble history is not in this endpoint contract",
    "forecast_global_ensemble_high_spread_80": "ensemble history is not in this endpoint contract",
}
CONSUMER_DISPOSITIONS = {
    "pooled_forecast_high_and_gap": {
        "disposition": "included",
        "resolver": "pit_daily_by_market_date_cutoff",
    },
    "pooled_forecast_profiles": {
        "disposition": "included_with_field_exclusions",
        "resolver": "pit_hourly_by_market_date_cutoff",
        "included_feature_columns": sorted(PROFILE_FEATURE_SOURCE_FIELDS),
        "excluded_feature_columns": EXCLUDED_PROFILE_FEATURES,
    },
    "forecast_relative_marine_fields": {
        "disposition": "excluded",
        "fields": [
            "marine_water_minus_forecast_high",
            "marine_onshore_water_minus_forecast_high",
            "marine_onshore_cooling_potential",
        ],
        "reason": "marine sidecars are not rebuilt by this corpus lane",
    },
    "forecast_error_secondary_artifact": {
        "disposition": "excluded",
        "reason": "must be rebuilt from the PIT resolver in a separately authorized fit",
    },
    "late_day_continuation": {
        "disposition": "excluded",
        "reason": "must be retrained explicitly from the PIT resolver",
    },
    "analog_distance": {
        "disposition": "excluded",
        "reason": "training-only corpus; active analog archive remains pinned",
    },
}


class ForecastCorpusError(RuntimeError):
    """Base class for fail-closed corpus errors."""


class PlanValidationError(ForecastCorpusError):
    pass


class StagingValidationError(ForecastCorpusError):
    pass


class MaterializationBlocked(ForecastCorpusError):
    pass


class CorpusVerificationError(ForecastCorpusError):
    pass


def _canonical_bytes(payload) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_payload(payload) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _self_hash(payload, field) -> str:
    body = dict(payload)
    body.pop(field, None)
    return _sha256_payload(body)


def _aware_datetime(value, label) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MaterializationBlocked(f"invalid {label}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise MaterializationBlocked(f"{label} must be timezone-aware")
    return parsed


def _iter_dates(start: date, end: date):
    cursor = start
    while cursor <= end:
        yield cursor
        cursor += timedelta(days=1)


def _window_for_year(year, season_start, season_end):
    start = date(int(year), int(season_start[0]), int(season_start[1]))
    end = date(int(year), int(season_end[0]), int(season_end[1]))
    if end < start:
        raise PlanValidationError("season end must not precede season start")
    return start, end


def _market_specs(market_ids=None):
    registry = {spec.id: spec for spec in all_specs()}
    selected = sorted(set(market_ids or registry))
    unknown = sorted(set(selected) - set(registry))
    if unknown:
        raise PlanValidationError(f"unknown market ids: {', '.join(unknown)}")
    return [registry[market_id] for market_id in selected]


def _binding_for(field, spec, lead_days):
    definition = SOURCE_FIELD_SPECS[field]
    unit = spec.display_unit if definition["unit"] == "native_temperature" else definition["unit"]
    return {
        "source_field": field,
        "request_field": f"{field}_previous_day{int(lead_days)}",
        "normalized_field": definition["normalized_field"],
        "source_unit": unit,
        "normalized_unit": unit,
    }


def build_plan(
    *,
    years=DEFAULT_YEARS,
    target_year=DEFAULT_TARGET_YEAR,
    market_ids=None,
    season_start=DEFAULT_SEASON_START,
    season_end=DEFAULT_SEASON_END,
    cutoff_hours=DEFAULT_CUTOFF_HOURS,
    source_model=DEFAULT_MODEL,
    lead_days=DEFAULT_LEAD_DAYS,
    planned_at_utc=None,
):
    years = tuple(sorted({int(year) for year in years}))
    target_year = int(target_year)
    cutoff_hours = tuple(sorted({int(hour) for hour in cutoff_hours}))
    if not years:
        raise PlanValidationError("at least one training year is required")
    if target_year in years or any(year >= target_year for year in years):
        raise PlanValidationError("target year must be structurally excluded from training years")
    if not cutoff_hours or any(hour < 0 or hour > 23 for hour in cutoff_hours):
        raise PlanValidationError("cutoff hours must be unique values in [0, 23]")
    if int(lead_days) <= 0:
        raise PlanValidationError("lead_days must be positive")
    if not source_model or str(source_model).lower() == "best_match":
        raise PlanValidationError("an explicit source model is required; best_match is not PIT-stable")

    requests = []
    expected_dates_by_year = {}
    total_call_equivalents = 0.0
    for year in years:
        start, end = _window_for_year(year, season_start, season_end)
        expected_dates_by_year[str(year)] = [day.isoformat() for day in _iter_dates(start, end)]
    for spec in _market_specs(market_ids):
        bindings = [_binding_for(field, spec, lead_days) for field in DEFAULT_SOURCE_FIELDS]
        for year in years:
            start, end = _window_for_year(year, season_start, season_end)
            day_count = (end - start).days + 1
            call_equivalents = day_count / 14.0 * max(1.0, len(bindings) / 10.0)
            request = {
                "provider": PROVIDER,
                "endpoint": PREVIOUS_RUNS_ENDPOINT,
                "method": "GET",
                "market_id": spec.id,
                "station": spec.icao,
                "year": year,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "source_timezone": spec.timezone,
                "source_model": str(source_model),
                "issue_evidence_kind": ISSUE_EVIDENCE_KIND,
                "lead_days": int(lead_days),
                "lead_hours": int(lead_days) * 24,
                "variables": bindings,
                "params": {
                    "latitude": spec.lat,
                    "longitude": spec.lon,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "hourly": ",".join(binding["request_field"] for binding in bindings),
                    "temperature_unit": spec.om_temperature_unit,
                    "wind_speed_unit": "kmh",
                    "timezone": spec.timezone,
                    "models": str(source_model),
                },
                "expected_local_dates": expected_dates_by_year[str(year)],
                "expected_hourly_rows_per_date": 24,
                "issue_time_required": True,
                "available_at_utc_required": True,
                "provider_contract_status": "probe_required_before_collection",
                "estimated_call_equivalents": round(call_equivalents, 6),
            }
            request["request_hash"] = _self_hash(request, "request_hash")
            requests.append(request)
            total_call_equivalents += call_equivalents

    market_ids_sorted = sorted({request["market_id"] for request in requests})
    expected_date_count = sum(len(dates) for dates in expected_dates_by_year.values())
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "planned_at_utc": planned_at_utc
        or datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run_no_network",
        "network_authorized": False,
        "provider_probe_authorized": False,
        "corpus_role": "training_only",
        "target_year": target_year,
        "target_year_excluded": True,
        "years": list(years),
        "market_ids": market_ids_sorted,
        "cutoff_hours_local": list(cutoff_hours),
        "season_window": {
            "start_month_day": list(season_start),
            "end_month_day": list(season_end),
        },
        "issue_contract": {
            "kind": ISSUE_EVIDENCE_KIND,
            "lead_days": int(lead_days),
            "source_model": str(source_model),
            "issue_time_required": True,
            "available_at_utc_required": True,
            "acceptance": "issue_time_utc <= feature_as_of_utc and available_at_utc <= feature_as_of_utc",
            "stitched_rows_allowed": False,
            "empty_issue_allowed": False,
        },
        "normalizer_version": NORMALIZER_VERSION,
        "source_fields": list(DEFAULT_SOURCE_FIELDS),
        "expected_dates_by_year": expected_dates_by_year,
        "consumer_dispositions": CONSUMER_DISPOSITIONS,
        "publication_contract": {
            "content_addressed": True,
            "atomic": True,
            "in_place_overwrite_allowed": False,
            "active_archive_discoverable": False,
        },
        "summary": {
            "request_count": len(requests),
            "market_count": len(market_ids_sorted),
            "year_count": len(years),
            "market_year_count": len(requests),
            "variable_bindings": len(requests) * len(DEFAULT_SOURCE_FIELDS),
            "expected_market_dates": len(market_ids_sorted) * expected_date_count,
            "expected_market_date_cutoffs": (
                len(market_ids_sorted) * expected_date_count * len(cutoff_hours)
            ),
            "expected_field_date_cutoff_cells": (
                len(market_ids_sorted)
                * expected_date_count
                * len(cutoff_hours)
                * len(DEFAULT_SOURCE_FIELDS)
            ),
            "estimated_call_equivalents": round(total_call_equivalents, 3),
        },
        "requests": sorted(
            requests,
            key=lambda item: (item["market_id"], item["year"], item["request_hash"]),
        ),
    }
    plan["plan_sha256"] = _self_hash(plan, "plan_sha256")
    verify_plan(plan)
    return plan


def verify_plan(plan):
    if not isinstance(plan, Mapping):
        raise PlanValidationError("plan must be a JSON object")
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise PlanValidationError("unsupported PIT forecast plan schema")
    if plan.get("plan_sha256") != _self_hash(plan, "plan_sha256"):
        raise PlanValidationError("plan self-hash mismatch")
    if plan.get("mode") != "dry_run_no_network":
        raise PlanValidationError("plan mode must remain dry_run_no_network")
    if plan.get("corpus_role") != "training_only":
        raise PlanValidationError("plan role must remain training_only")
    years = [int(year) for year in plan.get("years") or []]
    target_year = int(plan.get("target_year") or 0)
    if (
        not years
        or years != sorted(set(years))
        or plan.get("target_year_excluded") is not True
        or target_year in years
        or any(year >= target_year for year in years)
    ):
        raise PlanValidationError("plan does not structurally exclude target year")
    if (
        plan.get("network_authorized") is not False
        or plan.get("provider_probe_authorized") is not False
    ):
        raise PlanValidationError("planner output must not authorize network access")
    cutoff_hours = [int(hour) for hour in plan.get("cutoff_hours_local") or []]
    if (
        not cutoff_hours
        or cutoff_hours != sorted(set(cutoff_hours))
        or any(hour < 0 or hour > 23 for hour in cutoff_hours)
    ):
        raise PlanValidationError("plan cutoff matrix is invalid")
    if plan.get("source_fields") != list(DEFAULT_SOURCE_FIELDS):
        raise PlanValidationError("plan source-field matrix differs from the frozen contract")
    issue_contract = plan.get("issue_contract") or {}
    if (
        issue_contract.get("kind") != ISSUE_EVIDENCE_KIND
        or issue_contract.get("stitched_rows_allowed") is not False
        or issue_contract.get("empty_issue_allowed") is not False
        or issue_contract.get("issue_time_required") is not True
        or issue_contract.get("available_at_utc_required") is not True
    ):
        raise PlanValidationError("plan issue contract is not fail-closed")
    market_ids = sorted(set(plan.get("market_ids") or []))
    if not market_ids or market_ids != list(plan.get("market_ids") or []):
        raise PlanValidationError("plan market matrix must be sorted and unique")
    specs = {spec.id: spec for spec in _market_specs(market_ids)}
    expected_request_keys = {
        (market_id, year) for market_id in market_ids for year in years
    }
    hashes = set()
    request_keys = set()
    for request in plan.get("requests") or []:
        request_hash = request.get("request_hash")
        if not request_hash or request_hash != _self_hash(request, "request_hash"):
            raise PlanValidationError("request self-hash mismatch")
        if request_hash in hashes:
            raise PlanValidationError(f"duplicate request hash: {request_hash}")
        hashes.add(request_hash)
        if int(request.get("year") or 0) == target_year:
            raise PlanValidationError("target-year request is forbidden")
        request_key = (request.get("market_id"), int(request.get("year") or 0))
        if request_key in request_keys:
            raise PlanValidationError(f"duplicate market/year request: {request_key}")
        request_keys.add(request_key)
        if request_key not in expected_request_keys:
            raise PlanValidationError(f"request is outside the market/year matrix: {request_key}")
        if request.get("provider") != PROVIDER or request.get("endpoint") != PREVIOUS_RUNS_ENDPOINT:
            raise PlanValidationError("request provider or endpoint differs from the frozen contract")
        if request.get("method") != "GET":
            raise PlanValidationError("PIT forecast requests must use GET")
        if request.get("issue_evidence_kind") in REJECTED_ISSUE_EVIDENCE_KINDS:
            raise PlanValidationError("request has rejected issue-evidence kind")
        if request.get("issue_evidence_kind") != issue_contract["kind"]:
            raise PlanValidationError("request issue contract differs from the plan")
        lead_days = int(request.get("lead_days") or 0)
        if lead_days <= 0 or int(request.get("lead_hours") or 0) != lead_days * 24:
            raise PlanValidationError("request lead identity is invalid")
        if not request.get("source_model") or str(request["source_model"]).lower() == "best_match":
            raise PlanValidationError("request must pin an explicit source model")
        spec = specs[request["market_id"]]
        expected_bindings = [
            _binding_for(field, spec, lead_days)
            for field in DEFAULT_SOURCE_FIELDS
        ]
        if request.get("variables") != expected_bindings:
            raise PlanValidationError("request variable bindings differ from the frozen contract")
        if request.get("station") != spec.icao or request.get("source_timezone") != spec.timezone:
            raise PlanValidationError("request market identity differs from the registry")
        start = date.fromisoformat(request["window_start"])
        end = date.fromisoformat(request["window_end"])
        expected_dates = [day.isoformat() for day in _iter_dates(start, end)]
        if request.get("expected_local_dates") != expected_dates:
            raise PlanValidationError("request date matrix differs from its immutable window")
        if expected_dates != (plan.get("expected_dates_by_year") or {}).get(str(request_key[1])):
            raise PlanValidationError("request dates differ from the plan year matrix")
        if any(int(day[:4]) != request_key[1] for day in expected_dates):
            raise PlanValidationError("request window crosses its planned year")
        if int(request.get("expected_hourly_rows_per_date") or 0) != 24:
            raise PlanValidationError("request hourly envelope must contain 24 rows per date")
        expected_params = {
            "latitude": spec.lat,
            "longitude": spec.lon,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "hourly": ",".join(binding["request_field"] for binding in expected_bindings),
            "temperature_unit": spec.om_temperature_unit,
            "wind_speed_unit": "kmh",
            "timezone": spec.timezone,
            "models": request["source_model"],
        }
        if request.get("params") != expected_params:
            raise PlanValidationError("request parameters differ from the frozen contract")
        expected_call_equivalents = round(
            len(expected_dates) / 14.0 * max(1.0, len(expected_bindings) / 10.0),
            6,
        )
        if float(request.get("estimated_call_equivalents") or -1) != expected_call_equivalents:
            raise PlanValidationError("request call-equivalent estimate drifted")
    if len(hashes) != int((plan.get("summary") or {}).get("request_count") or -1):
        raise PlanValidationError("request count does not match plan summary")
    if request_keys != expected_request_keys:
        raise PlanValidationError("request market/year matrix is incomplete")
    expected_dates_by_year = plan.get("expected_dates_by_year") or {}
    expected_market_dates = len(market_ids) * sum(
        len(expected_dates_by_year.get(str(year)) or []) for year in years
    )
    summary = plan.get("summary") or {}
    expected_summary = {
        "request_count": len(expected_request_keys),
        "market_count": len(market_ids),
        "year_count": len(years),
        "market_year_count": len(expected_request_keys),
        "variable_bindings": len(expected_request_keys) * len(DEFAULT_SOURCE_FIELDS),
        "expected_market_dates": expected_market_dates,
        "expected_market_date_cutoffs": expected_market_dates * len(cutoff_hours),
        "expected_field_date_cutoff_cells": (
            expected_market_dates * len(cutoff_hours) * len(DEFAULT_SOURCE_FIELDS)
        ),
    }
    for key, expected in expected_summary.items():
        if int(summary.get(key) or -1) != expected:
            raise PlanValidationError(f"plan summary mismatch for {key}")
    expected_total_calls = round(
        sum(float(request["estimated_call_equivalents"]) for request in plan["requests"]),
        3,
    )
    if float(summary.get("estimated_call_equivalents") or -1) != expected_total_calls:
        raise PlanValidationError("plan summary mismatch for estimated_call_equivalents")
    return True


def load_plan(path):
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanValidationError(f"cannot read plan: {path}") from exc
    verify_plan(plan)
    return plan


def write_immutable_plan(path, plan):
    verify_plan(plan)
    path = Path(path)
    rendered = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == rendered:
            return path
        raise PlanValidationError(f"immutable plan already exists with different content: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(rendered, encoding="utf-8")
    try:
        os.link(temp_path, path)
    except FileExistsError as exc:
        raise PlanValidationError(f"immutable plan appeared concurrently: {path}") from exc
    finally:
        temp_path.unlink(missing_ok=True)
    return path


def _request_by_hash(plan, request_hash):
    for request in plan.get("requests") or []:
        if request.get("request_hash") == request_hash:
            return request
    raise StagingValidationError(f"request hash is not in plan: {request_hash}")


def _unit_paths(staging_root, request_hash):
    root = Path(staging_root) / "requests" / str(request_hash)
    return root, root / "response.json", root / "receipt.json"


def _write_bytes_atomic(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp_path.write_bytes(body)
    temp_path.replace(path)


def _append_failure(staging_root, payload):
    root = Path(staging_root)
    root.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": FAILURE_SCHEMA_VERSION,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    record["failure_sha256"] = _self_hash(record, "failure_sha256")
    path = root / "failure_ledger.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record


def _safe_http_headers(headers):
    allowed = {"content-type", "date", "etag", "last-modified", "x-request-id"}
    return {
        str(key).lower(): str(value)
        for key, value in (headers or {}).items()
        if str(key).lower() in allowed
    }


def _basic_response_validation(
    request,
    body,
    http_status,
    issue_evidence,
    *,
    cutoff_hours,
    target_year,
):
    errors = []
    payload = None
    if int(http_status or 0) != 200:
        errors.append(f"http_status_{http_status}")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        errors.append("response_not_valid_utf8_json")
    hourly = (payload or {}).get("hourly") if isinstance(payload, Mapping) else None
    times = (hourly or {}).get("time") if isinstance(hourly, Mapping) else None
    row_count = len(times or [])
    if row_count == 0:
        errors.append("zero_rows")
    expected_dates = set(request.get("expected_local_dates") or [])
    rows_by_date = defaultdict(list)
    for raw_time in times or []:
        try:
            valid_local = _parse_provider_local_time(
                raw_time,
                request["source_timezone"],
            )
        except MaterializationBlocked:
            errors.append(f"invalid_hourly_time:{raw_time}")
            continue
        target_date = valid_local.date().isoformat()
        if valid_local.year == int(target_year):
            errors.append(f"target_year_row:{target_date}")
        if target_date not in expected_dates:
            errors.append(f"row_outside_request_window:{target_date}")
        rows_by_date[target_date].append(valid_local)
    for target_date in sorted(expected_dates):
        day_rows = rows_by_date.get(target_date) or []
        clock_hours = {(item.hour, item.minute) for item in day_rows}
        if len(day_rows) != 24 or clock_hours != {(hour, 0) for hour in range(24)}:
            errors.append(f"incomplete_hourly_envelope:{target_date}:{len(day_rows)}")
    response_timezone = (payload or {}).get("timezone") if isinstance(payload, Mapping) else None
    if response_timezone and response_timezone != request.get("source_timezone"):
        errors.append(f"response_timezone_mismatch:{response_timezone}")
    hourly_units = (payload or {}).get("hourly_units") if isinstance(payload, Mapping) else None
    for binding in request.get("variables") or []:
        field = binding["request_field"]
        if not isinstance(hourly, Mapping) or field not in hourly:
            errors.append(f"missing_field:{field}")
            continue
        series = hourly.get(field)
        if not isinstance(series, list) or len(series) != row_count:
            errors.append(f"field_row_count_mismatch:{field}")
        elif any(to_float(value) is None for value in series):
            errors.append(f"null_or_invalid_field_value:{field}")
        actual_unit = (hourly_units or {}).get(field) if isinstance(hourly_units, Mapping) else None
        if not _provider_unit_valid(binding["source_unit"], actual_unit):
            errors.append(f"invalid_unit:{field}:{actual_unit}")
    if not issue_evidence:
        errors.append("missing_issue_evidence")
    evidence_by_date = {}
    for evidence in issue_evidence or []:
        target_date = str(evidence.get("target_date") or "")
        if target_date in evidence_by_date:
            errors.append(f"duplicate_issue_evidence:{target_date}")
        evidence_by_date[target_date] = evidence
        kind = str(evidence.get("issue_evidence_kind") or "")
        if kind in REJECTED_ISSUE_EVIDENCE_KINDS or kind != request["issue_evidence_kind"]:
            errors.append(f"rejected_issue_evidence:{kind or 'empty'}")
        if not target_date:
            errors.append("issue_evidence_missing_target_date")
        elif target_date not in expected_dates:
            errors.append(f"issue_evidence_outside_request_window:{target_date}")
        if not evidence.get("issue_time_utc"):
            errors.append("issue_evidence_missing_issue_time")
        if not evidence.get("available_at_utc"):
            errors.append("issue_evidence_missing_available_at")
        if not isinstance(evidence.get("run_id_exposed"), bool):
            errors.append(f"issue_evidence_run_id_exposure_unknown:{target_date}")
        if evidence.get("run_id_exposed") is True and not evidence.get("run_id"):
            errors.append("issue_evidence_missing_exposed_run_id")
        try:
            issue_time = _aware_datetime(evidence.get("issue_time_utc"), "issue_time_utc")
            available_at = _aware_datetime(
                evidence.get("available_at_utc"),
                "available_at_utc",
            )
        except MaterializationBlocked:
            errors.append(f"invalid_issue_timestamps:{target_date}")
            continue
        if available_at < issue_time:
            errors.append(f"availability_precedes_issue:{target_date}")
            continue
        if target_date in expected_dates:
            target_day = date.fromisoformat(target_date)
            for cutoff_hour in cutoff_hours:
                as_of = _feature_as_of(
                    target_day,
                    cutoff_hour,
                    request["source_timezone"],
                ).astimezone(timezone.utc)
                if issue_time.astimezone(timezone.utc) > as_of:
                    errors.append(f"issue_after_cutoff:{target_date}:{cutoff_hour}")
                if available_at.astimezone(timezone.utc) > as_of:
                    errors.append(f"available_after_cutoff:{target_date}:{cutoff_hour}")
    for target_date in sorted(expected_dates - set(evidence_by_date)):
        errors.append(f"missing_issue_evidence:{target_date}")
    return payload, row_count, sorted(set(errors))


def inspect_staged_unit(plan, staging_root, request_hash):
    _request_by_hash(plan, request_hash)
    _root, body_path, receipt_path = _unit_paths(staging_root, request_hash)
    if not body_path.exists() or not receipt_path.exists():
        return {"complete": False, "reason": "missing_body_or_receipt"}
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"complete": False, "reason": "invalid_receipt"}
    if receipt.get("schema_version") != STAGED_RESPONSE_SCHEMA_VERSION:
        return {"complete": False, "reason": "receipt_schema_mismatch"}
    if receipt.get("receipt_sha256") != _self_hash(receipt, "receipt_sha256"):
        return {"complete": False, "reason": "receipt_self_hash_mismatch"}
    if receipt.get("request_hash") != request_hash:
        return {"complete": False, "reason": "request_hash_mismatch"}
    if receipt.get("validation_status") != "complete":
        return {"complete": False, "reason": "validation_not_complete"}
    if int(receipt.get("row_count") or 0) <= 0:
        return {"complete": False, "reason": "zero_rows"}
    if int(receipt.get("byte_count") or -1) != body_path.stat().st_size:
        return {"complete": False, "reason": "byte_count_mismatch"}
    if receipt.get("raw_response_sha256") != sha256_file(body_path):
        return {"complete": False, "reason": "raw_response_hash_mismatch"}
    return {"complete": True, "reason": "hash_verified_complete", "receipt": receipt}


def stage_response(
    plan_path,
    staging_root,
    request_hash,
    body,
    *,
    http_status=200,
    http_headers=None,
    retrieved_at_utc,
    issue_evidence,
):
    plan = load_plan(plan_path)
    request = _request_by_hash(plan, request_hash)
    current = inspect_staged_unit(plan, staging_root, request_hash)
    if current["complete"]:
        return {"skipped": True, **current["receipt"]}
    if isinstance(body, str):
        body = body.encode("utf-8")
    body = bytes(body)
    _payload, row_count, errors = _basic_response_validation(
        request,
        body,
        http_status,
        issue_evidence,
        cutoff_hours=plan["cutoff_hours_local"],
        target_year=plan["target_year"],
    )
    _root, body_path, receipt_path = _unit_paths(staging_root, request_hash)
    _write_bytes_atomic(body_path, body)
    receipt = {
        "schema_version": STAGED_RESPONSE_SCHEMA_VERSION,
        "plan_sha256": plan["plan_sha256"],
        "request_hash": request_hash,
        "provider": request["provider"],
        "endpoint": request["endpoint"],
        "market_id": request["market_id"],
        "year": request["year"],
        "http_status": int(http_status or 0),
        "http_headers": _safe_http_headers(http_headers),
        "retrieved_at_utc": _aware_datetime(retrieved_at_utc, "retrieved_at_utc")
        .astimezone(timezone.utc)
        .isoformat(),
        "raw_response_sha256": hashlib.sha256(body).hexdigest(),
        "byte_count": len(body),
        "row_count": row_count,
        "issue_evidence": list(issue_evidence or []),
        "validation_status": "complete" if not errors else "failed",
        "validation_errors": errors,
    }
    receipt["receipt_sha256"] = _self_hash(receipt, "receipt_sha256")
    write_json_atomic(receipt_path, receipt, trailing_newline=True)
    if errors:
        _append_failure(
            staging_root,
            {
                "failure_class": "staged_response_validation_failed",
                "request_hash": request_hash,
                "errors": errors,
                "raw_response_sha256": receipt["raw_response_sha256"],
            },
        )
        raise StagingValidationError(
            f"staged response failed validation for {request_hash}: {', '.join(errors)}"
        )
    return {"skipped": False, **receipt}


def resume_ledger(plan_path, staging_root):
    plan = load_plan(plan_path)
    rows = []
    for request in plan["requests"]:
        state = inspect_staged_unit(plan, staging_root, request["request_hash"])
        rows.append(
            {
                "request_hash": request["request_hash"],
                "market_id": request["market_id"],
                "year": request["year"],
                "complete": state["complete"],
                "reason": state["reason"],
            }
        )
    return {
        "plan_sha256": plan["plan_sha256"],
        "complete_units": sum(row["complete"] for row in rows),
        "required_units": len(rows),
        "all_complete": bool(rows) and all(row["complete"] for row in rows),
        "units": rows,
    }


def _parse_provider_local_time(value, source_timezone):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MaterializationBlocked(f"invalid provider hourly time: {value!r}") from exc
    zone = ZoneInfo(source_timezone)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    else:
        parsed = parsed.astimezone(zone)
    return parsed


def _provider_unit_valid(expected, actual):
    aliases = {
        "C": {"C", "°C", "celsius"},
        "F": {"F", "°F", "fahrenheit"},
        "percent": {"%", "percent"},
        "W/m2": {"W/m2", "W/m²"},
        "km/h": {"km/h", "kmh"},
        "J/kg": {"J/kg"},
        "m": {"m"},
        "mm": {"mm"},
        "m3/m3": {"m3/m3", "m³/m³"},
        "kPa": {"kPa"},
    }
    return str(actual or "") in aliases.get(str(expected), {str(expected)})


def _feature_as_of(target_date, cutoff_hour, source_timezone):
    zone = ZoneInfo(source_timezone)
    return datetime.combine(target_date, time(int(cutoff_hour), 0), tzinfo=zone)


def _normalize_request(plan, request, staging_root):
    state = inspect_staged_unit(plan, staging_root, request["request_hash"])
    if not state["complete"]:
        raise MaterializationBlocked(
            f"request unit is not hash-verified complete: {request['request_hash']} ({state['reason']})"
        )
    _root, body_path, _receipt_path = _unit_paths(staging_root, request["request_hash"])
    receipt = state["receipt"]
    payload = json.loads(body_path.read_text(encoding="utf-8"))
    hourly = payload.get("hourly") or {}
    hourly_units = payload.get("hourly_units") or {}
    times = hourly.get("time") or []
    expected_dates = set(request.get("expected_local_dates") or [])
    evidence_by_date = {}
    for evidence in receipt.get("issue_evidence") or []:
        target_date = str(evidence.get("target_date") or "")
        if target_date in evidence_by_date:
            raise MaterializationBlocked(f"duplicate issue evidence for {target_date}")
        evidence_by_date[target_date] = evidence

    rows_by_date = defaultdict(list)
    for index, raw_time in enumerate(times):
        valid_local = _parse_provider_local_time(raw_time, request["source_timezone"])
        target_date = valid_local.date().isoformat()
        if valid_local.year == int(plan["target_year"]):
            raise MaterializationBlocked(
                f"target-year response row rejected from training role: {valid_local.isoformat()}"
            )
        if target_date not in expected_dates:
            raise MaterializationBlocked(
                f"response row is outside immutable request window: {valid_local.isoformat()}"
            )
        values = {}
        units = {}
        for binding in request["variables"]:
            request_field = binding["request_field"]
            series = hourly.get(request_field) or []
            value = to_float(series[index] if index < len(series) else None)
            provider_unit = hourly_units.get(request_field)
            values[binding["normalized_field"]] = value
            units[binding["normalized_field"]] = {
                "source": provider_unit,
                "normalized": binding["normalized_unit"],
                "valid": _provider_unit_valid(binding["source_unit"], provider_unit),
            }
        row = {
            "schema_version": ROW_SCHEMA_VERSION,
            "row_kind": "hourly_profile",
            "market_id": request["market_id"],
            "station": request["station"],
            "target_date": target_date,
            "valid_time_local": valid_local.isoformat(),
            "valid_time_utc": valid_local.astimezone(timezone.utc).isoformat(),
            "provider": request["provider"],
            "endpoint": request["endpoint"],
            "request_hash": request["request_hash"],
            "source_model": request["source_model"],
            "lead_days": request["lead_days"],
            "lead_hours": request["lead_hours"],
            "normalizer_version": plan["normalizer_version"],
            "raw_response_sha256": receipt["raw_response_sha256"],
            "retrieved_at_utc": receipt["retrieved_at_utc"],
            "values": values,
            "units": units,
        }
        rows_by_date[target_date].append(row)

    daily_rows = []
    hourly_rows = []
    coverage_rows = []
    errors = []
    for target_date_text in sorted(expected_dates):
        day_rows = sorted(
            rows_by_date.get(target_date_text) or [],
            key=lambda row: row["valid_time_utc"],
        )
        evidence = evidence_by_date.get(target_date_text)
        if evidence is None:
            errors.append(f"missing_issue_evidence:{target_date_text}")
            continue
        kind = str(evidence.get("issue_evidence_kind") or "")
        if kind in REJECTED_ISSUE_EVIDENCE_KINDS or kind != request["issue_evidence_kind"]:
            errors.append(f"invalid_issue_evidence:{target_date_text}:{kind or 'empty'}")
            continue
        issue_time = _aware_datetime(evidence.get("issue_time_utc"), "issue_time_utc")
        available_at = _aware_datetime(evidence.get("available_at_utc"), "available_at_utc")
        if available_at < issue_time:
            errors.append(f"availability_precedes_issue:{target_date_text}")
            continue
        if evidence.get("run_id_exposed") and not evidence.get("run_id"):
            errors.append(f"missing_exposed_run_id:{target_date_text}")
            continue
        distinct_hours = {row["valid_time_local"] for row in day_rows}
        expected_clock_hours = {(hour, 0) for hour in range(24)}
        actual_clock_hours = {
            (
                datetime.fromisoformat(row["valid_time_local"]).hour,
                datetime.fromisoformat(row["valid_time_local"]).minute,
            )
            for row in day_rows
        }
        if (
            len(day_rows) != int(request["expected_hourly_rows_per_date"])
            or len(distinct_hours) != len(day_rows)
            or actual_clock_hours != expected_clock_hours
        ):
            errors.append(
                f"incomplete_hourly_envelope:{target_date_text}:{len(day_rows)}"
            )
            continue
        field_complete = {
            binding["source_field"]: all(
                row["values"].get(binding["normalized_field"]) is not None
                for row in day_rows
            )
            for binding in request["variables"]
        }
        field_unit_valid = {
            binding["source_field"]: all(
                row["units"].get(binding["normalized_field"], {}).get("valid") is True
                for row in day_rows
            )
            for binding in request["variables"]
        }
        if not all(field_complete.values()):
            missing = sorted(field for field, complete in field_complete.items() if not complete)
            errors.append(f"incomplete_fields:{target_date_text}:{','.join(missing)}")
            continue
        if not all(field_unit_valid.values()):
            invalid = sorted(field for field, valid in field_unit_valid.items() if not valid)
            errors.append(f"invalid_units:{target_date_text}:{','.join(invalid)}")
            continue

        target_day = date.fromisoformat(target_date_text)
        safe_cutoffs = []
        for cutoff_hour in plan["cutoff_hours_local"]:
            as_of = _feature_as_of(target_day, cutoff_hour, request["source_timezone"])
            issue_safe = issue_time <= as_of.astimezone(issue_time.tzinfo)
            availability_safe = available_at <= as_of.astimezone(available_at.tzinfo)
            status = "complete" if issue_safe and availability_safe else "lookahead"
            coverage = {
                "schema_version": COVERAGE_SCHEMA_VERSION,
                "market_id": request["market_id"],
                "year": int(request["year"]),
                "target_date": target_date_text,
                "cutoff_hour_local": int(cutoff_hour),
                "feature_as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
                "issue_contract": kind,
                "issue_time_utc": issue_time.astimezone(timezone.utc).isoformat(),
                "available_at_utc": available_at.astimezone(timezone.utc).isoformat(),
                "field_status": {
                    field: (
                        "complete"
                        if complete
                        and field_unit_valid[field]
                        and issue_safe
                        and availability_safe
                        else "lookahead"
                        if complete and field_unit_valid[field]
                        else "missing"
                    )
                    for field, complete in sorted(field_complete.items())
                },
                "status": status,
                "request_hash": request["request_hash"],
                "raw_response_sha256": receipt["raw_response_sha256"],
            }
            coverage["coverage_row_sha256"] = _self_hash(coverage, "coverage_row_sha256")
            coverage_rows.append(coverage)
            if status != "complete":
                errors.append(f"lookahead:{target_date_text}:{cutoff_hour}")
                continue
            safe_cutoffs.append(int(cutoff_hour))
            temperatures = [row["values"]["target_temp_native"] for row in day_rows]
            high = max(temperatures)
            daily = {
                "schema_version": ROW_SCHEMA_VERSION,
                "row_kind": "daily_high",
                "market_id": request["market_id"],
                "station": request["station"],
                "target_date": target_date_text,
                "cutoff_hour_local": int(cutoff_hour),
                "feature_as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
                "forecast_high_native": high,
                "forecast_high_c": native_to_c(
                    high,
                    next(
                        binding["normalized_unit"]
                        for binding in request["variables"]
                        if binding["normalized_field"] == "target_temp_native"
                    ),
                ),
                "temperature_unit": next(
                    binding["normalized_unit"]
                    for binding in request["variables"]
                    if binding["normalized_field"] == "target_temp_native"
                ),
                "provider": request["provider"],
                "endpoint": request["endpoint"],
                "request_hash": request["request_hash"],
                "source_model": request["source_model"],
                "run_id": evidence.get("run_id") or "",
                "issue_time_utc": issue_time.astimezone(timezone.utc).isoformat(),
                "available_at_utc": available_at.astimezone(timezone.utc).isoformat(),
                "issue_evidence_kind": kind,
                "lead_days": request["lead_days"],
                "lead_hours": request["lead_hours"],
                "normalizer_version": plan["normalizer_version"],
                "raw_response_sha256": receipt["raw_response_sha256"],
                "retrieved_at_utc": receipt["retrieved_at_utc"],
            }
            daily["derived_row_sha256"] = _self_hash(daily, "derived_row_sha256")
            daily_rows.append(daily)

        for row in day_rows:
            enriched = {
                **row,
                "run_id": evidence.get("run_id") or "",
                "issue_time_utc": issue_time.astimezone(timezone.utc).isoformat(),
                "available_at_utc": available_at.astimezone(timezone.utc).isoformat(),
                "issue_evidence_kind": kind,
                "safe_cutoff_hours_local": safe_cutoffs,
            }
            enriched["derived_row_sha256"] = _self_hash(
                enriched,
                "derived_row_sha256",
            )
            hourly_rows.append(enriched)
    if errors:
        raise MaterializationBlocked("; ".join(sorted(set(errors))))
    return hourly_rows, daily_rows, coverage_rows


def _path_overlaps(path, root):
    path = Path(path).resolve()
    root = Path(root).resolve()
    return path == root or root in path.parents or path in root.parents


def assert_training_only_publish_root(publish_root, active_archive_roots=None):
    roots = list(active_archive_roots or [ACTIVE_FORECAST_ARCHIVE_ROOT])
    for root in roots:
        if _path_overlaps(publish_root, root):
            raise MaterializationBlocked(
                f"training corpus publication overlaps active forecast archive: {root}"
            )
    return Path(publish_root)


def _write_jsonl(path, rows):
    path = Path(path)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def materialize_corpus(
    plan_path,
    staging_root,
    publish_root=DEFAULT_PUBLISH_ROOT,
    *,
    active_archive_roots=None,
):
    plan = load_plan(plan_path)
    publish_root = assert_training_only_publish_root(
        publish_root,
        active_archive_roots=active_archive_roots,
    )
    ledger = resume_ledger(plan_path, staging_root)
    if not ledger["all_complete"]:
        missing = [row["request_hash"] for row in ledger["units"] if not row["complete"]]
        _append_failure(
            staging_root,
            {
                "failure_class": "partial_staging_blocks_publication",
                "plan_sha256": plan["plan_sha256"],
                "incomplete_request_hashes": missing,
            },
        )
        raise MaterializationBlocked(
            f"all request units must be complete before publication; incomplete={len(missing)}"
        )

    hourly_rows = []
    daily_rows = []
    coverage_rows = []
    try:
        for request in plan["requests"]:
            hourly, daily, coverage = _normalize_request(plan, request, staging_root)
            hourly_rows.extend(hourly)
            daily_rows.extend(daily)
            coverage_rows.extend(coverage)
    except MaterializationBlocked as exc:
        _append_failure(
            staging_root,
            {
                "failure_class": "materialization_validation_failed",
                "plan_sha256": plan["plan_sha256"],
                "error": str(exc),
            },
        )
        raise
    if not hourly_rows or not daily_rows or not coverage_rows:
        _append_failure(
            staging_root,
            {
                "failure_class": "zero_derived_rows",
                "plan_sha256": plan["plan_sha256"],
            },
        )
        raise MaterializationBlocked("zero derived rows can never be published")

    hourly_rows.sort(
        key=lambda row: (row["market_id"], row["target_date"], row["valid_time_utc"])
    )
    daily_rows.sort(
        key=lambda row: (
            row["market_id"],
            row["target_date"],
            int(row["cutoff_hour_local"]),
        )
    )
    coverage_rows.sort(
        key=lambda row: (
            row["market_id"],
            row["target_date"],
            int(row["cutoff_hour_local"]),
        )
    )
    publish_root.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=".pit-forecast-build-", dir=publish_root))
    try:
        plan_copy = temp_dir / "plan.json"
        plan_copy.write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        hourly_path = temp_dir / "forecast_hourly.jsonl"
        daily_path = temp_dir / "forecast_daily.jsonl"
        coverage_path = temp_dir / "coverage.jsonl"
        exclusions_path = temp_dir / "exclusions.json"
        _write_jsonl(hourly_path, hourly_rows)
        _write_jsonl(daily_path, daily_rows)
        _write_jsonl(coverage_path, coverage_rows)
        exclusions_path.write_text(
            json.dumps(plan["consumer_dispositions"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        files = {}
        for path in (plan_copy, hourly_path, daily_path, coverage_path, exclusions_path):
            files[path.name] = {
                "sha256": sha256_file(path),
                "byte_count": path.stat().st_size,
            }
        identity = {
            "plan_sha256": plan["plan_sha256"],
            "files": files,
            "hourly_rows": len(hourly_rows),
            "daily_rows": len(daily_rows),
            "coverage_rows": len(coverage_rows),
        }
        corpus_id = _sha256_payload(identity)
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "corpus_id": corpus_id,
            "corpus_role": "training_only",
            "plan_sha256": plan["plan_sha256"],
            "target_year": plan["target_year"],
            "target_year_excluded": True,
            "years": plan["years"],
            "market_ids": plan["market_ids"],
            "cutoff_hours_local": plan["cutoff_hours_local"],
            "source_fields": plan["source_fields"],
            "issue_contract": plan["issue_contract"],
            "normalizer_version": plan["normalizer_version"],
            "consumer_dispositions": plan["consumer_dispositions"],
            "active_archive_pinned": True,
            "daily_path_discoverable": False,
            "compatibility_fallback_allowed": False,
            "publication": {
                "content_addressed": True,
                "atomic": True,
                "in_place_overwrite_allowed": False,
            },
            "coverage": {
                "status": "complete",
                "expected_market_dates": plan["summary"]["expected_market_dates"],
                "expected_market_date_cutoffs": plan["summary"]["expected_market_date_cutoffs"],
                "expected_field_date_cutoff_cells": plan["summary"]["expected_field_date_cutoff_cells"],
                "coverage_rows": len(coverage_rows),
            },
            "row_counts": {
                "hourly": len(hourly_rows),
                "daily": len(daily_rows),
                "coverage": len(coverage_rows),
            },
            "files": files,
        }
        manifest["manifest_sha256"] = _self_hash(manifest, "manifest_sha256")
        manifest_path = temp_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verify_corpus_manifest(manifest_path)
        final_root = publish_root / "corpora" / corpus_id
        final_root.parent.mkdir(parents=True, exist_ok=True)
        if final_root.exists():
            raise MaterializationBlocked(
                f"content-addressed corpus already exists; overwrite refused: {final_root}"
            )
        temp_dir.replace(final_root)
        verify_corpus_manifest(final_root / "manifest.json")
        return final_root / "manifest.json"
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        raise


def verify_corpus_manifest(manifest_path):
    manifest_path = Path(manifest_path)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusVerificationError(f"cannot read corpus manifest: {manifest_path}") from exc
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise CorpusVerificationError("unsupported PIT forecast corpus manifest schema")
    if manifest.get("manifest_sha256") != _self_hash(manifest, "manifest_sha256"):
        raise CorpusVerificationError("corpus manifest self-hash mismatch")
    if manifest.get("corpus_role") != "training_only":
        raise CorpusVerificationError("corpus role is not training_only")
    if manifest.get("target_year_excluded") is not True:
        raise CorpusVerificationError("target-year exclusion is not asserted")
    if int(manifest.get("target_year") or 0) in [int(year) for year in manifest.get("years") or []]:
        raise CorpusVerificationError("target year appears in corpus years")
    if manifest.get("daily_path_discoverable") is not False:
        raise CorpusVerificationError("corpus is discoverable by an active archive path")
    if manifest.get("compatibility_fallback_allowed") is not False:
        raise CorpusVerificationError("compatibility fallback is not fail-closed")
    if (manifest.get("coverage") or {}).get("status") != "complete":
        raise CorpusVerificationError("corpus coverage is not complete")
    required_files = {
        "plan.json",
        "forecast_hourly.jsonl",
        "forecast_daily.jsonl",
        "coverage.jsonl",
        "exclusions.json",
    }
    files = manifest.get("files") or {}
    if set(files) != required_files:
        raise CorpusVerificationError("corpus manifest file inventory is incomplete")
    for name, expected in files.items():
        path = manifest_path.parent / name
        if not path.is_file():
            raise CorpusVerificationError(f"corpus file is missing: {name}")
        if path.stat().st_size != int(expected.get("byte_count") or -1):
            raise CorpusVerificationError(f"corpus file byte count mismatch: {name}")
        if sha256_file(path) != expected.get("sha256"):
            raise CorpusVerificationError(f"corpus file hash mismatch: {name}")
    plan = load_plan(manifest_path.parent / "plan.json")
    if plan["plan_sha256"] != manifest.get("plan_sha256"):
        raise CorpusVerificationError("published plan does not match corpus manifest")
    if plan["consumer_dispositions"] != manifest.get("consumer_dispositions"):
        raise CorpusVerificationError("manifest consumer dispositions differ from the plan")
    try:
        exclusions = json.loads(
            (manifest_path.parent / "exclusions.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusVerificationError("cannot read corpus exclusions receipt") from exc
    if exclusions != manifest.get("consumer_dispositions"):
        raise CorpusVerificationError("exclusions receipt differs from the manifest")
    row_counts = manifest.get("row_counts") or {}
    if any(int(row_counts.get(kind) or 0) <= 0 for kind in ("hourly", "daily", "coverage")):
        raise CorpusVerificationError("corpus row counts must all be positive")
    coverage = manifest.get("coverage") or {}
    if int(coverage.get("coverage_rows") or 0) != int(row_counts["coverage"]):
        raise CorpusVerificationError("coverage receipt row count differs from manifest")
    if int(coverage.get("expected_market_date_cutoffs") or 0) != int(row_counts["daily"]):
        raise CorpusVerificationError("daily row count differs from planned cutoff matrix")
    identity = {
        "plan_sha256": manifest.get("plan_sha256"),
        "files": files,
        "hourly_rows": int(row_counts.get("hourly") or 0),
        "daily_rows": int(row_counts.get("daily") or 0),
        "coverage_rows": int(row_counts.get("coverage") or 0),
    }
    if manifest.get("corpus_id") != _sha256_payload(identity):
        raise CorpusVerificationError("content-addressed corpus identity mismatch")
    return manifest


class PITForecastTrainingCorpus:
    """Explicit reader for one verified training corpus; no ambient fallback."""

    def __init__(self, manifest_path, market_id):
        self.manifest_path = Path(manifest_path)
        self.manifest = verify_corpus_manifest(self.manifest_path)
        self.market_id = str(market_id)
        if self.market_id not in self.manifest["market_ids"]:
            raise CorpusVerificationError(f"market is absent from corpus: {self.market_id}")
        self.years = tuple(int(year) for year in self.manifest["years"])
        self.cutoff_hours = tuple(int(hour) for hour in self.manifest["cutoff_hours_local"])
        self._daily = {}
        self._profiles = defaultdict(list)
        with (self.manifest_path.parent / "forecast_daily.jsonl").open(
            "r",
            encoding="utf-8",
        ) as handle:
            for line in handle:
                row = json.loads(line)
                if row.get("market_id") != self.market_id:
                    continue
                if row.get("derived_row_sha256") != _self_hash(row, "derived_row_sha256"):
                    raise CorpusVerificationError("daily derived-row hash mismatch")
                key = (row["target_date"], int(row["cutoff_hour_local"]))
                if key in self._daily:
                    raise CorpusVerificationError(f"duplicate daily PIT row: {key}")
                self._daily[key] = row
        with (self.manifest_path.parent / "forecast_hourly.jsonl").open(
            "r",
            encoding="utf-8",
        ) as handle:
            for line in handle:
                row = json.loads(line)
                if row.get("market_id") != self.market_id:
                    continue
                if row.get("derived_row_sha256") != _self_hash(row, "derived_row_sha256"):
                    raise CorpusVerificationError("hourly derived-row hash mismatch")
                self._profiles[row["target_date"]].append(row)
        for rows in self._profiles.values():
            rows.sort(key=lambda row: row["valid_time_utc"])

    def resolve(self, target_date, cutoff_hour):
        target_date = str(target_date)
        cutoff_hour = int(cutoff_hour)
        daily = self._daily.get((target_date, cutoff_hour))
        if daily is None:
            raise CorpusVerificationError(
                f"no cutoff-valid PIT daily forecast for {self.market_id} {target_date} {cutoff_hour:02d}:00"
            )
        profiles = []
        for row in self._profiles.get(target_date) or []:
            if cutoff_hour not in [int(hour) for hour in row.get("safe_cutoff_hours_local") or []]:
                raise CorpusVerificationError(
                    f"hourly row is not safe for requested cutoff: {target_date} {cutoff_hour}"
                )
            values = row["values"]
            valid_local = datetime.fromisoformat(row["valid_time_local"])
            profiles.append(
                {
                    "minute_of_day": valid_local.hour * 60 + valid_local.minute,
                    "time": row["valid_time_local"],
                    "temp_native": values.get("target_temp_native"),
                    "temp_c": native_to_c(
                        values.get("target_temp_native"),
                        daily["temperature_unit"],
                    ),
                    "cloud_cover": values.get("cloud_cover"),
                    "low_cloud": values.get("low_cloud"),
                    "mid_cloud": values.get("mid_cloud"),
                    "high_cloud": values.get("high_cloud"),
                    "solar": values.get("shortwave_radiation"),
                    "wind_kmh": values.get("wind_speed_kmh"),
                    "direct_radiation": values.get("direct_radiation"),
                    "diffuse_radiation": values.get("diffuse_radiation"),
                    "cape": values.get("cape"),
                    "temperature_925hpa": values.get("temperature_925hpa"),
                    "temperature_850hpa": values.get("temperature_850hpa"),
                    "geopotential_height_500hpa": values.get("geopotential_height_500hpa"),
                    "wind_gust_kmh": values.get("wind_gust_kmh"),
                    "visibility": values.get("visibility"),
                    "precipitation_probability": values.get("precipitation_probability"),
                    "precipitation": values.get("precipitation"),
                    "soil_temperature_0cm": values.get("soil_temperature_0cm"),
                    "soil_moisture_0_to_1cm": values.get("soil_moisture_0_to_1cm"),
                    "vapour_pressure_deficit": values.get("vapour_pressure_deficit"),
                    "et0_fao_evapotranspiration": values.get("et0_fao_evapotranspiration"),
                    "_pit_provenance": {
                        key: row.get(key)
                        for key in (
                            "provider",
                            "endpoint",
                            "request_hash",
                            "source_model",
                            "run_id",
                            "issue_time_utc",
                            "available_at_utc",
                            "issue_evidence_kind",
                            "lead_days",
                            "lead_hours",
                            "normalizer_version",
                            "raw_response_sha256",
                        )
                    },
                }
            )
        provenance = {
            key: daily.get(key)
            for key in (
                "provider",
                "endpoint",
                "request_hash",
                "source_model",
                "run_id",
                "issue_time_utc",
                "available_at_utc",
                "issue_evidence_kind",
                "lead_days",
                "lead_hours",
                "temperature_unit",
                "normalizer_version",
                "raw_response_sha256",
                "feature_as_of_utc",
            )
        }
        provenance["corpus_id"] = self.manifest["corpus_id"]
        return {
            "forecast_high": daily["forecast_high_native"],
            "profile_rows": profiles,
            "provenance": provenance,
        }


def _parse_int_list(value):
    return tuple(int(item.strip()) for item in str(value).split(",") if item.strip())


def _parse_market_list(value):
    return tuple(item.strip() for item in str(value).split(",") if item.strip())


def build_parser():
    parser = argparse.ArgumentParser(
        description="Plan and verify an immutable training-only PIT forecast corpus (no network client)."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Write an immutable dry-run request plan.")
    plan.add_argument("--out", required=True)
    plan.add_argument("--years", default=",".join(str(year) for year in DEFAULT_YEARS))
    plan.add_argument("--target-year", type=int, default=DEFAULT_TARGET_YEAR)
    plan.add_argument("--markets", default="")
    plan.add_argument("--season-start", default="05-10")
    plan.add_argument("--season-end", default="08-31")
    plan.add_argument("--cutoff-hours", default=",".join(str(hour) for hour in DEFAULT_CUTOFF_HOURS))
    plan.add_argument("--source-model", default=DEFAULT_MODEL)
    plan.add_argument("--lead-days", type=int, default=DEFAULT_LEAD_DAYS)
    plan.add_argument("--planned-at-utc", default="")

    resume = subparsers.add_parser("resume-status", help="Verify staged request units by hash.")
    resume.add_argument("--plan", required=True)
    resume.add_argument("--staging-root", required=True)

    materialize = subparsers.add_parser(
        "materialize",
        help="Atomically publish a complete staged corpus; never fetches data.",
    )
    materialize.add_argument("--plan", required=True)
    materialize.add_argument("--staging-root", required=True)
    materialize.add_argument("--publish-root", required=True)
    return parser


def _month_day(value):
    try:
        month, day = str(value).split("-", 1)
        return int(month), int(day)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"invalid MM-DD value: {value}") from exc


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "plan":
        plan = build_plan(
            years=_parse_int_list(args.years),
            target_year=args.target_year,
            market_ids=_parse_market_list(args.markets) or None,
            season_start=_month_day(args.season_start),
            season_end=_month_day(args.season_end),
            cutoff_hours=_parse_int_list(args.cutoff_hours),
            source_model=args.source_model,
            lead_days=args.lead_days,
            planned_at_utc=args.planned_at_utc or None,
        )
        path = write_immutable_plan(args.out, plan)
        print(
            json.dumps(
                {
                    "mode": plan["mode"],
                    "network_authorized": False,
                    "path": str(path),
                    "plan_sha256": plan["plan_sha256"],
                    "summary": plan["summary"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.command == "resume-status":
        print(json.dumps(resume_ledger(args.plan, args.staging_root), indent=2, sort_keys=True))
        return
    if args.command == "materialize":
        manifest = materialize_corpus(args.plan, args.staging_root, args.publish_root)
        print(json.dumps({"manifest": str(manifest)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
