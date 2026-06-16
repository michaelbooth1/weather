"""MRMS realized precipitation source and feature helpers."""
from __future__ import annotations

import gzip
import hashlib
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from weather.sources.grib_probe import extract_nearest_with_wgrib2, probe_grib_payload
from weather.sources.historical_schema import to_float


MRMS_PRECIP_SCHEMA_VERSION = "mrms_precip_v0.1"
SOURCE = "mrms_precip"
MRMS_S3_BASE_URL = "https://noaa-mrms-pds.s3.amazonaws.com/"
MRMS_DEFAULT_PRODUCT = "PrecipRate_00.00"
MRMS_PRODUCT_VERSION = "MRMS_CONUS_precip_rate_public_s3"
DEFAULT_RECENT_LOOKBACK_MINUTES = 20
DEFAULT_PRECIP_RATE_THRESHOLD_MM_HR = 0.1
MRMS_QPE_PRODUCTS = {"GaugeCorr_QPE_01H", "GaugeCorr_QPE_01H_00.00", "MultiSensor_QPE_01H"}
MRMS_ARCHIVE_UPGRADE_WARNING = (
    "MRMS public archive products can change across NOAA/MRMS upgrades; "
    "preserve product_version/object_key and validate pre/post-upgrade periods separately."
)


MRMS_PRECIP_FEATURE_COLUMNS = [
    "mrms_row_count",
    "mrms_source_lag_minutes",
    "mrms_any_precip_last_15m",
    "mrms_any_precip_last_30m",
    "mrms_any_precip_last_60m",
    "mrms_precip_since_7am_mm",
    "mrms_precip_since_cutoff_mm",
    "mrms_max_rate_peak_heating_mm_per_hr",
    "mrms_max_rate_since_cutoff_mm_per_hr",
    "mrms_convective_interruption",
]


MRMS_KEY_RE = re.compile(
    r"(?:^|/)MRMS_(?P<product>.+)_(?P<stamp>\d{8}-\d{6})\.grib2(?:\.gz)?$"
)


def payload_hash(payload) -> str:
    if isinstance(payload, bytes):
        data = payload
    else:
        data = str(payload or "").encode("utf-8")
    return hashlib.sha1(data).hexdigest()


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


def mrms_prefix(product=MRMS_DEFAULT_PRODUCT, target_date=None):
    day = parse_date(target_date or datetime.now(timezone.utc).date()).strftime("%Y%m%d")
    return f"CONUS/{product}/{day}/"


def build_mrms_object_key(product, valid_time):
    valid = parse_time(valid_time)
    if valid is None:
        raise ValueError("valid_time must be parseable")
    stamp = valid.strftime("%Y%m%d-%H%M%S")
    return f"{mrms_prefix(product, valid.date())}MRMS_{product}_{stamp}.grib2.gz"


def build_mrms_object_url(product, valid_time):
    return MRMS_S3_BASE_URL + build_mrms_object_key(product, valid_time)


def build_mrms_listing_url(product=MRMS_DEFAULT_PRODUCT, target_date=None):
    params = {
        "list-type": "2",
        "prefix": mrms_prefix(product, target_date),
    }
    return MRMS_S3_BASE_URL + "?" + urlencode(params)


def parse_mrms_key_time(key):
    match = MRMS_KEY_RE.search(str(key or ""))
    if not match:
        return None
    try:
        valid = datetime.strptime(match.group("stamp"), "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return {
        "product": match.group("product"),
        "valid_time_utc": valid.isoformat(),
        "object_key": key,
    }


def parse_s3_listing(xml_text):
    root = ET.fromstring(xml_text or "<ListBucketResult />")
    rows = []
    for contents in root.findall(".//{*}Contents"):
        key = contents.findtext("{*}Key")
        parsed = parse_mrms_key_time(key)
        if not parsed:
            continue
        last_modified = contents.findtext("{*}LastModified")
        size_text = contents.findtext("{*}Size")
        parsed.update({
            "last_modified": last_modified,
            "size_bytes": int(size_text) if str(size_text or "").isdigit() else None,
            "url": MRMS_S3_BASE_URL + key,
        })
        rows.append(parsed)
    return sorted(rows, key=lambda row: row["valid_time_utc"])


