"""Combined METAR v4 re-parse + lock-in v3 replay over captured inputs (read-only).

The production acceptance read for ``metar-parser-v4`` (obsTime keying, #189)
on top of the ``lockin-anchor-v3`` late-day lock-in (#191). For every captured
snapshot of a closed market-day it:

1. joins the snapshot's ``replay_inputs.jsonl`` record to the raw AWC METAR
   payload retained under ``observation_payloads/`` (the SHA-256 of the blob is
   verified, exactly as ``metar_keying_replay`` does);
2. re-parses that payload with the served v4 parser
   (``metar_data_from_payload``) and substitutes the result for the captured
   ``metar`` source block, then re-derives ``station_observations`` with the
   serving function ``derive_station_observations_source``; every other
   dependent feature (``guidance_physical_floor``, the lock-in anchor, the
   current reading) is recomputed by ``estimate_distribution`` itself;
3. runs ``estimate_distribution`` three times with the active serving bundle:
   ``old`` = captured inputs with the pre-restoration WU-only anchor (the v1
   path), ``v3_captured`` = captured inputs with lockin-anchor-v3 (#191 alone),
   ``new`` = v4 re-parsed inputs with lockin-anchor-v3 (#191 + #189).

With ``--compare-pre-lockin-floor`` it also runs ``new`` once more with the
model's ``pre_lockin_same_day_floor`` switch off (the lockin-anchor-v4 floor
before lock-in; on code without that floor the switch is inert and the two
runs agree) and reports, per block, the mass that floor moved onto the anchor
bucket, the L1 and the expected-value shift it causes. ``anchor_versions``
in the summary says which anchor contract the replayed code served.

It writes one JSONL row per snapshot and prints a per-hour-block summary
(00-05, 06-09, 10-12, 13-16, 17-23): rows changed, mean mass above and below
the anchor old vs new, the floor check (rows WITHOUT carry-over whose new vector
holds more mass below the new anchor bucket than the old vector; any such row
exits 3), the defect-baseline class (carry-over rows, whose old vector was
propped by the D-1 report v4 removes: counted in
``defect_baseline_below_increase`` and never failing the check), the absolute
count of rows with any mass below the same-day anchor bucket, and the
rows where v4 re-keying changed ``guidance_physical_floor`` or the anchor,
including the carry-over cases where v4 drops a D-1 23:5x report that the v3
keying carried into day D. It does not score against settlement or the market.

Read-only contract:
- It reads ``replay_inputs.jsonl``, ``observation_payloads.jsonl`` (or
  ``observation_payloads_long.csv``) and the content-addressed blobs of the
  selected market-day folders. Reconstructed replay records are not replayed
  (they have no retained payload).
- It writes exactly one new file, ``--out``, which must not exist and must lie
  outside the runtime ``data/`` tree. It never writes production state.
- It refuses target dates after ``LAST_REPLAYABLE_DATE`` (2026-09-29) and
  skips, without opening its blob, any snapshot built after that date.

CLI:
  python -m weather.backtesting.metar_v4_lockin_replay --out <path.jsonl>
      [folder ...] [--snapshots-root data/snapshots] [--market MARKET]
      [--from-date YYYY-MM-DD] [--through-date YYYY-MM-DD]
      [--compare-pre-lockin-floor]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.backtesting import lockin_anchor_replay as lockin
from weather.backtesting import metar_keying_replay as keying
from weather.backtesting.replay import (
    distribution_l1,
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    parse_built_at,
    record_target_date,
)
from weather.market.market_registry import REGISTRY
from weather.model.model_sources import SOURCE_PAYLOAD_CONTRACTS
from weather.paths import data_path

LAST_REPLAYABLE_DATE = lockin.LAST_REPLAYABLE_DATE
BELOW_ANCHOR_TOLERANCE = lockin.BELOW_ANCHOR_TOLERANCE
FLOOR_CHECK_FAILED_EXIT = lockin.FLOOR_CHECK_FAILED_EXIT
HOUR_BLOCKS = (
    ("00-05", 0, 5),
    ("06-09", 6, 9),
    ("10-12", 10, 12),
    ("13-16", 13, 16),
    ("17-23", 17, 23),
)
V4_PARSER_VERSION = SOURCE_PAYLOAD_CONTRACTS["metar"][0]
REPARSED = "ok"
NO_METAR_SOURCE = "no_metar_source"
NO_PAYLOAD_ROW = "no_payload_row"
SKIPPED_AFTER_CUTOFF = "skipped_after_cutoff"
COMPARED_STATUSES = (REPARSED, NO_METAR_SOURCE)
PRE_LOCKIN_FLOOR_SWITCH = "pre_lockin_same_day_floor"
ReplayRefused = lockin.ReplayRefused
check_out_path = lockin.check_out_path
select_folders = lockin.select_folders


def v4_sources(model, sources, payload):
    """Captured sources with the METAR block re-parsed by the served v4 parser.

    Mirrors serving: ``fetch_metar`` builds the block with
    ``metar_data_from_payload`` (envelope keys such as ``url`` are kept from the
    captured block), and ``fetch_live_sources`` re-derives
    ``station_observations`` from the blended sources. A captured
    ``station_observations`` block that came from another station source
    (SWOB) and still does is left untouched.
    """
    sources = dict(sources or {})
    item = dict(sources.get("metar") or {})
    data = dict(item.get("data") or {})
    data.update(model.metar_data_from_payload(payload))
    item["data"] = data
    item["parser_version"] = V4_PARSER_VERSION
    sources["metar"] = item
    captured_station = sources.get("station_observations") or {}
    derived = model.derive_station_observations_source(sources)
    if "metar" in (captured_station.get("fallback_source"), (derived or {}).get("fallback_source")):
        if derived:
            sources["station_observations"] = derived
        else:
            sources.pop("station_observations", None)
    return sources


def _anchor(payload):
    return dict((payload.get("high_has_stood_lockin") or {}).get("lockin_anchor") or {})


def _anchor_key(anchor):
    return (anchor.get("source"), anchor.get("high"), anchor.get("bucket"))


def _local_date(iso_utc, tz):
    if not iso_utc:
        return None
    try:
        parsed = datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(tz).date()


def _carried_rows(model, keyed, target):
    """v3-only rows observed before the target local day (the M0 carry-over)."""
    if keyed is None:
        return []
    return [
        row for row in keyed["rows_only_old"]
        if (_local_date(row.get("obs_time"), model.spec.tz) or target) < target
    ]


def _replay_without_pre_lockin_floor(model, record):
    had = PRE_LOCKIN_FLOOR_SWITCH in vars(model)
    previous = vars(model).get(PRE_LOCKIN_FLOOR_SWITCH)
    setattr(model, PRE_LOCKIN_FLOOR_SWITCH, False)
    try:
        return lockin._replay(model, record, legacy=False)
    finally:
        if had:
            setattr(model, PRE_LOCKIN_FLOOR_SWITCH, previous)
        else:
            delattr(model, PRE_LOCKIN_FLOOR_SWITCH)


def _expected(distribution):
    total = sum(distribution.values())
    return sum(b * p for b, p in distribution.items()) / total if total else None


def compare_snapshot(model, record, market_id, payload, status, *, compare_pre_lockin_floor=False):
    """One old / v3_captured / new comparison row for a captured record."""
    built_at = parse_built_at(record)
    target = record_target_date(record)
    if target is None or target > LAST_REPLAYABLE_DATE:
        raise ReplayRefused(f"refused: record targets {target}, after {LAST_REPLAYABLE_DATE}")
    model.set_target_date(target)
    keyed = keying.compare_payload(model, payload) if status == REPARSED else None
    new_sources = (
        v4_sources(model, record.get("sources"), payload) if status == REPARSED
        else record.get("sources") or {}
    )
    old, old_payload = lockin._replay(model, record, legacy=True)
    mid, mid_payload = lockin._replay(model, record, legacy=False)
    new, new_payload = lockin._replay(model, {**record, "sources": new_sources}, legacy=False)
    captured_anchor, anchor = _anchor(mid_payload), _anchor(new_payload)
    bucket = anchor.get("bucket")
    floor_old = captured_anchor.get("guidance_physical_floor")
    floor_new = anchor.get("guidance_physical_floor")
    carried = _carried_rows(model, keyed, target)
    b_off = None
    if compare_pre_lockin_floor:
        b_off, _ = _replay_without_pre_lockin_floor(model, {**record, "sources": new_sources})
    new_mean, b_off_mean = _expected(new), _expected(b_off) if b_off is not None else None
    return {
        "snapshot_id": str(record.get("snapshot_id")),
        "market_id": market_id,
        "target_date": target.isoformat(),
        "built_at": built_at.isoformat() if built_at else None,
        "hour": built_at.hour if built_at else None,
        "status": status,
        "recorded_parser_version": (record.get("sources") or {}).get("metar", {}).get("parser_version"),
        "lockin_anchor": anchor,
        "lockin_anchor_v3_captured": captured_anchor,
        "anchor_changed_by_reparse": _anchor_key(captured_anchor) != _anchor_key(anchor),
        "guidance_physical_floor_captured": floor_old,
        "guidance_physical_floor_reparsed": floor_new,
        "floor_changed_by_reparse": floor_old != floor_new,
        "floor_dropped_by_reparse": (
            floor_old is not None and (floor_new is None or floor_new < floor_old)
        ),
        "carried_prior_day_rows": carried,
        "metar_rows_only_report_time_keying": keyed["rows_only_old"] if keyed else [],
        "metar_rows_only_obs_time_keying": keyed["rows_only_new"] if keyed else [],
        "old_lockin_strength": old_payload.get("lockin_strength"),
        "v3_captured_lockin_strength": mid_payload.get("lockin_strength"),
        "new_lockin_strength": new_payload.get("lockin_strength"),
        "old_mass_above_anchor": lockin._above(old, bucket),
        "new_mass_above_anchor": lockin._above(new, bucket),
        "old_mass_below_anchor": lockin._below(old, bucket),
        "new_mass_below_anchor": lockin._below(new, bucket),
        "l1_new_vs_old": distribution_l1(new, old),
        "l1_new_vs_v3_captured": distribution_l1(new, mid),
        "old_final": {str(k): v for k, v in sorted(old.items())},
        "v3_captured_final": {str(k): v for k, v in sorted(mid.items())},
        "new_final": {str(k): v for k, v in sorted(new.items())},
        "anchor_version": anchor.get("version"),
        "observed_floor_stage": anchor.get("observed_floor_stage"),
        "b_off_mass_below_anchor": lockin._below(b_off, bucket) if b_off is not None else None,
        "l1_new_vs_b_off": distribution_l1(new, b_off) if b_off is not None else None,
        "mean_shift_new_vs_b_off": (
            new_mean - b_off_mean if new_mean is not None and b_off_mean is not None else None
        ),
        "b_off_final": (
            {str(k): v for k, v in sorted(b_off.items())} if b_off is not None else None
        ),
    }


def _below_increase(row):
    return (
        row["new_mass_below_anchor"] is not None
        and row["new_mass_below_anchor"] > row["old_mass_below_anchor"] + BELOW_ANCHOR_TOLERANCE
    )


def _defect_baseline(row):
    """A carry-over row: its old vector was shaped by the D-1 report v4 removes.

    On such rows the old ``guidance_physical_floor`` (and so the old vector) was
    propped by a prior-day reading, so "new below > old below" measures the
    removal of the defect, not a new violation. They are reported as their own
    class and never fail the floor check.
    """
    return bool(row["carried_prior_day_rows"])


def _below_violation(row):
    return _below_increase(row) and not _defect_baseline(row)


def _below_positive(row):
    """Absolute physical check: new mass below the same-day observed anchor bucket."""
    return (
        row["new_mass_below_anchor"] is not None
        and row["new_mass_below_anchor"] > BELOW_ANCHOR_TOLERANCE
    )


def _mean(rows, key):
    values = [row[key] for row in rows if row[key] is not None]
    return sum(values) / len(values) if values else None


def _pre_lockin_floor_effect(rows):
    """What the lockin-anchor-v4 pre-lock-in floor did (``--compare-pre-lockin-floor``)."""
    compared = [row for row in rows if row.get("l1_new_vs_b_off") is not None]
    if not compared:
        return {}
    moved = [row["b_off_mass_below_anchor"] for row in compared
             if row["b_off_mass_below_anchor"] is not None]
    shifts = [row["mean_shift_new_vs_b_off"] for row in compared
              if row["mean_shift_new_vs_b_off"] is not None]
    return {"pre_lockin_floor": {
        "rows": len(compared),
        "rows_changed": sum(1 for row in compared if row["l1_new_vs_b_off"] > 1e-12),
        "rows_b_off_below_anchor_positive": sum(1 for value in moved if value > BELOW_ANCHOR_TOLERANCE),
        "mean_mass_moved_onto_anchor": sum(moved) / len(moved) if moved else None,
        "max_mass_moved_onto_anchor": max(moved, default=None),
        "mean_l1_new_vs_b_off": _mean(compared, "l1_new_vs_b_off"),
        "max_l1_new_vs_b_off": max(row["l1_new_vs_b_off"] for row in compared),
        "mean_shift_new_vs_b_off": sum(shifts) / len(shifts) if shifts else None,
        "max_shift_new_vs_b_off": max(shifts, default=None),
    }}


def _counts(rows):
    carry = [row for row in rows if row["carried_prior_day_rows"]]
    return {
        "floor_changed_by_reparse": sum(1 for row in rows if row["floor_changed_by_reparse"]),
        "floor_dropped_by_reparse": sum(1 for row in rows if row["floor_dropped_by_reparse"]),
        "anchor_changed_by_reparse": sum(1 for row in rows if row["anchor_changed_by_reparse"]),
        "carry_over_rows": len(carry),
        "carry_over_floor_dropped": sum(1 for row in carry if row["floor_dropped_by_reparse"]),
        "carry_over_anchor_changed": sum(1 for row in carry if row["anchor_changed_by_reparse"]),
        "defect_baseline_below_increase": sum(1 for row in carry if _below_increase(row)),
        "rows_new_below_anchor_positive": sum(1 for row in rows if _below_positive(row)),
        "max_new_mass_below_anchor": max(
            (row["new_mass_below_anchor"] for row in rows if row["new_mass_below_anchor"] is not None),
            default=None,
        ),
    }


def summarize(rows, status_counts=None):
    blocks = []
    for label, start, end in HOUR_BLOCKS:
        group = [row for row in rows if row["hour"] is not None and start <= row["hour"] <= end]
        blocks.append({
            "block": label,
            "snapshots": len(group),
            "changed": sum(1 for row in group if row["l1_new_vs_old"] > 1e-12),
            "changed_by_reparse": sum(1 for row in group if row["l1_new_vs_v3_captured"] > 1e-12),
            "max_l1_new_vs_old": max((row["l1_new_vs_old"] for row in group), default=None),
            "mean_old_mass_above_anchor": _mean(group, "old_mass_above_anchor"),
            "mean_new_mass_above_anchor": _mean(group, "new_mass_above_anchor"),
            "mean_old_mass_below_anchor": _mean(group, "old_mass_below_anchor"),
            "mean_new_mass_below_anchor": _mean(group, "new_mass_below_anchor"),
            "rows_new_below_anchor_exceeds_old": sum(1 for row in group if _below_violation(row)),
            **_counts(group),
            **_pre_lockin_floor_effect(group),
        })
    violations = sum(1 for row in rows if _below_violation(row))
    return {
        "snapshots": len(rows),
        "status": dict(sorted((status_counts or {}).items())),
        "rows_new_below_anchor_exceeds_old": violations,
        "floor_check": "FAIL" if violations else "PASS",
        **_counts(rows),
        **_pre_lockin_floor_effect(rows),
        "anchor_versions": dict(sorted(Counter(
            str(row.get("anchor_version")) for row in rows
        ).items())),
        "blocks": blocks,
    }


_SUMMARY_KEYS = (
    "hour", "l1_new_vs_old", "l1_new_vs_v3_captured",
    "old_mass_above_anchor", "new_mass_above_anchor",
    "old_mass_below_anchor", "new_mass_below_anchor",
    "floor_changed_by_reparse", "floor_dropped_by_reparse", "anchor_changed_by_reparse",
    "carried_prior_day_rows", "anchor_version",
    "b_off_mass_below_anchor", "l1_new_vs_b_off", "mean_shift_new_vs_b_off",
)


def _payloads_by_snapshot(folder):
    return {str(row.get("snapshot_id")): row for row in keying.load_manifest(folder)}


def run(folders, out_path, *, model_factory=None, compare_pre_lockin_floor=False):
    if model_factory is None:
        from weather.model.toronto_model import TorontoHighTempModel

        def model_factory(market_id):
            return TorontoHighTempModel(market_id=market_id)

    out = check_out_path(out_path)
    models = {}
    rows = []
    status_counts = Counter()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        for folder, market_id, _ in folders:
            records = index_records_by_snapshot(load_replay_records(folder))
            manifest = _payloads_by_snapshot(folder)
            blobs = {}
            if market_id not in models:
                models[market_id] = model_factory(market_id)
            for snapshot_id in sorted(records):
                record = records[snapshot_id]
                if is_reconstructed(record) or not record.get("sources"):
                    continue
                built_at = parse_built_at(record)
                if built_at is not None and built_at.date() > LAST_REPLAYABLE_DATE:
                    status_counts[SKIPPED_AFTER_CUTOFF] += 1
                    continue
                payload, status = None, NO_METAR_SOURCE
                if (record["sources"].get("metar") or {}).get("data"):
                    entry = manifest.get(snapshot_id)
                    if entry is None:
                        status = NO_PAYLOAD_ROW
                    else:
                        digest = str(entry.get("payload_hash") or "")
                        if digest not in blobs:
                            blobs[digest] = keying.load_blob(folder, entry)
                        payload, status = blobs[digest]
                status_counts[status] += 1
                if status not in COMPARED_STATUSES:
                    handle.write(json.dumps({
                        "snapshot_id": snapshot_id, "market_id": market_id, "status": status,
                    }, sort_keys=True) + "\n")
                    continue
                row = compare_snapshot(models[market_id], record, market_id, payload, status,
                                       compare_pre_lockin_floor=compare_pre_lockin_floor)
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
                rows.append({key: row[key] for key in _SUMMARY_KEYS})
    return summarize(rows, status_counts)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Read-only combined replay: re-parse captured METAR payloads with the v4 "
                    "(obsTime) parser, then run the lockin-anchor-v3 late-day lock-in "
                    f"(closed dates <= {LAST_REPLAYABLE_DATE} only).",
    )
    parser.add_argument("folders", nargs="*", help="Market-day snapshot folders (default: all).")
    parser.add_argument("--snapshots-root", default=str(data_path() / "snapshots"))
    parser.add_argument("--market", default=None, choices=sorted(REGISTRY))
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--through-date", default=None,
                        help=f"Last target date (default and maximum {LAST_REPLAYABLE_DATE}).")
    parser.add_argument("--out", required=True,
                        help="New JSONL file outside data/ (never overwritten).")
    parser.add_argument("--compare-pre-lockin-floor", action="store_true",
                        help="Also replay with the pre-lock-in same-day floor switched off "
                             "and report its effect (one extra replay per snapshot).")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        folders = select_folders(
            args.folders,
            args.snapshots_root,
            market=args.market,
            from_date=lockin._parse_date(args.from_date),
            through_date=lockin._parse_date(args.through_date),
        )
        check_out_path(args.out)
        summary = run(folders, args.out, compare_pre_lockin_floor=args.compare_pre_lockin_floor)
    except ReplayRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"folders": len(folders), "out": str(Path(args.out).resolve()), **summary},
                     indent=2, sort_keys=True))
    if summary["rows_new_below_anchor_exceeds_old"]:
        print(
            "floor check FAILED: {} rows without carry-over put more mass below the anchor "
            "bucket than the old anchor did".format(summary["rows_new_below_anchor_exceeds_old"]),
            file=sys.stderr,
        )
        return FLOOR_CHECK_FAILED_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
