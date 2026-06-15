"""Versioned feature schema for live, training, and snapshot audits."""

from datetime import datetime

from weather.schema_registry import schema_version

# v0.6 (ROADMAP item 27): microclimate/onshore-flow features.
#
# v0.5 (ROADMAP item 50): forecast profile, radiation/cloud detail, and GFS
# ensemble-spread features. Old artifacts keep serving because prediction code
# selects by trained feature_names.
#
# v0.4 (ROADMAP item 30): source redundancy. Forecast source count and
# disagreement are explicit features/audit fields. Existing artifacts keep
# serving because HGB bundles select by feature_names and the LR path slices the
# trained scaler width.
#
# v0.3 (ROADMAP item 40): intra-hour freshness. Between WU prints the printed
# state is frozen; the live wu_current reading and the elapsed minutes are now
# explicit TRAINED features instead of fabricated rows (the reverted v0.5.1
# injection) or heuristic floors. high_so_far stays printed-only.
FEATURE_SCHEMA_VERSION = schema_version("feature_store")

FORECAST_PROFILE_COLUMNS = [
    "forecast_peak_hour",
    "forecast_peak_after_cutoff_hours",
    "forecast_temp_12",
    "forecast_temp_13",
    "forecast_temp_14",
    "forecast_temp_15",
    "forecast_temp_16",
    "forecast_afternoon_slope",
    "forecast_remaining_degree_hours",
    "forecast_remaining_solar_sum",
    "forecast_next_3h_solar_mean",
    "forecast_total_cloud_mean",
    "forecast_total_cloud_max",
    "forecast_low_cloud_mean",
    "forecast_low_cloud_max",
    "forecast_mid_cloud_mean",
    "forecast_high_cloud_mean",
    "forecast_cloud_trend_3h",
    "forecast_global_ensemble_spread",
    "forecast_next_3h_ensemble_spread",
    "forecast_global_ensemble_high_p10",
    "forecast_global_ensemble_high_p90",
    "forecast_global_ensemble_high_spread_80",
]

FORECAST_FEATURE_COLUMNS = [
    "forecast_high",
    "forecast_gap",
    "forecast_source_count",
    "forecast_disagreement",
    *FORECAST_PROFILE_COLUMNS,
]

NATIVE_NAN_FEATURE_COLUMNS = [
    "forecast_high",
    "forecast_gap",
    *FORECAST_PROFILE_COLUMNS,
    "live_reading_temp",
    "live_reading_minus_high",
]

FEATURE_COLUMNS = [
    "high_so_far",
    "current_temp",
    "rise_from_7am",
    "warming_rate_2h",
    "hours_at_peak",
    "dewpoint_c",
    "humidity",
    "pressure",
    "pressure_trend_3h",
    "wind_speed_kmh",
    "onshore_flow",
    "onshore_wind_speed_kmh",
    "lake_breeze_proxy",
    "forecast_high",
    "forecast_gap",
    "forecast_source_count",
    "forecast_disagreement",
    *FORECAST_PROFILE_COLUMNS,
    # Freshness features remain explicit trained inputs; serving old artifacts
    # uses trained feature names rather than this newest schema order.
    "minutes_since_cutoff",
    "live_reading_temp",
    "live_reading_minus_high",
    "wind_group",
    "cloud_group",
]

