"""Scratch-only NOAA CFSv2 850 hPa backfill for offline Tmax research.

The mirrored ``data/`` tree is an immutable input.  This module selects the
same explicit-issue baseline rows used by the offline Tmax evaluator, fetches
only the CFSv2 GRIB messages whose valid times fall on those target dates, and
writes a derived data root beneath an explicitly supplied scratch directory.

CFSv2 archives nominal model-cycle time, not publication time.  To keep the
feature safely on the available side of the local-midnight cutoff, the fixed
contract uses the target-minus-two-UTC-calendar-days 18Z control run and charges
a conservative 12-hour availability buffer.  This cycle is fixed uniformly,
not selected by retrospective availability, and its buffered time is strictly
before midnight for every built-in market in the evaluated summer corpus.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import importlib.util
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests

from weather.io import (
    copy_file_atomic,
    request_with_retries,
    write_bytes_atomic,
    write_csv_rows_atomic,
    write_json_atomic,
    write_text_atomic,
)
from weather.market.market_registry import BUILTIN_SPECS, MarketSpec
from weather.reporting.formatting import markdown_table
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


SCHEMA_VERSION = schema_version("cfsv2_pressure_research")
BASE_URL = (
    "https://www.ncei.noaa.gov/data/climate-forecast-system/access/"
    "operational-9-month-forecast/time-series"
)
VARIABLE = "t850"
MEMBER = "01"
CYCLE_HOUR_UTC = 18
ISSUE_LEAD_CALENDAR_DAYS = 2
AVAILABILITY_BUFFER_HOURS = 12
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_ATTEMPTS = 4
DEFAULT_PAUSE_SECONDS = 0.05
INVENTORY_PATTERN = re.compile(
    r"^(?P<message>\d+):(?P<offset>\d+):d=(?P<issue>\d{10}):"
    r"TMP:850 mb:(?P<step>\d+) hour fcst:"
)
CONTENT_RANGE_PATTERN = re.compile(
    r"^bytes\s+(?P<start>\d+)-(?P<end>\d+)/(?P<total>\d+|\*)$",
    re.IGNORECASE,
)
PRESSURE_LEVEL_HPA = 850
PRESSURE_LEVEL_TYPE = "isobaricInhPa"
GRID_TYPE = "regular_ll"
GRID_LONGITUDE_POINTS = 360
GRID_LATITUDE_POINTS = 181
GRID_INCREMENT_DEGREES = 1.0


@dataclass(frozen=True)
class InventoryMessage:
    message: int
    offset: int
    issue_text: str
    step_hours: int


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: str | Path) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def feature_issue_time(target_date: date) -> datetime:
    """Return the predeclared target-minus-two-days 18Z CFSv2 cycle."""

    prior = target_date - timedelta(days=ISSUE_LEAD_CALENDAR_DAYS)
    return datetime.combine(
        prior,
        datetime_time(hour=CYCLE_HOUR_UTC),
        tzinfo=timezone.utc,
    )


def _aware_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_local_cutoff(value: str) -> datetime_time:
    try:
        parsed = datetime_time.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(
            f"invalid local cutoff {value!r}; expected HH:MM[:SS]"
        ) from exc
    if parsed.tzinfo is not None:
        raise ValueError("local cutoff must not contain a timezone offset")
    return parsed


def buffered_available_time(issue_time: datetime) -> datetime:
    return _aware_utc(issue_time, label="issue_time") + timedelta(
        hours=AVAILABILITY_BUFFER_HOURS
    )


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
            "buffered CFSv2 availability is not strictly before the local cutoff: "
            + ", ".join(sorted(unsafe))
        )


def archive_urls(issue_time: datetime) -> tuple[str, str]:
    issue = _aware_utc(issue_time, label="issue_time")
    issue_text = issue.strftime("%Y%m%d%H")
    root = (
        f"{BASE_URL}/{issue:%Y}/{issue:%Y%m}/{issue:%Y%m%d}/{issue_text}"
    )
    stem = f"{VARIABLE}.{MEMBER}.{issue_text}.daily"
    return f"{root}/{stem}.grb2", f"{root}/{stem}.inv"


def parse_inventory(
    text: str,
    *,
    expected_issue_time: datetime | None = None,
) -> list[InventoryMessage]:
    messages = []
    for line in text.splitlines():
        match = INVENTORY_PATTERN.match(line.strip())
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
        raise ValueError("CFSv2 inventory contained no forecast messages")
    expected_numbers = list(range(1, len(messages) + 1))
    if [message.message for message in messages] != expected_numbers:
        raise ValueError("CFSv2 inventory message numbers are not contiguous from one")
    if any(right.offset <= left.offset for left, right in zip(messages, messages[1:])):
        raise ValueError("CFSv2 inventory offsets are not strictly increasing")
    issue_texts = {message.issue_text for message in messages}
    if len(issue_texts) != 1:
        raise ValueError("CFSv2 inventory contains mixed nominal issue cycles")
    try:
        datetime.strptime(messages[0].issue_text, "%Y%m%d%H")
    except ValueError as exc:
        raise ValueError("CFSv2 inventory contains an invalid nominal issue cycle") from exc
    if expected_issue_time is not None:
        expected_issue = _aware_utc(
            expected_issue_time, label="expected_issue_time"
        ).strftime("%Y%m%d%H")
        if messages[0].issue_text != expected_issue:
            raise ValueError(
                "CFSv2 inventory nominal issue cycle does not match the requested cycle: "
                f"expected={expected_issue}, got={messages[0].issue_text}"
            )
    steps = [message.step_hours for message in messages]
    if any(step <= 0 or step % 6 != 0 for step in steps):
        raise ValueError("CFSv2 inventory forecast steps are not positive 6-hour steps")
    if any(right <= left for left, right in zip(steps, steps[1:])):
        raise ValueError("CFSv2 inventory forecast steps are not strictly increasing")
    return messages


def selected_inventory_span(
    messages: Sequence[InventoryMessage],
    *,
    target_date: date,
    issue_time: datetime,
    specs: Sequence[MarketSpec] = BUILTIN_SPECS,
) -> tuple[list[InventoryMessage], int, int]:
    """Select the contiguous range covering every built-in local target day."""

    issue_utc = _aware_utc(issue_time, label="issue_time")
    expected_issue = issue_utc.strftime("%Y%m%d%H")
    if any(message.issue_text != expected_issue for message in messages):
        raise ValueError(
            "CFSv2 inventory nominal issue cycle does not match the selected cycle"
        )
    selected = []
    selected_indices = []
    for index, message in enumerate(messages):
        valid = issue_utc + timedelta(hours=message.step_hours)
        if any(valid.astimezone(spec.tz).date() == target_date for spec in specs):
            selected.append(message)
            selected_indices.append(index)
    if not selected:
        raise ValueError(f"inventory has no valid times for {target_date.isoformat()}")
    first_index = selected_indices[0]
    last_index = selected_indices[-1]
    if selected_indices != list(range(first_index, last_index + 1)):
        raise ValueError("selected CFSv2 messages do not form a contiguous span")
    if last_index + 1 >= len(messages):
        raise ValueError("selected range ends at the final inventory message")
    start = messages[first_index].offset
    end = messages[last_index + 1].offset - 1
    return selected, start, end


def _fetch_bytes(
    url: str,
    *,
    headers: Mapping[str, str] | None,
    timeout_seconds: float,
    attempts: int,
    request_get: Callable[..., Any],
    sleep_fn: Callable[[float], None],
) -> tuple[bytes, Any]:
    def once():
        response = request_get(
            url,
            headers=dict(headers or {}),
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        return response

    response = request_with_retries(
        once,
        attempts=attempts,
        base_delay=0.5,
        sleep=sleep_fn,
    )
    return bytes(response.content), response


def _validate_byte_range(
    byte_range: tuple[int, int],
    *,
    content_length: int,
    content_range: str | None,
    require_header: bool,
) -> str | None:
    start, end = (int(byte_range[0]), int(byte_range[1]))
    if start < 0 or end < start:
        raise ValueError(f"invalid CFSv2 byte range: {start}-{end}")
    expected_length = end - start + 1
    if content_length != expected_length:
        raise ValueError(
            "CFSv2 bounded byte range has the wrong length: "
            f"expected={expected_length}, got={content_length}"
        )
    if content_range is None:
        if require_header:
            raise ValueError("CFSv2 206 response omitted Content-Range")
        return None
    match = CONTENT_RANGE_PATTERN.fullmatch(str(content_range).strip())
    if match is None:
        raise ValueError(f"invalid CFSv2 Content-Range header: {content_range!r}")
    actual_start = int(match.group("start"))
    actual_end = int(match.group("end"))
    if (actual_start, actual_end) != (start, end):
        raise ValueError(
            "CFSv2 Content-Range does not match the requested byte range: "
            f"expected={start}-{end}, got={actual_start}-{actual_end}"
        )
    total_text = match.group("total")
    if total_text != "*" and int(total_text) <= end:
        raise ValueError(
            "CFSv2 Content-Range total is not larger than its final byte offset"
        )
    return str(content_range)


def fetch_or_load(
    *,
    path: str | Path,
    url: str,
    byte_range: tuple[int, int] | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
    request_get: Callable[..., Any] = requests.get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[bytes, dict[str, Any], bool]:
    path = Path(path)
    headers = None
    if byte_range is not None:
        _validate_byte_range(
            byte_range,
            content_length=byte_range[1] - byte_range[0] + 1,
            content_range=None,
            require_header=False,
        )
        headers = {"Range": f"bytes={byte_range[0]}-{byte_range[1]}"}
    if path.exists():
        content = path.read_bytes()
        if byte_range is not None:
            _validate_byte_range(
                byte_range,
                content_length=len(content),
                content_range=None,
                require_header=False,
            )
        record = {
            "url": url,
            "byte_range": list(byte_range) if byte_range else None,
            "cache_status": "reused",
            "status_code": None,
            "content_range": None,
            "etag": None,
            "last_modified": None,
            "retrieved_at_utc": None,
        }
        fetched = False
    else:
        content, response = _fetch_bytes(
            url,
            headers=headers,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            request_get=request_get,
            sleep_fn=sleep_fn,
        )
        if byte_range is not None:
            if int(response.status_code) != 206:
                raise ValueError(
                    "CFSv2 server did not honor the bounded byte range: "
                    f"status={response.status_code}"
                )
            content_range = _validate_byte_range(
                byte_range,
                content_length=len(content),
                content_range=response.headers.get("Content-Range"),
                require_header=True,
            )
        else:
            content_range = response.headers.get("Content-Range")
        write_bytes_atomic(path, content)
        record = {
            "url": url,
            "byte_range": list(byte_range) if byte_range else None,
            "cache_status": "fetched",
            "status_code": int(response.status_code),
            "content_range": content_range,
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "retrieved_at_utc": utc_iso(),
        }
        fetched = True
    stat = path.stat()
    record.update(
        {
            "path": str(path),
            "size_bytes": len(content),
            "sha256": sha256_bytes(content),
            "local_mtime_utc": datetime.fromtimestamp(
                stat.st_mtime, timezone.utc
            ).isoformat(),
        }
    )
    return content, record, fetched


def load_eccodes(eccodes_path: str | Path | None = None):
    """Load ecCodes normally or from an explicit pip-target root.

    The research workstation keeps its optional decoder in scratch.  Loading
    that package by explicit specs preserves the CLI's ``--eccodes-path``
    contract without making a repository package mutate process-global import
    search paths.
    """

    if eccodes_path is None:
        return importlib.import_module("eccodes")
    loaded = sys.modules.get("eccodes")
    if loaded is not None:
        return loaded
    root = Path(eccodes_path).resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"ecCodes dependency root is not a directory: {root}")

    inserted: set[str] = set()

    def load_package(name: str):
        existing = sys.modules.get(name)
        if existing is not None:
            return existing
        init_path = root / name / "__init__.py"
        if not init_path.is_file():
            raise ValueError(
                f"ecCodes dependency root is missing package {name!r}: {init_path}"
            )
        spec = importlib.util.spec_from_file_location(
            name,
            init_path,
            submodule_search_locations=[str(init_path.parent)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot construct import spec for {name!r}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        inserted.add(name)
        spec.loader.exec_module(module)
        return module

    try:
        if "_cffi_backend" not in sys.modules:
            backend_paths = sorted(root.glob("_cffi_backend*.pyd"))
            if len(backend_paths) != 1:
                raise ValueError(
                    "ecCodes dependency root must contain exactly one "
                    f"_cffi_backend extension; found={len(backend_paths)}"
                )
            backend_spec = importlib.util.spec_from_file_location(
                "_cffi_backend", backend_paths[0]
            )
            if backend_spec is None or backend_spec.loader is None:
                raise ImportError("cannot construct import spec for _cffi_backend")
            backend = importlib.util.module_from_spec(backend_spec)
            sys.modules["_cffi_backend"] = backend
            inserted.add("_cffi_backend")
            backend_spec.loader.exec_module(backend)
        load_package("pycparser")
        load_package("cffi")
        load_package("findlibs")

        eccodes_init = root / "eccodes" / "__init__.py"
        eccodes_spec = importlib.util.spec_from_file_location(
            "eccodes",
            eccodes_init,
            submodule_search_locations=[str(eccodes_init.parent)],
        )
        if eccodes_spec is None or eccodes_spec.loader is None:
            raise ImportError("cannot construct import spec for 'eccodes'")
        eccodes = importlib.util.module_from_spec(eccodes_spec)
        sys.modules["eccodes"] = eccodes
        inserted.add("eccodes")
        load_package("gribapi")
        eccodes_spec.loader.exec_module(eccodes)
        return eccodes
    except Exception:
        for name in sorted(
            (
                module_name
                for module_name in sys.modules
                if any(
                    module_name == prefix or module_name.startswith(prefix + ".")
                    for prefix in inserted
                )
            ),
            reverse=True,
        ):
            sys.modules.pop(name, None)
        raise


def _grib_valid_time(eccodes, handle: int) -> datetime:
    valid_date = int(eccodes.codes_get(handle, "validityDate"))
    valid_time = int(eccodes.codes_get(handle, "validityTime"))
    return datetime.strptime(
        f"{valid_date:08d}{valid_time:04d}", "%Y%m%d%H%M"
    ).replace(tzinfo=timezone.utc)


def _grib_reference_time(eccodes, handle: int) -> datetime:
    reference_date = int(eccodes.codes_get(handle, "dataDate"))
    reference_time = int(eccodes.codes_get(handle, "dataTime"))
    return datetime.strptime(
        f"{reference_date:08d}{reference_time:04d}", "%Y%m%d%H%M"
    ).replace(tzinfo=timezone.utc)


def decode_selected_range(
    path: str | Path,
    *,
    target_date: date,
    specs: Sequence[MarketSpec],
    eccodes,
    issue_time: datetime | None = None,
    expected_messages: Sequence[InventoryMessage] | None = None,
) -> tuple[dict[str, dict[str, dict[str, float]]], dict[str, Any]]:
    """Decode selected messages and extract nearest-grid values for all cities."""

    output: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    messages = 0
    max_distance_km = 0.0
    valid_times: list[str] = []
    reference_times: list[str] = []
    forecast_steps: list[int] = []
    grid_records: list[dict[str, Any]] = []
    expected_issue = (
        _aware_utc(issue_time, label="issue_time")
        if issue_time is not None
        else None
    )
    with Path(path).open("rb") as source:
        while True:
            handle = eccodes.codes_grib_new_from_file(source)
            if handle is None:
                break
            try:
                if str(eccodes.codes_get(handle, "shortName")) != "t":
                    raise ValueError("unexpected non-temperature CFSv2 message")
                if str(eccodes.codes_get(handle, "units")) != "K":
                    raise ValueError("unexpected CFSv2 temperature unit")
                if (
                    str(eccodes.codes_get(handle, "typeOfLevel"))
                    != PRESSURE_LEVEL_TYPE
                    or int(eccodes.codes_get(handle, "level"))
                    != PRESSURE_LEVEL_HPA
                ):
                    raise ValueError("unexpected CFSv2 pressure level")
                if str(eccodes.codes_get(handle, "stepType")) != "instant":
                    raise ValueError("unexpected non-instantaneous CFSv2 message")
                grid_record = {
                    "grid_type": str(eccodes.codes_get(handle, "gridType")),
                    "longitude_points": int(eccodes.codes_get(handle, "Ni")),
                    "latitude_points": int(eccodes.codes_get(handle, "Nj")),
                    "longitude_increment_degrees": float(
                        eccodes.codes_get(handle, "iDirectionIncrementInDegrees")
                    ),
                    "latitude_increment_degrees": float(
                        eccodes.codes_get(handle, "jDirectionIncrementInDegrees")
                    ),
                }
                if grid_record != {
                    "grid_type": GRID_TYPE,
                    "longitude_points": GRID_LONGITUDE_POINTS,
                    "latitude_points": GRID_LATITUDE_POINTS,
                    "longitude_increment_degrees": GRID_INCREMENT_DEGREES,
                    "latitude_increment_degrees": GRID_INCREMENT_DEGREES,
                }:
                    raise ValueError(f"unexpected CFSv2 grid contract: {grid_record}")
                grid_records.append(grid_record)
                reference_utc = _grib_reference_time(eccodes, handle)
                if expected_issue is not None and reference_utc != expected_issue:
                    raise ValueError(
                        "CFSv2 GRIB reference cycle does not match the requested cycle"
                    )
                step_hours = int(eccodes.codes_get(handle, "forecastTime"))
                valid_utc = _grib_valid_time(eccodes, handle)
                valid_times.append(valid_utc.isoformat())
                reference_times.append(reference_utc.isoformat())
                forecast_steps.append(step_hours)
                messages += 1
                for spec in specs:
                    valid_local = valid_utc.astimezone(spec.tz)
                    if valid_local.date() != target_date:
                        continue
                    nearest = eccodes.codes_grib_find_nearest(
                        handle,
                        float(spec.lat),
                        float(spec.lon),
                    )[0]
                    temperature_k = float(nearest["value"])
                    distance_km = float(nearest["distance"])
                    grid_lat = float(nearest["lat"])
                    grid_lon = float(nearest["lon"])
                    if (
                        not math.isfinite(temperature_k)
                        or not 150.0 <= temperature_k <= 350.0
                    ):
                        raise ValueError(
                            f"implausible CFSv2 850 hPa temperature: {temperature_k} K"
                        )
                    if (
                        not math.isfinite(distance_km)
                        or distance_km < 0.0
                        or not math.isfinite(grid_lat)
                        or not math.isfinite(grid_lon)
                    ):
                        raise ValueError("invalid CFSv2 nearest-grid metadata")
                    temperature_c = temperature_k - 273.15
                    max_distance_km = max(max_distance_km, distance_km)
                    output[spec.id][valid_local.isoformat()] = {
                        "temperature_850_c": temperature_c,
                        "grid_lat": grid_lat,
                        "grid_lon": grid_lon,
                        "distance_km": distance_km,
                    }
            finally:
                eccodes.codes_release(handle)
    if expected_messages is not None:
        expected_steps = [message.step_hours for message in expected_messages]
        expected_valid_times = [
            (expected_issue + timedelta(hours=step)).isoformat()
            for step in expected_steps
        ] if expected_issue is not None else []
        if forecast_steps != expected_steps:
            raise ValueError(
                "decoded CFSv2 forecast steps do not match the selected inventory span: "
                f"expected={expected_steps}, got={forecast_steps}"
            )
        if expected_issue is not None and valid_times != expected_valid_times:
            raise ValueError(
                "decoded CFSv2 valid times do not match the selected inventory span"
            )
    return {key: dict(value) for key, value in output.items()}, {
        "decoded_messages": messages,
        "reference_times_utc": reference_times,
        "forecast_steps_hours": forecast_steps,
        "valid_times_utc": valid_times,
        "grid": grid_records[0] if grid_records else None,
        "first_valid_time_utc": min(valid_times) if valid_times else None,
        "last_valid_time_utc": max(valid_times) if valid_times else None,
        "max_nearest_grid_distance_km": max_distance_km,
        "market_value_count": sum(len(values) for values in output.values()),
    }


def _station_root(root: Path, station: str) -> Path:
    lower = root / station.lower()
    upper = root / station.upper()
    return lower if lower.exists() or not upper.exists() else upper


def source_paths(data_root: str | Path, spec: MarketSpec) -> tuple[Path, Path]:
    root = Path(data_root)
    forecast = _station_root(root / "forecast_history", spec.icao) / "forecast_long.csv"
    settlement = (
        _station_root(root / "wunderground", spec.icao)
        / "daily"
        / "daily_summary.csv"
    )
    return forecast, settlement


def enrich_selected_rows(
    source_forecast_path: str | Path,
    *,
    spec: MarketSpec,
    selected_rows: Sequence[Mapping[str, Any]],
    values_by_date: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    expected_unit = str(spec.unit).strip().upper()
    if expected_unit not in {"C", "F"}:
        raise ValueError(
            f"unsupported native temperature unit for {spec.id}: {spec.unit!r}"
        )
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
    nonnull = 0
    with Path(source_forecast_path).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
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
            target_date = str(row.get("target_date") or "")
            valid_time = str(row.get("valid_time") or "")
            item = (values_by_date.get(target_date) or {}).get(valid_time) or {}
            temperature_c = to_float(item.get("temperature_850_c"))
            row["temperature_850hpa"] = (
                ""
                if temperature_c is None
                else c_to_native(temperature_c, expected_unit, digits=None)
            )
            if temperature_c is not None:
                nonnull += 1
                supported_dates.add(target_date)
            row["payload_hash"] = forecast_payload_hash(row)
            output.append(row)
    output.sort(key=lambda row: (str(row.get("target_date")), str(row.get("valid_time"))))
    return output, {
        "selected_market_dates": len(selected_keys),
        "supported_market_dates": len(supported_dates),
        "derived_rows": len(output),
        "temperature_850_nonnull_rows": nonnull,
    }


def _selected_baselines(
    source_data_root: Path,
    specs: Sequence[MarketSpec],
    cutoff_local: str,
) -> tuple[dict[str, list[dict[str, Any]]], list[str], list[dict[str, Any]]]:
    selected_by_market = {}
    audit = []
    target_dates = set()
    for spec in specs:
        rows, market_audit, _ = load_market_rows(
            data_root=source_data_root,
            spec=spec,
            family="pressure850",
            cutoff_local=cutoff_local,
        )
        selected_by_market[spec.id] = rows
        for provenance in market_audit.get("provenance", {}).values():
            provenance["sha256"] = sha256_file(provenance["path"])
        audit.append(market_audit)
        target_dates.update(str(row["target_date"]) for row in rows)
    return selected_by_market, sorted(target_dates), audit


def build_scratch_backfill(
    *,
    source_data_root: str | Path,
    output_root: str | Path,
    eccodes_path: str | Path | None,
    cutoff_local: str = "00:00",
    pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = DEFAULT_ATTEMPTS,
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
            "manifest": Path(output_root) / "manifest.json",
        },
    )
    output_root = paths["output_root"]
    selected, target_dates, baseline_audit = _selected_baselines(
        source_root, specs, cutoff_local
    )
    source_inputs = [
        {
            "market_id": market_audit["market_id"],
            "role": role,
            **provenance,
        }
        for market_audit in baseline_audit
        for role, provenance in market_audit.get("provenance", {}).items()
    ]
    decoder = load_eccodes(eccodes_path)
    values: dict[str, dict[str, dict[str, dict[str, float]]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    requests_provenance = []
    issue_records = []
    errors = []
    network_used = False
    for target_text in target_dates:
        target = date.fromisoformat(target_text)
        issue = feature_issue_time(target)
        assert_cutoff_safe(
            target,
            issue,
            specs,
            cutoff_local=cutoff_local,
        )
        grib_url, inventory_url = archive_urls(issue)
        issue_text = issue.strftime("%Y%m%d%H")
        issue_root = output_root / "raw" / issue_text
        try:
            inventory_bytes, inventory_record, fetched_inventory = fetch_or_load(
                path=issue_root / f"{VARIABLE}.{MEMBER}.{issue_text}.daily.inv",
                url=inventory_url,
                timeout_seconds=timeout_seconds,
                attempts=attempts,
                request_get=request_get,
                sleep_fn=sleep_fn,
            )
            inventory_request_index = len(requests_provenance)
            requests_provenance.append(inventory_record)
            network_used = network_used or fetched_inventory
            messages = parse_inventory(
                inventory_bytes.decode("utf-8"),
                expected_issue_time=issue,
            )
            selected_messages, start, end = selected_inventory_span(
                messages,
                target_date=target,
                issue_time=issue,
                specs=specs,
            )
            range_path = issue_root / (
                f"{VARIABLE}.{MEMBER}.{issue_text}.f"
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
            network_used = network_used or fetched_range
            decoded, decode_audit = decode_selected_range(
                range_path,
                target_date=target,
                specs=specs,
                eccodes=decoder,
                issue_time=issue,
                expected_messages=selected_messages,
            )
            for market_id, market_values in decoded.items():
                values[market_id][target_text].update(market_values)
            issue_records.append(
                {
                    "target_date": target_text,
                    "issue_time_utc": issue.isoformat(),
                    "buffered_available_time_utc": buffered_available_time(issue).isoformat(),
                    "selected_messages": [
                        {
                            "message": message.message,
                            "offset": message.offset,
                            "issue_text": message.issue_text,
                            "step_hours": message.step_hours,
                        }
                        for message in selected_messages
                    ],
                    "selected_steps_hours": [
                        message.step_hours for message in selected_messages
                    ],
                    "range_start": start,
                    "range_end": end,
                    "inventory_request_index": inventory_request_index,
                    "inventory_sha256": inventory_record["sha256"],
                    "range_request_index": range_request_index,
                    "range_sha256": range_record["sha256"],
                    "decode": decode_audit,
                }
            )
            fetched = fetched_inventory or fetched_range
            if fetched and pause_seconds > 0:
                sleep_fn(float(pause_seconds))
        except Exception as exc:  # noqa: BLE001 - preserve per-cycle blockers
            errors.append(
                {
                    "target_date": target_text,
                    "issue_time_utc": issue.isoformat(),
                    "inventory_url": inventory_url,
                    "grib_url": grib_url,
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
            output_root
            / "derived_data"
            / "forecast_history"
            / spec.icao.lower()
            / "forecast_long.csv"
        )
        derived_settlement = (
            output_root
            / "derived_data"
            / "wunderground"
            / spec.icao.lower()
            / "daily"
            / "daily_summary.csv"
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
        sha256_after = sha256_file(source_input["path"])
        source_input["sha256_after"] = sha256_after
        source_input["unchanged_during_run"] = (
            source_input.get("sha256") == sha256_after
        )
        source_mirror_mutated = (
            source_mirror_mutated or not source_input["unchanged_during_run"]
        )
    if source_mirror_mutated:
        errors.append(
            {
                "target_date": None,
                "issue_time_utc": None,
                "inventory_url": None,
                "grib_url": None,
                "error_type": "SourceMirrorMutationError",
                "error": "one or more source input hashes changed during the run",
            }
        )

    max_distance = max(
        (
            float(record["decode"]["max_nearest_grid_distance_km"])
            for record in issue_records
        ),
        default=None,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "research_only": True,
        "code": {
            "module": "weather.reporting.research.cfsv2_pressure_research",
            "path": str(Path(__file__).resolve(strict=True)),
            "sha256": sha256_file(__file__),
        },
        "source_data_root": str(source_root),
        "output_root": str(output_root),
        "derived_data_root": str(output_root / "derived_data"),
        "source": {
            "provider": "NOAA NCEI",
            "dataset": "CFSv2 operational 9-month forecast time series",
            "base_url": BASE_URL,
            "variable": VARIABLE,
            "member": MEMBER,
            "cycle_hour_utc": CYCLE_HOUR_UTC,
            "issue_lead_calendar_days": ISSUE_LEAD_CALENDAR_DAYS,
            "availability_buffer_hours": AVAILABILITY_BUFFER_HOURS,
            "issue_rule": "target minus two UTC calendar days at 18Z",
            "valid_time_rule": "all 6-hour messages falling on each local target date",
            "spatial_rule": "nearest point on archived regular 1-degree grid",
        },
        "cutoff_local": cutoff_local,
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
        "max_nearest_grid_distance_km": max_distance,
        "baseline_audit": baseline_audit,
        "source_input_count": len(source_inputs),
        "source_inputs": source_inputs,
        "markets": derived_markets,
        "supported_market_dates": sum(
            market["supported_market_dates"] for market in derived_markets
        ),
        "source_mirror_mutated": source_mirror_mutated,
    }


def write_manifest_report(path: str | Path, payload: Mapping[str, Any]) -> Path:
    path = Path(path)
    source = payload["source"]
    lines = [
        "# Scratch NOAA CFSv2 850 hPa Backfill",
        "",
        f"Generated: {payload['generated_at_utc']}",
        f"Schema: `{payload['schema_version']}`",
        "",
        "The mirrored data root was read-only. Raw ranges and derived rows were written only under scratch.",
        "",
        "## Contract",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Dataset", source["dataset"]],
            ["Variable/member", f"{source['variable']} / {source['member']}"],
            ["Issue rule", source["issue_rule"]],
            ["Availability buffer", f"{source['availability_buffer_hours']} hours"],
            ["Valid-time rule", source["valid_time_rule"]],
            ["Target dates", payload["target_date_count"]],
            ["Completed issues", payload["issue_count"]],
            ["Errors", payload["error_count"]],
            ["Requests", payload["request_count"]],
            ["Supported market-dates", payload["supported_market_dates"]],
            ["Max nearest-grid distance km", payload["max_nearest_grid_distance_km"]],
        ],
    )
    lines += ["", "## Market Coverage", ""]
    lines += markdown_table(
        ["Market", "Selected dates", "Supported dates", "Rows", "850 hPa rows"],
        [
            [
                market["market_id"],
                market["selected_market_dates"],
                market["supported_market_dates"],
                market["derived_rows"],
                market["temperature_850_nonnull_rows"],
            ]
            for market in payload["markets"]
        ],
    )
    if payload["errors"]:
        lines += ["", "## Errors", ""]
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
    )
    write_json_atomic(paths["manifest"], payload)
    write_manifest_report(paths["report"], payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill bounded NOAA CFSv2 850 hPa values into a scratch data root."
    )
    parser.add_argument("--source-data-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--eccodes-path", required=True)
    parser.add_argument("--cutoff-local", default="00:00")
    parser.add_argument("--pause-seconds", type=float, default=DEFAULT_PAUSE_SECONDS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    return parser


def main(argv: list[str] | None = None) -> int:
    payload = run(build_parser().parse_args(argv))
    print(
        f"CFSv2 850 hPa backfill: {payload['issue_count']}/"
        f"{payload['target_date_count']} issues, {payload['supported_market_dates']} "
        f"supported market-dates, {payload['error_count']} errors"
    )
    return 0 if payload["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
