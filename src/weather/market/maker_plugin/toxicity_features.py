"""Weather feature adapter for the COUNTERFACTUAL toxicity table (item 330 build 2).

Pure: no file, provider, network or environment reads. Callers pass every input
explicitly and receive a plain mapping that ``maker_core.quoting.fill_cost.FillContext.from_mapping``
accepts (the plugin may not import the quoting kernel, so it returns data, not the type).

Point in time: the context instant ``at_utc`` is the fill (or minute start).
Model-cycle availability times after ``at_utc`` are not yet known and are ignored;
a decided probability or book timestamped after ``at_utc`` is a leak and raises, and
so is a print at or after ``at_utc`` (the print at the fill instant is the fill itself).

Market prices never enter the information clock or the decided probability: the
book and prints contribute sizes and timing only (imbalance, depth, print size,
burst, cross-band sweep). Dated inputs are refused inside the evidence embargo.
``close_utc`` is a schedule, not a read, so it is not embargo-checked. The embargo
reduces instants to their UTC date, so a 2026-09-29 local evening (2026-09-30 UTC)
is already refused; that is conservative and intended.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Iterable, Mapping

from maker_core.contracts import utc_time
from maker_core.contracts.evidence_embargo import refuse
from weather.market.maker_plugin.clock import STATION_ROUTINE_MINUTES

BURST_WINDOW_S = 1.0   # Mirrors maker_core.quoting.fill_cost.TableSpec defaults.
SWEEP_WINDOW_S = 60.0


class FeatureAfterInstant(ValueError):
    """A feature input is timestamped after the context instant."""


def _time(value) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    utc_time(result)
    return result


def _size(value) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("size must be finite and non-negative")
    return number


def minutes_from_scheduled_print(station: str, at_utc: datetime) -> float:
    """Signed minutes from the nearest routine METAR minute (negative before the print)."""
    minutes = STATION_ROUTINE_MINUTES.get(station)
    if not minutes:
        raise ValueError(f"no routine observation minute for station {station}")
    hour = at_utc.replace(minute=0, second=0, microsecond=0)
    candidates = [hour + timedelta(hours=h, minutes=m) for h in (-1, 0, 1) for m in minutes]
    deltas = [(at_utc - c).total_seconds() / 60 for c in candidates]
    return min(deltas, key=lambda d: (abs(d), d))


def weather_fill_context(*, at_utc, station: str, maker_side: str, horizon_days: int, close_utc,
                         band: str, nbm_available_utc: Iterable = (), decided_probability: float | None = None,
                         decided_at_utc=None, book: Mapping | None = None, prints: Iterable[Mapping] = (),
                         burst_window_s: float = BURST_WINDOW_S, sweep_window_s: float = SWEEP_WINDOW_S) -> dict:
    """Return a ``FillContext`` mapping for one band at ``at_utc``.

    ``book``: ``{"as_of_utc", "yes_bids": [(price, size)], "yes_asks": [(price, size)]}``.
    ``prints``: ``[{"at_utc", "band", "size", ...}]`` for every band of the same event.
    Prices in ``book`` and ``prints`` are ignored; only sizes and times are read.
    """
    at = _time(at_utc)
    close = _time(close_utc)
    nbm = [_time(v) for v in nbm_available_utc]
    decided_at = None if decided_at_utc is None else _time(decided_at_utc)
    book_at = None if book is None else _time(book["as_of_utc"])
    trades = [(_time(p["at_utc"]), str(p["band"]), _size(p["size"])) for p in prints]
    # Absent optional inputs are not dates; every supplied one is checked.
    optional = (t for t in (decided_at, book_at) if t is not None)
    refuse(at, *nbm, *optional, *(t for t, _, _ in trades), purpose="read")
    if close < at:
        raise ValueError("context instant after market close")
    if decided_probability is not None and decided_at is None:
        raise ValueError("a decided probability needs its observation time")
    for name, when in (("decided", decided_at), ("book", book_at)):
        if when is not None and when > at:
            raise FeatureAfterInstant(f"{name} timestamped after the context instant")
    if any(t >= at for t, _, _ in trades):
        raise FeatureAfterInstant("print at or after the context instant")

    known_cycles = [t for t in nbm if t <= at]   # Later availability is not yet known: ignore, never leak.
    latest_cycle = max(known_cycles) if known_cycles else None
    feature_times = {"info_clock": latest_cycle or at}
    if decided_at is not None:
        feature_times["decided"] = decided_at

    imbalance, depth = None, 0.0
    if book is not None:
        bid = sum(_size(s) for _, s in book.get("yes_bids", ()))
        ask = sum(_size(s) for _, s in book.get("yes_asks", ()))
        depth = bid + ask
        imbalance = (bid - ask) / depth if depth else None
        feature_times["book"] = book_at

    sweep_from = at - timedelta(seconds=sweep_window_s)
    burst_from = at - timedelta(seconds=burst_window_s)
    recent = [(t, b, s) for t, b, s in trades if t >= sweep_from]
    own = sorted((t, s) for t, b, s in recent if b == band)
    if trades:
        feature_times["prints"] = max(t for t, _, _ in trades)

    return {
        "at_utc": at.isoformat(),
        "maker_side": maker_side,
        "horizon_days": horizon_days,
        "minutes_to_close": (close - at).total_seconds() / 60,
        "minutes_from_scheduled_print": minutes_from_scheduled_print(station, at),
        "minutes_since_model_cycle": None if latest_cycle is None else (at - latest_cycle).total_seconds() / 60,
        "decided_probability": decided_probability,
        "book_imbalance": imbalance,
        "depth_shares": depth,
        "last_print_size": own[-1][1] if own else 0.0,
        "burst_prints": sum(1 for t, _ in own if t >= burst_from),
        "sweep_bands": len({b for _, b, _ in recent}),
        "feature_times": {k: v.isoformat() for k, v in sorted(feature_times.items())},
    }
