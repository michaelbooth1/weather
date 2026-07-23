"""Scratch-only issue-time HRRR AOTK/smoke backfill for Tmax research.

The design is outcome-blind and frozen before GRIB acquisition or scoring.  It
uses the target-minus-one UTC-calendar-day 12Z extended HRRR cycle and steps
f18, f24, f30, f36, and f42.  Their union supplies exactly four six-hourly
samples on each built-in market's local target day.

``MASSDEN`` is modeled smoke mass density, not PM2.5.  NOAA changed its numeric
output at the 2021-12-21 12Z cycle: earlier values are already micrograms per
cubic metre despite the GRIB definition, while later values are kilograms per
cubic metre and are multiplied by 1e9.  The predeclared model features are
native dimensionless AOTK mean/max and mean/max of ``log1p`` normalized smoke
mass density.  No serving schema or collector is changed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests

from weather.io import (
    copy_file_atomic,
    write_csv_rows_atomic,
    write_json_atomic,
    write_text_atomic,
)
from weather.market.market_registry import BUILTIN_SPECS, MarketSpec
from weather.reporting.formatting import markdown_table
from weather.reporting.research.cfsv2_pressure_research import (
    _aware_utc,
    _grib_reference_time,
    _grib_valid_time,
    fetch_or_load,
    load_eccodes,
    sha256_bytes,
    sha256_file,
    source_paths,
    utc_iso,
)
from weather.reporting.research.offline_tmax_predictor_evaluation import (
    DEFAULT_BOOTSTRAP_REPLICATES,
    DEFAULT_BOOTSTRAP_SEED,
    DEFAULT_FOLDS,
    DEFAULT_HOLDOUT_FRACTION,
    DEFAULT_RIDGE_ALPHA,
    Thresholds,
    chronological_plan,
    load_market_rows,
    resolve_paths_outside_read_only_root,
)
from weather.schema_registry import schema_version
from weather.sources.forecast_history import (
    RICH_FORECAST_COLUMNS,
    forecast_payload_hash,
)
from weather.units import to_float


SCHEMA_VERSION = schema_version("hrrr_smoke_research")
DESIGN_SCHEMA_VERSION = schema_version("hrrr_smoke_design_contract")
BASE_URL = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
UNIT_NOTICE_URL = (
    "https://www.weather.gov/media/notification/pdf2/"
    "scn21-86rap_and_hrr_smoke_units_change_aab.pdf"
)
CYCLE_HOUR_UTC = 12
ISSUE_LEAD_CALENDAR_DAYS = 1
AVAILABILITY_BUFFER_HOURS = 2
FORECAST_STEPS = (18, 24, 30, 36, 42)
MASSDEN_UNIT_BOUNDARY = datetime(2021, 12, 21, 12, tzinfo=timezone.utc)
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_ATTEMPTS = 4
DEFAULT_INDEX_WORKERS = 16
DEFAULT_RANGE_WORKERS = 8
DEFAULT_PAUSE_SECONDS = 0.0
GRID_TYPE = "lambert"
GRID_X_POINTS = 1799
GRID_Y_POINTS = 1059
GRID_SPACING_METERS = 3000.0
MAX_NEAREST_DISTANCE_KM = 5.0
EXPECTED_LOCAL_SAMPLES = 4
HRRR_AOD_COLUMN = "hrrr_aerosol_optical_depth"
HRRR_SMOKE_COLUMN = "hrrr_smoke_mass_density_ug_m3"
HRRR_FORECAST_COLUMNS = RICH_FORECAST_COLUMNS + [
    HRRR_AOD_COLUMN,
    HRRR_SMOKE_COLUMN,
]
INDEX_PATTERN = re.compile(
    r"^(?P<message>\d+):(?P<offset>\d+):d=(?P<issue>\d{10}):(?P<descriptor>.*)$"
)


@dataclass(frozen=True)
class HrrrField:
    name: str
    descriptor_level: str
    parameter_number: int
    type_of_level: str
    level: int
    output_key: str


@dataclass(frozen=True)
class IndexMessage:
    message: int
    offset: int
    issue_text: str
    descriptor: str


@dataclass(frozen=True)
class SelectedMessage:
    field: str
    message: int
    offset: int
    end_offset: int
    issue_text: str
    step_hours: int
    descriptor: str


FIELDS = (
    HrrrField(
        name="MASSDEN",
        descriptor_level="8 m above ground",
        parameter_number=0,
        type_of_level="heightAboveGround",
        level=8,
        output_key=HRRR_SMOKE_COLUMN,
    ),
    HrrrField(
        name="AOTK",
        descriptor_level="entire atmosphere (considered as a single layer)",
        parameter_number=102,
        type_of_level="atmosphereSingleLayer",
        level=0,
        output_key=HRRR_AOD_COLUMN,
    ),
)

_HRRR_DESIGN_FROZEN_FIELDS = (
    "schema_version",
    "research_only",
    "selection_basis",
    "issue_time_contract",
    "field_contract",
    "transform_contract",
    "unit_contract",
    "grid_coverage_contract",
    "split_contract",
    "acceptance_contract",
    "target_dates",
    "complete_target_dates",
    "availability_records",
)


def _canonical_design_sha256(payload: Mapping[str, Any]) -> str:
    missing = [
        field for field in _HRRR_DESIGN_FROZEN_FIELDS if field not in payload
    ]
    if missing:
        raise ValueError(f"HRRR design is missing frozen fields: {missing}")
    frozen = {field: payload[field] for field in _HRRR_DESIGN_FROZEN_FIELDS}
    canonical = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(canonical)


def _validated_design_dates(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of ISO date strings")
    if value != sorted(set(value)):
        raise ValueError(f"{label} must be sorted and unique")
    for item in value:
        date.fromisoformat(item)
    return list(value)


def validate_design_contract(payload: Mapping[str, Any]) -> None:
    """Verify the frozen HRRR design before any resume reads outcomes/GRIBs."""

    if payload.get("schema_version") != DESIGN_SCHEMA_VERSION:
        raise ValueError("existing HRRR design contract has the wrong schema")
    if payload.get("contract_sha256") != _canonical_design_sha256(payload):
        raise ValueError("existing HRRR design canonical hash mismatch")
    if payload.get("frozen_before_grib_decode") is not True:
        raise ValueError("existing HRRR design was not frozen before GRIB decode")
    if payload.get("frozen_before_outcome_evaluation") is not True:
        raise ValueError("existing HRRR design was not frozen before outcomes")

    targets = _validated_design_dates(payload.get("target_dates"), label="HRRR target_dates")
    complete = _validated_design_dates(
        payload.get("complete_target_dates"), label="HRRR complete_target_dates"
    )
    if not set(complete).issubset(targets):
        raise ValueError("HRRR complete dates are not a subset of target dates")
    for field, expected in (
        ("target_date_count", len(targets)),
        ("complete_date_count", len(complete)),
        ("missing_date_count", len(targets) - len(complete)),
    ):
        if payload.get(field) != expected:
            raise ValueError(f"HRRR {field} mismatch")

    issue_contract = payload.get("issue_time_contract") or {}
    if issue_contract.get("forecast_steps_hours") != list(FORECAST_STEPS):
        raise ValueError("HRRR forecast-step contract changed")
    if [item.get("name") for item in payload.get("field_contract") or []] != [
        field.name for field in FIELDS
    ]:
        raise ValueError("HRRR field contract changed")
    records = list(payload.get("availability_records") or [])
    actual_keys = [(item.get("target_date"), item.get("step_hours")) for item in records]
    expected_keys = [(target, step) for target in targets for step in FORECAST_STEPS]
    if actual_keys != expected_keys:
        raise ValueError("HRRR availability records are incomplete or reordered")
    by_key = {(item["target_date"], int(item["step_hours"])): item for item in records}
    derived_complete = [
        target
        for target in targets
        if all(by_key[(target, step)].get("complete") is True for step in FORECAST_STEPS)
    ]
    if complete != derived_complete:
        raise ValueError("HRRR complete dates do not match availability records")
    if payload.get("split_contract") != _split_contract(complete):
        raise ValueError("HRRR split contract does not match complete dates")

    index_requests = list(payload.get("index_requests") or [])
    if payload.get("index_request_count") != len(index_requests):
        raise ValueError("HRRR index-request count mismatch")
    by_url = {item.get("url"): item for item in index_requests}
    if len(by_url) != len(index_requests):
        raise ValueError("HRRR index requests contain duplicate URLs")
    for record in records:
        expected_sha = record.get("index_sha256")
        if expected_sha is None:
            continue
        request = by_url.get(record.get("index_url"))
        if request is None or request.get("sha256") != expected_sha:
            raise ValueError("HRRR index request lineage differs from availability record")


def feature_issue_time(target_date: date) -> datetime:
    prior = target_date - timedelta(days=ISSUE_LEAD_CALENDAR_DAYS)
    return datetime.combine(
        prior,
        datetime_time(hour=CYCLE_HOUR_UTC),
        tzinfo=timezone.utc,
    )


def buffered_available_time(issue_time: datetime) -> datetime:
    return _aware_utc(issue_time, label="issue_time") + timedelta(
        hours=AVAILABILITY_BUFFER_HOURS
    )


def _parse_local_cutoff(value: str) -> datetime_time:
    try:
        parsed = datetime_time.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid local cutoff {value!r}") from exc
    if parsed.tzinfo is not None:
        raise ValueError("local cutoff must not contain a timezone offset")
    return parsed


def assert_cutoff_safe(
    target_date: date,
    issue_time: datetime,
    specs: Sequence[MarketSpec] = BUILTIN_SPECS,
    *,
    cutoff_local: str = "00:00",
) -> None:
    available = buffered_available_time(issue_time)
    cutoff_time = _parse_local_cutoff(cutoff_local)
    unsafe = []
    for spec in specs:
        cutoff = datetime.combine(target_date, cutoff_time, tzinfo=spec.tz)
        if available >= cutoff.astimezone(timezone.utc):
            unsafe.append(spec.id)
    if unsafe:
        raise ValueError(
            "buffered HRRR availability is not strictly before local cutoff: "
            + ", ".join(sorted(unsafe))
        )


def archive_urls(issue_time: datetime, step_hours: int) -> tuple[str, str]:
    issue = _aware_utc(issue_time, label="issue_time")
    step = int(step_hours)
    if step not in FORECAST_STEPS:
        raise ValueError(f"step is outside the frozen HRRR design: {step}")
    stem = f"hrrr.t{issue:%H}z.wrfsfcf{step:02d}.grib2"
    root = f"{BASE_URL}/hrrr.{issue:%Y%m%d}/conus"
    return f"{root}/{stem}", f"{root}/{stem}.idx"


def parse_index(
    text: str,
    *,
    expected_issue_time: datetime | None = None,
) -> list[IndexMessage]:
    messages = []
    for line in text.splitlines():
        match = INDEX_PATTERN.match(line.strip())
        if match is None:
            continue
        messages.append(
            IndexMessage(
                message=int(match.group("message")),
                offset=int(match.group("offset")),
                issue_text=match.group("issue"),
                descriptor=match.group("descriptor"),
            )
        )
    if not messages:
        raise ValueError("HRRR index contained no messages")
    if [item.message for item in messages] != list(range(1, len(messages) + 1)):
        raise ValueError("HRRR index message numbers are not contiguous from one")
    if any(right.offset <= left.offset for left, right in zip(messages, messages[1:])):
        raise ValueError("HRRR index offsets are not strictly increasing")
    issues = {item.issue_text for item in messages}
    if len(issues) != 1:
        raise ValueError("HRRR index contains mixed nominal cycles")
    try:
        datetime.strptime(messages[0].issue_text, "%Y%m%d%H")
    except ValueError as exc:
        raise ValueError("HRRR index contains an invalid nominal cycle") from exc
    if expected_issue_time is not None:
        expected = _aware_utc(
            expected_issue_time, label="expected_issue_time"
        ).strftime("%Y%m%d%H")
        if messages[0].issue_text != expected:
            raise ValueError(
                "HRRR index cycle does not match request: "
                f"expected={expected}, got={messages[0].issue_text}"
            )
    return messages


def select_messages(
    messages: Sequence[IndexMessage],
    *,
    step_hours: int,
) -> dict[str, SelectedMessage]:
    selected = {}
    for field in FIELDS:
        expected = f"{field.name}:{field.descriptor_level}:{int(step_hours)} hour fcst:"
        matches = [
            (index, item)
            for index, item in enumerate(messages)
            if item.descriptor == expected
        ]
        if len(matches) != 1:
            raise ValueError(
                f"HRRR index expected one exact {field.name} descriptor; found={len(matches)}"
            )
        index, item = matches[0]
        if index + 1 >= len(messages):
            raise ValueError(f"HRRR {field.name} is final index message; range end unknown")
        end = messages[index + 1].offset - 1
        if end < item.offset:
            raise ValueError(f"HRRR {field.name} has invalid byte span")
        selected[field.name] = SelectedMessage(
            field=field.name,
            message=item.message,
            offset=item.offset,
            end_offset=end,
            issue_text=item.issue_text,
            step_hours=int(step_hours),
            descriptor=item.descriptor,
        )
    return selected


def _selected_baselines(
    source_data_root: Path,
    specs: Sequence[MarketSpec],
    cutoff_local: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[str], list[dict[str, Any]]]:
    selected_by_market = {}
    audits = []
    target_dates = set()
    for spec in specs:
        rows, market_audit, _ = load_market_rows(
            data_root=source_data_root,
            spec=spec,
            family="hrrr_smoke",
            cutoff_local=cutoff_local,
        )
        selected_by_market[spec.id] = rows
        for provenance in market_audit.get("provenance", {}).values():
            provenance["sha256"] = sha256_file(provenance["path"])
        audits.append(market_audit)
        target_dates.update(str(row["target_date"]) for row in rows)
    return selected_by_market, sorted(target_dates), audits


def _audit_index(
    *,
    target_text: str,
    step_hours: int,
    raw_root: Path,
    timeout_seconds: float,
    attempts: int,
    request_get: Callable[..., Any],
    sleep_fn: Callable[[float], None],
) -> dict[str, Any]:
    target = date.fromisoformat(target_text)
    issue = feature_issue_time(target)
    grib_url, index_url = archive_urls(issue, step_hours)
    issue_text = issue.strftime("%Y%m%d%H")
    path = raw_root / issue_text / f"f{step_hours:02d}.idx"
    try:
        content, request, fetched = fetch_or_load(
            path=path,
            url=index_url,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            request_get=request_get,
            sleep_fn=sleep_fn,
        )
        messages = parse_index(
            content.decode("utf-8"), expected_issue_time=issue
        )
        selected = select_messages(messages, step_hours=step_hours)
        return {
            "target_date": target_text,
            "issue_time_utc": issue.isoformat(),
            "step_hours": int(step_hours),
            "grib_url": grib_url,
            "index_url": index_url,
            "index_request": request,
            "selected": {
                name: {
                    "field": item.field,
                    "message": item.message,
                    "offset": item.offset,
                    "end_offset": item.end_offset,
                    "issue_text": item.issue_text,
                    "step_hours": item.step_hours,
                    "descriptor": item.descriptor,
                }
                for name, item in selected.items()
            },
            "complete": True,
            "fetched": fetched,
            "error_type": None,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - exact availability blocker is evidence
        return {
            "target_date": target_text,
            "issue_time_utc": issue.isoformat(),
            "step_hours": int(step_hours),
            "grib_url": grib_url,
            "index_url": index_url,
            "index_request": None,
            "selected": {},
            "complete": False,
            "fetched": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _split_contract(complete_dates: Sequence[str]) -> dict[str, Any]:
    plan = chronological_plan(
        complete_dates,
        holdout_fraction=DEFAULT_HOLDOUT_FRACTION,
        folds=DEFAULT_FOLDS,
        min_train_dates=Thresholds.min_train_dates,
        min_holdout_dates=Thresholds.min_holdout_dates,
    )
    return {
        "policy": "four expanding-window development folds plus terminal 20% holdout",
        "holdout_fraction": DEFAULT_HOLDOUT_FRACTION,
        "folds": DEFAULT_FOLDS,
        "ridge_alpha": DEFAULT_RIDGE_ALPHA,
        "bootstrap_replicates": DEFAULT_BOOTSTRAP_REPLICATES,
        "bootstrap_seed": DEFAULT_BOOTSTRAP_SEED,
        "thresholds": {
            "min_markets": Thresholds.min_markets,
            "min_train_dates": Thresholds.min_train_dates,
            "min_validation_dates": Thresholds.min_validation_dates,
            "min_holdout_dates": Thresholds.min_holdout_dates,
            "min_train_rows": Thresholds.min_train_rows,
            "min_validation_rows": Thresholds.min_validation_rows,
            "min_holdout_rows": Thresholds.min_holdout_rows,
        },
        "date_plan": plan,
    }


def freeze_design_contract(
    *,
    target_dates: Sequence[str],
    output_path: str | Path,
    raw_root: str | Path,
    specs: Sequence[MarketSpec] = BUILTIN_SPECS,
    cutoff_local: str = "00:00",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    workers: int = DEFAULT_INDEX_WORKERS,
    request_get: Callable[..., Any] = requests.get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch exact indices and freeze availability, design, split, and gate."""

    tasks = [
        (target_text, step)
        for target_text in sorted(set(target_dates))
        for step in FORECAST_STEPS
    ]
    records = []
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        futures = {
            executor.submit(
                _audit_index,
                target_text=target_text,
                step_hours=step,
                raw_root=Path(raw_root),
                timeout_seconds=timeout_seconds,
                attempts=attempts,
                request_get=request_get,
                sleep_fn=sleep_fn,
            ): (target_text, step)
            for target_text, step in tasks
        }
        for future in as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda item: (item["target_date"], item["step_hours"]))
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_target[record["target_date"]].append(record)
    complete_dates = [
        target_text
        for target_text in sorted(by_target)
        if [item["step_hours"] for item in by_target[target_text]]
        == list(FORECAST_STEPS)
        and all(item["complete"] for item in by_target[target_text])
    ]
    year_targets = Counter(item[:4] for item in target_dates)
    year_complete = Counter(item[:4] for item in complete_dates)
    coverage_by_year = [
        {
            "year": int(year),
            "target_dates": year_targets[year],
            "complete_dates": year_complete[year],
            "missing_dates": year_targets[year] - year_complete[year],
        }
        for year in sorted(year_targets)
    ]
    normalized_records = []
    for record in records:
        normalized_records.append(
            {
                "target_date": record["target_date"],
                "issue_time_utc": record["issue_time_utc"],
                "step_hours": record["step_hours"],
                "grib_url": record["grib_url"],
                "index_url": record["index_url"],
                "index_sha256": (
                    record["index_request"]["sha256"]
                    if record["index_request"] is not None
                    else None
                ),
                "selected": record["selected"],
                "complete": record["complete"],
                "error_type": record["error_type"],
                "error": record["error"],
            }
        )
    issue_boundary_counts = Counter(
        "pre_boundary_numeric_ug_m3_identity"
        if feature_issue_time(date.fromisoformat(item)) < MASSDEN_UNIT_BOUNDARY
        else "post_boundary_numeric_kg_m3_times_1e9"
        for item in complete_dates
    )
    frozen = {
        "schema_version": DESIGN_SCHEMA_VERSION,
        "research_only": True,
        "selection_basis": (
            "exact HRRR index field/step availability under one cycle rule; no "
            "settlement values, residuals, model fits, or scores used"
        ),
        "issue_time_contract": {
            "rule": "target minus one UTC calendar day at 12Z",
            "availability_buffer_hours": AVAILABILITY_BUFFER_HOURS,
            "cutoff_local": cutoff_local,
            "forecast_steps_hours": list(FORECAST_STEPS),
            "valid_time_rule": "four six-hour samples on each market local target date",
        },
        "field_contract": [
            {
                "name": field.name,
                "descriptor_level": field.descriptor_level,
                "discipline": 0,
                "parameter_category": 20,
                "parameter_number": field.parameter_number,
                "type_of_level": field.type_of_level,
                "level": field.level,
            }
            for field in FIELDS
        ],
        "transform_contract": {
            "aotk": "mean and max on native nonnegative dimensionless scale",
            "massden": (
                "normalize to nonnegative micrograms per cubic metre, then compute "
                "mean and max of log1p(sample)"
            ),
            "chosen_before_outcome_evaluation": True,
        },
        "unit_contract": {
            "notice_url": UNIT_NOTICE_URL,
            "boundary_cycle_utc": MASSDEN_UNIT_BOUNDARY.isoformat(),
            "before_boundary": "numeric output already ug/m^3; identity",
            "at_or_after_boundary": "numeric output kg/m^3; multiply by 1e9",
            "eccodes_local_parameter_units_label": "unknown",
            "boundary_era_complete_date_counts": dict(sorted(issue_boundary_counts.items())),
        },
        "grid_coverage_contract": {
            "grid_type": GRID_TYPE,
            "nx": GRID_X_POINTS,
            "ny": GRID_Y_POINTS,
            "dx_m": GRID_SPACING_METERS,
            "dy_m": GRID_SPACING_METERS,
            "max_nearest_distance_km": MAX_NEAREST_DISTANCE_KM,
            "expected_local_samples_per_market_date": EXPECTED_LOCAL_SAMPLES,
            "markets": [
                {"market_id": spec.id, "lat": spec.lat, "lon": spec.lon}
                for spec in specs
            ],
        },
        "split_contract": _split_contract(complete_dates),
        "acceptance_contract": {
            "primary_metric": "paired holdout MAE delta C (variant minus baseline)",
            "uncertainty": "fleet-target-date clustered 95% bootstrap interval",
            "pass_rule": "point estimate below zero and entire 95% interval below zero",
            "otherwise": "STOP; no serving, collector, promotion, or live-trading change",
            "single_opening": True,
        },
        "target_dates": sorted(set(target_dates)),
        "complete_target_dates": complete_dates,
        "availability_records": normalized_records,
    }
    canonical = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    payload = {
        **frozen,
        "generated_at_utc": utc_iso(),
        "contract_sha256": sha256_bytes(canonical),
        "target_date_count": len(set(target_dates)),
        "complete_date_count": len(complete_dates),
        "missing_date_count": len(set(target_dates)) - len(complete_dates),
        "coverage_by_year": coverage_by_year,
        "index_request_count": sum(item["index_request"] is not None for item in records),
        "index_requests": [
            item["index_request"] for item in records if item["index_request"] is not None
        ],
        "frozen_before_grib_decode": True,
        "frozen_before_outcome_evaluation": True,
    }
    validate_design_contract(payload)
    write_json_atomic(output_path, payload)
    return payload


