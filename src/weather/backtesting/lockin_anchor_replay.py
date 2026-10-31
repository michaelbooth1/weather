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
  ``replay_inputs_reconstructed.jsonl``) under the snapshots root, plus the
  folder's ``snapshots_long.csv`` band rows when present, so each row also
  carries both arms' band probabilities (computed exactly as production records
  them) and the band's captured market price. With ``--no-market`` the price column is never read and every
  band's ``market_yes`` is null at source. It never reads settlement.
- It writes exactly one new file, ``--out``, which must not exist and must lie
  outside the runtime ``data/`` tree. It never writes production state.
- Replayable target dates are closed days (before today, Toronto) in two ranges:
  development dates <= ``LAST_DEVELOPMENT_DATE`` (2026-09-29) and evening-fix
  scoring dates >= ``EVENING_FIX_FIRST_DATE`` (2026-10-16). The reserved and
  embargoed dates ``EMBARGO_START``..``EMBARGO_END`` (2026-09-30..2026-10-15)
  stay refused: an explicit folder, date bound or record on them is an error,
  and a scan skips them by folder name without opening them.
- The replay itself is outcome-blind. Scoring it is
  ``weather.backtesting.evening_fix_scorer``, which has its own read gate.

CLI:
  python -m weather.backtesting.lockin_anchor_replay --out <path.jsonl>
      [folder ...] [--snapshots-root data/snapshots] [--market MARKET]
      [--from-date YYYY-MM-DD] [--through-date YYYY-MM-DD]
      [--include-reconstructed] [--with-v3-arm] [--no-market]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path

from weather.backtesting.replay import (
    as_int_distribution,
    band_model_probability,
    distribution_l1,
    index_records_by_snapshot,
    is_reconstructed,
    load_replay_records,
    parse_built_at,
    record_target_date,
)
from weather.backtesting.settled_days import folder_market_id
from weather.backtesting.settlement_io import row_band_value_hi
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import REGISTRY
from weather.model.model_constants import TORONTO_TZ
from weather.paths import data_path

LAST_DEVELOPMENT_DATE = date(2026, 9, 29)
EMBARGO_START = date(2026, 9, 30)
EMBARGO_END = date(2026, 10, 15)
EVENING_FIX_FIRST_DATE = date(2026, 10, 16)
# The pre-2026-10-13 name, kept for callers: the last development date.
LAST_REPLAYABLE_DATE = LAST_DEVELOPMENT_DATE
BELOW_ANCHOR_TOLERANCE = 1e-9
FLOOR_CHECK_FAILED_EXIT = 3
HOUR_BLOCKS = (("00-12", 0, 12), ("13-16", 13, 16), ("17-23", 17, 23))


class ReplayRefused(ValueError):
    """A request outside the read-only, closed-date contract."""


def _parse_date(value):
    return date.fromisoformat(str(value)) if value else None


def _today(today=None):
    return today if today is not None else datetime.now(TORONTO_TZ).date()


def in_embargo(target):
    return target is not None and EMBARGO_START <= target <= EMBARGO_END


def replay_refusal(target, today=None):
    """Why ``target`` may not be replayed, or None when it may."""
    if in_embargo(target):
        return (
            f"{target} is inside the reserved/embargo window {EMBARGO_START}..{EMBARGO_END}; "
            "those dates are never replayable by this command"
        )
    if target >= _today(today):
        return f"{target} is not a closed day (today is {_today(today)})"
    return None


def check_date_bounds(from_date=None, through_date=None):
    for flag, value in (("--from-date", from_date), ("--through-date", through_date)):
        if in_embargo(value):
            raise ReplayRefused(
                f"refused: {flag} {value} is inside the reserved/embargo window "
                f"{EMBARGO_START}..{EMBARGO_END}"
            )
    return from_date, through_date


def check_through_date(through_date):
    """Bound check kept for callers; there is no default cap any more."""
    check_date_bounds(through_date=through_date)
    return through_date