FEATURE_DIAGNOSTIC_COLUMNS = [
    "latest_wu_history_time",
    "latest_wu_history_minute",
    "latest_wu_history_temp",
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
    *FEATURE_DIAGNOSTIC_COLUMNS,
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
    for column in FEATURE_DIAGNOSTIC_COLUMNS:
        record[column] = scalar((features or {}).get(column))
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


def to_float(value):
    if value in (None, "", "nan", "NaN"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def empty_microclimate_features():
    return {
        "onshore_flow": 0.0,
        "onshore_wind_speed_kmh": 0.0,
        "lake_breeze_proxy": 0.0,
    }


def row_minute_of_day(row):
    minute = row.get("minute_of_day")
    if minute is not None and minute != "":
        try:
            return int(float(minute))
        except (TypeError, ValueError):
            pass
    value = row.get("time") or row.get("valid_time")
    if not value:
        return None
    text = str(value)
    if "T" in text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.hour * 60 + parsed.minute
        except ValueError:
            return None
    if ":" in text:
        try:
            hour, minute = text[:5].split(":")
            return int(hour) * 60 + int(minute)
        except (TypeError, ValueError):
            return None
    return None


def row_value(row, *keys):
    for key in keys:
        value = to_float(row.get(key))
        if value is not None:
            return value
    return None


def nearest_hour_value(profile, hour, key):
    target = int(hour) * 60
    candidates = [
        item for item in profile
        if item.get(key) is not None and abs(item["minute"] - target) <= 45
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item["minute"] - target)).get(key)


def forecast_profile_features(
    forecast_rows=None,
    cutoff_hour=None,
    high_so_far=None,
    wall_minute=None,
    ensemble_rows=None,
    ensemble_day_mean_spread=None,
    ensemble_day_high_p10=None,
    ensemble_day_high_p90=None,
):
    """Derived forecast-shape features shared by training and serving.

    ``forecast_rows`` should describe the target day in the market's native
    temperature unit. Rows may be historical forecast-history rows or live
    Open-Meteo rows; both shapes are normalized here.
    """
    features = {column: None for column in FORECAST_PROFILE_COLUMNS}
    if cutoff_hour is None:
        return features
    cutoff_minute = int(cutoff_hour) * 60
    remaining_start = max(int(wall_minute), cutoff_minute) if wall_minute is not None else cutoff_minute

    profile = []
    for row in forecast_rows or []:
        minute = row_minute_of_day(row)
        if minute is None:
            continue
        profile.append({
            "minute": minute,
            "temp": row_value(row, "temp_c", "target_temp_native", "target_temp_c"),
            "solar": row_value(row, "solar", "shortwave_radiation"),
            "cloud": row_value(row, "cloud_cover"),
            "low_cloud": row_value(row, "low_cloud", "cloud_cover_low"),
            "mid_cloud": row_value(row, "mid_cloud", "cloud_cover_mid"),
            "high_cloud": row_value(row, "high_cloud", "cloud_cover_high"),
        })
    profile.sort(key=lambda item: item["minute"])

    temp_profile = [item for item in profile if item["temp"] is not None]
    if temp_profile:
        peak = max(temp_profile, key=lambda item: item["temp"])
        features["forecast_peak_hour"] = peak["minute"] / 60.0
        features["forecast_peak_after_cutoff_hours"] = (peak["minute"] - cutoff_minute) / 60.0
        for hour in (12, 13, 14, 15, 16):
            features[f"forecast_temp_{hour}"] = nearest_hour_value(profile, hour, "temp")
        t12 = features["forecast_temp_12"]
        t16 = features["forecast_temp_16"]
        if t12 is not None and t16 is not None:
            features["forecast_afternoon_slope"] = t16 - t12
        high = to_float(high_so_far)
        if high is not None:
            remaining_temps = [
                item["temp"] for item in temp_profile
                if item["minute"] >= remaining_start
            ]
            features["forecast_remaining_degree_hours"] = sum(
                max(0.0, temp - high) for temp in remaining_temps
            )

    remaining = [item for item in profile if item["minute"] >= remaining_start]
    next_3h = [
        item for item in profile
        if remaining_start <= item["minute"] < remaining_start + 180
    ]
    previous_3h = [
        item for item in profile
        if remaining_start - 180 <= item["minute"] < remaining_start
    ]

    solar_remaining = [item["solar"] for item in remaining if item["solar"] is not None]
    if solar_remaining:
        features["forecast_remaining_solar_sum"] = sum(solar_remaining)
    features["forecast_next_3h_solar_mean"] = mean(
        item["solar"] for item in next_3h
    )

    for source_key, mean_key in (
        ("cloud", "forecast_total_cloud_mean"),
        ("low_cloud", "forecast_low_cloud_mean"),
        ("mid_cloud", "forecast_mid_cloud_mean"),
        ("high_cloud", "forecast_high_cloud_mean"),
    ):
        values = [item[source_key] for item in remaining if item[source_key] is not None]
        if values:
            features[mean_key] = mean(values)
    total_cloud_values = [item["cloud"] for item in remaining if item["cloud"] is not None]
    if total_cloud_values:
        features["forecast_total_cloud_max"] = max(total_cloud_values)
    low_cloud_values = [item["low_cloud"] for item in remaining if item["low_cloud"] is not None]
    if low_cloud_values:
        features["forecast_low_cloud_max"] = max(low_cloud_values)
    next_cloud = mean(item["cloud"] for item in next_3h)
    previous_cloud = mean(item["cloud"] for item in previous_3h)
    if next_cloud is not None and previous_cloud is not None:
        features["forecast_cloud_trend_3h"] = next_cloud - previous_cloud

    features["forecast_global_ensemble_spread"] = to_float(ensemble_day_mean_spread)
    ensemble_spreads = []
    for row in ensemble_rows or []:
        minute = row_minute_of_day(row)
        spread = row_value(row, "ensemble_member_spread")
        if minute is not None and spread is not None and remaining_start <= minute < remaining_start + 180:
            ensemble_spreads.append(spread)
    if ensemble_spreads:
        features["forecast_next_3h_ensemble_spread"] = mean(ensemble_spreads)
    p10 = to_float(ensemble_day_high_p10)
    p90 = to_float(ensemble_day_high_p90)
    features["forecast_global_ensemble_high_p10"] = p10
    features["forecast_global_ensemble_high_p90"] = p90
    if p10 is not None and p90 is not None:
        features["forecast_global_ensemble_high_spread_80"] = p90 - p10
    return features


def simulated_reading_at(rows, minute, value_key="temp_c", exact_window=10, max_lookback=75):
    """Simulate the live instantaneous reading at ``minute`` from historical
    observations: a real obs within ``exact_window`` minutes BEFORE wins;
    otherwise linearly interpolate between the bracketing observations.

    Interpolation reads the next obs's value -- as a proxy for the
    CONTEMPORANEOUS physical temperature the live wu_current feed genuinely
    reports at that minute, not as a peek at a future print. It must only ever
    feed the live_reading features, never the printed-path features (those
    stay <= the cutoff print). Without it, hourly-only history would make the
    simulated reading equal the cutoff print and the feature would train dead.
    """
    timed = sorted(
        (
            (int(row["minute_of_day"]), float(row[value_key]))
            for row in rows
            if row.get(value_key) is not None and row.get("minute_of_day") is not None
        ),
    )
    if not timed:
        return None
    before = [(m, v) for m, v in timed if m <= minute]
    after = [(m, v) for m, v in timed if m > minute]
    if before and minute - before[-1][0] <= exact_window:
        return before[-1][1]
    if before and after:
        (m0, v0), (m1, v1) = before[-1], after[0]
        if m1 == m0:
            return v1
        return v0 + (v1 - v0) * (minute - m0) / (m1 - m0)
    if before and minute - before[-1][0] <= max_lookback:
        return before[-1][1]
    return None


def build_historical_feature_record(
    local_date,
    rows,
    daily,
    cutoff_hour,
    forecast_high=None,
    forecast_source_count=None,
    forecast_disagreement=None,
    forecast_profile_rows=None,
    global_ensemble_profile_rows=None,
    global_ensemble_day_mean_spread=None,
    global_ensemble_day_high_p10=None,
    global_ensemble_day_high_p90=None,
    wind_group_fn=None,
    cloud_group_fn=None,
    microclimate_feature_fn=None,
    wall_minute=None,
):
    """One training record at printed-cutoff ``cutoff_hour``. ``wall_minute``
    (>= the cutoff minute) simulates the intra-hour serve state: the printed
    path stays <= the cutoff, while the live-reading features come from the
    simulated instantaneous reading at the wall minute (item 40). Defaults to
    the at-print state (wall == cutoff, reading == cutoff obs)."""
    cutoff_minutes = int(cutoff_hour) * 60
    if wall_minute is None:
        wall_minute = cutoff_minutes
    wall_minute = max(int(wall_minute), cutoff_minutes)
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
    minutes_since_cutoff = wall_minute - cutoff_minutes
    if minutes_since_cutoff > 0:
        live_reading = simulated_reading_at(rows, wall_minute)
    else:
        live_reading = current_obs.get("temp_c")
    live_reading_minus_high = (
        live_reading - high_so_far if live_reading is not None else None
    )
    current_temp = current_obs.get("temp_c")
    temp_7am = closest_value(rows, 420, 60, "temp_c")
    rise_from_7am = (
        current_temp - temp_7am
        if current_temp is not None and temp_7am is not None
        else 0.0
    )
    
    # warming_rate_2h
    temp_2h_ago = closest_value(rows, cutoff_minutes - 120, 60, "temp_c")
    warming_rate_2h = (
        current_temp - temp_2h_ago
        if current_temp is not None and temp_2h_ago is not None
        else 0.0
    )
    
    # hours_at_peak
    first_reached_min = None
    for row in obs_before:
        if row.get("temp_c") == high_so_far and row.get("minute_of_day") is not None:
            first_reached_min = int(row["minute_of_day"])
            break
    hours_at_peak = (
        (cutoff_minutes - first_reached_min) / 60.0
        if first_reached_min is not None
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
    microclimate = (
        microclimate_feature_fn(wind_group, current_obs.get("wind_kmh"))
        if microclimate_feature_fn is not None
        else empty_microclimate_features()
    )
    forecast_gap = (
        forecast_high - high_so_far
        if forecast_high is not None and high_so_far is not None
        else None
    )
    forecast_profile = forecast_profile_features(
        forecast_profile_rows,
        cutoff_hour,
        high_so_far=high_so_far,
        wall_minute=wall_minute,
        ensemble_rows=global_ensemble_profile_rows,
        ensemble_day_mean_spread=global_ensemble_day_mean_spread,
        ensemble_day_high_p10=global_ensemble_day_high_p10,
        ensemble_day_high_p90=global_ensemble_day_high_p90,
    )
    return {
        "date": local_date,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "high_so_far": high_so_far,
        "current_temp": current_temp,
        "rise_from_7am": rise_from_7am,
        "warming_rate_2h": warming_rate_2h,
        "hours_at_peak": hours_at_peak,
        "dewpoint_c": current_obs.get("dewpoint_c"),
        "humidity": current_obs.get("humidity"),
        "pressure": pressure,
        "pressure_trend_3h": pressure_trend_3h,
        "wind_speed_kmh": current_obs.get("wind_kmh"),
        **microclimate,
        "forecast_high": forecast_high,
        "forecast_gap": forecast_gap,
        "forecast_source_count": (
            forecast_source_count
            if forecast_source_count is not None
            else (1 if forecast_high is not None else 0)
        ),
        "forecast_disagreement": forecast_disagreement if forecast_disagreement is not None else 0.0,
        **forecast_profile,
        "minutes_since_cutoff": float(minutes_since_cutoff),
        "live_reading_temp": live_reading,
        "live_reading_minus_high": live_reading_minus_high,
        "wind_group": wind_group,
        "cloud_group": cloud_group,
        "final_bucket": (daily or {}).get("bucket"),
    }