def select_recent_objects(objects, now=None, lookback_minutes=DEFAULT_RECENT_LOOKBACK_MINUTES):
    now = parse_time(now or datetime.now(timezone.utc))
    if now is None:
        return []
    floor = now - timedelta(minutes=float(lookback_minutes))
    selected = []
    for row in objects or []:
        valid = parse_time(row.get("valid_time_utc"))
        if valid is not None and floor <= valid <= now:
            selected.append(dict(row))
    return sorted(selected, key=lambda row: row["valid_time_utc"])


def latest_object_age_minutes(objects, now=None):
    now = parse_time(now or datetime.now(timezone.utc))
    valids = [
        parse_time(row.get("valid_time_utc")) for row in objects or []
        if parse_time(row.get("valid_time_utc")) is not None
    ]
    if not valids or now is None:
        return None
    latest = max(valids)
    return max(0.0, (now - latest).total_seconds() / 60.0)


def decompress_maybe_gzip(payload: bytes) -> bytes:
    if bytes(payload[:2]) == b"\x1f\x8b":
        return gzip.decompress(payload)
    return payload


def probe_mrms_grib_payload(payload, source_url, object_key=None, product=MRMS_DEFAULT_PRODUCT, fetched_at=None):
    raw = decompress_maybe_gzip(payload)
    parsed = parse_mrms_key_time(object_key)
    return probe_grib_payload(
        raw,
        source=SOURCE,
        model="MRMS",
        source_url=source_url,
        object_key=object_key,
        valid_time=(parsed or {}).get("valid_time_utc"),
        grid="CONUS",
        domain="CONUS",
        fetched_at=fetched_at,
    ) | {
        "schema_version": MRMS_PRECIP_SCHEMA_VERSION,
        "product": product,
        "product_version": MRMS_PRODUCT_VERSION,
        "compressed_payload_hash": payload_hash(payload),
        "compressed_payload_bytes": len(payload),
    }


def normalize_mrms_precip_row(
    spec,
    valid_time_utc,
    precip_rate_mm_per_hr=None,
    qpe_mm=None,
    product=MRMS_DEFAULT_PRODUCT,
    source_url=None,
    object_key=None,
    payload_hash_value=None,
):
    valid = parse_time(valid_time_utc)
    if valid is None:
        raise ValueError("valid_time_utc must be parseable")
    local = valid.astimezone(spec.tz)
    rate = to_float(precip_rate_mm_per_hr)
    qpe = to_float(qpe_mm)
    return {
        "schema_version": MRMS_PRECIP_SCHEMA_VERSION,
        "source": SOURCE,
        "market": spec.id,
        "station": spec.icao,
        "product": product,
        "product_version": MRMS_PRODUCT_VERSION,
        "valid_time_utc": valid.isoformat(),
        "valid_time_local": local.isoformat(),
        "local_date": local.date().isoformat(),
        "minute_of_day": local.hour * 60 + local.minute,
        "precip_rate_mm_per_hr": rate,
        "qpe_mm": qpe,
        "precip_detected": bool((rate is not None and rate >= DEFAULT_PRECIP_RATE_THRESHOLD_MM_HR) or (qpe is not None and qpe > 0.0)),
        "source_url": source_url,
        "object_key": object_key,
        "payload_hash": payload_hash_value,
    }


def mrms_wgrib_match(product=MRMS_DEFAULT_PRODUCT):
    product = str(product or MRMS_DEFAULT_PRODUCT)
    if product in MRMS_QPE_PRODUCTS or "QPE" in product.upper():
        return ":APCP:"
    return ":PrecipRate:"


