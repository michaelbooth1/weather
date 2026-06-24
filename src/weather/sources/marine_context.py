"""Marine and lake-breeze context source helpers.

The live model should treat coastal sensors as contextual evidence, never as
settlement labels. This module keeps station metadata, parsers, freshness gates,
and diagnostic feature derivation together so missing sensors stay explicit.
"""
from __future__ import annotations

import hashlib
import gzip
from datetime import date, datetime, timezone

import requests

from weather.sources.historical_schema import to_float
from weather.units import c_to_native


MARINE_CONTEXT_SCHEMA_VERSION = "marine_context_v0.1"
MARINE_STATION_HISTORY_SCHEMA_VERSION = "marine_station_history_v0.1"
SOURCE = "marine_context"
HISTORY_SOURCE = "marine_station_history"
COOPS_DATAGETTER_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
NDBC_REALTIME_URL = "https://www.ndbc.noaa.gov/data/realtime2/{station}.txt"
NDBC_HISTORICAL_URL = "https://www.ndbc.noaa.gov/data/historical/stdmet/{station}h{year}.txt.gz"
DEFAULT_MAX_STALE_MINUTES = 90


MARINE_CONTEXT_FEATURE_COLUMNS = [
    "marine_station_count",
    "marine_latest_age_minutes",
    "marine_missing_sensor_count",
    "marine_water_temp_native",
    "marine_air_temp_native",
    "marine_water_minus_air_temp",
    "marine_water_minus_forecast_high",
    "marine_air_minus_current_temp",
    "marine_wind_speed_kmh",
    "marine_wind_direction_degrees",
    "marine_onshore_flow",
    "marine_offshore_flow",
    "marine_onshore_water_minus_forecast_high",
    "marine_onshore_cooling_potential",
    "marine_post_cutoff_onshore_reversal",
    "marine_breeze_risk",
    "marine_layer_suppression",
]


