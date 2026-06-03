"""Versioned feature schema for live, training, and snapshot audits."""

FEATURE_SCHEMA_VERSION = "toronto_feature_store_v0.1"

FEATURE_COLUMNS = [
    "high_so_far",
    "current_temp",
    "rise_from_7am",
    "dewpoint_c",
    "humidity",
    "pressure",
    "pressure_trend_3h",
    "wind_speed_kmh",
    "forecast_high",
    "forecast_gap",
    "wind_group",
    "cloud_group",
]

FEATURE_AUDIT_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "target_date",
    "model_version",
    "feature_schema_version",
    "cutoff_hour",
    *FEATURE_COLUMNS,
]


def scalar(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_live_feature_record(
    target_date,
    cutoff_hour,
    captured_at,
    model_version,
    features,
):
    record = {
        "target_date": target_date.isoformat() if hasattr(target_date, "isoformat") else target_date,
        "model_version": model_version,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "cutoff_hour": cutoff_hour,
    }
    if captured_at is not None:
        record["captured_at_local"] = captured_at.isoformat()
    for column in FEATURE_COLUMNS:
        record[column] = scalar((features or {}).get(column))
    return record


def feature_schema_metadata():
    return {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
    }


def audit_row(base, feature_record):
    row = {column: None for column in FEATURE_AUDIT_COLUMNS}
    row.update(base or {})
    for key, value in (feature_record or {}).items():
        if key in row:
            row[key] = value
    return row


def closest_value(rows, target_minute, window_min, value_key):
    candidates = [
        row for row in rows
        if row.get(value_key) is not None
        and abs(int(row["minute_of_day"]) - target_minute) <= window_min
    ]
    if not candidates:
        return None
    row = min(candidates, key=lambda item: abs(int(item["minute_of_day"]) - target_minute))
    return row.get(value_key)


def build_historical_feature_record(
    local_date,
    rows,
    daily,
    cutoff_hour,
    forecast_high=None,
    wind_group_fn=None,
    cloud_group_fn=None,
):
    cutoff_minutes = int(cutoff_hour) * 60
    obs_before = [
        row for row in rows
        if row.get("minute_of_day") is not None
        and int(row["minute_of_day"]) <= cutoff_minutes
    ]
    if not obs_before:
        return None
    current_obs = obs_before[-1]
    temps_before = [row["temp_c"] for row in obs_before if row.get("temp_c") is not None]
    if not temps_before:
        return None

    high_so_far = max(temps_before)
    current_temp = current_obs.get("temp_c")
    temp_7am = closest_value(rows, 420, 60, "temp_c")
    rise_from_7am = (
        current_temp - temp_7am
        if current_temp is not None and temp_7am is not None
        else 0.0
    )
    pressure = current_obs.get("pressure")
    pressure_window = []
    for row in rows:
        minute = row.get("minute_of_day")
        if minute is None:
            continue
        minute = int(minute)
        if (cutoff_minutes - 240) <= minute <= (cutoff_minutes - 120):
            pressure_window.append(row)
    pressure_3h = closest_value(
        pressure_window,
        cutoff_minutes - 180,
        60,
        "pressure",
    )
    pressure_trend_3h = (
        pressure - pressure_3h
        if pressure is not None and pressure_3h is not None
        else 0.0
    )
    wind_group = (
        wind_group_fn(current_obs.get("wind"))
        if wind_group_fn is not None
        else current_obs.get("wind_group")
    )
    cloud_group = (
        cloud_group_fn(current_obs.get("condition"), current_obs.get("clouds"))
        if cloud_group_fn is not None
        else current_obs.get("cloud_group")
    )
    forecast_gap = (
        forecast_high - high_so_far
        if forecast_high is not None and high_so_far is not None
        else None
    )
    return {
        "date": local_date,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "high_so_far": high_so_far,
        "current_temp": current_temp,
        "rise_from_7am": rise_from_7am,
        "dewpoint_c": current_obs.get("dewpoint_c"),
        "humidity": current_obs.get("humidity"),
        "pressure": pressure,
        "pressure_trend_3h": pressure_trend_3h,
        "wind_speed_kmh": current_obs.get("wind_kmh"),
        "forecast_high": forecast_high,
        "forecast_gap": forecast_gap,
        "wind_group": wind_group,
        "cloud_group": cloud_group,
        "final_bucket": (daily or {}).get("bucket"),
    }
