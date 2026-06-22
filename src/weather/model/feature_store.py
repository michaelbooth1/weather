"""Versioned feature schema for live, training, and snapshot audits."""

from datetime import datetime

from weather.schema_registry import schema_version
from weather.sources.eccc_gridded import ECCC_GRIDDED_FEATURE_COLUMNS
from weather.sources.marine_context import MARINE_CONTEXT_FEATURE_COLUMNS
from weather.sources.mrms_precip import MRMS_PRECIP_FEATURE_COLUMNS
from weather.sources.nbm_probabilistic_tmax import NBM_PROB_TMAX_FEATURE_COLUMNS
from weather.sources.reanalysis_synoptic import REANALYSIS_SYNOPTIC_FEATURE_COLUMNS
from weather.units import to_float

# v1.14 (ROADMAP item 186): gated reanalysis antecedent precipitation and
# precipitation-minus-ET0 water-balance windows for soil/land-surface dryness.
#
# v1.13 (ROADMAP items 194-196): robust forecast consensus/outlier features
# and model diagnostics for ramp warm-tail dampening and late-day lock-in
# coverage.
#
# v1.12 (ROADMAP items 193 and 197): live current-max trust/quarantine
# features plus startup observation plausibility flags, so support-only
# max-since-7 values and missing F-market live observations cannot silently
# warm the served distribution.
#
# v1.11 (ROADMAP item 191): live lake/sea water-temperature contrast features
# against the forecast high, including an onshore-gated cooling-potential signal.
#
# v1.10 (ROADMAP item 190): live NBM probabilistic maximum-temperature
# percentile features from NBP station guidance. Native QMD GRIB exceedance-grid
# features remain pending.
#
# v1.9 (ROADMAP item 189): live ECMWF/ML-NWP global model guidance features
# from Open-Meteo model-specific columns. The global model family contributes
# one clustered forecast-high vote plus per-member deltas/spreads.
#
# v1.8 (ROADMAP item 188): live Open-Meteo Air Quality aerosol/smoke features
# for PM2.5, AOD, dust, and a high-smoke suppression flag. Historical records
# default these live-only diagnostics to None until AQ backfills and smoke-slice
# settlement gates promote a retrained artifact.
#
# v1.7 (ROADMAP item 187): forecast radiation direct-share features from paired
# direct/diffuse radiation rows as a clearness proxy.
#
# v1.6 (ROADMAP item 32): gated pressure-level reanalysis features for cached
# NOAA PSL NCEP/NCAR 850 hPa temperature, 500 hPa height, and 1000-500 hPa
# thickness.
#
# v1.5 (ROADMAP item 32): lagged ENSO/PNA teleconnection fields plus static
# marine/lake-breeze context in the gated reanalysis/synoptic sidecar.
#
# v1.4 (ROADMAP item 32): gated reanalysis/synoptic sidecar features. Live
# serving defaults them to missing until source-lag and parity gates promote
# a trained candidate artifact.
#
# v1.3 (ROADMAP item 75): US official-grid and multi-model live-only run
# metadata, run-to-run change hooks, and after-cutoff NBM/HRRR disagreement.
# Historical records default these diagnostics to None until archives exist.
#
# v1.2 (ROADMAP item 80): ECCC GEM/HRDPS gridded forecast diagnostics for
# Toronto. Historical rows default these live-only fields to None until
# Toronto-specific backfills and replay gates exist.
#
# v1.1 (ROADMAP item 79): MRMS realized precipitation/radar interruption
# diagnostics. Historical rows default these live-only fields to None until
# MRMS backfills and replay gates exist.
#
# v1.0 (ROADMAP item 78): marine/coastal/lake-breeze context diagnostics.
# Historical records default these live-only station features to None until
# station-specific archives and replay gates exist.
#
# v0.9 (ROADMAP item 75): US NWS grid and Open-Meteo multi-model guidance
# features. Historical records default these live-only diagnostics to None
# until provenance-preserving archives exist.
#
# v0.8 (ROADMAP item 74): expanded Open-Meteo environmental forecast profile
# features for radiation partitioning, convection, vertical thermal structure,
# precipitation, visibility, gusts, soil state, VPD, and ET0.
#
# v0.7 (ROADMAP item 27): wind-gust and wind-shift features.
#
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
    "forecast_remaining_direct_radiation_sum",
    "forecast_remaining_diffuse_radiation_sum",
    "forecast_next_3h_direct_radiation_mean",
    "forecast_next_3h_diffuse_radiation_mean",
    "forecast_remaining_direct_radiation_share",
    "forecast_next_3h_direct_radiation_share",
    "forecast_remaining_precipitation_sum",
    "forecast_next_3h_precipitation_sum",
    "forecast_next_3h_precipitation_probability_max",
    "forecast_remaining_cape_mean",
    "forecast_next_3h_cape_max",
    "forecast_cape_trend_3h",
    "forecast_temperature_925hpa_mean",
    "forecast_temperature_850hpa_mean",
    "forecast_surface_to_925_lapse_proxy",
    "forecast_925_to_850_lapse_proxy",
    "forecast_geopotential_height_500hpa_mean",
    "forecast_wind_gust_max",
    "forecast_visibility_min",
    "forecast_soil_temperature_0cm_mean",
    "forecast_soil_moisture_0_to_1cm_mean",
    "forecast_vapour_pressure_deficit_mean",
    "forecast_et0_fao_evapotranspiration_sum",
    "forecast_remaining_aerosol_optical_depth_mean",
    "forecast_next_3h_aerosol_optical_depth_mean",
    "forecast_remaining_pm2_5_mean",
    "forecast_next_3h_pm2_5_mean",
    "forecast_remaining_pm10_mean",
    "forecast_remaining_dust_mean",
    "forecast_smoke_suppression_flag",
    "forecast_global_ensemble_spread",
    "forecast_next_3h_ensemble_spread",
    "forecast_global_ensemble_high_p10",
    "forecast_global_ensemble_high_p90",
    "forecast_global_ensemble_high_spread_80",
]