def check_out_path(out_path):
    out = Path(out_path).resolve()
    data_root = Path(data_path()).resolve()
    if out == data_root or data_root in out.parents:
        raise ReplayRefused(f"refused: --out {out} is inside the runtime data tree {data_root}")
    if out.exists():
        raise ReplayRefused(f"refused: --out {out} already exists; this command never overwrites")
    return out


def select_folders(folders, snapshots_root, market=None, from_date=None, through_date=None,
                   today=None):
    """Market-day folders to replay; an explicit folder on a refused date is an error.

    A scan skips refused dates by folder name only; it never opens them.
    """
    check_date_bounds(from_date, through_date)
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
        refusal = replay_refusal(target, today)
        if refusal:
            if explicit:
                raise ReplayRefused(f"refused: {folder.name}: {refusal}")
            continue
        if through_date is not None and target > through_date:
            continue
        if from_date is not None and target < from_date:
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


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def band_descriptor(band, no_market=False):
    """The outcome-free description of one captured band row (``market_yes`` null under no_market)."""
    value = band.get("bin_value_c")
    if value in (None, ""):
        value = band.get("bin_value")
    return {
        "label": band.get("range_label"),
        "kind": band.get("bin_kind"),
        "value": _number(value),
        "value_hi": _number(row_band_value_hi(band)),
        "market_yes": None if no_market else _number(band.get("market_yes")),
    }


def _replay(model, record, *, legacy, bands=None, pre_lockin_floor=True):
    """One arm: final vector, payload and (when bands are given) band probabilities.

    Band probabilities are computed inside the arm, because ``bin_probability``
    reads the calibration context that the arm's own estimate just set.
    """
    target = record_target_date(record)
    if target is not None:
        model.set_target_date(target)
    previous = getattr(model, "late_day_lockin_legacy_wu_anchor", False)
    previous_floor = getattr(model, "pre_lockin_same_day_floor", True)
    model.late_day_lockin_legacy_wu_anchor = legacy
    model.pre_lockin_same_day_floor = pre_lockin_floor
    try:
        result = model.estimate_distribution_result(
            record.get("sources") or {}, now=parse_built_at(record),
        )
        band_p = None
        if bands is not None and result.distribution:
            band_p = [band_model_probability(model, result.distribution, band) for band in bands]
    finally:
        model.late_day_lockin_legacy_wu_anchor = previous
        model.pre_lockin_same_day_floor = previous_floor
    payload = result.component_payload or {}
    return as_int_distribution(result.distribution), payload, band_p


def compare_record(model, record, market_id, *, bands=None, event_slug=None, v3_arm=False,
                   today=None, no_market=False):
    """One old-vs-new comparison row, or None when the record has no inputs."""
    if not record.get("sources"):
        return None
    built_at = parse_built_at(record)
    target = record_target_date(record)
    if target is not None:
        refusal = replay_refusal(target, today)
        if refusal:
            raise ReplayRefused(f"refused: record {record.get('snapshot_id')}: {refusal}")
    old, old_payload, old_band_p = _replay(model, record, legacy=True, bands=bands)
    new, new_payload, new_band_p = _replay(model, record, legacy=False, bands=bands)
    anchor = (new_payload.get("high_has_stood_lockin") or {}).get("lockin_anchor") or {}
    bucket = anchor.get("bucket")
    recorded = record.get("recorded_distribution")
    row = {
        "snapshot_id": str(record.get("snapshot_id")),
        "market_id": market_id,
        "event_slug": event_slug,
        "target_date": target.isoformat() if target else None,
        "built_at": built_at.isoformat() if built_at else None,
        "hour": built_at.hour if built_at else None,
        "reconstructed": is_reconstructed(record),
        "model_version": record.get("model_version"),
        "lockin_anchor": anchor,
        "old_lockin_strength": old_payload.get("lockin_strength"),
        "new_lockin_strength": new_payload.get("lockin_strength"),
        "old_mass_above_anchor": _above(old, bucket),
        "new_mass_above_anchor": _above(new, bucket),
        "old_mass_below_anchor": _below(old, bucket),
        "new_mass_below_anchor": _below(new, bucket),
        "l1_new_vs_old": distribution_l1(new, old),
        "l1_old_vs_recorded": distribution_l1(old, recorded) if recorded else None,
        "l1_new_vs_recorded": distribution_l1(new, recorded) if recorded else None,
        "old_final": {str(k): v for k, v in sorted(old.items())},
        "new_final": {str(k): v for k, v in sorted(new.items())},
    }
    if bands is not None:
        row["bands"] = [band_descriptor(band, no_market=no_market) for band in bands]
        row["old_band_p"] = old_band_p
        row["new_band_p"] = new_band_p
    if v3_arm:
        v3, _, v3_band_p = _replay(model, record, legacy=False, bands=bands,
                                   pre_lockin_floor=False)
        row["v3_final"] = {str(k): v for k, v in sorted(v3.items())}
        if bands is not None:
            row["v3_band_p"] = v3_band_p
    return row


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


