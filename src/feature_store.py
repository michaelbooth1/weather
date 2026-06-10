"""Versioned feature schema for live, training, and snapshot audits."""

# v0.3 (ROADMAP item 40): intra-hour freshness. Between WU prints the printed
# state is frozen; the live wu_current reading and the elapsed minutes are now
# explicit TRAINED features instead of fabricated rows (the reverted v0.5.1
# injection) or heuristic floors. high_so_far stays printed-only.
FEATURE_SCHEMA_VERSION = "toronto_feature_store_v0.3"

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
    "forecast_high",
    "forecast_gap",
    # Appended after forecast_gap so v0.2 artifacts (12 numerics) keep working:
    # HGB bundles select by feature_names, the LR path slices len(scaler_mean).
    "minutes_since_cutoff",
    "live_reading_temp",
    "live_reading_minus_high",
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
    wind_group_fn=None,
    cloud_group_fn=None,
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
        "warming_rate_2h": warming_rate_2h,
        "hours_at_peak": hours_at_peak,
        "dewpoint_c": current_obs.get("dewpoint_c"),
        "humidity": current_obs.get("humidity"),
        "pressure": pressure,
        "pressure_trend_3h": pressure_trend_3h,
        "wind_speed_kmh": current_obs.get("wind_kmh"),
        "forecast_high": forecast_high,
        "forecast_gap": forecast_gap,
        "minutes_since_cutoff": float(minutes_since_cutoff),
        "live_reading_temp": live_reading,
        "live_reading_minus_high": live_reading_minus_high,
        "wind_group": wind_group,
        "cloud_group": cloud_group,
        "final_bucket": (daily or {}).get("bucket"),
    }