EXPANDED_OPEN_METEO_SOURCE_FIELDS = [
    "cape",
    "temperature_925hpa",
    "temperature_850hpa",
    "geopotential_height_500hpa",
    "direct_radiation",
    "diffuse_radiation",
    "wind_gust_kmh",
    "visibility",
    "precipitation_probability",
    "precipitation",
    "soil_temperature_0cm",
    "soil_moisture_0_to_1cm",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
]

OPEN_METEO_AIR_QUALITY_FIELDS = [
    "pm2_5",
    "pm10",
    "aerosol_optical_depth",
    "dust",
    "us_aqi",
    "european_aqi",
]

SMOKE_PM2_5_THRESHOLD_UG_M3 = 35.5
SMOKE_AEROSOL_OPTICAL_DEPTH_THRESHOLD = 0.4
SMOKE_DUST_THRESHOLD_UG_M3 = 50.0

FORECAST_FEATURE_COLUMNS = [
    "forecast_high",
    "forecast_gap",
    "forecast_source_count",
    "forecast_disagreement",
    "forecast_robust_high",
    "forecast_trimmed_high",
    "forecast_warm_outlier_flag",
    "forecast_warm_outlier_gap",
    "forecast_source_family_count",
    *FORECAST_PROFILE_COLUMNS,
]

US_GUIDANCE_FEATURE_COLUMNS = [
    "nws_grid_high",
    "nws_grid_vs_forecast_high",
    "nws_grid_pop_after_cutoff_max",
    "nws_grid_qpf_after_cutoff_sum",
    "nws_grid_sky_cover_after_cutoff_mean",
    "nws_grid_hazard_count",
    "open_meteo_multimodel_high_spread",
    "open_meteo_gfs_high_delta",
    "open_meteo_hrrr_high_delta",
    "open_meteo_nbm_high_delta",
    "open_meteo_nam_high_delta",
    "open_meteo_nbm_hrrr_disagreement",
    "open_meteo_multimodel_next_3h_spread",
    "nws_grid_run_age_hours",
    *NBM_PROB_TMAX_FEATURE_COLUMNS,
    "open_meteo_multimodel_run_age_hours",
    "open_meteo_multimodel_run_to_run_high_change",
    "open_meteo_nbm_hrrr_disagreement_after_cutoff",
    "open_meteo_global_models_high_spread",
    "open_meteo_ecmwf_ifs_high_delta",
    "open_meteo_ecmwf_aifs_high_delta",
    "open_meteo_ncep_aigfs_high_delta",
    "open_meteo_gfs_graphcast_high_delta",
    "open_meteo_ecmwf_ifs_aifs_disagreement",
    "open_meteo_global_models_next_3h_spread",
    "open_meteo_global_models_run_to_run_high_change",
]

NATIVE_NAN_FEATURE_COLUMNS = [
    "forecast_high",
    "forecast_gap",
    *FORECAST_PROFILE_COLUMNS,
    *US_GUIDANCE_FEATURE_COLUMNS,
    *MARINE_CONTEXT_FEATURE_COLUMNS,
    *MRMS_PRECIP_FEATURE_COLUMNS,
    *ECCC_GRIDDED_FEATURE_COLUMNS,
    *REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
    "live_reading_temp",
    "live_reading_minus_high",
    "trusted_current_max",
    "support_only_current_max",
    "quarantined_current_max",
    "current_max_gap_to_history",
    "current_max_gap_to_current_temp",
]