BAND_COLUMNS = (
    "snapshot_id", "range_label", "bin_kind", "bin_value_c", "bin_value",
    "bin_value_hi_c", "bin_value_hi", "market_yes",
)
NO_MARKET_BAND_COLUMNS = tuple(column for column in BAND_COLUMNS if column != "market_yes")


def load_band_rows(folder, no_market=False):
    """Captured band rows per snapshot from ``snapshots_long.csv`` (outcome-free columns only).

    With ``no_market`` the ``market_yes`` column is never read (nulled at source).
    """
    path = Path(folder) / "snapshots_long.csv"
    if not path.exists():
        return {}
    import pandas as pd

    columns = NO_MARKET_BAND_COLUMNS if no_market else BAND_COLUMNS
    frame = pd.read_csv(path, usecols=lambda column: column in columns)
    if "snapshot_id" not in frame:
        return {}
    frame = frame.astype(object).where(frame.notna(), None)
    bands = {}
    for row in frame.to_dict("records"):
        bands.setdefault(str(row["snapshot_id"]), []).append(row)
    return bands


def run(folders, out_path, *, include_reconstructed=False, model_factory=None, v3_arm=False,
        today=None, no_market=False):
    if model_factory is None:
        from weather.model.toronto_model import TorontoHighTempModel

        def model_factory(market_id):
            return TorontoHighTempModel(market_id=market_id)

    out = check_out_path(out_path)
    models = {}
    rows = []
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        for folder, market_id, target in folders:
            refusal = replay_refusal(target, today)
            if refusal:
                raise ReplayRefused(f"refused: {Path(folder).name}: {refusal}")
            records = index_records_by_snapshot(load_replay_records(folder))
            band_rows = load_band_rows(folder, no_market=no_market)
            if market_id not in models:
                models[market_id] = model_factory(market_id)
            for snapshot_id in sorted(records):
                record = records[snapshot_id]
                if is_reconstructed(record) and not include_reconstructed:
                    continue
                row = compare_record(
                    models[market_id], record, market_id,
                    bands=band_rows.get(str(snapshot_id)),
                    event_slug=Path(folder).name, v3_arm=v3_arm, today=today,
                    no_market=no_market,
                )
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
        description="Read-only, outcome-blind old-vs-new late-day lock-in replay over captured "
                    f"inputs (closed dates <= {LAST_DEVELOPMENT_DATE} or >= {EVENING_FIX_FIRST_DATE}; "
                    f"{EMBARGO_START}..{EMBARGO_END} always refused).",
    )
    parser.add_argument("folders", nargs="*", help="Market-day snapshot folders (default: all).")
    parser.add_argument("--snapshots-root", default=str(data_path() / "snapshots"))
    parser.add_argument("--market", default=None, choices=sorted(REGISTRY))
    parser.add_argument("--from-date", default=None)
    parser.add_argument("--through-date", default=None,
                        help="Last target date (default: the last closed day).")
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--with-v3-arm", action="store_true",
                        help="Also replay v3 without the v4 pre-lock-in floor "
                             "(pre_lockin_same_day_floor = False).")
    parser.add_argument("--no-market", action="store_true",
                        help="Never read captured market prices: band market_yes is null at source.")
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
        summary = run(folders, args.out, include_reconstructed=args.include_reconstructed,
                      v3_arm=args.with_v3_arm, no_market=args.no_market)
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
