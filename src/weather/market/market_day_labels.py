"""CLI wrapper for settlement-ledger finalization."""
import argparse
from pathlib import Path

from weather.paths import data_path

from weather.backtesting.settled_days import discover_settled_folders
from weather.backtesting.settlement_ledger import (
    COMPLETE_DAY_MIN_ROWS,
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    LABEL_COLUMNS,
    FolderFinalizationError,
    finalize_folder,
    finalize_folders,
    load_daily_summary,
    merge_labels_csv,
    missing_fraction,
    quality_grade,
    quality_reason,
    write_labels_csv,
)
from weather.backtesting.venue_rule_labels import (
    DEFAULT_LABEL_ROOT,
    VENUE_RULE_CUTOVER_DATE,
    default_label_path,
)
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug


class VenueLabelsUnavailable(RuntimeError):
    """A market's venue-rule label CSV is missing; nothing was finalized."""


DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
# Venue-mode group of the folders dated before the cutover (WU daily summary).
WU_HISTORY_GROUP = "_wu_history"


def discover_default_folders(root=DEFAULT_SNAPSHOTS_ROOT):
    return discover_settled_folders(root, required_file="snapshots_long.csv")


def parse_overrides(items):
    overrides = {}
    for item in items:
        key, _, bucket = item.partition("=")
        overrides[key.strip()] = int(bucket)
    return overrides


def venue_label_paths(folders, venue_labels_root=DEFAULT_LABEL_ROOT):
    """Group folders by market with that market's venue-rule label CSV.

    Fails closed: a folder of an unknown market, or a market without a built
    label CSV, stops the run before any ledger write.
    """

    groups = {}
    missing = []
    for folder in folders:
        spec = spec_for_slug(Path(folder).name)
        if spec is None:
            raise VenueLabelsUnavailable(f"--label-rule venue: no market for folder {folder}")
        path = default_label_path(spec, venue_labels_root)
        if not path.exists():
            missing.append(f"{spec.id}: {path}")
        groups.setdefault(spec.id, (path, []))[1].append(Path(folder))
    if missing:
        raise VenueLabelsUnavailable(
            "--label-rule venue: build the venue-rule labels first "
            "(python -m weather.backtesting.venue_rule_labels build); missing " + "; ".join(sorted(set(missing)))
        )
    return groups


def venue_label_gaps(path, folders, cutover=VENUE_RULE_CUTOVER_DATE):
    """Split folders into finalizable ones and refused (folder, reason) pairs.

    A folder dated on or after the cutover is refused when its date has no row
    in the venue CSV, or a row with fewer than ``COMPLETE_DAY_MIN_ROWS`` reports:
    in both cases the ledger would fall back to the tape's WU high.
    """

    index = load_daily_summary(path)
    keep, refused = [], []
    for folder in folders:
        target = date_from_event_slug(Path(folder).name)
        row = index.get(target.isoformat()) if target is not None else None
        if target is None or target < cutover:
            keep.append(folder)
        elif row is None:
            refused.append((str(folder), f"no venue-rule label row for {target.isoformat()} in {path}"))
        elif row["row_count"] < COMPLETE_DAY_MIN_ROWS:
            refused.append((
                str(folder),
                f"venue-rule label for {target.isoformat()} has {row['row_count']} reports, "
                f"fewer than {COMPLETE_DAY_MIN_ROWS}, in {path}",
            ))
        else:
            keep.append(folder)
    return keep, refused


def venue_label_plan(folders, venue_labels_root=DEFAULT_LABEL_ROOT, cutover=VENUE_RULE_CUTOVER_DATE):
    """Route ``--label-rule venue`` folders to the daily summary that labels them.

    Returns ``(groups, refused)``. ``groups`` is a list of
    ``(group_name, daily_summary_path, folders)``: one ``WU_HISTORY_GROUP`` group
    (``daily_summary_path`` None, so each market's WU daily summary, exactly as
    ``--label-rule wu``) holding every folder dated before the cutover, then
    one group per market holding its folders dated on or after the cutover,
    labelled from that market's venue-rule CSV. ``refused`` lists the
    ``(folder, reason)`` pairs ``venue_label_gaps`` refuses. A missing CSV still
    raises ``VenueLabelsUnavailable`` before anything is planned.
    """

    wu_folders, groups, refused = [], [], []
    for market_id, (path, group) in sorted(venue_label_paths(folders, venue_labels_root).items()):
        group, gaps = venue_label_gaps(path, group, cutover)
        refused.extend(gaps)
        venue_folders = []
        for folder in group:
            target = date_from_event_slug(Path(folder).name)
            (wu_folders if target is not None and target < cutover else venue_folders).append(folder)
        if venue_folders:
            groups.append((market_id, path, venue_folders))
    if wu_folders:
        groups.insert(0, (WU_HISTORY_GROUP, None, wu_folders))
    return groups, refused


