"""Canonical nullable temperature and market-bucket helpers."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


NULL_TEMPERATURE_VALUES = {None, "", "None", "none", "null", "NaN", "nan", "MSNG"}


@dataclass(frozen=True)
class TemperatureBand:
    """Inclusive whole-degree endpoints in the market's native unit."""

    kind: str
    value: int
    value_hi: int
    unit: str | None = None


_TEMPERATURE_BAND = re.compile(
    r"(?P<value>[+-]?\d+)\s*(?P<unit>[CF])?\s*"
    r"(?:-\s*(?P<value_hi>[+-]?\d+)\s*(?P<unit_hi>[CF])?\s*)?"
    r"(?:(?:or\s+)?(?P<tail>below|under|lower|above|higher))?",
    re.IGNORECASE,
)


def parse_temperature_band(label, *, expected_unit=None):
    """Parse a complete band label, never arbitrary numbers from a question.

    A range separator and a negative endpoint are distinct: ``80-81 F`` and
    ``-5--4 C`` both retain their signs. Unknown text, mixed units, fractional
    buckets, inverted ranges and range/threshold combinations are unparseable.
    No temperature conversion or rounding is performed.
    """
    if not isinstance(label, str):
        return None
    text = label.replace("\u00c2", "").replace("\ufffd", "")
    text = text.replace("\u2103", " C").replace("\u2109", " F")
    text = text.replace("\u00b0", " ").replace("\u00ba", " ")
    text = text.translate(str.maketrans({"\u2212": "-", "\u2013": "-", "\u2014": "-"}))
    match = _TEMPERATURE_BAND.fullmatch(text.strip())
    if match is None:
        return None
    units = {value.upper() for value in (match["unit"], match["unit_hi"]) if value}
    if len(units) > 1:
        return None
    unit = next(iter(units), None)
    if expected_unit is not None:
        expected_unit = str(expected_unit).upper()
        if expected_unit not in {"C", "F"} or unit not in {None, expected_unit}:
            return None
        unit = expected_unit
    value = int(match["value"])
    value_hi = int(match["value_hi"]) if match["value_hi"] is not None else value
    tail = (match["tail"] or "").lower()
    if value_hi < value or (tail and match["value_hi"] is not None):
        return None
    kind = "lte" if tail in {"below", "under", "lower"} else "gte" if tail else "eq"
    return TemperatureBand(kind, value, value_hi, unit)


def _whole_degree(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return int(number) if math.isfinite(number) and number.is_integer() else None


def temperature_band_key(row):
    """Read legacy/native row fields with one label fallback and validation.

    Explicit numeric endpoints remain authoritative for legacy single-value
    display labels that omitted a range's upper endpoint. An explicit lower
    endpoint, threshold kind or fully spelled range must agree with the label.
    Zero is a value; malformed explicit values cannot fall back to a label.
    """
    def first(*keys):
        for key in keys:
            value = row.get(key)
            if value is not None and value != "":
                return value
        return None

    invalid = ("eq", None, None)
    label = first("range_label", "winning_band")
    parsed = parse_temperature_band(label)
    if label is not None and parsed is None:
        return invalid
    raw_kind = first("bin_kind", "winning_band_kind")
    kind = str(raw_kind).strip().lower() if raw_kind is not None else parsed.kind if parsed else "eq"
    if kind not in {"eq", "lte", "gte"} or (parsed and kind != parsed.kind):
        return invalid
    raw_value = first("bin_value", "bin_value_c", "winning_band_value")
    raw_hi = first("bin_value_hi", "bin_value_hi_c", "winning_band_value_hi")
    value = _whole_degree(raw_value) if raw_value is not None else parsed.value if parsed else None
    value_hi = _whole_degree(raw_hi) if raw_hi is not None else parsed.value_hi if parsed else value
    if value is None or value_hi is None or value_hi < value:
        return invalid
    if kind != "eq" and value_hi != value:
        return invalid
    if parsed and (value != parsed.value or (parsed.value_hi != parsed.value and value_hi != parsed.value_hi)):
        return invalid
    return kind, value, value_hi


def to_float(value):
    if value in NULL_TEMPERATURE_VALUES:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def round_half_up(value):
    """Return the project-wide market bucket for a numeric temperature."""
    value = to_float(value)
    if value is None:
        return None
    return int(math.floor(value + 0.5))


def f_to_c(value, digits=4):
    value = to_float(value)
    if value is None:
        return None
    converted = (value - 32.0) * 5.0 / 9.0
    return round(converted, digits) if digits is not None else converted


def c_to_f(value, digits=4):
    value = to_float(value)
    if value is None:
        return None
    converted = value * 9.0 / 5.0 + 32.0
    return round(converted, digits) if digits is not None else converted


def native_to_c(value, unit, digits=4):
    return f_to_c(value, digits=digits) if str(unit).upper() == "F" else to_float(value)


def c_to_native(value, unit, digits=4):
    return c_to_f(value, digits=digits) if str(unit).upper() == "F" else to_float(value)


def native_to_f(value, unit, digits=4):
    return c_to_f(value, digits=digits) if str(unit).upper() == "C" else to_float(value)


def f_to_native(value, unit, digits=4):
    return f_to_c(value, digits=digits) if str(unit).upper() == "C" else to_float(value)
