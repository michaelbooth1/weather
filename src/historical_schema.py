"""Shared normalized schema helpers for historical weather sources."""
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path


HOURLY_SCHEMA_VERSION = "historical_hourly_native_v1"
DAILY_SCHEMA_VERSION = "historical_daily_native_v1"

HOURLY_COLUMNS = [
    "schema_version",
    "source",
    "market_id",
    "city",
    "station",
    "station_name",
    "valid_time_utc",
    "valid_time_local",
    "local_date",
    "local_time",
    "minute",
    "temperature_unit",
    "temp_native",
    "dewpoint_native",
    "humidity",
    "pressure_hpa",
    "sea_level_pressure_hpa",
    "wind_dir_deg",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "condition",
    "clouds",
    "source_report_type",
    "source_quality",
]

DAILY_COLUMNS = [
    "schema_version",
    "source",
    "market_id",
    "city",
    "station",
    "station_name",
    "local_date",
    "temperature_unit",
    "row_count",
    "first_time",
    "last_time",
    "max_temp",
    "max_temp_bucket",
    "max_temp_times",
    "min_temp",
    "avg_temp",
    "max_dewpoint",
    "max_wind_kmh",
    "max_gust_kmh",
]


def sha256_file(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def round_half_up(value):
    if value is None:
        return None
    return int(math.floor(float(value) + 0.5))


def to_float(value):
    if value in (None, "", "None", "null", "NaN"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def c_to_native(value, unit):
    value = to_float(value)
    if value is None:
        return None
    return round(value * 9.0 / 5.0 + 32.0, 2) if unit == "F" else value


def normalize_wind_direction(value):
    number = to_float(value)
    if number is None or number >= 999:
        return None
    return int(number)


def localize_utc(naive_dt, tzinfo):
    return naive_dt.replace(tzinfo=timezone.utc).astimezone(tzinfo)


def hourly_record(
    *,
    source,
    spec,
    station,
    station_name,
    valid_time_local,
    temp_native=None,
    dewpoint_native=None,
    humidity=None,
    pressure_hpa=None,
    sea_level_pressure_hpa=None,
    wind_dir_deg=None,
    wind_speed_kmh=None,
    wind_gust_kmh=None,
    condition=None,
    clouds=None,
    source_report_type=None,
    source_quality=None,
):
    valid_time_utc = valid_time_local.astimezone(timezone.utc)
    return {
        "schema_version": HOURLY_SCHEMA_VERSION,
        "source": source,
        "market_id": spec.id,
        "city": spec.city_label,
        "station": station,
        "station_name": station_name,
        "valid_time_utc": valid_time_utc.isoformat(),
        "valid_time_local": valid_time_local.isoformat(),
        "local_date": valid_time_local.date().isoformat(),
        "local_time": valid_time_local.strftime("%H:%M"),
        "minute": valid_time_local.minute,
        "temperature_unit": spec.display_unit,
        "temp_native": temp_native,
        "dewpoint_native": dewpoint_native,
        "humidity": to_float(humidity),
        "pressure_hpa": to_float(pressure_hpa),
        "sea_level_pressure_hpa": to_float(sea_level_pressure_hpa),
        "wind_dir_deg": normalize_wind_direction(wind_dir_deg),
        "wind_speed_kmh": to_float(wind_speed_kmh),
        "wind_gust_kmh": to_float(wind_gust_kmh),
        "condition": condition,
        "clouds": clouds,
        "source_report_type": source_report_type,
        "source_quality": source_quality,
    }


def summarize_daily(records):
    grouped = defaultdict(list)
    for row in records:
        if row.get("local_date"):
            grouped[row["local_date"]].append(row)

    daily_rows = []
    for local_date, rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda item: item["valid_time_local"])
        temps = [to_float(row.get("temp_native")) for row in rows if to_float(row.get("temp_native")) is not None]
        dewpoints = [
            to_float(row.get("dewpoint_native")) for row in rows
            if to_float(row.get("dewpoint_native")) is not None
        ]
        winds = [
            to_float(row.get("wind_speed_kmh")) for row in rows
            if to_float(row.get("wind_speed_kmh")) is not None
        ]
        gusts = [
            to_float(row.get("wind_gust_kmh")) for row in rows
            if to_float(row.get("wind_gust_kmh")) is not None
        ]
        max_temp = max(temps) if temps else None
        max_times = [
            row["local_time"] for row in rows
            if max_temp is not None and to_float(row.get("temp_native")) == max_temp
        ]
        unit = next((row.get("temperature_unit") for row in rows if row.get("temperature_unit")), "")
        daily_rows.append({
            "schema_version": DAILY_SCHEMA_VERSION,
            "source": rows[0].get("source"),
            "market_id": rows[0].get("market_id"),
            "city": rows[0].get("city"),
            "station": rows[0].get("station"),
            "station_name": rows[0].get("station_name"),
            "local_date": local_date,
            "temperature_unit": unit,
            "row_count": len(rows),
            "first_time": rows[0].get("local_time"),
            "last_time": rows[-1].get("local_time"),
            "max_temp": max_temp,
            "max_temp_bucket": round_half_up(max_temp),
            "max_temp_times": "|".join(max_times),
            "min_temp": min(temps) if temps else None,
            "avg_temp": round(sum(temps) / len(temps), 2) if temps else None,
            "max_dewpoint": max(dewpoints) if dewpoints else None,
            "max_wind_kmh": max(winds) if winds else None,
            "max_gust_kmh": max(gusts) if gusts else None,
        })
    return daily_rows


def write_jsonl_partitions(root, records):
    root = Path(root)
    if root.exists():
        for old_file in root.glob("year=*/month=*/observations.jsonl"):
            old_file.unlink()
    grouped = defaultdict(list)
    for row in records:
        local_date = date.fromisoformat(row["local_date"])
        grouped[(local_date.year, local_date.month)].append(row)
    for (year, month), rows in grouped.items():
        path = root / f"year={year:04d}" / f"month={month:02d}" / "observations.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_daily_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DAILY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_manifest(path, source, spec, raw_root, hourly_root, daily_rows, metadata=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partitions = []
    for file_path in sorted(Path(hourly_root).glob("year=*/month=*/observations.jsonl")):
        with file_path.open("r", encoding="utf-8") as handle:
            row_count = sum(1 for _ in handle)
        partitions.append({
            "path": file_path.relative_to(path.parent).as_posix(),
            "row_count": row_count,
            "sha256": sha256_file(file_path),
        })
    raw_files = [
        {
            "path": file_path.relative_to(path.parent).as_posix(),
            "sha256": sha256_file(file_path),
            "bytes": file_path.stat().st_size,
        }
        for file_path in sorted(Path(raw_root).glob("**/*"))
        if file_path.is_file()
    ]
    payload = {
        "schema_version": "historical_source_manifest_v1",
        "source": source,
        "market_id": spec.id,
        "city": spec.city_label,
        "station": getattr(spec, "icao", ""),
        "temperature_unit": spec.display_unit,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_version": metadata.get("code_version") if metadata else None,
        "daily_record_count": len(daily_rows),
        "first_date": daily_rows[0]["local_date"] if daily_rows else None,
        "last_date": daily_rows[-1]["local_date"] if daily_rows else None,
        "raw_files": raw_files,
        "partitions": partitions,
        "metadata": metadata or {},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def quality_counts(records):
    counts = Counter(row.get("source_quality") or "" for row in records)
    return dict(sorted(counts.items()))