def finalize_with_venue_labels(folders, args, finalize_kwargs):
    """Finalize folders under the venue rule, routed by ``venue_label_plan``.

    Folders dated before the cutover finalize against each market's WU daily
    summary, identical to ``--label-rule wu``; later folders finalize against
    their market's venue-rule label CSV. Each group writes a scratch labels
    CSV; the real labels CSV is then written whole (or merged when a group
    failed), as ``finalize_folders`` does. Folders without a usable
    post-cutover label row are refused and reported as failures after the
    others are written.
    """

    labels = []
    groups, failures = venue_label_plan(folders, args.venue_labels_root)
    scratch_root = Path(args.ledger_root) / "_venue_rule_finalize"
    for name, path, group in groups:
        scratch = scratch_root / f"{name}_labels.csv"
        try:
            labels.extend(finalize_folders(group, daily_summary_path=path, labels_csv=scratch, **finalize_kwargs))
        except FolderFinalizationError as exc:
            labels.extend(exc.labels)
            failures.extend(exc.failures)
        finally:
            scratch.unlink(missing_ok=True)
    if failures:
        merge_labels_csv(args.labels_csv, labels)
        raise FolderFinalizationError(failures, labels=labels)
    write_labels_csv(args.labels_csv, labels)
    return labels


def cmd_finalize(args):
    folders = [Path(folder) for folder in args.folders] if args.folders else discover_default_folders(args.snapshots_root)
    finalize_kwargs = dict(
        overrides=parse_overrides(args.settle),
        interval_minutes=args.interval_minutes,
        gap_tolerance=args.tolerance,
        reconcile_polymarket=not args.skip_polymarket_reconciliation,
        ledger_root=args.ledger_root,
    )
    if args.label_rule == "venue":
        if args.daily_summary:
            raise SystemExit("--daily-summary and --label-rule venue are mutually exclusive")
        try:
            labels = finalize_with_venue_labels(folders, args, finalize_kwargs)
        except VenueLabelsUnavailable as exc:
            raise SystemExit(str(exc)) from exc
    else:
        labels = finalize_folders(
            folders,
            daily_summary_path=args.daily_summary or None,
            labels_csv=args.labels_csv,
            **finalize_kwargs,
        )
    counts = {}
    reconciliation_counts = {}
    for label in labels:
        counts[label["quality_grade"]] = counts.get(label["quality_grade"], 0) + 1
        status = label.get("reconciliation_status") or "-"
        reconciliation_counts[status] = reconciliation_counts.get(status, 0) + 1

    print(f"Wrote {len(labels)} market-day labels to {args.labels_csv}")
    print(f"Wrote per-market ledgers under {args.ledger_root}")
    print("Quality grades: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print("Polymarket reconciliation: " + ", ".join(
        f"{key}={value}" for key, value in sorted(reconciliation_counts.items())
    ))
    mismatches = [label for label in labels if label.get("reconciliation_status") == "mismatch"]
    for label in mismatches:
        print(
            "ALERT mismatch: "
            f"{label['event_slug']} ledger={label.get('winning_band')} "
            f"polymarket={label.get('polymarket_winning_band')}"
        )


def build_parser():
    parser = argparse.ArgumentParser(description="Finalize settlement labels into the settlement ledger.")
    sub = parser.add_subparsers(dest="command", required=True)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("folders", nargs="*", help="Snapshot folders. Defaults to all settled tapes.")
    finalize.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    finalize.add_argument(
        "--daily-summary",
        default="",
        help="Optional override daily-summary CSV. Empty uses each market's registry data root.",
    )
    finalize.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    finalize.add_argument(
        "--label-rule",
        choices=("wu", "venue"),
        default="wu",
        help="wu (default): each market's WU daily summary. venue: each market's venue-rule label CSV "
        "(WU before the cutover date, routine METAR from it); see docs/operations/venue-rule-labels.md.",
    )
    finalize.add_argument("--venue-labels-root", default=str(DEFAULT_LABEL_ROOT))
    finalize.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    finalize.add_argument(
        "--settle",
        action="append",
        default=[],
        help="Force settlement: EVENT_SLUG=BUCKET, MARKET:YYYY-MM-DD=BUCKET, or YYYY-MM-DD=BUCKET.",
    )
    finalize.add_argument("--interval-minutes", type=float, default=10.0)
    finalize.add_argument("--tolerance", type=float, default=1.5)
    finalize.add_argument(
        "--skip-polymarket-reconciliation",
        action="store_true",
        help="Do not fetch Gamma resolved outcomes during finalization.",
    )
    finalize.set_defaults(func=cmd_finalize)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
