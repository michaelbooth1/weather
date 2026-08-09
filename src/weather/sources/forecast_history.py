"""Legacy historical forecast archive used by serving compatibility paths.

The stitched historical rows and compatibility daily files in this module do
not prove issue-time point-in-time safety. New retraining that requires cutoff-
safe forecasts must use the explicit, training-only contract in
``weather.sources.forecast_training_corpus``. This archive remains the active
serving path and is not overwritten by that corpus.

CLI:
  python -m weather.sources.forecast_history backfill --target-date 2026-07-31 [--start-year 2015] [--end-year 2026]
  python -m weather.sources.forecast_history coverage --target-date 2026-07-31
  python -m weather.sources.forecast_history fleet-coverage --target-date 2026-07-31 --json-out data/backtest/forecast_history_coverage.json
"""
import argparse
import csv
import hashlib
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from weather.paths import data_path
# Keep the retry helper aliases as a compatibility surface for existing callers.
from weather.io import (
    http_error_is_retryable as _is_retryable,
    http_retry_after_seconds as retry_after_seconds,
    http_retry_delay_seconds as retry_delay_seconds,
    request_with_retries,
)

import requests

from weather.market.market_registry import TORONTO, all_specs, spec_for_id
from weather.sources.daily_summary import native_to_c
from weather.units import to_float

HIST_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
RICH_SCHEMA_VERSION = "forecast_history_long_v3"
DAILY_ISSUE_SCHEMA_VERSION = "forecast_history_daily_issue_v1"
FORECAST_HISTORY_COVERAGE_SCHEMA_VERSION = "forecast_history_coverage_v0.1"
DEFAULT_PREVIOUS_RUN_LEADS = (1, 2, 3, 4, 5, 6, 7)
DEFAULT_PREVIOUS_RUN_START_YEAR = 2021
# These defaults mirror the two code-owned trainer inputs. Tests bind them to
# model_constants.HISTORY_WINDOW_DAYS and
# base_retrain.FIRST_RETRAIN_SEASON_RADIUS_DAYS without introducing a runtime
# sources -> model/operations dependency.
DEFAULT_HISTORY_WINDOW_DAYS = 7
DEFAULT_TARGET_WINDOW_DAYS = 7
OPEN_METEO_HOURLY_FIELDS = (
    "temperature_2m",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "shortwave_radiation",
    "wind_speed_10m",
    "cape",
    "temperature_925hPa",
    "temperature_850hPa",
    "geopotential_height_500hPa",
    "direct_radiation",
    "diffuse_radiation",
    "wind_gusts_10m",
    "visibility",
    "precipitation_probability",
    "precipitation",
    "soil_temperature_0cm",
    "soil_moisture_0_to_1cm",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
)
OPEN_METEO_HOURLY_PARAM = ",".join(OPEN_METEO_HOURLY_FIELDS)
RICH_FORECAST_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "source",
    "source_model",
    "temperature_unit",
    "target_date",
    "issue_time",
    "issue_time_basis",
    "lead_hours",
    "lead_days",
    "valid_time",
    "forecast_kind",
    "target_temp_native",
    "target_temp_c",
    "cloud_cover",
    "low_cloud",
    "mid_cloud",
    "high_cloud",
    "shortwave_radiation",
    "wind_speed_kmh",
    "direct_radiation",
    "diffuse_radiation",
    "cape",
    "temperature_925hpa",
    "temperature_850hpa",
    "geopotential_height_500hpa",
    "wind_gust_kmh",
    "visibility",
    "precipitation_probability",
    "precipitation",
    "soil_temperature_0cm",
    "soil_moisture_0_to_1cm",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
    "source_url",
    "payload_hash",
]
RICH_CORE_REQUIRED_NON_NULL_FIELDS = (
    "cloud_cover",
    "low_cloud",
    "mid_cloud",
    "high_cloud",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
)
RICH_AUDIT_NON_NULL_FIELDS = RICH_CORE_REQUIRED_NON_NULL_FIELDS + (
    "cape",
    "temperature_925hpa",
    "temperature_850hpa",
    "geopotential_height_500hpa",
    "wind_gust_kmh",
    "visibility",
    "precipitation_probability",
    "precipitation",
    "soil_temperature_0cm",
    "soil_moisture_0_to_1cm",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
)
DAILY_ISSUE_COLUMNS = [
    "schema_version",
    "market",
    "station",
    "source",
    "source_model",
    "temperature_unit",
    "target_date",
    "issue_time",
    "issue_time_basis",
    "lead_hours",
    "lead_days",
    "forecast_high_native",
    "forecast_high_c",
    "hourly_rows",
]


def data_root_for(spec):
    return data_path() / "forecast_history" / spec.icao.lower()


def daily_path_for(spec):
    return data_root_for(spec) / "forecast_daily.csv"


def long_path_for(spec):
    return data_root_for(spec) / "forecast_long.csv"


def daily_issue_path_for(spec):
    return data_root_for(spec) / "forecast_daily_by_issue.csv"


# Toronto defaults so load_forecast_daily() and existing callers keep working.
DATA_ROOT = data_root_for(TORONTO)
DAILY_PATH = daily_path_for(TORONTO)
MANIFEST_PATH = DATA_ROOT / "manifest.json"


def _target_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("target_date must be an ISO date") from exc


def _anchor_in_year(target_date, year):
    target = _target_date(target_date)
    try:
        return target.replace(year=int(year))
    except ValueError:
        if target.month == 2 and target.day == 29:
            return date(int(year), 2, 28)
        raise


