"""Scratch-only NOAA CFSv2 0--0.1 m soil backfill for Tmax research.

The acquisition contract is fixed before model evaluation: target-minus-two UTC
calendar days at 18Z, control member 01, and every six-hour valid time falling
on a built-in market's local target day.  A complete-pair availability cohort
for ``soilt1`` and ``soilm1`` is written before any GRIB message is decoded.

The repository's historical forecast schema names its reusable research fields
``soil_temperature_0cm`` and ``soil_moisture_0_to_1cm``.  In this scratch
adapter only, those columns carry the CFSv2 *0--0.1 m layer* temperature and
volumetric moisture.  The physical depth contract is validated from GRIB keys
and recorded explicitly; no serving or collector contract is changed.
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
from datetime import date, datetime, timedelta, timezone
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
    fetch_or_load,
    feature_issue_time,
    load_eccodes,
    selected_inventory_span,
    sha256_bytes,
    sha256_file,
    source_paths,
    utc_iso,
)
from weather.reporting.research.offline_tmax_predictor_evaluation import (
    load_market_rows,
    resolve_paths_outside_read_only_root,
)
from weather.schema_registry import schema_version
from weather.sources.forecast_history import (
    RICH_FORECAST_COLUMNS,
    forecast_payload_hash,
)
from weather.units import c_to_native, to_float


SCHEMA_VERSION = schema_version("cfsv2_soil_research")
AVAILABILITY_SCHEMA_VERSION = schema_version(
    "cfsv2_soil_availability_contract"
)
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_ATTEMPTS = 4
DEFAULT_PAUSE_SECONDS = 0.05
DEFAULT_AVAILABILITY_WORKERS = 12
GRID_TYPE = "regular_gg"
GRID_LONGITUDE_POINTS = 384
GRID_LATITUDE_POINTS = 190
DEPTH_LEVEL_TYPE = "depthBelowLandLayer"
DEPTH_TOP_METERS = 0.0
DEPTH_BOTTOM_METERS = 0.1


@dataclass(frozen=True)
class SoilVariable:
    archive_name: str
    inventory_name: str
    short_name: str
    units: str
    decoded_key: str
    legacy_column: str


SOIL_VARIABLES = (
    SoilVariable(
        archive_name="soilt1",
        inventory_name="TMP",
        short_name="t",
        units="K",
        decoded_key="soil_temperature_c",
        legacy_column="soil_temperature_0cm",
    ),
    SoilVariable(
        archive_name="soilm1",
        inventory_name="SOILW",
        short_name="soilw",
        units="Proportion",
        decoded_key="soil_moisture_proportion",
        legacy_column="soil_moisture_0_to_1cm",
    ),
)


def archive_urls(variable: SoilVariable, issue_time: datetime) -> tuple[str, str]:
    issue = _aware_utc(issue_time, label="issue_time")
    issue_text = issue.strftime("%Y%m%d%H")
    root = f"{BASE_URL}/{issue:%Y}/{issue:%Y%m}/{issue:%Y%m%d}/{issue_text}"
    stem = f"{variable.archive_name}.{MEMBER}.{issue_text}.daily"
    return f"{root}/{stem}.grb2", f"{root}/{stem}.inv"


def parse_inventory(
    text: str,
    *,
    variable: SoilVariable,
    expected_issue_time: datetime | None = None,
) -> list[InventoryMessage]:
    pattern = re.compile(
        r"^(?P<message>\d+):(?P<offset>\d+):d=(?P<issue>\d{10}):"
        + re.escape(variable.inventory_name)
        + r":0-0\.1 m below ground:(?P<step>\d+) hour fcst:"
    )
    messages = []
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if match is None:
            continue
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
            f"CFSv2 {variable.archive_name} inventory contained no exact "
            "0-0.1 m forecast messages"
        )
    if [item.message for item in messages] != list(range(1, len(messages) + 1)):
        raise ValueError("CFSv2 soil inventory message numbers are not contiguous from one")
    if any(right.offset <= left.offset for left, right in zip(messages, messages[1:])):
        raise ValueError("CFSv2 soil inventory offsets are not strictly increasing")
    issue_texts = {item.issue_text for item in messages}
    if len(issue_texts) != 1:
        raise ValueError("CFSv2 soil inventory contains mixed nominal issue cycles")
    try:
        datetime.strptime(messages[0].issue_text, "%Y%m%d%H")
    except ValueError as exc:
        raise ValueError("CFSv2 soil inventory contains an invalid nominal issue cycle") from exc
    if expected_issue_time is not None:
        expected = _aware_utc(
            expected_issue_time, label="expected_issue_time"
        ).strftime("%Y%m%d%H")
        if messages[0].issue_text != expected:
            raise ValueError(
                "CFSv2 soil inventory nominal issue cycle does not match the "
                f"requested cycle: expected={expected}, got={messages[0].issue_text}"
            )
    steps = [item.step_hours for item in messages]
    if any(step <= 0 or step % 6 for step in steps):
        raise ValueError("CFSv2 soil inventory steps are not positive 6-hour steps")
    if any(right <= left for left, right in zip(steps, steps[1:])):
        raise ValueError("CFSv2 soil inventory forecast steps are not strictly increasing")
    return messages


def _probe_inventory(
    *,
    target_text: str,
    variable: SoilVariable,
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
            response = request_head(
                url,
                timeout=timeout_seconds,
                allow_redirects=True,
            )
            status = int(response.status_code)
            if status < 500 and status != 429:
                break
        except Exception as exc:  # noqa: BLE001 - captured in frozen support audit
            error = f"{type(exc).__name__}: {exc}"
        if attempt + 1 < max(1, int(attempts)):
            sleep_fn(min(4.0, 0.5 * (2**attempt)))
    if response is None:
        return {
            "target_date": target_text,
            "issue_time_utc": issue.isoformat(),
            "variable": variable.archive_name,
            "inventory_url": url,
            "status_code": None,
            "content_length": None,
            "etag": None,
            "last_modified": None,
            "error": error or "inventory probe produced no response",
        }
    return {
        "target_date": target_text,
        "issue_time_utc": issue.isoformat(),
        "variable": variable.archive_name,
        "inventory_url": url,
        "status_code": int(response.status_code),
        "content_length": response.headers.get("Content-Length"),
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "error": error,
    }


def freeze_availability_contract(
    *,
    target_dates: Sequence[str],
    output_path: str | Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    workers: int = DEFAULT_AVAILABILITY_WORKERS,
    request_head: Callable[..., Any] = requests.head,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Freeze exact complete-pair support before GRIB decoding or scoring."""

    tasks = [
        (target_text, variable)
        for target_text in sorted(set(target_dates))
        for variable in SOIL_VARIABLES
    ]
    records = []
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        futures = {
            executor.submit(
                _probe_inventory,
                target_text=target_text,
                variable=variable,
                timeout_seconds=timeout_seconds,
                attempts=attempts,
                request_head=request_head,
                sleep_fn=sleep_fn,
            ): (target_text, variable.archive_name)
            for target_text, variable in tasks
        }
        for future in as_completed(futures):
            records.append(future.result())
    records.sort(key=lambda item: (item["target_date"], item["variable"]))
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_target[record["target_date"]].append(record)
    complete = [
        target_text
        for target_text in sorted(by_target)
        if {item["variable"] for item in by_target[target_text]} == {
            item.archive_name for item in SOIL_VARIABLES
        }
        and all(item["status_code"] == 200 for item in by_target[target_text])
    ]
    coverage_by_year = []
    target_years = Counter(item[:4] for item in target_dates)
    complete_years = Counter(item[:4] for item in complete)
    for year in sorted(target_years):
        coverage_by_year.append(
            {
                "year": int(year),
                "target_dates": target_years[year],
                "complete_pair_dates": complete_years[year],
                "missing_pair_dates": target_years[year] - complete_years[year],
            }
        )
    frozen = {
        "schema_version": AVAILABILITY_SCHEMA_VERSION,
        "selection_basis": (
            "HTTP inventory existence for both exact fields under one uniform "
            "cycle/member rule; no residuals, settlements, or model scores used"
        ),
        "issue_rule": "target minus two UTC calendar days at 18Z",
        "member": MEMBER,
        "variables": [item.archive_name for item in SOIL_VARIABLES],
        "physical_depth_m": [DEPTH_TOP_METERS, DEPTH_BOTTOM_METERS],
        "target_dates": sorted(set(target_dates)),
        "complete_pair_target_dates": complete,
        "records": records,
    }
    canonical = json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode()
    payload = {
        **frozen,
        "generated_at_utc": utc_iso(),
        "contract_sha256": sha256_bytes(canonical),
        "target_date_count": len(set(target_dates)),
        "complete_pair_date_count": len(complete),
        "missing_pair_date_count": len(set(target_dates)) - len(complete),
        "coverage_by_year": coverage_by_year,
        "frozen_before_grib_decode": True,
    }
    write_json_atomic(output_path, payload)
    return payload


