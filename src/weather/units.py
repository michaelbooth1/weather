"""Canonical nullable temperature and market-bucket helpers."""

from __future__ import annotations

import math


NULL_TEMPERATURE_VALUES = {None, "", "None", "none", "null", "NaN", "nan", "MSNG"}


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
