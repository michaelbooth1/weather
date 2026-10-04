"""Read-only precheck of the scored replay's pull-opportunity preflight (no score, no write).

The scored run refuses at ``engine_preflight`` when
``pull_efficiency.opportunity_candidates(ReplayEngine(bundles, config).windows)`` exceeds
``config.max_events``. ``max_events`` is the rehearsed engine-events ceiling: the largest
calibration date's heap pops x 15, rounded up to a power of two. Candidates are minute starts
inside every condition's active windows, so they follow the condition count while heap pops
follow distinct capture clocks. This tool prints both numbers and the verdict before a look.

Run it on the production host with the pinned exam worktree's ``src`` first on PYTHONPATH,
so the count and the ceiling rule are the exam tree's own code:

    $env:PYTHONPATH = "<pinned exam worktree>\\src"
    .\\venv\\Scripts\\python.exe tools\\exam_pull_cap_precheck.py `
        --bundle <panel root>\\2026-09-30\\bundle ... --bundle <panel root>\\2026-10-14\\bundle `
        --ceiling-measurement <exam root>\\ceiling_measurement.json --universe <exam root>\\universe.json

Only each bundle's ``bundle.json`` is read (conditions and active windows); record streams
are never opened. ``--calibration-bundle`` with ``--rehearsal`` projects the panel count from
the calibration dates alone, before any panel export exists. Exit 0: the preflight would
pass; 3: it would refuse; 2: input refused or the exam tree is missing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Exam constants (execution_manifest at the pinned tree); cross-checked when it is importable.
QUOTE_DATES = tuple(date(2026, 9, 30) + timedelta(days=i) for i in range(14))
SETTLEMENT_DATE = date(2026, 10, 14)
MAINTENANCE = (timedelta(hours=5), timedelta(hours=8))
MULTIPLIER = 15
MINUTE = timedelta(minutes=1)
MAX_MANIFEST_BYTES = 1024**2
MAX_JSON_BYTES = 8 * 1024**2
PASS, REFUSE, ERROR = 0, 3, 2


class PrecheckError(ValueError):
    """An input this read-only check refuses to interpret."""


def _utc(text):
    value = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise PrecheckError("timestamp_requires_utc")
    return value.astimezone(timezone.utc)


def _read(path, maximum):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise PrecheckError(f"not_a_regular_file:{path}")
    raw = path.read_bytes()
    if len(raw) > maximum:
        raise PrecheckError(f"input_too_large:{path}")
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def read_manifest(directory):
    """(day, [(condition_id, market_id, active_from, active_until)], bundle.json sha256)."""
    doc, digest = _read(Path(directory) / "bundle.json", MAX_MANIFEST_BYTES)
    if not isinstance(doc, dict) or not isinstance(doc.get("conditions"), list):
        raise PrecheckError(f"invalid_bundle_manifest:{directory}")
    day = date.fromisoformat(doc["day"])
    conditions = []
    for c in doc["conditions"]:
        start, end = _utc(c["active_from"]), _utc(c["active_until"])
        if not start <= end:
            raise PrecheckError("invalid_active_window")
        conditions.append((c["condition_id"], c["market_id"], start, end))
    return day, conditions, digest


def read_universe(path):
    """condition_id -> target date, from the sealed universe inventory."""
    doc, digest = _read(path, MAX_JSON_BYTES)
    if not isinstance(doc, list):
        raise PrecheckError("invalid_universe_inventory")
    return {r["condition_id"]: date.fromisoformat(r["target_date"]) for r in doc}, digest


def active_intervals(manifests, targets=None):
    """The manifest rule: 05:00-08:00 UTC removed; none on the settlement date or past it.

    ``targets`` is the universe's target dates. Without it, bands whose target is after the
    settlement date keep their windows, so the count is an upper bound.
    """
    intervals = []
    for day, conditions, _ in manifests:
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        low, high = start + MAINTENANCE[0], start + MAINTENANCE[1]
        for cid, _, active_from, active_until in conditions:
            if day == SETTLEMENT_DATE or (targets is not None and targets[cid] > SETTLEMENT_DATE):
                continue
            for a, b in ((active_from, min(active_until, low)), (max(active_from, high), active_until)):
                if a < b:
                    intervals.append((day, cid, a, b))
    return intervals


def windows_by_condition(intervals):
    windows = {}
    for _, cid, start, end in intervals:
        windows.setdefault(cid, []).append((start, end))
    return windows


def opportunity_candidates(windows):
    """Minute starts in each condition's union of windows (replica of the exam tree's count)."""
    total = 0
    for cid in sorted(windows):
        until = None
        for start, end in sorted(windows[cid]):
            at = start.replace(second=0, microsecond=0)
            if at < start:
                at += MINUTE
            if until is not None:
                at = max(at, until)
            if at < end:
                count = -((at - end) // MINUTE)
                total += count
                at += count * MINUTE
            until = at if until is None else max(until, at)
    return total


def next_power_of_two(value):
    return 1 if value <= 1 else 2 ** math.ceil(math.log2(value))


def ceiling_from_rehearsals(per_date_events):
    return next_power_of_two(max(per_date_events.values()) * MULTIPLIER)


def read_ceiling(args):
    """(max_events, {date: rehearsed engine_events} or None, provenance)."""
    if args.ceiling_measurement:
        doc, digest = _read(args.ceiling_measurement, MAX_JSON_BYTES)
        per_date = {d: m["engine_events"] for d, m in doc["per_date"].items()}
        bound = doc["derived"]["ceilings"]["engine_events"]
        if bound != ceiling_from_rehearsals(per_date):
            raise PrecheckError("ceiling_measurement_engine_events_not_rule_derived")
        return bound, per_date, dict(source="ceiling_measurement", sha256=digest, doc=doc)
    if args.rehearsal:
        per_date, digests = {}, {}
        for path in args.rehearsal:
            doc, digest = _read(path, MAX_JSON_BYTES)
            if doc["date"] in per_date:
                raise PrecheckError("duplicate_rehearsal_date")
            per_date[doc["date"]], digests[doc["date"]] = doc["measured"]["engine_events"], digest
        return ceiling_from_rehearsals(per_date), per_date, dict(source="rehearsal", sha256=digests)
    if args.max_events:
        return args.max_events, None, dict(source="max_events_argument")
    raise PrecheckError("ceiling_source_required")


def exam_crosscheck(intervals, manifests, candidates, provenance):
    """Recount with the pinned exam tree's own engine and preflight; refuse any disagreement."""
    from maker_core.replay import ceilings, execution_manifest
    from maker_core.replay.bundle import Bundle, Condition
    from maker_core.replay.engine import MAX_ENGINE_EVENTS, ReplayConfig, ReplayEngine
    from maker_core.replay.pull_efficiency import opportunity_candidates as exam_candidates

    if (tuple(execution_manifest.QUOTE_DATES), execution_manifest.SETTLEMENT_DATE) != (QUOTE_DATES, SETTLEMENT_DATE):
        raise PrecheckError("exam_dates_differ_from_this_tool")
    bundles = []
    for day, conditions, _ in manifests:
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        bundles.append(Bundle(day, start + timedelta(days=1), "captured",
                              tuple(Condition(cid, market, "precheck", a, b) for cid, market, a, b in conditions),
                              (), {}, 0, tuple((cid, a, b) for d, cid, a, b in intervals if d == day)))
    config = ReplayConfig(**execution_manifest.FROZEN_CONFIG, hazard_per_minute=0.0,
                          max_events=MAX_ENGINE_EVENTS, max_outputs=MAX_ENGINE_EVENTS)
    counted = exam_candidates(ReplayEngine(tuple(bundles), config).windows)
    if counted != candidates:
        raise PrecheckError(f"exam_tree_count_differs:{counted}!={candidates}")
    if provenance.get("source") == "ceiling_measurement":
        doc = provenance.pop("doc")
        if ceilings.derive(doc["per_date"]) != doc["derived"]:
            raise PrecheckError("ceiling_measurement_not_derived_by_exam_rule")
    return dict(status="AGREES", module=sys.modules[exam_candidates.__module__].__file__)