def _scaled_surface_meters(eccodes, handle: int, which: str) -> float:
    scaled = float(eccodes.codes_get(handle, f"scaledValueOf{which}FixedSurface"))
    factor = int(eccodes.codes_get(handle, f"scaleFactorOf{which}FixedSurface"))
    return scaled * (10.0 ** (-factor))


def decode_selected_range(
    path: str | Path,
    *,
    variable: SoilVariable,
    target_date: date,
    specs: Sequence[MarketSpec],
    eccodes,
    issue_time: datetime,
    expected_messages: Sequence[InventoryMessage],
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    """Decode one bounded variable range under exact time/depth/grid contracts."""

    issue_utc = _aware_utc(issue_time, label="issue_time")
    output: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    forecast_steps: list[int] = []
    valid_times: list[str] = []
    reference_times: list[str] = []
    grid_records = []
    max_distance = 0.0
    with Path(path).open("rb") as source:
        while True:
            handle = eccodes.codes_grib_new_from_file(source)
            if handle is None:
                break
            try:
                if str(eccodes.codes_get(handle, "shortName")) != variable.short_name:
                    raise ValueError(f"unexpected CFSv2 {variable.archive_name} shortName")
                if str(eccodes.codes_get(handle, "units")) != variable.units:
                    raise ValueError(f"unexpected CFSv2 {variable.archive_name} unit")
                if str(eccodes.codes_get(handle, "typeOfLevel")) != DEPTH_LEVEL_TYPE:
                    raise ValueError("unexpected CFSv2 soil level type")
                depth_top = _scaled_surface_meters(eccodes, handle, "First")
                depth_bottom = _scaled_surface_meters(eccodes, handle, "Second")
                if not (
                    math.isclose(depth_top, DEPTH_TOP_METERS, abs_tol=1e-12)
                    and math.isclose(depth_bottom, DEPTH_BOTTOM_METERS, abs_tol=1e-12)
                ):
                    raise ValueError(
                        "unexpected CFSv2 soil depth layer: "
                        f"{depth_top:g}-{depth_bottom:g} m"
                    )
                if str(eccodes.codes_get(handle, "stepType")) != "instant":
                    raise ValueError("unexpected non-instantaneous CFSv2 soil message")
                grid = {
                    "grid_type": str(eccodes.codes_get(handle, "gridType")),
                    "longitude_points": int(eccodes.codes_get(handle, "Ni")),
                    "latitude_points": int(eccodes.codes_get(handle, "Nj")),
                    "longitude_increment_degrees": float(
                        eccodes.codes_get(handle, "iDirectionIncrementInDegrees")
                    ),
                }
                if (
                    grid["grid_type"] != GRID_TYPE
                    or grid["longitude_points"] != GRID_LONGITUDE_POINTS
                    or grid["latitude_points"] != GRID_LATITUDE_POINTS
                    or not math.isfinite(grid["longitude_increment_degrees"])
                    or not 0.8 <= grid["longitude_increment_degrees"] <= 1.1
                ):
                    raise ValueError(f"unexpected CFSv2 soil grid contract: {grid}")
                grid_records.append(grid)
                reference = _grib_reference_time(eccodes, handle)
                if reference != issue_utc:
                    raise ValueError("CFSv2 soil GRIB cycle does not match request")
                step = int(eccodes.codes_get(handle, "forecastTime"))
                valid = _grib_valid_time(eccodes, handle)
                forecast_steps.append(step)
                valid_times.append(valid.isoformat())
                reference_times.append(reference.isoformat())
                for spec in specs:
                    valid_local = valid.astimezone(spec.tz)
                    if valid_local.date() != target_date:
                        continue
                    candidates = sorted(
                        eccodes.codes_grib_find_nearest(
                            handle,
                            float(spec.lat),
                            float(spec.lon),
                            npoints=4,
                        ),
                        key=lambda item: (
                            float(item["distance"]),
                            float(item["lat"]),
                            float(item["lon"]),
                        ),
                    )
                    if variable.archive_name == "soilt1":
                        plausible = [
                            item
                            for item in candidates
                            if math.isfinite(float(item["value"]))
                            and 200.0 <= float(item["value"]) <= 340.0
                        ]
                    else:
                        plausible = [
                            item
                            for item in candidates
                            if math.isfinite(float(item["value"]))
                            and 0.0 <= float(item["value"]) <= 1.0
                        ]
                    if not plausible:
                        value_label = (
                            "soil temperature"
                            if variable.archive_name == "soilt1"
                            else "soil moisture"
                        )
                        raise ValueError(
                            f"no plausible CFSv2 {value_label} value among "
                            "the four bracketing grid cells"
                        )
                    # Soil fields use 9999 over water.  Selecting the closest
                    # valid one of the four bracketing cells is deterministic,
                    # outcome-blind, and keeps coastal cities on a land cell.
                    nearest = plausible[0]
                    value = float(nearest["value"])
                    distance = float(nearest["distance"])
                    grid_lat = float(nearest["lat"])
                    grid_lon = float(nearest["lon"])
                    decoded_value = value - 273.15 if variable.archive_name == "soilt1" else value
                    if (
                        not math.isfinite(distance)
                        or distance < 0
                        or not math.isfinite(grid_lat)
                        or not math.isfinite(grid_lon)
                    ):
                        raise ValueError("invalid CFSv2 soil nearest-grid metadata")
                    max_distance = max(max_distance, distance)
                    output[spec.id][valid_local.isoformat()] = {
                        variable.decoded_key: decoded_value,
                        "grid_lat": grid_lat,
                        "grid_lon": grid_lon,
                        "distance_km": distance,
                    }
            finally:
                eccodes.codes_release(handle)
    expected_steps = [item.step_hours for item in expected_messages]
    expected_valid = [
        (issue_utc + timedelta(hours=step)).isoformat() for step in expected_steps
    ]
    if forecast_steps != expected_steps:
        raise ValueError(
            "decoded CFSv2 soil forecast steps do not match inventory: "
            f"expected={expected_steps}, got={forecast_steps}"
        )
    if valid_times != expected_valid:
        raise ValueError("decoded CFSv2 soil valid times do not match inventory")
    if len({json.dumps(item, sort_keys=True) for item in grid_records}) > 1:
        raise ValueError("decoded CFSv2 soil messages use mixed grids")
    return {key: dict(value) for key, value in output.items()}, {
        "variable": variable.archive_name,
        "decoded_messages": len(forecast_steps),
        "reference_times_utc": reference_times,
        "forecast_steps_hours": forecast_steps,
        "valid_times_utc": valid_times,
        "physical_depth_m": [DEPTH_TOP_METERS, DEPTH_BOTTOM_METERS],
        "grid": grid_records[0] if grid_records else None,
        "first_valid_time_utc": min(valid_times) if valid_times else None,
        "last_valid_time_utc": max(valid_times) if valid_times else None,
        "max_nearest_grid_distance_km": max_distance,
        "market_value_count": sum(len(item) for item in output.values()),
    }


def enrich_selected_rows(
    source_forecast_path: str | Path,
    *,
    spec: MarketSpec,
    selected_rows: Sequence[Mapping[str, Any]],
    values_by_date: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected_unit = str(spec.unit).strip().upper()
    if expected_unit not in {"C", "F"}:
        raise ValueError(f"unsupported native temperature unit for {spec.id}: {spec.unit!r}")
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
    temperature_nonnull = 0
    moisture_nonnull = 0
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
                    "selected forecast row temperature unit does not match its market: "
                    f"market={spec.id}, expected={expected_unit}, got={row_unit or '<blank>'}"
                )
            target_text = str(row.get("target_date") or "")
            valid_time = str(row.get("valid_time") or "")
            item = (values_by_date.get(target_text) or {}).get(valid_time) or {}
            soil_temperature_c = to_float(item.get("soil_temperature_c"))
            soil_moisture = to_float(item.get("soil_moisture_proportion"))
            if (soil_temperature_c is None) != (soil_moisture is None):
                raise ValueError("CFSv2 soil adapter encountered an unpaired field value")
            row["soil_temperature_0cm"] = (
                ""
                if soil_temperature_c is None
                else c_to_native(soil_temperature_c, expected_unit, digits=None)
            )
            row["soil_moisture_0_to_1cm"] = (
                "" if soil_moisture is None else soil_moisture
            )
            if soil_temperature_c is not None:
                temperature_nonnull += 1
                moisture_nonnull += 1
                supported_dates.add(target_text)
            row["payload_hash"] = forecast_payload_hash(row)
            output.append(row)
    output.sort(key=lambda row: (str(row.get("target_date")), str(row.get("valid_time"))))
    return output, {
        "selected_market_dates": len(selected_keys),
        "supported_market_dates": len(supported_dates),
        "derived_rows": len(output),
        "soil_temperature_nonnull_rows": temperature_nonnull,
        "soil_moisture_nonnull_rows": moisture_nonnull,
    }


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
            family="soil",
            cutoff_local=cutoff_local,
        )
        selected_by_market[spec.id] = rows
        for provenance in market_audit.get("provenance", {}).values():
            provenance["sha256"] = sha256_file(provenance["path"])
        audits.append(market_audit)
        target_dates.update(str(row["target_date"]) for row in rows)
    return selected_by_market, sorted(target_dates), audits


