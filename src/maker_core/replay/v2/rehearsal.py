"""Score-free calibration rehearsal output contract (registration draft §9; W6, U2) — whitelist and guards.

A rehearsal runs the full v2 scored pipeline on a v0.2 night-format calibration export (2026-09-27..29 only) and
keeps **only** the §9 outputs: input bytes, records by kind, engine wakes, decisions, span runs, scored-report
bytes, sidecar bytes, runtime, peak memory above the pre-input baseline, the §11 reachability fields, and the
equivalence and determinism hashes. No fill, P&L, reward, markout, removed-move count or contrast is kept or shown.

This module holds the parts of that contract that do not depend on the pipeline wiring:

- ``calibration_day(path)``: the date a bundle path names, refused before a byte is read unless it is a
  calibration date (``rehearsal_restricted_to_calibration_dates``), as ``pack_cli.rehearse`` does for v1;
- ``whitelisted(doc)``: walks a rehearsal document against ``schema()``, every path and the type of every leaf
  (CONSOLIDATED row 16, binding: DECISION_LOG 2026-10-15), and refuses any key outside it, any leaf of the wrong
  type and any data key of the wrong shape (``rehearsal_whitelist:<path>``), so a smuggled score key or value fails
  closed; every reader re-checks it, and the CLI re-checks what it writes and prints (``rehearse_cli.guarded``);
- ``environment()``: the source/environment digest and the hash seed in force, which E7 compares (row 17).

and the end-to-end rehearsal (U2 part 2):

- ``rehearse(paths, inventory, ...)``: path names checked, bundles opened under one shared ``RunBudget``, the §4
  rule applied to the calibration dates (``intervals.sources(..., panel="calibration")``), then the whole scored
  pipeline (``pipeline.run_passes``: eight base passes and every matched-clock round; ``report.build_report``: the
  bootstrap, the report and the sidecar, kept as bytes and hash only). Returns the whitelisted document.
  Per-pass rows (policy x fill bound), matched-clock rounds and match status, and the sidecar record count are
  not kept: they are outside the §9 list (Defender D3.1), and differences across fill bounds are fill-driven.
  Passes enter only through the §9 maxima in ``measured`` and the ``decision_sha256`` digest.
- ``ceiling_input(doc)``: the ``measured`` block projected to ``ceilings.MEASURED`` for ``ceilings.derive``.

Report path (pending review, T1 report decision 3): a scored report needs an enrolled execution manifest, which
cannot exist before signature. The rehearsal therefore composes the report from the same declared sources
relabelled ``synthetic`` (``report_status`` FIXTURE_ONLY, recorded in the document). Every pass, round, bootstrap
replicate and sidecar row is the same work; the FIXTURE_ONLY report omits only ``pack_check`` (a fixed set of
digests) and ``pre_registration_sha256``, so ``report_bytes`` is short of the scored report by that fixed block.

Measurement: the run clock starts after the path check and stops after the report bytes are taken; the
records-by-kind count rides the base drive (the first read of each day), so it adds no pass. Memory is the
process peak (``v2.host.process_memory``, row 13) above the peak taken before the first input byte, so one rehearsal
runs per fresh process, as v1's did. The §11 block of a carried rehearsal (U3, ``reachability``) is read after
that: its decision tee runs inside the measured pipeline, its policy-free opportunity count does not.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
import hashlib
from pathlib import Path
import math
import re
import time

from maker_core.evidence.journal import digest
from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES
from maker_core.replay.v2.threads import PINNED_VARIABLES

FORMAT = "maker_core.replay.v2.rehearsal.v0.1"
MODES = ("per_date", "carried")
HAZARD_VARIANTS = ("max_m", "r1_per_city")
INTERPRETATION = "Resource counts, reachability fields and hashes only; no score, fill, P&L, reward or contrast."

MEASURED_KEYS = ("input_bytes", "records", "records_by_kind", "wakes", "decisions", "span_runs", "report_bytes",
                 "sidecar_bytes", "runtime_seconds", "peak_memory_above_baseline_bytes",
                 "baseline_memory_bytes")
# The §11 reachability block (carried mode only): counts and fractions, never a cell or a score.
REACHABILITY_KEYS = ("status", "f_cal", "screen_pass_rate", "decision_reasons", "quoted_fraction", "n_cal", "l_cal",
                     "expected_clock_removed")

# Keys that may never appear anywhere in a rehearsal document, even under a free-form leaf.
FORBIDDEN = frozenset({"fills", "final_cash", "pnl", "reward", "rewards", "markout", "markouts", "contrast",
                       "removed_moves", "score", "scores", "cells", "band_days", "registered_decision", "target",
                       "actual", "calendar_prefix_fraction", "exclusions", "exclusions_sha256"})
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
REPORT_STATUSES = ("FIXTURE_ONLY", "PRE_REGISTERED_REPLAY")
THREAD_PINS = PINNED_VARIABLES  # the four BLAS/OpenMP pins ``threads.py`` checks
HASH_PROBE = "maker_core.replay.v2.rehearsal hash seed probe"


def calibration_day(path) -> date:
    """The date an exporter path names (``<root>/<day>/bundle`` or a dated leaf); refused unless calibration.

    Reads only the path text, so a quote-panel date is refused before any byte of it is opened."""
    path = Path(path)
    name = path.name if _DATE.fullmatch(path.name) else path.parent.name
    allowed = {d.isoformat(): d for d in CALIBRATION_DATES}
    if name not in allowed:
        raise BundleError("rehearsal_restricted_to_calibration_dates")
    return allowed[name]


def check_mode(mode, days):
    """``per_date`` takes exactly one calibration date; ``carried`` exactly the three, in order (reg §9)."""
    if mode not in MODES:
        raise BundleError("rehearsal_mode_invalid")
    days = list(days)
    if mode == "per_date" and len(days) != 1:
        raise BundleError("rehearsal_per_date_requires_one_date")
    if mode == "carried" and days != list(CALIBRATION_DATES):
        raise BundleError("rehearsal_carried_requires_the_three_calibration_dates")
    return days


class MapOf:
    """A mapping whose keys are data (kinds, dates, file names, ``ACTION:REASON``): each key must fullmatch
    ``key`` and each value must satisfy ``value``; at most ``limit`` entries."""

    def __init__(self, key, value, limit):
        self.key, self.value, self.limit = re.compile(key), value, limit


class ListOf:
    """A list whose items each satisfy ``item``; at most ``limit`` items."""

    def __init__(self, item, limit):
        self.item, self.limit = item, limit


_HEX64 = re.compile(r"[0-9a-f]{64}")
_DECIMAL = re.compile(r"-?[0-9]{1,30}(\.[0-9]{1,40})?(E[+-]?[0-9]{1,4})?")
_VERSION = re.compile(r"[0-9A-Za-z.+_-]{1,40}")
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})")
_COUNT_LIMIT = 2**63


def _count(v):
    return type(v) is int and 0 <= v < _COUNT_LIMIT


def _seconds(v):
    return type(v) in (int, float) and math.isfinite(v) and v >= 0


def _unit(v):
    return _seconds(v) and v <= 1


def _hex64(v):
    return isinstance(v, str) and _HEX64.fullmatch(v) is not None


def _decimal(v):
    return isinstance(v, str) and _DECIMAL.fullmatch(v) is not None


def _instant(v):
    return isinstance(v, str) and _TIME.fullmatch(v) is not None


def _signed64(v):
    return type(v) is int and -(2**63) <= v < 2**63


def _version(v):
    return isinstance(v, str) and _VERSION.fullmatch(v) is not None


def _seed(v):
    """``PYTHONHASHSEED`` as Python accepts it (0..4294967295), or ``random``."""
    return isinstance(v, str) and (v == "random" or (v.isdigit() and len(v) <= 10 and int(v) < 2**32))


def _one_of(*allowed):
    return lambda v: isinstance(v, str) and v in allowed


def _nullable(check):
    return lambda v: v is None or (check(v) if callable(check) else _conforms(v, check))


def _conforms(value, spec):
    try:
        _walk(value, spec, "")
    except BundleError:
        return False
    return True


_SCHEMA = []


def schema():
    """The rehearsal document schema: every path and the type of every leaf (CONSOLIDATED row 16, binding:
    DECISION_LOG 2026-10-15). A key outside it, a leaf of the wrong type, a structure where a leaf belongs or a data
    key of the wrong shape refuses at its path, so a value cannot ride under an allowed name in another shape."""
    if not _SCHEMA:
        from maker_core.replay.bundle import KINDS
        from maker_core.replay.v2 import reachability
        dates = [d.isoformat() for d in CALIBRATION_DATES]
        date_key = "|".join(re.escape(d) for d in dates)
        count = _count
        _SCHEMA.append({
            "format": _one_of(FORMAT), "mode": _one_of(*MODES), "dates": ListOf(_one_of(*dates), len(dates)),
            "hazard_variant": _one_of(*HAZARD_VARIANTS), "calibration_sha256": _hex64,
            "after_fail_sha256": _nullable(_hex64), "measured_at": _instant,
            "interpretation": _one_of(INTERPRETATION), "report_status": _one_of(*REPORT_STATUSES),
            "replicates": count, "hazard_per_minute": _unit, "hazard_map_sha256": _nullable(_hex64),
            "inventory_sha256": _hex64,
            "pull_candidates": count,  # carried mode only: E6's policy-free pull-candidate count (not a §11 field)
            "measured": {**{k: count for k in MEASURED_KEYS}, "runtime_seconds": _seconds,
                         "records_by_kind": MapOf("|".join(sorted(KINDS)), count, len(KINDS))},
            "hashes": {"input_hashes": MapOf(date_key, MapOf(r"bundle\.json|[a-zA-Z0-9_-]{1,64}\.jsonl(\.gz)?",
                                                             _hex64, 64), len(dates)),
                       "report_sha256": _hex64, "sidecar_sha256": _hex64, "decision_sha256": _hex64},
            "reachability": {
                "status": _one_of("PASS", "FAIL", "UNIDENTIFIED"), "f_cal": _nullable(_decimal),
                "screen_pass_rate": {"reached": count, "passed": count, "rate": _nullable(_decimal),
                                     "reading": _one_of(reachability.SCREEN_READING)},
                "decision_reasons": MapOf(r"[A-Z][A-Z0-9_]{0,63}:[A-Z][A-Z0-9_]{0,63}", count, 256),
                "quoted_fraction": MapOf("|".join(re.escape(p) for p in reachability.QUOTED_FRACTION_POLICIES),
                                         {"eligible_seconds": _decimal, "quoted_seconds": _decimal,
                                          "quoted_fraction": _nullable(_decimal)}, 3),
                "n_cal": count, "l_cal": count,
                "expected_clock_removed": _nullable({"calibration": _decimal, "panel": _decimal,
                                                     "panel_scale": _one_of(reachability.PANEL_SCALE_TEXT)})},
            "environment": {
                "source_sha256": _hex64, "python": _version, "numpy": _nullable(_version),
                "scipy": _nullable(_version),
                "thread_pins": {name: _nullable(_one_of(*map(str, range(1, 257)))) for name in THREAD_PINS},
                "hash_seed": _seed,
                "hash_probe": _signed64},
        })
    return _SCHEMA[0]


def _refuse(path):
    raise BundleError("rehearsal_whitelist:" + path)


def _walk(value, spec, path):
    if isinstance(value, Mapping):
        for key in value:
            if str(key) in FORBIDDEN:
                _refuse(f"{path}.{key}" if path else str(key))  # never allowed, at any depth or under a data key
    if isinstance(spec, dict):
        if not isinstance(value, Mapping):
            _refuse(path)
        for key, item in value.items():
            where = f"{path}.{key}" if path else str(key)
            if not isinstance(key, str) or key not in spec:
                _refuse(where)
            _walk(item, spec[key], where)
    elif isinstance(spec, MapOf):
        if not isinstance(value, Mapping) or len(value) > spec.limit:
            _refuse(path)
        for key, item in value.items():
            where = f"{path}.{key}" if path else str(key)
            if not isinstance(key, str) or spec.key.fullmatch(key) is None:
                _refuse(f"{path}.<key>")  # the key is data of the wrong shape: it is not echoed
            _walk(item, spec.value, where)
    elif isinstance(spec, ListOf):
        if not isinstance(value, list) or len(value) > spec.limit:
            _refuse(path)
        for i, item in enumerate(value):
            _walk(item, spec.item, f"{path}[{i}]")
    elif isinstance(value, (Mapping, list, tuple)) or not spec(value):
        _refuse(path)  # a structure where a leaf belongs, or a leaf of the wrong type or shape


def whitelisted(doc):
    """``doc`` unchanged when every key is in ``schema()`` at its path, every leaf has its type, and no forbidden key
    appears anywhere. Re-checked by every reader (``ceiling_input``, ``reachability.gate_report``, the CLI)."""
    if not isinstance(doc, Mapping):
        _refuse("")
    _walk(doc, schema(), "")
    return doc


def environment(environ=None):
    """What E7 compares (CONSOLIDATED row 17, binding): the digest of every ``maker_core`` source file this process
    can import, the interpreter and numeric library versions, the BLAS thread pins as seen, and the hash seed in
    force. ``hash_seed`` is ``PYTHONHASHSEED`` as set (``random`` when unset); ``hash_probe`` is ``hash()`` of a
    fixed string, so it shows the seed actually in force and differs between processes with different seeds."""
    import importlib.metadata
    import os
    import platform
    import maker_core
    environ = os.environ if environ is None else environ
    package = Path(maker_core.__file__).resolve().parent
    sources = {p.relative_to(package).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted(package.rglob("*.py"))}

    def version(name):
        try:
            return importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            return None
    seed = environ.get("PYTHONHASHSEED")
    return dict(source_sha256=digest(sources), python=platform.python_version(), numpy=version("numpy"),
                scipy=version("scipy"), thread_pins={name: environ.get(name) for name in THREAD_PINS},
                hash_seed="random" if seed in (None, "", "random") else seed, hash_probe=hash(HASH_PROBE))


def _counting(source, counts, done):
    """``source`` with its first read counted by record kind; later reads (matched-clock rounds) are not."""
    from maker_core.replay.v2.lockstep import DaySource

    def records():
        first = source.plan.day not in done
        for record in source.records():
            if first:
                counts[record.kind] += 1
            yield record
        done.add(source.plan.day)
    return DaySource(source.plan, records)


def _rehearsal_label(source):
    """The declared source relabelled ``synthetic`` so ``build_report`` composes without a manifest (see above)."""
    if not source.plan.declared:
        raise BundleError("rehearsal_requires_declared_intervals")
    return replace(source, plan=replace(source.plan, provenance="synthetic"))


def _zones(inventory):
    zones = {}
    for row in inventory:
        if zones.setdefault(row["market_id"], row["local_timezone"]) != row["local_timezone"]:
            raise BundleError("market_time_zone_disagreement")
    return zones


def rehearse(paths, inventory, *, mode, hazard_per_minute, calibration_sha256, hazard_variant="max_m", now,
             hazard_by_market=None, replicates=2000, clock=time.monotonic, memory=None, limits=None,
             progress=lambda *_: None, environ=None):
    """One score-free rehearsal (registration §9): ``per_date`` (one calibration bundle) or ``carried`` (the three).

    ``inventory`` is the weather producer's universe rows for those dates; ``hazard_per_minute`` comes from the
    unchanged calibration recipe (``calibration_sha256`` names its document; ``reachability.hazards`` reads both
    from it). ``hazard_variant="r1_per_city"`` (§11 R1) also takes ``hazard_by_market`` for every market of the
    inventory. A ``carried`` rehearsal adds the §11 ``reachability`` block (``reachability.block``). ``environment``
    (row 17) is read from ``environ`` (``os.environ`` by default) and this process. Nothing scored
    leaves this function: the report and the engines are dropped and only the whitelisted document is returned."""
    from maker_core.replay.bundle_v02 import open_stream_bundle
    from maker_core.replay.v2.host import process_memory
    from maker_core.replay.v2 import intervals, reachability
    from maker_core.replay.v2.engine import EngineV2
    from maker_core.replay.v2.kernel import V2Config
    from maker_core.replay.v2.limits import RunBudget
    from maker_core.replay.v2.pipeline import run_passes
    from maker_core.replay.v2.report import build_report, report_bytes

    if hazard_variant not in HAZARD_VARIANTS:
        raise BundleError("rehearsal_hazard_variant_invalid")
    paths = list(paths)
    days = sorted(calibration_day(path) for path in paths)  # before any byte is read
    if len(set(days)) != len(days):
        raise BundleError("rehearsal_duplicate_date")
    check_mode(mode, days)
    hazard_map = reachability.check_hazard_map(hazard_variant, hazard_by_market, {r["market_id"] for r in inventory})
    memory = memory or process_memory
    baseline = memory()[1]
    started = clock()
    budget = RunBudget(clock=clock)
    bundles = sorted((open_stream_bundle(Path(path), limits=limits, clock=clock, run=budget) for path in paths),
                     key=lambda b: b.day)
    if [b.day for b in bundles] != days:
        raise BundleError("rehearsal_restricted_to_calibration_dates")  # a manifest naming another day
    declared, _ = intervals.sources(bundles, inventory, panel="calibration", check=budget.check)
    counts, done = Counter(), set()
    sources = [_counting(_rehearsal_label(s), counts, done) for s in declared]
    config = V2Config(hazard_per_minute=hazard_per_minute)
    engine = EngineV2 if hazard_map is None else reachability.per_city_engine(EngineV2, hazard_map)
    decisions = Counter()
    if mode == "carried":
        engine = reachability.counting_engine(decisions, engine)
    run = run_passes(sources, config, time_zones=_zones(inventory), engine=engine, progress=progress)
    report, sidecar = build_report(run, config, replicates=replicates, check=budget.check)
    raw = report_bytes(report)
    runtime = clock() - started
    peak = memory()[1]
    status = report["status"]
    del report
    reach = opportunities = None
    if mode == "carried":
        opportunities = reachability.policy_free_opportunities(run.plan, run.books, check=budget.check)
        reach = reachability.block(run, decisions, check=budget.check, opportunities=opportunities)
    engines = [p.engine for passes in run.passes.values() for p in passes.values()]
    summaries = [e.summary() for e in engines] + [t if isinstance(t, dict) else t.engine.summary()
                                                  for *_, t in run.trials]
    if sum(counts.values()) != run.replayed["records"]:
        raise BundleError("rehearsal_record_count_mismatch")
    decision_shas = [e.summary()["decision_sha256"] for e in engines]  # one per pass, kept only as a digest
    measured = dict(
        input_bytes=sum(b.input_bytes for b in bundles), records=sum(counts.values()),
        records_by_kind=dict(sorted(counts.items())),
        wakes=max(s["wakes"] for s in summaries), decisions=max(s["decisions"] for s in summaries),
        span_runs=max(s["intervals"] for s in summaries), report_bytes=len(raw), sidecar_bytes=sidecar["bytes"],
        runtime_seconds=runtime,
        peak_memory_above_baseline_bytes=max(0, peak - baseline), baseline_memory_bytes=baseline)
    doc = dict(
        format=FORMAT, mode=mode, dates=[d.isoformat() for d in days], hazard_variant=hazard_variant,
        calibration_sha256=calibration_sha256, hazard_per_minute=hazard_per_minute,
        hazard_map_sha256=None if hazard_map is None else digest(sorted(hazard_map.items())),
        inventory_sha256=digest(list(inventory)),
        measured_at=now.isoformat(), interpretation=INTERPRETATION,
        report_status=status, replicates=replicates, measured=measured,
        hashes=dict(input_hashes={b.day.isoformat(): dict(b.input_hashes) for b in bundles},
                    report_sha256=hashlib.sha256(raw).hexdigest(), sidecar_sha256=sidecar["sha256"],
                    decision_sha256=digest(decision_shas)),
        environment=environment(environ))
    if reach is not None:
        doc["reachability"] = reach
        doc["pull_candidates"] = opportunities["candidates"]
    return whitelisted(doc)


def ceiling_input(doc) -> dict:
    """A whitelisted rehearsal document's ``measured`` block reduced to ``ceilings.MEASURED`` (``derive``'s input)."""
    from maker_core.replay.v2 import ceilings
    whitelisted(doc)
    if doc.get("format") != FORMAT:
        raise BundleError("rehearsal_format_invalid")
    measured = doc["measured"]
    if not set(ceilings.MEASURED) <= set(measured):
        raise BundleError("incomplete_ceiling_measurement")
    return {k: measured[k] for k in ceilings.MEASURED}