def extract_mrms_nearest_precip_row(
    spec,
    grib_path,
    valid_time_utc,
    product=MRMS_DEFAULT_PRODUCT,
    source_url=None,
    object_key=None,
    wgrib2_path=None,
    runner=None,
    match=None,
):
    match = match or mrms_wgrib_match(product)
    extracted = extract_nearest_with_wgrib2(
        grib_path,
        lon=spec.lon,
        lat=spec.lat,
        match=match,
        wgrib2_path=wgrib2_path,
        runner=runner,
    )
    value = extracted.get("value")
    row = normalize_mrms_precip_row(
        spec,
        valid_time_utc,
        precip_rate_mm_per_hr=None if product in MRMS_QPE_PRODUCTS or "QPE" in str(product).upper() else value,
        qpe_mm=value if product in MRMS_QPE_PRODUCTS or "QPE" in str(product).upper() else None,
        product=product,
        source_url=source_url,
        object_key=object_key,
        payload_hash_value=payload_hash({"path": str(grib_path), "object_key": object_key, "match": match}),
    )
    row["extraction"] = {
        "method": "wgrib2_lon",
        "match": match,
        "lon": spec.lon,
        "lat": spec.lat,
        "raw": extracted.get("raw"),
    }
    return row


def fetch_mrms_precip_for_market(
    spec,
    target_date,
    get_text=None,
    now=None,
    product=MRMS_DEFAULT_PRODUCT,
    lookback_minutes=DEFAULT_RECENT_LOOKBACK_MINUTES,
):
    if ":US" not in str(getattr(spec, "wu_history_id", "")):
        return {
            "schema_version": MRMS_PRECIP_SCHEMA_VERSION,
            "source": SOURCE,
            "market": spec.id,
            "available": False,
            "reason": "MRMS CONUS live precipitation layer is US-only.",
            "rows": [],
            "objects": [],
        }
    get_text = get_text or _default_get_text
    listing_url = build_mrms_listing_url(product, target_date)
    objects = []
    try:
        objects = parse_s3_listing(get_text(listing_url))
    except Exception as exc:  # noqa: BLE001 - source status should report lag/failure
        return {
            "schema_version": MRMS_PRECIP_SCHEMA_VERSION,
            "source": SOURCE,
            "market": spec.id,
            "target_date": parse_date(target_date).isoformat(),
            "available": False,
            "reason": f"MRMS listing unavailable: {exc}",
            "listing_url": listing_url,
            "rows": [],
            "objects": [],
        }
    recent = select_recent_objects(objects, now=now, lookback_minutes=lookback_minutes)
    lag = latest_object_age_minutes(objects, now=now)
    return {
        "schema_version": MRMS_PRECIP_SCHEMA_VERSION,
        "source": SOURCE,
        "market": spec.id,
        "target_date": parse_date(target_date).isoformat(),
        "available": False,
        "reason": (
            "nearest MRMS extraction is not configured in this lightweight live fetcher"
            if recent else "no recent MRMS object; treat as source lag, not no-precip evidence"
        ),
        "listing_url": listing_url,
        "product": product,
        "product_version": MRMS_PRODUCT_VERSION,
        "objects": objects,
        "recent_objects": recent,
        "latest_object_age_minutes": round(lag, 1) if lag is not None else None,
        "rows": [],
        "row_count": 0,
    }


def _default_get_text(url):
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    return response.text


def empty_mrms_precip_features():
    return {column: None for column in MRMS_PRECIP_FEATURE_COLUMNS}


def _row_minute(row):
    minute = (row or {}).get("minute_of_day")
    if minute is not None:
        try:
            return int(minute)
        except (TypeError, ValueError):
            return None
    valid = parse_time((row or {}).get("valid_time_utc"))
    if valid is None:
        return None
    return valid.hour * 60 + valid.minute


def _row_precip_mm(row, default_interval_minutes=2.0):
    qpe = to_float((row or {}).get("qpe_mm"))
    if qpe is not None:
        return qpe
    rate = to_float((row or {}).get("precip_rate_mm_per_hr"))
    if rate is None:
        return None
    return rate * float(default_interval_minutes) / 60.0


def _row_rate(row):
    return to_float((row or {}).get("precip_rate_mm_per_hr"))


def _rows_between(rows, start_minute, end_minute):
    selected = []
    for row in rows or []:
        minute = _row_minute(row)
        if minute is None:
            continue
        if start_minute <= minute <= end_minute:
            selected.append(row)
    return selected