def archive_window_for_target(
    year,
    target_date,
    *,
    target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
    history_window_days=DEFAULT_HISTORY_WINDOW_DAYS,
):
    """Return the prior-year archive window needed for a training target.

    The trainer selects target-date +/- ``target_window_days``. Each selected
    date also needs the climatology halo, so the archive radius is the sum of
    the two existing inputs rather than a fixed month/day season.
    """
    target_window_days = int(target_window_days)
    history_window_days = int(history_window_days)
    if target_window_days < 0 or history_window_days < 0:
        raise ValueError("target and history window days must be non-negative")
    anchor = _anchor_in_year(target_date, year)
    radius_days = target_window_days + history_window_days
    return anchor - timedelta(days=radius_days), anchor + timedelta(days=radius_days)


def season_start_end(
    year,
    target_date,
    *,
    target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
    history_window_days=DEFAULT_HISTORY_WINDOW_DAYS,
    today=None,
):
    """Return the effective provider request bounds for one analog year."""
    start_date, end_date = archive_window_for_target(
        year,
        target_date,
        target_window_days=target_window_days,
        history_window_days=history_window_days,
    )
    current = today or date.today()
    if int(year) == current.year and end_date > current:
        end_date = current
    if end_date < start_date:
        raise ValueError("target-derived archive window has not begun")
    return start_date.isoformat(), end_date.isoformat()


def target_window_contract(
    target_date,
    years,
    *,
    target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
    history_window_days=DEFAULT_HISTORY_WINDOW_DAYS,
    today=None,
):
    """Describe the caller-declared archive target independently of evidence."""
    target = _target_date(target_date)
    normalized_years = sorted({int(year) for year in years})
    if not normalized_years:
        raise ValueError("target window contract requires at least one year")
    requested_by_year = {}
    fetched_by_year = {}
    for year in normalized_years:
        requested_start, requested_end = archive_window_for_target(
            year,
            target,
            target_window_days=target_window_days,
            history_window_days=history_window_days,
        )
        fetched_start, fetched_end = season_start_end(
            year,
            target,
            target_window_days=target_window_days,
            history_window_days=history_window_days,
            today=today,
        )
        requested_by_year[str(year)] = {
            "start": requested_start.isoformat(),
            "end": requested_end.isoformat(),
        }
        fetched_by_year[str(year)] = {"start": fetched_start, "end": fetched_end}
    target_window_days = int(target_window_days)
    history_window_days = int(history_window_days)
    return {
        "target_date": target.isoformat(),
        "target_window_days": target_window_days,
        "history_window_days": history_window_days,
        "archive_radius_days": target_window_days + history_window_days,
        "requested_by_year": requested_by_year,
        "fetched_by_year": fetched_by_year,
    }


def forecast_payload_hash(row):
    payload = {key: row.get(key) for key in row if key != "payload_hash"}
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def first_present(row, *keys):
    for key in keys:
        value = (row or {}).get(key)
        if value not in (None, ""):
            return value
    return None


def row_value(row, *keys):
    row = row or {}
    for key in keys:
        value = to_float(row.get(key))
        if value is not None:
            return value
    return None


def row_temp_native(row):
    return row_value(
        row,
        "temp_native",
        "temperature_native",
        "target_temp_native",
        "temp_c",
        "target_temp_c",
    )


def row_forecast_high_native(row):
    return row_value(
        row,
        "forecast_high_native",
        "day_max_native",
        "forecast_high",
        "day_max",
        "forecast_high_c",
        "day_max_c",
    )


def hourly_value(hourly, key, index):
    values = (hourly or {}).get(key) or []
    return to_float(values[index] if index < len(values) else None)


def local_valid_datetime(raw_time, spec):
    dt = datetime.fromisoformat(str(raw_time))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=spec.tz)
    return dt.astimezone(spec.tz)


def rich_row(
    spec,
    source,
    source_model,
    target_date,
    valid_time,
    target_temp_native,
    issue_time="",
    issue_time_basis="",
    lead_days="",
    cloud_cover=None,
    low_cloud=None,
    mid_cloud=None,
    high_cloud=None,
    shortwave_radiation=None,
    wind_speed_kmh=None,
    direct_radiation=None,
    diffuse_radiation=None,
    cape=None,
    temperature_925hpa=None,
    temperature_850hpa=None,
    geopotential_height_500hpa=None,
    wind_gust_kmh=None,
    visibility=None,
    precipitation_probability=None,
    precipitation=None,
    soil_temperature_0cm=None,
    soil_moisture_0_to_1cm=None,
    vapour_pressure_deficit=None,
    et0_fao_evapotranspiration=None,
    source_url=HIST_FORECAST_URL,
):
    lead_hours = ""
    if lead_days not in ("", None):
        lead_hours = int(lead_days) * 24
    row = {
        "schema_version": RICH_SCHEMA_VERSION,
        "market": spec.id,
        "station": spec.icao,
        "source": source,
        "source_model": source_model,
        "temperature_unit": spec.display_unit,
        "target_date": target_date,
        "issue_time": issue_time,
        "issue_time_basis": issue_time_basis,
        "lead_hours": lead_hours,
        "lead_days": lead_days,
        "valid_time": valid_time,
        "forecast_kind": "hourly",
        "target_temp_native": target_temp_native,
        "target_temp_c": native_to_c(target_temp_native, spec.display_unit),
        "cloud_cover": cloud_cover,
        "low_cloud": low_cloud,
        "mid_cloud": mid_cloud,
        "high_cloud": high_cloud,
        "shortwave_radiation": shortwave_radiation,
        "wind_speed_kmh": wind_speed_kmh,
        "direct_radiation": direct_radiation,
        "diffuse_radiation": diffuse_radiation,
        "cape": cape,
        "temperature_925hpa": temperature_925hpa,
        "temperature_850hpa": temperature_850hpa,
        "geopotential_height_500hpa": geopotential_height_500hpa,
        "wind_gust_kmh": wind_gust_kmh,
        "visibility": visibility,
        "precipitation_probability": precipitation_probability,
        "precipitation": precipitation,
        "soil_temperature_0cm": soil_temperature_0cm,
        "soil_moisture_0_to_1cm": soil_moisture_0_to_1cm,
        "vapour_pressure_deficit": vapour_pressure_deficit,
        "et0_fao_evapotranspiration": et0_fao_evapotranspiration,
        "source_url": source_url,
    }
    row["payload_hash"] = forecast_payload_hash(row)
    return row


