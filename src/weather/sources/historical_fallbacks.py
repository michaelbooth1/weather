"""Supplemental historical fallback source helpers.

Meteostat and NASA POWER are useful for station discovery, source-trust
research, and energy-budget context. They are not settlement labels.
"""
from __future__ import annotations

import csv
import io
import json
import math
from datetime import datetime

from weather.sources.historical_schema import to_float
from weather.units import c_to_native


HISTORICAL_FALLBACKS_SCHEMA_VERSION = "historical_fallbacks_v0.1"
METEOSTAT_HOURLY_BASE_URL = "https://data.meteostat.net/hourly"
NASA_POWER_HOURLY_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
NASA_POWER_PARAMETERS = (
    "ALLSKY_SFC_SW_DWN",
    "CLRSKY_SFC_SW_DWN",
    "T2M",
    "T2MDEW",
    "RH2M",
    "PRECTOTCORR",
    "PS",
    "WS10M",
    "WD10M",
)
NASA_FILL_VALUES = {-999, -999.0, -9999, -9999.0}
MODEL_SOURCE_TOKENS = ("model", "mosmix", "dwd_mosmix", "interpolation", "interpolated")
FALLBACK_SOURCES = {"meteostat", "nasa_power"}
REFERENCE_SOURCES = {"wu", "metar", "ghcnh", "reanalysis", "validated_supplemental"}
DISALLOWED_PROMOTION_ROLES = {"settlement_label", "canonical_observation_replacement"}


def build_meteostat_hourly_url(year, station_id):
    return f"{METEOSTAT_HOURLY_BASE_URL}/{int(year)}/{station_id}.csv.gz"


