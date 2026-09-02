"""Outcome-blind bounded collection for the multi-year Previous Runs corpus.

The module and complete denominator first existed in a plan-only ancestor
commit with no HTTP transport. Collection support is deliberately confined to
the descendant implementation commit and remains bound to that immutable plan.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
import stat
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlsplit

from weather.market.market_registry import BUILTIN_SPECS


ENDPOINT = "https://previous-runs-api.open-meteo.com/v1/forecast"
SOURCE = "open_meteo_previous_runs"
ISSUE_TIME_BASIS = "fixed_lead_day_offset"
HISTORICAL_AVAILABILITY = "HISTORICAL_FIRST_AVAILABILITY_UNPROVEN"
PLAN_SCHEMA_VERSION = "previous_runs_research_collection_plan_v1"
SOURCE_GIT_TIP = "f2722a4ed6c82557cca10325db82e5c66d03788b"
SOURCE_GIT_TREE = "11b69220188449a84929d678b4146c161922da78"
OUTPUT_ROOT = r"C:\Users\Michael\Documents\Codex\inputs\pit-12field-multiyear-2021-2025"
ASSIGNMENT_PATH = "config/international_live_execution_host.json"
ASSIGNMENT_SHA256 = "111367a167628fcd78753f341beac119f81d9b87380989a9299d165daad80a5b"
WRAPPER_ENVIRONMENT = "WEATHER_RESEARCH_COLLECTION_WRAPPER_ACTIVE"
MAX_RAW_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_RESPONSE_HEADER_BYTES = 1024 * 1024
UNIT_RECEIPT_SCHEMA_VERSION = "previous_runs_research_unit_receipt_v1"
ATTEMPT_RECEIPT_SCHEMA_VERSION = "previous_runs_research_attempt_receipt_v1"
RESUME_STATE_SCHEMA_VERSION = "previous_runs_research_resume_state_v1"
RUN_SUMMARY_SCHEMA_VERSION = "previous_runs_research_run_summary_v1"
CORPUS_MANIFEST_SCHEMA_VERSION = "previous_runs_research_corpus_manifest_v1"
FINAL_VERIFICATION_SCHEMA_VERSION = "previous_runs_research_final_verification_v1"

FIELDS = (
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
LEADS = tuple(range(1, 8))
YEARS = tuple(range(2021, 2026))
SEGMENTS = (
    ("may10-jun30", "05-10", "06-30", 52),
    ("jul01-aug31", "07-01", "08-31", 62),
)
CSV_COLUMNS = (
    "market",
    "target_datetime_local",
    "field",
    "lead_days",
    "value",
    "unit",
    "issue_time_basis",
    "source",
)
EXPECTED_UNITS = {
    "temperature_2m": "native_temperature",
    "cloud_cover": "%",
    "shortwave_radiation": "W/m²",
    "wind_speed_10m": "km/h",
    "cape": "J/kg",
    "direct_radiation": "W/m²",
    "diffuse_radiation": "W/m²",
    "wind_gusts_10m": "km/h",
    "precipitation_probability": "%",
    "precipitation": "mm",
    "vapour_pressure_deficit": "kPa",
    "et0_fao_evapotranspiration": "mm",
}


class PlanError(RuntimeError):
    """The immutable request plan is malformed or has drifted."""


class CollectionError(RuntimeError):
    """A bounded collection operation failed closed."""


class ResponseIntegrityError(CollectionError):
    """A provider response cannot be safely normalized."""


class TransportFailure(RuntimeError):
    """The injected transport failed before returning an HTTP response."""


class RetainedArtifactError(CollectionError):
    """Retained evidence is missing, changed, or internally inconsistent."""


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class RequestsTransport:
    """Bounded streaming transport for the one authorized endpoint."""

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, object],
        timeout: tuple[float, float],
        maximum_bytes: int,
    ) -> TransportResponse:
        if url != ENDPOINT or urlsplit(url).hostname != "previous-runs-api.open-meteo.com":
            raise CollectionError("transport endpoint differs from operator authorization")
        import requests

        try:
            with requests.get(
                url,
                params=dict(params),
                timeout=timeout,
                stream=True,
            ) as response:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    body.extend(chunk)
                    if len(body) > maximum_bytes:
                        raise ResponseIntegrityError(
                            "raw response exceeds the 64 MiB bound"
                        )
                return TransportResponse(
                    status_code=int(response.status_code),
                    headers={
                        str(key): str(value)
                        for key, value in response.headers.items()
                    },
                    body=bytes(body),
                )
        except ResponseIntegrityError:
            raise
        except requests.RequestException as exc:
            raise TransportFailure(str(exc)) from exc


def canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def payload_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def self_hash(payload: dict, field: str) -> str:
    body = dict(payload)
    body.pop(field, None)
    return payload_sha256(body)


def _hourly_parameter() -> str:
    return ",".join(
        f"{field}_previous_day{lead}" for field in FIELDS for lead in LEADS
    )


def _unit_inventory(spec) -> dict[str, str]:
    inventory = dict(EXPECTED_UNITS)
    inventory["temperature_2m"] = (
        "°F" if spec.om_temperature_unit == "fahrenheit" else "°C"
    )
    return inventory


def build_plan(*, planned_at_utc: str) -> dict:
    planned = datetime.fromisoformat(planned_at_utc.replace("Z", "+00:00"))
    if planned.tzinfo is None:
        raise PlanError("planned_at_utc must be timezone-aware")
    requests = []
    for spec in BUILTIN_SPECS:
        for year in YEARS:
            for segment_id, start_mmdd, end_mmdd, day_count in SEGMENTS:
                start_date = f"{year}-{start_mmdd}"
                end_date = f"{year}-{end_mmdd}"
                parameters = {
                    "end_date": end_date,
                    "hourly": _hourly_parameter(),
                    "latitude": spec.lat,
                    "longitude": spec.lon,
                    "start_date": start_date,
                    "temperature_unit": spec.om_temperature_unit,
                    "timezone": spec.timezone,
                    "wind_speed_unit": "kmh",
                }
                request = {
                    "day_count": day_count,
                    "endpoint": ENDPOINT,
                    "expected_long_rows_before_missingness": (
                        day_count * 24 * len(FIELDS) * len(LEADS)
                    ),
                    "expected_units": _unit_inventory(spec),
                    "fields": list(FIELDS),
                    "historical_availability": HISTORICAL_AVAILABILITY,
                    "issue_time_basis": ISSUE_TIME_BASIS,
                    "leads": list(LEADS),
                    "market": spec.id,
                    "native_temperature_unit": spec.display_unit,
                    "parameters": parameters,
                    "parameters_sha256": payload_sha256(parameters),
                    "segment": segment_id,
                    "source": SOURCE,
                    "timezone": spec.timezone,
                    "unit_id": f"{spec.id}--{year}--{segment_id}",
                    "year": year,
                }
                request["request_sha256"] = self_hash(request, "request_sha256")
                requests.append(request)

    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "status": "IMMUTABLE_OUTCOME_BLIND_PLAN_BEFORE_NETWORK_ACCESS",
        "planned_at_utc": planned.astimezone(timezone.utc).isoformat(),
        "purpose": (
            "Collect research-only multi-year Open-Meteo Previous Runs forecast "
            "features; do not fit, select, score, or freeze a model."
        ),
        "source_git": {
            "tip": SOURCE_GIT_TIP,
            "tree": SOURCE_GIT_TREE,
            "branch": (
                "origin/codex/workstation-research-12field-seasonal-"
                "challenger-2026-09-86a"
            ),
        },
        "provider_contract": {
            "endpoint": ENDPOINT,
            "allowed_hosts": ["previous-runs-api.open-meteo.com"],
            "authentication": "none",
            "source": SOURCE,
            "issue_time_basis": ISSUE_TIME_BASIS,
            "historical_availability": HISTORICAL_AVAILABILITY,
            "retrieval_time_is_historical_availability": False,
            "caller_supplied_issue_or_availability_time_allowed": False,
            "stitched_or_historical_forecast_source_allowed": False,
        },
        "scope": {
            "markets": [spec.id for spec in BUILTIN_SPECS],
            "years": list(YEARS),
            "date_window": "May 10 through August 31 inclusive",
            "segments_per_market_year": [
                {"id": row[0], "start_mmdd": row[1], "end_mmdd": row[2]}
                for row in SEGMENTS
            ],
            "fields": list(FIELDS),
            "leads": list(LEADS),
            "cadence": "hourly",
            "normalized_csv_columns": list(CSV_COLUMNS),
        },
        "expected_denominator": {
            "dates_per_year": 114,
            "target_dates": 570,
            "market_days": 6840,
            "request_units": len(requests),
            "long_rows_before_missingness": 13_789_440,
            "missing_cells_must_remain_in_denominator": True,
        },
        "output_contract": {
            "root": OUTPUT_ROOT,
            "must_be_new": True,
            "must_be_non_reparse": True,
            "must_be_outside_frozen_mirror": True,
            "completed_units_may_be_overwritten": False,
            "atomic_publication": True,
            "retain_failed_and_partial_evidence": True,
            "immutable_plan_and_request_hash_on_every_artifact": True,
            "post_collection_acl": {
                "identity": "CodexSandboxOffline",
                "access_control_type": "Deny",
                "rights": [
                    "Write",
                    "Delete",
                    "DeleteSubdirectoriesAndFiles",
                ],
            },
        },
        "execution_contract": {
            "profile": "workstation_research_collection_v1",
            "assignment_path": ASSIGNMENT_PATH,
            "assignment_sha256": ASSIGNMENT_SHA256,
            "bind_tracked_workstation_host_and_attending_principal": True,
            "refuse_dedicated_capture_host": True,
            "host_global_mutex": "Global\\WeatherProjectHeavyWorkloadV1",
            "share_portable_live_poison_state": True,
            "kill_on_close_child_tree": True,
            "sequential_requests_only": True,
            "overall_runtime_seconds": 14_400,
            "connect_timeout_seconds": 10,
            "read_timeout_seconds": 120,
        },
        "retry_contract": {
            "maximum_attempts_per_unit": 3,
            "retryable": ["transport_failure", "HTTP_429", "HTTP_5xx"],
            "non_retryable": ["HTTP_4xx_except_429", "validation_failure"],
            "fallback_delays_seconds": [5, 15],
            "honor_retry_after": True,
            "retry_after_must_fit_overall_runtime": True,
            "concurrent_retries": False,
            "permanent_failure_remains_in_denominator": True,
        },
        "artifact_contract": {
            "per_unit": [
                "raw-response.json",
                "response-headers.json",
                "normalized.csv",
                "receipt.json",
                "resume-state.json",
            ],
            "raw_response_sha256_and_bytes": True,
            "normalized_sha256_rows_and_bytes": True,
            "field_and_lead_non_null_counts": True,
            "retrieval_timestamp_is_retrieval_evidence_only": True,
        },
        "validation_contract": {
            "unique_key": [
                "market",
                "target_datetime_local",
                "field",
                "lead_days",
            ],
            "finite_where_present": True,
            "expected_local_hourly_coverage": True,
            "exact_field_and_lead_partitions": True,
            "exact_timezone_unit_request_identity": True,
            "coverage_matrices": [
                "year",
                "market",
                "field",
                "lead",
                "month",
                "segment",
            ],
        },
        "positive_controls": {
            "frozen_2026_root": r"C:\Users\Michael\Documents\Codex\inputs\pit-12field-20260810",
            "frozen_2026_values_may_be_read": False,
            "required_column_contract": list(CSV_COLUMNS),
            "historical_temperature_overlap": (
                "compare only if an exact hash-bound workstation archive row exists"
            ),
            "verify_2025_features_without_outcomes_or_market_evidence": True,
        },
        "prohibited_data_and_actions": [
            "outcomes",
            "settlements",
            "market prices",
            "market probabilities",
            "model fitting",
            "model selection",
            "model scoring",
            "model freeze",
            "2026 provider collection",
            "frozen mirror mutation",
            "production contact",
            "Scheduler mutation",
            "credential access",
            "exchange contact",
            "release or pointer creation",
            "promotion",
            "alpha allocation",
            "confirmation window",
        ],
        "next_experiment_preregistered_not_executed": {
            "train_years": [2021, 2022, 2023, 2024],
            "untouched_terminal_evaluation_year": 2025,
            "model_family": "incumbent-anchored residual correction",
            "primary_sensitivity_leads": [2, 3, 4, 5, 6, 7],
            "2026_role": "external secondary evaluation only; never pooled with 2025",
        },
        "requests": requests,
    }
    plan["plan_sha256"] = self_hash(plan, "plan_sha256")
    verify_plan(plan)
    return plan


def verify_plan(plan: dict) -> None:
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise PlanError("unexpected plan schema")
    if plan.get("plan_sha256") != self_hash(plan, "plan_sha256"):
        raise PlanError("plan hash mismatch")
    if plan.get("status") != "IMMUTABLE_OUTCOME_BLIND_PLAN_BEFORE_NETWORK_ACCESS":
        raise PlanError("plan status differs from the pre-network authorization")
    if plan.get("source_git") != {
        "tip": SOURCE_GIT_TIP,
        "tree": SOURCE_GIT_TREE,
        "branch": (
            "origin/codex/workstation-research-12field-seasonal-"
            "challenger-2026-09-86a"
        ),
    }:
        raise PlanError("source branch binding differs from the authorization")
    if (plan.get("provider_contract") or {}).get("endpoint") != ENDPOINT:
        raise PlanError("endpoint differs from operator authorization")
    if (plan.get("scope") or {}).get("fields") != list(FIELDS):
        raise PlanError("field contract differs from operator authorization")
    if (plan.get("scope") or {}).get("leads") != list(LEADS):
        raise PlanError("lead contract differs from operator authorization")
    expected_markets = [spec.id for spec in BUILTIN_SPECS]
    if (plan.get("scope") or {}).get("markets") != expected_markets:
        raise PlanError("market contract differs from operator authorization")
    if (plan.get("scope") or {}).get("years") != list(YEARS):
        raise PlanError("year contract differs from operator authorization")
    if (plan.get("scope") or {}).get("segments_per_market_year") != [
        {"id": segment[0], "start_mmdd": segment[1], "end_mmdd": segment[2]}
        for segment in SEGMENTS
    ]:
        raise PlanError("date-segment contract differs from operator authorization")
    provider_contract = plan.get("provider_contract") or {}
    if (
        provider_contract.get("allowed_hosts")
        != ["previous-runs-api.open-meteo.com"]
        or provider_contract.get("source") != SOURCE
        or provider_contract.get("issue_time_basis") != ISSUE_TIME_BASIS
        or provider_contract.get("historical_availability")
        != HISTORICAL_AVAILABILITY
        or provider_contract.get("caller_supplied_issue_or_availability_time_allowed")
        is not False
        or provider_contract.get("stitched_or_historical_forecast_source_allowed")
        is not False
    ):
        raise PlanError("provider provenance contract differs from authorization")
    requests = plan.get("requests") or []
    expected_count = len(BUILTIN_SPECS) * len(YEARS) * len(SEGMENTS)
    if len(requests) != expected_count:
        raise PlanError("request denominator is incomplete")
    seen = set()
    specs_by_id = {spec.id: spec for spec in BUILTIN_SPECS}
    expected_units = {
        spec.id: _unit_inventory(spec) for spec in BUILTIN_SPECS
    }
    expected_request_keys = {
        (spec.id, year, segment[0])
        for spec in BUILTIN_SPECS
        for year in YEARS
        for segment in SEGMENTS
    }
    for request in requests:
        if request.get("request_sha256") != self_hash(request, "request_sha256"):
            raise PlanError("request hash mismatch")
        if request.get("parameters_sha256") != payload_sha256(request["parameters"]):
            raise PlanError("parameter hash mismatch")
        if request.get("endpoint") != ENDPOINT:
            raise PlanError("request endpoint drifted")
        if request.get("fields") != list(FIELDS) or request.get("leads") != list(LEADS):
            raise PlanError("request field or lead matrix drifted")
        market = request.get("market")
        year = request.get("year")
        segment_id = request.get("segment")
        request_key = (market, year, segment_id)
        if request_key not in expected_request_keys:
            raise PlanError("request market/year/segment is outside authorization")
        spec = specs_by_id[str(market)]
        segment = next(item for item in SEGMENTS if item[0] == segment_id)
        expected_parameters = {
            "end_date": f"{year}-{segment[2]}",
            "hourly": _hourly_parameter(),
            "latitude": spec.lat,
            "longitude": spec.lon,
            "start_date": f"{year}-{segment[1]}",
            "temperature_unit": spec.om_temperature_unit,
            "timezone": spec.timezone,
            "wind_speed_unit": "kmh",
        }
        if request.get("parameters") != expected_parameters:
            raise PlanError("request parameters differ from the exact authorized query")
        if (
            request.get("timezone") != spec.timezone
            or request.get("expected_units") != expected_units[str(market)]
            or request.get("day_count") != segment[3]
            or request.get("expected_long_rows_before_missingness")
            != segment[3] * 24 * len(FIELDS) * len(LEADS)
            or request.get("source") != SOURCE
            or request.get("issue_time_basis") != ISSUE_TIME_BASIS
            or request.get("historical_availability")
            != HISTORICAL_AVAILABILITY
        ):
            raise PlanError("request identity or denominator differs")
        unit_id = request.get("unit_id")
        if unit_id != f"{market}--{year}--{segment_id}" or unit_id in seen:
            raise PlanError("duplicate or missing request unit")
        seen.add(unit_id)
    if {
        (request["market"], request["year"], request["segment"])
        for request in requests
    } != expected_request_keys:
        raise PlanError("request matrix is incomplete")
    expected_rows = sum(
        int(request["expected_long_rows_before_missingness"])
        for request in requests
    )
    denominator = plan.get("expected_denominator") or {}
    if expected_rows != 13_789_440 or denominator.get(
        "long_rows_before_missingness"
    ) != expected_rows:
        raise PlanError("expected row denominator drifted")


def write_plan(path: str | Path, plan: dict) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(plan, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
    return destination


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_record(path: Path, *, relative_to: Path) -> dict:
    return {
        "relative_path": path.relative_to(relative_to).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
    }


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_json_atomic(path: Path, payload: object) -> None:
    _write_bytes_atomic(path, _json_bytes(payload))


def _write_json_private(path: Path, payload: object) -> None:
    with path.open("xb") as handle:
        handle.write(_json_bytes(payload))
        handle.flush()
        os.fsync(handle.fileno())


def _is_reparse_point(path: Path) -> bool:
    details = path.stat()
    attributes = int(getattr(details, "st_file_attributes", 0))
    return path.is_symlink() or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def load_bound_plan(path: str | Path) -> tuple[dict, bytes]:
    plan_path = Path(path)
    plan_bytes = plan_path.read_bytes()
    try:
        plan = json.loads(plan_bytes)
    except (TypeError, ValueError) as exc:
        raise PlanError("collection plan is not valid JSON") from exc
    verify_plan(plan)
    if str((plan.get("output_contract") or {}).get("root")) != OUTPUT_ROOT:
        raise PlanError("collection output root differs from the immutable plan")
    if (plan.get("execution_contract") or {}).get("profile") != (
        "workstation_research_collection_v1"
    ):
        raise PlanError("collection execution profile differs from the immutable plan")
    if any(
        forbidden in request.get("parameters", {})
        for request in plan["requests"]
        for forbidden in (
            "issue_time_utc",
            "available_at_utc",
            "run_id",
            "publication_time",
        )
    ):
        raise PlanError("a request manufactures historical availability evidence")
    return plan, plan_bytes


def initialize_output_root(
    plan: dict,
    plan_bytes: bytes,
    *,
    root: str | Path | None = None,
) -> Path:
    output_root = Path(root or plan["output_contract"]["root"])
    if not output_root.is_absolute():
        raise CollectionError("collection output root must be absolute")
    if not output_root.is_dir() or _is_reparse_point(output_root):
        raise CollectionError("collection output root is absent or redirected")
    plan_copy = output_root / "collection-plan.json"
    if plan_copy.exists():
        if plan_copy.read_bytes() != plan_bytes:
            raise RetainedArtifactError("retained collection plan differs byte-for-byte")
    else:
        _write_bytes_atomic(plan_copy, plan_bytes)
    metadata = {
        "schema_version": "previous_runs_research_root_metadata_v1",
        "plan_sha256": plan["plan_sha256"],
        "plan_file_sha256": _sha256_bytes(plan_bytes),
        "source_git_tip": plan["source_git"]["tip"],
        "source_git_tree": plan["source_git"]["tree"],
        "output_root": str(output_root),
        "historical_availability": HISTORICAL_AVAILABILITY,
        "outcome_data_allowed": False,
    }
    metadata["metadata_sha256"] = self_hash(metadata, "metadata_sha256")
    metadata_path = output_root / "root-metadata.json"
    if metadata_path.exists():
        try:
            retained = json.loads(metadata_path.read_bytes())
        except (TypeError, ValueError) as exc:
            raise RetainedArtifactError("retained root metadata is malformed") from exc
        if retained != metadata:
            raise RetainedArtifactError("retained root metadata differs from the plan")
    else:
        _write_json_atomic(metadata_path, metadata)
    (output_root / "units").mkdir(exist_ok=True)
    return output_root


def _expected_local_times(request: Mapping[str, object]) -> list[str]:
    start = datetime.fromisoformat(str(request["parameters"]["start_date"]))
    end = datetime.fromisoformat(str(request["parameters"]["end_date"]))
    cursor = start
    expected = []
    while cursor.date() <= end.date():
        expected.append(cursor.strftime("%Y-%m-%dT%H:%M"))
        cursor += timedelta(hours=1)
    if len(expected) != int(request["day_count"]) * 24:
        raise PlanError("request day count differs from its local-hour denominator")
    return expected


def _normalize_response(
    request: Mapping[str, object],
    body: bytes,
    destination: Path,
) -> dict:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise ResponseIntegrityError("response is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ResponseIntegrityError("response root must be a JSON object")
    if payload.get("timezone") != request["timezone"]:
        raise ResponseIntegrityError("response timezone differs from the request")
    hourly = payload.get("hourly")
    hourly_units = payload.get("hourly_units")
    if not isinstance(hourly, dict) or not isinstance(hourly_units, dict):
        raise ResponseIntegrityError("response lacks hourly data or units")
    times = hourly.get("time")
    expected_times = _expected_local_times(request)
    if not isinstance(times, list) or any(not isinstance(item, str) for item in times):
        raise ResponseIntegrityError("response local-time vector is malformed")
    if times != expected_times:
        if len(times) != len(set(times)):
            raise ResponseIntegrityError("response local-time vector contains duplicates")
        raise ResponseIntegrityError("response local-time vector is truncated or misaligned")

    series: dict[tuple[str, int], tuple[list[object], str, bool]] = {}
    missing_series = []
    for field in request["fields"]:
        expected_unit = request["expected_units"][field]
        for lead in request["leads"]:
            request_field = f"{field}_previous_day{lead}"
            values = hourly.get(request_field)
            actual_unit = hourly_units.get(request_field)
            if values is None:
                values = [None] * len(times)
                missing_series.append(request_field)
                if actual_unit is None:
                    actual_unit = expected_unit
            elif not isinstance(values, list) or len(values) != len(times):
                raise ResponseIntegrityError(
                    f"response series is truncated or malformed: {request_field}"
                )
            if actual_unit != expected_unit:
                raise ResponseIntegrityError(
                    f"response unit mismatch for {request_field}: {actual_unit!r}"
                )
            for value in values:
                if value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ResponseIntegrityError(
                        f"response value is non-numeric: {request_field}"
                    )
                if not math.isfinite(float(value)):
                    raise ResponseIntegrityError(
                        f"response value is non-finite: {request_field}"
                    )
            series[(field, int(lead))] = (values, str(actual_unit), request_field in missing_series)

    non_null_by_field: Counter[str] = Counter()
    non_null_by_lead: Counter[int] = Counter()
    non_null_by_field_lead: Counter[tuple[str, int]] = Counter()
    requested_by_month_field_lead: Counter[tuple[int, str, int]] = Counter()
    non_null_by_month_field_lead: Counter[tuple[int, str, int]] = Counter()
    row_count = 0
    with destination.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for time_index, target_datetime_local in enumerate(times):
            month = int(target_datetime_local[5:7])
            for field in request["fields"]:
                for lead in request["leads"]:
                    values, unit, _missing = series[(field, int(lead))]
                    value = values[time_index]
                    writer.writerow(
                        (
                            request["market"],
                            target_datetime_local,
                            field,
                            int(lead),
                            "" if value is None else str(value),
                            unit,
                            ISSUE_TIME_BASIS,
                            SOURCE,
                        )
                    )
                    row_count += 1
                    cell = (month, field, int(lead))
                    requested_by_month_field_lead[cell] += 1
                    if value is not None:
                        non_null_by_field[str(field)] += 1
                        non_null_by_lead[int(lead)] += 1
                        non_null_by_field_lead[(str(field), int(lead))] += 1
                        non_null_by_month_field_lead[cell] += 1
        handle.flush()
        os.fsync(handle.fileno())

    expected_rows = int(request["expected_long_rows_before_missingness"])
    if row_count != expected_rows:
        raise ResponseIntegrityError("normalized row count differs from the denominator")
    coverage_cells = []
    for month, field, lead in sorted(requested_by_month_field_lead):
        requested_count = requested_by_month_field_lead[(month, field, lead)]
        non_null_count = non_null_by_month_field_lead[(month, field, lead)]
        coverage_cells.append(
            {
                "month": month,
                "field": field,
                "lead_days": lead,
                "requested": requested_count,
                "non_null": non_null_count,
                "missing": requested_count - non_null_count,
            }
        )
    non_null_count = sum(non_null_by_field.values())
    return {
        "normalized_columns": list(CSV_COLUMNS),
        "row_count": row_count,
        "non_null_count": non_null_count,
        "missing_count": row_count - non_null_count,
        "missing_series": sorted(missing_series),
        "field_non_null_counts": {
            field: non_null_by_field[field] for field in request["fields"]
        },
        "lead_non_null_counts": {
            str(lead): non_null_by_lead[int(lead)] for lead in request["leads"]
        },
        "field_lead_non_null_counts": {
            f"{field}|{lead}": non_null_by_field_lead[(field, int(lead))]
            for field in request["fields"]
            for lead in request["leads"]
        },
        "coverage_cells": coverage_cells,
    }


def _validated_headers(headers: Mapping[str, str]) -> dict[str, str]:
    normalized = {str(key): str(value) for key, value in headers.items()}
    if len(canonical_bytes(normalized)) > MAX_RESPONSE_HEADER_BYTES:
        raise ResponseIntegrityError("response headers exceed the 1 MiB bound")
    return dict(sorted(normalized.items(), key=lambda item: item[0].lower()))


def _utc_iso(utcnow: Callable[[], datetime]) -> str:
    value = utcnow()
    if value.tzinfo is None:
        raise CollectionError("retrieval clock returned a naive timestamp")
    return value.astimezone(timezone.utc).isoformat()


def _retry_after_seconds(
    headers: Mapping[str, str],
    *,
    fallback: float,
    utcnow: Callable[[], datetime],
) -> float:
    value = next(
        (header_value for key, header_value in headers.items() if key.lower() == "retry-after"),
        None,
    )
    if value is None:
        return float(fallback)
    try:
        seconds = float(value)
        if seconds < 0 or not math.isfinite(seconds):
            raise ValueError
        return seconds
    except (TypeError, ValueError):
        try:
            deadline = parsedate_to_datetime(str(value))
        except (TypeError, ValueError) as exc:
            raise ResponseIntegrityError("Retry-After header is malformed") from exc
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        now = utcnow()
        if now.tzinfo is None:
            raise CollectionError("retry clock returned a naive timestamp")
        return max(0.0, (deadline - now.astimezone(timezone.utc)).total_seconds())


def _unit_root(output_root: Path, request: Mapping[str, object]) -> Path:
    unit_id = str(request["unit_id"])
    if not unit_id or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-" for character in unit_id):
        raise PlanError("request unit id is not a canonical path component")
    return output_root / "units" / unit_id


def _next_attempt_number(unit_root: Path) -> int:
    attempts_root = unit_root / "attempts"
    existing = []
    if attempts_root.exists():
        for path in attempts_root.iterdir():
            if path.is_dir() and path.name.startswith("attempt-"):
                try:
                    existing.append(int(path.name.split("-", 1)[1]))
                except ValueError:
                    continue
    return max(existing, default=0) + 1


def _preserve_interrupted_stages(unit_root: Path) -> None:
    attempts_root = unit_root / "attempts"
    attempts_root.mkdir(parents=True, exist_ok=True)
    for path in sorted(unit_root.glob(".attempt-*.publishing")):
        if not path.is_dir():
            raise RetainedArtifactError("interrupted attempt marker is not a directory")
        destination = attempts_root / f"interrupted-{path.name[9:-11]}"
        if destination.exists():
            raise RetainedArtifactError("interrupted attempt evidence name collided")
        os.replace(path, destination)


def _publish_attempt(stage: Path, destination: Path) -> None:
    if destination.exists():
        raise RetainedArtifactError(f"attempt destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(stage, destination)


def _load_json(path: Path, label: str) -> dict:
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, TypeError, ValueError) as exc:
        raise RetainedArtifactError(f"{label} is absent or malformed") from exc
    if not isinstance(payload, dict):
        raise RetainedArtifactError(f"{label} is not a JSON object")
    return payload


def _record_resume_state(
    unit_root: Path,
    *,
    plan_sha256: str,
    request_sha256: str,
    status: str,
    detail: Mapping[str, object],
    utcnow: Callable[[], datetime],
) -> dict:
    history_root = unit_root / "resume-history"
    history_root.mkdir(parents=True, exist_ok=True)
    sequence = len(list(history_root.glob("*.json"))) + 1
    state = {
        "schema_version": RESUME_STATE_SCHEMA_VERSION,
        "sequence": sequence,
        "recorded_at_utc": _utc_iso(utcnow),
        "plan_sha256": plan_sha256,
        "request_sha256": request_sha256,
        "status": status,
        "detail": dict(detail),
    }
    state["resume_state_sha256"] = self_hash(state, "resume_state_sha256")
    history_path = history_root / f"{sequence:04d}.json"
    _write_json_private(history_path, state)
    _write_json_atomic(unit_root / "resume-state.json", state)
    return state


def _verify_completed_unit(
    completed: Path,
    *,
    plan_sha256: str,
    request: Mapping[str, object],
) -> dict:
    receipt_path = completed / "receipt.json"
    receipt = _load_json(receipt_path, "completed-unit receipt")
    if receipt.get("schema_version") != UNIT_RECEIPT_SCHEMA_VERSION:
        raise RetainedArtifactError("completed-unit receipt schema differs")
    if receipt.get("receipt_sha256") != self_hash(receipt, "receipt_sha256"):
        raise RetainedArtifactError("completed-unit receipt self-hash differs")
    if (
        receipt.get("plan_sha256") != plan_sha256
        or receipt.get("request_sha256") != request["request_sha256"]
        or receipt.get("unit_id") != request["unit_id"]
    ):
        raise RetainedArtifactError("completed-unit receipt binding differs")
    for record in receipt.get("artifacts") or []:
        path = completed / str(record.get("relative_path"))
        if not path.is_file():
            raise RetainedArtifactError("completed-unit artifact is missing")
        if path.stat().st_size != int(record.get("bytes", -1)):
            raise RetainedArtifactError("completed-unit artifact byte count differs")
        if _sha256_file(path) != record.get("sha256"):
            raise RetainedArtifactError("completed-unit artifact hash differs")
    expected_names = {"raw-response.json", "response-headers.json", "normalized.csv"}
    if {record.get("relative_path") for record in receipt.get("artifacts") or []} != expected_names:
        raise RetainedArtifactError("completed-unit artifact inventory differs")
    return receipt


def _attempt_receipt(
    *,
    plan_sha256: str,
    request: Mapping[str, object],
    attempt: int,
    retrieved_at_utc: str,
    classification: str,
    retryable: bool,
    status_code: int | None,
    error_type: str | None,
    error_message: str | None,
    artifacts: list[dict],
) -> dict:
    receipt = {
        "schema_version": ATTEMPT_RECEIPT_SCHEMA_VERSION,
        "plan_sha256": plan_sha256,
        "request_sha256": request["request_sha256"],
        "parameters_sha256": request["parameters_sha256"],
        "unit_id": request["unit_id"],
        "attempt": attempt,
        "retrieved_at_utc": retrieved_at_utc,
        "retrieval_is_historical_availability_evidence": False,
        "historical_availability": HISTORICAL_AVAILABILITY,
        "classification": classification,
        "retryable": retryable,
        "status_code": status_code,
        "error_type": error_type,
        "error_message": error_message,
        "artifacts": artifacts,
    }
    receipt["attempt_receipt_sha256"] = self_hash(
        receipt, "attempt_receipt_sha256"
    )
    return receipt


def _failed_attempt_history(unit_root: Path) -> list[dict]:
    history = []
    attempts_root = unit_root / "attempts"
    if not attempts_root.exists():
        return history
    for directory in sorted(attempts_root.glob("attempt-*")):
        receipt_path = directory / "attempt-receipt.json"
        if not receipt_path.is_file():
            history.append({"attempt_directory": directory.name, "classification": "INTERRUPTED"})
            continue
        receipt = _load_json(receipt_path, "attempt receipt")
        if receipt.get("attempt_receipt_sha256") != self_hash(
            receipt, "attempt_receipt_sha256"
        ):
            raise RetainedArtifactError("attempt receipt self-hash differs")
        history.append(
            {
                "attempt": receipt.get("attempt"),
                "classification": receipt.get("classification"),
                "retryable": receipt.get("retryable"),
                "status_code": receipt.get("status_code"),
                "retrieved_at_utc": receipt.get("retrieved_at_utc"),
                "receipt_sha256": _sha256_file(receipt_path),
            }
        )
    return history


def collect_unit(
    *,
    plan_sha256: str,
    request: Mapping[str, object],
    output_root: Path,
    transport,
    started_monotonic: float,
    overall_runtime_seconds: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    unit_root = _unit_root(output_root, request)
    unit_root.mkdir(parents=True, exist_ok=True)
    _preserve_interrupted_stages(unit_root)
    completed = unit_root / "completed"
    if completed.exists():
        receipt = _verify_completed_unit(
            completed, plan_sha256=plan_sha256, request=request
        )
        return {"unit_id": request["unit_id"], "status": "SKIPPED_VERIFIED", "receipt": receipt}

    maximum_attempts = 3
    next_attempt = _next_attempt_number(unit_root)
    if next_attempt > maximum_attempts:
        history = _failed_attempt_history(unit_root)
        _record_resume_state(
            unit_root,
            plan_sha256=plan_sha256,
            request_sha256=str(request["request_sha256"]),
            status="PERMANENT_FAILURE",
            detail={"attempt_history": history},
            utcnow=utcnow,
        )
        return {"unit_id": request["unit_id"], "status": "PERMANENT_FAILURE"}

    for attempt in range(next_attempt, maximum_attempts + 1):
        elapsed = monotonic() - started_monotonic
        if elapsed >= overall_runtime_seconds:
            _record_resume_state(
                unit_root,
                plan_sha256=plan_sha256,
                request_sha256=str(request["request_sha256"]),
                status="RUNTIME_BOUND_REACHED",
                detail={"elapsed_seconds": elapsed},
                utcnow=utcnow,
            )
            return {"unit_id": request["unit_id"], "status": "RUNTIME_BOUND_REACHED"}

        stage = unit_root / f".attempt-{uuid.uuid4().hex}.publishing"
        stage.mkdir()
        retrieved_at_utc = _utc_iso(utcnow)
        response = None
        classification = "TRANSPORT_FAILURE"
        retryable = True
        error_type = None
        error_message = None
        status_code = None
        try:
            response = transport.get(
                ENDPOINT,
                params=request["parameters"],
                timeout=(10.0, 120.0),
                maximum_bytes=MAX_RAW_RESPONSE_BYTES,
            )
            if not isinstance(response, TransportResponse):
                raise CollectionError("injected transport returned an unsupported response")
            status_code = int(response.status_code)
            headers = _validated_headers(response.headers)
            if len(response.body) > MAX_RAW_RESPONSE_BYTES:
                raise ResponseIntegrityError("raw response exceeds the 64 MiB bound")
            raw_path = stage / "raw-response.json"
            with raw_path.open("xb") as handle:
                handle.write(response.body)
                handle.flush()
                os.fsync(handle.fileno())
            header_payload = {
                "schema_version": "previous_runs_research_response_headers_v1",
                "plan_sha256": plan_sha256,
                "request_sha256": request["request_sha256"],
                "parameters_sha256": request["parameters_sha256"],
                "unit_id": request["unit_id"],
                "endpoint": ENDPOINT,
                "status_code": status_code,
                "retrieved_at_utc": retrieved_at_utc,
                "retrieval_is_historical_availability_evidence": False,
                "headers": headers,
            }
            header_payload["headers_artifact_sha256"] = self_hash(
                header_payload, "headers_artifact_sha256"
            )
            _write_json_private(stage / "response-headers.json", header_payload)

            if status_code == 200:
                projection = _normalize_response(
                    request, response.body, stage / "normalized.csv"
                )
                artifacts = [
                    _artifact_record(stage / name, relative_to=stage)
                    for name in (
                        "raw-response.json",
                        "response-headers.json",
                        "normalized.csv",
                    )
                ]
                receipt = {
                    "schema_version": UNIT_RECEIPT_SCHEMA_VERSION,
                    "status": (
                        "COMPLETE"
                        if projection["missing_count"] == 0
                        else "COMPLETE_WITH_EXPLICIT_GAPS"
                    ),
                    "plan_sha256": plan_sha256,
                    "request_sha256": request["request_sha256"],
                    "parameters_sha256": request["parameters_sha256"],
                    "unit_id": request["unit_id"],
                    "market": request["market"],
                    "year": request["year"],
                    "segment": request["segment"],
                    "endpoint": ENDPOINT,
                    "source": SOURCE,
                    "issue_time_basis": ISSUE_TIME_BASIS,
                    "historical_availability": HISTORICAL_AVAILABILITY,
                    "caller_supplied_issue_or_availability_time": False,
                    "stitched_source_used": False,
                    "attempt": attempt,
                    "retrieved_at_utc": retrieved_at_utc,
                    "retrieval_is_historical_availability_evidence": False,
                    "raw_response_bytes": len(response.body),
                    "raw_response_sha256": _sha256_bytes(response.body),
                    "projection": projection,
                    "artifacts": artifacts,
                    "retry_history": _failed_attempt_history(unit_root),
                }
                receipt["receipt_sha256"] = self_hash(receipt, "receipt_sha256")
                _write_json_private(stage / "receipt.json", receipt)
                _publish_attempt(stage, completed)
                receipt_file_sha256 = _sha256_file(completed / "receipt.json")
                _record_resume_state(
                    unit_root,
                    plan_sha256=plan_sha256,
                    request_sha256=str(request["request_sha256"]),
                    status="COMPLETE_VERIFIED",
                    detail={
                        "receipt_file_sha256": receipt_file_sha256,
                        "receipt_sha256": receipt["receipt_sha256"],
                        "attempt": attempt,
                    },
                    utcnow=utcnow,
                )
                return {"unit_id": request["unit_id"], "status": receipt["status"], "receipt": receipt}
            if status_code == 429:
                classification = "HTTP_429"
                retryable = True
            elif 500 <= status_code <= 599:
                classification = "HTTP_5XX"
                retryable = True
            else:
                classification = "HTTP_NON_RETRYABLE"
                retryable = False
        except ResponseIntegrityError as exc:
            classification = "RESPONSE_INTEGRITY_FAILURE"
            retryable = False
            error_type = type(exc).__name__
            error_message = str(exc)
        except CollectionError as exc:
            classification = "COLLECTION_CONTRACT_FAILURE"
            retryable = False
            error_type = type(exc).__name__
            error_message = str(exc)
        except TransportFailure as exc:
            classification = "TRANSPORT_FAILURE"
            retryable = True
            error_type = type(exc).__name__
            error_message = str(exc)
        except Exception as exc:  # noqa: BLE001 - unexpected faults fail closed
            if completed.exists() and not stage.exists():
                receipt = _verify_completed_unit(
                    completed, plan_sha256=plan_sha256, request=request
                )
                _record_resume_state(
                    unit_root,
                    plan_sha256=plan_sha256,
                    request_sha256=str(request["request_sha256"]),
                    status="COMPLETE_VERIFIED",
                    detail={
                        "receipt_file_sha256": _sha256_file(
                            completed / "receipt.json"
                        ),
                        "receipt_sha256": receipt["receipt_sha256"],
                        "attempt": attempt,
                        "recovered_after_publish": True,
                    },
                    utcnow=utcnow,
                )
                return {
                    "unit_id": request["unit_id"],
                    "status": receipt["status"],
                    "receipt": receipt,
                }
            classification = "COLLECTION_CONTRACT_FAILURE"
            retryable = False
            error_type = type(exc).__name__
            error_message = str(exc)

        artifacts = [
            _artifact_record(path, relative_to=stage)
            for path in sorted(stage.iterdir())
            if path.is_file()
        ]
        failed_receipt = _attempt_receipt(
            plan_sha256=plan_sha256,
            request=request,
            attempt=attempt,
            retrieved_at_utc=retrieved_at_utc,
            classification=classification,
            retryable=retryable,
            status_code=status_code,
            error_type=error_type,
            error_message=error_message,
            artifacts=artifacts,
        )
        _write_json_private(stage / "attempt-receipt.json", failed_receipt)
        _publish_attempt(stage, unit_root / "attempts" / f"attempt-{attempt:02d}")

        if not retryable or attempt >= maximum_attempts:
            history = _failed_attempt_history(unit_root)
            terminal = (
                "INTEGRITY_FAILURE"
                if classification in {"RESPONSE_INTEGRITY_FAILURE", "COLLECTION_CONTRACT_FAILURE"}
                else "PERMANENT_FAILURE"
            )
            _record_resume_state(
                unit_root,
                plan_sha256=plan_sha256,
                request_sha256=str(request["request_sha256"]),
                status=terminal,
                detail={"attempt_history": history, "classification": classification},
                utcnow=utcnow,
            )
            return {"unit_id": request["unit_id"], "status": terminal}

        fallback = (5.0, 15.0)[attempt - 1]
        try:
            delay = _retry_after_seconds(
                response.headers if response is not None else {},
                fallback=fallback,
                utcnow=utcnow,
            )
        except ResponseIntegrityError as exc:
            _record_resume_state(
                unit_root,
                plan_sha256=plan_sha256,
                request_sha256=str(request["request_sha256"]),
                status="INTEGRITY_FAILURE",
                detail={"classification": "MALFORMED_RETRY_AFTER", "error": str(exc)},
                utcnow=utcnow,
            )
            return {"unit_id": request["unit_id"], "status": "INTEGRITY_FAILURE"}
        remaining = overall_runtime_seconds - (monotonic() - started_monotonic)
        if delay > remaining:
            _record_resume_state(
                unit_root,
                plan_sha256=plan_sha256,
                request_sha256=str(request["request_sha256"]),
                status="RUNTIME_BOUND_REACHED",
                detail={"retry_after_seconds": delay, "remaining_seconds": remaining},
                utcnow=utcnow,
            )
            return {"unit_id": request["unit_id"], "status": "RUNTIME_BOUND_REACHED"}
        sleeper(delay)
    raise AssertionError("bounded attempt loop fell through")


def _request_coverage_denominator(request: Mapping[str, object]) -> list[dict]:
    start = datetime.fromisoformat(str(request["parameters"]["start_date"])).date()
    end = datetime.fromisoformat(str(request["parameters"]["end_date"])).date()
    days_by_month: Counter[int] = Counter()
    cursor = start
    while cursor <= end:
        days_by_month[cursor.month] += 1
        cursor += timedelta(days=1)
    rows = []
    for month in sorted(days_by_month):
        for field in request["fields"]:
            for lead in request["leads"]:
                rows.append(
                    {
                        "month": month,
                        "field": field,
                        "lead_days": int(lead),
                        "requested": days_by_month[month] * 24,
                        "non_null": 0,
                        "missing": days_by_month[month] * 24,
                    }
                )
    return rows


def _rollup_coverage(rows: list[dict], dimensions: tuple[str, ...]) -> list[dict]:
    totals: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0])
    for row in rows:
        key = tuple(row[dimension] for dimension in dimensions)
        totals[key][0] += int(row["requested"])
        totals[key][1] += int(row["non_null"])
        totals[key][2] += int(row["missing"])
    result = []
    for key in sorted(totals, key=lambda item: tuple(str(value) for value in item)):
        record = {dimension: value for dimension, value in zip(dimensions, key)}
        requested, non_null, missing = totals[key]
        record.update(
            {
                "requested": requested,
                "non_null": non_null,
                "missing": missing,
                "coverage_fraction": non_null / requested if requested else None,
            }
        )
        result.append(record)
    return result


def _retained_inventory(
    root: Path,
    *,
    final_stage: Path,
    include_final_names: tuple[str, ...],
) -> list[dict]:
    records = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or final_stage in path.parents:
            continue
        records.append(_artifact_record(path, relative_to=root))
    for name in include_final_names:
        path = final_stage / name
        record = _artifact_record(path, relative_to=final_stage)
        record["relative_path"] = f"final/{name}"
        records.append(record)
    return sorted(records, key=lambda item: item["relative_path"])


def finalize_collection(
    plan: dict,
    output_root: Path,
    *,
    utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    final_root = output_root / "final"
    if final_root.exists():
        return verify_final(output_root)

    coverage_rows = []
    unit_summaries = []
    integrity_errors = []
    completed_count = 0
    complete_without_gaps = 0
    raw_bytes = 0
    normalized_bytes = 0
    normalized_rows = 0
    non_null_rows = 0
    retry_classifications: Counter[str] = Counter()
    for request in plan["requests"]:
        unit_root = _unit_root(output_root, request)
        completed = unit_root / "completed"
        receipt = None
        if completed.exists():
            try:
                receipt = _verify_completed_unit(
                    completed,
                    plan_sha256=plan["plan_sha256"],
                    request=request,
                )
            except RetainedArtifactError as exc:
                integrity_errors.append(f"{request['unit_id']}: {exc}")
        try:
            attempts = _failed_attempt_history(unit_root)
        except RetainedArtifactError as exc:
            integrity_errors.append(f"{request['unit_id']}: {exc}")
            attempts = []
        for attempt in attempts:
            retry_classifications[str(attempt.get("classification"))] += 1
        if receipt is not None:
            completed_count += 1
            if receipt["status"] == "COMPLETE":
                complete_without_gaps += 1
            projection = receipt["projection"]
            raw_bytes += int(receipt["raw_response_bytes"])
            normalized_rows += int(projection["row_count"])
            non_null_rows += int(projection["non_null_count"])
            normalized_bytes += int(
                next(
                    record["bytes"]
                    for record in receipt["artifacts"]
                    if record["relative_path"] == "normalized.csv"
                )
            )
            cells = projection["coverage_cells"]
            unit_status = receipt["status"]
        else:
            cells = _request_coverage_denominator(request)
            state_path = unit_root / "resume-state.json"
            if state_path.exists():
                try:
                    state = _load_json(state_path, "resume state")
                    if state.get("resume_state_sha256") != self_hash(
                        state, "resume_state_sha256"
                    ):
                        raise RetainedArtifactError("resume-state self-hash differs")
                    unit_status = str(state.get("status"))
                    if unit_status == "INTEGRITY_FAILURE":
                        integrity_errors.append(
                            f"{request['unit_id']}: retained response integrity failure"
                        )
                except RetainedArtifactError as exc:
                    integrity_errors.append(f"{request['unit_id']}: {exc}")
                    unit_status = "INVALID_RESUME_STATE"
            else:
                unit_status = "NOT_ATTEMPTED"
        for cell in cells:
            coverage_rows.append(
                {
                    "year": int(request["year"]),
                    "market": request["market"],
                    "segment": request["segment"],
                    "month": int(cell["month"]),
                    "field": cell["field"],
                    "lead_days": int(cell["lead_days"]),
                    "requested": int(cell["requested"]),
                    "non_null": int(cell["non_null"]),
                    "missing": int(cell["missing"]),
                    "unit_status": unit_status,
                }
            )
        unit_summaries.append(
            {
                "unit_id": request["unit_id"],
                "request_sha256": request["request_sha256"],
                "status": unit_status,
                "attempts": attempts,
                "receipt_file_sha256": (
                    _sha256_file(completed / "receipt.json") if receipt is not None else None
                ),
            }
        )

    requested_rows = int(plan["expected_denominator"]["long_rows_before_missingness"])
    if sum(row["requested"] for row in coverage_rows) != requested_rows:
        integrity_errors.append("coverage matrix request denominator drifted")
    if sum(row["non_null"] for row in coverage_rows) != non_null_rows:
        integrity_errors.append("coverage matrix non-null denominator drifted")

    if integrity_errors:
        disposition = "NO_GO_INTEGRITY_FAILURE"
    elif completed_count == 0:
        disposition = "NO_GO_PROVIDER_COVERAGE"
    elif completed_count < len(plan["requests"]) or non_null_rows < requested_rows:
        disposition = "PARTIAL_RESEARCH_CORPUS_WITH_EXPLICIT_GAPS"
    else:
        disposition = "COMPLETE_RESEARCH_CORPUS"

    stage = output_root / f".final-{uuid.uuid4().hex}.publishing"
    stage.mkdir()
    coverage_path = stage / "coverage-matrix.csv"
    coverage_columns = (
        "year",
        "market",
        "segment",
        "month",
        "field",
        "lead_days",
        "requested",
        "non_null",
        "missing",
        "unit_status",
    )
    with coverage_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=coverage_columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(coverage_rows)
        handle.flush()
        os.fsync(handle.fileno())

    manifest = {
        "schema_version": CORPUS_MANIFEST_SCHEMA_VERSION,
        "created_at_utc": _utc_iso(utcnow),
        "disposition": disposition,
        "plan_sha256": plan["plan_sha256"],
        "source_git_tip": plan["source_git"]["tip"],
        "source_git_tree": plan["source_git"]["tree"],
        "endpoint": ENDPOINT,
        "source": SOURCE,
        "issue_time_basis": ISSUE_TIME_BASIS,
        "historical_availability": HISTORICAL_AVAILABILITY,
        "caller_supplied_issue_or_availability_time": False,
        "stitched_source_used": False,
        "counts": {
            "request_units": len(plan["requests"]),
            "completed_units": completed_count,
            "complete_without_gaps_units": complete_without_gaps,
            "requested_rows": requested_rows,
            "normalized_rows": normalized_rows,
            "non_null_rows": non_null_rows,
            "missing_rows": requested_rows - non_null_rows,
            "raw_response_bytes": raw_bytes,
            "normalized_bytes": normalized_bytes,
        },
        "retry_history": dict(sorted(retry_classifications.items())),
        "integrity_errors": integrity_errors,
        "coverage_matrix": _artifact_record(coverage_path, relative_to=stage),
        "coverage_rollups": {
            "year": _rollup_coverage(coverage_rows, ("year",)),
            "market": _rollup_coverage(coverage_rows, ("market",)),
            "field": _rollup_coverage(coverage_rows, ("field",)),
            "lead": _rollup_coverage(coverage_rows, ("lead_days",)),
            "month": _rollup_coverage(coverage_rows, ("month",)),
            "segment": _rollup_coverage(coverage_rows, ("segment",)),
        },
        "units": unit_summaries,
        "next_experiment_preregistered_not_executed": plan[
            "next_experiment_preregistered_not_executed"
        ],
        "outcome_or_model_work_performed": False,
    }
    manifest["corpus_manifest_sha256"] = self_hash(
        manifest, "corpus_manifest_sha256"
    )
    _write_json_private(stage / "corpus-manifest.json", manifest)
    inventory = _retained_inventory(
        output_root,
        final_stage=stage,
        include_final_names=("coverage-matrix.csv", "corpus-manifest.json"),
    )
    verification = {
        "schema_version": FINAL_VERIFICATION_SCHEMA_VERSION,
        "verified_at_utc": _utc_iso(utcnow),
        "disposition": disposition,
        "plan_sha256": plan["plan_sha256"],
        "corpus_manifest_file_sha256": _sha256_file(stage / "corpus-manifest.json"),
        "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
        "retained_inventory": inventory,
        "retained_inventory_sha256": payload_sha256(inventory),
        "raw_projection_plan_receipt_manifest_rehash": "PASS",
    }
    verification["verification_sha256"] = self_hash(
        verification, "verification_sha256"
    )
    _write_json_private(stage / "final-verification.json", verification)
    os.replace(stage, final_root)
    return verify_final(output_root)


def verify_final(output_root: str | Path) -> dict:
    root = Path(output_root)
    final_root = root / "final"
    verification = _load_json(final_root / "final-verification.json", "final verification")
    if verification.get("schema_version") != FINAL_VERIFICATION_SCHEMA_VERSION:
        raise RetainedArtifactError("final verification schema differs")
    if verification.get("verification_sha256") != self_hash(
        verification, "verification_sha256"
    ):
        raise RetainedArtifactError("final verification self-hash differs")
    inventory = verification.get("retained_inventory") or []
    if verification.get("retained_inventory_sha256") != payload_sha256(inventory):
        raise RetainedArtifactError("final inventory self-hash differs")
    for record in inventory:
        path = root / str(record.get("relative_path"))
        if not path.is_file():
            raise RetainedArtifactError(
                f"retained final artifact is missing: {record.get('relative_path')}"
            )
        if path.stat().st_size != int(record.get("bytes", -1)):
            raise RetainedArtifactError(
                f"retained final artifact size differs: {record.get('relative_path')}"
            )
        if _sha256_file(path) != record.get("sha256"):
            raise RetainedArtifactError(
                f"retained final artifact hash differs: {record.get('relative_path')}"
            )
    manifest_path = final_root / "corpus-manifest.json"
    if _sha256_file(manifest_path) != verification.get("corpus_manifest_file_sha256"):
        raise RetainedArtifactError("corpus manifest file hash differs")
    manifest = _load_json(manifest_path, "corpus manifest")
    if manifest.get("corpus_manifest_sha256") != self_hash(
        manifest, "corpus_manifest_sha256"
    ):
        raise RetainedArtifactError("corpus manifest self-hash differs")
    return {
        "disposition": manifest["disposition"],
        "plan_sha256": manifest["plan_sha256"],
        "corpus_manifest_sha256": manifest["corpus_manifest_sha256"],
        "corpus_manifest_file_sha256": verification["corpus_manifest_file_sha256"],
        "final_verification_file_sha256": _sha256_file(
            final_root / "final-verification.json"
        ),
        "counts": manifest["counts"],
        "retry_history": manifest["retry_history"],
        "coverage_rollups": manifest["coverage_rollups"],
        "integrity_errors": manifest["integrity_errors"],
    }


def run_collection(
    plan_path: str | Path,
    *,
    transport=None,
    output_root: str | Path | None = None,
    require_wrapper: bool = True,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    utcnow: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict:
    if require_wrapper and os.environ.get(WRAPPER_ENVIRONMENT) != "1":
        raise CollectionError("provider collection requires the dedicated bounded wrapper")
    plan, plan_bytes = load_bound_plan(plan_path)
    root = initialize_output_root(plan, plan_bytes, root=output_root)
    if (root / "final").exists():
        return verify_final(root)
    started = monotonic()
    runtime = float(plan["execution_contract"]["overall_runtime_seconds"])
    transport = transport or RequestsTransport()
    for request in plan["requests"]:
        result = collect_unit(
            plan_sha256=plan["plan_sha256"],
            request=request,
            output_root=root,
            transport=transport,
            started_monotonic=started,
            overall_runtime_seconds=runtime,
            monotonic=monotonic,
            sleeper=sleeper,
            utcnow=utcnow,
        )
        if result["status"] == "INTEGRITY_FAILURE":
            break
        if result["status"] == "RUNTIME_BOUND_REACHED":
            return {
                "schema_version": RUN_SUMMARY_SCHEMA_VERSION,
                "status": "RESUMABLE_RUNTIME_BOUND_REACHED",
                "plan_sha256": plan["plan_sha256"],
                "output_root": str(root),
                "finalized": False,
            }
        if monotonic() - started >= runtime:
            return {
                "schema_version": RUN_SUMMARY_SCHEMA_VERSION,
                "status": "RESUMABLE_RUNTIME_BOUND_REACHED",
                "plan_sha256": plan["plan_sha256"],
                "output_root": str(root),
                "finalized": False,
            }
    return finalize_collection(plan, root, utcnow=utcnow)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--out", required=True)
    plan.add_argument("--planned-at-utc", required=True)
    collect = subparsers.add_parser(
        "collect",
        help="Run the immutable plan through the dedicated bounded wrapper.",
    )
    collect.add_argument("--plan", required=True)
    verify = subparsers.add_parser(
        "verify-final",
        help="Re-hash the retained terminal corpus without writing it.",
    )
    verify.add_argument("--root", default=OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "plan":
        plan = build_plan(planned_at_utc=args.planned_at_utc)
        destination = write_plan(args.out, plan)
        print(
            json.dumps(
                {
                    "path": str(destination),
                    "plan_sha256": plan["plan_sha256"],
                    "request_units": len(plan["requests"]),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "collect":
        result = run_collection(args.plan)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if result.get("status") == "RESUMABLE_RUNTIME_BOUND_REACHED":
            return 3
        return 2 if result["disposition"] == "NO_GO_INTEGRITY_FAILURE" else 0
    if args.command == "verify-final":
        print(
            json.dumps(
                verify_final(args.root),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
