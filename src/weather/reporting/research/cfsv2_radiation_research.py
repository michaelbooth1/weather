"""Exact-issue NOAA CFSv2 radiation source-contract sensitivity for Tmax.

The outcome-blind design reuses the CFSv2 top-soil experiment's frozen 206-date
cohort, target-minus-two-calendar-days 18Z control member, and local-day
f36--f60 horizon.  Four exact time-series files are required: surface downward
shortwave, visible diffuse, near-IR diffuse, and total cloud cover.

Before any outcome join, arithmetic is fixed as total = DSWRF, diffuse = VDDSF
+ NDDSF, and direct-derived = max(total - diffuse, 0), all in W m**-2; cloud is
TCDC in percent.  The existing radiation evaluator then uses its already fixed
total/direct/diffuse/cloud aggregates.  This is a source-contract sensitivity,
not independent outcome confirmation, and changes no collector or serving path.
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
from datetime import date, datetime, timedelta
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
    BASE_URL,
    MEMBER,
    InventoryMessage,
    _aware_utc,
    _grib_reference_time,
    _grib_valid_time,
    assert_cutoff_safe,
    buffered_available_time,
    feature_issue_time,
    fetch_or_load,
    load_eccodes,
    selected_inventory_span,
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


SCHEMA_VERSION = schema_version("cfsv2_radiation_research")
DESIGN_SCHEMA_VERSION = schema_version("cfsv2_radiation_design_contract")
SOIL_AVAILABILITY_SCHEMA_VERSION = schema_version(
    "cfsv2_soil_availability_contract"
)
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_ATTEMPTS = 4
DEFAULT_WORKERS = 16
GRID_TYPE = "regular_gg"
GRID_X_POINTS = 384
GRID_Y_POINTS = 190
EXPECTED_LOCAL_SAMPLES = 4
RADIATION_FORECAST_COLUMNS = RICH_FORECAST_COLUMNS


@dataclass(frozen=True)
class RadiationVariable:
    archive_name: str
    inventory_name: str
    short_name: str
    units: str
    type_of_level: str
    level: int
    parameter_category: int
    parameter_number: int
    decoded_key: str
    minimum: float
    maximum: float


RADIATION_VARIABLES = (
    RadiationVariable(
        "dswsfc", "DSWRF", "sdswrf", "W m**-2", "surface", 0, 4, 192,
        "total_shortwave_w_m2", 0.0, 1500.0,
    ),
    RadiationVariable(
        "vddsf", "VDDSF", "vddsf", "W m**-2", "surface", 0, 4, 201,
        "visible_diffuse_w_m2", 0.0, 1500.0,
    ),
    RadiationVariable(
        "nddsf", "NDDSF", "nddsf", "W m**-2", "surface", 0, 4, 203,
        "near_ir_diffuse_w_m2", 0.0, 1500.0,
    ),
    RadiationVariable(
        "tcdcclm", "TCDC", "tcc", "%", "atmosphereSingleLayer", 0, 6, 1,
        "total_cloud_percent", 0.0, 100.0,
    ),
)

_SOIL_AVAILABILITY_FROZEN_FIELDS = (
    "schema_version",
    "selection_basis",
    "issue_rule",
    "member",
    "variables",
    "physical_depth_m",
    "target_dates",
    "complete_pair_target_dates",
    "records",
)
_RADIATION_DESIGN_FROZEN_FIELDS = (
    "schema_version",
    "source_contract_sensitivity",
    "independent_outcome_confirmation",
    "upstream_date_contract",
    "target_dates",
    "candidate_target_dates",
    "complete_target_dates",
    "issue_contract",
    "field_contract",
    "arithmetic_contract",
    "feature_contract",
    "evaluation_contract",
    "availability_records",
    "coverage_by_year",
    "frozen_before_grib_decode",
    "frozen_before_outcome_join",
    "frozen_before_model_fit_or_score",
)
_SOIL_ARCHIVE_NAMES = ("soilt1", "soilm1")


def _canonical_subset_sha256(
    payload: Mapping[str, Any], fields: Sequence[str], *, label: str
) -> str:
    missing = [field for field in fields if field not in payload]
    if missing:
        raise ValueError(f"{label} is missing frozen fields: {missing}")
    frozen = {field: payload[field] for field in fields}
    canonical = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    return sha256_bytes(canonical)


def _validated_dates(value: Any, *, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be a list of ISO date strings")
    if value != sorted(set(value)):
        raise ValueError(f"{label} must be sorted and unique")
    for item in value:
        date.fromisoformat(item)
    return list(value)


def _paths_collide(left: str | Path, right: str | Path) -> bool:
    left_path = Path(left).resolve(strict=False)
    right_path = Path(right).resolve(strict=False)
    if left_path == right_path:
        return True
    if left_path.exists() and right_path.exists():
        try:
            return left_path.samefile(right_path)
        except OSError:
            return False
    return False


def _known_generated_output_paths(
    output_root: str | Path,
    *,
    target_dates: Sequence[str],
    specs: Sequence[MarketSpec],
) -> dict[str, Path]:
    """Enumerate every file this runner can create below ``output_root``."""

    root = Path(output_root)
    outputs = {
        "design": root / "design_contract.json",
        "manifest": root / "manifest.json",
        "report": root / "manifest.md",
        "integrity_audit": root / "predictor_scale_integrity_audit.json",
    }
    for spec in specs:
        outputs[f"forecast:{spec.id}"] = (
            root / "derived_data" / "forecast_history" / spec.icao.lower() / "forecast_long.csv"
        )
        outputs[f"settlement:{spec.id}"] = (
            root
            / "derived_data"
            / "wunderground"
            / spec.icao.lower()
            / "daily"
            / "daily_summary.csv"
        )
    for target_text in target_dates:
        target = date.fromisoformat(target_text)
        issue = feature_issue_time(target)
        issue_text = issue.strftime("%Y%m%d%H")
        selected_steps = [
            step
            for step in range(6, 121, 6)
            if any(
                (issue + timedelta(hours=step)).astimezone(spec.tz).date() == target
                for spec in specs
            )
        ]
        for variable in RADIATION_VARIABLES:
            prefix = f"raw:{target_text}:{variable.archive_name}"
            outputs[f"{prefix}:inventory"] = (
                root
                / "raw"
                / issue_text
                / f"{variable.archive_name}.{MEMBER}.{issue_text}.daily.inv"
            )
            if selected_steps:
                outputs[f"{prefix}:range"] = (
                    root
                    / "raw"
                    / issue_text
                    / (
                        f"{variable.archive_name}.{MEMBER}.{issue_text}.f"
                        f"{selected_steps[0]:04d}-f{selected_steps[-1]:04d}.grb2"
                    )
                )
    return outputs


def _reject_upstream_output_collisions(
    upstream_contract_path: str | Path,
    generated_paths: Mapping[str, Path],
) -> None:
    for label, path in generated_paths.items():
        if _paths_collide(path, upstream_contract_path):
            raise ValueError(
                f"CFSv2 radiation {label} output collides with upstream soil contract"
            )


def validate_soil_availability_contract(payload: Mapping[str, Any]) -> None:
    """Fail closed on a mutable upstream soil availability contract."""

    if payload.get("schema_version") != SOIL_AVAILABILITY_SCHEMA_VERSION:
        raise ValueError("upstream CFSv2 soil contract has the wrong schema")
    actual_hash = str(payload.get("contract_sha256") or "")
    expected_hash = _canonical_subset_sha256(
        payload,
        _SOIL_AVAILABILITY_FROZEN_FIELDS,
        label="upstream CFSv2 soil contract",
    )
    if actual_hash != expected_hash:
        raise ValueError("upstream CFSv2 soil contract canonical hash mismatch")
    targets = _validated_dates(payload.get("target_dates"), label="soil target_dates")
    complete = _validated_dates(
        payload.get("complete_pair_target_dates"),
        label="soil complete_pair_target_dates",
    )
    if not set(complete).issubset(targets):
        raise ValueError("soil complete-pair dates are not a subset of target dates")
    if payload.get("issue_rule") != "target minus two UTC calendar days at 18Z":
        raise ValueError("upstream CFSv2 soil issue rule changed")
    if payload.get("member") != MEMBER:
        raise ValueError("upstream CFSv2 soil member changed")
    variables = list(_SOIL_ARCHIVE_NAMES)
    if (
        payload.get("variables") != variables
        or payload.get("physical_depth_m") != [0.0, 0.1]
    ):
        raise ValueError("upstream CFSv2 soil field/depth contract changed")
    records = list(payload.get("records") or [])
    actual_keys = [(item.get("target_date"), item.get("variable")) for item in records]
    expected_keys = sorted(
        (target, variable) for target in targets for variable in variables
    )
    if actual_keys != expected_keys:
        raise ValueError("upstream CFSv2 soil availability records are incomplete or reordered")
    by_key = {(item["target_date"], item["variable"]): item for item in records}
    derived_complete = [
        target
        for target in targets
        if all(by_key[(target, variable)].get("status_code") == 200 for variable in variables)
    ]
    if complete != derived_complete:
        raise ValueError("upstream CFSv2 soil complete-pair dates do not match records")
    if payload.get("target_date_count") != len(targets):
        raise ValueError("upstream CFSv2 soil target-date count mismatch")
    if payload.get("complete_pair_date_count") != len(complete):
        raise ValueError("upstream CFSv2 soil complete-date count mismatch")
    if payload.get("missing_pair_date_count") != len(targets) - len(complete):
        raise ValueError("upstream CFSv2 soil missing-date count mismatch")
    if payload.get("frozen_before_grib_decode") is not True:
        raise ValueError("upstream CFSv2 soil contract was not frozen before decode")


def validate_design_contract(
    payload: Mapping[str, Any], *, upstream_contract_path: str | Path
) -> None:
    """Verify the frozen CFSv2 radiation design before resume or acquisition."""

    if payload.get("schema_version") != DESIGN_SCHEMA_VERSION:
        raise ValueError("existing CFSv2 radiation design has the wrong schema")
    expected_hash = _canonical_subset_sha256(
        payload,
        _RADIATION_DESIGN_FROZEN_FIELDS,
        label="CFSv2 radiation design",
    )
    if payload.get("contract_sha256") != expected_hash:
        raise ValueError("existing CFSv2 radiation design canonical hash mismatch")
    if not all(
        payload.get(field) is True
        for field in (
            "frozen_before_grib_decode",
            "frozen_before_outcome_join",
            "frozen_before_model_fit_or_score",
        )
    ):
        raise ValueError("existing CFSv2 radiation design was not outcome-blind")

    targets = _validated_dates(payload.get("target_dates"), label="radiation target_dates")
    candidates = _validated_dates(
        payload.get("candidate_target_dates"), label="radiation candidate_target_dates"
    )
    complete = _validated_dates(
        payload.get("complete_target_dates"), label="radiation complete_target_dates"
    )
    if not set(candidates).issubset(targets) or not set(complete).issubset(candidates):
        raise ValueError("CFSv2 radiation date cohorts violate subset invariants")
    for field, expected in (
        ("target_date_count", len(targets)),
        ("candidate_date_count", len(candidates)),
        ("complete_date_count", len(complete)),
        ("missing_date_count", len(candidates) - len(complete)),
    ):
        if payload.get(field) != expected:
            raise ValueError(f"CFSv2 radiation {field} mismatch")

    variable_names = [item.archive_name for item in RADIATION_VARIABLES]
    records = list(payload.get("availability_records") or [])
    actual_keys = [(item.get("target_date"), item.get("variable")) for item in records]
    expected_keys = sorted(
        (target, variable) for target in candidates for variable in variable_names
    )
    if actual_keys != expected_keys:
        raise ValueError("CFSv2 radiation availability records are incomplete or reordered")
    by_key = {(item["target_date"], item["variable"]): item for item in records}
    derived_complete = [
        target
        for target in candidates
        if all(by_key[(target, variable)].get("status_code") == 200 for variable in variable_names)
    ]
    if complete != derived_complete:
        raise ValueError("CFSv2 radiation complete dates do not match availability records")

    upstream_path = Path(upstream_contract_path).resolve(strict=True)
    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    validate_soil_availability_contract(upstream)
    binding = payload.get("upstream_date_contract") or {}
    if binding.get("file_sha256") != sha256_file(upstream_path):
        raise ValueError("upstream frozen date contract changed after design freeze")
    if binding.get("contract_sha256") != upstream.get("contract_sha256"):
        raise ValueError("upstream canonical date contract changed after design freeze")
    if targets != upstream["target_dates"] or candidates != upstream["complete_pair_target_dates"]:
        raise ValueError("CFSv2 radiation design date cohort differs from upstream contract")


VARIABLE_BY_NAME = {item.archive_name: item for item in RADIATION_VARIABLES}


def archive_urls(variable: RadiationVariable, issue_time: datetime) -> tuple[str, str]:
    issue = _aware_utc(issue_time, label="issue_time")
    issue_text = issue.strftime("%Y%m%d%H")
    root = f"{BASE_URL}/{issue:%Y}/{issue:%Y%m}/{issue:%Y%m%d}/{issue_text}"
    stem = f"{variable.archive_name}.{MEMBER}.{issue_text}.daily"
    return f"{root}/{stem}.grb2", f"{root}/{stem}.inv"


def parse_inventory(
    text: str,
    *,
    variable: RadiationVariable,
    expected_issue_time: datetime | None = None,
) -> list[InventoryMessage]:
    level = (
        "surface"
        if variable.archive_name != "tcdcclm"
        else "entire atmosphere \\(considered as a single layer\\)"
    )
    pattern = re.compile(
        rf"^(?P<message>\d+):(?P<offset>\d+):d=(?P<issue>\d{{10}}):"
        rf"{re.escape(variable.inventory_name)}:{level}:"
        rf"(?P<step>\d+) hour fcst:"
    )
    messages = []
    for line in text.splitlines():
        if match := pattern.match(line.strip()):
            messages.append(
                InventoryMessage(
                    message=int(match.group("message")),
                    offset=int(match.group("offset")),
                    issue_text=match.group("issue"),
                    step_hours=int(match.group("step")),
                )
            )
    if not messages:
        raise ValueError(
            f"CFSv2 {variable.archive_name} inventory contained no exact field messages"
        )
    if [item.message for item in messages] != list(range(1, len(messages) + 1)):
        raise ValueError("CFSv2 radiation inventory message numbers are not contiguous")
    if any(right.offset <= left.offset for left, right in zip(messages, messages[1:])):
        raise ValueError("CFSv2 radiation inventory offsets are not increasing")
    if len({item.issue_text for item in messages}) != 1:
        raise ValueError("CFSv2 radiation inventory contains mixed issue cycles")
    if expected_issue_time is not None:
        expected = _aware_utc(
            expected_issue_time, label="expected_issue_time"
        ).strftime("%Y%m%d%H")
        if messages[0].issue_text != expected:
            raise ValueError(
                f"CFSv2 radiation inventory cycle mismatch: {messages[0].issue_text} != {expected}"
            )
    steps = [item.step_hours for item in messages]
    if any(step <= 0 or step % 6 for step in steps):
        raise ValueError("CFSv2 radiation steps are not positive six-hour steps")
    if any(right <= left for left, right in zip(steps, steps[1:])):
        raise ValueError("CFSv2 radiation steps are not strictly increasing")
    return messages


def _head_inventory(
    *,
    target_text: str,
    variable: RadiationVariable,
    timeout_seconds: float,
    attempts: int,
    request_head: Callable[..., Any],
    sleep_fn: Callable[[float], None],
) -> dict[str, Any]:
    target = date.fromisoformat(target_text)
    issue = feature_issue_time(target)
    _, url = archive_urls(variable, issue)
    response = None
    error = None
    for attempt in range(max(1, int(attempts))):
        try:
            response = request_head(url, timeout=timeout_seconds, allow_redirects=True)
            if int(response.status_code) < 500 and int(response.status_code) != 429:
                break
        except Exception as exc:  # noqa: BLE001 - frozen availability evidence
            error = f"{type(exc).__name__}: {exc}"
        if attempt + 1 < max(1, int(attempts)):
            sleep_fn(min(4.0, 0.5 * (2**attempt)))
    return {
        "target_date": target_text,
        "issue_time_utc": issue.isoformat(),
        "variable": variable.archive_name,
        "inventory_url": url,
        "status_code": None if response is None else int(response.status_code),
        "content_length": None if response is None else response.headers.get("Content-Length"),
        "etag": None if response is None else response.headers.get("ETag"),
        "last_modified": None if response is None else response.headers.get("Last-Modified"),
        "error": error if response is None else None,
    }


def freeze_design_contract(
    *,
    upstream_contract_path: str | Path,
    output_path: str | Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    workers: int = DEFAULT_WORKERS,
    request_head: Callable[..., Any] = requests.head,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Freeze exact fields, arithmetic, split, and support before GRIB/outcomes."""

    upstream_path = Path(upstream_contract_path).resolve(strict=True)
    output_path = Path(output_path).resolve(strict=False)
    if _paths_collide(output_path, upstream_path):
        raise ValueError(
            "CFSv2 radiation design output collides with upstream soil contract"
        )
    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    validate_soil_availability_contract(upstream)
    candidate_dates = list(upstream.get("complete_pair_target_dates") or [])
    target_dates = list(upstream.get("target_dates") or [])
    if not candidate_dates or not target_dates:
        raise ValueError("upstream CFSv2 soil contract has no frozen date cohort")
    tasks = [
        (target_text, variable)
        for target_text in candidate_dates
        for variable in RADIATION_VARIABLES
    ]
    records = []
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        futures = [
            executor.submit(
                _head_inventory,
                target_text=target_text,
                variable=variable,
                timeout_seconds=timeout_seconds,
                attempts=attempts,
                request_head=request_head,
                sleep_fn=sleep_fn,
            )
            for target_text, variable in tasks
        ]
        for future in as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda item: (item["target_date"], item["variable"]))
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_date[record["target_date"]].append(record)
    required = {item.archive_name for item in RADIATION_VARIABLES}
    complete = [
        target_text
        for target_text in candidate_dates
        if {item["variable"] for item in by_date[target_text]} == required
        and all(item["status_code"] == 200 for item in by_date[target_text])
    ]
    plan = chronological_plan(
        complete,
        holdout_fraction=DEFAULT_HOLDOUT_FRACTION,
        folds=DEFAULT_FOLDS,
        min_train_dates=Thresholds().min_train_dates,
        min_holdout_dates=Thresholds().min_holdout_dates,
    )
    coverage = []
    candidate_years = Counter(item[:4] for item in candidate_dates)
    complete_years = Counter(item[:4] for item in complete)
    for year in sorted(candidate_years):
        coverage.append(
            {
                "year": int(year),
                "candidate_dates": candidate_years[year],
                "complete_dates": complete_years[year],
                "missing_dates": candidate_years[year] - complete_years[year],
            }
        )
    frozen = {
        "schema_version": DESIGN_SCHEMA_VERSION,
        "source_contract_sensitivity": True,
        "independent_outcome_confirmation": False,
        "upstream_date_contract": {
            "path": str(upstream_path),
            "file_sha256": sha256_file(upstream_path),
            "contract_sha256": upstream.get("contract_sha256"),
            "schema_version": upstream.get("schema_version"),
            "basis": "exact complete-pair CFSv2 soil cohort; no outcome values or scores",
        },
        "target_dates": target_dates,
        "candidate_target_dates": candidate_dates,
        "complete_target_dates": complete,
        "issue_contract": {
            "rule": "target minus two UTC calendar days at 18Z",
            "member": MEMBER,
            "availability_buffer_hours": 12,
            "selected_steps_hours": [36, 42, 48, 54, 60],
            "local_samples_per_market_date": EXPECTED_LOCAL_SAMPLES,
        },
        "field_contract": [
            {
                "archive_name": item.archive_name,
                "inventory_name": item.inventory_name,
                "short_name": item.short_name,
                "units": item.units,
                "type_of_level": item.type_of_level,
                "level": item.level,
                "discipline": 0,
                "parameter_category": item.parameter_category,
                "parameter_number": item.parameter_number,
                "step_type": "instant",
                "grid": {"type": GRID_TYPE, "nx": GRID_X_POINTS, "ny": GRID_Y_POINTS},
            }
            for item in RADIATION_VARIABLES
        ],
        "arithmetic_contract": {
            "shortwave_radiation": "dswsfc total downward shortwave, W m**-2",
            "diffuse_radiation": "vddsf + nddsf, W m**-2",
            "direct_radiation": "max(dswsfc - (vddsf + nddsf), 0), W m**-2",
            "cloud_cover": "tcdcclm total cloud cover, percent",
            "chosen_before_outcome_join": True,
            "no_direct_or_diffuse_field_fabrication": True,
        },
        "feature_contract": {
            "family": "radiation",
            "columns": [
                "shortwave_sum",
                "shortwave_max",
                "direct_sum",
                "diffuse_sum",
                "direct_fraction",
                "cloud_cover_mean",
                "cloud_cover_max",
            ],
            "ridge_alpha": DEFAULT_RIDGE_ALPHA,
            "chosen_before_outcome_join": True,
        },
        "evaluation_contract": {
            "split": plan,
            "folds": DEFAULT_FOLDS,
            "holdout_fraction": DEFAULT_HOLDOUT_FRACTION,
            "bootstrap_replicates": DEFAULT_BOOTSTRAP_REPLICATES,
            "bootstrap_seed": DEFAULT_BOOTSTRAP_SEED,
            "acceptance": (
                "primary holdout MAE delta point and entire fleet-date clustered "
                "95% interval below zero; otherwise STOP"
            ),
        },
        "availability_records": records,
        "coverage_by_year": coverage,
        "frozen_before_grib_decode": True,
        "frozen_before_outcome_join": True,
        "frozen_before_model_fit_or_score": True,
    }
    canonical = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    payload = {
        **frozen,
        "generated_at_utc": utc_iso(),
        "contract_sha256": sha256_bytes(canonical),
        "target_date_count": len(target_dates),
        "candidate_date_count": len(candidate_dates),
        "complete_date_count": len(complete),
        "missing_date_count": len(candidate_dates) - len(complete),
    }
    validate_design_contract(payload, upstream_contract_path=upstream_path)
    path = output_path
    write_json_atomic(path, payload)
    return payload