def verdict(candidates, max_events):
    return dict(candidates=candidates, max_events=max_events, ratio=candidates / max_events,
                verdict="PREFLIGHT_WOULD_REFUSE" if candidates > max_events else "PREFLIGHT_WOULD_PASS")


def projection(calibration_manifests, per_date_events, max_events):
    """Panel estimate from calibration dates: 14 quote dates at the busiest date's candidates."""
    rows = {}
    for manifest in calibration_manifests:
        day = manifest[0].isoformat()
        count = opportunity_candidates(windows_by_condition(active_intervals([manifest])))
        events = (per_date_events or {}).get(day)
        rows[day] = dict(conditions=len(manifest[1]), candidates=count, engine_events=events,
                         candidates_per_heap_pop=count / events if events else None)
    projected = len(QUOTE_DATES) * max(r["candidates"] for r in rows.values())
    return dict(per_date=rows, rule="14 x largest calibration-date candidates", **verdict(projected, max_events))


def run(args):
    max_events, per_date, provenance = read_ceiling(args)
    targets, universe_sha = read_universe(args.universe) if args.universe else (None, None)
    result = dict(format="exam_pull_cap_precheck.v1", max_events=max_events, rehearsed_engine_events=per_date,
                  ceiling_source={k: v for k, v in provenance.items() if k != "doc"})
    if args.bundle:
        manifests = sorted((read_manifest(p) for p in args.bundle), key=lambda m: m[0])
        if len({m[0] for m in manifests}) != len(manifests):
            raise PrecheckError("duplicate_bundle_day")
        if targets is not None and any(c[0] not in targets for m in manifests for c in m[1]):
            raise PrecheckError("universe_missing_condition")
        intervals = active_intervals(manifests, targets)
        candidates = opportunity_candidates(windows_by_condition(intervals))
        days = [m[0] for m in manifests]
        result["panel"] = dict(
            days=[d.isoformat() for d in days], conditions=sum(len(m[1]) for m in manifests),
            complete=days == [*QUOTE_DATES, SETTLEMENT_DATE],
            count_kind="exact" if targets is not None else "upper_bound_without_universe",
            universe_sha256=universe_sha, bundle_json_sha256={m[0].isoformat(): m[2] for m in manifests},
            **verdict(candidates, max_events))
        if args.allow_without_exam_tree:
            result["panel"]["exam_tree"] = dict(status="NOT_CHECKED")
        else:
            result["panel"]["exam_tree"] = exam_crosscheck(intervals, manifests, candidates, provenance)
    if args.calibration_bundle:
        result["projection"] = projection([read_manifest(p) for p in args.calibration_bundle], per_date, max_events)
    if "panel" not in result and "projection" not in result:
        raise PrecheckError("bundle_or_calibration_bundle_required")
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--bundle", type=Path, action="append", help="panel bundle directory (repeat; 14 quote + settlement)")
    p.add_argument("--calibration-bundle", type=Path, action="append", help="calibration bundle directory (repeat)")
    p.add_argument("--universe", type=Path, help="sealed universe inventory JSON (exact target-date exclusion)")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--ceiling-measurement", type=Path, help="derive_ceilings output JSON")
    source.add_argument("--rehearsal", type=Path, action="append", help="rehearse output JSON (repeat per date)")
    source.add_argument("--max-events", type=int, help="an explicit engine-events ceiling")
    p.add_argument("--allow-without-exam-tree", action="store_true",
                   help="skip the exam-tree recount (fixtures only; production sets PYTHONPATH instead)")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if not args.allow_without_exam_tree and args.bundle:
            try:
                import maker_core.replay.pull_efficiency  # noqa: F401
            except ImportError as exc:
                raise PrecheckError("exam_tree_not_on_pythonpath: set PYTHONPATH to the pinned worktree's src") from exc
        result = run(args)
    except (PrecheckError, KeyError, TypeError, ValueError, OSError) as exc:
        print(json.dumps(dict(format="exam_pull_cap_precheck.v1", status="REFUSED",
                              error=f"{type(exc).__name__}: {exc}")))
        return ERROR
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    for key in ("panel", "projection"):
        if key in result:
            r = result[key]
            print(f"{key}: candidates={r['candidates']} max_events={r['max_events']} "
                  f"ratio={r['ratio']:.4f} verdict={r['verdict']}")
    decisive = result.get("panel") or result["projection"]
    return REFUSE if decisive["verdict"] == "PREFLIGHT_WOULD_REFUSE" else PASS


if __name__ == "__main__":
    raise SystemExit(main())