def normalize_massden_ug_m3(raw_value: float, issue_time: datetime) -> tuple[float, str]:
    raw = float(raw_value)
    if not math.isfinite(raw) or raw < 0.0:
        raise ValueError(f"HRRR MASSDEN is not finite and nonnegative: {raw}")
    issue = _aware_utc(issue_time, label="issue_time")
    if issue < MASSDEN_UNIT_BOUNDARY:
        normalized = raw
        rule = "pre_boundary_numeric_ug_m3_identity"
    else:
        normalized = raw * 1_000_000_000.0
        rule = "post_boundary_numeric_kg_m3_times_1e9"
    if not math.isfinite(normalized) or normalized > 1_000_000.0:
        raise ValueError(
            f"implausible normalized HRRR smoke mass density: {normalized} ug/m^3"
        )
    return normalized, rule


def decode_message(
    path: str | Path,
    *,
    field: HrrrField,
    target_date: date,
    specs: Sequence[MarketSpec],
    eccodes,
    issue_time: datetime,
    step_hours: int,
    station_grid_lookup: Mapping[str, Mapping[str, float | int]] | None = None,
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    """Decode one exact HRRR message under parameter/time/grid/unit contracts."""

    issue = _aware_utc(issue_time, label="issue_time")
    expected_valid = issue + timedelta(hours=int(step_hours))
    output: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    with Path(path).open("rb") as source:
        handle = eccodes.codes_grib_new_from_file(source)
        if handle is None:
            raise ValueError("bounded HRRR range contained no GRIB message")
        try:
            parameter = {
                "discipline": int(eccodes.codes_get(handle, "discipline")),
                "parameter_category": int(
                    eccodes.codes_get(handle, "parameterCategory")
                ),
                "parameter_number": int(eccodes.codes_get(handle, "parameterNumber")),
                "short_name": str(eccodes.codes_get(handle, "shortName")),
                "name": str(eccodes.codes_get(handle, "name")),
                "units": str(eccodes.codes_get(handle, "units")),
            }
            expected_parameter = {
                "discipline": 0,
                "parameter_category": 20,
                "parameter_number": field.parameter_number,
                "short_name": "unknown",
                "name": "unknown",
                "units": "unknown",
            }
            if parameter != expected_parameter:
                raise ValueError(
                    f"unexpected HRRR {field.name} parameter/unit contract: {parameter}"
                )
            if (
                str(eccodes.codes_get(handle, "typeOfLevel")) != field.type_of_level
                or int(eccodes.codes_get(handle, "level")) != field.level
            ):
                raise ValueError(f"unexpected HRRR {field.name} level contract")
            if str(eccodes.codes_get(handle, "stepType")) != "instant":
                raise ValueError(f"unexpected non-instantaneous HRRR {field.name}")
            if (
                int(eccodes.codes_get(handle, "typeOfGeneratingProcess")) != 2
                or int(eccodes.codes_get(handle, "generatingProcessIdentifier")) != 83
            ):
                raise ValueError(f"unexpected HRRR {field.name} generating process")
            grid = {
                "grid_type": str(eccodes.codes_get(handle, "gridType")),
                "nx": int(eccodes.codes_get(handle, "Nx")),
                "ny": int(eccodes.codes_get(handle, "Ny")),
                "dx_m": float(eccodes.codes_get(handle, "DxInMetres")),
                "dy_m": float(eccodes.codes_get(handle, "DyInMetres")),
            }
            if grid != {
                "grid_type": GRID_TYPE,
                "nx": GRID_X_POINTS,
                "ny": GRID_Y_POINTS,
                "dx_m": GRID_SPACING_METERS,
                "dy_m": GRID_SPACING_METERS,
            }:
                raise ValueError(f"unexpected HRRR grid contract: {grid}")
            reference = _grib_reference_time(eccodes, handle)
            valid = _grib_valid_time(eccodes, handle)
            actual_step = int(eccodes.codes_get(handle, "forecastTime"))
            if reference != issue:
                raise ValueError("HRRR GRIB cycle does not match request")
            if actual_step != int(step_hours):
                raise ValueError("HRRR GRIB forecast step does not match request")
            if valid != expected_valid:
                raise ValueError("HRRR GRIB valid time does not match cycle plus step")
            max_distance = 0.0
            normalization_rules = set()
            raw_values = []
            normalized_values = []
            computed_grid_lookup = station_grid_lookup is None
            if station_grid_lookup is None:
                nearest_points = eccodes.codes_grib_find_nearest_multiple(
                    handle,
                    False,
                    [float(spec.lat) for spec in specs],
                    [float(spec.lon) for spec in specs],
                )
                if len(nearest_points) != len(specs):
                    raise ValueError(
                        "HRRR nearest-grid lookup returned the wrong point count"
                    )
                station_grid_lookup = {
                    spec.id: {
                        "index": int(nearest["index"]),
                        "grid_lat": float(nearest["lat"]),
                        "grid_lon": float(nearest["lon"]),
                        "distance_km": float(nearest["distance"]),
                    }
                    for spec, nearest in zip(specs, nearest_points)
                }
            if set(station_grid_lookup) != {spec.id for spec in specs}:
                raise ValueError("HRRR station-grid lookup does not match market set")
            eligible_specs = [
                spec
                for spec in specs
                if valid.astimezone(spec.tz).date() == target_date
            ]
            selected_values = eccodes.codes_get_elements(
                handle,
                "values",
                [int(station_grid_lookup[spec.id]["index"]) for spec in eligible_specs],
            )
            if len(selected_values) != len(eligible_specs):
                raise ValueError("HRRR indexed value lookup returned the wrong point count")
            for spec, selected_value in zip(eligible_specs, selected_values):
                valid_local = valid.astimezone(spec.tz)
                lookup = station_grid_lookup[spec.id]
                raw = float(selected_value)
                distance = float(lookup["distance_km"])
                grid_lat = float(lookup["grid_lat"])
                grid_lon = float(lookup["grid_lon"])
                if (
                    not math.isfinite(distance)
                    or distance < 0.0
                    or distance > MAX_NEAREST_DISTANCE_KM
                    or not math.isfinite(grid_lat)
                    or not math.isfinite(grid_lon)
                ):
                    raise ValueError(
                        f"HRRR nearest-grid contract failed for {spec.id}: {distance} km"
                    )
                if field.name == "AOTK":
                    if not math.isfinite(raw) or not 0.0 <= raw <= 50.0:
                        raise ValueError(f"implausible HRRR AOTK: {raw}")
                    normalized = raw
                    rule = "native_nonnegative_dimensionless"
                else:
                    normalized, rule = normalize_massden_ug_m3(raw, issue)
                max_distance = max(max_distance, distance)
                normalization_rules.add(rule)
                raw_values.append(raw)
                normalized_values.append(normalized)
                output[spec.id][valid_local.isoformat()] = {
                    field.output_key: normalized,
                    "grid_lat": grid_lat,
                    "grid_lon": grid_lon,
                    "distance_km": distance,
                }
        finally:
            eccodes.codes_release(handle)
        extra = eccodes.codes_grib_new_from_file(source)
        if extra is not None:
            try:
                raise ValueError("bounded HRRR range contained more than one GRIB message")
            finally:
                eccodes.codes_release(extra)
    return {key: dict(value) for key, value in output.items()}, {
        "field": field.name,
        "decoded_messages": 1,
        "parameter": parameter,
        "level": {"type": field.type_of_level, "level": field.level},
        "grid": grid,
        "reference_time_utc": reference.isoformat(),
        "forecast_step_hours": actual_step,
        "valid_time_utc": valid.isoformat(),
        "max_nearest_grid_distance_km": max_distance,
        "market_value_count": sum(len(item) for item in output.values()),
        "normalization_rules": sorted(normalization_rules),
        "raw_value_min": min(raw_values) if raw_values else None,
        "raw_value_max": max(raw_values) if raw_values else None,
        "normalized_value_min": min(normalized_values) if normalized_values else None,
        "normalized_value_max": max(normalized_values) if normalized_values else None,
        "station_grid_lookup": station_grid_lookup if computed_grid_lookup else None,
        "station_grid_lookup_mode": "computed" if computed_grid_lookup else "reused",
    }


def _merge_field_values(
    decoded: Mapping[str, Mapping[str, Mapping[str, Mapping[str, float]]]],
    specs: Sequence[MarketSpec],
) -> dict[str, dict[str, dict[str, float]]]:
    merged: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    mass = decoded["MASSDEN"]
    aotk = decoded["AOTK"]
    for spec in specs:
        mass_rows = mass.get(spec.id) or {}
        aotk_rows = aotk.get(spec.id) or {}
        if set(mass_rows) != set(aotk_rows):
            raise ValueError(f"HRRR fields have different valid times for {spec.id}")
        for valid_time in sorted(mass_rows):
            if not (
                math.isclose(
                    float(mass_rows[valid_time]["grid_lat"]),
                    float(aotk_rows[valid_time]["grid_lat"]),
                    abs_tol=1e-9,
                )
                and math.isclose(
                    float(mass_rows[valid_time]["grid_lon"]),
                    float(aotk_rows[valid_time]["grid_lon"]),
                    abs_tol=1e-9,
                )
            ):
                raise ValueError(f"HRRR fields selected different grid cells for {spec.id}")
            merged[spec.id][valid_time] = {
                HRRR_AOD_COLUMN: aotk_rows[valid_time][HRRR_AOD_COLUMN],
                HRRR_SMOKE_COLUMN: mass_rows[valid_time][HRRR_SMOKE_COLUMN],
            }
    return {key: dict(value) for key, value in merged.items()}


def enrich_selected_rows(
    source_forecast_path: str | Path,
    *,
    spec: MarketSpec,
    selected_rows: Sequence[Mapping[str, Any]],
    values_by_date: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected_unit = str(spec.unit).strip().upper()
    if expected_unit not in {"C", "F"}:
        raise ValueError(f"unsupported temperature unit for {spec.id}: {spec.unit!r}")
    selected_keys = {
        (
            str(row["target_date"]),
            str(row["selected_issue_time"]),
            str(row.get("source") or ""),
            str(row.get("source_model") or ""),
        )
        for row in selected_rows
    }
    output = []
    supported_dates = set()
    paired_rows = Counter()
    with Path(source_forecast_path).open("r", encoding="utf-8-sig", newline="") as handle:
        for source_row in csv.DictReader(handle):
            key = (
                str(source_row.get("target_date") or ""),
                str(source_row.get("issue_time") or ""),
                str(source_row.get("source") or ""),
                str(source_row.get("source_model") or ""),
            )
            if key not in selected_keys:
                continue
            row = dict(source_row)
            row_unit = str(row.get("temperature_unit") or "").strip().upper()
            if row_unit != expected_unit:
                raise ValueError(
                    "selected forecast row temperature unit does not match market: "
                    f"market={spec.id}, expected={expected_unit}, got={row_unit or '<blank>'}"
                )
            target_text = str(row.get("target_date") or "")
            valid_time = str(row.get("valid_time") or "")
            item = (values_by_date.get(target_text) or {}).get(valid_time) or {}
            aotk_value = to_float(item.get(HRRR_AOD_COLUMN))
            smoke_value = to_float(item.get(HRRR_SMOKE_COLUMN))
            if (aotk_value is None) != (smoke_value is None):
                raise ValueError("HRRR adapter encountered an unpaired field value")
            row[HRRR_AOD_COLUMN] = "" if aotk_value is None else aotk_value
            row[HRRR_SMOKE_COLUMN] = "" if smoke_value is None else smoke_value
            if aotk_value is not None:
                paired_rows[target_text] += 1
            row["payload_hash"] = forecast_payload_hash(row)
            output.append(row)
    invalid_counts = {
        target_text: count
        for target_text, count in paired_rows.items()
        if count != EXPECTED_LOCAL_SAMPLES
    }
    if invalid_counts:
        raise ValueError(
            f"HRRR adapter did not produce exactly four paired samples: {invalid_counts}"
        )
    supported_dates.update(paired_rows)
    output.sort(key=lambda row: (str(row.get("target_date")), str(row.get("valid_time"))))
    return output, {
        "selected_market_dates": len(selected_keys),
        "supported_market_dates": len(supported_dates),
        "derived_rows": len(output),
        "paired_nonnull_rows": sum(paired_rows.values()),
        "expected_samples_per_supported_date": EXPECTED_LOCAL_SAMPLES,
    }


def _download_range(
    *,
    path: Path,
    url: str,
    start: int,
    end: int,
    timeout_seconds: float,
    attempts: int,
    request_get: Callable[..., Any],
    sleep_fn: Callable[[float], None],
) -> tuple[Path, dict[str, Any], bool]:
    _, record, fetched = fetch_or_load(
        path=path,
        url=url,
        byte_range=(int(start), int(end)),
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        request_get=request_get,
        sleep_fn=sleep_fn,
    )
    return path, record, fetched


def build_scratch_backfill(
    *,
    source_data_root: str | Path,
    output_root: str | Path,
    eccodes_path: str | Path | None,
    cutoff_local: str = "00:00",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    index_workers: int = DEFAULT_INDEX_WORKERS,
    range_workers: int = DEFAULT_RANGE_WORKERS,
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    specs: Sequence[MarketSpec] = BUILTIN_SPECS,
    request_get: Callable[..., Any] = requests.get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    source_root, paths = resolve_paths_outside_read_only_root(
        read_only_root=source_data_root,
        paths={
            "output_root": output_root,
            "raw_root": Path(output_root) / "raw",
            "derived_root": Path(output_root) / "derived_data",
            "design": Path(output_root) / "design_contract.json",
            "manifest": Path(output_root) / "manifest.json",
        },
    )
    output_root = paths["output_root"]
    preexisting_design = None
    if paths["design"].exists():
        preexisting_design = json.loads(paths["design"].read_text(encoding="utf-8"))
        validate_design_contract(preexisting_design)
    selected, target_dates, baseline_audit = _selected_baselines(
        source_root, specs, cutoff_local
    )
    source_inputs = [
        {"market_id": audit["market_id"], "role": role, **provenance}
        for audit in baseline_audit
        for role, provenance in audit.get("provenance", {}).items()
    ]
    for target_text in target_dates:
        target = date.fromisoformat(target_text)
        assert_cutoff_safe(
            target,
            feature_issue_time(target),
            specs,
            cutoff_local=cutoff_local,
        )
    if preexisting_design is not None:
        if preexisting_design.get("target_dates") != target_dates:
            raise ValueError(
                "existing HRRR design target universe differs from selected baseline dates"
            )
        design = preexisting_design
    else:
        design = freeze_design_contract(
            target_dates=target_dates,
            output_path=paths["design"],
            raw_root=paths["raw_root"],
            specs=specs,
            cutoff_local=cutoff_local,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            workers=index_workers,
            request_get=request_get,
            sleep_fn=sleep_fn,
        )
    decoder = load_eccodes(eccodes_path)
    availability = {
        (item["target_date"], int(item["step_hours"])): item
        for item in design["availability_records"]
    }
    requests_provenance = list(design["index_requests"])
    values: dict[str, dict[str, dict[str, dict[str, float]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    issue_records = []
    errors = []
    station_grid_lookup = None
    complete_set = set(design["complete_target_dates"])
    network_used = any(
        item.get("cache_status") == "fetched" for item in requests_provenance
    )
    with ThreadPoolExecutor(max_workers=max(1, int(range_workers))) as executor:
        for target_text in design["complete_target_dates"]:
            target = date.fromisoformat(target_text)
            issue = feature_issue_time(target)
            issue_text = issue.strftime("%Y%m%d%H")
            futures = {}
            try:
                for step in FORECAST_STEPS:
                    availability_record = availability[(target_text, step)]
                    for field in FIELDS:
                        selected_message = availability_record["selected"][field.name]
                        path = (
                            paths["raw_root"]
                            / issue_text
                            / f"f{step:02d}"
                            / f"{field.name}.grib2"
                        )
                        future = executor.submit(
                            _download_range,
                            path=path,
                            url=availability_record["grib_url"],
                            start=int(selected_message["offset"]),
                            end=int(selected_message["end_offset"]),
                            timeout_seconds=timeout_seconds,
                            attempts=attempts,
                            request_get=request_get,
                            sleep_fn=sleep_fn,
                        )
                        futures[future] = (step, field, selected_message)
                downloaded = {}
                for future in as_completed(futures):
                    step, field, selected_message = futures[future]
                    path, request, fetched = future.result()
                    downloaded[(step, field.name)] = (
                        field,
                        selected_message,
                        path,
                        request,
                    )
                    network_used = network_used or fetched
                decoded_results = {}
                if station_grid_lookup is None:
                    first_key = (FORECAST_STEPS[0], FIELDS[0].name)
                    first_field, _, first_path, _ = downloaded[first_key]
                    first_decoded, first_audit = decode_message(
                        first_path,
                        field=first_field,
                        target_date=target,
                        specs=specs,
                        eccodes=decoder,
                        issue_time=issue,
                        step_hours=first_key[0],
                    )
                    station_grid_lookup = first_audit["station_grid_lookup"]
                    decoded_results[first_key] = (first_decoded, first_audit)
                decode_futures = {}
                for (step, field_name), (field, _, path, _) in downloaded.items():
                    if (step, field_name) in decoded_results:
                        continue
                    future = executor.submit(
                        decode_message,
                        path,
                        field=field,
                        target_date=target,
                        specs=specs,
                        eccodes=decoder,
                        issue_time=issue,
                        step_hours=step,
                        station_grid_lookup=station_grid_lookup,
                    )
                    decode_futures[future] = (step, field_name)
                for future in as_completed(decode_futures):
                    decoded_results[decode_futures[future]] = future.result()
                target_values: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
                step_records = []
                for step in FORECAST_STEPS:
                    decoded_by_field = {}
                    field_records = []
                    for field in FIELDS:
                        _, selected_message, path, request = downloaded[(step, field.name)]
                        requests_provenance.append(request)
                        decoded, decode_audit = decoded_results[(step, field.name)]
                        decoded_by_field[field.name] = decoded
                        field_records.append(
                            {
                                "field": field.name,
                                "selected_message": selected_message,
                                "range_request_index": len(requests_provenance) - 1,
                                "range_sha256": request["sha256"],
                                "decode": decode_audit,
                            }
                        )
                    merged = _merge_field_values(decoded_by_field, specs)
                    for market_id, market_values in merged.items():
                        for valid_time, item in market_values.items():
                            if valid_time in target_values[market_id]:
                                raise ValueError(
                                    f"duplicate HRRR valid time for {market_id}: {valid_time}"
                                )
                            target_values[market_id][valid_time] = item
                    step_records.append(
                        {"step_hours": step, "fields": field_records}
                    )
                for spec in specs:
                    count = len(target_values.get(spec.id) or {})
                    if count != EXPECTED_LOCAL_SAMPLES:
                        raise ValueError(
                            f"HRRR local sample count for {spec.id} is {count}, "
                            f"expected {EXPECTED_LOCAL_SAMPLES}"
                        )
                    for item in target_values[spec.id].values():
                        if set(item) != {HRRR_AOD_COLUMN, HRRR_SMOKE_COLUMN}:
                            raise ValueError(f"unpaired HRRR target values for {spec.id}")
                for market_id, market_values in target_values.items():
                    values[market_id][target_text].update(market_values)
                issue_records.append(
                    {
                        "target_date": target_text,
                        "issue_time_utc": issue.isoformat(),
                        "buffered_available_time_utc": buffered_available_time(issue).isoformat(),
                        "massden_unit_rule": (
                            "pre_boundary_numeric_ug_m3_identity"
                            if issue < MASSDEN_UNIT_BOUNDARY
                            else "post_boundary_numeric_kg_m3_times_1e9"
                        ),
                        "steps": step_records,
                    }
                )
                if pause_seconds > 0:
                    sleep_fn(float(pause_seconds))
            except Exception as exc:  # noqa: BLE001 - exact target blocker is evidence
                for future in futures:
                    future.cancel()
                errors.append(
                    {
                        "target_date": target_text,
                        "issue_time_utc": issue.isoformat(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )

    derived_markets = []
    for spec in specs:
        source_forecast, source_settlement = source_paths(source_root, spec)
        rows, coverage = enrich_selected_rows(
            source_forecast,
            spec=spec,
            selected_rows=selected[spec.id],
            values_by_date=values.get(spec.id) or {},
        )
        forecast_path = (
            paths["derived_root"]
            / "forecast_history"
            / spec.icao.lower()
            / "forecast_long.csv"
        )
        settlement_path = (
            paths["derived_root"]
            / "wunderground"
            / spec.icao.lower()
            / "daily"
            / "daily_summary.csv"
        )
        write_csv_rows_atomic(forecast_path, HRRR_FORECAST_COLUMNS, rows)
        if source_settlement.exists():
            copy_file_atomic(source_settlement, settlement_path)
        derived_markets.append(
            {
                "market_id": spec.id,
                "station": spec.icao,
                **coverage,
                "forecast_path": str(forecast_path),
                "forecast_sha256": sha256_file(forecast_path),
                "settlement_path": str(settlement_path),
                "settlement_sha256": sha256_file(settlement_path),
            }
        )

    successful_dates = {item["target_date"] for item in issue_records}
    failed_dates = {item["target_date"] for item in errors}
    selected_dates_by_market = {
        spec.id: {str(row["target_date"]) for row in selected[spec.id]}
        for spec in specs
    }
    market_date_coverage = []
    for target_text in target_dates:
        for spec in specs:
            predictor_acquired = target_text in successful_dates
            baseline_and_settlement_available = (
                target_text in selected_dates_by_market[spec.id]
            )
            supported = predictor_acquired and baseline_and_settlement_available
            if supported:
                reason = None
            elif predictor_acquired and not baseline_and_settlement_available:
                reason = "baseline_or_settlement_unavailable_in_sealed_corpus"
            elif target_text not in complete_set:
                reason = "incomplete_exact_index_field_step_availability"
            elif target_text in failed_dates:
                reason = "bounded_range_fetch_or_strict_decode_failure"
            else:
                reason = "unexpected_missing_support"
            market_date_coverage.append(
                {
                    "target_date": target_text,
                    "market_id": spec.id,
                    "predictor_acquired": predictor_acquired,
                    "baseline_and_settlement_available": baseline_and_settlement_available,
                    "supported": supported,
                    "drop_reason": reason,
                }
            )

    source_mirror_mutated = False
    for source_input in source_inputs:
        after = sha256_file(source_input["path"])
        source_input["sha256_after"] = after
        source_input["unchanged_during_run"] = source_input.get("sha256") == after
        source_mirror_mutated = source_mirror_mutated or not source_input["unchanged_during_run"]
    if source_mirror_mutated:
        errors.append(
            {
                "target_date": None,
                "issue_time_utc": None,
                "error_type": "SourceMirrorMutationError",
                "error": "one or more source input hashes changed during the run",
            }
        )
    normalization_counts = Counter(
        item["massden_unit_rule"] for item in issue_records
    )
    max_distance = max(
        (
            float(field["decode"]["max_nearest_grid_distance_km"])
            for issue in issue_records
            for step in issue["steps"]
            for field in step["fields"]
        ),
        default=None,
    )
    drop_reason_counts = Counter(
        item["drop_reason"] for item in market_date_coverage if item["drop_reason"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "research_only": True,
        "code": {
            "module": "weather.reporting.research.hrrr_smoke_research",
            "path": str(Path(__file__).resolve(strict=True)),
            "sha256": sha256_file(__file__),
        },
        "source_data_root": str(source_root),
        "output_root": str(output_root),
        "derived_data_root": str(paths["derived_root"]),
        "source": {
            "provider": "NOAA",
            "dataset": "HRRR CONUS surface archive",
            "base_url": BASE_URL,
            "unit_notice_url": UNIT_NOTICE_URL,
        },
        "design_contract_path": str(paths["design"]),
        "design_contract_file_sha256": sha256_file(paths["design"]),
        "design": design,
        "target_date_count": len(target_dates),
        "first_target_date": target_dates[0] if target_dates else None,
        "last_target_date": target_dates[-1] if target_dates else None,
        "request_count": len(requests_provenance),
        "requests": requests_provenance,
        "network_used": network_used,
        "issue_count": len(issue_records),
        "issues": issue_records,
        "error_count": len(errors),
        "errors": errors,
        "normalization_boundary_counts": dict(sorted(normalization_counts.items())),
        "max_nearest_grid_distance_km": max_distance,
        "baseline_audit": baseline_audit,
        "source_input_count": len(source_inputs),
        "source_inputs": source_inputs,
        "markets": derived_markets,
        "supported_market_dates": sum(item["supported_market_dates"] for item in derived_markets),
        "market_date_coverage": market_date_coverage,
        "drop_reason_counts": dict(sorted(drop_reason_counts.items())),
        "source_mirror_mutated": source_mirror_mutated,
        "serving_or_collector_contract_changed": False,
    }


def write_manifest_report(path: str | Path, payload: Mapping[str, Any]) -> Path:
    design = payload["design"]
    lines = [
        "# Scratch NOAA HRRR AOTK + Smoke Mass Backfill",
        "",
        f"Generated: {payload['generated_at_utc']}",
        f"Schema: `{payload['schema_version']}`",
        "",
        "Every index, GRIB range, and derived row is under scratch; the source mirror remained read-only.",
        "",
        "MASSDEN is modeled smoke mass density, not PM2.5. The design and transform were frozen before outcomes were evaluated.",
        "",
        "## Frozen Design",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Issue rule", design["issue_time_contract"]["rule"]],
            ["Forecast steps", ", ".join(map(str, FORECAST_STEPS))],
            ["Fields", "AOTK + MASSDEN at 8 m"],
            ["AOTK transform", "native mean/max"],
            ["MASSDEN transform", "normalize ug/m^3, log1p each sample, mean/max"],
            ["Unit boundary", MASSDEN_UNIT_BOUNDARY.isoformat()],
            ["Target dates", payload["target_date_count"]],
            ["Complete index dates", design["complete_date_count"]],
            ["Decoded issues", payload["issue_count"]],
            ["Decode/fetch errors", payload["error_count"]],
            ["Supported market-dates", payload["supported_market_dates"]],
            ["Design contract SHA-256", design["contract_sha256"]],
            ["Max nearest-grid distance km", payload["max_nearest_grid_distance_km"]],
        ],
    )
    lines += ["", "## Availability by Year", ""]
    lines += markdown_table(
        ["Year", "Targets", "Complete", "Missing"],
        [
            [item["year"], item["target_dates"], item["complete_dates"], item["missing_dates"]]
            for item in design["coverage_by_year"]
        ],
    )
    lines += ["", "## Boundary Eras", ""]
    lines += markdown_table(
        ["Rule", "Decoded target dates"],
        [[key, value] for key, value in payload["normalization_boundary_counts"].items()],
    )
    lines += ["", "## Market Coverage", ""]
    lines += markdown_table(
        ["Market", "Selected dates", "Supported dates", "Paired rows"],
        [
            [
                item["market_id"],
                item["selected_market_dates"],
                item["supported_market_dates"],
                item["paired_nonnull_rows"],
            ]
            for item in payload["markets"]
        ],
    )
    if payload["errors"]:
        lines += ["", "## Errors", ""]
        lines.extend(
            f"- {item['target_date']} ({item['error_type']}): {item['error']}"
            for item in payload["errors"]
        )
    return write_text_atomic(path, "\n".join(lines) + "\n")


def _audit_quantiles(values: Sequence[float]) -> dict[str, float]:
    """Return deterministic linear-interpolation quantiles for a raw predictor."""

    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("cannot audit an empty predictor series")
    output = {}
    for percentile in (0, 1, 5, 25, 50, 75, 95, 99, 100):
        position = (len(ordered) - 1) * percentile / 100.0
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            value = ordered[lower]
        else:
            fraction = position - lower
            value = ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
        output[f"p{percentile:03d}"] = float(value)
    return output


def write_predictor_integrity_audit(
    *,
    manifest_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Verify cached artifacts and raw HRRR scales without reading outcomes.

    The audit reads only the two predictor columns plus ``issue_time`` from the
    derived forecast CSVs.  Settlement files are hashed, never parsed.  This
    keeps the scale gate outcome-blind while still proving the evaluator input
    tree matches the manifest byte-for-byte.
    """

    manifest_path = Path(manifest_path).resolve(strict=True)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches = []

    def verify_file(record: Mapping[str, Any], *, label: str) -> None:
        raw_path = Path(str(record["path"]))
        path = raw_path if raw_path.is_absolute() else (Path.cwd() / raw_path)
        if not path.exists():
            mismatches.append(f"{label}:missing:{path}")
            return
        size = path.stat().st_size
        if record.get("size_bytes") is not None and size != int(record["size_bytes"]):
            mismatches.append(f"{label}:size:{path}")
        expected_sha = record.get("sha256")
        if expected_sha and sha256_file(path) != expected_sha:
            mismatches.append(f"{label}:sha256:{path}")

    for index, record in enumerate(payload["requests"]):
        verify_file(record, label=f"request[{index}]")
    for index, record in enumerate(payload["source_inputs"]):
        verify_file(record, label=f"source_input[{index}]")
        if not record.get("unchanged_during_run"):
            mismatches.append(f"source_input[{index}]:changed_during_run")
        if record.get("sha256") != record.get("sha256_after"):
            mismatches.append(f"source_input[{index}]:before_after_sha256")

    design_path = Path(str(payload["design_contract_path"]))
    if not design_path.is_absolute():
        design_path = Path.cwd() / design_path
    if sha256_file(design_path) != payload["design_contract_file_sha256"]:
        mismatches.append("design_contract:sha256")
    code_path = Path(str(payload["code"]["path"]))
    if sha256_file(code_path) != payload["code"]["sha256"]:
        mismatches.append("research_module:sha256")

    series = {HRRR_AOD_COLUMN: [], HRRR_SMOKE_COLUMN: []}
    era_series = {
        "pre_boundary_numeric_ug_m3_identity": {
            HRRR_AOD_COLUMN: [],
            HRRR_SMOKE_COLUMN: [],
        },
        "post_boundary_numeric_kg_m3_times_1e9": {
            HRRR_AOD_COLUMN: [],
            HRRR_SMOKE_COLUMN: [],
        },
    }
    sample_counts = Counter()
    for market in payload["markets"]:
        for role in ("forecast", "settlement"):
            path = Path(str(market[f"{role}_path"]))
            expected_sha = market[f"{role}_sha256"]
            if sha256_file(path) != expected_sha:
                mismatches.append(f"market:{market['market_id']}:{role}:sha256")
        forecast_path = Path(str(market["forecast_path"]))
        with forecast_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            indices = {
                name: header.index(name)
                for name in ("target_date", "issue_time", HRRR_AOD_COLUMN, HRRR_SMOKE_COLUMN)
            }
            for row in reader:
                raw_aod = row[indices[HRRR_AOD_COLUMN]].strip()
                raw_smoke = row[indices[HRRR_SMOKE_COLUMN]].strip()
                if not raw_aod and not raw_smoke:
                    continue
                if not raw_aod or not raw_smoke:
                    mismatches.append(
                        f"market:{market['market_id']}:unpaired_predictor_row"
                    )
                    continue
                values = {
                    HRRR_AOD_COLUMN: float(raw_aod),
                    HRRR_SMOKE_COLUMN: float(raw_smoke),
                }
                if any(not math.isfinite(value) or value < 0.0 for value in values.values()):
                    mismatches.append(
                        f"market:{market['market_id']}:nonfinite_or_negative_predictor"
                    )
                    continue
                issue = datetime.fromisoformat(
                    row[indices["issue_time"]].replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                era = (
                    "pre_boundary_numeric_ug_m3_identity"
                    if issue < MASSDEN_UNIT_BOUNDARY
                    else "post_boundary_numeric_kg_m3_times_1e9"
                )
                for field, value in values.items():
                    series[field].append(value)
                    era_series[era][field].append(value)
                sample_counts[(market["market_id"], row[indices["target_date"]])] += 1

    invalid_sample_counts = {
        f"{market_id}:{target_date}": count
        for (market_id, target_date), count in sample_counts.items()
        if count != EXPECTED_LOCAL_SAMPLES
    }
    if invalid_sample_counts:
        mismatches.append("derived_predictors:unexpected_local_sample_counts")
    expected_rows = sum(int(item["paired_nonnull_rows"]) for item in payload["markets"])
    if any(len(values) != expected_rows for values in series.values()):
        mismatches.append("derived_predictors:paired_row_count")

    field_audits = {}
    for field, values in series.items():
        field_audits[field] = {
            "count": len(values),
            "finite_count": sum(math.isfinite(value) for value in values),
            "negative_count": sum(value < 0.0 for value in values),
            "zero_count": sum(value == 0.0 for value in values),
            "zero_fraction": sum(value == 0.0 for value in values) / len(values),
            "quantiles": _audit_quantiles(values),
            "log1p_finite_count": sum(math.isfinite(math.log1p(value)) for value in values),
            "by_unit_era": {
                era: {
                    "count": len(era_values[field]),
                    "quantiles": _audit_quantiles(era_values[field]),
                }
                for era, era_values in era_series.items()
            },
        }
    pre_median = field_audits[HRRR_SMOKE_COLUMN]["by_unit_era"][
        "pre_boundary_numeric_ug_m3_identity"
    ]["quantiles"]["p050"]
    post_median = field_audits[HRRR_SMOKE_COLUMN]["by_unit_era"][
        "post_boundary_numeric_kg_m3_times_1e9"
    ]["quantiles"]["p050"]
    positive = [value for value in (pre_median, post_median) if value > 0.0]
    median_era_log10_gap = (
        abs(math.log10(pre_median) - math.log10(post_median))
        if len(positive) == 2
        else None
    )
    no_billion_fold_discontinuity = (
        median_era_log10_gap is None or median_era_log10_gap < 6.0
    )
    if not no_billion_fold_discontinuity:
        mismatches.append("massden:obvious_unit_discontinuity")

    result = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "predictor_scale_integrity_audit",
        "generated_at_utc": utc_iso(),
        "outcome_blind": True,
        "outcome_fields_read": [],
        "settlement_files_parsed": False,
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "design_contract_file_sha256": payload["design_contract_file_sha256"],
        "design_contract_sha256": payload["design"]["contract_sha256"],
        "request_count": len(payload["requests"]),
        "index_request_count": sum(
            str(record["path"]).lower().endswith(".idx") for record in payload["requests"]
        ),
        "grib_range_request_count": sum(
            str(record["path"]).lower().endswith(".grib2") for record in payload["requests"]
        ),
        "source_input_count": len(payload["source_inputs"]),
        "derived_predictor_row_count": expected_rows,
        "derived_market_date_count": len(sample_counts),
        "invalid_sample_counts": invalid_sample_counts,
        "fields": field_audits,
        "massden_median_era_log10_gap": median_era_log10_gap,
        "no_obvious_billion_fold_unit_discontinuity": no_billion_fold_discontinuity,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "status": "PASS" if not mismatches else "FAIL",
    }
    write_json_atomic(output_path, result)
    if mismatches:
        raise ValueError(f"HRRR predictor integrity audit failed: {mismatches[:5]}")
    return result


def run(args: argparse.Namespace) -> dict[str, Any]:
    _, paths = resolve_paths_outside_read_only_root(
        read_only_root=args.source_data_root,
        paths={
            "output_root": args.output_root,
            "manifest": Path(args.output_root) / "manifest.json",
            "report": Path(args.output_root) / "manifest.md",
        },
    )
    payload = build_scratch_backfill(
        source_data_root=args.source_data_root,
        output_root=paths["output_root"],
        eccodes_path=args.eccodes_path,
        cutoff_local=args.cutoff_local,
        timeout_seconds=args.timeout_seconds,
        attempts=args.attempts,
        index_workers=args.index_workers,
        range_workers=args.range_workers,
        pause_seconds=args.pause_seconds,
    )
    write_json_atomic(paths["manifest"], payload)
    write_manifest_report(paths["report"], payload)
    write_predictor_integrity_audit(
        manifest_path=paths["manifest"],
        output_path=paths["output_root"] / "predictor_scale_integrity_audit.json",
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill fixed-cycle NOAA HRRR AOTK and smoke mass into scratch."
    )
    parser.add_argument("--source-data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--eccodes-path", required=True)
    parser.add_argument("--cutoff-local", default="00:00")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--index-workers", type=int, default=DEFAULT_INDEX_WORKERS)
    parser.add_argument("--range-workers", type=int, default=DEFAULT_RANGE_WORKERS)
    parser.add_argument("--pause-seconds", type=float, default=DEFAULT_PAUSE_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(
        f"HRRR smoke backfill: {payload['issue_count']}/"
        f"{payload['design']['complete_date_count']} available issues, "
        f"{payload['supported_market_dates']} supported market-dates, "
        f"{payload['error_count']} errors"
    )
    return 0 if payload["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
