"""CLI wrapper for settlement-ledger finalization."""
import argparse
from pathlib import Path

from weather.paths import data_path

from weather.backtesting.settled_days import discover_settled_folders
from weather.backtesting.settlement_ledger import (
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    LABEL_COLUMNS,
    FolderFinalizationError,
    finalize_folder,
    finalize_folders,
    merge_labels_csv,
    missing_fraction,
    quality_grade,
    quality_reason,
    write_labels_csv,
)
from weather.backtesting.venue_rule_labels import DEFAULT_LABEL_ROOT, default_label_path
from weather.market.market_registry import spec_for_slug


DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"


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
            raise SystemExit(f"--label-rule venue: no market for folder {folder}")
        path = default_label_path(spec, venue_labels_root)
        if not path.exists():
            missing.append(f"{spec.id}: {path}")
        groups.setdefault(spec.id, (path, []))[1].append(Path(folder))
    if missing:
        raise SystemExit(
            "--label-rule venue: build the venue-rule labels first "
            "(python -m weather.backtesting.venue_rule_labels build); missing " + "; ".join(sorted(set(missing)))
        )
    return groups


def finalize_with_venue_labels(folders, args, finalize_kwargs):
    """Finalize each market's folders against its venue-rule label CSV.

    Each market group writes a scratch labels CSV; the real labels CSV is then
    written whole (or merged when a group failed), as ``finalize_folders`` does.
    """

    labels = []
    failures = []
    scratch_root = Path(args.ledger_root) / "_venue_rule_finalize"
    for market_id, (path, group) in sorted(venue_label_paths(folders, args.venue_labels_root).items()):
        scratch = scratch_root / f"{market_id}_labels.csv"
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
        labels = finalize_with_venue_labels(folders, args, finalize_kwargs)
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
