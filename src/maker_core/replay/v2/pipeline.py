"""The v2 scored pipeline's passes: base passes in lockstep, then matched-clock rounds in lockstep.

Base passes: the four policies under both fill bounds (eight engines) on one parse per day. Then the
frozen exposure-matched clock (``maker_core.replay.baselines.matched_clock``) for each bound: the same
calendar-prefix rule, tolerance, bisection, attempt cap and best-trial choice; each round's trials for
both bounds share one parse. Engines are interchangeable: ``EngineV2`` for scored runs, the reference
schedule for differential tests.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal

from maker_core.evidence.journal import digest
from maker_core.replay.fill_model import BOUNDS
from maker_core.replay.v2.engine import EngineV2
from maker_core.replay.v2.lockstep import drive, run_plan
from maker_core.replay.v2.score import BandDayScorer, Books

D = Decimal
BASE_POLICIES = ("informed-v0", "no_quote", "blind_re1", "clock_only")
MAX_CLOCK_ROUNDS = 12


@dataclass
class Pass:
    engine: object
    scorer: BandDayScorer
    rows: list | None = None

    def band_days(self, books, markets):
        if self.rows is None:
            self.rows = self.scorer.band_days(self.engine.settlements, books, markets)
        return self.rows


def fraction(rows):
    covered = sum((r["covered_seconds"] for r in rows), D(0))
    pulled = sum((r["pulled_seconds"] for r in rows), D(0))
    return (pulled / covered if covered else None), covered


def clock_windows(plan, value):
    windows = []
    for day in plan.days:
        for c in day.conditions:
            for start, end in day.windows.get(c.condition_id, ()):
                seconds = int((end - start).total_seconds() * float(value))
                if seconds:
                    windows.append((c.condition_id, start, start + timedelta(seconds=seconds)))
    return tuple(windows)


class _Bisection:
    """One bound's frozen bisection, advanced one trial at a time so bounds can share parses."""

    def __init__(self, target, covered, base_actual, base):
        self.target, self.attempts = target, 1
        self.done = target is None or base_actual is None
        self.low, self.high = D(0), D(1)
        self.tolerance = None if self.done else min(D(1), D(60) / covered)
        self.best = (None if self.done else abs(base_actual - target), base, base_actual, D(0))
        self.rounds = 0
        self.pending = None

    def next_fraction(self):
        if self.done or self.rounds >= MAX_CLOCK_ROUNDS or self.best[0] <= self.tolerance:
            self.done = True
            return None
        self.rounds += 1
        self.pending = (self.low + self.high) / 2
        return self.pending

    def observe(self, trial, got):
        value, self.pending = self.pending, None
        self.attempts += 1
        if got is None:
            self.done = True
            return
        if abs(got - self.target) < self.best[0]:
            self.best = (abs(got - self.target), trial, got, value)
        if got < self.target:
            self.low = value
        else:
            self.high = value

    def summary(self, windows_count):
        error, _, actual, value = self.best
        if self.tolerance is None:
            return dict(status="UNMATCHED", target=self.target, actual=actual, tolerance=None, attempts=1)
        return dict(status="MATCHED" if error <= self.tolerance else "UNMATCHED", target=self.target,
                    actual=actual, tolerance=self.tolerance, absolute_error=error, attempts=self.attempts,
                    calendar_prefix_fraction=value, selected_windows=windows_count,
                    interpretation="ex-post exposure-matched clock control; no return optimization")


@dataclass
class Run:
    plan: object
    books: Books
    passes: dict  # bound -> policy -> Pass (clock_only is the selected trial)
    matches: dict  # bound -> matched-clock summary
    markets: dict
    trials: list  # (bound, round, calendar fraction, Pass); passes kept only when ``config.keep``


def run_passes(sources, config, *, time_zones, engine=EngineV2, progress=lambda *_: None) -> Run:
    """Every pass of one scored run: eight base engines on one parse, then lockstep matched-clock rounds.

    ``time_zones`` (market_id -> IANA zone) is required: it drives the local-midnight refresh (``lockstep.drive``).
    A scored run takes it from ``execution_manifest.market_time_zones`` (the validated universe inventory).
    """
    sources = sorted(sources, key=lambda s: s.plan.day)
    plan = run_plan(sources)
    markets = {c.condition_id: c.market_id for day in plan.days for c in day.conditions}
    books = Books()
    passes = {}
    engines = []
    for bound in BOUNDS:
        passes[bound] = {}
        for policy in BASE_POLICIES:
            cfg = replace(config, policy=policy, fill_bound=bound, clock_pulls=())
            scorer = BandDayScorer(policy, bound, pull_runs=policy in ("informed-v0", "clock_only"))
            passes[bound][policy] = Pass(engine(cfg, plan, sink=scorer), scorer)
            engines.append(passes[bound][policy].engine)
    drive(sources, engines, observers=(books,), time_zones=time_zones)
    progress("base", len(engines))
    bisections, log = {}, []
    for bound in BOUNDS:
        target, covered = fraction(passes[bound]["informed-v0"].band_days(books, markets))
        base = passes[bound]["clock_only"]
        actual, _ = fraction(base.band_days(books, markets))
        bisections[bound] = _Bisection(target, covered, actual, base)
    while True:
        trials = {}
        for bound, state in bisections.items():
            value = state.next_fraction()
            if value is None:
                continue
            cfg = replace(config, policy="clock_only", fill_bound=bound, clock_pulls=clock_windows(plan, value))
            scorer = BandDayScorer("clock_only", bound, pull_runs=True)
            trials[bound] = Pass(engine(cfg, plan, sink=scorer), scorer)
        if not trials:
            break
        drive(sources, [t.engine for t in trials.values()], time_zones=time_zones)
        progress("clock_round", len(trials))
        for bound, trial in trials.items():
            got, _ = fraction(trial.band_days(books, markets))
            state = bisections[bound]
            log.append((bound, state.rounds, state.pending, trial if config.keep else trial.engine.summary()))
            state.observe(trial, got)
    matches = {}
    for bound, state in bisections.items():
        best = state.best[1]
        passes[bound]["clock_only"] = best
        matches[bound] = state.summary(len(best.engine.config.clock_pulls))
        matches[bound]["selected_windows_sha256"] = _windows_digest(best.engine.config.clock_pulls)
    return Run(plan, books, passes, matches, markets, log)


def _windows_digest(windows):
    return digest([list(w) for w in windows])