MARINE_CONTEXT_REGISTRY = {
    "toronto": [
        {
            "provider": "ndbc",
            "station_id": "45159",
            "station_name": "Northwest Lake Ontario buoy",
            "water_body": "Lake Ontario",
            "distance_km": 43.0,
            "bearing_degrees": 95.0,
            "sensor_support": ("wind", "air_temperature", "water_temperature", "pressure"),
            "required_sensors": ("wind", "water_temperature"),
            "onshore_direction_min": 60.0,
            "onshore_direction_max": 160.0,
            "adoption_rationale": "Lake Ontario east/southeast flow can cap Pearson afternoon highs.",
        },
    ],
    "nyc": [
        {
            "provider": "coops",
            "station_id": "8518750",
            "station_name": "The Battery, NY",
            "water_body": "New York Harbor",
            "distance_km": 14.0,
            "bearing_degrees": 210.0,
            "sensor_support": ("wind", "air_temperature", "water_temperature", "pressure", "humidity"),
            "required_sensors": ("wind", "air_temperature", "water_temperature"),
            "onshore_direction_min": 45.0,
            "onshore_direction_max": 165.0,
            "adoption_rationale": "Harbor and Atlantic onshore flow can suppress LGA highs.",
        },
        {
            "provider": "ndbc",
            "station_id": "44065",
            "station_name": "New York Harbor Entrance",
            "water_body": "Atlantic Ocean",
            "distance_km": 33.0,
            "bearing_degrees": 170.0,
            "sensor_support": ("wind", "air_temperature", "water_temperature", "pressure"),
            "required_sensors": ("wind", "water_temperature"),
            "onshore_direction_min": 45.0,
            "onshore_direction_max": 165.0,
            "adoption_rationale": "Outer-harbor marine layer context for NYC sea-breeze days.",
        },
    ],
    "miami": [
        {
            "provider": "coops",
            "station_id": "8723214",
            "station_name": "Virginia Key, FL",
            "water_body": "Biscayne Bay",
            "distance_km": 12.0,
            "bearing_degrees": 115.0,
            "sensor_support": ("wind", "air_temperature", "water_temperature", "pressure", "humidity"),
            "required_sensors": ("wind", "air_temperature", "water_temperature"),
            "onshore_direction_min": 45.0,
            "onshore_direction_max": 160.0,
            "adoption_rationale": "Atlantic/Biscayne Bay breeze and marine humidity near KMIA.",
        },
    ],
    "houston": [
        {
            "provider": "coops",
            "station_id": "8770613",
            "station_name": "Morgans Point, TX",
            "water_body": "Galveston Bay",
            "distance_km": 32.0,
            "bearing_degrees": 105.0,
            "sensor_support": ("wind", "air_temperature", "water_temperature", "pressure", "humidity"),
            "required_sensors": ("wind", "air_temperature", "water_temperature"),
            "onshore_direction_min": 90.0,
            "onshore_direction_max": 190.0,
            "adoption_rationale": "Galveston Bay/Gulf onshore flow can slow KHOU afternoon heating.",
        },
    ],
    "los-angeles": [
        {
            "provider": "coops",
            "station_id": "9410660",
            "station_name": "Los Angeles, CA",
            "water_body": "Pacific Ocean",
            "distance_km": 28.0,
            "bearing_degrees": 170.0,
            "sensor_support": ("wind", "air_temperature", "water_temperature", "pressure", "humidity"),
            "required_sensors": ("wind", "air_temperature", "water_temperature"),
            "onshore_direction_min": 220.0,
            "onshore_direction_max": 320.0,
            "adoption_rationale": "Pacific sea breeze and marine layer are core KLAX high-temperature risks.",
        },
    ],
    "san-francisco": [
        {
            "provider": "coops",
            "station_id": "9414290",
            "station_name": "San Francisco, CA",
            "water_body": "San Francisco Bay",
            "distance_km": 20.0,
            "bearing_degrees": 350.0,
            "sensor_support": ("wind", "air_temperature", "water_temperature", "pressure", "humidity"),
            "required_sensors": ("wind", "air_temperature", "water_temperature"),
            "onshore_direction_min": 220.0,
            "onshore_direction_max": 320.0,
            "adoption_rationale": "Bay/Pacific marine layer and west flow dominate KSFO warm-season busts.",
        },
    ],
    "seattle": [
        {
            "provider": "coops",
            "station_id": "9447130",
            "station_name": "Seattle, WA",
            "water_body": "Puget Sound",
            "distance_km": 17.0,
            "bearing_degrees": 350.0,
            "sensor_support": ("wind", "air_temperature", "water_temperature", "pressure", "humidity"),
            "required_sensors": ("wind", "air_temperature", "water_temperature"),
            "onshore_direction_min": 180.0,
            "onshore_direction_max": 310.0,
            "adoption_rationale": "Puget Sound marine air and reversal timing can suppress KSEA highs.",
        },
    ],
    "chicago": [
        {
            "provider": "coops",
            "station_id": "9087044",
            "station_name": "Calumet Harbor, IL",
            "water_body": "Lake Michigan",
            "distance_km": 34.0,
            "bearing_degrees": 115.0,
            "sensor_support": ("wind", "air_temperature", "water_temperature", "pressure"),
            "required_sensors": ("wind", "water_temperature"),
            "onshore_direction_min": 30.0,
            "onshore_direction_max": 140.0,
            "adoption_rationale": "Lake Michigan easterlies can sharply cap ORD afternoon highs.",
        },
        {
            "provider": "ndbc",
            "station_id": "CHII2",
            "station_name": "Chicago, IL C-MAN",
            "water_body": "Lake Michigan",
            "distance_km": 25.0,
            "bearing_degrees": 105.0,
            "sensor_support": ("wind", "air_temperature", "water_temperature", "pressure"),
            "required_sensors": ("wind", "water_temperature"),
            "onshore_direction_min": 30.0,
            "onshore_direction_max": 140.0,
            "adoption_rationale": "Nearshore wind and lake temperature for ORD lake-breeze diagnostics.",
        },
    ],
}


def payload_hash(payload) -> str:
    return hashlib.sha1(str(payload or "").encode("utf-8")).hexdigest()


def parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def parse_iso_time(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def ms_to_kmh(value):
    value = to_float(value)
    return None if value is None else round(value * 3.6, 2)


def registry_for_market(market_id):
    return [dict(row) for row in MARINE_CONTEXT_REGISTRY.get(str(market_id or ""), ())]


def build_coops_params(station_id, product, target_date, units="metric"):
    day = parse_date(target_date).strftime("%Y%m%d")
    return {
        "product": product,
        "application": "weather-market-research",
        "begin_date": day,
        "end_date": day,
        "station": str(station_id),
        "time_zone": "lst_ldt",
        "units": units,
        "format": "json",
    }


def build_ndbc_historical_url(station_id, target_date):
    day = parse_date(target_date)
    return NDBC_HISTORICAL_URL.format(station=str(station_id).lower(), year=day.year)


def parse_coops_local_time(value, spec):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=spec.tz)
        except ValueError:
            continue
    parsed = parse_iso_time(value)
    return parsed.astimezone(spec.tz) if parsed else None


