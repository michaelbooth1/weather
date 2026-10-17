"""Seeded synthetic COUNTERFACTUAL quote minutes and fills with planted regimes.

Stdlib ``random`` only. Planted truth (probability units per share):

- flow: calm minutes fill rarely and mark out benign (+0.01); burst and sweep
  minutes fill often and mark out toxic (-0.04);
- clock: minutes inside the scheduled-print window add a further -0.02.

Every record is fictional and dated on or before 2026-09-29.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
import random

from maker_core.quoting.fill_cost import FillContext
from maker_core.replay.toxicity import CounterfactualFill, Mark, QuoteMinute

HAZARD = {"calm": 0.03, "burst": 0.25, "sweep": 0.35}
MARKOUT = {"calm": 0.01, "burst": -0.04, "sweep": -0.04}
PRINT_WINDOW_MARKOUT = -0.02
PRICE = 0.5


def _context(rng, at, flow, print_window, side):
    return FillContext(
        at_utc=at, maker_side=side, horizon_days=1, minutes_to_close=600.0,
        minutes_from_scheduled_print=rng.uniform(-2, 8) if print_window else rng.uniform(15, 40),
        minutes_since_model_cycle=120.0, decided_probability=round(rng.random(), 6),
        book_imbalance=round(rng.uniform(-1, 1), 6), depth_shares=round(rng.uniform(20, 200), 3),
        last_print_size=round(rng.uniform(1, 150), 3),
        burst_prints=5 if flow == "burst" else rng.choice((0, 1)),
        sweep_bands=3 if flow == "sweep" else 1,
        feature_times={"prints": at - timedelta(seconds=2), "book": at - timedelta(seconds=1)})


def synthetic_records(*, dates, markets, minutes_per_cell, seed, first=date(2026, 9, 1), noise=0.01):
    rng = random.Random(seed)
    minutes, fills = [], []
    for d in range(dates):
        day = first + timedelta(days=d)
        for m in range(markets):
            market = f"mkt-{m:02d}"
            condition = f"cond-{m:02d}-{day.isoformat()}"
            for i in range(minutes_per_cell):
                start = datetime.combine(day, time(15, 0), tzinfo=timezone.utc) + timedelta(minutes=i)
                flow = rng.choices(("calm", "burst", "sweep"), weights=(70, 15, 15))[0]
                print_window = rng.random() < 0.25
                side = rng.choice(("YES", "NO"))
                context = _context(rng, start, flow, print_window, side)
                minutes.append(QuoteMinute(condition, market, day, start, context))
                if rng.random() >= HAZARD[flow]:
                    continue
                fill_at = start + timedelta(seconds=20)
                delta = MARKOUT[flow] + (PRINT_WINDOW_MARKOUT if print_window else 0.0)
                marks = {}
                for h, seconds in (("1m", 60), ("5m", 300), ("30m", 1800)):
                    token = PRICE + delta + rng.gauss(0, noise)
                    mid = token if side == "YES" else 1 - token
                    marks[h] = Mark(fill_at + timedelta(seconds=seconds + 5), round(mid, 6))
                token = min(1.0, max(0.0, PRICE + 1.5 * delta + rng.gauss(0, noise)))
                settlement = token if side == "YES" else 1 - token
                fills.append(CounterfactualFill(
                    f"fill-{len(fills):05d}", condition, market, day, start, fill_at, side, PRICE,
                    float(rng.choice((10, 20, 30))), replace(context, at_utc=fill_at), marks,
                    round(settlement, 6), fill_at + timedelta(hours=6)))
    return minutes, fills
