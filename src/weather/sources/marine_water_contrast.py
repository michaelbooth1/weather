"""Historical marine water-temperature contrast sidecar.

This module turns station-history rows and cached gridded SST points into the
same marine contrast feature columns used by live serving. Station history is
cutoff-aware so replay does not learn from end-of-day winds that were not
available at the simulated serve time. GLSEA/OISST support is intentionally
cache-first: operators download or place NetCDF files locally, then this adapter
extracts the nearest market point with provenance.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from weather.market.market_registry import REGISTRY, all_specs, spec_for_id
from weather.model.model_constants import INTRADAY_CUTOFF_HOURS
from weather.paths import data_path
from weather.schema_registry import schema_version
from weather.sources.forecast_history import daily_path_for, load_forecast_daily
from weather.sources.historical_fallbacks import haversine_km
from weather.sources.historical_schema import replace_with_retry
from weather.sources.marine_context import (
    HISTORY_SOURCE,
    MARINE_CONTEXT_FEATURE_COLUMNS,
    derive_marine_context_features,
    fetch_marine_station_history_for_market,
    latest_row,
    parse_date,
    payload_hash,
    registry_for_market,
    sensor_present,
)
from weather.units import c_to_native, to_float


MARINE_WATER_CONTRAST_SCHEMA_VERSION = schema_version("marine_water_contrast_features")
MARINE_WATER_CONTRAST_BACKFILL_SCHEMA_VERSION = schema_version("marine_water_contrast_backfill")
MARINE_GRIDDED_SST_POINT_SCHEMA_VERSION = schema_version("marine_gridded_sst_point")

SOURCE = "marine_water_contrast"
DEFAULT_ROOT = data_path() / "marine_water_contrast"
FEATURE_FILENAME = "marine_water_contrast_features.csv"
GLSEA_SOURCE_URL = (
    "https://coastwatch.glerl.noaa.gov/satellite-data-products/"
    "great-lakes-surface-environmental-analysis-glsea/"
)
OISST_SOURCE_URL = "https://www.ncei.noaa.gov/products/optimum-interpolation-sst"
GRIDDED_SST_PROVIDERS = {"glsea", "oisst"}
DEFAULT_GRIDDED_PROVIDER_BY_MARKET = {
    "toronto": "glsea",
    "chicago": "glsea",
    "nyc": "oisst",
    "miami": "oisst",
    "houston": "oisst",
    "los-angeles": "oisst",
    "san-francisco": "oisst",
    "seattle": "oisst",
}
GRIDDED_SST_VARIABLE_CANDIDATES = (
    "sst",
    "analysed_sst",
    "analysis_sst",
    "water_temp",
    "water_temperature",
    "surface_temperature",
)
GRIDDED_SST_COLUMNS = [
    "schema_version",
    "source",
    "provider",
    "product",
    "market_id",
    "city",
    "local_date",
    "water_temp_c",
    "water_temp_native",
    "temperature_unit",
    "market_lat",
    "market_lon",
    "grid_lat",
    "grid_lon",
    "grid_distance_km",
    "source_url",
    "raw_path",
    "payload_hash",
]
FEATURE_META_COLUMNS = [
    "schema_version",
    "source",
    "market_id",
    "city",
    "station",
    "local_date",
    "cutoff_hour",
    "wall_minute",
    "feature_source",
    "sst_provider",
    "sst_product",
    "water_body",
    "station_ids",
    "source_urls",
    "payload_hash",
    "provenance",
]
FEATURE_COLUMNS = [*FEATURE_META_COLUMNS, *MARINE_CONTEXT_FEATURE_COLUMNS]


def iter_dates(start_date: date, end_date: date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def chunk_date_range(start_date: date, end_date: date, chunk_days: int = 31):
    current = start_date
    while current <= end_date:
        chunk_end = min(current + timedelta(days=max(1, int(chunk_days)) - 1), end_date)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def write_csv_atomic(path: str | Path, columns: list[str], rows: list[dict[str, Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    replace_with_retry(tmp_path, path)
    return path


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _iso_date(value: Any) -> str:
    return parse_date(value).isoformat()


def _json_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def cutoff_context_from_station_history(
    station_history: dict[str, Any],
    cutoff_hour: int,
    *,
    wall_minute: int | None = None,
) -> dict[str, Any]:
    """Return a live-shaped marine context using rows available by cutoff."""
    cutoff_hour = int(cutoff_hour)
    if wall_minute is None:
        wall_minute = cutoff_hour * 60
    wall_minute = max(int(wall_minute), cutoff_hour * 60)
    stations = []
    all_rows = []
    for station in (station_history or {}).get("stations") or []:
        available_rows = []
        for row in station.get("rows") or []:
            minute = row.get("minute_of_day")
            if minute is None:
                continue
            try:
                minute = int(float(minute))
            except (TypeError, ValueError):
                continue
            if minute <= wall_minute:
                available_rows.append(row)
        latest = latest_row(available_rows)
        missing = [
            sensor
            for sensor in station.get("required_sensors") or ()
            if not sensor_present(latest, sensor)
        ]
        latest_minute = None
        if latest and latest.get("minute_of_day") is not None:
            try:
                latest_minute = int(float(latest.get("minute_of_day")))
            except (TypeError, ValueError):
                latest_minute = None
        result = dict(station)
        result.update({
            "latest": latest,
            "rows": available_rows,
            "row_count": len(available_rows),
            "missing_sensors": missing,
            "usable": bool(latest) and not missing,
            "latest_age_minutes": (
                round(max(0, wall_minute - latest_minute), 1)
                if latest_minute is not None else None
            ),
            "reason": "" if latest and not missing else (
                "missing required historical sensors by cutoff: " + ", ".join(missing)
                if latest else "no historical marine rows by cutoff"
            ),
        })
        stations.append(result)
        all_rows.extend(available_rows)
    usable = [row for row in stations if row.get("usable")]
    return {
        "schema_version": station_history.get("schema_version"),
        "source": station_history.get("source") or HISTORY_SOURCE,
        "market": station_history.get("market"),
        "target_date": station_history.get("target_date"),
        "available": bool(usable),
        "reason": "" if usable else "no cutoff-available historical marine station with required sensors",
        "stations": stations,
        "rows": sorted(all_rows, key=lambda row: row.get("valid_time_utc") or ""),
        "row_count": len(all_rows),
        "usable_station_count": len(usable),
        "provenance": station_history.get("provenance") or {},
        "payload_hash": station_history.get("payload_hash"),
    }


def _station_source_urls(context: dict[str, Any]) -> list[str]:
    urls = []
    for row in (context or {}).get("rows") or []:
        url = row.get("source_url")
        if url and url not in urls:
            urls.append(url)
    return urls


def _station_ids(context: dict[str, Any]) -> list[str]:
    ids = []
    for row in (context or {}).get("stations") or []:
        station_id = row.get("station_id")
        if station_id and station_id not in ids:
            ids.append(station_id)
    return ids


def _water_bodies(context: dict[str, Any]) -> list[str]:
    bodies = []
    for row in (context or {}).get("stations") or []:
        body = row.get("water_body")
        if body and body not in bodies:
            bodies.append(body)
    return bodies


def gridded_sst_context(
    spec,
    sst_row: dict[str, Any],
    *,
    station_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inject gridded SST into a live-shaped marine context.

    If station context is provided, station wind/air rows remain available and
    the gridded water temperature replaces sparse point-station water readings.
    Without station context, the returned payload still exposes ungated water
    contrast features but cannot infer onshore flow.
    """
    provider = str((sst_row or {}).get("provider") or (sst_row or {}).get("source") or "gridded_sst").lower()
    water_native = to_float((sst_row or {}).get("water_temp_native"))
    if water_native is None:
        water_c = to_float((sst_row or {}).get("water_temp_c"))
        water_native = c_to_native(water_c, spec.display_unit)
    latest_patch = {
        "provider": provider,
        "station_id": f"{provider}:{spec.id}",
        "station_name": f"{provider.upper()} nearest SST grid point",
        "market": spec.id,
        "local_date": (sst_row or {}).get("local_date"),
        "water_temp_c": to_float((sst_row or {}).get("water_temp_c")),
        "water_temp_native": water_native,
        "source_url": (sst_row or {}).get("source_url"),
        "raw_path": (sst_row or {}).get("raw_path"),
    }
    if station_context and station_context.get("stations"):
        context = json.loads(json.dumps(station_context, default=str))
        for station in context.get("stations") or []:
            latest = dict(station.get("latest") or {})
            latest.update(latest_patch)
            station["latest"] = latest
            if station.get("rows"):
                patched = dict(station["rows"][-1])
                patched.update(latest_patch)
                station["rows"][-1] = patched
        context["source"] = SOURCE
        context["gridded_sst"] = dict(sst_row or {})
        return context

    station = {
        "schema_version": MARINE_GRIDDED_SST_POINT_SCHEMA_VERSION,
        "provider": provider,
        "station_id": f"{provider}:{spec.id}",
        "station_name": f"{provider.upper()} nearest SST grid point",
        "water_body": provider.upper(),
        "distance_km": (sst_row or {}).get("grid_distance_km"),
        "bearing_degrees": None,
        "sensor_support": ["water_temperature"],
        "required_sensors": ["water_temperature"],
        "missing_sensors": [],
        "usable": water_native is not None,
        "latest": latest_patch if water_native is not None else None,
        "rows": [latest_patch] if water_native is not None else [],
        "row_count": 1 if water_native is not None else 0,
        "latest_age_minutes": None,
        "onshore_direction_min": None,
        "onshore_direction_max": None,
        "reason": "" if water_native is not None else "missing gridded SST water temperature",
        "errors": [],
    }
    return {
        "schema_version": MARINE_GRIDDED_SST_POINT_SCHEMA_VERSION,
        "source": SOURCE,
        "market": spec.id,
        "target_date": (sst_row or {}).get("local_date"),
        "available": station["usable"],
        "reason": "" if station["usable"] else station["reason"],
        "stations": [station],
        "rows": station["rows"],
        "row_count": station["row_count"],
        "usable_station_count": 1 if station["usable"] else 0,
        "provenance": {"gridded_sst": dict(sst_row or {})},
        "payload_hash": (sst_row or {}).get("payload_hash"),
        "gridded_sst": dict(sst_row or {}),
    }