CURRENT_MAX_TRUST_FEATURE_COLUMNS = [
    "trusted_current_max",
    "support_only_current_max",
    "quarantined_current_max",
    "current_max_trusted_flag",
    "current_max_support_only_flag",
    "current_max_quarantined_flag",
    "current_max_gap_to_history",
    "current_max_gap_to_current_temp",
    "startup_feature_quarantined_flag",
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
    "wind_gust_kmh",
    "wind_shift_3h_degrees",
    "onshore_flow",
    "onshore_wind_speed_kmh",
    "lake_breeze_proxy",
    "forecast_high",
    "forecast_gap",
    "forecast_source_count",
    "forecast_disagreement",
    *FORECAST_PROFILE_COLUMNS,
    *US_GUIDANCE_FEATURE_COLUMNS,
    *MARINE_CONTEXT_FEATURE_COLUMNS,
    *MRMS_PRECIP_FEATURE_COLUMNS,
    *ECCC_GRIDDED_FEATURE_COLUMNS,
    *REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
    # Freshness features remain explicit trained inputs; serving old artifacts
    # uses trained feature names rather than this newest schema order.
    "minutes_since_cutoff",
    "live_reading_temp",
    "live_reading_minus_high",
    *CURRENT_MAX_TRUST_FEATURE_COLUMNS,
    "wind_group",
    "cloud_group",
]

