"""Pure research helpers for report clocks and observation-only decidedness.

These are archive-observation probabilities, not settlement authority, live
availability, or trading permission. Inputs must be in one station's native
unit. Hourly-rule filtering reproduces WRH's documented minute window only.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from weather.units import round_half_up


# Modal routine minutes from typed IEM reports, 2026-06-01..2026-09-22.
# Historical research table only: NOT a publication/availability schedule.
# Rebuild full counts with tools/observation_clock_20260923.py; retain rare
# off-minute reports and SPECI risk separately. No serving module imports this.
STATION_ROUTINE_MINUTES = {
    "KATL": (52,), "KAUS": (53,), "KORD": (51,), "KDAL": (53,),
    "KBKF": (58,), "KHOU": (53,), "KLAX": (53,), "KMIA": (53,),
    "KLGA": (51,), "KSFO": (56,), "KSEA": (53,), "CYYZ": (0,),
}


@dataclass(frozen=True)
class Observation:
    valid: datetime
    temperature: float | None
    kind: str  # routine, special, unknown, minute

    def __post_init__(self):
        if self.valid.tzinfo is None or self.valid.utcoffset() is None:
            raise ValueError("observation timestamps must be timezone-aware")
        if self.temperature is not None and not math.isfinite(self.temperature):
            raise ValueError("temperature must be finite or absent")
        if self.kind not in {"routine", "special", "unknown", "minute"}:
            raise ValueError("unknown observation kind")


def hourly_rule_minute(station: str, minute: int) -> bool:
    """86a proxy: K stations :51..:59, others :56..:04, inclusively.

    WRH defines these windows by platform, not ICAO prefix. The configured
    mapping is a research approximation, not a verified platform lookup.
    """
    if not 0 <= minute < 60:
        raise ValueError("minute outside 0..59")
    return 51 <= minute <= 59 if station.upper().startswith("K") else minute >= 56 or minute <= 4


def clock_table(observations, timezone: str):
    """Counts, not availability times. SPECI deltas use the prior report <=90m.

    Change bins are native degrees: [0,1), [1,2), [2,4), [4,infinity).
    Counts include reports with missing temperature; those deltas are unknown.
    Caller supplies deduplicated reports from documented typed responses.
    """
    zone = ZoneInfo(timezone)
    rows = sorted(set(observations), key=lambda r: (r.valid, r.kind))
    routine = Counter()
    special_hour = Counter()
    change = Counter()
    joint = Counter()
    days = set()
    previous = None
    for row in rows:
        local = row.valid.astimezone(zone)
        days.add(local.date())
        if row.kind == "routine":
            routine[local.minute] += 1
        if row.kind == "special":
            special_hour[local.hour] += 1
            label = "unknown"
            if (previous is not None and row.temperature is not None
                    and previous.temperature is not None
                    and 0 < (row.valid - previous.valid).total_seconds() <= 5400):
                delta = abs(row.temperature - previous.temperature)
                label = "lt1" if delta < 1 else "1to2" if delta < 2 else "2to4" if delta < 4 else "ge4"
            change[label] += 1
            joint[(local.hour, label)] += 1
        previous = row
    return {
        "days": len(days), "routine_count": sum(routine.values()),
        "special_count": sum(special_hour.values()),
        "unknown_count": sum(r.kind == "unknown" for r in rows),
        "routine_minutes": dict(sorted(routine.items())),
        "special_hours": {h: special_hour[h] for h in range(24)},
        "special_changes": dict(sorted(change.items())),
        "special_hour_change": [{"hour": h, "change": c, "count": n}
                                for (h, c), n in sorted(joint.items())],
        "availability_lag_seconds": None,
    }


def day_grid(observations, station: str, timezone: str, local_date: date, *, hourly=False):
    """96 as-of points, never carrying an observation from a different date.

    ``decided`` compares half-up rounded whole degrees; ``decided_exact``
    compares the native observed temperatures. Missing prefixes stay missing.
    Coverage is diagnostic: all 24 civil hours represented, not physical truth.
    The grid is valid for ordinary 24h dates; refuse DST-transition days.
    """
    zone = ZoneInfo(timezone)
    from datetime import time, timedelta
    begin = datetime.combine(local_date, time(), zone)
    end = datetime.combine(local_date + timedelta(days=1), time(), zone)
    if begin.utcoffset() != end.utcoffset():
        raise ValueError("24h grid does not support DST-transition dates")
    samples = []
    for row in observations:
        local = row.valid.astimezone(zone)
        if local.date() != local_date or row.temperature is None:
            continue
        if hourly and not hourly_rule_minute(station, local.minute):
            continue
        minute = local.hour * 60 + local.minute + local.second / 60 + local.microsecond / 60000000
        samples.append((minute, row.temperature))
    samples.sort()
    final = max((value for _, value in samples), default=None)
    hours = len({int(minute // 60) for minute, _ in samples})
    summary = {"date": local_date.isoformat(), "samples": len(samples), "hours": hours,
               "complete_hours": hours == 24, "final_max": final,
               "final_degree": None if final is None else round_half_up(final)}
    grid = []
    idx, running = 0, None
    for minute in range(0, 1440, 15):
        while idx < len(samples) and samples[idx][0] <= minute:
            running = samples[idx][1] if running is None else max(running, samples[idx][1])
            idx += 1
        degree = None if running is None else round_half_up(running)
        grid.append({"minute": minute, "running_max": running, "running_degree": degree,
                     "decided": None if degree is None else int(degree == summary["final_degree"]),
                     "decided_exact": None if running is None else int(running == final),
                     "remaining_rise": None if degree is None else summary["final_degree"] - degree})
    return summary, grid


def band_dead(running_degree: int | None, upper: int | None):
    """Observed deadness is known (0/1), not an estimated future event.

    The upper endpoint is inclusive. None means an open upper tail. Missing
    observations stay unknown even for that tail.
    """
    if running_degree is None:
        return None
    return int(upper is not None and running_degree > upper)


def historical_dead_probability(running_histogram, upper):
    """Across-day P(running whole-degree maximum > inclusive band upper)."""
    n = sum(running_histogram.values())
    if n == 0:
        return None
    return sum(count for value, count in running_histogram.items()
               if upper is not None and int(value) > upper) / n


@dataclass(frozen=True)
class RemainingRiseEstimator:
    """Station/definition-specific empirical remaining-rise distribution.

    Fit only complete observation days strictly before ``before``. No future
    fallback, temperature from tomorrow, or cross-station borrowing. At least
    ``minimum_days`` eligible days per quarter-hour are required. The simple
    estimator is intentionally unconditional on current weather or season.
    """
    before: date
    rises: dict[int, tuple[int, ...]]
    minimum_days: int = 20

    @classmethod
    def fit(cls, days, *, before: date, minimum_days=20):
        if minimum_days < 1:
            raise ValueError("minimum_days must be positive")
        rises = defaultdict(list)
        seen = set()
        for summary, grid in days:
            day = date.fromisoformat(summary["date"])
            if day >= before:
                raise ValueError("training date is not before the holdout boundary")
            if day in seen:
                raise ValueError("duplicate station training date")
            seen.add(day)
            if not summary["complete_hours"]:
                continue
            for row in grid:
                if row["remaining_rise"] is not None:
                    rises[row["minute"]].append(row["remaining_rise"])
        return cls(before, {m: tuple(sorted(values)) for m, values in rises.items()}, minimum_days)

    def predict(self, minute: int, running_degree: int | None, *, target_date: date,
                band_upper: int | None = None):
        if target_date < self.before:
            raise ValueError("prediction is not held out")
        if minute not in range(0, 1440, 15):
            raise ValueError("prediction minute must be on the 15-minute grid")
        values = self.rises.get(minute, ())
        if running_degree is None or len(values) < self.minimum_days:
            return {"n": len(values), "p_decided": None, "p_final_above": None,
                    "dead": band_dead(running_degree, band_upper)}
        return {"n": len(values), "p_decided": bisect_right(values, 0) / len(values),
                "p_final_above": (0.0 if band_upper is None else
                    1 - bisect_right(values, band_upper - running_degree) / len(values)),
                "dead": band_dead(running_degree, band_upper)}
