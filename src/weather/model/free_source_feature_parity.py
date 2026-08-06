"""Dark, point-in-time surface-feature parity from captured free sources.

The deployed artifacts were trained from Weather Underground surface rows, but
live WU collection is intentionally disabled.  This module reconstructs only
the fields whose semantics survive on the existing free same-station feeds.
It never fetches data and it never treats a merely similar field as parity.
"""

from __future__ import annotations

import math
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from weather.model.feature_store import (
    closest_temperature_native,
    closest_value,
    closest_wind_direction,
    row_dewpoint_native,
    row_temp_native,
    row_wind_direction,
    wind_direction_delta_degrees,
)


FREE_SOURCE_FEATURE_PARITY_FLAG = "WEATHER_FREE_SOURCE_FEATURE_PARITY"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_CARDINALS = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)
_METAR_PRECIP_CODES = ("DZ", "RA", "SN", "SG", "IC", "PL", "GR", "GS", "UP", "SH", "TS")
_METAR_FOG_CODES = ("BR", "FG", "HZ")
_METAR_WEATHER_TOKEN = re.compile(
    r"^[+-]?(?:VC)?(?:MI|PR|BC|DR|BL|SH|TS|FZ)?"
    r"(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS){1,3}$"
)
_CLOUD_AMOUNT = {
    "30": "Clear",
    "31": "Few",
    "32": "Few",
    "33": "SCT",
    "34": "SCT",
    "35": "BKN",
    "36": "BKN",
    "37": "BKN",
    "38": "OVC",
}
_AFFECTED_FIELDS = (
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
    "wind_group",
    "cloud_group",
)


def free_source_feature_parity_enabled(value=None):
    """Return the explicit opt-in state; absence and unknown values are off."""

    if value is None:
        value = os.getenv(FREE_SOURCE_FEATURE_PARITY_FLAG, "")
    return str(value).strip().lower() in _TRUE_VALUES


def build_free_source_feature_overrides(model, sources, cutoff_hour, captured_at):
    """Build one-source, cutoff-safe overrides without network or disk access.

    Toronto prefers ECCC SWOB because it carries direct relative humidity and
    station pressure.  Other markets use METAR.  Toronto may fall back to its
    METAR, but a single returned record is never spliced across providers.
    """

    blank = _blank_overrides(model)
    if captured_at is None:
        return blank
    target_date = getattr(model, "target_date", None)
    if target_date is None:
        return blank
    target_date_text = (
        target_date.isoformat() if hasattr(target_date, "isoformat") else str(target_date)
    )
    source_order = (
        ("eccc_swob", "metar")
        if getattr(model, "market_id", None) == "toronto"
        else ("metar",)
    )
    for source_name in source_order:
        item = (sources or {}).get(source_name) or {}
        if not _eligible_source_item(item, captured_at):
            continue
        raw_payload = ((item.get("data") or {}).get("raw_payload"))
        if source_name == "eccc_swob":
            rows = _normalize_eccc_rows(
                raw_payload,
                model.spec,
                target_date_text,
                cutoff_hour,
                captured_at,
            )
        else:
            rows = _normalize_metar_rows(
                raw_payload,
                model.spec,
                target_date_text,
                cutoff_hour,
                captured_at,
            )
        if rows:
            return feature_overrides_from_rows(model, rows, cutoff_hour)
    return blank