def historical_forecast_rows(payload, spec=TORONTO, source_model="best_match"):
    hourly = payload.get("hourly", {}) or {}
    times = hourly.get("time") or []
    temps = hourly.get("temperature_2m") or []
    rows = []
    for index, raw_time in enumerate(times):
        temp = to_float(temps[index] if index < len(temps) else None)
        if temp is None or not raw_time:
            continue
        valid_dt = local_valid_datetime(raw_time, spec)
        rows.append(rich_row(
            spec,
            source="open_meteo_historical_forecast",
            source_model=source_model,
            target_date=valid_dt.date().isoformat(),
            valid_time=valid_dt.isoformat(),
            target_temp_native=temp,
            issue_time="",
            issue_time_basis="stitched_continuous_archive",
            lead_days="",
            cloud_cover=hourly_value(hourly, "cloud_cover", index),
            low_cloud=hourly_value(hourly, "cloud_cover_low", index),
            mid_cloud=hourly_value(hourly, "cloud_cover_mid", index),
            high_cloud=hourly_value(hourly, "cloud_cover_high", index),
            shortwave_radiation=hourly_value(hourly, "shortwave_radiation", index),
            wind_speed_kmh=hourly_value(hourly, "wind_speed_10m", index),
            direct_radiation=hourly_value(hourly, "direct_radiation", index),
            diffuse_radiation=hourly_value(hourly, "diffuse_radiation", index),
            cape=hourly_value(hourly, "cape", index),
            temperature_925hpa=hourly_value(hourly, "temperature_925hPa", index),
            temperature_850hpa=hourly_value(hourly, "temperature_850hPa", index),
            geopotential_height_500hpa=hourly_value(hourly, "geopotential_height_500hPa", index),
            wind_gust_kmh=hourly_value(hourly, "wind_gusts_10m", index),
            visibility=hourly_value(hourly, "visibility", index),
            precipitation_probability=hourly_value(hourly, "precipitation_probability", index),
            precipitation=hourly_value(hourly, "precipitation", index),
            soil_temperature_0cm=hourly_value(hourly, "soil_temperature_0cm", index),
            soil_moisture_0_to_1cm=hourly_value(hourly, "soil_moisture_0_to_1cm", index),
            vapour_pressure_deficit=hourly_value(hourly, "vapour_pressure_deficit", index),
            et0_fao_evapotranspiration=hourly_value(hourly, "et0_fao_evapotranspiration", index),
            source_url=HIST_FORECAST_URL,
        ))
    return rows


def previous_run_rows(payload, spec=TORONTO, leads=DEFAULT_PREVIOUS_RUN_LEADS, source_model="best_match"):
    hourly = payload.get("hourly", {}) or {}
    times = hourly.get("time") or []
    rows = []
    for index, raw_time in enumerate(times):
        if not raw_time:
            continue
        valid_dt = local_valid_datetime(raw_time, spec)
        for lead in leads:
            key = f"temperature_2m_previous_day{lead}"
            values = hourly.get(key) or []
            temp = to_float(values[index] if index < len(values) else None)
            if temp is None:
                continue
            issue_date = valid_dt.date() - timedelta(days=int(lead))
            issue_dt = datetime(issue_date.year, issue_date.month, issue_date.day, tzinfo=spec.tz)
            rows.append(rich_row(
                spec,
                source="open_meteo_previous_runs",
                source_model=source_model,
                target_date=valid_dt.date().isoformat(),
                valid_time=valid_dt.isoformat(),
                target_temp_native=temp,
                issue_time=issue_dt.isoformat(),
                issue_time_basis="fixed_lead_day_offset",
                lead_days=int(lead),
                source_url=PREVIOUS_RUNS_URL,
            ))
    return rows