def _merge_variable_values(
    decoded_by_variable: Mapping[str, Mapping[str, Mapping[str, Mapping[str, float]]]],
    specs: Sequence[MarketSpec],
) -> dict[str, dict[str, dict[str, float]]]:
    merged: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    temp = decoded_by_variable["soilt1"]
    moisture = decoded_by_variable["soilm1"]
    for spec in specs:
        temp_rows = temp.get(spec.id) or {}
        moisture_rows = moisture.get(spec.id) or {}
        if set(temp_rows) != set(moisture_rows):
            raise ValueError(f"CFSv2 soil valid-time pairing differs for {spec.id}")
        for valid_time in sorted(temp_rows):
            if not (
                math.isclose(
                    float(temp_rows[valid_time]["grid_lat"]),
                    float(moisture_rows[valid_time]["grid_lat"]),
                    abs_tol=1e-9,
                )
                and math.isclose(
                    float(temp_rows[valid_time]["grid_lon"]),
                    float(moisture_rows[valid_time]["grid_lon"]),
                    abs_tol=1e-9,
                )
            ):
                raise ValueError(
                    f"CFSv2 soil variables selected different grid cells for {spec.id}"
                )
            merged[spec.id][valid_time] = {
                "soil_temperature_c": temp_rows[valid_time]["soil_temperature_c"],
                "soil_moisture_proportion": moisture_rows[valid_time][
                    "soil_moisture_proportion"
                ],
            }
    return {key: dict(value) for key, value in merged.items()}