def feature_overrides_from_rows(model, rows, cutoff_hour):
    """Apply the historical feature formulas to normalized free-source rows."""

    cutoff_minutes = int(cutoff_hour) * 60
    obs_before = sorted(
        (
            row
            for row in rows or []
            if row.get("minute_of_day") is not None
            and int(row["minute_of_day"]) <= cutoff_minutes
        ),
        key=lambda row: int(row["minute_of_day"]),
    )
    if not obs_before:
        return _blank_overrides(model)
    current_obs = obs_before[-1]
    current_temp = row_temp_native(current_obs)
    temperatures = [
        row_temp_native(row)
        for row in obs_before
        if row_temp_native(row) is not None
    ]
    high_so_far = max(temperatures) if temperatures else None
    temp_7am = closest_temperature_native(obs_before, 7 * 60, 60)
    temp_2h = closest_temperature_native(obs_before, cutoff_minutes - 120, 60)
    first_reached = next(
        (
            int(row["minute_of_day"])
            for row in obs_before
            if high_so_far is not None and row_temp_native(row) == high_so_far
        ),
        None,
    )
    pressure = _number(current_obs.get("pressure"))
    pressure_3h = closest_value(
        obs_before,
        cutoff_minutes - 180,
        60,
        "pressure",
    )
    wind_speed = _number(current_obs.get("wind_kmh"))
    wind_group = model.wind_group(current_obs.get("wind"))
    cloud_group = model.cloud_group(
        current_obs.get("condition"),
        current_obs.get("clouds"),
    )
    return {
        "rise_from_7am": (
            current_temp - temp_7am
            if current_temp is not None and temp_7am is not None
            else None
        ),
        "warming_rate_2h": (
            current_temp - temp_2h
            if current_temp is not None and temp_2h is not None
            else None
        ),
        "hours_at_peak": (
            (cutoff_minutes - first_reached) / 60.0
            if first_reached is not None
            else None
        ),
        "dewpoint_c": row_dewpoint_native(current_obs),
        "humidity": _number(current_obs.get("humidity")),
        "pressure": pressure,
        "pressure_trend_3h": (
            pressure - pressure_3h
            if pressure is not None and pressure_3h is not None
            else None
        ),
        "wind_speed_kmh": wind_speed,
        "wind_gust_kmh": _number(current_obs.get("gust_kmh")),
        "wind_shift_3h_degrees": wind_direction_delta_degrees(
            row_wind_direction(current_obs),
            closest_wind_direction(obs_before, cutoff_minutes - 180, 60),
        ),
        **model.microclimate_features(wind_group, wind_speed),
        "wind_group": wind_group,
        "cloud_group": cloud_group,
    }


def _blank_overrides(model):
    values = {field: None for field in _AFFECTED_FIELDS}
    values.update(model.microclimate_features(None, None))
    return values


def _eligible_source_item(item, captured_at):
    if not item.get("ok") or item.get("stale"):
        return False
    data = item.get("data") or {}
    if data.get("target_date_match") is False:
        return False
    captured = _as_datetime(captured_at)
    fetched = _as_datetime(item.get("fetched_at"))
    return captured is not None and fetched is not None and fetched <= captured


def _normalize_metar_rows(raw_payload, spec, target_date, cutoff_hour, captured_at):
    if not isinstance(raw_payload, list):
        return []
    captured = _as_datetime(captured_at)
    rows = []
    for raw in raw_payload:
        if not isinstance(raw, dict):
            continue
        if str(raw.get("icaoId") or "").upper() != str(spec.icao).upper():
            continue
        observed = _metar_observed_at(raw)
        received = _as_datetime(raw.get("receiptTime"))
        if observed is None or captured is None or observed > captured:
            continue
        if received is not None and received > captured:
            continue
        local = observed.astimezone(spec.tz)
        minute = local.hour * 60 + local.minute
        if local.date().isoformat() != target_date or minute > int(cutoff_hour) * 60:
            continue
        speed_knots = _number(raw.get("wspd"))
        gust_knots = _number(raw.get("wgst"))
        wind_degrees = _wind_degrees(raw.get("wdir"))
        wind = _wind_cardinal(raw.get("wdir"), speed_knots)
        cloud_text = _metar_cloud_text(raw)
        condition = _metar_condition(raw)
        rows.append(
            {
                "time": local.strftime("%H:%M"),
                "minute_of_day": minute,
                "temp_native": spec.c_to_native(_number(raw.get("temp"))),
                "dewpoint_native": spec.c_to_native(_number(raw.get("dewp"))),
                # AWC METAR does not report direct RH.  Do not derive it.
                "humidity": None,
                # Altimeter and sea-level pressure are not WU station pressure.
                "pressure": None,
                "wind": wind,
                "wind_degrees": wind_degrees,
                # The legacy feature name carries native WU wind units.
                "wind_kmh": _knots_to_artifact_units(speed_knots, spec.unit),
                "gust_kmh": _knots_to_artifact_units(gust_knots, spec.unit),
                "condition": condition,
                "clouds": cloud_text,
            }
        )
    return _dedupe_rows(rows)


