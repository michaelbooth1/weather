"""Unit-explicit daily-summary helpers.

WU daily summaries now carry both market-native temperatures and true Celsius
temperatures. Older files stored native Fahrenheit in ``*_c`` columns for
Fahrenheit markets, so readers must choose the desired unit intentionally and
handle the legacy shape without guessing from a column suffix.
"""
import csv
from pathlib import Path

from weather.schema_registry import schema_version
from weather.units import c_to_f, c_to_native, f_to_c, native_to_c, round_half_up, to_float

WU_DAILY_SCHEMA_VERSION = schema_version("wu_daily")


def _first_number(row, columns):
    for column in columns:
        if column not in row:
            continue
        value = to_float(row.get(column))
        if value is not None:
            return value
    return None


def row_unit(row):
    return str(row.get("temperature_unit") or row.get("settlement_unit") or "C").upper()


def is_legacy_wu_c_lie(row):
    """True when ``*_c`` columns are known to carry native F values."""
    return row_unit(row) == "F" and row.get("schema_version") == "wu_daily_native_v1"


def native_high(row):
    return _first_number(row, ("max_temp_native", "max_temp", "max_temp_c"))


def native_bucket(row):
    bucket = _first_number(row, ("max_temp_bucket_native", "max_temp_bucket", "max_temp_bucket_c"))
    return round_half_up(bucket)


def native_min(row):
    return _first_number(row, ("min_temp_native", "min_temp", "min_temp_c"))


def native_avg(row):
    return _first_number(row, ("avg_temp_native", "avg_temp", "avg_temp_c"))


def native_dewpoint(row):
    return _first_number(row, ("max_dewpoint_native", "max_dewpoint", "max_dewpoint_c"))


def celsius_high(row):
    unit = row_unit(row)
    if is_legacy_wu_c_lie(row):
        return native_to_c(native_high(row), unit)
    explicit = to_float(row.get("max_temp_c"))
    if explicit is not None:
        return explicit
    return native_to_c(native_high(row), unit)


def celsius_bucket(row):
    high = celsius_high(row)
    return round_half_up(high)


def celsius_min(row):
    unit = row_unit(row)
    if is_legacy_wu_c_lie(row):
        return native_to_c(native_min(row), unit)
    explicit = to_float(row.get("min_temp_c"))
    if explicit is not None:
        return explicit
    return native_to_c(native_min(row), unit)


def celsius_avg(row):
    unit = row_unit(row)
    if is_legacy_wu_c_lie(row):
        return native_to_c(native_avg(row), unit)
    explicit = to_float(row.get("avg_temp_c"))
    if explicit is not None:
        return explicit
    return native_to_c(native_avg(row), unit)


def celsius_dewpoint(row):
    unit = row_unit(row)
    if is_legacy_wu_c_lie(row):
        return native_to_c(native_dewpoint(row), unit)
    explicit = to_float(row.get("max_dewpoint_c"))
    if explicit is not None:
        return explicit
    return native_to_c(native_dewpoint(row), unit)


def row_count(row):
    try:
        return int(float(row.get("row_count") or 0))
    except (TypeError, ValueError):
        return 0


def read_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def native_index(path):
    return {
        row["local_date"]: {
            "bucket": native_bucket(row),
            "high": native_high(row),
            "row_count": row_count(row),
            "unit": row_unit(row),
            "row": row,
        }
        for row in read_rows(path)
        if row.get("local_date") and native_bucket(row) is not None
    }


def celsius_index(path):
    return {
        row["local_date"]: {
            "bucket": celsius_bucket(row),
            "high_c": celsius_high(row),
            "row_count": row_count(row),
            "unit": "C",
            "row": row,
        }
        for row in read_rows(path)
        if row.get("local_date") and celsius_high(row) is not None
    }