def daily_issue_rows(hourly_rows):
    grouped = defaultdict(list)
    for row in hourly_rows:
        temp = to_float(row.get("target_temp_native"))
        if temp is None:
            continue
        key = (
            row.get("market"),
            row.get("station"),
            row.get("source"),
            row.get("source_model"),
            row.get("temperature_unit"),
            row.get("target_date"),
            row.get("issue_time"),
            row.get("issue_time_basis"),
            row.get("lead_hours"),
            row.get("lead_days"),
        )
        grouped[key].append(temp)
    rows = []
    for key, temps in sorted(grouped.items(), key=lambda item: tuple("" if value is None else str(value) for value in item[0])):
        (
            market,
            station,
            source,
            source_model,
            unit,
            target_date,
            issue_time,
            issue_time_basis,
            lead_hours,
            lead_days,
        ) = key
        high = max(temps)
        rows.append({
            "schema_version": DAILY_ISSUE_SCHEMA_VERSION,
            "market": market,
            "station": station,
            "source": source,
            "source_model": source_model,
            "temperature_unit": unit,
            "target_date": target_date,
            "issue_time": issue_time,
            "issue_time_basis": issue_time_basis,
            "lead_hours": lead_hours,
            "lead_days": lead_days,
            "forecast_high_native": high,
            "forecast_high_c": native_to_c(high, unit),
            "hourly_rows": len(temps),
        })
    return rows


def compatibility_daily_from_rows(hourly_rows):
    daily = {}
    for row in hourly_rows:
        if row.get("source") != "open_meteo_historical_forecast":
            continue
        temp = to_float(row.get("target_temp_native"))
        day = row.get("target_date")
        if temp is None or not day:
            continue
        daily[day] = max(daily.get(day, float("-inf")), temp)
    return {d: v for d, v in daily.items() if v != float("-inf")}