def haversine_km(lat1, lon1, lat2, lon2):
    lat1 = math.radians(float(lat1))
    lon1 = math.radians(float(lon1))
    lat2 = math.radians(float(lat2))
    lon2 = math.radians(float(lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2.0 * math.asin(math.sqrt(a))


def parse_meteostat_station_metadata(text):
    text = text or ""
    stripped = text.lstrip()
    if not stripped:
        return []
    if stripped[0] in "[{":
        payload = json.loads(text)
        rows = payload.get("stations") if isinstance(payload, dict) else payload
        return [dict(row) for row in rows or []]
    return list(csv.DictReader(io.StringIO(text)))


def _station_lat(row):
    return to_float(row.get("latitude") or row.get("lat") or row.get("LATITUDE"))


def _station_lon(row):
    return to_float(row.get("longitude") or row.get("lon") or row.get("LONGITUDE"))


def _station_id(row):
    return row.get("id") or row.get("station") or row.get("wmo") or row.get("ICAO") or ""


def station_discovery_report(specs, station_rows, max_candidates=3):
    reports = []
    for spec in specs:
        candidates = []
        for station in station_rows or []:
            lat = _station_lat(station)
            lon = _station_lon(station)
            if lat is None or lon is None:
                continue
            distance = haversine_km(spec.lat, spec.lon, lat, lon)
            candidates.append({
                "station_id": _station_id(station),
                "name": station.get("name") or station.get("NAME"),
                "icao": (station.get("icao") or station.get("ICAO") or "").upper(),
                "wmo": station.get("wmo") or station.get("WMO"),
                "country": station.get("country") or station.get("country_code") or station.get("ISO_CODE"),
                "latitude": lat,
                "longitude": lon,
                "distance_km": round(distance, 3),
                "meteostat_inventory": {
                    key: station.get(key)
                    for key in ("hourly_start", "hourly_end", "daily_start", "daily_end", "inventory")
                    if key in station
                },
            })
        candidates.sort(key=lambda row: row["distance_km"])
        canonical_match = next(
            (row for row in candidates if row.get("icao") == spec.icao.upper()),
            None,
        )
        reports.append({
            "schema_version": HISTORICAL_FALLBACKS_SCHEMA_VERSION,
            "market_id": spec.id,
            "city": spec.city_label,
            "canonical_icao": spec.icao,
            "source": "meteostat",
            "allowed_role": "supplemental_discovery",
            "canonical_match": canonical_match,
            "candidates": candidates[:max_candidates],
        })
    return {
        "schema_version": HISTORICAL_FALLBACKS_SCHEMA_VERSION,
        "source": "meteostat",
        "markets": reports,
    }


def _source_columns(row):
    return {
        key: value for key, value in (row or {}).items()
        if key.endswith("_source") or key.startswith("_source") or key in {"source", "_source"}
    }


def _classify_sources(source_columns):
    values = [str(value).lower() for value in (source_columns or {}).values() if value not in (None, "")]
    if not values:
        return "unknown"
    model_flags = [any(token in value for token in MODEL_SOURCE_TOKENS) for value in values]
    if all(model_flags):
        return "model_filled"
    if any(model_flags):
        return "mixed"
    return "observed_station"


def normalize_meteostat_hourly_csv(text, spec, station_id):
    rows = []
    for raw in csv.DictReader(io.StringIO(text or "")):
        time_value = raw.get("time") or raw.get("date") or raw.get("datetime")
        hour_value = raw.get("hour")
        if time_value and hour_value and len(str(time_value)) == 10:
            time_value = f"{time_value}T{int(hour_value):02d}:00"
        if not time_value:
            continue
        try:
            local_dt = datetime.fromisoformat(str(time_value).replace(" ", "T")).replace(tzinfo=spec.tz)
        except ValueError:
            continue
        temp_c = to_float(raw.get("temp"))
        source_cols = _source_columns(raw)
        source_class = _classify_sources(source_cols)
        rows.append({
            "schema_version": HISTORICAL_FALLBACKS_SCHEMA_VERSION,
            "source": "meteostat",
            "source_role": "supplemental_context",
            "allowed_as_settlement_label": False,
            "market": spec.id,
            "station": station_id,
            "valid_time_local": local_dt.isoformat(),
            "local_date": local_dt.date().isoformat(),
            "minute_of_day": local_dt.hour * 60 + local_dt.minute,
            "temp_native": c_to_native(temp_c, spec.display_unit),
            "temp_c": temp_c,
            "dewpoint_native": c_to_native(raw.get("dwpt"), spec.display_unit),
            "dewpoint_c": to_float(raw.get("dwpt")),
            "humidity": to_float(raw.get("rhum")),
            "precipitation_mm": to_float(raw.get("prcp")),
            "wind_dir_deg": to_float(raw.get("wdir")),
            "wind_speed_kmh": to_float(raw.get("wspd")),
            "pressure_hpa": to_float(raw.get("pres")),
            "cloud_cover": to_float(raw.get("cldc")),
            "condition_code": raw.get("coco"),
            "source_columns": source_cols,
            "source_class": source_class,
            "model_filled": source_class in {"model_filled", "mixed"},
            "raw": dict(raw),
        })
    return rows


def build_nasa_power_hourly_params(spec, start_date, end_date, parameters=NASA_POWER_PARAMETERS):
    return {
        "latitude": spec.lat,
        "longitude": spec.lon,
        "start": str(start_date).replace("-", ""),
        "end": str(end_date).replace("-", ""),
        "community": "RE",
        "parameters": ",".join(parameters),
        "format": "JSON",
        "time-standard": "LST",
    }


def _power_value(series, key):
    value = to_float((series or {}).get(key))
    if value in NASA_FILL_VALUES:
        return None
    return value


def normalize_nasa_power_payload(payload, spec):
    params = (((payload or {}).get("properties") or {}).get("parameter") or {})
    keys = sorted({key for series in params.values() for key in (series or {})})
    rows = []
    fill_counts = {
        name: {"total": 0, "fill": 0, "fill_rate": None}
        for name in NASA_POWER_PARAMETERS
    }
    for key in keys:
        try:
            local_dt = datetime.strptime(key, "%Y%m%d%H").replace(tzinfo=spec.tz)
        except ValueError:
            continue
        values = {}
        for name in NASA_POWER_PARAMETERS:
            series = params.get(name) or {}
            if key in series:
                fill_counts[name]["total"] += 1
            raw_value = to_float(series.get(key))
            if raw_value in NASA_FILL_VALUES:
                fill_counts[name]["fill"] += 1
                values[name] = None
            else:
                values[name] = raw_value
        rows.append({
            "schema_version": HISTORICAL_FALLBACKS_SCHEMA_VERSION,
            "source": "nasa_power",
            "source_role": "supplemental_energy_budget",
            "allowed_as_settlement_label": False,
            "market": spec.id,
            "station": f"nasa_power:{spec.lat:.4f},{spec.lon:.4f}",
            "valid_time_local": local_dt.isoformat(),
            "local_date": local_dt.date().isoformat(),
            "minute_of_day": local_dt.hour * 60 + local_dt.minute,
            "temp_native": c_to_native(values.get("T2M"), spec.display_unit),
            "temp_c": values.get("T2M"),
            "dewpoint_native": c_to_native(values.get("T2MDEW"), spec.display_unit),
            "dewpoint_c": values.get("T2MDEW"),
            "humidity": values.get("RH2M"),
            "precipitation_mm": values.get("PRECTOTCORR"),
            "pressure_hpa": values.get("PS") * 10.0 if values.get("PS") is not None else None,
            "wind_speed_kmh": values.get("WS10M") * 3.6 if values.get("WS10M") is not None else None,
            "wind_dir_deg": values.get("WD10M"),
            "solar_allsky_wh_m2": values.get("ALLSKY_SFC_SW_DWN"),
            "solar_clearsky_wh_m2": values.get("CLRSKY_SFC_SW_DWN"),
            "raw_parameters": values,
        })
    for stats in fill_counts.values():
        total = stats["total"]
        stats["fill_rate"] = stats["fill"] / total if total else None
    return {
        "schema_version": HISTORICAL_FALLBACKS_SCHEMA_VERSION,
        "source": "nasa_power",
        "source_role": "supplemental_energy_budget",
        "allowed_as_settlement_label": False,
        "rows": rows,
        "fill_value_stats": fill_counts,
        "row_count": len(rows),
    }


def fallback_source_policy():
    return {
        "schema_version": HISTORICAL_FALLBACKS_SCHEMA_VERSION,
        "sources": {
            "meteostat": {
                "allowed_roles": ["supplemental_discovery", "source_trust", "weather_regime_context"],
                "disallowed_roles": ["settlement_label", "canonical_observation_replacement"],
                "requires_source_column_preservation": True,
            },
            "nasa_power": {
                "allowed_roles": ["energy_budget_context", "solar_backfill", "weather_regime_context"],
                "disallowed_roles": ["settlement_label", "canonical_observation_replacement"],
                "requires_fill_value_audit": True,
            },
        },
    }


def _row_market(row):
    return str((row or {}).get("market_id") or (row or {}).get("market") or "").lower()


def _row_source(row):
    source = str((row or {}).get("source") or "").lower()
    role = str((row or {}).get("source_role") or "").lower()
    if role == "supplemental" or source.startswith("ghcnh_supplemental"):
        return "validated_supplemental"
    return source


def _row_regime(row):
    for key in ("regime", "weather_regime", "temperature_regime"):
        value = (row or {}).get(key)
        if value:
            return str(value)
    return "all"


def _row_slot(row):
    local_date = (row or {}).get("local_date")
    if not local_date:
        value = (row or {}).get("valid_time_local") or (row or {}).get("valid_time")
        local_date = str(value or "")[:10]
    minute = (row or {}).get("minute_of_day")
    if minute is None:
        value = (row or {}).get("time")
        if value and ":" in str(value):
            try:
                hour, minute_text = str(value)[:5].split(":")
                minute = int(hour) * 60 + int(minute_text)
            except ValueError:
                minute = None
    return (str(local_date), int(minute) if minute is not None else None)


def _row_value(row):
    for key in ("temp_native", "high", "day_max_native", "temp_c", "temperature"):
        value = to_float((row or {}).get(key))
        if value is not None:
            return value
    return None


def _mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _source_class(row):
    if (row or {}).get("source_class"):
        return str((row or {}).get("source_class"))
    if (row or {}).get("model_filled"):
        return "model_filled"
    return "unknown"


def _index_reference_rows(rows):
    indexed = {}
    for row in rows or []:
        source = _row_source(row)
        if source not in REFERENCE_SOURCES:
            continue
        market = _row_market(row)
        regime = _row_regime(row)
        slot = _row_slot(row)
        indexed.setdefault((market, regime, source), {})[slot] = row
        indexed.setdefault((market, "all", source), {})[slot] = row
    return indexed


def fallback_coverage_bias_report(fallback_rows, reference_rows):
    """Compare supplemental fallback rows against trusted reference sources.

    Rows are matched by market, local date, and minute-of-day when available.
    The report is source-trust evidence only; it does not mark either fallback
    source as settlement truth.
    """
    fallback_rows = list(fallback_rows or [])
    reference_rows = list(reference_rows or [])
    references = _index_reference_rows(reference_rows)
    pair_rows = []
    for fallback_row in fallback_rows:
        fallback_source = _row_source(fallback_row)
        if fallback_source not in FALLBACK_SOURCES:
            continue
        market = _row_market(fallback_row)
        regime = _row_regime(fallback_row)
        slot = _row_slot(fallback_row)
        fallback_value = _row_value(fallback_row)
        for ref_regime in (regime, "all"):
            for reference_source in sorted(REFERENCE_SOURCES):
                reference_index = references.get((market, ref_regime, reference_source)) or {}
                if not reference_index:
                    continue
                reference_row = reference_index.get(slot)
                reference_value = _row_value(reference_row)
                pair_rows.append({
                    "market_id": market,
                    "regime": ref_regime,
                    "fallback_source": fallback_source,
                    "reference_source": reference_source,
                    "slot": slot,
                    "fallback_value": fallback_value,
                    "reference_value": reference_value,
                    "comparable": fallback_value is not None and reference_value is not None,
                    "model_filled": _source_class(fallback_row) in {"model_filled", "mixed"},
                })
    groups = {}
    for row in pair_rows:
        key = (row["market_id"], row["regime"], row["fallback_source"], row["reference_source"])
        groups.setdefault(key, []).append(row)
    comparisons = []
    for (market, regime, fallback_source, reference_source), rows in sorted(groups.items()):
        reference_slots = references.get((market, regime, reference_source)) or {}
        comparable = [row for row in rows if row["comparable"]]
        diffs = [row["fallback_value"] - row["reference_value"] for row in comparable]
        comparisons.append({
            "market_id": market,
            "regime": regime,
            "fallback_source": fallback_source,
            "reference_source": reference_source,
            "reference_rows": len(reference_slots),
            "fallback_rows": len(rows),
            "overlap_rows": len(comparable),
            "coverage_rate": len(comparable) / len(reference_slots) if reference_slots else None,
            "bias_fallback_minus_reference": _mean(diffs),
            "mae_fallback_vs_reference": _mean([abs(value) for value in diffs]),
            "max_abs_bias": max([abs(value) for value in diffs], default=None),
            "model_filled_rows": sum(1 for row in rows if row["model_filled"]),
            "model_filled_rate": (
                sum(1 for row in rows if row["model_filled"]) / len(rows)
                if rows else None
            ),
        })
    markets = {}
    for row in comparisons:
        markets.setdefault(row["market_id"], []).append(row)
    return {
        "schema_version": HISTORICAL_FALLBACKS_SCHEMA_VERSION,
        "source": "historical_fallbacks",
        "report_type": "coverage_bias",
        "summary": {
            "fallback_rows": len(fallback_rows),
            "reference_rows": len(reference_rows),
            "comparison_rows": len(comparisons),
            "comparable_pairs": sum(row["overlap_rows"] for row in comparisons),
            "fallback_sources": sorted({
                _row_source(row) for row in fallback_rows
                if _row_source(row) in FALLBACK_SOURCES
            }),
            "reference_sources": sorted({
                _row_source(row) for row in reference_rows
                if _row_source(row) in REFERENCE_SOURCES
            }),
        },
        "markets": [
            {"market_id": market, "comparisons": rows}
            for market, rows in sorted(markets.items())
        ],
        "comparisons": comparisons,
    }


def render_fallback_coverage_bias_markdown(payload):
    lines = [
        "# Historical Fallback Coverage And Bias",
        "",
        "| Market | Regime | Fallback | Reference | Coverage | Bias | MAE | Model-Filled Rate |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in (payload or {}).get("comparisons") or []:
        lines.append(
            "| {market_id} | {regime} | {fallback_source} | {reference_source} | "
            "{coverage_rate} | {bias_fallback_minus_reference} | "
            "{mae_fallback_vs_reference} | {model_filled_rate} |".format(**row)
        )
    return "\n".join(lines) + "\n"


def _metric(report, *keys):
    current = report or {}
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def fallback_feature_promotion_gate(
    replay_report,
    min_scored_rows=30,
    min_brier_improvement=0.0,
):
    rows = int(
        to_float(_metric(replay_report, "scored_rows"))
        or to_float(_metric(replay_report, "summary", "scored_rows"))
        or 0
    )
    improvement = to_float(_metric(replay_report, "brier_improvement"))
    if improvement is None:
        baseline = to_float(_metric(replay_report, "baseline_brier"))
        candidate = to_float(_metric(replay_report, "candidate_brier"))
        if baseline is None:
            baseline = to_float(_metric(replay_report, "baseline", "brier"))
        if candidate is None:
            candidate = to_float(_metric(replay_report, "candidate", "brier"))
        improvement = baseline - candidate if baseline is not None and candidate is not None else None
    roles = set(replay_report.get("feature_roles") or replay_report.get("roles") or [])
    disallowed = sorted(roles & DISALLOWED_PROMOTION_ROLES)
    reasons = []
    if rows < int(min_scored_rows):
        reasons.append("insufficient_scored_rows")
    if improvement is None:
        reasons.append("missing_replay_improvement")
    elif improvement <= float(min_brier_improvement):
        reasons.append("no_positive_brier_improvement")
    if disallowed:
        reasons.append("disallowed_truth_role")
    ok = not reasons
    return {
        "schema_version": HISTORICAL_FALLBACKS_SCHEMA_VERSION,
        "source": "historical_fallbacks",
        "gate": "fallback_feature_promotion",
        "ok": ok,
        "status": "promotable" if ok else "blocked",
        "scored_rows": rows,
        "min_scored_rows": int(min_scored_rows),
        "brier_improvement": improvement,
        "min_brier_improvement": float(min_brier_improvement),
        "feature_roles": sorted(roles),
        "disallowed_roles": disallowed,
        "reasons": reasons,
        "policy": "Fallback features require replay lift beyond existing Open-Meteo/reanalysis/history features.",
    }
