"""Finalize market-day settlement labels and collection-quality grades."""
import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import (  # noqa: E402
    DEFAULT_DAILY_SUMMARY,
    DEFAULT_SNAPSHOTS_ROOT,
    load_daily_summary,
    settlement_for_tape,
)
from collection_health import coverage_summary, parse_times  # noqa: E402
from market_config import date_from_event_slug  # noqa: E402
from settled_days import discover_settled_folders  # noqa: E402


DEFAULT_LABELS_CSV = Path("data") / "backtest" / "market_day_labels.csv"
LABEL_COLUMNS = [
    "event_slug",
    "target_date",
    "settlement_bucket",
    "settlement_source",
    "quality_grade",
    "quality_reason",
    "snapshot_count",
    "band_count",
    "row_count",
    "coverage_clean",
    "capture_ratio",
    "max_gap_minutes",
    "coverage_reason",
    "note",
    "finalized_at_utc",
]


def missing_fraction(frame, columns):
    checks = []
    for column in columns:
        if column not in frame:
            checks.append(1.0)
            continue
        checks.append(float(frame[column].isna().mean()))
    return max(checks) if checks else 0.0


def quality_grade(
    snapshot_count,
    band_count,
    settlement_bucket,
    settlement_source,
    missing_core_fraction=0.0,
    collection_clean=True,
):
    if settlement_bucket is None:
        return "missing_settlement"
    if snapshot_count <= 0 or band_count <= 0:
        return "missing_tape"
    if snapshot_count < 6 or not collection_clean:
        return "partial"
    if "sparse" in str(settlement_source):
        return "partial"
    if str(settlement_source) == "override":
        return "manual_override"
    if missing_core_fraction > 0.20:
        return "stale_source"
    return "complete"


def quality_reason(grade, missing_core_fraction, coverage_reason=None):
    if grade == "missing_settlement":
        return "no settlement bucket available"
    if grade == "missing_tape":
        return "snapshot tape missing required rows or bands"
    if grade == "manual_override":
        return "manual settlement override"
    if grade == "partial":
        if coverage_reason and coverage_reason != "ok":
            return f"collection coverage incomplete: {coverage_reason}"
        return "too few snapshots or sparse settlement source"
    if grade == "stale_source":
        return f"core source missing fraction {missing_core_fraction:.1%}"
    return "complete enough for headline scoring"


def captured_times(frame):
    if "captured_at_local" not in frame:
        return []
    rows = frame
    if "snapshot_id" in frame:
        rows = frame.drop_duplicates("snapshot_id")
    return parse_times(rows["captured_at_local"].dropna().astype(str).tolist())


def finalize_folder(
    folder,
    daily_index,
    overrides=None,
    finalized_at=None,
    interval_minutes=10.0,
    gap_tolerance=1.5,
):
    folder = Path(folder)
    tape = folder / "snapshots_long.csv"
    if not tape.exists():
        return None
    frame = pd.read_csv(tape)
    target_date = date_from_event_slug(folder.name)
    bucket, source, note = settlement_for_tape(frame, target_date, daily_index, overrides or {})
    snapshot_count = int(frame["snapshot_id"].nunique()) if "snapshot_id" in frame else 0
    band_count = int(frame["range_label"].nunique()) if "range_label" in frame else 0
    missing_core = missing_fraction(
        frame,
        ["model_probability", "market_yes", "wu_history_high_c"],
    )
    coverage = coverage_summary(captured_times(frame), interval_minutes, gap_tolerance)
    coverage_clean = bool(coverage.get("clean"))
    grade = quality_grade(
        snapshot_count,
        band_count,
        bucket,
        source,
        missing_core,
        collection_clean=coverage_clean,
    )
    finalized_at = finalized_at or datetime.now(timezone.utc)
    label = {
        "event_slug": folder.name,
        "target_date": target_date.isoformat() if target_date else "",
        "settlement_bucket": bucket,
        "settlement_source": source,
        "quality_grade": grade,
        "quality_reason": quality_reason(grade, missing_core, coverage.get("reason")),
        "snapshot_count": snapshot_count,
        "band_count": band_count,
        "row_count": len(frame),
        "coverage_clean": coverage_clean,
        "capture_ratio": coverage.get("capture_ratio"),
        "max_gap_minutes": coverage.get("max_gap_minutes"),
        "coverage_reason": coverage.get("reason"),
        "note": note,
        "finalized_at_utc": finalized_at.isoformat(),
    }
    (folder / "settlement.json").write_text(
        json.dumps(label, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return label


def write_labels_csv(path, labels):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(labels, key=lambda row: row["target_date"])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in ordered:
            writer.writerow(row)


def discover_default_folders(root=DEFAULT_SNAPSHOTS_ROOT):
    return discover_settled_folders(root, required_file="snapshots_long.csv")


def finalize_folders(
    folders,
    daily_summary_path=DEFAULT_DAILY_SUMMARY,
    labels_csv=DEFAULT_LABELS_CSV,
    overrides=None,
    interval_minutes=10.0,
    gap_tolerance=1.5,
):
    daily_index = load_daily_summary(daily_summary_path)
    labels = []
    finalized_at = datetime.now(timezone.utc)
    for folder in folders:
        label = finalize_folder(
            folder,
            daily_index,
            overrides=overrides,
            finalized_at=finalized_at,
            interval_minutes=interval_minutes,
            gap_tolerance=gap_tolerance,
        )
        if label:
            labels.append(label)
    write_labels_csv(labels_csv, labels)
    return labels


def cmd_finalize(args):
    folders = [Path(folder) for folder in args.folders] if args.folders else discover_default_folders(args.snapshots_root)
    overrides = {}
    for item in args.settle:
        date_text, _, bucket = item.partition("=")
        overrides[date_text.strip()] = int(bucket)
    labels = finalize_folders(
        folders,
        args.daily_summary,
        args.labels_csv,
        overrides,
        interval_minutes=args.interval_minutes,
        gap_tolerance=args.tolerance,
    )
    counts = {}
    for label in labels:
        counts[label["quality_grade"]] = counts.get(label["quality_grade"], 0) + 1
    print(f"Wrote {len(labels)} market-day labels to {args.labels_csv}")
    print("Quality grades: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))


def build_parser():
    parser = argparse.ArgumentParser(description="Finalize settlement labels for market-day tapes.")
    sub = parser.add_subparsers(dest="command", required=True)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("folders", nargs="*", help="Snapshot folders. Defaults to settled Toronto tapes.")
    finalize.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    finalize.add_argument("--daily-summary", default=str(DEFAULT_DAILY_SUMMARY))
    finalize.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    finalize.add_argument("--settle", action="append", default=[], help="Force settlement: YYYY-MM-DD=BUCKET")
    finalize.add_argument("--interval-minutes", type=float, default=10.0)
    finalize.add_argument("--tolerance", type=float, default=1.5)
    finalize.set_defaults(func=cmd_finalize)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