def load_forecast_profiles(path=None, source="open_meteo_historical_forecast"):
    """target_date -> hourly forecast rows in the market's native unit.

    This powers cutoff-specific forecast-shape features without leaking the
    observed outcome. Old v1 files simply return ``None`` for newly added
    radiation/cloud-layer fields until the archive is backfilled.
    """
    path = Path(path or long_path_for(TORONTO))
    if not path.exists():
        return {}
    profiles = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if source and row.get("source") != source:
                continue
            target_date = row.get("target_date")
            if not target_date:
                continue
            minute = ""
            valid_time = row.get("valid_time")
            if valid_time:
                try:
                    valid_dt = datetime.fromisoformat(str(valid_time).replace("Z", "+00:00"))
                    minute = valid_dt.hour * 60 + valid_dt.minute
                except ValueError:
                    minute = ""
            temp_native = row_temp_native(row)
            profiles[target_date].append({
                "minute_of_day": minute,
                "time": valid_time,
                "temp_native": temp_native,
                "temp_c": temp_native,
                "cloud_cover": to_float(row.get("cloud_cover")),
                "low_cloud": to_float(first_present(row, "low_cloud", "cloud_cover_low")),
                "mid_cloud": to_float(first_present(row, "mid_cloud", "cloud_cover_mid")),
                "high_cloud": to_float(first_present(row, "high_cloud", "cloud_cover_high")),
                "solar": to_float(first_present(row, "shortwave_radiation", "solar")),
                "wind_kmh": to_float(row.get("wind_speed_kmh")),
                "direct_radiation": to_float(row.get("direct_radiation")),
                "diffuse_radiation": to_float(row.get("diffuse_radiation")),
                "cape": to_float(row.get("cape")),
                "temperature_925hpa": to_float(first_present(
                    row,
                    "temperature_925hpa",
                    "temperature_925hPa",
                )),
                "temperature_850hpa": to_float(first_present(
                    row,
                    "temperature_850hpa",
                    "temperature_850hPa",
                )),
                "geopotential_height_500hpa": to_float(first_present(
                    row,
                    "geopotential_height_500hpa",
                    "geopotential_height_500hPa",
                )),
                "wind_gust_kmh": to_float(first_present(row, "wind_gust_kmh", "wind_gusts_10m")),
                "visibility": to_float(row.get("visibility")),
                "precipitation_probability": to_float(row.get("precipitation_probability")),
                "precipitation": to_float(row.get("precipitation")),
                "soil_temperature_0cm": to_float(row.get("soil_temperature_0cm")),
                "soil_moisture_0_to_1cm": to_float(row.get("soil_moisture_0_to_1cm")),
                "vapour_pressure_deficit": to_float(row.get("vapour_pressure_deficit")),
                "et0_fao_evapotranspiration": to_float(row.get("et0_fao_evapotranspiration")),
            })
    return dict(profiles)


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def fetch_historical_forecast_payload(
    year,
    spec=TORONTO,
    timeout=30,
    *,
    target_date,
    target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
    history_window_days=DEFAULT_HISTORY_WINDOW_DAYS,
):
    start, end = season_start_end(
        year,
        target_date,
        target_window_days=target_window_days,
        history_window_days=history_window_days,
    )

    def _once():
        resp = requests.get(HIST_FORECAST_URL, params={
            "latitude": spec.lat,
            "longitude": spec.lon,
            "start_date": start,
            "end_date": end,
            "hourly": OPEN_METEO_HOURLY_PARAM,
            "temperature_unit": spec.om_temperature_unit,
            "wind_speed_unit": "kmh",
            "timezone": spec.timezone,
        }, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    return request_with_retries(_once)


def fetch_previous_runs_payload(
    year,
    spec=TORONTO,
    leads=DEFAULT_PREVIOUS_RUN_LEADS,
    source_model="best_match",
    timeout=30,
    *,
    target_date,
    target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
    history_window_days=DEFAULT_HISTORY_WINDOW_DAYS,
):
    start, end = season_start_end(
        year,
        target_date,
        target_window_days=target_window_days,
        history_window_days=history_window_days,
    )
    hourly = ",".join(f"temperature_2m_previous_day{lead}" for lead in leads)

    def _once():
        params = {
            "latitude": spec.lat,
            "longitude": spec.lon,
            "start_date": start,
            "end_date": end,
            "hourly": hourly,
            "temperature_unit": spec.om_temperature_unit,
            "timezone": spec.timezone,
        }
        if source_model and source_model != "best_match":
            params["models"] = source_model
        resp = requests.get(PREVIOUS_RUNS_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    return request_with_retries(_once)


def fetch_year_forecast(
    year,
    spec=TORONTO,
    timeout=30,
    *,
    target_date,
    target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
    history_window_days=DEFAULT_HISTORY_WINDOW_DAYS,
):
    """Return {local_date_iso: forecast_daily_max_native} for compatibility."""
    payload = fetch_historical_forecast_payload(
        year,
        spec,
        timeout=timeout,
        target_date=target_date,
        target_window_days=target_window_days,
        history_window_days=history_window_days,
    )
    return compatibility_daily_from_rows(historical_forecast_rows(payload, spec))


def load_forecast_daily(path=DAILY_PATH):
    """date_iso -> forecast high in the market's native unit."""
    index = {}
    if not Path(path).exists():
        return index
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            d = row.get("local_date")
            v = row_forecast_high_native(row)
            if d and v is not None:
                index[d] = v
    return index


def backfill(
    start_year,
    end_year,
    spec=TORONTO,
    pause=0.4,
    include_previous_runs=True,
    previous_runs_start_year=DEFAULT_PREVIOUS_RUN_START_YEAR,
    previous_runs_leads=DEFAULT_PREVIOUS_RUN_LEADS,
    previous_runs_model="best_match",
    *,
    target_date,
    target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
    history_window_days=DEFAULT_HISTORY_WINDOW_DAYS,
):
    if int(end_year) < int(start_year):
        raise ValueError("end_year must be greater than or equal to start_year")
    target = _target_date(target_date)
    window_contract = target_window_contract(
        target,
        range(start_year, end_year + 1),
        target_window_days=target_window_days,
        history_window_days=history_window_days,
    )
    data_root = data_root_for(spec)
    daily_path = daily_path_for(spec)
    long_path = long_path_for(spec)
    daily_issue_path = daily_issue_path_for(spec)
    manifest_path = data_root / "manifest.json"
    data_root.mkdir(parents=True, exist_ok=True)
    rows = {}
    rich_rows = []
    per_year = {}
    previous_per_year = {}
    for year in range(start_year, end_year + 1):
        try:
            payload = fetch_historical_forecast_payload(
                year,
                spec,
                target_date=target,
                target_window_days=target_window_days,
                history_window_days=history_window_days,
            )
            year_rows = historical_forecast_rows(payload, spec)
            year_daily = compatibility_daily_from_rows(year_rows)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  {year}: ERROR {type(exc).__name__}: {exc}")
            per_year[year] = 0
            year_rows = []
            year_daily = {}
        rich_rows.extend(year_rows)
        if include_previous_runs and year >= int(previous_runs_start_year):
            try:
                previous_payload = fetch_previous_runs_payload(
                    year,
                    spec,
                    leads=previous_runs_leads,
                    source_model=previous_runs_model,
                    target_date=target,
                    target_window_days=target_window_days,
                    history_window_days=history_window_days,
                )
                previous_rows = previous_run_rows(
                    previous_payload,
                    spec,
                    leads=previous_runs_leads,
                    source_model=previous_runs_model,
                )
            except Exception as exc:  # noqa: BLE001 - previous-runs availability varies by model/year
                print(f"  {year}: previous-runs ERROR {type(exc).__name__}: {exc}")
                previous_rows = []
            rich_rows.extend(previous_rows)
            previous_per_year[year] = len(previous_rows)
        elif include_previous_runs:
            previous_per_year[year] = 0
        if not year_daily:
            continue
        per_year[year] = len(year_daily)
        rows.update(year_daily)
        print(f"  {year}: {len(year_daily)} forecast-days "
              f"({min(year_daily.values()):.1f}..{max(year_daily.values()):.1f} {spec.display_unit})"
              if year_daily else f"  {year}: no data")
        time.sleep(pause)

    ordered = sorted(rows.items())
    with daily_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["local_date", "forecast_high_c"])
        for d, v in ordered:
            writer.writerow([d, f"{v:.1f}"])

    rich_rows.sort(key=lambda row: (
        row.get("target_date") or "",
        row.get("source") or "",
        str(row.get("lead_days") or ""),
        row.get("valid_time") or "",
    ))
    write_csv(long_path, RICH_FORECAST_COLUMNS, rich_rows)
    issue_rows = daily_issue_rows(rich_rows)
    write_csv(daily_issue_path, DAILY_ISSUE_COLUMNS, issue_rows)

    covered_years = sorted(y for y, n in per_year.items() if n > 0)
    manifest = {
        "endpoints": {
            "historical_forecast": HIST_FORECAST_URL,
            "previous_runs": PREVIOUS_RUNS_URL,
        },
        "market": spec.id,
        "params": {"latitude": spec.lat, "longitude": spec.lon,
                   "hourly": OPEN_METEO_HOURLY_PARAM, "timezone": spec.timezone},
        "previous_runs": {
            "enabled": bool(include_previous_runs),
            "start_year": int(previous_runs_start_year),
            "leads": list(previous_runs_leads),
            "model": previous_runs_model,
            "per_year_rows": previous_per_year,
        },
        "schema_versions": {
            "long": RICH_SCHEMA_VERSION,
            "daily_by_issue": DAILY_ISSUE_SCHEMA_VERSION,
            "compatibility_daily": "forecast_daily_legacy_v1",
        },
        "target_window": window_contract,
        "generated_at": datetime.now().isoformat(),
        "total_days": len(ordered),
        "long_rows": len(rich_rows),
        "daily_issue_rows": len(issue_rows),
        "covered_years": covered_years,
        "per_year_days": per_year,
    }
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)

    print(f"\n=== Coverage ({spec.id}) ===")
    print(f"  years with data : {covered_years[0] if covered_years else '-'}"
          f"..{covered_years[-1] if covered_years else '-'} ({len(covered_years)} years)")
    print(f"  total forecast-days: {len(ordered)}")
    print(f"  long source/issue rows: {len(rich_rows)}")
    print(f"  daily source/issue rows: {len(issue_rows)}")
    print(f"  written to {daily_path}")
    return manifest