FEATURE_DIAGNOSTIC_COLUMNS = [
    "latest_wu_history_time",
    "latest_wu_history_minute",
    "latest_wu_history_temp",
    "current_max_state",
    "current_max_disposition",
    "current_max_quarantine_reason",
    "startup_feature_quarantine_reason",
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


def plausible_native_temperature(value, unit):
    number = to_float(value)
    if number is None:
        return False
    unit = str(unit or "").upper()
    if unit == "F":
        return 30.0 <= number <= 125.0
    return -45.0 <= number <= 55.0


def current_max_trust_features(
    current_max,
    *,
    history_max=None,
    current_temp=None,
    cutoff_hour=None,
    unit=None,
    gap_threshold=10.0,
):
    current_max = to_float(current_max)
    history_max = to_float(history_max)
    current_temp = to_float(current_temp)
    gap_to_history = None if current_max is None or history_max is None else current_max - history_max
    gap_to_current = None if current_max is None or current_temp is None else current_max - current_temp
    pre_reset = cutoff_hour is not None and int(cutoff_hour) < 7
    state = "missing_current_max"
    disposition = "missing"
    reason = ""
    trusted = None
    support = None
    quarantined = None
    if current_max is None:
        reason = "missing_current_max"
    elif unit and not plausible_native_temperature(current_max, unit):
        state = "implausible_current_max_unit"
        disposition = "quarantined"
        reason = f"implausible_{str(unit).upper()}_current_max"
        quarantined = current_max
    elif pre_reset:
        state = "pre_reset_current_max_null"
        disposition = "null_before_reset"
        reason = "before_7am_reset"
        support = current_max
    elif gap_to_history is not None and gap_to_history >= float(gap_threshold):
        state = (
            "early_current_max_history_gap"
            if cutoff_hour is not None and int(cutoff_hour) <= 12
            else "current_max_history_gap"
        )
        disposition = "quarantined"
        reason = "large_gap_to_wu_history"
        quarantined = current_max
    elif gap_to_current is not None and gap_to_current >= float(gap_threshold):
        state = "current_max_current_temp_gap"
        disposition = "quarantined"
        reason = "large_gap_to_current_temp"
        quarantined = current_max
    elif history_max is None:
        state = "missing_history_for_current_max"
        disposition = "support_only"
        reason = "missing_wu_history"
        support = current_max
    elif gap_to_history is not None and gap_to_history > 1e-9:
        state = "current_max_above_history_minor_gap"
        disposition = "support_only"
        reason = "minor_gap_to_wu_history"
        support = current_max
    else:
        state = "wu_history_validated_current_max"
        disposition = "validated"
        reason = "validated_by_wu_history"
        trusted = current_max
    return {
        "trusted_current_max": trusted,
        "support_only_current_max": support,
        "quarantined_current_max": quarantined,
        "current_max_trusted_flag": 1.0 if trusted is not None else 0.0,
        "current_max_support_only_flag": 1.0 if support is not None else 0.0,
        "current_max_quarantined_flag": 1.0 if quarantined is not None else 0.0,
        "current_max_gap_to_history": gap_to_history,
        "current_max_gap_to_current_temp": gap_to_current,
        "current_max_state": state,
        "current_max_disposition": disposition,
        "current_max_quarantine_reason": reason if disposition == "quarantined" else "",
    }


def startup_observation_guard_features(*, high_so_far=None, current_temp=None, live_reading_temp=None, unit=None):
    unit = str(unit or "").upper()
    bad = []
    for name, value in (
        ("high_so_far", high_so_far),
        ("current_temp", current_temp),
        ("live_reading_temp", live_reading_temp),
    ):
        if value is not None and unit and not plausible_native_temperature(value, unit):
            bad.append(name)
    quarantined = bool(bad and live_reading_temp is None)
    return {
        "startup_feature_quarantined_flag": 1.0 if quarantined else 0.0,
        "startup_feature_quarantine_reason": ",".join(bad) if quarantined else "",
    }


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


def closest_temperature_native(rows, target_minute, window_min):
    candidates = []
    for row in rows:
        minute = row_minute_of_day(row)
        value = row_temp_native(row)
        if minute is None or value is None:
            continue
        distance = abs(minute - target_minute)
        if distance <= window_min:
            candidates.append((distance, value))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def empty_microclimate_features():
    return {
        "onshore_flow": 0.0,
        "onshore_wind_speed_kmh": 0.0,
        "lake_breeze_proxy": 0.0,
    }


def empty_us_guidance_features():
    return {column: None for column in US_GUIDANCE_FEATURE_COLUMNS}


def empty_marine_context_features():
    return {column: None for column in MARINE_CONTEXT_FEATURE_COLUMNS}


def empty_mrms_precip_features():
    return {column: None for column in MRMS_PRECIP_FEATURE_COLUMNS}


def empty_eccc_gridded_features():
    return {column: None for column in ECCC_GRIDDED_FEATURE_COLUMNS}


def empty_reanalysis_synoptic_features():
    return {column: None for column in REANALYSIS_SYNOPTIC_FEATURE_COLUMNS}


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


def row_dewpoint_native(row):
    return row_value(row, "dewpoint_native", "dewpoint_c")


def row_air_temp_native(row):
    return row_value(row, "air_temp_native", "air_temp_c", "temp_native", "temp_c")


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


def row_max_native(row):
    return row_value(
        row,
        "max_native",
        "max_temp_native",
        "high_native",
        "max_c",
        "max_temp_c",
        "high_c",
    )


def row_max_since_7am_native(row):
    return row_value(row, "max_since_7am_native", "max_since_7am_c")


def row_same_day_max_native(row):
    return row_value(row, "same_day_max_native", "same_day_max_c")


COMPASS_DEGREES = {
    "N": 0.0,
    "NNE": 22.5,
    "NE": 45.0,
    "ENE": 67.5,
    "E": 90.0,
    "ESE": 112.5,
    "SE": 135.0,
    "SSE": 157.5,
    "S": 180.0,
    "SSW": 202.5,
    "SW": 225.0,
    "WSW": 247.5,
    "W": 270.0,
    "WNW": 292.5,
    "NW": 315.0,
    "NNW": 337.5,
}


def wind_direction_degrees(value):
    if value in (None, "", "nan", "NaN"):
        return None
    numeric = to_float(value)
    if numeric is not None:
        return numeric % 360.0
    text = str(value).strip().upper()
    text = text.replace("°", "").replace("DEG", "").strip()
    if text in {"CALM", "VRB", "VARIABLE", "VAR"}:
        return None
    numeric = to_float(text)
    if numeric is not None:
        return numeric % 360.0
    return COMPASS_DEGREES.get(text)


def wind_direction_delta_degrees(current, previous):
    current_degrees = wind_direction_degrees(current)
    previous_degrees = wind_direction_degrees(previous)
    if current_degrees is None or previous_degrees is None:
        return None
    delta = abs((current_degrees - previous_degrees + 180.0) % 360.0 - 180.0)
    return float(delta)


def row_wind_direction(row):
    return (
        row.get("wind_dir")
        or row.get("wind_direction")
        or row.get("wind_degrees")
        or row.get("wind")
    )


def closest_wind_direction(rows, target_minute, window_min):
    candidates = []
    for row in rows:
        minute = row_minute_of_day(row)
        if minute is None:
            continue
        direction = row_wind_direction(row)
        if wind_direction_degrees(direction) is None:
            continue
        if abs(minute - target_minute) <= window_min:
            candidates.append((abs(minute - target_minute), direction))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]


