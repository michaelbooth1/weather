"""Open-Meteo source archive helpers for replay-safe backfills.

These helpers normalize payloads from Open-Meteo's historical/replay-compatible
APIs without making any promotion or reporting-gate decisions.
"""
from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from weather.paths import data_path
from weather.sources.forecast_history import HIST_FORECAST_URL
from weather.units import to_float


OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION = "open_meteo_global_model_archive_v0.1"
OPEN_METEO_AIR_QUALITY_ARCHIVE_SCHEMA_VERSION = "open_meteo_air_quality_archive_v0.1"
OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_GLOBAL_MODEL_MEMBERS = (
    "ecmwf_ifs025",
    "ecmwf_aifs025",
    "ncep_aigfs025",
    "gfs_graphcast025",
)
OPEN_METEO_AIR_QUALITY_HOURLY_FIELDS = (
    "pm2_5",
    "pm10",
    "aerosol_optical_depth",
    "dust",
    "us_aqi",
    "european_aqi",
)

GLOBAL_MODEL_HOURLY_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "source",
    "source_url",
    "target_date",
    "valid_time",
    "minute_of_day",
    "temperature_unit",
    "ecmwf_ifs025_temp_native",
    "ecmwf_aifs025_temp_native",
    "ncep_aigfs025_temp_native",
    "gfs_graphcast025_temp_native",
    "model_temp_median",
    "model_temp_spread",
    "payload_hash",
    "fetched_at",
]
GLOBAL_MODEL_DAILY_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "source",
    "source_url",
    "target_date",
    "temperature_unit",
    "ecmwf_ifs025_high_native",
    "ecmwf_aifs025_high_native",
    "ncep_aigfs025_high_native",
    "gfs_graphcast025_high_native",
    "day_max_native",
    "day_high_spread",
    "hourly_rows",
    "payload_hash",
    "fetched_at",
]
AIR_QUALITY_HOURLY_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "source",
    "source_url",
    "target_date",
    "valid_time",
    "minute_of_day",
    "pm2_5",
    "pm10",
    "aerosol_optical_depth",
    "dust",
    "us_aqi",
    "european_aqi",
    "payload_hash",
    "fetched_at",
]


def parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def payload_hash(payload) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def _array_get(mapping, key, index):
    values = (mapping or {}).get(key) or []
    if index >= len(values):
        return None
    return values[index]


def _local_datetime(raw_time, spec):
    parsed = datetime.fromisoformat(str(raw_time))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=spec.tz)
    return parsed.astimezone(spec.tz)


def _median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None


def build_open_meteo_global_model_archive_params(
    spec,
    start_date,
    end_date,
    model_members=OPEN_METEO_GLOBAL_MODEL_MEMBERS,
):
    return {
        "latitude": spec.lat,
        "longitude": spec.lon,
        "start_date": parse_date(start_date).isoformat(),
        "end_date": parse_date(end_date).isoformat(),
        "hourly": "temperature_2m",
        "temperature_unit": spec.om_temperature_unit,
        "timezone": spec.timezone,
        "models": ",".join(model_members),
    }


def build_open_meteo_air_quality_archive_params(
    spec,
    start_date,
    end_date,
    fields=OPEN_METEO_AIR_QUALITY_HOURLY_FIELDS,
):
    return {
        "latitude": spec.lat,
        "longitude": spec.lon,
        "start_date": parse_date(start_date).isoformat(),
        "end_date": parse_date(end_date).isoformat(),
        "hourly": ",".join(fields),
        "timezone": spec.timezone,
    }


