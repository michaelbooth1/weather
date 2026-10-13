"""Score-free calibration rehearsal output contract (registration draft §9; W6, U2) — whitelist and guards.

A rehearsal runs the full v2 scored pipeline on a v0.2 night-format calibration export (2026-09-27..29 only) and
keeps **only** the §9 outputs: input bytes, records by kind, engine wakes, decisions, span runs, scored-report
bytes, sidecar bytes, runtime, peak memory above the pre-input baseline, the §11 reachability fields, and the
equivalence and determinism hashes. No fill, P&L, reward, markout, removed-move count or contrast is kept or shown.

This module holds the parts of that contract that do not depend on the pipeline wiring:

- ``calibration_day(path)``: the date a bundle path names, refused before a byte is read unless it is a
  calibration date (``rehearsal_restricted_to_calibration_dates``), as ``pack_cli.rehearse`` does for v1;
- ``project_pass(summary)``: an engine ``summary()`` projected to the whitelisted pass keys (``fills``,
  ``final_cash`` and the exclusion counts are dropped, never copied);
- ``whitelisted(doc)``: walks a rehearsal document and refuses any key outside ``WHITELIST`` at its path
  (``rehearsal_whitelist:<path>``), so a smuggled score key anywhere fails closed.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
import re

from maker_core.replay.bundle import BundleError
from maker_core.replay.calibration import CALIBRATION_DATES

FORMAT = "maker_core.replay.v2.rehearsal.v0.1"
MODES = ("per_date", "carried")
HAZARD_VARIANTS = ("max_m", "r1_per_city")
INTERPRETATION = "Resource counts, reachability fields and hashes only; no score, fill, P&L, reward or contrast."

PASS_KEYS = ("policy", "fill_bound", "instants", "wakes", "timer_pops", "stale_timers", "decisions", "intervals",
             "decision_sha256")
MEASURED_KEYS = ("input_bytes", "records", "records_by_kind", "wakes", "decisions", "span_runs", "report_bytes",
                 "sidecar_bytes", "sidecar_records", "runtime_seconds", "peak_memory_above_baseline_bytes",
                 "baseline_memory_bytes")
# The §11 reachability block (carried mode only): counts and fractions, never a cell or a score.
REACHABILITY_KEYS = ("status", "f_cal", "screen_pass_rate", "decision_reasons", "quoted_fraction", "n_cal", "l_cal",
                     "expected_clock_removed")

ANY = object()  # a free-form leaf (a value, or a mapping whose keys are data such as kinds, dates or reasons)
WHITELIST = {
    "format": ANY, "mode": ANY, "dates": ANY, "hazard_variant": ANY, "calibration_sha256": ANY,
    "after_fail_sha256": ANY, "measured_at": ANY, "interpretation": ANY,
    "measured": {**{k: ANY for k in MEASURED_KEYS}, "records_by_kind": ANY},
    "passes": [{k: ANY for k in PASS_KEYS}],
    "clock": {"rounds": ANY, "matches": {ANY: {"status": ANY, "attempts": ANY}}},
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


def project_pass(summary) -> dict:
    """An engine ``summary()`` reduced to ``PASS_KEYS``; a summary missing any of them refuses."""
    if not isinstance(summary, Mapping) or not set(PASS_KEYS) <= set(summary):
        raise BundleError("rehearsal_pass_summary_incomplete")
    return {k: summary[k] for k in PASS_KEYS}


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