def nearest_hour_value(profile, hour, key):
    target = int(hour) * 60
    candidates = [
        item for item in profile
        if item.get(key) is not None and abs(item["minute"] - target) <= 45
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: abs(item["minute"] - target)).get(key)


def radiation_direct_share(profile_rows):
    direct_total = 0.0
    radiation_total = 0.0
    for item in profile_rows:
        direct = item.get("direct_radiation")
        diffuse = item.get("diffuse_radiation")
        if direct is None or diffuse is None:
            continue
        row_total = direct + diffuse
        if row_total <= 0:
            continue
        direct_total += direct
        radiation_total += row_total
    if radiation_total <= 0:
        return None
    return direct_total / radiation_total


def merge_forecast_air_quality_rows(forecast_rows=None, air_quality_rows=None):
    forecast_rows = list(forecast_rows or [])
    air_quality_rows = list(air_quality_rows or [])
    if not air_quality_rows:
        return forecast_rows
    aq_by_minute = {
        row_minute_of_day(row): row
        for row in air_quality_rows
        if row_minute_of_day(row) is not None
    }
    merged = []
    seen_minutes = set()
    for row in forecast_rows:
        copy = dict(row)
        minute = row_minute_of_day(copy)
        aq_row = aq_by_minute.get(minute)
        if aq_row:
            for field in OPEN_METEO_AIR_QUALITY_FIELDS:
                value = aq_row.get(field)
                if value is not None:
                    copy[field] = value
        if minute is not None:
            seen_minutes.add(minute)
        merged.append(copy)
    for row in air_quality_rows:
        minute = row_minute_of_day(row)
        if minute is None or minute in seen_minutes:
            continue
        merged.append(dict(row))
    return sorted(
        merged,
        key=lambda row: row_minute_of_day(row) if row_minute_of_day(row) is not None else 99999,
    )