def build_scratch_backfill(
    *,
    source_data_root: str | Path,
    output_root: str | Path,
    eccodes_path: str | Path | None,
    cutoff_local: str = "00:00",
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    availability_workers: int = DEFAULT_AVAILABILITY_WORKERS,
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
            "availability": Path(output_root) / "availability_contract.json",
            "manifest": Path(output_root) / "manifest.json",
        },
    )
    output_root = paths["output_root"]
    selected, target_dates, baseline_audit = _selected_baselines(
        source_root, specs, cutoff_local
    )
    source_inputs = [
        {"market_id": audit["market_id"], "role": role, **provenance}
        for audit in baseline_audit
        for role, provenance in audit.get("provenance", {}).items()
    ]
    availability = freeze_availability_contract(
        target_dates=target_dates,
        output_path=paths["availability"],
        timeout_seconds=timeout_seconds,
        attempts=attempts,
        workers=availability_workers,
        request_head=request_head,
        sleep_fn=sleep_fn,
    )
    decoder = load_eccodes(eccodes_path)
    values: dict[str, dict[str, dict[str, dict[str, float]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    requests_provenance = []
    issue_records = []
    errors = []
    network_used = True
    for target_text in availability["complete_pair_target_dates"]:
        target = date.fromisoformat(target_text)
        issue = feature_issue_time(target)
        assert_cutoff_safe(target, issue, specs, cutoff_local=cutoff_local)
        issue_text = issue.strftime("%Y%m%d%H")
        issue_root = output_root / "raw" / issue_text
        decoded_by_variable = {}
        variable_records = []
        try:
            for variable in SOIL_VARIABLES:
                grib_url, inventory_url = archive_urls(variable, issue)
                inventory_bytes, inventory_record, fetched_inventory = fetch_or_load(
                    path=issue_root / f"{variable.archive_name}.{MEMBER}.{issue_text}.daily.inv",
                    url=inventory_url,
                    timeout_seconds=timeout_seconds,
                    attempts=attempts,
                    request_get=request_get,
                    sleep_fn=sleep_fn,
                )
                inventory_request_index = len(requests_provenance)
                requests_provenance.append(inventory_record)
                messages = parse_inventory(
                    inventory_bytes.decode("utf-8"),
                    variable=variable,
                    expected_issue_time=issue,
                )
                selected_messages, start, end = selected_inventory_span(
                    messages,
                    target_date=target,
                    issue_time=issue,
                    specs=specs,
                )
                range_path = issue_root / (
                    f"{variable.archive_name}.{MEMBER}.{issue_text}.f"
                    f"{selected_messages[0].step_hours:04d}-"
                    f"f{selected_messages[-1].step_hours:04d}.grb2"
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
                range_request_index = len(requests_provenance)
                requests_provenance.append(range_record)
                decoded, decode_audit = decode_selected_range(
                    range_path,
                    variable=variable,
                    target_date=target,
                    specs=specs,
                    eccodes=decoder,
                    issue_time=issue,
                    expected_messages=selected_messages,
                )
                decoded_by_variable[variable.archive_name] = decoded
                variable_records.append(
                    {
                        "variable": variable.archive_name,
                        "inventory_url": inventory_url,
                        "grib_url": grib_url,
                        "selected_messages": [
                            {
                                "message": item.message,
                                "offset": item.offset,
                                "issue_text": item.issue_text,
                                "step_hours": item.step_hours,
                            }
                            for item in selected_messages
                        ],
                        "selected_steps_hours": [item.step_hours for item in selected_messages],
                        "range_start": start,
                        "range_end": end,
                        "inventory_request_index": inventory_request_index,
                        "inventory_sha256": inventory_record["sha256"],
                        "range_request_index": range_request_index,
                        "range_sha256": range_record["sha256"],
                        "decode": decode_audit,
                    }
                )
                network_used = network_used or fetched_inventory or fetched_range
            if variable_records[0]["selected_steps_hours"] != variable_records[1]["selected_steps_hours"]:
                raise ValueError("CFSv2 soil variables selected different forecast steps")
            if (
                variable_records[0]["decode"]["valid_times_utc"]
                != variable_records[1]["decode"]["valid_times_utc"]
            ):
                raise ValueError("CFSv2 soil variables decoded different valid times")
            merged = _merge_variable_values(decoded_by_variable, specs)
            for market_id, market_values in merged.items():
                values[market_id][target_text].update(market_values)
            issue_records.append(
                {
                    "target_date": target_text,
                    "issue_time_utc": issue.isoformat(),
                    "buffered_available_time_utc": buffered_available_time(issue).isoformat(),
                    "variables": variable_records,
                }
            )
            if pause_seconds > 0:
                sleep_fn(float(pause_seconds))
        except Exception as exc:  # noqa: BLE001 - retain exact per-cycle blocker
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
        derived_forecast = (
            output_root / "derived_data" / "forecast_history" / spec.icao.lower()
            / "forecast_long.csv"
        )
        derived_settlement = (
            output_root / "derived_data" / "wunderground" / spec.icao.lower()
            / "daily" / "daily_summary.csv"
        )
        write_csv_rows_atomic(derived_forecast, RICH_FORECAST_COLUMNS, rows)
        if source_settlement.exists():
            copy_file_atomic(source_settlement, derived_settlement)
        derived_markets.append(
            {
                "market_id": spec.id,
                "station": spec.icao,
                **coverage,
                "forecast_path": str(derived_forecast),
                "forecast_sha256": sha256_file(derived_forecast),
                "settlement_path": str(derived_settlement),
                "settlement_sha256": sha256_file(derived_settlement),
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
        "code": {
            "module": "weather.reporting.research.cfsv2_soil_research",
            "path": str(Path(__file__).resolve(strict=True)),
            "sha256": sha256_file(__file__),
        },
        "source_data_root": str(source_root),
        "output_root": str(output_root),
        "derived_data_root": str(output_root / "derived_data"),
        "source": {
            "provider": "NOAA NCEI",
            "dataset": "CFSv2 operational 9-month forecast time series",
            "variables": [item.archive_name for item in SOIL_VARIABLES],
            "member": MEMBER,
            "issue_rule": "target minus two UTC calendar days at 18Z",
            "availability_buffer_hours": 12,
            "valid_time_rule": "all 6-hour messages falling on each local target date",
            "spatial_rule": (
                "closest plausible value among four bracketing cells on the archived "
                "384x190 regular Gaussian grid; paired variables must select one cell"
            ),
            "physical_depth_m": [DEPTH_TOP_METERS, DEPTH_BOTTOM_METERS],
        },
        "adapter_contract": {
            "physical_layer": "CFSv2 0-0.1 m below ground",
            "legacy_temperature_column": "soil_temperature_0cm",
            "legacy_moisture_column": "soil_moisture_0_to_1cm",
            "warning": (
                "legacy column names do not describe the CFSv2 0-0.1 m layer; "
                "mapping exists only to reuse the offline soil feature aggregator"
            ),
            "serving_or_collector_contract_changed": False,
        },
        "cutoff_local": cutoff_local,
        "target_date_count": len(target_dates),
        "first_target_date": target_dates[0] if target_dates else None,
        "last_target_date": target_dates[-1] if target_dates else None,
        "availability_contract_path": str(paths["availability"]),
        "availability_contract_sha256": sha256_file(paths["availability"]),
        "availability": availability,
        "request_count": len(requests_provenance),
        "requests": requests_provenance,
        "network_used": network_used,
        "issue_count": len(issue_records),
        "issues": issue_records,
        "error_count": len(errors),
        "errors": errors,
        "max_nearest_grid_distance_km": max_distance,
        "baseline_audit": baseline_audit,
        "source_input_count": len(source_inputs),
        "source_inputs": source_inputs,
        "markets": derived_markets,
        "supported_market_dates": sum(item["supported_market_dates"] for item in derived_markets),
        "source_mirror_mutated": source_mirror_mutated,
    }


def write_manifest_report(path: str | Path, payload: Mapping[str, Any]) -> Path:
    source = payload["source"]
    availability = payload["availability"]
    lines = [
        "# Scratch NOAA CFSv2 Top-layer Soil Backfill",
        "",
        f"Generated: {payload['generated_at_utc']}",
        f"Schema: `{payload['schema_version']}`",
        "",
        "The source mirror remained read-only. Raw ranges and derived rows were written only under scratch.",
        "",
        "The legacy adapter column names are not literal depth labels here: both carry the exact CFSv2 0-0.1 m layer solely for the offline soil-family aggregator.",
        "",
        "## Frozen Contract",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Variables/member", f"{', '.join(source['variables'])} / {source['member']}"],
            ["Issue rule", source["issue_rule"]],
            ["Physical depth", "0-0.1 m below ground"],
            ["Target dates", payload["target_date_count"]],
            ["Complete-pair dates", availability["complete_pair_date_count"]],
            ["Missing-pair dates", availability["missing_pair_date_count"]],
            ["Decoded issues", payload["issue_count"]],
            ["Decode errors", payload["error_count"]],
            ["Supported market-dates", payload["supported_market_dates"]],
            ["Availability contract SHA-256", availability["contract_sha256"]],
        ],
    )
    lines += ["", "## Availability by Year", ""]
    lines += markdown_table(
        ["Year", "Targets", "Complete pair", "Missing pair"],
        [
            [item["year"], item["target_dates"], item["complete_pair_dates"], item["missing_pair_dates"]]
            for item in availability["coverage_by_year"]
        ],
    )
    lines += ["", "## Market Coverage", ""]
    lines += markdown_table(
        ["Market", "Selected dates", "Supported dates", "Rows", "Paired rows"],
        [
            [
                item["market_id"], item["selected_market_dates"], item["supported_market_dates"],
                item["derived_rows"], item["soil_temperature_nonnull_rows"],
            ]
            for item in payload["markets"]
        ],
    )
    if payload["errors"]:
        lines += ["", "## Decode Errors", ""]
        lines.extend(
            f"- {item['target_date']} ({item['error_type']}): {item['error']}"
            for item in payload["errors"]
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
        eccodes_path=args.eccodes_path,
        cutoff_local=args.cutoff_local,
        pause_seconds=args.pause_seconds,
        timeout_seconds=args.timeout_seconds,
        attempts=args.attempts,
        availability_workers=args.availability_workers,
    )
    write_json_atomic(paths["manifest"], payload)
    write_manifest_report(paths["report"], payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill bounded NOAA CFSv2 top-layer soil values into scratch."
    )
    parser.add_argument("--source-data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--eccodes-path", required=True)
    parser.add_argument("--cutoff-local", default="00:00")
    parser.add_argument("--pause-seconds", type=float, default=DEFAULT_PAUSE_SECONDS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--availability-workers", type=int, default=DEFAULT_AVAILABILITY_WORKERS)
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(
        f"CFSv2 soil backfill: {payload['issue_count']}/"
        f"{payload['availability']['complete_pair_date_count']} available issues, "
        f"{payload['supported_market_dates']} supported market-dates, "
        f"{payload['error_count']} decode errors"
    )
    return 0 if payload["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
