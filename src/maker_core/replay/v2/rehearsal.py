"""Score-free calibration rehearsal output contract (registration draft §9; W6, U2) — whitelist and guards.

A rehearsal runs the full v2 scored pipeline on a v0.2 night-format calibration export (2026-09-27..29 only) and
keeps **only** the §9 outputs: input bytes, records by kind, engine wakes, decisions, span runs, scored-report
bytes, sidecar bytes, runtime, peak memory above the pre-input baseline, the §11 reachability fields, and the
equivalence and determinism hashes. No fill, P&L, reward, markout, removed-move count or contrast is kept or shown.

This module holds the parts of that contract that do not depend on the pipeline wiring:

- ``calibration_day(path)``: the date a bundle path names, refused before a byte is read unless it is a
  calibration date (``rehearsal_restricted_to_calibration_dates``), as ``pack_cli.rehearse`` does for v1;
- ``whitelisted(doc)``: walks a rehearsal document and refuses any key outside ``WHITELIST`` at its path
  (``rehearsal_whitelist:<path>``), so a smuggled score key anywhere fails closed.

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
process peak (``ceilings.process_memory``) above the peak taken before the first input byte, so one rehearsal
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
import re
import time

from maker_core.evidence.journal import digest
from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES

FORMAT = "maker_core.replay.v2.rehearsal.v0.1"
MODES = ("per_date", "carried")
HAZARD_VARIANTS = ("max_m", "r1_per_city")
INTERPRETATION = "Resource counts, reachability fields and hashes only; no score, fill, P&L, reward or contrast."

MEASURED_KEYS = ("input_bytes", "records", "records_by_kind", "wakes", "decisions", "span_runs", "report_bytes",
                 "sidecar_bytes", "runtime_seconds", "peak_memory_above_baseline_bytes",
                 "baseline_memory_bytes")
# The §11 reachability block (carried mode only): counts and fractions, never a cell or a score.
REACHABILITY_KEYS = ("status", "f_cal", "screen_pass_rate", "decision_reasons", "quoted_fraction", "n_cal", "l_cal",
                     "pull_candidates", "opportunity_exclusions", "expected_clock_removed")

ANY = object()  # a free-form leaf (a value, or a mapping whose keys are data such as kinds, dates or reasons)
WHITELIST = {
    "format": ANY, "mode": ANY, "dates": ANY, "hazard_variant": ANY, "calibration_sha256": ANY,
    "after_fail_sha256": ANY, "measured_at": ANY, "interpretation": ANY, "report_status": ANY, "replicates": ANY,
    "hazard_per_minute": ANY, "hazard_map_sha256": ANY,
    "measured": {**{k: ANY for k in MEASURED_KEYS}, "records_by_kind": ANY},
    "hashes": {"input_hashes": ANY, "report_sha256": ANY, "sidecar_sha256": ANY, "decision_sha256": ANY},
    "reachability": {**{k: ANY for k in REACHABILITY_KEYS}, "decision_reasons": ANY, "quoted_fraction": ANY},
}
# Keys that may never appear anywhere in a rehearsal document, even under a free-form leaf.
FORBIDDEN = frozenset({"fills", "final_cash", "pnl", "reward", "rewards", "markout", "markouts", "contrast",
                       "removed_moves", "score", "scores", "cells", "band_days", "registered_decision", "target",
                       "actual", "calendar_prefix_fraction", "exclusions", "exclusions_sha256"})
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


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


def _walk(value, spec, path):
    if isinstance(value, Mapping):
        for key, item in value.items():
            where = f"{path}.{key}" if path else str(key)
            if str(key) in FORBIDDEN:
                raise BundleError("rehearsal_whitelist:" + where)
            if spec is ANY:
                _walk(item, ANY, where)
                continue
            if not isinstance(spec, Mapping):
                raise BundleError("rehearsal_whitelist:" + where)
            child = spec.get(key, spec.get(ANY, None)) if ANY in spec else spec.get(key)
            if child is None:
                raise BundleError("rehearsal_whitelist:" + where)
            _walk(item, child, where)
    elif isinstance(value, (list, tuple)):
        item_spec = ANY if spec is ANY else (spec[0] if isinstance(spec, list) and spec else None)
        if item_spec is None:
            raise BundleError("rehearsal_whitelist:" + path)
        for i, item in enumerate(value):
            _walk(item, item_spec, f"{path}[{i}]")
    elif spec is not ANY:
        raise BundleError("rehearsal_whitelist:" + path)  # a leaf where the whitelist expects structure


def whitelisted(doc):
    """``doc`` unchanged when every key is whitelisted at its path and no forbidden key appears anywhere."""
    if not isinstance(doc, Mapping):
        raise BundleError("rehearsal_whitelist:")
    _walk(doc, WHITELIST, "")
    return doc


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
             progress=lambda *_: None):
    """One score-free rehearsal (registration §9): ``per_date`` (one calibration bundle) or ``carried`` (the three).

    ``inventory`` is the weather producer's universe rows for those dates; ``hazard_per_minute`` comes from the
    unchanged calibration recipe (``calibration_sha256`` names its document; ``reachability.hazards`` reads both
    from it). ``hazard_variant="r1_per_city"`` (§11 R1) also takes ``hazard_by_market`` for every market of the
    inventory. A ``carried`` rehearsal adds the §11 ``reachability`` block (``reachability.block``). Nothing scored
    leaves this function: the report and the engines are dropped and only the whitelisted document is returned."""
    from maker_core.replay.bundle_v02 import open_stream_bundle
    from maker_core.replay.ceilings import process_memory
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
    reach = reachability.block(run, decisions, check=budget.check) if mode == "carried" else None
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
        measured_at=now.isoformat(), interpretation=INTERPRETATION,
        report_status=status, replicates=replicates, measured=measured,
        hashes=dict(input_hashes={b.day.isoformat(): dict(b.input_hashes) for b in bundles},
                    report_sha256=hashlib.sha256(raw).hexdigest(), sidecar_sha256=sidecar["sha256"],
                    decision_sha256=digest(decision_shas)))
    if reach is not None:
        doc["reachability"] = reach
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