def normalize_coops_product(product, payload, spec, station, target_date):
    rows = []
    target_iso = parse_date(target_date).isoformat()
    for raw in (payload or {}).get("data") or []:
        local_dt = parse_coops_local_time(raw.get("t"), spec)
        if local_dt is None or local_dt.date().isoformat() != target_iso:
            continue
        row = {
            "schema_version": MARINE_CONTEXT_SCHEMA_VERSION,
            "source": SOURCE,
            "provider": "coops",
            "station_id": station["station_id"],
            "station_name": station.get("station_name"),
            "market": spec.id,
            "time": local_dt.strftime("%H:%M"),
            "valid_time_local": local_dt.isoformat(),
            "valid_time_utc": local_dt.astimezone(timezone.utc).isoformat(),
            "local_date": target_iso,
            "minute_of_day": local_dt.hour * 60 + local_dt.minute,
            "source_url": COOPS_DATAGETTER_URL,
            "raw": dict(raw),
        }
        if product == "wind":
            row["wind_speed_kmh"] = ms_to_kmh(raw.get("s"))
            row["wind_gust_kmh"] = ms_to_kmh(raw.get("g"))
            row["wind_direction_degrees"] = to_float(raw.get("d"))
            row["wind_direction_cardinal"] = raw.get("dr")
        elif product == "air_temperature":
            value = to_float(raw.get("v"))
            row["air_temp_c"] = value
            row["air_temp_native"] = c_to_native(value, spec.display_unit)
        elif product == "water_temperature":
            value = to_float(raw.get("v"))
            row["water_temp_c"] = value
            row["water_temp_native"] = c_to_native(value, spec.display_unit)
        elif product == "air_pressure":
            row["pressure_hpa"] = to_float(raw.get("v"))
        elif product == "humidity":
            row["humidity"] = to_float(raw.get("v"))
        rows.append(row)
    return rows


def _row_key(row):
    return row.get("valid_time_utc") or row.get("valid_time_local") or row.get("time")


def merge_rows_by_time(rows):
    merged = {}
    for row in rows or []:
        key = _row_key(row)
        if not key:
            continue
        target = merged.setdefault(key, {})
        target.update(row)
    return sorted(merged.values(), key=lambda row: row.get("valid_time_utc") or "")


def ndbc_number(value, kind):
    number = to_float(value)
    if number is None:
        return None
    if kind == "direction" and number >= 990:
        return None
    if kind == "wind" and number >= 90:
        return None
    if kind == "pressure" and number >= 9000:
        return None
    if kind == "temperature" and number >= 90:
        return None
    return number


def parse_ndbc_realtime_text(text, spec, station, target_date, source_url=None):
    header = None
    rows = []
    target_iso = parse_date(target_date).isoformat()
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            tokens = line.lstrip("#").split()
            if len(tokens) >= 5 and tokens[0] in {"YY", "YYYY"}:
                header = tokens
            continue
        if not header:
            continue
        values = line.split()
        if len(values) < len(header):
            continue
        raw = dict(zip(header, values))
        year = int(raw.get("YY") or raw.get("YYYY"))
        if year < 100:
            year += 2000
        try:
            utc_dt = datetime(
                year,
                int(raw["MM"]),
                int(raw["DD"]),
                int(raw["hh"]),
                int(raw["mm"]),
                tzinfo=timezone.utc,
            )
        except (KeyError, ValueError):
            continue
        local_dt = utc_dt.astimezone(spec.tz)
        if local_dt.date().isoformat() != target_iso:
            continue
        air_c = ndbc_number(raw.get("ATMP"), "temperature")
        water_c = ndbc_number(raw.get("WTMP"), "temperature")
        dewpoint_c = ndbc_number(raw.get("DEWP"), "temperature")
        row = {
            "schema_version": MARINE_CONTEXT_SCHEMA_VERSION,
            "source": SOURCE,
            "provider": "ndbc",
            "station_id": station["station_id"],
            "station_name": station.get("station_name"),
            "market": spec.id,
            "time": local_dt.strftime("%H:%M"),
            "valid_time_local": local_dt.isoformat(),
            "valid_time_utc": utc_dt.isoformat(),
            "local_date": target_iso,
            "minute_of_day": local_dt.hour * 60 + local_dt.minute,
            "wind_direction_degrees": ndbc_number(raw.get("WDIR"), "direction"),
            "wind_speed_kmh": ms_to_kmh(ndbc_number(raw.get("WSPD"), "wind")),
            "wind_gust_kmh": ms_to_kmh(ndbc_number(raw.get("GST"), "wind")),
            "pressure_hpa": ndbc_number(raw.get("PRES"), "pressure"),
            "air_temp_c": air_c,
            "air_temp_native": c_to_native(air_c, spec.display_unit),
            "water_temp_c": water_c,
            "water_temp_native": c_to_native(water_c, spec.display_unit),
            "dewpoint_c": dewpoint_c,
            "dewpoint_native": c_to_native(dewpoint_c, spec.display_unit),
            "source_url": source_url or NDBC_REALTIME_URL.format(station=station["station_id"]),
            "raw": raw,
        }
        rows.append(row)
    return sorted(rows, key=lambda row: row["valid_time_utc"])