def smoke_suppression_flag(profile_rows):
    saw_air_quality = False
    for item in profile_rows:
        pm2_5 = item.get("pm2_5")
        aerosol_optical_depth = item.get("aerosol_optical_depth")
        dust = item.get("dust")
        if pm2_5 is not None:
            saw_air_quality = True
            if pm2_5 >= SMOKE_PM2_5_THRESHOLD_UG_M3:
                return 1.0
        if aerosol_optical_depth is not None:
            saw_air_quality = True
            if aerosol_optical_depth >= SMOKE_AEROSOL_OPTICAL_DEPTH_THRESHOLD:
                return 1.0
        if dust is not None:
            saw_air_quality = True
            if dust >= SMOKE_DUST_THRESHOLD_UG_M3:
                return 1.0
    return 0.0 if saw_air_quality else None


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
            "temp": row_temp_native(row),
            "solar": row_value(row, "solar", "shortwave_radiation"),
            "cloud": row_value(row, "cloud_cover"),
            "low_cloud": row_value(row, "low_cloud", "cloud_cover_low"),
            "mid_cloud": row_value(row, "mid_cloud", "cloud_cover_mid"),
            "high_cloud": row_value(row, "high_cloud", "cloud_cover_high"),
            "direct_radiation": row_value(row, "direct_radiation"),
            "diffuse_radiation": row_value(row, "diffuse_radiation"),
            "precipitation": row_value(row, "precipitation"),
            "precipitation_probability": row_value(row, "precipitation_probability"),
            "cape": row_value(row, "cape"),
            "temperature_925hpa": row_value(row, "temperature_925hpa", "temperature_925hPa"),
            "temperature_850hpa": row_value(row, "temperature_850hpa", "temperature_850hPa"),
            "geopotential_height_500hpa": row_value(
                row,
                "geopotential_height_500hpa",
                "geopotential_height_500hPa",
            ),
            "wind_gust_kmh": row_value(row, "wind_gust_kmh", "wind_gusts_10m", "gust_kmh", "wind_gust"),
            "visibility": row_value(row, "visibility"),
            "soil_temperature_0cm": row_value(row, "soil_temperature_0cm"),
            "soil_moisture_0_to_1cm": row_value(row, "soil_moisture_0_to_1cm"),
            "vapour_pressure_deficit": row_value(row, "vapour_pressure_deficit"),
            "et0_fao_evapotranspiration": row_value(row, "et0_fao_evapotranspiration"),
            "pm2_5": row_value(row, "pm2_5", "pm25"),
            "pm10": row_value(row, "pm10"),
            "aerosol_optical_depth": row_value(row, "aerosol_optical_depth", "aod"),
            "dust": row_value(row, "dust"),
            "us_aqi": row_value(row, "us_aqi"),
            "european_aqi": row_value(row, "european_aqi"),
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

    direct_remaining = [
        item["direct_radiation"] for item in remaining
        if item["direct_radiation"] is not None
    ]
    diffuse_remaining = [
        item["diffuse_radiation"] for item in remaining
        if item["diffuse_radiation"] is not None
    ]
    if direct_remaining:
        features["forecast_remaining_direct_radiation_sum"] = sum(direct_remaining)
    if diffuse_remaining:
        features["forecast_remaining_diffuse_radiation_sum"] = sum(diffuse_remaining)
    features["forecast_next_3h_direct_radiation_mean"] = mean(
        item["direct_radiation"] for item in next_3h
    )
    features["forecast_next_3h_diffuse_radiation_mean"] = mean(
        item["diffuse_radiation"] for item in next_3h
    )
    features["forecast_remaining_direct_radiation_share"] = radiation_direct_share(remaining)
    features["forecast_next_3h_direct_radiation_share"] = radiation_direct_share(next_3h)

    precipitation_remaining = [
        item["precipitation"] for item in remaining
        if item["precipitation"] is not None
    ]
    if precipitation_remaining:
        features["forecast_remaining_precipitation_sum"] = sum(precipitation_remaining)
    next_precipitation = [
        item["precipitation"] for item in next_3h
        if item["precipitation"] is not None
    ]
    if next_precipitation:
        features["forecast_next_3h_precipitation_sum"] = sum(next_precipitation)
    next_precip_probability = [
        item["precipitation_probability"] for item in next_3h
        if item["precipitation_probability"] is not None
    ]
    if next_precip_probability:
        features["forecast_next_3h_precipitation_probability_max"] = max(next_precip_probability)

    features["forecast_remaining_cape_mean"] = mean(item["cape"] for item in remaining)
    next_cape = [item["cape"] for item in next_3h if item["cape"] is not None]
    if next_cape:
        features["forecast_next_3h_cape_max"] = max(next_cape)
    next_cape_mean = mean(item["cape"] for item in next_3h)
    previous_cape_mean = mean(item["cape"] for item in previous_3h)
    if next_cape_mean is not None and previous_cape_mean is not None:
        features["forecast_cape_trend_3h"] = next_cape_mean - previous_cape_mean

    surface_remaining = [item["temp"] for item in remaining if item["temp"] is not None]
    temp_925_remaining = [
        item["temperature_925hpa"] for item in remaining
        if item["temperature_925hpa"] is not None
    ]
    temp_850_remaining = [
        item["temperature_850hpa"] for item in remaining
        if item["temperature_850hpa"] is not None
    ]
    surface_mean = mean(surface_remaining)
    temp_925_mean = mean(temp_925_remaining)
    temp_850_mean = mean(temp_850_remaining)
    features["forecast_temperature_925hpa_mean"] = temp_925_mean
    features["forecast_temperature_850hpa_mean"] = temp_850_mean
    if surface_mean is not None and temp_925_mean is not None:
        features["forecast_surface_to_925_lapse_proxy"] = surface_mean - temp_925_mean
    if temp_925_mean is not None and temp_850_mean is not None:
        features["forecast_925_to_850_lapse_proxy"] = temp_925_mean - temp_850_mean
    features["forecast_geopotential_height_500hpa_mean"] = mean(
        item["geopotential_height_500hpa"] for item in remaining
    )

    wind_gusts = [
        item["wind_gust_kmh"] for item in remaining
        if item["wind_gust_kmh"] is not None
    ]
    if wind_gusts:
        features["forecast_wind_gust_max"] = max(wind_gusts)
    visibility_values = [
        item["visibility"] for item in remaining
        if item["visibility"] is not None
    ]
    if visibility_values:
        features["forecast_visibility_min"] = min(visibility_values)
    features["forecast_soil_temperature_0cm_mean"] = mean(
        item["soil_temperature_0cm"] for item in remaining
    )
    features["forecast_soil_moisture_0_to_1cm_mean"] = mean(
        item["soil_moisture_0_to_1cm"] for item in remaining
    )
    features["forecast_vapour_pressure_deficit_mean"] = mean(
        item["vapour_pressure_deficit"] for item in remaining
    )
    et0_remaining = [
        item["et0_fao_evapotranspiration"] for item in remaining
        if item["et0_fao_evapotranspiration"] is not None
    ]
    if et0_remaining:
        features["forecast_et0_fao_evapotranspiration_sum"] = sum(et0_remaining)

    features["forecast_remaining_aerosol_optical_depth_mean"] = mean(
        item["aerosol_optical_depth"] for item in remaining
    )
    features["forecast_next_3h_aerosol_optical_depth_mean"] = mean(
        item["aerosol_optical_depth"] for item in next_3h
    )
    features["forecast_remaining_pm2_5_mean"] = mean(
        item["pm2_5"] for item in remaining
    )
    features["forecast_next_3h_pm2_5_mean"] = mean(
        item["pm2_5"] for item in next_3h
    )
    features["forecast_remaining_pm10_mean"] = mean(
        item["pm10"] for item in remaining
    )
    features["forecast_remaining_dust_mean"] = mean(
        item["dust"] for item in remaining
    )
    features["forecast_smoke_suppression_flag"] = smoke_suppression_flag(remaining)

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