def coverage(
    spec=TORONTO,
    *,
    target_date,
    required_years=None,
    target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
    history_window_days=DEFAULT_HISTORY_WINDOW_DAYS,
):
    report = forecast_history_coverage(
        spec,
        target_date=target_date,
        required_years=required_years,
        target_window_days=target_window_days,
        history_window_days=history_window_days,
    )
    print(
        f"[{spec.id}] forecast history {report['status']} for target "
        f"{report['declared_target']['target_date']}: "
        f"{report['covered_required_date_count']}/{report['required_date_count']} required dates, "
        f"manifest={report['manifest_target_status']}"
    )
    return report


def _nonnull(value):
    return value not in (None, "")


def _coverage_target_requirement(
    target_date,
    required_years,
    *,
    target_window_days,
    history_window_days,
):
    target = _target_date(target_date)
    years = (
        sorted({int(year) for year in required_years})
        if required_years is not None
        else list(range(DEFAULT_PREVIOUS_RUN_START_YEAR, target.year))
    )
    if not years:
        raise ValueError("coverage requires at least one caller- or policy-declared year")
    return target_window_contract(
        target,
        years,
        target_window_days=target_window_days,
        history_window_days=history_window_days,
    )


def _required_target_dates(requirement):
    required = set()
    for bounds in requirement.get("requested_by_year", {}).values():
        start = date.fromisoformat(bounds["start"])
        end = date.fromisoformat(bounds["end"])
        required.update(
            (start + timedelta(days=offset)).isoformat()
            for offset in range((end - start).days + 1)
        )
    return required


def _load_target_manifest(path):
    if not path.exists():
        return None, "MISSING"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "INVALID"
    if not isinstance(payload, dict):
        return None, "INVALID"
    return payload, "READABLE"


def _manifest_target_status(manifest, requirement):
    if manifest is None:
        return "MISSING"
    declared = manifest.get("target_window")
    if not isinstance(declared, dict):
        return "UNDECLARED"
    scalar_fields = (
        "target_date",
        "target_window_days",
        "history_window_days",
        "archive_radius_days",
    )
    if any(declared.get(field) != requirement.get(field) for field in scalar_fields):
        return "MISMATCH"
    declared_windows = declared.get("requested_by_year")
    if not isinstance(declared_windows, dict):
        return "MISMATCH"
    for year, expected in requirement.get("requested_by_year", {}).items():
        if declared_windows.get(year) != expected:
            return "MISMATCH"
    return "MATCH"


