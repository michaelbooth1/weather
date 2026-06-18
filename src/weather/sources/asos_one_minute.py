"""IEM/NCEI one-minute ASOS normalization and spike-timing helpers."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.paths import data_path

import requests

from weather.sources.historical_schema import to_float
from weather.units import f_to_native, round_half_up


ASOS_1MIN_SCHEMA_VERSION = "asos_1min_v0.1"
SOURCE = "asos_1min"
IEM_ASOS_1MIN_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos1min.py"
DEFAULT_ROOT = data_path() / "sources" / "asos_1min"


def payload_hash(text: str) -> str:
    return hashlib.sha1(str(text or "").encode("utf-8")).hexdigest()


def parse_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def parse_valid_utc(value):
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_now():
    return datetime.now(timezone.utc)


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def knots_to_kmh(value):
    value = to_float(value)
    return None if value is None else round(value * 1.852, 2)


def inches_hg_to_hpa(value):
    value = to_float(value)
    return None if value is None else round(value * 33.8638866667, 2)


def resolve_iem_1min_station(spec):
    icao = str(getattr(spec, "icao", "") or "").upper()
    if ":US" not in str(getattr(spec, "wu_history_id", "")):
        return {
            "supported": False,
            "station": None,
            "icao": icao,
            "reason": "IEM one-minute ASOS resolver is US-only.",
        }
    if not icao:
        return {
            "supported": False,
            "station": None,
            "icao": icao,
            "reason": "market has no ICAO station.",
        }
    station = icao[1:] if icao.startswith("K") and len(icao) == 4 else icao
    return {"supported": True, "station": station, "icao": icao, "reason": ""}


def build_iem_1min_params(station, start_utc, end_utc):
    start = parse_valid_utc(start_utc)
    end = parse_valid_utc(end_utc)
    if start is None or end is None:
        raise ValueError("start_utc and end_utc must be parseable datetimes")
    return {
        "station": str(station).upper(),
        "year1": start.year,
        "month1": start.month,
        "day1": start.day,
        "hour1": start.hour,
        "minute1": start.minute,
        "year2": end.year,
        "month2": end.month,
        "day2": end.day,
        "hour2": end.hour,
        "minute2": end.minute,
        "tz": "Etc/UTC",
        "format": "onlycomma",
        "vars": "tmpf,dwpf,sknt,drct,alti",
    }


def normalize_iem_1min_csv(text, spec, station=None, source_url=IEM_ASOS_1MIN_URL, fetched_at=None):
    station = station or resolve_iem_1min_station(spec).get("station") or getattr(spec, "icao", "")
    digest = payload_hash(text)
    fetched_dt = parse_valid_utc(fetched_at) if fetched_at else None
    fetched_at_utc = fetched_dt.isoformat() if fetched_dt else None
    rows = []
    reader = csv.DictReader(io.StringIO(text or ""))
    for raw in reader:
        utc_dt = parse_valid_utc(raw.get("valid") or raw.get("time") or raw.get("timestamp"))
        temp_f = to_float(raw.get("tmpf"))
        if utc_dt is None or temp_f is None:
            continue
        local_dt = utc_dt.astimezone(spec.tz)
        dewpoint_f = to_float(raw.get("dwpf"))
        rows.append({
            "schema_version": ASOS_1MIN_SCHEMA_VERSION,
            "source": SOURCE,
            "market": spec.id,
            "station": spec.icao,
            "iem_station": station,
            "valid_time_utc": utc_dt.isoformat(),
            "valid_time_local": local_dt.isoformat(),
            "local_date": local_dt.date().isoformat(),
            "minute_of_day": local_dt.hour * 60 + local_dt.minute,
            "temp_native": f_to_native(temp_f, spec.display_unit),
            "temp_f": temp_f,
            "dewpoint_native": f_to_native(dewpoint_f, spec.display_unit),
            "dewpoint_f": dewpoint_f,
            "wind_speed_kmh": knots_to_kmh(raw.get("sknt")),
            "wind_dir_deg": to_float(raw.get("drct")),
            "pressure_hpa": inches_hg_to_hpa(raw.get("alti")),
            "source_url": source_url,
            "payload_hash": digest,
            "fetched_at_utc": fetched_at_utc,
            "raw_station": raw.get("station") or station,
        })
    rows.sort(key=lambda row: row["valid_time_utc"])
    return rows


def availability_summary(spec, local_date, rows, expected_minutes=1440, station_resolution=None):
    local_date = parse_date(local_date).isoformat()
    station_resolution = station_resolution or resolve_iem_1min_station(spec)
    day_rows = [row for row in rows or [] if row.get("local_date") == local_date]
    temp_rows = [row for row in day_rows if row.get("temp_native") is not None]
    expected = max(1, int(expected_minutes or 1))
    if not station_resolution.get("supported"):
        reason = station_resolution.get("reason") or "unsupported station"
    elif not temp_rows:
        reason = "no one-minute rows with temperature"
    else:
        reason = ""
    return {
        "schema_version": ASOS_1MIN_SCHEMA_VERSION,
        "market": spec.id,
        "station": spec.icao,
        "iem_station": station_resolution.get("station"),
        "local_date": local_date,
        "supported": bool(station_resolution.get("supported")),
        "available": bool(temp_rows) and bool(station_resolution.get("supported")),
        "row_count": len(day_rows),
        "temp_row_count": len(temp_rows),
        "expected_minutes": expected,
        "coverage_ratio": len(temp_rows) / expected,
        "first_minute": min((row.get("minute_of_day") for row in temp_rows), default=None),
        "last_minute": max((row.get("minute_of_day") for row in temp_rows), default=None),
        "reason": reason,
    }


def _row_temp(row):
    for key in ("temp_native", "temp_f", "temp_c"):
        value = to_float((row or {}).get(key))
        if value is not None:
            return value
    return None


def _longest_consecutive_run(minutes):
    minutes = sorted(set(int(minute) for minute in minutes if minute is not None))
    if not minutes:
        return 0
    best = current = 1
    for previous, minute in zip(minutes, minutes[1:]):
        if minute == previous + 1:
            current += 1
        else:
            best = max(best, current)
            current = 1
    return max(best, current)


def _local_minute(value, spec=None):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value)
    if ":" in text and "T" not in text and len(text.split(":")[0]) <= 2:
        parts = text.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except (TypeError, ValueError):
            return None
    parsed = parse_valid_utc(value)
    if parsed is None:
        return None
    local = parsed.astimezone(spec.tz) if spec is not None else parsed
    return local.hour * 60 + local.minute


def market_day_utc_window(spec, local_date):
    local_date = parse_date(local_date)
    start_local = datetime(local_date.year, local_date.month, local_date.day, tzinfo=spec.tz)
    end_local = start_local + timedelta(days=1) - timedelta(minutes=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _group_by(rows, key_func):
    grouped = defaultdict(list)
    for row in rows or []:
        grouped[key_func(row)].append(row)
    return grouped


def _row_valid_dt(row):
    return parse_valid_utc((row or {}).get("valid_time_utc"))


def summarize_hourly(rows):
    summaries = []
    for (market, station, local_date, hour), group in sorted(_group_by(
        rows,
        lambda row: (
            row.get("market"),
            row.get("station"),
            row.get("local_date"),
            int(row.get("minute_of_day") or 0) // 60,
        ),
    ).items()):
        temps = [_row_temp(row) for row in group]
        temps = [temp for temp in temps if temp is not None]
        valid_times = [_row_valid_dt(row) for row in group]
        valid_times = [item for item in valid_times if item is not None]
        summaries.append({
            "schema_version": ASOS_1MIN_SCHEMA_VERSION,
            "source": SOURCE,
            "market": market,
            "station": station,
            "iem_station": group[0].get("iem_station"),
            "local_date": local_date,
            "local_hour": hour,
            "row_count": len(group),
            "temp_row_count": len(temps),
            "max_temp_native": max(temps) if temps else None,
            "min_temp_native": min(temps) if temps else None,
            "mean_temp_native": round(mean(temps), 4) if temps else None,
            "first_valid_utc": min(valid_times).isoformat() if valid_times else None,
            "last_valid_utc": max(valid_times).isoformat() if valid_times else None,
            "payload_hashes": ";".join(sorted({str(row.get("payload_hash")) for row in group if row.get("payload_hash")})),
        })
    return summaries


def summarize_daily(rows, expected_minutes=1440):
    summaries = []
    expected = max(1, int(expected_minutes or 1))
    for (market, station, local_date), group in sorted(_group_by(
        rows,
        lambda row: (row.get("market"), row.get("station"), row.get("local_date")),
    ).items()):
        temps_by_minute = [
            (int(row.get("minute_of_day")), _row_temp(row))
            for row in group
            if row.get("minute_of_day") is not None and _row_temp(row) is not None
        ]
        temps = [temp for _, temp in temps_by_minute]
        max_temp = max(temps) if temps else None
        high_minutes = [minute for minute, temp in temps_by_minute if temp == max_temp]
        valid_times = [_row_valid_dt(row) for row in group]
        valid_times = [item for item in valid_times if item is not None]
        fetched_times = [parse_valid_utc(row.get("fetched_at_utc")) for row in group if row.get("fetched_at_utc")]
        fetched_times = [item for item in fetched_times if item is not None]
        source_lag = None
        if fetched_times and valid_times:
            source_lag = (max(fetched_times) - max(valid_times)).total_seconds() / 60.0
        summaries.append({
            "schema_version": ASOS_1MIN_SCHEMA_VERSION,
            "source": SOURCE,
            "market": market,
            "station": station,
            "iem_station": group[0].get("iem_station"),
            "local_date": local_date,
            "row_count": len(group),
            "temp_row_count": len(temps),
            "expected_minutes": expected,
            "coverage_ratio": len(temps) / expected,
            "max_temp_native": max_temp,
            "first_reached_minute": min(high_minutes) if high_minutes else None,
            "high_duration_minutes": len(high_minutes),
            "spike_persistence_minutes": _longest_consecutive_run(high_minutes),
            "first_valid_utc": min(valid_times).isoformat() if valid_times else None,
            "last_valid_utc": max(valid_times).isoformat() if valid_times else None,
            "source_lag_minutes": round(source_lag, 2) if source_lag is not None else None,
            "payload_hashes": ";".join(sorted({str(row.get("payload_hash")) for row in group if row.get("payload_hash")})),
        })
    return summaries


def high_timing_features(rows, cutoff_hour=None, wall_minute=None, hourly_rows=None):
    cutoff_minute = int(cutoff_hour) * 60 if cutoff_hour is not None else None
    end_minute = int(wall_minute) if wall_minute is not None else cutoff_minute
    source_rows = []
    for row in rows or []:
        minute = row.get("minute_of_day")
        temp = _row_temp(row)
        if minute is None or temp is None:
            continue
        minute = int(minute)
        if end_minute is not None and minute > end_minute:
            continue
        source_rows.append((minute, temp))
    if not source_rows:
        return {
            "asos_1min_row_count": 0,
            "asos_1min_max_so_far": None,
            "asos_1min_first_reached_minute": None,
            "asos_1min_high_duration_minutes": None,
            "asos_1min_spike_persistence_minutes": None,
            "asos_1min_intrahour_max_since_last_print": None,
            "asos_1min_minus_hourly_metar_high": None,
        }
    max_temp = max(temp for _, temp in source_rows)
    high_minutes = [minute for minute, temp in source_rows if temp == max_temp]
    hourly_temps = [
        _row_temp(row) for row in hourly_rows or []
        if _row_temp(row) is not None
    ]
    hourly_high = max(hourly_temps) if hourly_temps else None
    intrahour_start = (end_minute - 59) if end_minute is not None else None
    intrahour_values = [
        temp for minute, temp in source_rows
        if intrahour_start is None or minute >= intrahour_start
    ]
    return {
        "asos_1min_row_count": len(source_rows),
        "asos_1min_max_so_far": max_temp,
        "asos_1min_first_reached_minute": min(high_minutes),
        "asos_1min_high_duration_minutes": len(high_minutes),
        "asos_1min_spike_persistence_minutes": _longest_consecutive_run(high_minutes),
        "asos_1min_intrahour_max_since_last_print": max(intrahour_values) if intrahour_values else None,
        "asos_1min_minus_hourly_metar_high": (
            max_temp - hourly_high if hourly_high is not None else None
        ),
    }


def compare_asos_1min_to_wu(
    rows,
    spec,
    local_date=None,
    settlement_bucket=None,
    wu_final_high=None,
    wu_print_time=None,
    hourly_rows=None,
):
    local_date_text = parse_date(local_date).isoformat() if local_date else None
    day_rows = [
        row for row in rows or []
        if local_date_text is None or row.get("local_date") == local_date_text
    ]
    features = high_timing_features(day_rows, wall_minute=1439, hourly_rows=hourly_rows)
    asos_max = features.get("asos_1min_max_so_far")
    first_minute = features.get("asos_1min_first_reached_minute")
    settlement_value = to_float(settlement_bucket)
    wu_final = to_float(wu_final_high)
    if wu_final is None:
        wu_final = settlement_value
    wu_print_minute = _local_minute(wu_print_time, spec=spec)
    return {
        "schema_version": ASOS_1MIN_SCHEMA_VERSION,
        "source": SOURCE,
        "market": spec.id,
        "station": spec.icao,
        "local_date": local_date_text or (day_rows[0].get("local_date") if day_rows else None),
        **features,
        "settlement_bucket": settlement_value,
        "asos_1min_bucket": round_half_up(asos_max),
        "asos_1min_minus_settlement_bucket": asos_max - settlement_value if asos_max is not None and settlement_value is not None else None,
        "wu_final_high": wu_final,
        "asos_1min_minus_wu_final_high": asos_max - wu_final if asos_max is not None and wu_final is not None else None,
        "wu_print_minute": wu_print_minute,
        "asos_1min_minutes_from_first_high_to_wu_print": (
            wu_print_minute - first_minute if wu_print_minute is not None and first_minute is not None else None
        ),
    }


def compare_daily_summary_to_wu_print(summary, settlement_bucket=None, wu_print_time=None, spec=None):
    summary = summary or {}
    asos_max = to_float(summary.get("max_temp_native") or summary.get("asos_1min_max_so_far"))
    first_minute = to_float(summary.get("first_reached_minute") or summary.get("asos_1min_first_reached_minute"))
    settlement_value = to_float(settlement_bucket)
    print_minute = _local_minute(wu_print_time, spec=spec)
    return {
        "asos_1min_available": bool(summary),
        "asos_1min_local_date": summary.get("local_date"),
        "asos_1min_row_count": to_float(summary.get("temp_row_count") or summary.get("row_count")),
        "asos_1min_coverage_ratio": to_float(summary.get("coverage_ratio")),
        "asos_1min_max_so_far": asos_max,
        "asos_1min_first_reached_minute": int(first_minute) if first_minute is not None else None,
        "asos_1min_high_duration_minutes": to_float(summary.get("high_duration_minutes")),
        "asos_1min_spike_persistence_minutes": to_float(summary.get("spike_persistence_minutes")),
        "asos_1min_bucket": round_half_up(asos_max),
        "asos_1min_minus_settlement_bucket": (
            asos_max - settlement_value if asos_max is not None and settlement_value is not None else None
        ),
        "asos_1min_wu_print_minute": print_minute,
        "asos_1min_minutes_from_first_high_to_wu_print": (
            print_minute - first_minute if print_minute is not None and first_minute is not None else None
        ),
        "asos_1min_source_lag_minutes": to_float(summary.get("source_lag_minutes")),
    }


def late_day_lockin_evidence(
    rows,
    spec,
    local_date,
    now,
    current_reading=None,
    settlement_bucket=None,
    wu_final_high=None,
    wu_print_time=None,
    hourly_rows=None,
    min_stood_minutes=45,
):
    now_minute = _local_minute(now, spec=spec)
    comparison = compare_asos_1min_to_wu(
        rows,
        spec,
        local_date=local_date,
        settlement_bucket=settlement_bucket,
        wu_final_high=wu_final_high,
        wu_print_time=wu_print_time,
        hourly_rows=hourly_rows,
    )
    first_minute = comparison.get("asos_1min_first_reached_minute")
    max_temp = comparison.get("asos_1min_max_so_far")
    current_value = to_float(current_reading)
    stood_minutes = now_minute - first_minute if now_minute is not None and first_minute is not None else None
    current_minus_high = current_value - max_temp if current_value is not None and max_temp is not None else None
    reasons = []
    if not comparison.get("asos_1min_row_count"):
        reasons.append("missing_asos_1min_rows")
    if stood_minutes is None:
        reasons.append("missing_first_high_or_now")
    elif stood_minutes < int(min_stood_minutes):
        reasons.append("high_not_stood_long_enough")
    if current_minus_high is None:
        reasons.append("missing_current_reading")
    elif current_minus_high > 0:
        reasons.append("current_above_one_minute_high")
    return {
        "schema_version": ASOS_1MIN_SCHEMA_VERSION,
        "report": "late_day_lockin_asos_1min_evidence",
        "market": spec.id,
        "station": spec.icao,
        "local_date": parse_date(local_date).isoformat(),
        **comparison,
        "now_minute": now_minute,
        "stood_minutes": stood_minutes,
        "current_minus_asos_1min_high": current_minus_high,
        "supports_lockin": not reasons,
        "reason": "ok" if not reasons else ";".join(reasons),
    }


def adoption_gate(
    availability_rows,
    comparison_rows=None,
    min_coverage_ratio=0.8,
    max_abs_bias=1.0,
    min_exact_bucket_agreement=0.7,
    max_source_lag_minutes=180.0,
):
    availability_rows = availability_rows or []
    comparison_rows = comparison_rows or []
    coverage_values = [
        to_float(row.get("coverage_ratio"))
        for row in availability_rows
        if row.get("available", True)
    ]
    coverage_values = [value for value in coverage_values if value is not None]
    bias_values = []
    for row in comparison_rows:
        raw_bias = row.get("asos_1min_minus_settlement_bucket")
        if raw_bias is None or raw_bias == "":
            raw_bias = row.get("asos_minus_settlement")
        value = to_float(raw_bias)
        if value is not None:
            bias_values.append(abs(value))
    agreements = []
    for row in comparison_rows:
        explicit = to_float(row.get("exact_bucket_agreement"))
        if explicit is not None:
            agreements.append(1.0 if explicit >= 1.0 else 0.0)
            continue
        asos_bucket = to_float(row.get("asos_1min_bucket"))
        settlement = to_float(row.get("settlement_bucket"))
        if asos_bucket is not None and settlement is not None:
            agreements.append(1.0 if int(asos_bucket) == int(settlement) else 0.0)
    lag_values = []
    for row in comparison_rows:
        raw_lag = row.get("source_lag_minutes")
        if raw_lag is None or raw_lag == "":
            raw_lag = row.get("asos_1min_source_lag_minutes")
        lag_values.append(to_float(raw_lag))
    lag_values = [value for value in lag_values if value is not None]

    coverage_ok = bool(coverage_values) and min(coverage_values) >= float(min_coverage_ratio)
    bias_ok = bool(bias_values) and mean(bias_values) <= float(max_abs_bias)
    agreement_ok = bool(agreements) and mean(agreements) >= float(min_exact_bucket_agreement)
    lag_ok = bool(lag_values) and max(lag_values) <= float(max_source_lag_minutes)
    checks = {
        "coverage": coverage_ok,
        "bias": bias_ok,
        "exact_bucket_agreement": agreement_ok,
        "source_lag": lag_ok,
    }
    failing = [name for name, ok in checks.items() if not ok]
    return {
        "schema_version": ASOS_1MIN_SCHEMA_VERSION,
        "source": SOURCE,
        "adopt": not failing,
        "status": "ADOPT" if not failing else "DO_NOT_ADOPT",
        "reason": "ok" if not failing else ";".join(failing),
        "checks": checks,
        "coverage_days": len(coverage_values),
        "min_coverage_ratio": min(coverage_values) if coverage_values else None,
        "mean_abs_bias": mean(bias_values),
        "exact_bucket_agreement_rate": mean(agreements),
        "max_source_lag_minutes": max(lag_values) if lag_values else None,
        "thresholds": {
            "min_coverage_ratio": min_coverage_ratio,
            "max_abs_bias": max_abs_bias,
            "min_exact_bucket_agreement": min_exact_bucket_agreement,
            "max_source_lag_minutes": max_source_lag_minutes,
        },
    }


def _write_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fieldnames})
    return path


def _write_jsonl_partitions(root, rows):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for local_date, group in sorted(_group_by(rows, lambda row: row.get("local_date")).items()):
        path = root / f"{local_date}.jsonl"
        with path.open("w", encoding="utf-8") as handle:
            for row in sorted(group, key=lambda item: item.get("valid_time_utc") or ""):
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        written.append(path)
    return written


def load_daily_summary(root, spec, local_date):
    root = Path(root)
    store_root = root if (root / "daily" / "daily_summary.csv").exists() else root / spec.id
    path = store_root / "daily" / "daily_summary.csv"
    if not path.exists():
        return None
    target = parse_date(local_date).isoformat()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("local_date") == target:
                return row
    return None


class AsosOneMinuteClient:
    RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(self, timeout=60, max_attempts=3, retry_sleep=10):
        self.timeout = timeout
        self.max_attempts = max(1, int(max_attempts))
        self.retry_sleep = retry_sleep

    def fetch(self, station, start_utc, end_utc):
        params = build_iem_1min_params(station, start_utc, end_utc)
        for attempt in range(1, self.max_attempts + 1):
            response = requests.get(IEM_ASOS_1MIN_URL, params=params, timeout=self.timeout)
            try:
                response.raise_for_status()
                return response.text
            except requests.HTTPError:
                if response.status_code not in self.RETRY_STATUS_CODES or attempt == self.max_attempts:
                    raise
                retry_after = response.headers.get("Retry-After")
                try:
                    sleep_seconds = float(retry_after) if retry_after else None
                except ValueError:
                    sleep_seconds = None
                if sleep_seconds is None:
                    sleep_seconds = self.retry_sleep * attempt
                time.sleep(max(0.0, sleep_seconds))
        return ""


class AsosOneMinuteStore:
    def __init__(self, spec, root=None):
        self.spec = spec
        self.root = Path(root) if root else DEFAULT_ROOT / spec.id
        self.raw_root = self.root / "raw"
        self.rows_root = self.root / "rows"
        self.hourly_root = self.root / "hourly"
        self.daily_root = self.root / "daily"

    def raw_path(self, local_date):
        local_date = parse_date(local_date)
        return self.raw_root / f"asos_1min_{local_date.isoformat()}.csv"

    def raw_files(self):
        return sorted(self.raw_root.glob("asos_1min_*.csv"))

    def raw_dates(self):
        dates = []
        for path in self.raw_files():
            try:
                dates.append(date.fromisoformat(path.stem.replace("asos_1min_", "")))
            except ValueError:
                continue
        return sorted(set(dates))

    def backfill(
        self,
        start_date,
        end_date,
        skip_existing=False,
        client=None,
        sleep_seconds=0.0,
    ):
        start_date = parse_date(start_date)
        end_date = parse_date(end_date)
        resolution = resolve_iem_1min_station(self.spec)
        self.raw_root.mkdir(parents=True, exist_ok=True)
        if not resolution.get("supported"):
            return self.rebuild(station_resolution=resolution)
        client = client or AsosOneMinuteClient()
        current = start_date
        while current <= end_date:
            path = self.raw_path(current)
            if not skip_existing or not path.exists():
                start_utc, end_utc = market_day_utc_window(self.spec, current)
                text = client.fetch(resolution["station"], start_utc, end_utc)
                path.write_text(text, encoding="utf-8")
                if sleep_seconds:
                    time.sleep(sleep_seconds)
            current = current + timedelta(days=1)
        return self.rebuild(station_resolution=resolution)

    def rebuild(self, station_resolution=None, comparison_rows=None):
        station_resolution = station_resolution or resolve_iem_1min_station(self.spec)
        rows = []
        for path in self.raw_files():
            text = path.read_text(encoding="utf-8")
            fetched_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
            rows.extend(normalize_iem_1min_csv(
                text,
                self.spec,
                station=station_resolution.get("station"),
                fetched_at=fetched_at,
            ))
        rows = sorted(rows, key=lambda row: (row.get("valid_time_utc") or "", row.get("payload_hash") or ""))
        _write_jsonl_partitions(self.rows_root, rows)
        hourly_rows = summarize_hourly(rows)
        daily_rows = summarize_daily(rows)
        availability_dates = {parse_date(row.get("local_date")) for row in daily_rows if row.get("local_date")}
        availability_dates.update(self.raw_dates())
        availability_rows = []
        daily_by_date = {row.get("local_date"): row for row in daily_rows}
        for local_day in sorted(availability_dates):
            daily = daily_by_date.get(local_day.isoformat()) or {}
            availability_rows.append(availability_summary(
                self.spec,
                local_day,
                rows,
                expected_minutes=daily.get("expected_minutes") or 1440,
                station_resolution=station_resolution,
            ))
        gate = adoption_gate(availability_rows, comparison_rows or [])
        _write_csv(
            self.hourly_root / "hourly_summary.csv",
            hourly_rows,
            [
                "schema_version", "source", "market", "station", "iem_station",
                "local_date", "local_hour", "row_count", "temp_row_count",
                "max_temp_native", "min_temp_native", "mean_temp_native",
                "first_valid_utc", "last_valid_utc", "payload_hashes",
            ],
        )
        _write_csv(
            self.daily_root / "daily_summary.csv",
            daily_rows,
            [
                "schema_version", "source", "market", "station", "iem_station",
                "local_date", "row_count", "temp_row_count", "expected_minutes",
                "coverage_ratio", "max_temp_native", "first_reached_minute",
                "high_duration_minutes", "spike_persistence_minutes",
                "first_valid_utc", "last_valid_utc", "source_lag_minutes",
                "payload_hashes",
            ],
        )
        manifest = {
            "schema_version": ASOS_1MIN_SCHEMA_VERSION,
            "source": SOURCE,
            "provider": "IEM ASOS one-minute",
            "market": self.spec.id,
            "station": self.spec.icao,
            "iem_station": station_resolution.get("station"),
            "station_resolution": station_resolution,
            "raw_file_count": len(self.raw_files()),
            "row_count": len(rows),
            "hourly_rows": len(hourly_rows),
            "daily_rows": len(daily_rows),
            "availability": availability_rows,
            "adoption_gate": gate,
            "outputs": {
                "rows_root": str(self.rows_root),
                "hourly_summary": str(self.hourly_root / "hourly_summary.csv"),
                "daily_summary": str(self.daily_root / "daily_summary.csv"),
            },
            "generated_at": utc_now().isoformat(),
        }
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {
            "records": len(rows),
            "hourly_rows": len(hourly_rows),
            "daily_rows": len(daily_rows),
            "manifest": manifest,
        }
