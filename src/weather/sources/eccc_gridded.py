"""ECCC GEM/HRDPS gridded forecast helpers for Toronto."""
from __future__ import annotations

import hashlib
import re
import statistics
from datetime import date, datetime, timedelta, timezone

from weather.sources.grib_probe import probe_grib_payload
from weather.sources.historical_schema import to_float


ECCC_GRIDDED_SCHEMA_VERSION = "eccc_gridded_v0.1"
SOURCE = "eccc_gem"
OPEN_METEO_GEM_URL = "https://api.open-meteo.com/v1/gem"
HRDPS_DATAMART_BASE_URL = "https://dd.weather.gc.ca/today/model_hrdps"
GEM_MODELS = ("gem_seamless", "gem_global", "gem_regional")
OPEN_METEO_GEM_GRID = "point"
OPEN_METEO_GEM_DOMAIN = "open_meteo_gem"
OPEN_METEO_RUN_TIME_STATUS = "not_exposed_by_open_meteo"

OPEN_METEO_GEM_FIELD_MAP = {
    "temperature_2m": "temp_native",
    "wind_speed_10m": "wind_kmh",
    "wind_direction_10m": "wind_direction_degrees",
    "wind_gusts_10m": "wind_gust_kmh",
    "cloud_cover": "cloud_cover",
    "precipitation": "precipitation",
    "relative_humidity_2m": "humidity",
    "surface_pressure": "surface_pressure",
    "temperature_925hPa": "temperature_925hpa",
    "temperature_850hPa": "temperature_850hpa",
    "geopotential_height_500hPa": "geopotential_height_500hpa",
}

ECCC_GRIDDED_FEATURE_COLUMNS = [
    "eccc_gem_high",
    "eccc_gem_seamless_high",
    "eccc_gem_high_spread",
    "eccc_gem_vs_forecast_high",
    "eccc_gem_vs_open_meteo_high",
    "eccc_gem_vs_weather_high",
    "eccc_gem_vs_eccc_city_high",
    "eccc_gem_gust_after_cutoff_max",
    "eccc_gem_cloud_after_cutoff_mean",
    "eccc_gem_precip_after_cutoff_sum",
    "eccc_gem_humidity_after_cutoff_mean",
    "eccc_gem_temperature_925hpa_mean",
    "eccc_gem_temperature_850hpa_mean",
    "eccc_gem_geopotential_height_500hpa_mean",
    "eccc_gem_lake_breeze_wind_shift",
    "eccc_gem_run_age_hours",
]

HRDPS_FILENAME_RE = re.compile(
    r"(?P<run>\d{8}T\d{2}Z)_MSC_HRDPS_(?P<variable>[A-Z0-9]+)_(?P<level>[^_]+)_"
    r"(?P<grid>RLatLon[0-9.]+)_PT(?P<forecast_hour>\d{3})H\.grib2$"
)


def payload_hash(payload) -> str:
    return hashlib.sha1(str(payload or "").encode("utf-8")).hexdigest()


def parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_time(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _to_aware_local(value, tz):
    if value is None:
        return datetime.now(tz)
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _minutes_between(later, earlier):
    later_time = parse_time(later)
    earlier_time = parse_time(earlier)
    if later_time is None or earlier_time is None:
        return None
    return (later_time - earlier_time).total_seconds() / 60.0


def build_open_meteo_gem_params(spec, forecast_days=2):
    return {
        "latitude": spec.lat,
        "longitude": spec.lon,
        "hourly": ",".join(OPEN_METEO_GEM_FIELD_MAP),
        "temperature_unit": spec.om_temperature_unit,
        "wind_speed_unit": "kmh",
        "timezone": spec.timezone,
        "forecast_days": int(forecast_days),
        "models": ",".join(GEM_MODELS),
    }


def _array_get(mapping, key, index):
    values = mapping.get(key) or []
    if index >= len(values):
        return None
    return values[index]


def fetch_open_meteo_gem_for_market(spec, target_date, get_json, now=None):
    if spec.id != "toronto":
        return {
            "schema_version": ECCC_GRIDDED_SCHEMA_VERSION,
            "source": SOURCE,
            "available": False,
            "reason": "ECCC GEM/HRDPS gridded layer is Toronto-only in this slice.",
            "rows": [],
            "day_rows": [],
            "day_model_highs": {},
        }
    payload = get_json(OPEN_METEO_GEM_URL, build_open_meteo_gem_params(spec))
    return normalize_open_meteo_gem_payload(payload, spec, target_date, now=now)


def normalize_open_meteo_gem_payload(payload, spec, target_date, now=None):
    target = parse_date(target_date)
    hourly = (payload or {}).get("hourly") or {}
    day_rows = []
    rows = []
    model_day_temps = {model: [] for model in GEM_MODELS}
    fetched_at_local = _to_aware_local(now, spec.tz)
    now = fetched_at_local.replace(tzinfo=None)
    fetched_at = fetched_at_local.isoformat()
    payload_hash_value = payload_hash(payload)
    for index, raw_time in enumerate(hourly.get("time") or []):
        try:
            dt = datetime.fromisoformat(str(raw_time))
        except ValueError:
            continue
        if dt.date() != target:
            continue
        model_payloads = {}
        model_temps = []
        for model in GEM_MODELS:
            values = {}
            for source_key, target_key in OPEN_METEO_GEM_FIELD_MAP.items():
                value = to_float(_array_get(hourly, f"{source_key}_{model}", index))
                values[target_key] = value
            temp = values.get("temp_native")
            if temp is not None:
                values["temp_c"] = temp
                model_temps.append(temp)
                model_day_temps[model].append(temp)
            model_payloads[model] = values
        row = {
            "schema_version": ECCC_GRIDDED_SCHEMA_VERSION,
            "source": SOURCE,
            "time": dt.strftime("%H:%M"),
            "valid_time": dt.replace(tzinfo=spec.tz).isoformat(),
            "run_time": None,
            "run_time_status": OPEN_METEO_RUN_TIME_STATUS,
            "forecast_hour": None,
            "grid": OPEN_METEO_GEM_GRID,
            "domain": OPEN_METEO_GEM_DOMAIN,
            "source_url": OPEN_METEO_GEM_URL,
            "payload_hash": payload_hash_value,
            "fetched_at": fetched_at,
            "fetch_lag_minutes": None,
            "fetch_lag_status": OPEN_METEO_RUN_TIME_STATUS,
            "models": model_payloads,
            "model_temp_spread": max(model_temps) - min(model_temps) if len(model_temps) >= 2 else None,
        }
        day_rows.append(row)
        if dt >= now:
            rows.append(row)
    day_model_highs = {
        model: max(values) if values else None
        for model, values in model_day_temps.items()
    }
    high_values = [value for value in day_model_highs.values() if value is not None]
    return {
        "schema_version": ECCC_GRIDDED_SCHEMA_VERSION,
        "source": SOURCE,
        "available": bool(day_rows),
        "url": OPEN_METEO_GEM_URL,
        "source_url": OPEN_METEO_GEM_URL,
        "grid": OPEN_METEO_GEM_GRID,
        "domain": OPEN_METEO_GEM_DOMAIN,
        "rows": rows[:18],
        "day_rows": day_rows,
        "day_model_highs": day_model_highs,
        "day_max_native": statistics.median(high_values) if high_values else None,
        "day_max_c": statistics.median(high_values) if high_values else None,
        "day_high_spread": max(high_values) - min(high_values) if len(high_values) >= 2 else None,
        "row_count": len(day_rows),
        "payload_hash": payload_hash_value,
        "fetched_at": fetched_at,
        "fetch_lag_minutes": None,
        "fetch_lag_status": OPEN_METEO_RUN_TIME_STATUS,
        "generation_time_ms": (payload or {}).get("generationtime_ms"),
        "model_run_age_hours": None,
        "raw_payload": payload,
    }


def build_hrdps_datamart_url(
    run_time,
    forecast_hour,
    variable="TMP",
    level="AGL-2m",
    domain="continental",
    grid_size="2.5km",
    grid="RLatLon0.0225",
):
    run = parse_time(run_time)
    if run is None:
        raise ValueError("run_time must be parseable")
    forecast_hour = int(forecast_hour)
    run_hour = run.strftime("%H")
    fff = f"{forecast_hour:03d}"
    run_stamp = run.strftime("%Y%m%dT%HZ")
    filename = f"{run_stamp}_MSC_HRDPS_{variable}_{level}_{grid}_PT{fff}H.grib2"
    return f"{HRDPS_DATAMART_BASE_URL}/{domain}/{grid_size}/{run_hour}/{fff}/{filename}"


def parse_hrdps_datamart_filename(filename):
    match = HRDPS_FILENAME_RE.search(str(filename or "").split("/")[-1])
    if not match:
        return None
    row = match.groupdict()
    run = datetime.strptime(row["run"], "%Y%m%dT%HZ").replace(tzinfo=timezone.utc)
    row["run_time_utc"] = run.isoformat()
    row["forecast_hour"] = int(row["forecast_hour"])
    row["valid_time_utc"] = (run + timedelta(hours=row["forecast_hour"])).isoformat()
    return row


def probe_hrdps_grib_payload(payload, source_url, object_key=None, fetched_at=None):
    parsed = parse_hrdps_datamart_filename(object_key or source_url) or {}
    fetch_lag_minutes = _minutes_between(fetched_at, parsed.get("run_time_utc"))
    return probe_grib_payload(
        payload,
        source=SOURCE,
        model="HRDPS",
        source_url=source_url,
        object_key=object_key,
        run_time=parsed.get("run_time_utc"),
        forecast_hour=parsed.get("forecast_hour"),
        valid_time=parsed.get("valid_time_utc"),
        grid=parsed.get("grid"),
        domain="continental",
        fetched_at=fetched_at,
    ) | {
        "schema_version": ECCC_GRIDDED_SCHEMA_VERSION,
        "product": parsed.get("variable"),
        "level": parsed.get("level"),
        "fetch_lag_minutes": fetch_lag_minutes,
        "fetch_lag_basis": "fetched_at_minus_run_time" if fetch_lag_minutes is not None else None,
    }


def empty_eccc_gridded_features():
    return {column: None for column in ECCC_GRIDDED_FEATURE_COLUMNS}


def _minute(row):
    value = (row or {}).get("time") or (row or {}).get("valid_time")
    if not value:
        return None
    text = str(value)
    if "T" in text:
        try:
            parsed = datetime.fromisoformat(text)
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            return None
    try:
        hour, minute = text[:5].split(":")
        return int(hour) * 60 + int(minute)
    except (TypeError, ValueError):
        return None


def _model_values(row, key, model_preference=("gem_seamless", "gem_regional", "gem_global")):
    models = (row or {}).get("models") or {}
    values = []
    for model in model_preference:
        value = to_float((models.get(model) or {}).get(key))
        if value is not None:
            values.append(value)
    return values


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _direction_in_sector(direction, start=60.0, end=160.0):
    direction = to_float(direction)
    if direction is None:
        return None
    direction %= 360.0
    return start <= direction <= end


def derive_eccc_gridded_features(
    eccc_gem,
    forecast_high=None,
    open_meteo_high=None,
    weather_high=None,
    eccc_city_high=None,
    cutoff_hour=None,
    wall_minute=None,
):
    features = empty_eccc_gridded_features()
    data = eccc_gem or {}
    highs = data.get("day_model_highs") or {}
    high_values = [to_float(value) for value in highs.values() if to_float(value) is not None]
    gem_high = data.get("day_max_native")
    if gem_high is None and high_values:
        gem_high = statistics.median(high_values)
    features["eccc_gem_high"] = gem_high
    features["eccc_gem_seamless_high"] = highs.get("gem_seamless")
    if len(high_values) >= 2:
        features["eccc_gem_high_spread"] = max(high_values) - min(high_values)
    for key, reference in (
        ("eccc_gem_vs_forecast_high", forecast_high),
        ("eccc_gem_vs_open_meteo_high", open_meteo_high),
        ("eccc_gem_vs_weather_high", weather_high),
        ("eccc_gem_vs_eccc_city_high", eccc_city_high),
    ):
        if gem_high is not None and reference is not None:
            features[key] = gem_high - reference
    run_age = data.get("model_run_age_hours")
    if run_age is not None:
        features["eccc_gem_run_age_hours"] = run_age

    cutoff_minute = int(cutoff_hour) * 60 if cutoff_hour is not None else 0
    start_minute = max(cutoff_minute, int(wall_minute) if wall_minute is not None else cutoff_minute)
    rows = data.get("day_rows") or data.get("rows") or []
    remaining = [
        row for row in rows
        if _minute(row) is not None and _minute(row) >= start_minute
    ]
    gusts = [value for row in remaining for value in _model_values(row, "wind_gust_kmh")]
    clouds = [value for row in remaining for value in _model_values(row, "cloud_cover")]
    precip = [value for row in remaining for value in _model_values(row, "precipitation")]
    humidity = [value for row in remaining for value in _model_values(row, "humidity")]
    t925 = [value for row in remaining for value in _model_values(row, "temperature_925hpa")]
    t850 = [value for row in remaining for value in _model_values(row, "temperature_850hpa")]
    h500 = [value for row in remaining for value in _model_values(row, "geopotential_height_500hpa")]
    if gusts:
        features["eccc_gem_gust_after_cutoff_max"] = max(gusts)
    features["eccc_gem_cloud_after_cutoff_mean"] = _mean(clouds)
    features["eccc_gem_precip_after_cutoff_sum"] = sum(precip) if precip else None
    features["eccc_gem_humidity_after_cutoff_mean"] = _mean(humidity)
    features["eccc_gem_temperature_925hpa_mean"] = _mean(t925)
    features["eccc_gem_temperature_850hpa_mean"] = _mean(t850)
    features["eccc_gem_geopotential_height_500hpa_mean"] = _mean(h500)

    before_dirs = [
        value for row in rows
        if _minute(row) is not None and _minute(row) <= cutoff_minute
        for value in _model_values(row, "wind_direction_degrees")
    ]
    after_dirs = [
        value for row in remaining
        for value in _model_values(row, "wind_direction_degrees")
    ]
    if before_dirs and after_dirs:
        before_onshore = any(_direction_in_sector(value) for value in before_dirs)
        after_onshore = any(_direction_in_sector(value) for value in after_dirs)
        features["eccc_gem_lake_breeze_wind_shift"] = 1.0 if after_onshore and not before_onshore else 0.0
    return features


def _market_id(row):
    return str((row or {}).get("market_id") or (row or {}).get("market") or "").lower()


def _settlement_high(row):
    for key in ("settlement_high", "settlement", "observed_high", "actual_high", "day_max_native"):
        value = to_float((row or {}).get(key))
        if value is not None:
            return value
    return None


def _case_names(row, high_spread_threshold=2.0):
    cases = ["all_toronto"]
    if to_float((row or {}).get("eccc_gem_lake_breeze_wind_shift")) == 1.0:
        cases.append("lake_breeze_wind_shift")
    spread = to_float((row or {}).get("eccc_gem_high_spread"))
    if spread is not None and spread >= high_spread_threshold:
        cases.append("high_model_spread")
    precip = to_float((row or {}).get("eccc_gem_precip_after_cutoff_sum"))
    if precip is not None and precip > 0.0:
        cases.append("post_cutoff_precip")
    delta = to_float((row or {}).get("eccc_gem_vs_forecast_high"))
    if delta is not None:
        if delta > 0.0:
            cases.append("gem_warmer_than_consensus")
        elif delta < 0.0:
            cases.append("gem_cooler_than_consensus")
    return cases


def _score_summary(rows):
    rows = list(rows)
    improvements = []
    gem_errors = []
    forecast_errors = []
    deltas = []
    for row in rows:
        settlement = _settlement_high(row)
        gem_high = to_float((row or {}).get("eccc_gem_high"))
        forecast_high = to_float((row or {}).get("forecast_high"))
        delta = to_float((row or {}).get("eccc_gem_vs_forecast_high"))
        if delta is not None:
            deltas.append(delta)
        if settlement is None or gem_high is None or forecast_high is None:
            continue
        gem_error = abs(gem_high - settlement)
        forecast_error = abs(forecast_high - settlement)
        gem_errors.append(gem_error)
        forecast_errors.append(forecast_error)
        improvements.append(forecast_error - gem_error)
    return {
        "rows": len(rows),
        "scored_rows": len(improvements),
        "mean_eccc_gem_vs_forecast_high": _mean(deltas),
        "mean_gem_abs_error": _mean(gem_errors),
        "mean_forecast_abs_error": _mean(forecast_errors),
        "mean_abs_error_improvement": _mean(improvements),
    }


def score_eccc_toronto_features(rows, min_scored_rows=20, high_spread_threshold=2.0):
    """Score ECCC GEM/HRDPS features on Toronto rows only.

    Positive ``mean_abs_error_improvement`` means the GEM high was closer to
    settlement than the existing forecast high on the scored slice.
    """
    input_rows = list(rows or [])
    toronto_rows = [row for row in input_rows if _market_id(row) == "toronto"]
    case_rows = {}
    for row in toronto_rows:
        for case in _case_names(row, high_spread_threshold=high_spread_threshold):
            case_rows.setdefault(case, []).append(row)
    cases = [
        {"case": case, **_score_summary(case_rows[case])}
        for case in sorted(case_rows)
    ]
    summary = _score_summary(toronto_rows)
    summary.update({
        "input_rows": len(input_rows),
        "toronto_rows": len(toronto_rows),
        "skipped_non_toronto_rows": len(input_rows) - len(toronto_rows),
    })
    enough_rows = summary["scored_rows"] >= int(min_scored_rows)
    mean_improvement = summary.get("mean_abs_error_improvement")
    expansion_allowed = bool(enough_rows and mean_improvement is not None and mean_improvement >= 0.0)
    return {
        "schema_version": ECCC_GRIDDED_SCHEMA_VERSION,
        "source": SOURCE,
        "market_id": "toronto",
        "summary": summary,
        "cases": cases,
        "expansion_gate": {
            "eligible_for_canadian_expansion_review": expansion_allowed,
            "status": "reviewable" if expansion_allowed else "needs_more_toronto_evidence",
            "min_scored_rows": int(min_scored_rows),
            "reason": (
                "Toronto scored slice is non-negative versus forecast consensus."
                if expansion_allowed
                else "Score Toronto rows before considering Canadian expansion markets."
            ),
        },
    }


def render_eccc_toronto_score_markdown(payload):
    summary = (payload or {}).get("summary") or {}
    lines = [
        "# ECCC GEM/HRDPS Toronto Feature Score",
        "",
        f"- Toronto rows: {summary.get('toronto_rows', 0)}",
        f"- Scored rows: {summary.get('scored_rows', 0)}",
        f"- Expansion gate: {((payload or {}).get('expansion_gate') or {}).get('status', 'unknown')}",
        "",
        "| Case | Rows | Scored | Mean GEM-Forecast High | Mean Error Improvement |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in (payload or {}).get("cases") or []:
        lines.append(
            "| {case} | {rows} | {scored_rows} | {delta} | {improvement} |".format(
                case=row.get("case"),
                rows=row.get("rows", 0),
                scored_rows=row.get("scored_rows", 0),
                delta=row.get("mean_eccc_gem_vs_forecast_high"),
                improvement=row.get("mean_abs_error_improvement"),
            )
        )
    return "\n".join(lines) + "\n"
