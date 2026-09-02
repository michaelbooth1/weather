"""Outcome-blind planning for the bounded multi-year Previous Runs corpus.

The initial version of this module deliberately contains no HTTP transport.
It exists so the complete request denominator can be generated, reviewed, and
committed before the first provider request.  Collection support is added only
in a descendant commit after that immutable plan exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

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
    if (plan.get("provider_contract") or {}).get("endpoint") != ENDPOINT:
        raise PlanError("endpoint differs from operator authorization")
    if (plan.get("scope") or {}).get("fields") != list(FIELDS):
        raise PlanError("field contract differs from operator authorization")
    if (plan.get("scope") or {}).get("leads") != list(LEADS):
        raise PlanError("lead contract differs from operator authorization")
    requests = plan.get("requests") or []
    expected_count = len(BUILTIN_SPECS) * len(YEARS) * len(SEGMENTS)
    if len(requests) != expected_count:
        raise PlanError("request denominator is incomplete")
    seen = set()
    for request in requests:
        if request.get("request_sha256") != self_hash(request, "request_sha256"):
            raise PlanError("request hash mismatch")
        if request.get("parameters_sha256") != payload_sha256(request["parameters"]):
            raise PlanError("parameter hash mismatch")
        if request.get("endpoint") != ENDPOINT:
            raise PlanError("request endpoint drifted")
        if request.get("fields") != list(FIELDS) or request.get("leads") != list(LEADS):
            raise PlanError("request field or lead matrix drifted")
        unit_id = request.get("unit_id")
        if not unit_id or unit_id in seen:
            raise PlanError("duplicate or missing request unit")
        seen.add(unit_id)
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--out", required=True)
    plan.add_argument("--planned-at-utc", required=True)
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
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