def _normalize_eccc_rows(raw_payload, spec, target_date, cutoff_hour, captured_at):
    if not isinstance(raw_payload, dict):
        return []
    captured = _as_datetime(captured_at)
    rows = []
    for item in raw_payload.get("files") or []:
        xml_text = item.get("text") if isinstance(item, dict) else None
        if not xml_text:
            continue
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            continue
        values = {}
        for element in root.iter():
            name = element.attrib.get("name")
            if name and name not in values:
                values[name] = element.attrib.get("value")
        if str(values.get("icao_stn_id") or "").upper() != str(spec.icao).upper():
            continue
        observed = _as_datetime(values.get("date_tm"))
        if observed is None or captured is None or observed > captured:
            continue
        local = observed.astimezone(spec.tz)
        minute = local.hour * 60 + local.minute
        if local.date().isoformat() != target_date or minute > int(cutoff_hour) * 60:
            continue
        speed = _number(values.get("avg_wnd_spd_10m_pst2mts"))
        direction = _wind_degrees(values.get("avg_wnd_dir_10m_pst2mts"))
        rows.append(
            {
                "time": local.strftime("%H:%M"),
                "minute_of_day": minute,
                "temp_native": _number(values.get("air_temp")),
                "dewpoint_native": _number(values.get("dwpt_temp")),
                "humidity": _number(values.get("rel_hum")),
                # WU metric history uses station pressure; SWOB stn_pres is hPa.
                "pressure": _number(values.get("stn_pres")),
                "wind": _wind_cardinal(direction, speed),
                "wind_degrees": direction,
                "wind_kmh": speed,
                "gust_kmh": _number(values.get("max_wnd_gst_spd_10m_pst10mts")),
                "condition": _eccc_condition(values.get("prsnt_wx_1")),
                "clouds": _eccc_cloud_text(values),
            }
        )
    return _dedupe_rows(rows)


def _dedupe_rows(rows):
    by_minute = {}
    for row in rows:
        by_minute[int(row["minute_of_day"])] = row
    return [by_minute[key] for key in sorted(by_minute)]


def _number(value):
    if value in (None, "", "MSNG"):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _as_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _metar_observed_at(raw):
    epoch = _number(raw.get("obsTime"))
    if epoch is not None:
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            pass
    return _as_datetime(raw.get("reportTime"))


def _knots_to_artifact_units(value, unit):
    if value is None:
        return None
    factor = 1.1507794480235425 if str(unit).upper() == "F" else 1.852
    return value * factor


def _wind_degrees(value):
    number = _number(value)
    if number is None or number < 0.0 or number > 360.0:
        return None
    return number % 360.0


def _wind_cardinal(value, speed):
    text = str(value or "").strip().upper()
    if speed == 0.0:
        return "CALM"
    if text == "VRB":
        return "VRB"
    degrees = _wind_degrees(value)
    if degrees is None:
        return None
    return _CARDINALS[int((degrees + 11.25) // 22.5) % 16]


def _metar_cloud_text(raw):
    covers = []
    for layer in raw.get("clouds") or []:
        cover = str((layer or {}).get("cover") or "").upper()
        if cover in {"CLR", "SKC", "FEW", "SCT", "BKN", "OVC"}:
            covers.append("CLR" if cover == "SKC" else cover)
    aggregate = str(raw.get("cover") or "").upper()
    if aggregate in {"CLR", "SKC", "FEW", "SCT", "BKN", "OVC"}:
        covers.append("CLR" if aggregate == "SKC" else aggregate)
    return " ".join(dict.fromkeys(covers)) or None


def _metar_condition(raw):
    text = str(raw.get("wxString") or raw.get("rawOb") or "").upper()
    tokens = {
        token
        for token in re.findall(r"[A-Z+-]+", text)
        if _METAR_WEATHER_TOKEN.fullmatch(token)
    }
    if any(any(code in token for code in _METAR_PRECIP_CODES) for token in tokens):
        return "Rain"
    if any(any(code in token for code in _METAR_FOG_CODES) for token in tokens):
        return "Fog"
    return None


def _eccc_cloud_text(values):
    amounts = []
    for index in range(1, 5):
        code = str(values.get(f"cld_amt_code_{index}") or "")
        amount = _CLOUD_AMOUNT.get(code)
        if amount:
            amounts.append(amount)
    return " ".join(amounts) or None


def _eccc_condition(value):
    code = _number(value)
    if code is None:
        return None
    # Standard present-weather ranges only.  Canadian extension codes (such as
    # 125) remain absent until an authoritative one-to-one decoder is bound.
    if 40 <= code <= 49:
        return "Fog"
    if 50 <= code <= 99:
        return "Rain"
    return None