def _field_status(rows, field):
    rows = list(rows or [])
    missing = 0
    zero = 0
    nonzero = 0
    present = 0
    for row in rows:
        value = row_value(row, field)
        if value is None:
            missing += 1
            continue
        present += 1
        if value == 0.0:
            zero += 1
        else:
            nonzero += 1
    total = len(rows)
    return {
        "field": field,
        "rows": total,
        "present_rows": present,
        "missing_rows": missing,
        "zero_rows": zero,
        "nonzero_rows": nonzero,
        "missing_rate": missing / total if total else None,
        "zero_rate_among_present": zero / present if present else None,
    }


def forecast_profile_missing_zero_report(rows, fields=EXPANDED_OPEN_METEO_SOURCE_FIELDS):
    rows = list(rows or [])
    by_source = {}
    for row in rows:
        source = row.get("source") or "unknown"
        by_source.setdefault(source, []).append(row)
    source_fields = []
    for source, source_rows in sorted(by_source.items()):
        for field in fields:
            source_fields.append({"source": source, **_field_status(source_rows, field)})
    return {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "report_type": "forecast_profile_missing_zero",
        "summary": {
            "rows": len(rows),
            "sources": sorted(by_source),
            "fields": list(fields),
            "radiation_fields": ["direct_radiation", "diffuse_radiation"],
        },
        "fields": [_field_status(rows, field) for field in fields],
        "source_fields": source_fields,
    }