def sensor_present(row, sensor):
    if not row:
        return False
    if sensor == "wind":
        return (
            row.get("wind_speed_kmh") is not None
            and row.get("wind_direction_degrees") is not None
        )
    if sensor == "air_temperature":
        return row.get("air_temp_native") is not None
    if sensor == "water_temperature":
        return row.get("water_temp_native") is not None
    if sensor == "pressure":
        return row.get("pressure_hpa") is not None
    if sensor == "humidity":
        return row.get("humidity") is not None
    return row.get(sensor) is not None


def latest_row(rows):
    timed = []
    for row in rows or []:
        parsed = parse_iso_time(row.get("valid_time_utc"))
        if parsed is not None:
            timed.append((parsed.astimezone(timezone.utc), row))
    if not timed:
        return None
    return max(timed, key=lambda item: item[0])[1]


def row_age_minutes(row, now=None):
    parsed = parse_iso_time((row or {}).get("valid_time_utc"))
    if parsed is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (now.astimezone(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 60.0)


def station_result(station, rows, now=None, max_stale_minutes=DEFAULT_MAX_STALE_MINUTES, errors=None):
    latest = latest_row(rows)
    age = row_age_minutes(latest, now=now)
    stale = age is None or age > max_stale_minutes
    missing = [
        sensor for sensor in station.get("required_sensors") or ()
        if not sensor_present(latest, sensor)
    ]
    result = {
        "schema_version": MARINE_CONTEXT_SCHEMA_VERSION,
        "provider": station.get("provider"),
        "station_id": station.get("station_id"),
        "station_name": station.get("station_name"),
        "water_body": station.get("water_body"),
        "distance_km": station.get("distance_km"),
        "bearing_degrees": station.get("bearing_degrees"),
        "sensor_support": list(station.get("sensor_support") or ()),
        "required_sensors": list(station.get("required_sensors") or ()),
        "missing_sensors": missing,
        "latest_age_minutes": round(age, 1) if age is not None else None,
        "stale": stale,
        "usable": bool(latest) and not stale and not missing,
        "latest": latest,
        "rows": rows or [],
        "row_count": len(rows or []),
        "onshore_direction_min": station.get("onshore_direction_min"),
        "onshore_direction_max": station.get("onshore_direction_max"),
        "adoption_rationale": station.get("adoption_rationale"),
        "errors": errors or [],
    }
    if not latest:
        result["reason"] = "no target-date marine rows"
    elif stale:
        result["reason"] = "latest marine row is stale"
    elif missing:
        result["reason"] = "missing required sensors: " + ", ".join(missing)
    else:
        result["reason"] = ""
    return result


def default_get_text(url, timeout=10):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_marine_context_for_market(
    spec,
    target_date,
    get_json,
    get_text=None,
    now=None,
    max_stale_minutes=DEFAULT_MAX_STALE_MINUTES,
    timeout=10,
):
    stations = registry_for_market(spec.id)
    if not stations:
        return {
            "schema_version": MARINE_CONTEXT_SCHEMA_VERSION,
            "source": SOURCE,
            "market": spec.id,
            "target_date": parse_date(target_date).isoformat(),
            "available": False,
            "reason": "no marine-context stations configured for market",
            "stations": [],
            "rows": [],
        }
    if get_text is None:
        get_text = lambda url: default_get_text(url, timeout=timeout)

    station_results = []
    all_rows = []
    for station in stations:
        errors = []
        rows = []
        provider = station.get("provider")
        if provider == "coops":
            product_map = {
                "wind": "wind",
                "air_temperature": "air_temperature",
                "water_temperature": "water_temperature",
                "pressure": "air_pressure",
                "humidity": "humidity",
            }
            for sensor in station.get("sensor_support") or ():
                product = product_map.get(sensor)
                if not product:
                    continue
                params = build_coops_params(station["station_id"], product, target_date)
                try:
                    payload = get_json(COOPS_DATAGETTER_URL, params)
                    rows.extend(normalize_coops_product(product, payload, spec, station, target_date))
                except Exception as exc:  # noqa: BLE001 - per-station diagnostics
                    errors.append({"product": product, "error": str(exc)})
            rows = merge_rows_by_time(rows)
        elif provider == "ndbc":
            url = NDBC_REALTIME_URL.format(station=station["station_id"])
            try:
                text = get_text(url)
                rows = parse_ndbc_realtime_text(text, spec, station, target_date, source_url=url)
            except Exception as exc:  # noqa: BLE001 - per-station diagnostics
                errors.append({"url": url, "error": str(exc)})
        else:
            errors.append({"provider": provider, "error": "unsupported marine provider"})
        all_rows.extend(rows)
        station_results.append(station_result(
            station,
            rows,
            now=now,
            max_stale_minutes=max_stale_minutes,
            errors=errors,
        ))

    usable = [row for row in station_results if row.get("usable")]
    all_rows = sorted(all_rows, key=lambda row: row.get("valid_time_utc") or "")
    return {
        "schema_version": MARINE_CONTEXT_SCHEMA_VERSION,
        "source": SOURCE,
        "market": spec.id,
        "target_date": parse_date(target_date).isoformat(),
        "available": bool(usable),
        "reason": "" if usable else "no fresh marine station with required sensors",
        "stations": station_results,
        "rows": all_rows,
        "row_count": len(all_rows),
        "usable_station_count": len(usable),
        "payload_hash": payload_hash([
            {
                "station_id": item.get("station_id"),
                "row_count": item.get("row_count"),
                "latest": item.get("latest"),
                "errors": item.get("errors"),
            }
            for item in station_results
        ]),
    }


def historical_station_result(station, rows, target_date, errors=None):
    rows = list(rows or [])
    missing = [
        sensor for sensor in station.get("required_sensors") or ()
        if not any(sensor_present(row, sensor) for row in rows)
    ]
    latest = latest_row(rows)
    return {
        "schema_version": MARINE_STATION_HISTORY_SCHEMA_VERSION,
        "provider": station.get("provider"),
        "station_id": station.get("station_id"),
        "station_name": station.get("station_name"),
        "water_body": station.get("water_body"),
        "distance_km": station.get("distance_km"),
        "bearing_degrees": station.get("bearing_degrees"),
        "sensor_support": list(station.get("sensor_support") or ()),
        "required_sensors": list(station.get("required_sensors") or ()),
        "missing_sensors": missing,
        "usable": bool(rows) and not missing,
        "latest": latest,
        "rows": rows,
        "row_count": len(rows),
        "local_date": parse_date(target_date).isoformat(),
        "onshore_direction_min": station.get("onshore_direction_min"),
        "onshore_direction_max": station.get("onshore_direction_max"),
        "adoption_rationale": station.get("adoption_rationale"),
        "errors": errors or [],
        "reason": "" if rows and not missing else (
            "missing required historical sensors: " + ", ".join(missing)
            if rows else "no target-date historical marine rows"
        ),
    }


def default_get_ndbc_history_text(url, timeout=20):
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return gzip.decompress(response.content).decode("utf-8", errors="replace")


def fetch_marine_station_history_for_market(
    spec,
    target_date,
    get_json=None,
    get_text=None,
    timeout=20,
):
    stations = registry_for_market(spec.id)
    target_iso = parse_date(target_date).isoformat()
    if not stations:
        return {
            "schema_version": MARINE_STATION_HISTORY_SCHEMA_VERSION,
            "source": HISTORY_SOURCE,
            "market": spec.id,
            "target_date": target_iso,
            "available": False,
            "reason": "no marine-context stations configured for market",
            "stations": [],
            "rows": [],
        }
    get_json = get_json or _default_get_json
    get_text = get_text or (lambda url: default_get_ndbc_history_text(url, timeout=timeout))
    station_results = []
    all_rows = []
    raw_payloads = []
    for station in stations:
        errors = []
        rows = []
        provider = station.get("provider")
        if provider == "coops":
            product_map = {
                "wind": "wind",
                "air_temperature": "air_temperature",
                "water_temperature": "water_temperature",
                "pressure": "air_pressure",
                "humidity": "humidity",
            }
            for sensor in station.get("sensor_support") or ():
                product = product_map.get(sensor)
                if not product:
                    continue
                params = build_coops_params(station["station_id"], product, target_date)
                try:
                    payload = get_json(COOPS_DATAGETTER_URL, params)
                    raw_payloads.append({
                        "provider": "coops",
                        "station_id": station["station_id"],
                        "product": product,
                        "params": params,
                        "payload": payload,
                    })
                    rows.extend(normalize_coops_product(product, payload, spec, station, target_date))
                except Exception as exc:  # noqa: BLE001 - source row diagnostics
                    errors.append({"product": product, "error": str(exc)})
            rows = merge_rows_by_time(rows)
        elif provider == "ndbc":
            url = build_ndbc_historical_url(station["station_id"], target_date)
            try:
                text = get_text(url)
                raw_payloads.append({
                    "provider": "ndbc",
                    "station_id": station["station_id"],
                    "url": url,
                    "text": text,
                })
                rows = parse_ndbc_realtime_text(text, spec, station, target_date, source_url=url)
            except Exception as exc:  # noqa: BLE001 - source row diagnostics
                errors.append({"url": url, "error": str(exc)})
        else:
            errors.append({"provider": provider, "error": "unsupported marine provider"})
        all_rows.extend(rows)
        station_results.append(historical_station_result(station, rows, target_date, errors=errors))
    usable = [row for row in station_results if row.get("usable")]
    raw_payload = {
        "schema_version": MARINE_STATION_HISTORY_SCHEMA_VERSION,
        "source": HISTORY_SOURCE,
        "market": spec.id,
        "target_date": target_iso,
        "payloads": raw_payloads,
    }
    return {
        "schema_version": MARINE_STATION_HISTORY_SCHEMA_VERSION,
        "source": HISTORY_SOURCE,
        "market": spec.id,
        "target_date": target_iso,
        "available": bool(usable),
        "reason": "" if usable else "no historical marine station with required sensors",
        "stations": station_results,
        "rows": sorted(all_rows, key=lambda row: row.get("valid_time_utc") or ""),
        "row_count": len(all_rows),
        "usable_station_count": len(usable),
        "provenance": {
            "registry_source": "MARINE_CONTEXT_REGISTRY",
            "providers": sorted({station.get("provider") for station in stations if station.get("provider")}),
            "history_basis": "CO-OPS datagetter daily products and NDBC historical stdmet text",
        },
        "payload_hash": payload_hash(raw_payload),
        "raw_payload": raw_payload,
    }


def _default_get_json(url, params):
    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def direction_in_sector(direction, start, end):
    direction = to_float(direction)
    start = to_float(start)
    end = to_float(end)
    if direction is None or start is None or end is None:
        return None
    direction %= 360.0
    start %= 360.0
    end %= 360.0
    if start <= end:
        return start <= direction <= end
    return direction >= start or direction <= end


def offshore_for_sector(direction, start, end):
    start = None if start is None else (float(start) + 180.0) % 360.0
    end = None if end is None else (float(end) + 180.0) % 360.0
    return direction_in_sector(direction, start, end)


def empty_marine_context_features():
    return {column: None for column in MARINE_CONTEXT_FEATURE_COLUMNS}


def _best_station_result(results):
    candidates = [
        row for row in results or []
        if row.get("usable") and row.get("latest")
    ]
    if not candidates:
        return None

    def score(result):
        latest = result.get("latest") or {}
        sensor_count = sum(
            1 for key in (
                "water_temp_native",
                "air_temp_native",
                "wind_speed_kmh",
                "wind_direction_degrees",
                "pressure_hpa",
                "humidity",
            )
            if latest.get(key) is not None
        )
        age = result.get("latest_age_minutes")
        distance = result.get("distance_km")
        return (-sensor_count, age if age is not None else 10_000.0, distance if distance is not None else 10_000.0)

    return sorted(candidates, key=score)[0]


def _has_reversal(rows, start, end, cutoff_minute, wall_minute):
    if cutoff_minute is None:
        return None
    before = []
    after = []
    for row in rows or []:
        minute = row.get("minute_of_day")
        direction = row.get("wind_direction_degrees")
        if minute is None or direction is None:
            continue
        minute = int(minute)
        if minute <= cutoff_minute:
            before.append(direction)
        elif wall_minute is None or minute <= wall_minute:
            after.append(direction)
    if not before or not after:
        return None
    had_offshore = any(offshore_for_sector(direction, start, end) for direction in before)
    has_onshore = any(direction_in_sector(direction, start, end) for direction in after)
    return 1.0 if had_offshore and has_onshore else 0.0


def derive_marine_context_features(
    marine_context,
    current_temp_native=None,
    forecast_high_native=None,
    cutoff_hour=None,
    wall_minute=None,
):
    features = empty_marine_context_features()
    results = (marine_context or {}).get("stations") or []
    if not results:
        return features
    usable = [row for row in results if row.get("usable")]
    features["marine_station_count"] = float(len(usable))
    features["marine_missing_sensor_count"] = float(sum(
        len(row.get("missing_sensors") or []) for row in results
    ))
    ages = [
        row.get("latest_age_minutes") for row in usable
        if row.get("latest_age_minutes") is not None
    ]
    if ages:
        features["marine_latest_age_minutes"] = min(ages)

    best = _best_station_result(results)
    if not best:
        return features

    row = best.get("latest") or {}
    water = row.get("water_temp_native")
    air = row.get("air_temp_native")
    wind_speed = row.get("wind_speed_kmh")
    direction = row.get("wind_direction_degrees")
    start = best.get("onshore_direction_min")
    end = best.get("onshore_direction_max")
    features["marine_water_temp_native"] = water
    features["marine_air_temp_native"] = air
    features["marine_wind_speed_kmh"] = wind_speed
    features["marine_wind_direction_degrees"] = direction
    if water is not None and air is not None:
        features["marine_water_minus_air_temp"] = water - air
    forecast_high = to_float(forecast_high_native)
    if water is not None and forecast_high is not None:
        features["marine_water_minus_forecast_high"] = water - forecast_high
    if air is not None and current_temp_native is not None:
        features["marine_air_minus_current_temp"] = air - current_temp_native
    onshore = direction_in_sector(direction, start, end)
    offshore = offshore_for_sector(direction, start, end)
    if onshore is not None:
        features["marine_onshore_flow"] = 1.0 if onshore else 0.0
    if onshore is not None and features["marine_water_minus_forecast_high"] is not None:
        contrast = features["marine_water_minus_forecast_high"]
        features["marine_onshore_water_minus_forecast_high"] = contrast if onshore else 0.0
        features["marine_onshore_cooling_potential"] = max(0.0, -contrast) if onshore else 0.0
    if offshore is not None:
        features["marine_offshore_flow"] = 1.0 if offshore else 0.0
    cutoff_minute = int(cutoff_hour) * 60 if cutoff_hour is not None else None
    features["marine_post_cutoff_onshore_reversal"] = _has_reversal(
        best.get("rows") or [],
        start,
        end,
        cutoff_minute,
        int(wall_minute) if wall_minute is not None else None,
    )

    cooler_marine_air = (
        features["marine_air_minus_current_temp"] is not None
        and features["marine_air_minus_current_temp"] <= -1.0
    )
    cooler_water = (
        features["marine_water_minus_air_temp"] is not None
        and features["marine_water_minus_air_temp"] <= -1.0
    )
    if features["marine_onshore_flow"] is not None and wind_speed is not None:
        features["marine_breeze_risk"] = (
            1.0 if features["marine_onshore_flow"] and wind_speed >= 8.0 and (cooler_marine_air or cooler_water)
            else 0.0
        )
    humidity = row.get("humidity")
    if features["marine_onshore_flow"] is not None:
        strong_cool_air = (
            features["marine_air_minus_current_temp"] is not None
            and features["marine_air_minus_current_temp"] <= -2.0
        )
        humid_cool_water = (
            humidity is not None and humidity >= 75.0
            and features["marine_water_minus_air_temp"] is not None
            and features["marine_water_minus_air_temp"] <= 0.0
        )
        features["marine_layer_suppression"] = (
            1.0 if features["marine_onshore_flow"] and (strong_cool_air or humid_cool_water)
            else 0.0
        )
    return features


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def marine_context_regime(features):
    features = features or {}
    if to_float(features.get("marine_layer_suppression")) == 1.0:
        return "marine_layer_suppression"
    if to_float(features.get("marine_breeze_risk")) == 1.0:
        return "breeze_risk"
    if to_float(features.get("marine_onshore_flow")) == 1.0:
        return "onshore_flow"
    if to_float(features.get("marine_offshore_flow")) == 1.0:
        return "offshore_flow"
    if to_float(features.get("marine_station_count")):
        return "marine_neutral"
    return "no_usable_marine_context"


def active_marine_context_state(
    marine_context,
    current_temp_native=None,
    forecast_high_native=None,
    cutoff_hour=None,
    wall_minute=None,
):
    features = derive_marine_context_features(
        marine_context or {},
        current_temp_native=current_temp_native,
        forecast_high_native=forecast_high_native,
        cutoff_hour=cutoff_hour,
        wall_minute=wall_minute,
    )
    station_count = to_float(features.get("marine_station_count")) or 0.0
    if station_count <= 0:
        return None
    usable_stations = [
        row for row in (marine_context or {}).get("stations") or []
        if row.get("usable") and row.get("latest")
    ]
    station_ids = [row.get("station_id") for row in usable_stations if row.get("station_id")]
    return {
        "schema_version": MARINE_CONTEXT_SCHEMA_VERSION,
        "source": SOURCE,
        "active": True,
        "market": (marine_context or {}).get("market"),
        "regime": marine_context_regime(features),
        "station_count": station_count,
        "station_ids": station_ids,
        "latest_age_minutes": features.get("marine_latest_age_minutes"),
        "missing_sensor_count": features.get("marine_missing_sensor_count"),
        "water_temp_native": features.get("marine_water_temp_native"),
        "air_temp_native": features.get("marine_air_temp_native"),
        "water_minus_air_temp": features.get("marine_water_minus_air_temp"),
        "water_minus_forecast_high": features.get("marine_water_minus_forecast_high"),
        "air_minus_current_temp": features.get("marine_air_minus_current_temp"),
        "onshore_water_minus_forecast_high": features.get("marine_onshore_water_minus_forecast_high"),
        "onshore_cooling_potential": features.get("marine_onshore_cooling_potential"),
        "wind_speed_kmh": features.get("marine_wind_speed_kmh"),
        "wind_direction_degrees": features.get("marine_wind_direction_degrees"),
        "onshore_flow": features.get("marine_onshore_flow"),
        "breeze_risk": features.get("marine_breeze_risk"),
        "marine_layer_suppression": features.get("marine_layer_suppression"),
    }


def _features_from_record(row):
    nested = row.get("features") if isinstance(row, dict) else None
    if isinstance(nested, dict):
        merged = dict(row)
        merged.update(nested)
        return merged
    return row or {}


def _boolish(value):
    if isinstance(value, bool):
        return value
    number = to_float(value)
    if number is not None:
        return number != 0.0
    return str(value or "").strip().lower() in {"true", "yes", "y"}


def marine_context_backtest(rows):
    grouped = {}
    for row in rows or []:
        features = _features_from_record(row)
        market = row.get("market") or row.get("market_id") or features.get("market") or "unknown"
        regime = row.get("marine_regime") or marine_context_regime(features)
        key = (market, regime)
        group = grouped.setdefault(key, {
            "market": market,
            "regime": regime,
            "rows": 0,
            "settlement_errors": [],
            "forecast_errors": [],
            "forecast_overcalls": [],
            "high_has_stood_reversals": [],
        })
        raw_settlement_error = row.get("settlement_error")
        if raw_settlement_error is None or raw_settlement_error == "":
            raw_settlement_error = row.get("wu_settlement_error")
        raw_forecast_error = row.get("forecast_error")
        if raw_forecast_error is None or raw_forecast_error == "":
            raw_forecast_error = row.get("forecast_minus_settlement")
        settlement_error = to_float(raw_settlement_error)
        forecast_error = to_float(raw_forecast_error)
        reversal = row.get("high_has_stood_reversal")
        group["rows"] += 1
        group["settlement_errors"].append(settlement_error)
        group["forecast_errors"].append(forecast_error)
        group["forecast_overcalls"].append(1.0 if forecast_error is not None and forecast_error > 0 else 0.0)
        group["high_has_stood_reversals"].append(1.0 if _boolish(reversal) else 0.0)

    regimes = []
    for group in grouped.values():
        settlement_errors = [value for value in group["settlement_errors"] if value is not None]
        forecast_errors = [value for value in group["forecast_errors"] if value is not None]
        regimes.append({
            "market": group["market"],
            "regime": group["regime"],
            "rows": group["rows"],
            "mean_settlement_error": mean(settlement_errors),
            "settlement_miss_rate": mean(1.0 if abs(value) >= 1.0 else 0.0 for value in settlement_errors),
            "mean_forecast_error": mean(forecast_errors),
            "forecast_overcall_rate": mean(group["forecast_overcalls"]),
            "high_has_stood_reversal_rate": mean(group["high_has_stood_reversals"]),
        })
    regimes.sort(key=lambda row: (row["market"], row["regime"]))
    return {
        "schema_version": MARINE_CONTEXT_SCHEMA_VERSION,
        "source": SOURCE,
        "summary": {
            "rows": sum(row["rows"] for row in regimes),
            "markets": len({row["market"] for row in regimes}),
            "regimes": len(regimes),
            "breeze_or_layer_rows": sum(
                row["rows"] for row in regimes
                if row["regime"] in {"breeze_risk", "marine_layer_suppression"}
            ),
        },
        "regimes": regimes,
    }


def render_marine_context_backtest_markdown(payload):
    def fmt(value):
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    lines = [
        "# Marine Context Backtest",
        "",
        f"Rows: `{(payload.get('summary') or {}).get('rows', 0)}`",
        "",
        "| Market | Regime | Rows | Settlement Miss Rate | Forecast Overcall Rate | High-Has-Stood Reversal Rate |",
        "| :--- | :--- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("regimes") or []:
        lines.append(
            "| "
            + " | ".join([
                str(row.get("market")),
                str(row.get("regime")),
                str(row.get("rows")),
                fmt(row.get("settlement_miss_rate")),
                fmt(row.get("forecast_overcall_rate")),
                fmt(row.get("high_has_stood_reversal_rate")),
            ])
            + " |"
        )
    return "\n".join(lines) + "\n"
