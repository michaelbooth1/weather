"""Shared venue revision selection and exact native-unit bucketing.

Legacy training labels keep their correction preference; authoritative raw snapshots
use last-shown order. Both paths use this one revision selector.
"""

from decimal import Decimal, ROUND_FLOOR
from fractions import Fraction


def native_decimal(value, unit):
    if isinstance(value, Fraction):
        value = Decimal(value.numerator) / Decimal(value.denominator)
    elif not isinstance(value, Decimal):
        value = Decimal(str(value))
    if not value.is_finite() or unit not in {"C", "F"}:
        raise ValueError("invalid temperature or unit")
    return value * Decimal(9) / Decimal(5) + Decimal(32) if unit == "F" else value


def settlement_bucket(temperature_c, unit):
    """Round ties toward the higher integer, including negative half degrees."""
    value = native_decimal(temperature_c, unit)
    return int((value + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))


def select_reports(routine_reports, *, snapshot_order=False, deadlines=None):
    """One report per observation time; an accepted correction replaces the original.

    The default retains legacy IEM correction preference and next-day closure.
    snapshot_order uses last-shown order, including unmarked replacements.
    deadlines supplies explicit per-day publication cutoffs for captured replay.
    """

    first_by_date = {}
    for report in routine_reports:
        first_by_date.setdefault(report["local_date"], report["valid_time_utc"])
    dates = sorted(first_by_date)

    def deadline(local_date):
        if deadlines is not None:
            return deadlines.get(local_date)
        later = [day for day in dates if day > local_date]
        return first_by_date[later[0]] if later else None

    chosen = {}
    rejected = 0
    for report in routine_reports:
        key = report["valid_time_utc"]
        if snapshot_order:
            receipt = report.get("receipt_utc")
            limit = deadline(report["local_date"])
            if receipt is not None and limit is not None and receipt >= limit:
                rejected += 1
                continue
            chosen[key] = report
            continue
        if report["corrected"]:
            limit = deadline(report["local_date"])
            receipt = report.get("receipt_utc")
            if receipt is not None and (limit is None or receipt >= limit):
                rejected += 1
                continue
            chosen[key] = report
            continue
        current = chosen.get(key)
        if current is None or not current["corrected"]:
            chosen[key] = report
    return [chosen[key] for key in sorted(chosen)], rejected
