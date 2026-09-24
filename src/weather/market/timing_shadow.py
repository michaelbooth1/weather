"""Pure observation-clock shadow output. No I/O, serving or trading authority.

Decidedness means the archived running maximum remains on its current side
of the nearest band boundary, under 89b's empirical remaining-rise estimator.
It is neither a venue settlement probability nor an own-fill risk estimate.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from weather.market.observation_clock import RemainingRiseEstimator, STATION_ROUTINE_MINUTES
from weather.units import parse_temperature_band


@dataclass(frozen=True)
class ShadowBand:
    condition: str
    target_date: date
    unit: str
    lower: int | None
    upper: int | None

    def __post_init__(self):
        if self.unit not in {"C", "F"}:
            raise ValueError("native band unit must be C or F")
        for value in (self.lower, self.upper):
            if value is not None and type(value) is not int:
                raise ValueError("band endpoints must be whole degrees")
        if self.lower is None and self.upper is None:
            raise ValueError("band must have a boundary")
        if self.lower is not None and self.upper is not None and self.upper < self.lower:
            raise ValueError("inverted band")

    @classmethod
    def from_label(cls, condition, target_date, label, unit):
        parsed = parse_temperature_band(label, expected_unit=unit)
        if parsed is None:
            raise ValueError("unparseable or wrong-unit band")
        return cls(condition, target_date, unit,
                   None if parsed.kind == 'lte' else parsed.value,
                   None if parsed.kind == 'gte' else parsed.value_hi)


def routine_clock(station, now, *, routine_minutes=None):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must be timezone-aware")
    minutes = STATION_ROUTINE_MINUTES.get(station.upper(), ()) if routine_minutes is None else tuple(routine_minutes)
    if any(type(m) is not int or not 0 <= m < 60 for m in minutes):
        raise ValueError("routine minutes must be integers in 0..59")
    if not minutes:
        return {"minutes_since_metar": None, "minutes_to_metar": None}
    phase = now.minute + now.second / 60 + now.microsecond / 60_000_000
    return {"minutes_since_metar": min((phase-m) % 60 for m in minutes),
            "minutes_to_metar": min((m-phase) % 60 for m in minutes)}


def publication_clock(now, publications):
    """Distances to supplied object-time proxies; future entries are hindsight."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("clock must be timezone-aware")
    if any(t.tzinfo is None or t.utcoffset() is None for t in publications):
        raise ValueError("publication timestamps must be timezone-aware")
    times = sorted(t.timestamp() for t in publications)
    t = now.timestamp()
    index = bisect_right(times, t)
    previous = times[index-1] if index else None
    following = t if previous == t else times[index] if index < len(times) else None
    return {"minutes_since": None if previous is None else (t-previous)/60,
            "minutes_to": None if following is None else (following-t)/60}


def band_risk(band, estimator, *, minute, running_degree, local_date):
    result = {"p_band_decided": None, "p_high_decided": None, "training_days": 0,
              "observed_locked": None, "current_yes": None}
    if local_date != band.target_date or running_degree is None:
        return result
    if type(running_degree) is not int or not 0 <= minute < 1440:
        raise ValueError("whole-degree running maximum and valid minute required")
    if local_date < estimator.before:
        raise ValueError("training reaches the prediction date")
    quarter = (minute // 15) * 15
    values = estimator.rises.get(quarter, ())
    inside = ((band.lower is None or running_degree >= band.lower)
              and (band.upper is None or running_degree <= band.upper))
    locked = ((band.upper is not None and running_degree > band.upper)
              or (band.upper is None and running_degree >= band.lower))
    result.update(training_days=len(values), observed_locked=locked, current_yes=inside)
    if locked:
        result['p_band_decided'] = 1.0
    if len(values) < estimator.minimum_days:
        return result
    result['p_high_decided'] = bisect_right(values, 0) / len(values)
    if not locked:
        boundary = band.upper if inside else band.lower - 1
        result['p_band_decided'] = bisect_right(values, boundary-running_degree) / len(values)
    return result


def timing_row(station, now, band, estimator, *, station_timezone, running_degree,
               observation_cutoff, publications=None, routine_minutes=None):
    """Emit one shadow row from caller-supplied public/captured inputs.

    The caller must enforce source age and native units. Cutoff is the latest
    observation valid-time admitted, never a claim of actual public receipt.
    """
    clocks = routine_clock(station, now, routine_minutes=routine_minutes)
    if observation_cutoff.tzinfo is None or observation_cutoff.utcoffset() is None or observation_cutoff > now:
        raise ValueError("observation cutoff must be aware and no later than now")
    local = now.astimezone(ZoneInfo(station_timezone))
    cutoff = observation_cutoff.astimezone(ZoneInfo(station_timezone))
    risk = band_risk(band, estimator, minute=cutoff.hour*60+cutoff.minute,
                     running_degree=running_degree if cutoff.date() == local.date() else None,
                     local_date=local.date())
    utc = now.astimezone(timezone.utc)
    cycles = [utc.replace(hour=h, minute=0, second=0, microsecond=0) + timedelta(days=d)
              for d in (-1, 0, 1) for h in (1, 7, 13, 19)]
    model_clocks = {'nbm_cycle': publication_clock(now, cycles)}
    model_clocks.update({model: publication_clock(now, times) for model, times in (publications or {}).items()})
    return {'timestamp_utc': utc.isoformat(), 'station': station, 'condition': band.condition,
            'target_date': band.target_date.isoformat(), 'day_ahead': (band.target_date-local.date()).days,
            'native_unit': band.unit, 'observation_cutoff_utc': observation_cutoff.astimezone(timezone.utc).isoformat(),
            **clocks, **risk, 'model_clocks': model_clocks,
            'mode': 'shadow_only', 'counts_toward_trading_readiness': False}