def forecast_history_coverage(
    spec=TORONTO,
    path=None,
    required_fields=None,
    *,
    target_date,
    required_years=None,
    target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
    history_window_days=DEFAULT_HISTORY_WINDOW_DAYS,
    manifest_path=None,
):
    """Summarize one archive against a caller-declared training target."""
    path = Path(path) if path else long_path_for(spec)
    manifest_path = Path(manifest_path) if manifest_path else path.parent / "manifest.json"
    required_fields = tuple(required_fields or RICH_CORE_REQUIRED_NON_NULL_FIELDS)
    audit_fields = tuple(dict.fromkeys(RICH_AUDIT_NON_NULL_FIELDS + required_fields))
    target_requirement = _coverage_target_requirement(
        target_date,
        required_years,
        target_window_days=target_window_days,
        history_window_days=history_window_days,
    )
    required_dates = _required_target_dates(target_requirement)
    row_count = 0
    historical_rows = 0
    dates = set()
    schemas = defaultdict(int)
    nonnull_fields = {field: 0 for field in audit_fields}
    header = []
    if not path.exists():
        return {
            "market": spec.id,
            "station": spec.icao,
            "path": str(path),
            "exists": False,
            "header_ok": False,
            "rows": 0,
            "historical_rows": 0,
            "days": 0,
            "years": "",
            "schemas": {},
            "nonnull_fields": nonnull_fields,
            "missing_nonnull_fields": list(required_fields),
            "partial_nonnull_fields": {},
            "incomplete_required_fields": list(required_fields),
            "declared_target": target_requirement,
            "required_date_count": len(required_dates),
            "covered_required_date_count": 0,
            "missing_required_date_count": len(required_dates),
            "missing_required_date_samples": sorted(required_dates)[:20],
            "date_range_relevant": False,
            "manifest_path": str(manifest_path),
            "manifest_target_status": "MISSING",
            "manifest_target_matches": False,
            "blockers": ["archive_file_missing"],
            "target_status": "BLOCK",
            "status": "MISSING",
        }
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        for row in reader:
            row_count += 1
            schema = row.get("schema_version") or ""
            if schema:
                schemas[schema] += 1
            if row.get("source") != "open_meteo_historical_forecast":
                continue
            historical_rows += 1
            target_date = row.get("target_date")
            if target_date:
                dates.add(target_date)
            for field in audit_fields:
                if _nonnull(row.get(field)):
                    nonnull_fields[field] += 1
    years = sorted({item[:4] for item in dates if len(item) >= 4})
    missing_fields = [
        field for field in audit_fields
        if historical_rows == 0 or nonnull_fields.get(field, 0) == 0
    ]
    partial_fields = {
        field: nonnull_fields.get(field, 0)
        for field in audit_fields
        if 0 < nonnull_fields.get(field, 0) < historical_rows
    }
    incomplete_required_fields = [
        field for field in required_fields
        if historical_rows == 0 or nonnull_fields.get(field, 0) < historical_rows
    ]
    header_ok = header == RICH_FORECAST_COLUMNS
    schema_ok = bool(schemas) and set(schemas) == {RICH_SCHEMA_VERSION}
    missing_required_dates = sorted(required_dates - dates)
    date_range_relevant = not missing_required_dates
    manifest, manifest_read_status = _load_target_manifest(manifest_path)
    manifest_target_status = (
        _manifest_target_status(manifest, target_requirement)
        if manifest_read_status == "READABLE"
        else manifest_read_status
    )
    blockers = []
    if not header_ok:
        blockers.append("header_mismatch")
    if not schema_ok:
        blockers.append("schema_mismatch")
    if historical_rows <= 0:
        blockers.append("historical_rows_missing")
    if incomplete_required_fields:
        blockers.append("required_fields_incomplete")
    if not date_range_relevant:
        blockers.append("declared_target_dates_missing")
    if manifest_target_status != "MATCH":
        blockers.append("archive_target_manifest_mismatch")
    status = "OK" if not blockers else "FAIL"
    return {
        "market": spec.id,
        "station": spec.icao,
        "path": str(path),
        "exists": True,
        "header_ok": header_ok,
        "rows": row_count,
        "historical_rows": historical_rows,
        "days": len(dates),
        "years": f"{years[0]}..{years[-1]}" if years else "",
        "schemas": dict(sorted(schemas.items())),
        "nonnull_fields": nonnull_fields,
        "missing_nonnull_fields": missing_fields,
        "partial_nonnull_fields": partial_fields,
        "incomplete_required_fields": incomplete_required_fields,
        "declared_target": target_requirement,
        "required_date_count": len(required_dates),
        "covered_required_date_count": len(required_dates & dates),
        "missing_required_date_count": len(missing_required_dates),
        "missing_required_date_samples": missing_required_dates[:20],
        "date_range_relevant": date_range_relevant,
        "manifest_path": str(manifest_path),
        "manifest_target_status": manifest_target_status,
        "manifest_target_matches": manifest_target_status == "MATCH",
        "blockers": blockers,
        "target_status": "PASS" if not blockers else "BLOCK",
        "status": status,
    }


