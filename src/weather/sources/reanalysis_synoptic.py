"""Gated ERA5/reanalysis synoptic feature sidecar.

The normalized historical hourly schema is shared by several sources, so the
richer reanalysis-only signals live in this sidecar. Training and validation
can opt into the sidecar; live serving defaults these features to missing until
source-lag and parity gates explicitly promote them.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.market.market_registry import spec_for_id
from weather.schema_registry import schema_version
from weather.sources.historical_schema import to_float
from weather.sources.marine_context import registry_for_market
from weather.sources.reanalysis_history import ReanalysisStore, parse_local_datetime, value_at


REANALYSIS_SYNOPTIC_SCHEMA_VERSION = schema_version("reanalysis_synoptic_features")
SOURCE = "open_meteo_era5_reanalysis_synoptic"
CPC_ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
CPC_PNA_URL = "https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/norm.pna.monthly.b5001.current.ascii"
TELECONNECTION_SOURCE_URLS = {
    "oni": CPC_ONI_URL,
    "pna": CPC_PNA_URL,
}

SUPPORTED_OPEN_METEO_HISTORICAL_ARCHIVE_FIELDS = (
    "surface_pressure",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
    "wind_speed_100m",
    "wind_direction_100m",
    "soil_temperature_0_to_7cm",
    "soil_moisture_0_to_7cm",
)

UNAVAILABLE_OPEN_METEO_HISTORICAL_UPPER_AIR_FIELDS = (
    "temperature_850hPa",
    "geopotential_height_500hPa",
    "thickness_1000_500hPa",
)

REANALYSIS_SYNOPTIC_FEATURE_COLUMNS = [
    "reanalysis_synoptic_available",
    "reanalysis_prev_day_max_temp",
    "reanalysis_prev_day_min_temp",
    "reanalysis_prev_day_avg_temp",
    "reanalysis_prev_day_temp_range",
    "reanalysis_prev_day_max_dewpoint",
    "reanalysis_prev_day_max_wind_kmh",
    "reanalysis_prev_day_max_gust_kmh",
    "reanalysis_prev_day_pressure_mean_hpa",
    "reanalysis_pressure_change_24h_hpa",
    "reanalysis_prev_day_heat_anomaly",
    "reanalysis_prev_3d_heat_anomaly",
    "reanalysis_prev_7d_heat_anomaly",
    "reanalysis_prev_day_soil_temperature_0_to_7cm_mean",
    "reanalysis_prev_day_soil_moisture_0_to_7cm_mean",
    "reanalysis_prev_day_vapour_pressure_deficit_mean",
    "reanalysis_prev_day_et0_fao_evapotranspiration_sum",
    "reanalysis_prev_day_shortwave_radiation_sum",
    "reanalysis_prev_day_low_cloud_mean",
    "reanalysis_prev_day_mid_cloud_mean",
    "reanalysis_prev_day_high_cloud_mean",
    "reanalysis_coastal_flag",
    "reanalysis_continentality_km",
    "reanalysis_sea_breeze_context_flag",
    "reanalysis_lake_breeze_context_flag",
    "reanalysis_nearest_water_distance_km",
    "reanalysis_marine_context_station_count",
    "reanalysis_teleconnection_available",
    "reanalysis_enso_oni_lagged",
    "reanalysis_enso_oni_lag_months",
    "reanalysis_enso_el_nino_flag",
    "reanalysis_enso_la_nina_flag",
    "reanalysis_pna_lagged",
    "reanalysis_pna_lag_months",
    "reanalysis_pna_positive_flag",
    "reanalysis_pna_negative_flag",
]

FEATURE_META_COLUMNS = [
    "schema_version",
    "source",
    "market_id",
    "city",
    "station",
    "local_date",
    "antecedent_date",
    "temperature_unit",
]

CONTINENTALITY_KM_BY_MARKET = {
    "toronto": 43.0,
    "nyc": 14.0,
    "atlanta": 430.0,
    "austin": 230.0,
    "chicago": 34.0,
    "dallas": 430.0,
    "denver": 1000.0,
    "houston": 32.0,
    "los-angeles": 28.0,
    "miami": 12.0,
    "san-francisco": 20.0,
    "seattle": 17.0,
}

RAW_DAILY_FIELD_SPECS = {
    "soil_temperature_0_to_7cm": ("reanalysis_prev_day_soil_temperature_0_to_7cm_mean", "mean"),
    "soil_moisture_0_to_7cm": ("reanalysis_prev_day_soil_moisture_0_to_7cm_mean", "mean"),
    "vapour_pressure_deficit": ("reanalysis_prev_day_vapour_pressure_deficit_mean", "mean"),
    "et0_fao_evapotranspiration": ("reanalysis_prev_day_et0_fao_evapotranspiration_sum", "sum"),
    "shortwave_radiation": ("reanalysis_prev_day_shortwave_radiation_sum", "sum"),
    "cloud_cover_low": ("reanalysis_prev_day_low_cloud_mean", "mean"),
    "cloud_cover_mid": ("reanalysis_prev_day_mid_cloud_mean", "mean"),
    "cloud_cover_high": ("reanalysis_prev_day_high_cloud_mean", "mean"),
}

ONI_SEASON_CENTER_MONTH = {
    "DJF": 1,
    "JFM": 2,
    "FMA": 3,
    "MAM": 4,
    "AMJ": 5,
    "MJJ": 6,
    "JJA": 7,
    "JAS": 8,
    "ASO": 9,
    "SON": 10,
    "OND": 11,
    "NDJ": 12,
}

ONI_SEASON_END_MONTH = {
    "DJF": 2,
    "JFM": 3,
    "FMA": 4,
    "MAM": 5,
    "AMJ": 6,
    "MJJ": 7,
    "JJA": 8,
    "JAS": 9,
    "ASO": 10,
    "SON": 11,
    "OND": 12,
    "NDJ": 1,
}


def empty_reanalysis_synoptic_features():
    return {column: None for column in REANALYSIS_SYNOPTIC_FEATURE_COLUMNS}


def parse_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def mean(values):
    values = [to_float(value) for value in values]
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def field_value(row, key):
    return to_float((row or {}).get(key))


def month_end(year, month):
    return date(int(year), int(month), calendar.monthrange(int(year), int(month))[1])


def month_delta(later, earlier):
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def default_feature_path(spec, root=None):
    store = ReanalysisStore(spec, root)
    return store.root / "features" / "reanalysis_synoptic_features.csv"


def read_reanalysis_daily(path):
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("local_date"):
                continue
            rows.append(row)
    return rows


def _doy_window(day, radius=15):
    doy = day.timetuple().tm_yday
    max_doy = 366
    return [((doy + offset - 1) % max_doy) + 1 for offset in range(-radius, radius + 1)]


def _normal_by_doy(daily_by_date):
    grouped = defaultdict(list)
    for local_date, row in daily_by_date.items():
        value = field_value(row, "max_temp")
        if value is None:
            continue
        grouped[local_date.timetuple().tm_yday].append((local_date.year, value))
    return grouped


def _normal_max(day, grouped_by_doy, radius=15):
    values = []
    for doy in _doy_window(day, radius=radius):
        values.extend(value for year, value in grouped_by_doy.get(doy, ()) if year != day.year)
    return mean(values)


def _heat_anomaly(days, daily_by_date, grouped_by_doy):
    actuals = []
    normals = []
    for day in days:
        row = daily_by_date.get(day)
        actual = field_value(row, "max_temp")
        normal = _normal_max(day, grouped_by_doy)
        if actual is None or normal is None:
            continue
        actuals.append(actual)
        normals.append(normal)
    if not actuals or not normals:
        return None
    return mean(actuals) - mean(normals)


def load_normalized_hourly_daily_metrics(hourly_root):
    grouped = defaultdict(lambda: defaultdict(list))
    for path in sorted(Path(hourly_root).glob("year=*/month=*/observations.jsonl")):
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                try:
                    local_date = parse_date(row.get("local_date"))
                except (TypeError, ValueError):
                    continue
                for source_key, metric_key in (
                    ("pressure_hpa", "pressure_mean_hpa"),
                    ("sea_level_pressure_hpa", "sea_level_pressure_mean_hpa"),
                ):
                    value = field_value(row, source_key)
                    if value is not None:
                        grouped[local_date][metric_key].append(value)
    daily = {}
    for local_date, metrics in grouped.items():
        daily[local_date] = {key: mean(values) for key, values in metrics.items()}
    return daily


def load_raw_daily_metrics(store):
    grouped = defaultdict(lambda: defaultdict(list))
    for payload in store.iter_raw_payloads():
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        for index, value in enumerate(times):
            local_dt = parse_local_datetime(value, store.spec.tz)
            if local_dt is None:
                continue
            local_date = local_dt.date()
            for source_key in RAW_DAILY_FIELD_SPECS:
                raw_value = value_at(hourly, source_key, index)
                if raw_value is not None:
                    grouped[local_date][source_key].append(raw_value)
    daily = {}
    for local_date, metrics in grouped.items():
        out = {}
        for source_key, values in metrics.items():
            _feature_key, reducer = RAW_DAILY_FIELD_SPECS[source_key]
            out[source_key] = sum(values) if reducer == "sum" else mean(values)
        daily[local_date] = out
    return daily


def reanalysis_static_features(spec):
    marine_stations = registry_for_market(spec.id)
    distances = [
        to_float(station.get("distance_km"))
        for station in marine_stations
    ]
    distances = [value for value in distances if value is not None]
    lake_stations = [
        station for station in marine_stations
        if "lake" in str(station.get("water_body") or "").lower()
    ]
    return {
        "reanalysis_coastal_flag": 1.0 if getattr(spec, "coastal", False) else 0.0,
        "reanalysis_continentality_km": CONTINENTALITY_KM_BY_MARKET.get(spec.id),
        "reanalysis_sea_breeze_context_flag": 1.0 if marine_stations else 0.0,
        "reanalysis_lake_breeze_context_flag": 1.0 if lake_stations else 0.0,
        "reanalysis_nearest_water_distance_km": min(distances) if distances else None,
        "reanalysis_marine_context_station_count": float(len(marine_stations)),
    }


def parse_cpc_oni_ascii(text):
    rows = []
    for line in str(text or "").splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        season = parts[0].upper()
        if season not in ONI_SEASON_CENTER_MONTH:
            continue
        try:
            year = int(parts[1])
        except (TypeError, ValueError):
            continue
        value = to_float(parts[3])
        if value is None or value <= -90.0:
            continue
        center_month = ONI_SEASON_CENTER_MONTH[season]
        end_month = ONI_SEASON_END_MONTH[season]
        end_year = year + 1 if season == "NDJ" else year
        rows.append({
            "index": "oni",
            "season": season,
            "year": year,
            "month": center_month,
            "center_month": date(year, center_month, 1),
            "available_month_end": month_end(end_year, end_month),
            "value": value,
        })
    return sorted(rows, key=lambda row: row["available_month_end"])


def parse_cpc_pna_ascii(text):
    rows = []
    for line in str(text or "").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            year = int(parts[0])
            month = int(parts[1])
        except (TypeError, ValueError):
            continue
        if not 1 <= month <= 12:
            continue
        value = to_float(parts[2])
        if value is None or value <= -90.0:
            continue
        rows.append({
            "index": "pna",
            "year": year,
            "month": month,
            "center_month": date(year, month, 1),
            "available_month_end": month_end(year, month),
            "value": value,
        })
    return sorted(rows, key=lambda row: row["available_month_end"])


def read_text_if_exists(path):
    if not path:
        return ""
    path = Path(path)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def load_teleconnection_index(oni_path=None, pna_path=None):
    return {
        "oni": parse_cpc_oni_ascii(read_text_if_exists(oni_path)),
        "pna": parse_cpc_pna_ascii(read_text_if_exists(pna_path)),
        "source_urls": dict(TELECONNECTION_SOURCE_URLS),
    }


def _latest_available_teleconnection(records, local_date):
    local_date = parse_date(local_date)
    cutoff = date(local_date.year, local_date.month, 1)
    candidates = [
        row for row in records or []
        if row.get("available_month_end") and row["available_month_end"] < cutoff
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: row["available_month_end"])


def teleconnection_features_for_date(local_date, teleconnection_index=None):
    features = {
        "reanalysis_teleconnection_available": 0.0,
        "reanalysis_enso_oni_lagged": None,
        "reanalysis_enso_oni_lag_months": None,
        "reanalysis_enso_el_nino_flag": None,
        "reanalysis_enso_la_nina_flag": None,
        "reanalysis_pna_lagged": None,
        "reanalysis_pna_lag_months": None,
        "reanalysis_pna_positive_flag": None,
        "reanalysis_pna_negative_flag": None,
    }
    teleconnection_index = teleconnection_index or {}
    target_month = date(parse_date(local_date).year, parse_date(local_date).month, 1)
    oni = _latest_available_teleconnection(teleconnection_index.get("oni"), local_date)
    pna = _latest_available_teleconnection(teleconnection_index.get("pna"), local_date)
    if oni:
        value = oni["value"]
        features["reanalysis_teleconnection_available"] = 1.0
        features["reanalysis_enso_oni_lagged"] = value
        features["reanalysis_enso_oni_lag_months"] = float(month_delta(target_month, oni["center_month"]))
        features["reanalysis_enso_el_nino_flag"] = 1.0 if value >= 0.5 else 0.0
        features["reanalysis_enso_la_nina_flag"] = 1.0 if value <= -0.5 else 0.0
    if pna:
        value = pna["value"]
        features["reanalysis_teleconnection_available"] = 1.0
        features["reanalysis_pna_lagged"] = value
        features["reanalysis_pna_lag_months"] = float(month_delta(target_month, pna["center_month"]))
        features["reanalysis_pna_positive_flag"] = 1.0 if value >= 0.5 else 0.0
        features["reanalysis_pna_negative_flag"] = 1.0 if value <= -0.5 else 0.0
    return features


def build_reanalysis_synoptic_rows(
    spec,
    daily_rows,
    hourly_daily_metrics=None,
    raw_daily_metrics=None,
    teleconnection_index=None,
):
    daily_by_date = {}
    for row in daily_rows or []:
        try:
            local_date = parse_date(row.get("local_date"))
        except (TypeError, ValueError):
            continue
        daily_by_date[local_date] = row

    grouped_by_doy = _normal_by_doy(daily_by_date)
    hourly_daily_metrics = hourly_daily_metrics or {}
    raw_daily_metrics = raw_daily_metrics or {}
    static_features = reanalysis_static_features(spec)
    rows = []
    for local_date in sorted(daily_by_date):
        antecedent_date = local_date - timedelta(days=1)
        prev = daily_by_date.get(antecedent_date)
        features = empty_reanalysis_synoptic_features()
        features.update(static_features)
        features.update(teleconnection_features_for_date(local_date, teleconnection_index))
        features["reanalysis_synoptic_available"] = 1.0 if prev else 0.0
        if prev:
            max_temp = field_value(prev, "max_temp")
            min_temp = field_value(prev, "min_temp")
            features.update({
                "reanalysis_prev_day_max_temp": max_temp,
                "reanalysis_prev_day_min_temp": min_temp,
                "reanalysis_prev_day_avg_temp": field_value(prev, "avg_temp"),
                "reanalysis_prev_day_temp_range": (
                    max_temp - min_temp if max_temp is not None and min_temp is not None else None
                ),
                "reanalysis_prev_day_max_dewpoint": field_value(prev, "max_dewpoint"),
                "reanalysis_prev_day_max_wind_kmh": field_value(prev, "max_wind_kmh"),
                "reanalysis_prev_day_max_gust_kmh": field_value(prev, "max_gust_kmh"),
            })
            pressure = (hourly_daily_metrics.get(antecedent_date) or {}).get("pressure_mean_hpa")
            prev_pressure = (
                hourly_daily_metrics.get(antecedent_date - timedelta(days=1)) or {}
            ).get("pressure_mean_hpa")
            features["reanalysis_prev_day_pressure_mean_hpa"] = pressure
            features["reanalysis_pressure_change_24h_hpa"] = (
                pressure - prev_pressure
                if pressure is not None and prev_pressure is not None
                else None
            )
            features["reanalysis_prev_day_heat_anomaly"] = _heat_anomaly(
                [antecedent_date],
                daily_by_date,
                grouped_by_doy,
            )
            features["reanalysis_prev_3d_heat_anomaly"] = _heat_anomaly(
                [local_date - timedelta(days=offset) for offset in range(1, 4)],
                daily_by_date,
                grouped_by_doy,
            )
            features["reanalysis_prev_7d_heat_anomaly"] = _heat_anomaly(
                [local_date - timedelta(days=offset) for offset in range(1, 8)],
                daily_by_date,
                grouped_by_doy,
            )
            raw_metrics = raw_daily_metrics.get(antecedent_date) or {}
            for raw_key, (feature_key, _reducer) in RAW_DAILY_FIELD_SPECS.items():
                value = raw_metrics.get(raw_key)
                if value is not None:
                    features[feature_key] = value

        row = {
            "schema_version": REANALYSIS_SYNOPTIC_SCHEMA_VERSION,
            "source": SOURCE,
            "market_id": spec.id,
            "city": spec.city_label,
            "station": f"era5:{spec.lat:.4f},{spec.lon:.4f}",
            "local_date": local_date.isoformat(),
            "antecedent_date": antecedent_date.isoformat(),
            "temperature_unit": spec.display_unit,
        }
        row.update(features)
        rows.append(row)
    return rows


def write_feature_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [*FEATURE_META_COLUMNS, *REANALYSIS_SYNOPTIC_FEATURE_COLUMNS]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def load_reanalysis_synoptic_features(path=None, spec=None, root=None):
    if path is None:
        if spec is None:
            return {}
        path = default_feature_path(spec, root=root)
    path = Path(path)
    if not path.exists():
        return {}
    index = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            local_date = row.get("local_date")
            if not local_date:
                continue
            index[local_date] = {
                column: field_value(row, column)
                for column in REANALYSIS_SYNOPTIC_FEATURE_COLUMNS
            }
    return index


def summarize_feature_rows(spec, rows):
    rows = list(rows or [])
    present_by_field = {
        column: sum(1 for row in rows if row.get(column) not in (None, ""))
        for column in REANALYSIS_SYNOPTIC_FEATURE_COLUMNS
    }
    available_rows = sum(1 for row in rows if to_float(row.get("reanalysis_synoptic_available")) == 1.0)
    return {
        "schema_version": REANALYSIS_SYNOPTIC_SCHEMA_VERSION,
        "source": SOURCE,
        "market_id": spec.id,
        "city": spec.city_label,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": len(rows),
        "available_rows": available_rows,
        "first_date": rows[0]["local_date"] if rows else None,
        "last_date": rows[-1]["local_date"] if rows else None,
        "feature_columns": list(REANALYSIS_SYNOPTIC_FEATURE_COLUMNS),
        "present_by_field": present_by_field,
        "supported_open_meteo_historical_archive_fields": list(
            SUPPORTED_OPEN_METEO_HISTORICAL_ARCHIVE_FIELDS
        ),
        "teleconnection_source_urls": dict(TELECONNECTION_SOURCE_URLS),
        "unavailable_open_meteo_historical_upper_air_fields": list(
            UNAVAILABLE_OPEN_METEO_HISTORICAL_UPPER_AIR_FIELDS
        ),
        "upper_air_policy": (
            "Open-Meteo Historical Weather / ERA5 archive returns supported surface, "
            "soil, cloud, radiation, pressure, VPD, ET0, and 100 m wind variables. "
            "Forecast-style pressure-level variables are recorded as unavailable "
            "until a pressure-level reanalysis source is added."
        ),
        "static_feature_policy": (
            "Coastal, continentality, and static marine/lake-breeze context fields "
            "come from market-registry and marine-context metadata and are kept in "
            "the gated family so pooled validation can score them."
        ),
        "teleconnection_policy": (
            "ENSO/PNA teleconnection values are loaded from local NOAA CPC ASCII "
            "snapshots and lagged to the latest completed month or season available "
            "before the target month, avoiding target-month leakage."
        ),
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_summary_markdown(payload):
    def fmt(value):
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    lines = [
        "# Reanalysis Synoptic Feature Sidecar",
        "",
        f"Market: `{payload.get('market_id')}`",
        f"Rows: `{payload.get('rows', 0)}`",
        f"Rows with antecedent reanalysis: `{payload.get('available_rows', 0)}`",
        f"Date range: `{payload.get('first_date')}` to `{payload.get('last_date')}`",
        "",
        "## Field Coverage",
        "",
        "| Field | Present Rows |",
        "| :--- | ---: |",
    ]
    for field, count in (payload.get("present_by_field") or {}).items():
        lines.append(f"| `{field}` | {fmt(count)} |")
    lines.extend([
        "",
        "## Unsupported Upper-Air Fields",
        "",
    ])
    for field in payload.get("unavailable_open_meteo_historical_upper_air_fields") or []:
        lines.append(f"- `{field}`")
    lines.extend([
        "",
        payload.get("upper_air_policy") or "",
        "",
        "## Teleconnection Policy",
        "",
        payload.get("teleconnection_policy") or "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def build_sidecar_for_spec(spec, root=None, oni_path=None, pna_path=None):
    store = ReanalysisStore(spec, root)
    daily_rows = read_reanalysis_daily(store.daily_root / "daily_summary.csv")
    hourly_daily = load_normalized_hourly_daily_metrics(store.hourly_root)
    raw_daily = load_raw_daily_metrics(store)
    teleconnection_index = load_teleconnection_index(oni_path=oni_path, pna_path=pna_path)
    rows = build_reanalysis_synoptic_rows(
        spec,
        daily_rows,
        hourly_daily_metrics=hourly_daily,
        raw_daily_metrics=raw_daily,
        teleconnection_index=teleconnection_index,
    )
    return store, rows, summarize_feature_rows(spec, rows)


def cmd_build(args):
    spec = spec_for_id(args.market)
    store, rows, summary = build_sidecar_for_spec(
        spec,
        root=args.data_root or None,
        oni_path=args.oni_path or None,
        pna_path=args.pna_path or None,
    )
    features_out = Path(args.features_out) if args.features_out else default_feature_path(spec, root=args.data_root or None)
    summary_out = (
        Path(args.summary_out)
        if args.summary_out
        else store.root / "features" / "reanalysis_synoptic_summary.json"
    )
    report_out = (
        Path(args.report_out)
        if args.report_out
        else store.root / "features" / "reanalysis_synoptic_report.md"
    )
    write_feature_csv(features_out, rows)
    write_json(summary_out, summary)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.write_text(render_summary_markdown(summary), encoding="utf-8")
    print(
        f"Wrote {len(rows)} reanalysis synoptic rows for {spec.id}: "
        f"{features_out}"
    )


def build_parser():
    parser = argparse.ArgumentParser(description="Build gated reanalysis/synoptic feature sidecars.")
    parser.add_argument("--market", default="toronto")
    parser.add_argument("--data-root", default="")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--features-out", default="")
    build.add_argument("--summary-out", default="")
    build.add_argument("--report-out", default="")
    build.add_argument("--oni-path", default="")
    build.add_argument("--pna-path", default="")
    build.set_defaults(func=cmd_build)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