def decode_selected_range(
    path: str | Path,
    *,
    variable: RadiationVariable,
    target_date: date,
    specs: Sequence[MarketSpec],
    eccodes,
    issue_time: datetime,
    expected_messages: Sequence[InventoryMessage],
    station_grid_lookup: Mapping[str, Mapping[str, float | int]] | None = None,
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    issue = _aware_utc(issue_time, label="issue_time")
    output: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    steps = []
    valid_times = []
    grids = []
    max_distance = 0.0
    with Path(path).open("rb") as source:
        while True:
            handle = eccodes.codes_grib_new_from_file(source)
            if handle is None:
                break
            try:
                actual = {
                    "short_name": str(eccodes.codes_get(handle, "shortName")),
                    "units": str(eccodes.codes_get(handle, "units")),
                    "type_of_level": str(eccodes.codes_get(handle, "typeOfLevel")),
                    "level": int(eccodes.codes_get(handle, "level")),
                    "discipline": int(eccodes.codes_get(handle, "discipline")),
                    "parameter_category": int(eccodes.codes_get(handle, "parameterCategory")),
                    "parameter_number": int(eccodes.codes_get(handle, "parameterNumber")),
                    "step_type": str(eccodes.codes_get(handle, "stepType")),
                    "pdt": int(eccodes.codes_get(handle, "productDefinitionTemplateNumber")),
                }
                expected = {
                    "short_name": variable.short_name,
                    "units": variable.units,
                    "type_of_level": variable.type_of_level,
                    "level": variable.level,
                    "discipline": 0,
                    "parameter_category": variable.parameter_category,
                    "parameter_number": variable.parameter_number,
                    "step_type": "instant",
                    "pdt": 0,
                }
                if actual != expected:
                    raise ValueError(
                        f"unexpected CFSv2 {variable.archive_name} GRIB contract: {actual}"
                    )
                grid = {
                    "grid_type": str(eccodes.codes_get(handle, "gridType")),
                    "nx": int(eccodes.codes_get(handle, "Ni")),
                    "ny": int(eccodes.codes_get(handle, "Nj")),
                }
                if grid != {"grid_type": GRID_TYPE, "nx": GRID_X_POINTS, "ny": GRID_Y_POINTS}:
                    raise ValueError(f"unexpected CFSv2 radiation grid: {grid}")
                grids.append(grid)
                if _grib_reference_time(eccodes, handle) != issue:
                    raise ValueError("CFSv2 radiation GRIB cycle mismatch")
                step = int(eccodes.codes_get(handle, "forecastTime"))
                valid = _grib_valid_time(eccodes, handle)
                steps.append(step)
                valid_times.append(valid.isoformat())
                if station_grid_lookup is None:
                    nearest_points = eccodes.codes_grib_find_nearest_multiple(
                        handle,
                        False,
                        [float(spec.lat) for spec in specs],
                        [float(spec.lon) for spec in specs],
                    )
                    if len(nearest_points) != len(specs):
                        raise ValueError(
                            "CFSv2 radiation nearest-grid lookup returned the wrong count"
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
                    raise ValueError("CFSv2 radiation station-grid lookup has wrong markets")
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
                    raise ValueError("CFSv2 radiation indexed value count mismatch")
                for spec, selected_value in zip(eligible_specs, selected_values):
                    local = valid.astimezone(spec.tz)
                    lookup = station_grid_lookup[spec.id]
                    value = float(selected_value)
                    distance = float(lookup["distance_km"])
                    grid_lat = float(lookup["grid_lat"])
                    grid_lon = float(lookup["grid_lon"])
                    if not math.isfinite(value) or not variable.minimum <= value <= variable.maximum:
                        raise ValueError(
                            f"implausible CFSv2 {variable.archive_name} value: {value}"
                        )
                    if not all(math.isfinite(item) for item in (distance, grid_lat, grid_lon)):
                        raise ValueError("invalid CFSv2 radiation nearest-grid metadata")
                    max_distance = max(max_distance, distance)
                    output[spec.id][local.isoformat()] = {
                        variable.decoded_key: value,
                        "grid_lat": grid_lat,
                        "grid_lon": grid_lon,
                        "distance_km": distance,
                    }
            finally:
                eccodes.codes_release(handle)
    expected_steps = [item.step_hours for item in expected_messages]
    expected_valid = [(issue + timedelta(hours=step)).isoformat() for step in expected_steps]
    if steps != expected_steps or valid_times != expected_valid:
        raise ValueError("decoded CFSv2 radiation times differ from exact inventory span")
    for spec in specs:
        if len(output.get(spec.id) or {}) != EXPECTED_LOCAL_SAMPLES:
            raise ValueError(
                f"CFSv2 {variable.archive_name} produced the wrong local sample count for {spec.id}"
            )
    return {key: dict(value) for key, value in output.items()}, {
        "variable": variable.archive_name,
        "decoded_messages": len(steps),
        "forecast_steps_hours": steps,
        "valid_times_utc": valid_times,
        "grid": grids[0] if grids else None,
        "station_grid_lookup": station_grid_lookup,
        "max_nearest_grid_distance_km": max_distance,
        "market_value_count": sum(len(item) for item in output.values()),
    }


def derive_radiation_components(
    decoded: Mapping[str, Mapping[str, Mapping[str, Mapping[str, float]]]],
    specs: Sequence[MarketSpec],
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    merged: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    clamp_count = 0
    min_unclamped_direct = math.inf
    for spec in specs:
        variable_rows = {
            name: (decoded.get(name) or {}).get(spec.id) or {}
            for name in VARIABLE_BY_NAME
        }
        valid_sets = {tuple(sorted(rows)) for rows in variable_rows.values()}
        if len(valid_sets) != 1:
            raise ValueError(f"CFSv2 radiation valid-time pairing differs for {spec.id}")
        for valid_time in next(iter(valid_sets), ()):
            items = [variable_rows[name][valid_time] for name in VARIABLE_BY_NAME]
            first = items[0]
            if any(
                not math.isclose(float(item["grid_lat"]), float(first["grid_lat"]), abs_tol=1e-9)
                or not math.isclose(float(item["grid_lon"]), float(first["grid_lon"]), abs_tol=1e-9)
                for item in items[1:]
            ):
                raise ValueError(f"CFSv2 radiation fields selected different cells for {spec.id}")
            total = float(variable_rows["dswsfc"][valid_time]["total_shortwave_w_m2"])
            visible = float(variable_rows["vddsf"][valid_time]["visible_diffuse_w_m2"])
            near_ir = float(variable_rows["nddsf"][valid_time]["near_ir_diffuse_w_m2"])
            cloud = float(variable_rows["tcdcclm"][valid_time]["total_cloud_percent"])
            diffuse = visible + near_ir
            unclamped_direct = total - diffuse
            min_unclamped_direct = min(min_unclamped_direct, unclamped_direct)
            if unclamped_direct < 0.0:
                clamp_count += 1
            merged[spec.id][valid_time] = {
                "shortwave_radiation": total,
                "diffuse_radiation": diffuse,
                "direct_radiation": max(unclamped_direct, 0.0),
                "cloud_cover": cloud,
            }
    return {key: dict(value) for key, value in merged.items()}, {
        "direct_zero_clamp_count": clamp_count,
        "minimum_unclamped_direct_w_m2": (
            None if min_unclamped_direct is math.inf else min_unclamped_direct
        ),
    }


def _selected_baselines(
    source_root: Path,
    specs: Sequence[MarketSpec],
    cutoff_local: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    selected = {}
    audits = []
    for spec in specs:
        rows, audit, _ = load_market_rows(
            data_root=source_root,
            spec=spec,
            family="radiation",
            cutoff_local=cutoff_local,
        )
        selected[spec.id] = rows
        for provenance in audit.get("provenance", {}).values():
            provenance["sha256"] = sha256_file(provenance["path"])
        audits.append(audit)
    return selected, audits


def enrich_selected_rows(
    source_forecast_path: str | Path,
    *,
    spec: MarketSpec,
    selected_rows: Sequence[Mapping[str, Any]],
    values_by_date: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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
    paired_by_date = Counter()
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
            target_text = str(row.get("target_date") or "")
            valid_time = str(row.get("valid_time") or "")
            item = (values_by_date.get(target_text) or {}).get(valid_time) or {}
            values = {
                field: to_float(item.get(field))
                for field in (
                    "shortwave_radiation",
                    "direct_radiation",
                    "diffuse_radiation",
                    "cloud_cover",
                )
            }
            present = [value is not None for value in values.values()]
            if any(present) and not all(present):
                raise ValueError("CFSv2 radiation adapter encountered an unpaired row")
            for field, value in values.items():
                row[field] = "" if value is None else value
            for field in ("low_cloud", "mid_cloud", "high_cloud"):
                row[field] = ""
            if all(present):
                paired_by_date[target_text] += 1
            row["payload_hash"] = forecast_payload_hash(row)
            output.append(row)
    invalid = {
        target_text: count
        for target_text, count in paired_by_date.items()
        if count != EXPECTED_LOCAL_SAMPLES
    }
    if invalid:
        raise ValueError(f"CFSv2 radiation adapter local sample mismatch: {invalid}")
    output.sort(key=lambda row: (str(row.get("target_date")), str(row.get("valid_time"))))
    return output, {
        "selected_market_dates": len(selected_keys),
        "supported_market_dates": len(paired_by_date),
        "derived_rows": len(output),
        "paired_nonnull_rows": sum(paired_by_date.values()),
        "expected_samples_per_supported_date": EXPECTED_LOCAL_SAMPLES,
    }


def _acquire_variable(
    *,
    output_root: Path,
    target_text: str,
    variable: RadiationVariable,
    specs: Sequence[MarketSpec],
    timeout_seconds: float,
    attempts: int,
    request_get: Callable[..., Any],
    sleep_fn: Callable[[float], None],
) -> dict[str, Any]:
    target = date.fromisoformat(target_text)
    issue = feature_issue_time(target)
    issue_text = issue.strftime("%Y%m%d%H")
    issue_root = output_root / "raw" / issue_text
    grib_url, inventory_url = archive_urls(variable, issue)
    inventory_path = issue_root / f"{variable.archive_name}.{MEMBER}.{issue_text}.daily.inv"
    inventory_bytes, inventory_record, fetched_inventory = fetch_or_load(
        path=inventory_path,
        url=inventory_url,
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        request_get=request_get,
        sleep_fn=sleep_fn,
    )
    messages = parse_inventory(
        inventory_bytes.decode("utf-8"),
        variable=variable,
        expected_issue_time=issue,
    )
    selected, start, end = selected_inventory_span(
        messages,
        target_date=target,
        issue_time=issue,
        specs=specs,
    )
    range_path = issue_root / (
        f"{variable.archive_name}.{MEMBER}.{issue_text}.f"
        f"{selected[0].step_hours:04d}-f{selected[-1].step_hours:04d}.grb2"
    )
    _, range_record, fetched_range = fetch_or_load(
        path=range_path,
        url=grib_url,
        byte_range=(start, end),
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        request_get=request_get,
        sleep_fn=sleep_fn,
    )
    return {
        "target_date": target_text,
        "issue_time": issue,
        "variable": variable,
        "inventory_url": inventory_url,
        "grib_url": grib_url,
        "inventory_record": inventory_record,
        "range_record": range_record,
        "range_path": range_path,
        "messages": selected,
        "range_start": start,
        "range_end": end,
        "network_used": fetched_inventory or fetched_range,
    }


def build_scratch_backfill(
    *,
    source_data_root: str | Path,
    output_root: str | Path,
    upstream_contract_path: str | Path,
    eccodes_path: str | Path | None,
    cutoff_local: str = "00:00",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    workers: int = DEFAULT_WORKERS,
    specs: Sequence[MarketSpec] = BUILTIN_SPECS,
    request_get: Callable[..., Any] = requests.get,
    request_head: Callable[..., Any] = requests.head,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    source_root, paths = resolve_paths_outside_read_only_root(
        read_only_root=source_data_root,
        paths={
            "output_root": output_root,
            "raw_root": Path(output_root) / "raw",
            "derived_root": Path(output_root) / "derived_data",
            "design": Path(output_root) / "design_contract.json",
        },
    )
    output_root = paths["output_root"]
    upstream_contract_path = Path(upstream_contract_path).resolve(strict=True)
    _reject_upstream_output_collisions(
        upstream_contract_path,
        _known_generated_output_paths(output_root, target_dates=(), specs=specs),
    )
    upstream_contract = json.loads(upstream_contract_path.read_text(encoding="utf-8"))
    validate_soil_availability_contract(upstream_contract)
    _reject_upstream_output_collisions(
        upstream_contract_path,
        _known_generated_output_paths(
            output_root,
            target_dates=upstream_contract["complete_pair_target_dates"],
            specs=specs,
        ),
    )
    if paths["design"].exists():
        design = json.loads(paths["design"].read_text(encoding="utf-8"))
    else:
        design = freeze_design_contract(
            upstream_contract_path=upstream_contract_path,
            output_path=paths["design"],
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            workers=workers,
            request_head=request_head,
            sleep_fn=sleep_fn,
        )
    validate_design_contract(design, upstream_contract_path=upstream_contract_path)

    complete_dates = list(design["complete_target_dates"])
    acquired: dict[tuple[str, str], dict[str, Any]] = {}
    acquire_errors = []
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        futures = {
            executor.submit(
                _acquire_variable,
                output_root=output_root,
                target_text=target_text,
                variable=variable,
                specs=specs,
                timeout_seconds=timeout_seconds,
                attempts=attempts,
                request_get=request_get,
                sleep_fn=sleep_fn,
            ): (target_text, variable.archive_name)
            for target_text in complete_dates
            for variable in RADIATION_VARIABLES
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                acquired[key] = future.result()
            except Exception as exc:  # noqa: BLE001 - exact acquisition blocker
                acquire_errors.append(
                    {
                        "target_date": key[0],
                        "variable": key[1],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )

    eccodes = load_eccodes(eccodes_path)
    issue_records = []
    errors = list(acquire_errors)
    values: dict[str, dict[str, dict[str, dict[str, float]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    request_records = []
    network_used = False
    total_clamps = 0
    minimum_unclamped = math.inf
    station_grid_lookup = None
    for target_text in complete_dates:
        target = date.fromisoformat(target_text)
        issue = feature_issue_time(target)
        assert_cutoff_safe(target, issue, specs, cutoff_local=cutoff_local)
        if any((target_text, item.archive_name) not in acquired for item in RADIATION_VARIABLES):
            continue
        decoded = {}
        variable_records = []
        try:
            for variable in RADIATION_VARIABLES:
                record = acquired[(target_text, variable.archive_name)]
                inventory_index = len(request_records)
                request_records.append(record["inventory_record"])
                range_index = len(request_records)
                request_records.append(record["range_record"])
                network_used = network_used or bool(record["network_used"])
                decoded_values, decode_audit = decode_selected_range(
                    record["range_path"],
                    variable=variable,
                    target_date=target,
                    specs=specs,
                    eccodes=eccodes,
                    issue_time=issue,
                    expected_messages=record["messages"],
                    station_grid_lookup=station_grid_lookup,
                )
                if station_grid_lookup is None:
                    station_grid_lookup = decode_audit["station_grid_lookup"]
                decoded[variable.archive_name] = decoded_values
                variable_records.append(
                    {
                        "variable": variable.archive_name,
                        "inventory_url": record["inventory_url"],
                        "grib_url": record["grib_url"],
                        "selected_steps_hours": [item.step_hours for item in record["messages"]],
                        "range_start": record["range_start"],
                        "range_end": record["range_end"],
                        "inventory_request_index": inventory_index,
                        "range_request_index": range_index,
                        "decode": decode_audit,
                    }
                )
            steps = {tuple(item["selected_steps_hours"]) for item in variable_records}
            valid_times = {tuple(item["decode"]["valid_times_utc"]) for item in variable_records}
            if len(steps) != 1 or len(valid_times) != 1:
                raise ValueError("CFSv2 radiation fields decoded different time contracts")
            merged, arithmetic_audit = derive_radiation_components(decoded, specs)
            total_clamps += int(arithmetic_audit["direct_zero_clamp_count"])
            if arithmetic_audit["minimum_unclamped_direct_w_m2"] is not None:
                minimum_unclamped = min(
                    minimum_unclamped,
                    float(arithmetic_audit["minimum_unclamped_direct_w_m2"]),
                )
            for market_id, market_values in merged.items():
                values[market_id][target_text].update(market_values)
            issue_records.append(
                {
                    "target_date": target_text,
                    "issue_time_utc": issue.isoformat(),
                    "buffered_available_time_utc": buffered_available_time(issue).isoformat(),
                    "variables": variable_records,
                    "arithmetic_audit": arithmetic_audit,
                }
            )
        except Exception as exc:  # noqa: BLE001 - exact decode blocker
            errors.append(
                {
                    "target_date": target_text,
                    "variable": None,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    # Outcomes and settlements are first read only after the design and exact
    # predictor acquisition/decoding are frozen and complete.
    selected, baseline_audit = _selected_baselines(source_root, specs, cutoff_local)
    source_inputs = [
        {"market_id": audit["market_id"], "role": role, **provenance}
        for audit in baseline_audit
        for role, provenance in audit.get("provenance", {}).items()
    ]
    derived_markets = []
    for spec in specs:
        source_forecast, source_settlement = source_paths(source_root, spec)
        rows, coverage = enrich_selected_rows(
            source_forecast,
            spec=spec,
            selected_rows=selected[spec.id],
            values_by_date=values.get(spec.id) or {},
        )
        forecast_path = paths["derived_root"] / "forecast_history" / spec.icao.lower() / "forecast_long.csv"
        settlement_path = paths["derived_root"] / "wunderground" / spec.icao.lower() / "daily" / "daily_summary.csv"
        write_csv_rows_atomic(forecast_path, RADIATION_FORECAST_COLUMNS, rows)
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
    source_mirror_mutated = False
    for item in source_inputs:
        item["sha256_after"] = sha256_file(item["path"])
        item["unchanged_during_run"] = item["sha256"] == item["sha256_after"]
        source_mirror_mutated = source_mirror_mutated or not item["unchanged_during_run"]
    if source_mirror_mutated:
        errors.append(
            {
                "target_date": None,
                "variable": None,
                "error_type": "SourceMirrorMutationError",
                "error": "one or more source input hashes changed during the run",
            }
        )
    max_distance = max(
        (
            float(variable["decode"]["max_nearest_grid_distance_km"])
            for issue in issue_records
            for variable in issue["variables"]
        ),
        default=None,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "research_only": True,
        "source_contract_sensitivity": True,
        "independent_outcome_confirmation": False,
        "code": {
            "module": "weather.reporting.research.cfsv2_radiation_research",
            "path": str(Path(__file__).resolve(strict=True)),
            "sha256": sha256_file(__file__),
        },
        "source_data_root": str(source_root),
        "output_root": str(output_root),
        "derived_data_root": str(paths["derived_root"]),
        "design_contract_path": str(paths["design"]),
        "design_contract_file_sha256": sha256_file(paths["design"]),
        "design": design,
        "request_count": len(request_records),
        "requests": request_records,
        "network_used": network_used,
        "issue_count": len(issue_records),
        "issues": issue_records,
        "error_count": len(errors),
        "errors": errors,
        "max_nearest_grid_distance_km": max_distance,
        "arithmetic_audit": {
            "direct_zero_clamp_count": total_clamps,
            "minimum_unclamped_direct_w_m2": (
                None if minimum_unclamped is math.inf else minimum_unclamped
            ),
        },
        "baseline_audit": baseline_audit,
        "source_input_count": len(source_inputs),
        "source_inputs": source_inputs,
        "markets": derived_markets,
        "supported_market_dates": sum(item["supported_market_dates"] for item in derived_markets),
        "source_mirror_mutated": source_mirror_mutated,
        "serving_or_collector_contract_changed": False,
    }


def _audit_quantiles(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("cannot audit an empty CFSv2 radiation series")
    output = {}
    for percentile in (0, 1, 5, 25, 50, 75, 95, 99, 100):
        position = (len(ordered) - 1) * percentile / 100.0
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        fraction = position - lower
        output[f"p{percentile:03d}"] = float(
            ordered[lower]
            if lower == upper
            else ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
        )
    return output


def write_predictor_integrity_audit(
    *,
    manifest_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Hash every input/output and audit only predictor columns before scoring."""

    manifest_path = Path(manifest_path).resolve(strict=True)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches = []

    def verify(record: Mapping[str, Any], label: str) -> None:
        path = Path(str(record["path"]))
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            mismatches.append(f"{label}:missing")
            return
        if record.get("size_bytes") is not None and path.stat().st_size != int(record["size_bytes"]):
            mismatches.append(f"{label}:size")
        if record.get("sha256") and sha256_file(path) != record["sha256"]:
            mismatches.append(f"{label}:sha256")

    for index, record in enumerate(payload["requests"]):
        verify(record, f"request[{index}]")
    for index, record in enumerate(payload["source_inputs"]):
        verify(record, f"source_input[{index}]")
        if not record.get("unchanged_during_run") or record.get("sha256") != record.get("sha256_after"):
            mismatches.append(f"source_input[{index}]:changed")
    if sha256_file(payload["design_contract_path"]) != payload["design_contract_file_sha256"]:
        mismatches.append("design_contract:sha256")
    if sha256_file(payload["code"]["path"]) != payload["code"]["sha256"]:
        mismatches.append("research_module:sha256")

    fields = {
        field: []
        for field in (
            "shortwave_radiation",
            "direct_radiation",
            "diffuse_radiation",
            "cloud_cover",
        )
    }
    sample_counts = Counter()
    clamp_count = 0
    minimum_unclamped = math.inf
    for market in payload["markets"]:
        for role in ("forecast", "settlement"):
            if sha256_file(market[f"{role}_path"]) != market[f"{role}_sha256"]:
                mismatches.append(f"market:{market['market_id']}:{role}:sha256")
        with Path(market["forecast_path"]).open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            reader = csv.reader(handle)
            header = next(reader)
            indices = {
                name: header.index(name)
                for name in ("target_date", *fields)
            }
            for row in reader:
                raw = {field: row[indices[field]].strip() for field in fields}
                if not any(raw.values()):
                    continue
                if not all(raw.values()):
                    mismatches.append(f"market:{market['market_id']}:unpaired")
                    continue
                values = {field: float(value) for field, value in raw.items()}
                if any(not math.isfinite(value) for value in values.values()):
                    mismatches.append(f"market:{market['market_id']}:nonfinite")
                    continue
                if (
                    values["shortwave_radiation"] < 0.0
                    or values["direct_radiation"] < 0.0
                    or values["diffuse_radiation"] < 0.0
                    or not 0.0 <= values["cloud_cover"] <= 100.0
                ):
                    mismatches.append(f"market:{market['market_id']}:bounds")
                    continue
                unclamped = values["shortwave_radiation"] - values["diffuse_radiation"]
                expected_direct = max(unclamped, 0.0)
                if not math.isclose(
                    values["direct_radiation"], expected_direct, abs_tol=1e-9
                ):
                    mismatches.append(f"market:{market['market_id']}:arithmetic")
                if unclamped < 0.0:
                    clamp_count += 1
                minimum_unclamped = min(minimum_unclamped, unclamped)
                for field, value in values.items():
                    fields[field].append(value)
                sample_counts[(market["market_id"], row[indices["target_date"]])] += 1
    invalid_counts = {
        f"{market_id}:{target_date}": count
        for (market_id, target_date), count in sample_counts.items()
        if count != EXPECTED_LOCAL_SAMPLES
    }
    if invalid_counts:
        mismatches.append("derived_predictors:local_sample_counts")
    expected_rows = sum(int(item["paired_nonnull_rows"]) for item in payload["markets"])
    if any(len(values) != expected_rows for values in fields.values()):
        mismatches.append("derived_predictors:paired_row_count")
    if clamp_count != int(payload["arithmetic_audit"]["direct_zero_clamp_count"]):
        mismatches.append("derived_predictors:clamp_count")
    recorded_minimum = payload["arithmetic_audit"]["minimum_unclamped_direct_w_m2"]
    if not math.isclose(minimum_unclamped, float(recorded_minimum), abs_tol=1e-9):
        mismatches.append("derived_predictors:minimum_unclamped")

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
        "inventory_request_count": sum(
            str(item["path"]).lower().endswith(".inv") for item in payload["requests"]
        ),
        "grib_range_request_count": sum(
            str(item["path"]).lower().endswith(".grb2") for item in payload["requests"]
        ),
        "source_input_count": len(payload["source_inputs"]),
        "derived_market_date_count": len(sample_counts),
        "derived_predictor_row_count": expected_rows,
        "invalid_sample_counts": invalid_counts,
        "direct_zero_clamp_count": clamp_count,
        "minimum_unclamped_direct_w_m2": minimum_unclamped,
        "fields": {
            field: {
                "count": len(values),
                "finite_count": sum(math.isfinite(value) for value in values),
                "negative_count": sum(value < 0.0 for value in values),
                "zero_count": sum(value == 0.0 for value in values),
                "quantiles": _audit_quantiles(values),
            }
            for field, values in fields.items()
        },
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "status": "PASS" if not mismatches else "FAIL",
    }
    write_json_atomic(output_path, result)
    if mismatches:
        raise ValueError(f"CFSv2 radiation integrity audit failed: {mismatches[:5]}")
    return result


def write_manifest_report(path: str | Path, payload: Mapping[str, Any]) -> Path:
    design = payload["design"]
    lines = [
        "# Scratch NOAA CFSv2 Radiation Source-contract Sensitivity",
        "",
        f"Generated: {payload['generated_at_utc']}",
        f"Schema: `{payload['schema_version']}`",
        "",
        "This shares outcomes/dates with earlier families; it is an independent issue-time provider contract, not independent outcome confirmation.",
        "",
        "The exact predeclared arithmetic is total=DSWRF, diffuse=VDDSF+NDDSF, direct=max(total-diffuse,0), cloud=TCDC.",
        "",
        "## Frozen Design",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Issue/member", "target-2 UTC days 18Z / member01"],
            ["Candidate dates", design["candidate_date_count"]],
            ["Exact four-field dates", design["complete_date_count"]],
            ["Decoded dates", payload["issue_count"]],
            ["Errors", payload["error_count"]],
            ["Supported market-dates", payload["supported_market_dates"]],
            ["Direct clamps", payload["arithmetic_audit"]["direct_zero_clamp_count"]],
            ["Design SHA-256", design["contract_sha256"]],
        ],
    )
    lines += ["", "## Coverage by Year", ""]
    lines += markdown_table(
        ["Year", "Candidates", "Complete", "Missing"],
        [
            [item["year"], item["candidate_dates"], item["complete_dates"], item["missing_dates"]]
            for item in design["coverage_by_year"]
        ],
    )
    return write_text_atomic(path, "\n".join(lines) + "\n")


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
        upstream_contract_path=args.upstream_contract,
        eccodes_path=args.eccodes_path,
        cutoff_local=args.cutoff_local,
        timeout_seconds=args.timeout_seconds,
        attempts=args.attempts,
        workers=args.workers,
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
        description="Backfill exact NOAA CFSv2 radiation fields into a scratch Tmax corpus."
    )
    parser.add_argument("--source-data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--upstream-contract", required=True)
    parser.add_argument("--eccodes-path", required=True)
    parser.add_argument("--cutoff-local", default="00:00")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(
        f"CFSv2 radiation backfill: {payload['issue_count']}/"
        f"{payload['design']['complete_date_count']} exact issues, "
        f"{payload['supported_market_dates']} supported market-dates, "
        f"{payload['error_count']} errors"
    )
    return 0 if payload["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
