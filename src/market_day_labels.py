"""CLI wrapper for settlement-ledger finalization."""
import argparse
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from settlement_ledger import (  # noqa: E402
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    LABEL_COLUMNS,
    finalize_folder,
    finalize_folders,
    missing_fraction,
    quality_grade,
    quality_reason,
    write_labels_csv,
)
from settled_days import discover_settled_folders  # noqa: E402


DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"


def discover_default_folders(root=DEFAULT_SNAPSHOTS_ROOT):
    return discover_settled_folders(root, required_file="snapshots_long.csv")


def parse_overrides(items):
    overrides = {}
    for item in items:
        key, _, bucket = item.partition("=")
        overrides[key.strip()] = int(bucket)
    return overrides


def cmd_finalize(args):
    folders = [Path(folder) for folder in args.folders] if args.folders else discover_default_folders(args.snapshots_root)
    labels = finalize_folders(
        folders,
        daily_summary_path=args.daily_summary or None,
        labels_csv=args.labels_csv,
        overrides=parse_overrides(args.settle),
        interval_minutes=args.interval_minutes,
        gap_tolerance=args.tolerance,
        reconcile_polymarket=not args.skip_polymarket_reconciliation,
        ledger_root=args.ledger_root,
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