def _feature_row(
    spec,
    local_date: str,
    cutoff_hour: int,
    wall_minute: int,
    context: dict[str, Any],
    features: dict[str, Any],
    *,
    sst_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sst_row = sst_row or {}
    provider = sst_row.get("provider")
    station_urls = _station_source_urls(context)
    sst_url = sst_row.get("source_url")
    urls = [url for url in [*station_urls, sst_url] if url]
    station_ids = _station_ids(context)
    bodies = _water_bodies(context)
    provenance = {
        "station_history_source": context.get("source"),
        "station_payload_hash": context.get("payload_hash"),
        "station_ids": station_ids,
        "gridded_sst_provider": provider,
        "gridded_sst_payload_hash": sst_row.get("payload_hash"),
        "cutoff_policy": "station rows filtered to wall_minute before deriving onshore features",
    }
    row = {
        "schema_version": MARINE_WATER_CONTRAST_SCHEMA_VERSION,
        "source": SOURCE,
        "market_id": spec.id,
        "city": spec.city_label,
        "station": spec.icao,
        "local_date": local_date,
        "cutoff_hour": int(cutoff_hour),
        "wall_minute": int(wall_minute),
        "feature_source": (
            "station_history_plus_gridded_sst"
            if provider and station_ids else
            "gridded_sst" if provider else
            "station_history"
        ),
        "sst_provider": provider,
        "sst_product": sst_row.get("product"),
        "water_body": "|".join(bodies) or sst_row.get("provider"),
        "station_ids": "|".join(station_ids),
        "source_urls": "|".join(urls),
        "payload_hash": _json_hash(provenance),
        "provenance": json.dumps(provenance, sort_keys=True),
    }
    row.update({column: features.get(column) for column in MARINE_CONTEXT_FEATURE_COLUMNS})
    return row


def build_feature_rows(
    spec,
    station_history_payloads: dict[str, dict[str, Any]] | None = None,
    gridded_sst_rows: dict[str, dict[str, Any]] | None = None,
    forecast_high_index: dict[str, Any] | None = None,
    cutoff_hours: tuple[int, ...] = INTRADAY_CUTOFF_HOURS,
    wall_offsets: tuple[int, ...] = (0,),
) -> list[dict[str, Any]]:
    station_history_payloads = station_history_payloads or {}
    gridded_sst_rows = gridded_sst_rows or {}
    forecast_high_index = forecast_high_index or {}
    dates = sorted(set(station_history_payloads) | set(gridded_sst_rows) | set(forecast_high_index))
    rows = []
    for local_date in dates:
        station_payload = station_history_payloads.get(local_date)
        sst_row = gridded_sst_rows.get(local_date)
        if not station_payload and not sst_row:
            continue
        for cutoff_hour in cutoff_hours:
            for offset in wall_offsets:
                wall_minute = int(cutoff_hour) * 60 + int(offset)
                context = (
                    cutoff_context_from_station_history(
                        station_payload,
                        int(cutoff_hour),
                        wall_minute=wall_minute,
                    )
                    if station_payload else None
                )
                if sst_row:
                    context = gridded_sst_context(spec, sst_row, station_context=context)
                if not context:
                    continue
                features = derive_marine_context_features(
                    context,
                    forecast_high_native=forecast_high_index.get(local_date),
                    cutoff_hour=cutoff_hour,
                    wall_minute=wall_minute,
                )
                rows.append(_feature_row(
                    spec,
                    local_date,
                    int(cutoff_hour),
                    wall_minute,
                    context,
                    features,
                    sst_row=sst_row,
                ))
    return rows


def load_feature_index(path: str | Path) -> dict[tuple[str, int], dict[str, float | None]]:
    index: dict[tuple[str, int], dict[str, float | None]] = {}
    for row in read_csv_rows(path):
        local_date = row.get("local_date")
        cutoff = row.get("cutoff_hour")
        if not local_date or cutoff in (None, ""):
            continue
        try:
            key = (local_date, int(float(cutoff)))
        except (TypeError, ValueError):
            continue
        index[key] = {
            column: to_float(row.get(column))
            for column in MARINE_CONTEXT_FEATURE_COLUMNS
        }
    return index


def load_marine_water_contrast_features(spec=None, root: str | Path | None = None, path: str | Path | None = None):
    if path is None:
        if spec is None:
            return {}
        path = MarineWaterContrastStore(spec, root=root).features_path
    return load_feature_index(path)


def _decode_attr(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _find_netcdf_variable(dataset, names: tuple[str, ...]):
    for name in names:
        variable = dataset.variables.get(name)
        if variable is not None:
            return variable
    raise KeyError(f"none of {names!r} found in NetCDF variables")


def _nearest_index(values, target: float) -> int:
    candidates = [(abs(float(value) - float(target)), index) for index, value in enumerate(values)]
    return min(candidates, key=lambda item: item[0])[1]


def _grid_target_lon(lons, lon: float) -> float:
    values = [float(value) for value in lons]
    if values and min(values) >= 0.0 and max(values) > 180.0:
        return float(lon) % 360.0
    return float(lon)


def _parse_netcdf_time_units(units: Any):
    text = _decode_attr(units)
    match = re.search(
        r"(?P<unit>hours|days)\s+since\s+"
        r"(?P<year>\d{1,4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
        r"(?:[ T](?P<hour>\d{1,2}):(?P<minute>\d{1,2})(?::(?P<second>\d+(?:\.\d+)?))?)?",
        text,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"unsupported NetCDF time units: {text!r}")
    base = datetime(
        int(match.group("year")),
        int(match.group("month")),
        int(match.group("day")),
        int(match.group("hour") or 0),
        int(match.group("minute") or 0),
        int(float(match.group("second") or 0)),
    )
    return match.group("unit").lower(), base


def _netcdf_time_dates(time_variable) -> list[date]:
    values = getattr(time_variable, "data", None)
    if values is None:
        values = time_variable[:]
    unit, base = _parse_netcdf_time_units(getattr(time_variable, "units", ""))
    dates = []
    for raw in values:
        value = float(raw)
        delta = timedelta(hours=value) if unit == "hours" else timedelta(days=value)
        dates.append((base + delta).date())
    return dates


def _attr_float(variable, name: str, default=None):
    value = getattr(variable, name, None)
    if value is None:
        return default
    try:
        if hasattr(value, "flat"):
            value = value.flat[0]
        return float(value)
    except (TypeError, ValueError):
        return default


def _scaled_netcdf_value(raw_value, variable):
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    for attr_name in ("missing_value", "_FillValue"):
        missing = _attr_float(variable, attr_name)
        if missing is not None and value == missing:
            return None
    if not math.isfinite(value) or abs(value) > 1e30:
        return None
    scale = _attr_float(variable, "scale_factor", 1.0)
    offset = _attr_float(variable, "add_offset", 0.0)
    return value * scale + offset


def _temperature_to_c(value: float | None, units: Any) -> float | None:
    if value is None:
        return None
    text = _decode_attr(units).lower()
    if "kelvin" in text or "degk" in text or text.strip() in {"k", "degree_k"} or value > 150.0:
        return value - 273.15
    return value


def _variable_index_tuple(variable, *, time_index: int, lat_index: int, lon_index: int):
    indexes = []
    for dimension in variable.dimensions:
        dim = str(dimension).lower()
        if dim == "time":
            indexes.append(time_index)
        elif dim in {"lat", "latitude"}:
            indexes.append(lat_index)
        elif dim in {"lon", "longitude"}:
            indexes.append(lon_index)
        else:
            indexes.append(0)
    return tuple(indexes)


def provider_source_url(provider: str) -> str:
    provider = str(provider or "").lower()
    if provider == "glsea":
        return GLSEA_SOURCE_URL
    if provider == "oisst":
        return OISST_SOURCE_URL
    return ""


def extract_gridded_sst_points_from_netcdf(
    path: str | Path,
    spec,
    *,
    provider: str,
    product: str | None = None,
    source_url: str | None = None,
    variable_names: tuple[str, ...] = GRIDDED_SST_VARIABLE_CANDIDATES,
) -> list[dict[str, Any]]:
    from scipy.io import netcdf_file

    path = Path(path)
    provider = str(provider or "").lower()
    product = product or provider.upper()
    source_url = source_url or provider_source_url(provider)
    file_hash = hashlib.sha1(path.read_bytes()).hexdigest()
    rows = []
    with netcdf_file(path, "r", mmap=False) as dataset:
        variable = _find_netcdf_variable(dataset, variable_names)
        time_variable = _find_netcdf_variable(dataset, ("time",))
        lat_variable = _find_netcdf_variable(dataset, ("lat", "latitude"))
        lon_variable = _find_netcdf_variable(dataset, ("lon", "longitude"))
        dates = _netcdf_time_dates(time_variable)
        lats = [float(value) for value in lat_variable.data]
        lons = [float(value) for value in lon_variable.data]
        lat_index = _nearest_index(lats, spec.lat)
        lon_index = _nearest_index(lons, _grid_target_lon(lons, spec.lon))
        grid_lat = lats[lat_index]
        grid_lon = lons[lon_index]
        distance = haversine_km(spec.lat, spec.lon, grid_lat, grid_lon if grid_lon <= 180 else grid_lon - 360.0)
        for time_index, local_date in enumerate(dates):
            value = _scaled_netcdf_value(
                variable.data[_variable_index_tuple(
                    variable,
                    time_index=time_index,
                    lat_index=lat_index,
                    lon_index=lon_index,
                )],
                variable,
            )
            water_c = _temperature_to_c(value, getattr(variable, "units", ""))
            rows.append({
                "schema_version": MARINE_GRIDDED_SST_POINT_SCHEMA_VERSION,
                "source": "gridded_sst",
                "provider": provider,
                "product": product,
                "market_id": spec.id,
                "city": spec.city_label,
                "local_date": local_date.isoformat(),
                "water_temp_c": water_c,
                "water_temp_native": c_to_native(water_c, spec.display_unit),
                "temperature_unit": spec.display_unit,
                "market_lat": spec.lat,
                "market_lon": spec.lon,
                "grid_lat": grid_lat,
                "grid_lon": grid_lon,
                "grid_distance_km": round(distance, 3),
                "source_url": source_url,
                "raw_path": str(path),
                "payload_hash": file_hash,
            })
    return rows


def load_gridded_sst_points(path: str | Path, spec=None) -> dict[str, dict[str, Any]]:
    rows = read_csv_rows(path)
    index = {}
    market_id = getattr(spec, "id", None)
    for row in rows:
        if market_id and row.get("market_id") and row.get("market_id") != market_id:
            continue
        local_date = row.get("local_date")
        if local_date:
            index[local_date] = dict(row)
    return index


class MarineWaterContrastStore:
    def __init__(self, spec, root: str | Path | None = None):
        self.spec = spec
        self.root = Path(root) if root else DEFAULT_ROOT / spec.icao.lower()
        self.station_payload_root = self.root / "raw" / "station_history"
        self.gridded_sst_path = self.root / "raw" / "gridded_sst_points.csv"
        self.features_path = self.root / "features" / FEATURE_FILENAME
        self.manifest_path = self.root / "manifest.json"

    def station_payload_path(self, target_date: date | str) -> Path:
        return self.station_payload_root / f"{_iso_date(target_date)}.json"

    def write_station_history_payload(self, target_date: date | str, payload: dict[str, Any]) -> Path:
        path = self.station_payload_path(target_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        return path

    def read_station_history_payloads(self) -> dict[str, dict[str, Any]]:
        payloads = {}
        for path in sorted(self.station_payload_root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            target_date = payload.get("target_date") or path.stem
            payloads[_iso_date(target_date)] = payload
        return payloads

    def station_history_covered_dates(self) -> set[date]:
        dates = set()
        for path in self.station_payload_root.glob("*.json"):
            try:
                dates.add(date.fromisoformat(path.stem[:10]))
            except ValueError:
                continue
        return dates

    def feature_covered_dates(self) -> set[date]:
        dates = set()
        for row in read_csv_rows(self.features_path):
            try:
                dates.add(date.fromisoformat(row.get("local_date", "")[:10]))
            except ValueError:
                continue
        return dates

    def missing_ranges(self, start_date: date, end_date: date, chunk_days: int = 31):
        covered = self.feature_covered_dates()
        missing = [day for day in iter_dates(start_date, end_date) if day not in covered]
        if not missing:
            return []
        ranges = []
        run_start = prev = missing[0]
        for current in missing[1:]:
            if current == prev + timedelta(days=1):
                prev = current
                continue
            ranges.extend(chunk_date_range(run_start, prev, chunk_days))
            run_start = prev = current
        ranges.extend(chunk_date_range(run_start, prev, chunk_days))
        return ranges

    def write_gridded_sst_points(self, rows: list[dict[str, Any]]) -> Path:
        existing = read_csv_rows(self.gridded_sst_path)
        by_key = {
            (row.get("provider"), row.get("market_id"), row.get("local_date"), row.get("payload_hash")): row
            for row in existing
        }
        for row in rows:
            by_key[(row.get("provider"), row.get("market_id"), row.get("local_date"), row.get("payload_hash"))] = row
        return write_csv_atomic(self.gridded_sst_path, GRIDDED_SST_COLUMNS, list(by_key.values()))

    def build_features(
        self,
        *,
        forecast_high_index: dict[str, Any] | None = None,
        cutoff_hours: tuple[int, ...] = INTRADAY_CUTOFF_HOURS,
        wall_offsets: tuple[int, ...] = (0,),
    ) -> list[dict[str, Any]]:
        rows = build_feature_rows(
            self.spec,
            station_history_payloads=self.read_station_history_payloads(),
            gridded_sst_rows=load_gridded_sst_points(self.gridded_sst_path, spec=self.spec),
            forecast_high_index=forecast_high_index or load_forecast_daily(daily_path_for(self.spec)),
            cutoff_hours=cutoff_hours,
            wall_offsets=wall_offsets,
        )
        write_csv_atomic(self.features_path, FEATURE_COLUMNS, rows)
        self.write_manifest(rows)
        return rows

    def write_manifest(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        providers = sorted({row.get("sst_provider") for row in rows if row.get("sst_provider")})
        feature_sources = sorted({row.get("feature_source") for row in rows if row.get("feature_source")})
        payload = {
            "schema_version": MARINE_WATER_CONTRAST_BACKFILL_SCHEMA_VERSION,
            "source": SOURCE,
            "market_id": self.spec.id,
            "city": self.spec.city_label,
            "station": self.spec.icao,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "feature_rows": len(rows),
            "first_date": rows[0]["local_date"] if rows else None,
            "last_date": rows[-1]["local_date"] if rows else None,
            "feature_columns": list(MARINE_CONTEXT_FEATURE_COLUMNS),
            "feature_sources": feature_sources,
            "gridded_sst_providers": providers,
            "station_history_payload_days": len(self.station_history_covered_dates()),
            "gridded_sst_points_path": str(self.gridded_sst_path),
            "features_path": str(self.features_path),
            "source_urls": {
                "glsea": GLSEA_SOURCE_URL,
                "oisst": OISST_SOURCE_URL,
            },
            "policy": (
                "Historical station rows are filtered to cutoff wall time; gridded SST "
                "may replace station water temperature while station wind supplies onshore gating."
            ),
        }
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return payload

    def coverage(self, start_date: date | None = None, end_date: date | None = None) -> dict[str, Any]:
        feature_dates = self.feature_covered_dates()
        station_dates = self.station_history_covered_dates()
        if self.gridded_sst_path.exists():
            gridded_dates = {
                parse_date(row.get("local_date"))
                for row in read_csv_rows(self.gridded_sst_path)
                if row.get("local_date") and (not row.get("market_id") or row.get("market_id") == self.spec.id)
            }
        else:
            gridded_dates = set()
        expected = set(iter_dates(start_date, end_date)) if start_date and end_date else (feature_dates | station_dates | gridded_dates)
        missing = sorted(expected - feature_dates)
        return {
            "schema_version": MARINE_WATER_CONTRAST_BACKFILL_SCHEMA_VERSION,
            "source": SOURCE,
            "market_id": self.spec.id,
            "station": self.spec.icao,
            "data_root": str(self.root),
            "expected_days": len(expected),
            "feature_days": len(feature_dates & expected) if expected else len(feature_dates),
            "station_history_payload_days": len(station_dates & expected) if expected else len(station_dates),
            "gridded_sst_days": len(gridded_dates & expected) if expected else len(gridded_dates),
            "missing_days": len(missing),
            "missing_dates": [day.isoformat() for day in missing[:20]],
            "first_feature_date": min(feature_dates).isoformat() if feature_dates else None,
            "last_feature_date": max(feature_dates).isoformat() if feature_dates else None,
            "features_path": str(self.features_path),
            "manifest_exists": self.manifest_path.exists(),
        }


def backfill_station_history(
    spec,
    start_date: date,
    end_date: date,
    *,
    root: str | Path | None = None,
    skip_existing: bool = False,
    continue_on_error: bool = False,
    get_json=None,
    get_text=None,
    cutoff_hours: tuple[int, ...] = INTRADAY_CUTOFF_HOURS,
) -> dict[str, Any]:
    store = MarineWaterContrastStore(spec, root=root)
    rows = []
    for target_date in iter_dates(start_date, end_date):
        if skip_existing and store.station_payload_path(target_date).exists():
            rows.append({
                "target_date": target_date.isoformat(),
                "status": "skipped_existing",
                "path": str(store.station_payload_path(target_date)),
            })
            continue
        try:
            payload = fetch_marine_station_history_for_market(
                spec,
                target_date,
                get_json=get_json,
                get_text=get_text,
            )
            path = store.write_station_history_payload(target_date, payload)
            rows.append({
                "target_date": target_date.isoformat(),
                "status": "success",
                "available": payload.get("available"),
                "path": str(path),
                "payload_hash": payload.get("payload_hash"),
            })
        except Exception as exc:  # noqa: BLE001 - backfill ledger should capture source failures
            rows.append({
                "target_date": target_date.isoformat(),
                "status": "failed",
                "error": str(exc),
            })
            if not continue_on_error:
                raise
    feature_rows = store.build_features(cutoff_hours=cutoff_hours)
    return {
        "schema_version": MARINE_WATER_CONTRAST_BACKFILL_SCHEMA_VERSION,
        "source": SOURCE,
        "market_id": spec.id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "rows": rows,
        "success_count": sum(1 for row in rows if row.get("status") == "success"),
        "skipped_existing_count": sum(1 for row in rows if row.get("status") == "skipped_existing"),
        "failed_count": sum(1 for row in rows if row.get("status") == "failed"),
        "feature_rows": len(feature_rows),
        "features_path": str(store.features_path),
    }


def parse_csv_ints(value: str) -> tuple[int, ...]:
    items = []
    for item in str(value or "").split(","):
        item = item.strip()
        if item:
            items.append(int(item))
    return tuple(items)


def cmd_backfill_station_history(args):
    spec = spec_for_id(args.market)
    payload = backfill_station_history(
        spec,
        parse_date(args.start),
        parse_date(args.end),
        root=args.data_root or None,
        skip_existing=args.skip_existing,
        continue_on_error=args.continue_on_error,
        cutoff_hours=parse_csv_ints(args.cutoff_hours) or INTRADAY_CUTOFF_HOURS,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


def cmd_build_features(args):
    spec = spec_for_id(args.market)
    store = MarineWaterContrastStore(spec, root=args.data_root or None)
    forecast_index = load_forecast_daily(args.forecast_daily) if args.forecast_daily else load_forecast_daily(daily_path_for(spec))
    rows = store.build_features(
        forecast_high_index=forecast_index,
        cutoff_hours=parse_csv_ints(args.cutoff_hours) or INTRADAY_CUTOFF_HOURS,
        wall_offsets=parse_csv_ints(args.wall_offsets) or (0,),
    )
    print(f"Wrote {len(rows)} marine water-contrast rows to {store.features_path}")


def cmd_extract_gridded_netcdf(args):
    spec = spec_for_id(args.market)
    store = MarineWaterContrastStore(spec, root=args.data_root or None)
    rows = extract_gridded_sst_points_from_netcdf(
        args.path,
        spec,
        provider=args.provider,
        product=args.product or None,
        source_url=args.source_url or None,
    )
    out = Path(args.out) if args.out else store.write_gridded_sst_points(rows)
    if args.out:
        write_csv_atomic(out, GRIDDED_SST_COLUMNS, rows)
    print(f"Wrote {len(rows)} gridded SST point rows to {out}")


def cmd_coverage(args):
    spec = spec_for_id(args.market)
    store = MarineWaterContrastStore(spec, root=args.data_root or None)
    start = parse_date(args.start) if args.start else None
    end = parse_date(args.end) if args.end else None
    print(json.dumps(store.coverage(start, end), indent=2, sort_keys=True))


def cmd_fleet_coverage(args):
    rows = []
    for spec in all_specs():
        if args.only_configured and not registry_for_market(spec.id):
            continue
        rows.append(MarineWaterContrastStore(spec, root=args.data_root or None).coverage(
            parse_date(args.start) if args.start else None,
            parse_date(args.end) if args.end else None,
        ))
    payload = {
        "schema_version": MARINE_WATER_CONTRAST_BACKFILL_SCHEMA_VERSION,
        "source": SOURCE,
        "market_count": len(rows),
        "markets": rows,
        "summary": {
            "feature_days": sum(row.get("feature_days", 0) for row in rows),
            "missing_days": sum(row.get("missing_days", 0) for row in rows),
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser():
    parser = argparse.ArgumentParser(description="Build marine lake/sea SST contrast sidecars.")
    parser.add_argument("--market", default="toronto")
    parser.add_argument("--data-root", default="")
    sub = parser.add_subparsers(dest="command", required=True)

    backfill = sub.add_parser("backfill-station-history")
    backfill.add_argument("--start", required=True)
    backfill.add_argument("--end", required=True)
    backfill.add_argument("--skip-existing", action="store_true")
    backfill.add_argument("--continue-on-error", action="store_true")
    backfill.add_argument("--cutoff-hours", default=",".join(str(hour) for hour in INTRADAY_CUTOFF_HOURS))
    backfill.set_defaults(func=cmd_backfill_station_history)

    build = sub.add_parser("build-features")
    build.add_argument("--forecast-daily", default="")
    build.add_argument("--cutoff-hours", default=",".join(str(hour) for hour in INTRADAY_CUTOFF_HOURS))
    build.add_argument("--wall-offsets", default="0")
    build.set_defaults(func=cmd_build_features)

    gridded = sub.add_parser("extract-gridded-netcdf")
    gridded.add_argument("--path", required=True)
    gridded.add_argument("--provider", choices=sorted(GRIDDED_SST_PROVIDERS), required=True)
    gridded.add_argument("--product", default="")
    gridded.add_argument("--source-url", default="")
    gridded.add_argument("--out", default="")
    gridded.set_defaults(func=cmd_extract_gridded_netcdf)

    coverage = sub.add_parser("coverage")
    coverage.add_argument("--start", default="")
    coverage.add_argument("--end", default="")
    coverage.set_defaults(func=cmd_coverage)

    fleet = sub.add_parser("fleet-coverage")
    fleet.add_argument("--start", default="")
    fleet.add_argument("--end", default="")
    fleet.add_argument("--only-configured", action="store_true")
    fleet.set_defaults(func=cmd_fleet_coverage)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