def _any_precip(rows, threshold=DEFAULT_PRECIP_RATE_THRESHOLD_MM_HR):
    for row in rows or []:
        if row.get("precip_detected") is True:
            return 1.0
        rate = _row_rate(row)
        qpe = to_float(row.get("qpe_mm"))
        if (rate is not None and rate >= threshold) or (qpe is not None and qpe > 0.0):
            return 1.0
    return 0.0


def _sum_precip(rows):
    values = [_row_precip_mm(row) for row in rows or []]
    values = [value for value in values if value is not None]
    return sum(values) if values else None


def _max_rate(rows):
    values = [_row_rate(row) for row in rows or []]
    values = [value for value in values if value is not None]
    return max(values) if values else None


def derive_mrms_precip_features(
    mrms_precip,
    cutoff_hour=None,
    wall_minute=None,
    forecast_next_3h_cape_max=None,
    forecast_next_3h_precip_probability_max=None,
    warming_rate_2h=None,
):
    features = empty_mrms_precip_features()
    data = mrms_precip or {}
    rows = list(data.get("rows") or [])
    features["mrms_row_count"] = float(len(rows))
    lag = data.get("latest_object_age_minutes")
    if lag is not None:
        features["mrms_source_lag_minutes"] = lag
    if not rows:
        return features

    if wall_minute is None:
        wall_minute = max((_row_minute(row) for row in rows if _row_minute(row) is not None), default=None)
    if wall_minute is None:
        return features
    wall_minute = int(wall_minute)
    cutoff_minute = int(cutoff_hour) * 60 if cutoff_hour is not None else wall_minute
    for window in (15, 30, 60):
        features[f"mrms_any_precip_last_{window}m"] = _any_precip(
            _rows_between(rows, wall_minute - window, wall_minute)
        )
    since_7am = _rows_between(rows, 7 * 60, wall_minute)
    since_cutoff = _rows_between(rows, cutoff_minute, wall_minute)
    peak_heating = _rows_between(rows, 11 * 60, min(17 * 60, wall_minute))
    features["mrms_precip_since_7am_mm"] = _sum_precip(since_7am)
    features["mrms_precip_since_cutoff_mm"] = _sum_precip(since_cutoff)
    features["mrms_max_rate_peak_heating_mm_per_hr"] = _max_rate(peak_heating)
    features["mrms_max_rate_since_cutoff_mm_per_hr"] = _max_rate(since_cutoff)

    realized = features["mrms_any_precip_last_60m"] == 1.0 or (
        features["mrms_precip_since_cutoff_mm"] is not None
        and features["mrms_precip_since_cutoff_mm"] > 0.0
    )
    cape_support = (
        forecast_next_3h_cape_max is not None
        and float(forecast_next_3h_cape_max) >= 500.0
    )
    pop_support = (
        forecast_next_3h_precip_probability_max is not None
        and float(forecast_next_3h_precip_probability_max) >= 40.0
    )
    stall_support = warming_rate_2h is not None and float(warming_rate_2h) <= 0.0
    features["mrms_convective_interruption"] = (
        1.0 if realized and (cape_support or pop_support or stall_support) else 0.0
    )
    return features


def _date_range(start_date, end_date):
    current = parse_date(start_date)
    end = parse_date(end_date)
    while current <= end:
        yield current
        current = current + timedelta(days=1)


def build_mrms_backfill_feature_rows(
    spec,
    rows_by_date,
    start_date,
    end_date,
    product=MRMS_DEFAULT_PRODUCT,
    cutoff_hour=12,
):
    output = []
    rows_by_date = rows_by_date or {}
    for local_date in _date_range(start_date, end_date):
        day_key = local_date.isoformat()
        rows = list(rows_by_date.get(day_key) or [])
        features = derive_mrms_precip_features(
            {"rows": rows},
            cutoff_hour=cutoff_hour,
            wall_minute=23 * 60 + 59,
        )
        output.append({
            "schema_version": MRMS_PRECIP_SCHEMA_VERSION,
            "source": SOURCE,
            "market": spec.id,
            "station": spec.icao,
            "local_date": day_key,
            "product": product,
            "product_version": MRMS_PRODUCT_VERSION,
            "archive_available": bool(rows),
            "row_count": len(rows),
            "object_keys": sorted({row.get("object_key") for row in rows if row.get("object_key")}),
            "archive_warning": MRMS_ARCHIVE_UPGRADE_WARNING,
            **features,
        })
    return output


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def _boolish(value):
    if isinstance(value, bool):
        return value
    number = to_float(value)
    if number is not None:
        return number != 0.0
    return str(value or "").strip().lower() in {"true", "yes", "y"}


