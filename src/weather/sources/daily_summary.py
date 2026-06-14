"""Unit-explicit daily-summary helpers.

WU daily summaries now carry both market-native temperatures and true Celsius
temperatures. Older files stored native Fahrenheit in ``*_c`` columns for
Fahrenheit markets, so readers must choose the desired unit intentionally and
handle the legacy shape without guessing from a column suffix.
"""
import csv
import math
from pathlib import Path


WU_DAILY_SCHEMA_VERSION = "wu_daily_native_v2"


def to_float(value):
    if value in (None, "", "None", "null", "NaN", "MSNG"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def round_half_up(value):
    value = to_float(value)
    if value is None:
        return None
    return int(math.floor(value + 0.5))


def f_to_c(value):
    value = to_float(value)
    if value is None:
        return None
    return round((value - 32.0) * 5.0 / 9.0, 4)


def c_to_f(value):
    value = to_float(value)
    if value is None:
        return None
    return round(value * 9.0 / 5.0 + 32.0, 4)


def native_to_c(value, unit):
    return f_to_c(value) if str(unit).upper() == "F" else to_float(value)


def c_to_native(value, unit):
    return c_to_f(value) if str(unit).upper() == "F" else to_float(value)


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