def render_forecast_profile_missing_zero_markdown(payload):
    lines = [
        "# Forecast Profile Missing-Vs-Zero Report",
        "",
        "| Source | Field | Rows | Present | Missing | Zero | Nonzero |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in (payload or {}).get("source_fields") or []:
        lines.append(
            "| {source} | {field} | {rows} | {present_rows} | {missing_rows} | "
            "{zero_rows} | {nonzero_rows} |".format(**row)
        )
    return "\n".join(lines) + "\n"


def expanded_open_meteo_promotion_gate(
    backfill_status=None,
    replay_report=None,
    min_scored_rows=30,
    min_brier_improvement=0.0,
):
    backfill_status = backfill_status or {}
    replay_report = replay_report or {}
    reasons = []
    if not backfill_status.get("all_active_markets_backfilled"):
        reasons.append("forecast_history_backfills_not_complete")
    if not backfill_status.get("per_market_candidates_retrained"):
        reasons.append("per_market_retrain_not_complete")
    if not backfill_status.get("pooled_candidate_retrained"):
        reasons.append("pooled_retrain_not_complete")
    scored_rows = int(to_float(replay_report.get("scored_rows") or (replay_report.get("summary") or {}).get("scored_rows")) or 0)
    if scored_rows < int(min_scored_rows):
        reasons.append("insufficient_replay_rows")
    improvement = to_float(replay_report.get("brier_improvement"))
    if improvement is None:
        baseline = to_float(replay_report.get("baseline_brier") or (replay_report.get("baseline") or {}).get("brier"))
        candidate = to_float(replay_report.get("candidate_brier") or (replay_report.get("candidate") or {}).get("brier"))
        improvement = baseline - candidate if baseline is not None and candidate is not None else None
    if improvement is None:
        reasons.append("missing_replay_improvement")
    elif improvement <= float(min_brier_improvement):
        reasons.append("no_positive_replay_lift")
    ok = not reasons
    return {
        "schema_version": FEATURE_SCHEMA_VERSION,
        "gate": "expanded_open_meteo_feature_promotion",
        "ok": ok,
        "status": "promotable" if ok else "blocked",
        "scored_rows": scored_rows,
        "min_scored_rows": int(min_scored_rows),
        "brier_improvement": improvement,
        "min_brier_improvement": float(min_brier_improvement),
        "reasons": reasons,
        "policy": (
            "Expanded Open-Meteo fields require all active-market backfills, "
            "per-market and pooled retraining, and settlement-scored replay lift."
        ),
    }


def simulated_reading_at(rows, minute, value_key=None, exact_window=10, max_lookback=75):
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
            (int(row["minute_of_day"]), float(value))
            for row in rows
            for value in [
                row_value(row, value_key) if value_key else row_temp_native(row)
            ]
            if value is not None and row.get("minute_of_day") is not None
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
    reanalysis_synoptic_features=None,
    wind_group_fn=None,
    cloud_group_fn=None,
    microclimate_feature_fn=None,
    wall_minute=None,
    strict=False,
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
    temps_before = [row_temp_native(row) for row in obs_before if row_temp_native(row) is not None]
    if not temps_before:
        return None

    high_so_far = max(temps_before)
    minutes_since_cutoff = wall_minute - cutoff_minutes
    if minutes_since_cutoff > 0:
        live_reading = simulated_reading_at(rows, wall_minute)
    else:
        live_reading = row_temp_native(current_obs)
    live_reading_minus_high = (
        live_reading - high_so_far if live_reading is not None else None
    )
    current_temp = row_temp_native(current_obs)
    if current_temp is None and strict:
        return None
    temp_7am = closest_temperature_native(rows, 420, 60)
    if temp_7am is None and strict:
        return None
    rise_from_7am = (
        current_temp - temp_7am
        if current_temp is not None and temp_7am is not None
        else 0.0
    )
    
    # warming_rate_2h
    temp_2h_ago = closest_temperature_native(rows, cutoff_minutes - 120, 60)
    warming_rate_2h = (
        current_temp - temp_2h_ago
        if current_temp is not None and temp_2h_ago is not None
        else 0.0
    )
    
    # hours_at_peak
    first_reached_min = None
    for row in obs_before:
        if row_temp_native(row) == high_so_far and row.get("minute_of_day") is not None:
            first_reached_min = int(row["minute_of_day"])
            break
    hours_at_peak = (
        (cutoff_minutes - first_reached_min) / 60.0
        if first_reached_min is not None
        else 0.0
    )

    dewpoint = row_dewpoint_native(current_obs)
    if dewpoint is None and strict:
        return None
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
    if wind_group is None and strict:
        return None
    wind_3h_direction = closest_wind_direction(
        rows,
        cutoff_minutes - 180,
        60,
    )
    wind_shift_3h = wind_direction_delta_degrees(
        row_wind_direction(current_obs),
        wind_3h_direction,
    )
    cloud_group = (
        cloud_group_fn(current_obs.get("condition"), current_obs.get("clouds"))
        if cloud_group_fn is not None
        else current_obs.get("cloud_group")
    )
    if cloud_group is None and strict:
        return None
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
    current_max_features = {
        **current_max_trust_features(
            None,
            history_max=high_so_far,
            current_temp=current_temp,
            cutoff_hour=cutoff_hour,
            unit=None,
        ),
        "startup_feature_quarantined_flag": 0.0,
        "startup_feature_quarantine_reason": "",
    }
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
        "dewpoint_c": dewpoint,
        "humidity": current_obs.get("humidity"),
        "pressure": pressure,
        "pressure_trend_3h": pressure_trend_3h,
        "wind_speed_kmh": current_obs.get("wind_kmh"),
        "wind_gust_kmh": row_value(current_obs, "gust_kmh", "wind_gust_kmh", "wind_gust"),
        "wind_shift_3h_degrees": wind_shift_3h if wind_shift_3h is not None else 0.0,
        **microclimate,
        "forecast_high": forecast_high,
        "forecast_gap": forecast_gap,
        "forecast_source_count": (
            forecast_source_count
            if forecast_source_count is not None
            else (1 if forecast_high is not None else 0)
        ),
        "forecast_disagreement": forecast_disagreement if forecast_disagreement is not None else 0.0,
        "forecast_robust_high": forecast_high,
        "forecast_trimmed_high": forecast_high,
        "forecast_warm_outlier_flag": 0.0,
        "forecast_warm_outlier_gap": 0.0,
        "forecast_source_family_count": (
            forecast_source_count
            if forecast_source_count is not None
            else (1 if forecast_high is not None else 0)
        ),
        **forecast_profile,
        **empty_us_guidance_features(),
        **empty_marine_context_features(),
        **empty_mrms_precip_features(),
        **empty_eccc_gridded_features(),
        **{
            **empty_reanalysis_synoptic_features(),
            **(reanalysis_synoptic_features or {}),
        },
        "minutes_since_cutoff": float(minutes_since_cutoff),
        "live_reading_temp": live_reading,
        "live_reading_minus_high": live_reading_minus_high,
        **current_max_features,
        "wind_group": wind_group,
        "cloud_group": cloud_group,
        "final_bucket": (daily or {}).get("bucket"),
    }