def _case_types(row):
    cases = []
    raw_error = row.get("forecast_overcall_error")
    if raw_error is None or raw_error == "":
        raw_error = row.get("forecast_minus_settlement")
    if _boolish(row.get("forecast_overcall")) or (to_float(raw_error) or 0.0) > 0:
        cases.append("forecast_overcall")
    if _boolish(row.get("late_day_continuation_failed")):
        cases.append("late_day_continuation_failed")
    if _boolish(row.get("market_moved_after_storm")):
        cases.append("market_moved_after_storm")
    return cases or ["all_other"]


def score_mrms_interruption_cases(rows):
    grouped = {}
    input_rows = list(rows or [])
    interruption_input_rows = 0
    for row in input_rows:
        features = dict(row.get("features") or {})
        features.update({key: value for key, value in row.items() if str(key).startswith("mrms_")})
        interruption = to_float(features.get("mrms_convective_interruption"))
        if interruption == 1.0:
            interruption_input_rows += 1
        overcall_error = row.get("forecast_overcall_error")
        if overcall_error is None or overcall_error == "":
            overcall_error = row.get("forecast_minus_settlement")
        market_move = row.get("market_move_after_storm_bps")
        if market_move is None or market_move == "":
            market_move = row.get("market_move_bps")
        for case_type in _case_types(row):
            key = (row.get("market") or row.get("market_id") or "unknown", case_type)
            group = grouped.setdefault(key, {
                "market": key[0],
                "case_type": case_type,
                "rows": 0,
                "interruptions": [],
                "overcall_errors": [],
                "market_moves": [],
            })
            group["rows"] += 1
            group["interruptions"].append(1.0 if interruption == 1.0 else 0.0)
            group["overcall_errors"].append(to_float(overcall_error))
            group["market_moves"].append(to_float(market_move))
    cases = []
    for group in grouped.values():
        cases.append({
            "market": group["market"],
            "case_type": group["case_type"],
            "rows": group["rows"],
            "mrms_interruption_rate": mean(group["interruptions"]),
            "mean_forecast_overcall_error": mean(group["overcall_errors"]),
            "mean_market_move_after_storm_bps": mean(group["market_moves"]),
        })
    cases.sort(key=lambda row: (row["market"], row["case_type"]))
    return {
        "schema_version": MRMS_PRECIP_SCHEMA_VERSION,
        "source": SOURCE,
        "summary": {
            "rows": len(input_rows),
            "markets": len({row["market"] for row in cases}),
            "case_groups": len(cases),
            "interruption_rows": interruption_input_rows,
        },
        "cases": cases,
    }


def render_mrms_score_markdown(payload):
    def fmt(value):
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    lines = [
        "# MRMS Interruption Score Report",
        "",
        f"Rows: `{(payload.get('summary') or {}).get('rows', 0)}`",
        "",
        "| Market | Case | Rows | MRMS Interruption Rate | Mean Forecast Overcall Error | Mean Market Move bps |",
        "| :--- | :--- | ---: | ---: | ---: | ---: |",
    ]
    for row in payload.get("cases") or []:
        lines.append(
            "| "
            + " | ".join([
                str(row.get("market")),
                str(row.get("case_type")),
                str(row.get("rows")),
                fmt(row.get("mrms_interruption_rate")),
                fmt(row.get("mean_forecast_overcall_error")),
                fmt(row.get("mean_market_move_after_storm_bps")),
            ])
            + " |"
        )
    return "\n".join(lines) + "\n"