def fetch_open_meteo_global_model_archive_payload(spec, start_date, end_date, timeout=30, session=None):
    client = session or requests
    response = client.get(
        HIST_FORECAST_URL,
        params=build_open_meteo_global_model_archive_params(spec, start_date, end_date),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def fetch_open_meteo_air_quality_archive_payload(spec, start_date, end_date, timeout=30, session=None):
    client = session or requests
    response = client.get(
        OPEN_METEO_AIR_QUALITY_URL,
        params=build_open_meteo_air_quality_archive_params(spec, start_date, end_date),
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def normalize_open_meteo_global_model_archive(
    payload,
    spec,
    source_url=HIST_FORECAST_URL,
    fetched_at=None,
    model_members=OPEN_METEO_GLOBAL_MODEL_MEMBERS,
):
    hourly = (payload or {}).get("hourly") or {}
    times = hourly.get("time") or []
    hash_value = payload_hash(payload or {})
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    rows = []
    grouped_highs = defaultdict(lambda: {model: [] for model in model_members})
    for index, raw_time in enumerate(times):
        if not raw_time:
            continue
        try:
            local_dt = _local_datetime(raw_time, spec)
        except ValueError:
            continue
        model_values = {}
        values = []
        for model in model_members:
            value = to_float(_array_get(hourly, f"temperature_2m_{model}", index))
            if value is None and len(model_members) == 1:
                value = to_float(_array_get(hourly, "temperature_2m", index))
            model_values[model] = value
            if value is not None:
                values.append(value)
                grouped_highs[local_dt.date().isoformat()][model].append(value)
        row = {
            "schema_version": OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION,
            "market": spec.id,
            "station": spec.icao,
            "source": "open_meteo_global_models",
            "source_url": source_url,
            "target_date": local_dt.date().isoformat(),
            "valid_time": local_dt.isoformat(),
            "minute_of_day": local_dt.hour * 60 + local_dt.minute,
            "temperature_unit": spec.display_unit,
            "model_temp_median": _median(values),
            "model_temp_spread": max(values) - min(values) if len(values) >= 2 else None,
            "payload_hash": hash_value,
            "fetched_at": fetched_at,
        }
        for model, value in model_values.items():
            row[f"{model}_temp_native"] = value
        rows.append(row)
    daily_rows = []
    for target_date, highs_by_model in sorted(grouped_highs.items()):
        model_highs = {
            model: max(values) if values else None
            for model, values in highs_by_model.items()
        }
        high_values = [value for value in model_highs.values() if value is not None]
        daily = {
            "schema_version": OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION,
            "market": spec.id,
            "station": spec.icao,
            "source": "open_meteo_global_models",
            "source_url": source_url,
            "target_date": target_date,
            "temperature_unit": spec.display_unit,
            "day_max_native": _median(high_values),
            "day_high_spread": max(high_values) - min(high_values) if len(high_values) >= 2 else None,
            "hourly_rows": sum(1 for row in rows if row.get("target_date") == target_date),
            "payload_hash": hash_value,
            "fetched_at": fetched_at,
        }
        for model, value in model_highs.items():
            daily[f"{model}_high_native"] = value
        daily_rows.append(daily)
    return {
        "schema_version": OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION,
        "source": "open_meteo_global_models",
        "market": spec.id,
        "station": spec.icao,
        "source_url": source_url,
        "payload_hash": hash_value,
        "fetched_at": fetched_at,
        "model_members": list(model_members),
        "hourly_rows": rows,
        "daily_rows": daily_rows,
        "raw_payload": payload,
    }


def normalize_open_meteo_air_quality_archive(
    payload,
    spec,
    source_url=OPEN_METEO_AIR_QUALITY_URL,
    fetched_at=None,
    fields=OPEN_METEO_AIR_QUALITY_HOURLY_FIELDS,
):
    hourly = (payload or {}).get("hourly") or {}
    times = hourly.get("time") or []
    hash_value = payload_hash(payload or {})
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    rows = []
    for index, raw_time in enumerate(times):
        if not raw_time:
            continue
        try:
            local_dt = _local_datetime(raw_time, spec)
        except ValueError:
            continue
        row = {
            "schema_version": OPEN_METEO_AIR_QUALITY_ARCHIVE_SCHEMA_VERSION,
            "market": spec.id,
            "station": spec.icao,
            "source": "open_meteo_air_quality",
            "source_url": source_url,
            "target_date": local_dt.date().isoformat(),
            "valid_time": local_dt.isoformat(),
            "minute_of_day": local_dt.hour * 60 + local_dt.minute,
            "payload_hash": hash_value,
            "fetched_at": fetched_at,
        }
        for field in fields:
            row[field] = to_float(_array_get(hourly, field, index))
        rows.append(row)
    return {
        "schema_version": OPEN_METEO_AIR_QUALITY_ARCHIVE_SCHEMA_VERSION,
        "source": "open_meteo_air_quality",
        "market": spec.id,
        "station": spec.icao,
        "source_url": source_url,
        "payload_hash": hash_value,
        "fetched_at": fetched_at,
        "hourly_fields": list(fields),
        "hourly_rows": rows,
        "raw_payload": payload,
    }


def _write_csv(path, columns, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


class OpenMeteoArchiveStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else data_path() / "open_meteo_archives"

    def market_root(self, spec):
        return self.root / spec.icao.lower()

    def write_global_model_archive(self, normalized, spec):
        root = self.market_root(spec) / "global_models"
        hourly_path = root / "hourly.csv"
        daily_path = root / "daily.csv"
        payload_path = root / "raw_payloads" / f"{normalized['payload_hash']}.json"
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(json.dumps(normalized.get("raw_payload") or {}, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        _write_csv(hourly_path, GLOBAL_MODEL_HOURLY_COLUMNS, normalized.get("hourly_rows") or [])
        _write_csv(daily_path, GLOBAL_MODEL_DAILY_COLUMNS, normalized.get("daily_rows") or [])
        return {
            "schema_version": OPEN_METEO_GLOBAL_MODEL_ARCHIVE_SCHEMA_VERSION,
            "hourly_rows": len(normalized.get("hourly_rows") or []),
            "daily_rows": len(normalized.get("daily_rows") or []),
            "hourly_path": str(hourly_path),
            "daily_path": str(daily_path),
            "raw_payload_path": str(payload_path),
        }

    def write_air_quality_archive(self, normalized, spec):
        root = self.market_root(spec) / "air_quality"
        hourly_path = root / "hourly.csv"
        payload_path = root / "raw_payloads" / f"{normalized['payload_hash']}.json"
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text(json.dumps(normalized.get("raw_payload") or {}, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        _write_csv(hourly_path, AIR_QUALITY_HOURLY_COLUMNS, normalized.get("hourly_rows") or [])
        return {
            "schema_version": OPEN_METEO_AIR_QUALITY_ARCHIVE_SCHEMA_VERSION,
            "hourly_rows": len(normalized.get("hourly_rows") or []),
            "hourly_path": str(hourly_path),
            "raw_payload_path": str(payload_path),
        }