def _market_ids(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def forecast_history_fleet_coverage(
    target_date,
    market_ids=None,
    required_fields=None,
    *,
    required_years=None,
    target_window_days=DEFAULT_TARGET_WINDOW_DAYS,
    history_window_days=DEFAULT_HISTORY_WINDOW_DAYS,
):
    ids = set(market_ids or [])
    specs = [spec for spec in all_specs() if not ids or spec.id in ids]
    declared_years = (
        tuple(sorted({int(year) for year in required_years}))
        if required_years is not None
        else None
    )
    target_requirement = _coverage_target_requirement(
        target_date,
        declared_years,
        target_window_days=target_window_days,
        history_window_days=history_window_days,
    )
    markets = [
        forecast_history_coverage(
            spec,
            required_fields=required_fields,
            target_date=target_date,
            required_years=declared_years,
            target_window_days=target_window_days,
            history_window_days=history_window_days,
        )
        for spec in specs
    ]
    ok_count = sum(1 for row in markets if row.get("status") == "OK")
    return {
        "schema_version": FORECAST_HISTORY_COVERAGE_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(),
        "status": "PASS" if markets and ok_count == len(markets) else "BLOCK",
        "declared_target": target_requirement,
        "required_fields": list(required_fields or RICH_CORE_REQUIRED_NON_NULL_FIELDS),
        "audit_fields": list(RICH_AUDIT_NON_NULL_FIELDS),
        "summary": {
            "market_count": len(markets),
            "ok_market_count": ok_count,
            "failed_market_count": len(markets) - ok_count,
            "all_active_markets_backfilled": bool(markets) and ok_count == len(markets),
        },
        "markets": markets,
    }


def render_forecast_history_coverage_markdown(payload):
    summary = payload.get("summary") or {}
    target = payload.get("declared_target") or {}
    lines = [
        "# Forecast History Coverage",
        "",
        f"- Schema: `{payload.get('schema_version')}`",
        f"- Gate status: `{payload.get('status', 'BLOCK')}`",
        f"- Declared target: `{target.get('target_date') or '-'}`",
        f"- Target window days: `+/-{target.get('target_window_days', 0)}`",
        f"- Climatology halo days: `+/-{target.get('history_window_days', 0)}`",
        f"- Markets OK: {summary.get('ok_market_count', 0)}/{summary.get('market_count', 0)}",
        f"- All active markets backfilled: {summary.get('all_active_markets_backfilled')}",
        "",
        "| Market | Status | Rows | Historical rows | Required dates | Missing target dates | Manifest | Years | Header | Schemas | Missing fields | Partial fields | Blockers |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("markets") or []:
        schemas = ", ".join(f"{key}:{value}" for key, value in (row.get("schemas") or {}).items()) or "-"
        missing = ", ".join(row.get("missing_nonnull_fields") or []) or "-"
        partial = ", ".join(
            f"{key}:{value}" for key, value in (row.get("partial_nonnull_fields") or {}).items()
        ) or "-"
        blockers = ", ".join(row.get("blockers") or []) or "-"
        lines.append(
            f"| {row.get('market')} | {row.get('status')} | {row.get('rows', 0)} | "
            f"{row.get('historical_rows', 0)} | {row.get('required_date_count', 0)} | "
            f"{row.get('missing_required_date_count', 0)} | {row.get('manifest_target_status', '-')} | "
            f"{row.get('years') or '-'} | {row.get('header_ok')} | {schemas} | "
            f"{missing} | {partial} | {blockers} |"
        )
    return "\n".join(lines) + "\n"


def write_forecast_history_coverage_outputs(payload, json_out=None, markdown_out=None):
    if json_out:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if markdown_out:
        path = Path(markdown_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_forecast_history_coverage_markdown(payload), encoding="utf-8")


def parse_leads(value):
    if not value:
        return DEFAULT_PREVIOUS_RUN_LEADS
    return tuple(int(item.strip()) for item in str(value).split(",") if item.strip())


def parse_years(value):
    if not value:
        return None
    years = tuple(sorted({int(item.strip()) for item in str(value).split(",") if item.strip()}))
    if not years:
        raise ValueError("at least one required year must be declared")
    return years


def add_target_arguments(parser, *, include_years=False):
    parser.add_argument(
        "--target-date",
        required=True,
        help="Training target date (ISO); never inferred from the archive manifest.",
    )
    parser.add_argument(
        "--target-window-days",
        type=int,
        default=DEFAULT_TARGET_WINDOW_DAYS,
        help="Trainer-selected target radius; defaults to the current +/-7 policy.",
    )
    parser.add_argument(
        "--history-window-days",
        type=int,
        default=DEFAULT_HISTORY_WINDOW_DAYS,
        help="Climatology halo around each selected date; defaults to HISTORY_WINDOW_DAYS.",
    )
    if include_years:
        parser.add_argument(
            "--years",
            default="",
            help="Comma-separated required years; default policy is 2021 through target_year-1.",
        )


def main():
    parser = argparse.ArgumentParser(description="Backfill archived Open-Meteo forecasts.")
    parser.add_argument("--market", default="toronto",
                        help="Registered market id (toronto, nyc, ...); sets geo + data root.")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--start-year", type=int, default=2015)
    b.add_argument("--end-year", type=int, default=datetime.now().year)
    b.add_argument("--pause", type=float, default=0.4)
    b.add_argument("--previous-runs", dest="previous_runs", action="store_true", default=True)
    b.add_argument("--no-previous-runs", dest="previous_runs", action="store_false")
    b.add_argument("--previous-runs-start-year", type=int, default=DEFAULT_PREVIOUS_RUN_START_YEAR)
    b.add_argument("--previous-runs-leads", default=",".join(str(item) for item in DEFAULT_PREVIOUS_RUN_LEADS))
    b.add_argument("--previous-runs-model", default="best_match")
    add_target_arguments(b)
    cov = sub.add_parser("coverage")
    add_target_arguments(cov, include_years=True)
    fc = sub.add_parser("fleet-coverage")
    fc.add_argument("--markets", default="", help="Comma-separated market ids; defaults to all registered markets.")
    fc.add_argument("--json-out", default="")
    fc.add_argument("--out", default="")
    add_target_arguments(fc, include_years=True)
    args = parser.parse_args()
    spec = spec_for_id(args.market)

    if args.command == "backfill":
        backfill(
            args.start_year,
            args.end_year,
            spec,
            pause=args.pause,
            include_previous_runs=args.previous_runs,
            previous_runs_start_year=args.previous_runs_start_year,
            previous_runs_leads=parse_leads(args.previous_runs_leads),
            previous_runs_model=args.previous_runs_model,
            target_date=args.target_date,
            target_window_days=args.target_window_days,
            history_window_days=args.history_window_days,
        )
    elif args.command == "coverage":
        payload = coverage(
            spec,
            target_date=args.target_date,
            required_years=parse_years(args.years),
            target_window_days=args.target_window_days,
            history_window_days=args.history_window_days,
        )
        if payload["status"] != "OK":
            raise SystemExit(2)
    elif args.command == "fleet-coverage":
        market_ids = _market_ids(args.markets)
        for market_id in market_ids:
            spec_for_id(market_id)
        payload = forecast_history_fleet_coverage(
            args.target_date,
            market_ids,
            required_years=parse_years(args.years),
            target_window_days=args.target_window_days,
            history_window_days=args.history_window_days,
        )
        write_forecast_history_coverage_outputs(payload, json_out=args.json_out, markdown_out=args.out)
        print(
            f"Forecast history coverage OK markets: "
            f"{payload['summary']['ok_market_count']}/{payload['summary']['market_count']}"
        )
        if args.json_out:
            print(f"Wrote JSON coverage to {args.json_out}")
        if args.out:
            print(f"Wrote coverage report to {args.out}")
        if payload["status"] != "PASS":
            raise SystemExit(2)


if __name__ == "__main__":
    main()
