"""Old-vs-new late-day lock-in replay over captured inputs (read-only).

The v0.5.11 serving change re-anchors the late-day lock-in stages on
``max(WU history high, guidance physical floor)`` when the WU printed history is
empty. This command replays every captured snapshot of closed market-days
through ``estimate_distribution`` twice with the current code and the active
serving bundle: once with the pre-restoration WU-only anchor
(``late_day_lockin_legacy_wu_anchor = True``) and once as served now. It writes
one JSONL row per snapshot with both final vectors and prints a per-hour-block
summary. The floor check counts rows whose new final vector holds more mass
below the anchor bucket than the old one; any such row makes the command exit
3 (``floor_check: FAIL``). It does not score against settlement or the market; that is the
reviewer's next step on the written rows.

Read-only contract:
- It reads ``replay_inputs.jsonl`` (and, only with ``--include-reconstructed``,
  ``replay_inputs_reconstructed.jsonl``) under the snapshots root.
- It writes exactly one new file, ``--out``, which must not exist and must lie
  outside the runtime ``data/`` tree. It never writes production state.
- It refuses target dates after ``LAST_REPLAYABLE_DATE`` (2026-09-29): later
  dates are held for the reserved 88a panel and the maker-replay evidence.

CLI:
  python -m weather.backtesting.lockin_anchor_replay --out <path.jsonl>
      [folder ...] [--snapshots-root data/snapshots] [--market MARKET]
      [--from-date YYYY-MM-DD] [--through-date YYYY-MM-DD]
      [--include-reconstructed]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from weather.backtesting.replay import (
    as_int_distribution,
    distribution_l1,
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    parse_built_at,
    record_target_date,
)
from weather.backtesting.settled_days import folder_market_id
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import REGISTRY
from weather.paths import data_path

LAST_REPLAYABLE_DATE = date(2026, 9, 29)
BELOW_ANCHOR_TOLERANCE = 1e-9
FLOOR_CHECK_FAILED_EXIT = 3
HOUR_BLOCKS = (("00-12", 0, 12), ("13-16", 13, 16), ("17-23", 17, 23))


class ReplayRefused(ValueError):
    """A request outside the read-only, closed-date contract."""


def _parse_date(value):
    return date.fromisoformat(str(value)) if value else None


def check_through_date(through_date):
    if through_date is not None and through_date > LAST_REPLAYABLE_DATE:
        raise ReplayRefused(
            f"refused: --through-date {through_date} is after {LAST_REPLAYABLE_DATE}; "
            "dates from 2026-09-30 are not replayable by this command"
        )
    return through_date or LAST_REPLAYABLE_DATE


def check_out_path(out_path):
    out = Path(out_path).resolve()
    data_root = Path(data_path()).resolve()
    if out == data_root or data_root in out.parents:
        raise ReplayRefused(f"refused: --out {out} is inside the runtime data tree {data_root}")
    if out.exists():
        raise ReplayRefused(f"refused: --out {out} already exists; this command never overwrites")
    return out


def select_folders(folders, snapshots_root, market=None, from_date=None, through_date=None):
    """Market-day folders to replay; an explicit folder past the cutoff is refused."""
    through_date = check_through_date(through_date)
    explicit = bool(folders)
    candidates = [Path(folder) for folder in folders] if explicit else sorted(
        path for path in Path(snapshots_root).iterdir() if path.is_dir()
    )
    selected = []
    for folder in candidates:
        market_id = folder_market_id(folder)
        target = date_from_event_slug(folder.name)
        if market_id is None or target is None:
            continue
        if target > LAST_REPLAYABLE_DATE:
            if explicit:
                raise ReplayRefused(
                    f"refused: {folder.name} targets {target}, after {LAST_REPLAYABLE_DATE}"
                )
            continue
        if target > through_date or (from_date is not None and target < from_date):
            continue
        if market is not None and market_id != market:
            continue
        selected.append((folder, market_id, target))
    return selected


def _above(distribution, bucket):
    if bucket is None:
        return None
    return sum(p for b, p in distribution.items() if b > bucket)


def _below(distribution, bucket):
    if bucket is None:
        return None
    return sum(p for b, p in distribution.items() if b < bucket)


def _replay(model, record, *, legacy):
    target = record_target_date(record)
    if target is not None:
        model.set_target_date(target)
    previous = getattr(model, "late_day_lockin_legacy_wu_anchor", False)
    model.late_day_lockin_legacy_wu_anchor = legacy
    try:
        result = model.estimate_distribution_result(
            record.get("sources") or {}, now=parse_built_at(record),
        )
    finally:
        model.late_day_lockin_legacy_wu_anchor = previous
    payload = result.component_payload or {}
    return as_int_distribution(result.distribution), payload


def compare_record(model, record, market_id):
    """One old-vs-new comparison row, or None when the record has no inputs."""
    if not record.get("sources"):
        return None
    built_at = parse_built_at(record)
    target = record_target_date(record)
    if target is not None and target > LAST_REPLAYABLE_DATE:
        raise ReplayRefused(f"refused: record targets {target}, after {LAST_REPLAYABLE_DATE}")
    old, old_payload = _replay(model, record, legacy=True)
    new, new_payload = _replay(model, record, legacy=False)
    anchor = (new_payload.get("high_has_stood_lockin") or {}).get("lockin_anchor") or {}
    bucket = anchor.get("bucket")
    recorded = record.get("recorded_distribution")
    return {
        "snapshot_id": str(record.get("snapshot_id")),
        "market_id": market_id,
        "target_date": target.isoformat() if target else None,
        "built_at": built_at.isoformat() if built_at else None,
        "hour": built_at.hour if built_at else None,
        "reconstructed": is_reconstructed(record),
        "lockin_anchor": anchor,
        "old_lockin_strength": old_payload.get("lockin_strength"),
        "new_lockin_strength": new_payload.get("lockin_strength"),
        "old_mass_above_anchor": _above(old, bucket),
        "new_mass_above_anchor": _above(new, bucket),
        "old_mass_below_anchor": _below(old, bucket),
        "new_mass_below_anchor": _below(new, bucket),
        "l1_new_vs_old": distribution_l1(new, old),
        "l1_old_vs_recorded": distribution_l1(old, recorded) if recorded else None,
        "old_final": {str(k): v for k, v in sorted(old.items())},
        "new_final": {str(k): v for k, v in sorted(new.items())},
    }


def summarize(rows):
    blocks = []
    for label, start, end in HOUR_BLOCKS:
        group = [row for row in rows if row["hour"] is not None and start <= row["hour"] <= end]
        anchored = [row for row in group if row["new_mass_above_anchor"] is not None]
        mean = lambda key: (  # noqa: E731
            sum(row[key] for row in anchored) / len(anchored) if anchored else None
        )
        blocks.append({
            "block": label,
            "snapshots": len(group),
            "changed": sum(1 for row in group if row["l1_new_vs_old"] > 1e-12),
            "max_l1_new_vs_old": max((row["l1_new_vs_old"] for row in group), default=None),
            "mean_old_mass_above_anchor": mean("old_mass_above_anchor"),
            "mean_new_mass_above_anchor": mean("new_mass_above_anchor"),
        })
    fidelity = [row["l1_old_vs_recorded"] for row in rows if row["l1_old_vs_recorded"] is not None]
    below_violations = [
        row for row in rows
        if row["new_mass_below_anchor"] is not None
        and row["new_mass_below_anchor"] > row["old_mass_below_anchor"] + BELOW_ANCHOR_TOLERANCE
    ]
    return {
        "snapshots": len(rows),
        "rows_new_below_anchor_exceeds_old": len(below_violations),
        "floor_check": "FAIL" if below_violations else "PASS",
        "blocks": blocks,
        "old_vs_recorded_l1_max": max(fidelity, default=None),
        "old_vs_recorded_rows": len(fidelity),
    }


def run(folders, out_path, *, include_reconstructed=False, model_factory=None):
    if model_factory is None:
        from weather.model.toronto_model import TorontoHighTempModel

        def model_factory(market_id):
            return TorontoHighTempModel(market_id=market_id)

    out = check_out_path(out_path)
    models = {}
    rows = []
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        for folder, market_id, _ in folders:
            records = index_records_by_snapshot(load_replay_records(folder))
            if market_id not in models:
                models[market_id] = model_factory(market_id)
            for snapshot_id in sorted(records):
                record = records[snapshot_id]
                if is_reconstructed(record) and not include_reconstructed:
                    continue
                row = compare_record(models[market_id], record, market_id)
                if row is None:
                    continue
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                rows.append({key: row[key] for key in (
                    "hour", "l1_new_vs_old", "l1_old_vs_recorded",
                    "old_mass_above_anchor", "new_mass_above_anchor",
                    "old_mass_below_anchor", "new_mass_below_anchor",
                )})
    return summarize(rows)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Read-only old-vs-new late-day lock-in replay over captured inputs "
                    f"(closed dates <= {LAST_REPLAYABLE_DATE} only).",
    )
    parser.add_argument("folders", nargs="*", help="Market-day snapshot folders (default: all).")
    parser.add_argument("--snapshots-root", default=str(data_path() / "snapshots"))
    parser.add_argument("--market", default=None, choices=sorted(REGISTRY))
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--through-date", default=None,
                        help=f"Last target date (default and maximum {LAST_REPLAYABLE_DATE}).")
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--out", required=True,
                        help="New JSONL file outside data/ (never overwritten).")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        folders = select_folders(
            args.folders,
            args.snapshots_root,
            market=args.market,
            from_date=_parse_date(args.from_date),
            through_date=_parse_date(args.through_date),
        )
        check_out_path(args.out)
        summary = run(folders, args.out, include_reconstructed=args.include_reconstructed)
    except ReplayRefused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"folders": len(folders), "out": str(Path(args.out).resolve()), **summary},
                     indent=2, sort_keys=True))
    if summary["rows_new_below_anchor_exceeds_old"]:
        print(
            "floor check FAILED: {} rows put more mass below the anchor bucket than the old "
            "anchor did".format(summary["rows_new_below_anchor_exceeds_old"]),
            file=sys.stderr,
        )
        return FLOOR_CHECK_FAILED_EXIT
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
