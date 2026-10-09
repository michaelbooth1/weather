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
    binding: dict | None = None  # ``run_binding``: set only by ``run_passes``; ``report.build_report`` requires it


RUN_BINDING_FORMAT = "maker_core.replay.v2.run_binding.v0.1"
CALLER_ZONE_MAP = dict(builder="caller", registry_checked=False)


def _zone_pairs(time_zones):
    return [[market, zone] for market, zone in sorted(dict(time_zones).items())]


def run_binding(time_zones) -> dict:
    """The run digest's inputs beyond the bundles (owner T1(a)/T2(a), 2026-10-09), with their SHA-256.

    - ``day_roll_refresh``: always true here; ``day_roll.NO_REFRESH`` is refused (``day_roll_refresh_required``);
    - ``time_zones`` and ``time_zones_sha256``: the exact market_id -> zone map the day roll used;
    - ``time_zones_source``: ``RegisteredZones.source`` from ``execution_manifest.market_time_zones`` (builder,
      ``registry_checked``, inventory and registry digests), or ``builder="caller"`` for any other mapping;
    - ``tzdata``: ``bundle.tzdata_binding`` of those zones (pinned version, IANA release, zone-file shas); a
      tzdata other than ``bundle.TZDATA_VERSION`` refuses ``tzdata_version_unpinned``.

    ``sha256`` is the digest of every other field. It binds no decision: the decision and P&L digests are
    unchanged by it."""
    from maker_core.replay.bundle import BundleError, RegisteredZones, tzdata_binding
    from maker_core.replay.v2.day_roll import NO_REFRESH
    if time_zones is NO_REFRESH:
        raise BundleError("day_roll_refresh_required")
    pairs = _zone_pairs(time_zones)
    source = dict(time_zones.source) if isinstance(time_zones, RegisteredZones) else dict(CALLER_ZONE_MAP)
    body = dict(format=RUN_BINDING_FORMAT, day_roll_refresh=True, time_zones=dict(pairs),
                time_zones_sha256=digest(pairs), time_zones_source=source,
                tzdata=tzdata_binding(zone for _, zone in pairs))
    return dict(body, sha256=digest(body))


def verify_run_binding(run, *, scored) -> dict:
    """Refuse a run whose binding is missing, altered, refresh-off or, when ``scored``, not from the registry.

    ``scored`` is true for every report that is not FIXTURE_ONLY: such a run must come from ``run_passes`` with
    a ``market_time_zones`` map (owner T2(a)); a fixture run may bind a hand-made map (``builder="caller"``)."""
    from maker_core.replay.bundle import TZDATA_VERSION, BundleError
    binding = getattr(run, "binding", None)
    if not isinstance(binding, dict) or binding.get("format") != RUN_BINDING_FORMAT:
        raise BundleError("run_binding_required")
    if binding.get("sha256") != digest({k: v for k, v in binding.items() if k != "sha256"}):
        raise BundleError("run_binding_digest_mismatch")
    if binding["time_zones_sha256"] != digest(_zone_pairs(binding["time_zones"])):
        raise BundleError("run_binding_digest_mismatch")
    if binding["day_roll_refresh"] is not True:
        raise BundleError("day_roll_refresh_required")
    if binding["tzdata"].get("version") != TZDATA_VERSION:
        raise BundleError("tzdata_version_unpinned")
    if not set(run.markets.values()) <= set(binding["time_zones"]):
        raise BundleError("market_time_zone_unknown")
    if scored and binding["time_zones_source"].get("registry_checked") is not True:
        raise BundleError("run_binding_unregistered_zone_map")
    return binding


def run_passes(sources, config, *, time_zones, engine=EngineV2, progress=lambda *_: None) -> Run:
    """Every pass of one scored run: eight base engines on one parse, then lockstep matched-clock rounds.

    ``time_zones`` (market_id -> IANA zone) is required: it drives the local-midnight refresh (``lockstep.drive``).
    A scored run takes it from ``execution_manifest.market_time_zones`` (the validated universe inventory) and
    may not turn the refresh off: ``day_roll.NO_REFRESH`` is refused here (``day_roll_refresh_required``).

    Binding (owner T2(a), 2026-10-09): before any work, ``run_binding`` records the refresh flag, the zone map, its
    sha and its source, and the pinned tzdata (T1(a)) into ``Run.binding``; ``report.build_report`` refuses a run
    without it, and a non-fixture report refuses a map not built by ``market_time_zones(..., registered=)``. So a
    run that bypasses this function (``lockstep.drive`` directly) or passes a hand-made map produces no scored
    report. For a ``maker_replay_universe.universe()``-built inventory the registry cross-check is close to a
    tautology (both sides read ``BUILTIN_SPECS``): it catches a tampered or hand-built inventory, not a wrong
    registry entry.
    """
    binding = run_binding(time_zones)
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
    return Run(plan, books, passes, matches, markets, log, binding)


def _windows_digest(windows):
    return digest([list(w) for w in windows])
