"""Freshness gate and repair helper for newly settled market-day labels."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.backtesting.settlement_ledger import (
    COMPLETE_DAY_MIN_ROWS,
    DEFAULT_LABELS_CSV,
    DEFAULT_LEDGER_ROOT,
    daily_summary_path_for_spec,
    finalize_folder,
    ledger_path_for_market,
    load_daily_summary,
    read_jsonl,
    resolve_ledger_root,
    upsert_ledger_record,
    write_folder_label,
    write_labels_csv,
    write_resolution_specs,
)
from weather.backtesting.replay import REPLAY_INPUTS_FILENAME, REPLAY_STATUS_LONG_FILENAME
from weather.market.market_config import event_slug_for_date
from weather.market.market_registry import all_specs
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("settled_day_freshness")
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "settled_day_freshness.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "settled_day_freshness_report.md"
TORONTO_TZ = ZoneInfo("America/Toronto")
FALLBACK_SETTLEMENT_SOURCES = {"snapshot_high", "daily_summary(sparse)", "none"}


def truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def read_labels_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def labels_by_slug(path):
    return {
        row.get("event_slug"): row
        for row in read_labels_csv(path)
        if row.get("event_slug")
    }


def ledger_by_slug(ledger_root, specs):
    rows = {}
    for spec in specs:
        for row in read_jsonl(ledger_path_for_market(spec.id, ledger_root)):
            slug = row.get("event_slug")
            if slug:
                rows[slug] = row
    return rows


def merge_labels_csv(path, labels):
    if not labels:
        return []
    existing = labels_by_slug(path)
    for label in labels:
        slug = label.get("event_slug")
        if slug:
            existing[slug] = dict(label)
    write_labels_csv(path, existing.values())
    return list(existing.values())


def parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def target_date_from_args(*, target_date=None, as_of=None):
    explicit = parse_date(target_date)
    if explicit:
        return explicit
    as_of_date = parse_date(as_of)
    if as_of_date:
        return as_of_date - timedelta(days=1)
    return datetime.now(TORONTO_TZ).date() - timedelta(days=1)


def selected_specs(market_ids=None):
    ids = {str(market_id).strip() for market_id in market_ids or [] if str(market_id).strip()}
    specs = all_specs()
    if ids:
        specs = [spec for spec in specs if spec.id in ids]
    return specs


def daily_summary_status(spec, target_date):
    path = daily_summary_path_for_spec(spec)
    index = load_daily_summary(path)
    keys = sorted(index)
    target_key = target_date.isoformat()
    target = index.get(target_key)
    latest_key = keys[-1] if keys else None
    if not path.exists():
        status = "missing_file"
    elif target and int(target.get("row_count") or 0) >= COMPLETE_DAY_MIN_ROWS:
        status = "current"
    elif target:
        status = "sparse"
    elif latest_key and latest_key < target_key:
        status = "stale"
    elif latest_key:
        status = "missing_target"
    else:
        status = "empty"
    return {
        "path": str(path),
        "exists": path.exists(),
        "status": status,
        "target_date": target_key,
        "latest_date": latest_key,
        "target_row_count": target.get("row_count") if target else None,
        "target_bucket": target.get("bucket") if target else None,
    }


def market_row(spec, target_date, snapshots_root, labels, ledgers, ledger_root):
    slug = event_slug_for_date(target_date, spec.id)
    folder = Path(snapshots_root) / slug
    tape = folder / "snapshots_long.csv"
    settlement_path = folder / "settlement.json"
    replay_status_path = folder / REPLAY_STATUS_LONG_FILENAME
    replay_inputs_path = folder / REPLAY_INPUTS_FILENAME
    source_status_path = folder / "source_status_long.csv"
    folder_label = read_json(settlement_path)
    label_csv_row = labels.get(slug) or {}
    ledger_row = ledgers.get(slug) or {}
    best_label = ledger_row or folder_label or label_csv_row
    source = best_label.get("settlement_source")
    summary_status = daily_summary_status(spec, target_date)

    folder_exists = folder.exists()
    tape_exists = tape.exists()
    label_csv_exists = bool(label_csv_row)
    ledger_exists = bool(ledger_row)
    settlement_json_exists = bool(folder_label)
    replay_status_exists = replay_status_path.exists()
    replay_inputs_exists = replay_inputs_path.exists()
    source_status_exists = source_status_path.exists()
    missing = []
    if not folder_exists:
        missing.append("folder")
    if not tape_exists:
        missing.append("snapshots_long.csv")
    if not label_csv_exists:
        missing.append("labels_csv")
    if not ledger_exists:
        missing.append("ledger")
    if not settlement_json_exists:
        missing.append("settlement_json")
    if not replay_status_exists:
        missing.append(REPLAY_STATUS_LONG_FILENAME)
    if not replay_inputs_exists:
        missing.append(REPLAY_INPUTS_FILENAME)
    if not source_status_exists:
        missing.append("source_status_long.csv")

    needs_finalization = bool(
        folder_exists
        and tape_exists
        and (not label_csv_exists or not ledger_exists or not settlement_json_exists)
    )
    needs_replay_status_repair = bool(
        folder_exists
        and tape_exists
        and (not replay_status_exists or not replay_inputs_exists or not source_status_exists)
    )
    source_lag_warning = bool(
        source in FALLBACK_SETTLEMENT_SOURCES
        and summary_status.get("status") not in {"current", "sparse"}
    )
    return {
        "market_id": spec.id,
        "city": spec.city_label,
        "event_slug": slug,
        "target_date": target_date.isoformat(),
        "folder_path": str(folder),
        "snapshots_long_path": str(tape),
        "settlement_json_path": str(settlement_path),
        "replay_status_long_path": str(replay_status_path),
        "replay_inputs_path": str(replay_inputs_path),
        "source_status_path": str(source_status_path),
        "ledger_path": str(ledger_path_for_market(spec.id, ledger_root)),
        "folder_exists": folder_exists,
        "snapshots_long_exists": tape_exists,
        "labels_csv_exists": label_csv_exists,
        "ledger_exists": ledger_exists,
        "settlement_json_exists": settlement_json_exists,
        "replay_status_long_exists": replay_status_exists,
        "replay_inputs_exists": replay_inputs_exists,
        "source_status_exists": source_status_exists,
        "canonical_complete": not missing,
        "missing_requirements": missing,
        "needs_finalization": needs_finalization,
        "needs_replay_status_repair": needs_replay_status_repair,
        "settlement_source": source,
        "settlement_bucket": best_label.get("settlement_bucket"),
        "winning_band": best_label.get("winning_band"),
        "quality_grade": best_label.get("quality_grade"),
        "material_coverage_grade": best_label.get("material_coverage_grade"),
        "material_coverage_reason": best_label.get("material_coverage_reason"),
        "material_coverage_window": best_label.get("material_coverage_window"),
        "material_coverage_gap_count": best_label.get("material_coverage_gap_count"),
        "material_coverage_max_gap_minutes": best_label.get("material_coverage_max_gap_minutes"),
        "material_peak_gap_minutes": best_label.get("material_peak_gap_minutes"),
        "material_coverage_decisive_gap_count": best_label.get("material_coverage_decisive_gap_count"),
        "material_coverage_gap_windows": best_label.get("material_coverage_gap_windows"),
        "promotion_countable": truthy(best_label.get("promotion_countable")),
        "promotion_countable_reason": best_label.get("promotion_countable_reason"),
        "reconciliation_status": best_label.get("reconciliation_status"),
        "daily_summary": summary_status,
        "source_lag_warning": source_lag_warning,
    }


def repair_command(target_date, snapshots_root, labels_csv, ledger_root, market_ids=None):
    command = [
        sys.executable,
        "-m",
        "weather.operations.settled_day_freshness",
        "repair",
        "--target-date",
        target_date.isoformat(),
        "--snapshots-root",
        str(snapshots_root),
        "--labels-csv",
        str(labels_csv),
        "--ledger-root",
        str(ledger_root),
    ]
    if market_ids:
        command += ["--markets", ",".join(market_ids)]
    return " ".join(command)


def replay_status_repair_command(target_date, snapshots_root, market_ids=None):
    command = [
        sys.executable,
        "-m",
        "weather.operations.replay_status_backfill",
        "--snapshots-root",
        str(snapshots_root),
        "--as-of",
        (target_date + timedelta(days=1)).isoformat(),
    ]
    if market_ids:
        command.append("# markets: " + ",".join(market_ids))
    return " ".join(command)


def summarize_rows(rows):
    incomplete = [row for row in rows if not row.get("canonical_complete")]
    needs_finalization = [row for row in rows if row.get("needs_finalization")]
    source_lag = [row for row in rows if row.get("source_lag_warning")]
    quality_counts = {}
    material_coverage_counts = {}
    material_rows = []
    for row in rows:
        grade = row.get("quality_grade") or "missing"
        quality_counts[grade] = quality_counts.get(grade, 0) + 1
        material_grade = row.get("material_coverage_grade") or "missing"
        material_coverage_counts[material_grade] = material_coverage_counts.get(material_grade, 0) + 1
        if row.get("material_coverage_grade"):
            material_rows.append(row)
    status = "PASS"
    if incomplete:
        status = "FAIL"
    elif source_lag:
        status = "WARN"
    return {
        "status": status,
        "expected_market_count": len(rows),
        "complete_market_count": len(rows) - len(incomplete),
        "incomplete_market_count": len(incomplete),
        "needs_finalization_count": len(needs_finalization),
        "needs_replay_status_repair_count": sum(1 for row in rows if row.get("needs_replay_status_repair")),
        "missing_label_count": sum(1 for row in rows if not row.get("labels_csv_exists")),
        "missing_ledger_count": sum(1 for row in rows if not row.get("ledger_exists")),
        "missing_settlement_json_count": sum(1 for row in rows if not row.get("settlement_json_exists")),
        "missing_replay_status_count": sum(1 for row in rows if not row.get("replay_status_long_exists")),
        "missing_replay_inputs_count": sum(1 for row in rows if not row.get("replay_inputs_exists")),
        "missing_source_status_count": sum(1 for row in rows if not row.get("source_status_exists")),
        "missing_tape_count": sum(1 for row in rows if not row.get("snapshots_long_exists")),
        "source_lag_warning_count": len(source_lag),
        "quality_counts": dict(sorted(quality_counts.items())),
        "partial_label_count": quality_counts.get("partial", 0),
        "material_coverage_counts": dict(sorted(material_coverage_counts.items())),
        "promotion_countability_available": bool(material_rows),
        "promotion_countable_label_count": sum(1 for row in material_rows if row.get("promotion_countable")),
        "promotion_blocked_label_count": sum(1 for row in material_rows if row.get("promotion_countable") is False),
    }


def build_freshness_payload(
    *,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    labels_csv=DEFAULT_LABELS_CSV,
    ledger_root=DEFAULT_LEDGER_ROOT,
    target_date=None,
    as_of=None,
    market_ids=None,
):
    target = target_date_from_args(target_date=target_date, as_of=as_of)
    specs = selected_specs(market_ids)
    labels = labels_by_slug(labels_csv)
    ledger_root = resolve_ledger_root(ledger_root)
    ledgers = ledger_by_slug(ledger_root, specs)
    rows = [
        market_row(spec, target, snapshots_root, labels, ledgers, ledger_root)
        for spec in specs
    ]
    summary = summarize_rows(rows)
    market_id_list = [spec.id for spec in specs]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": summary["status"],
        "target_date": target.isoformat(),
        "as_of": str(as_of or ""),
        "snapshots_root": str(snapshots_root),
        "labels_csv": str(labels_csv),
        "ledger_root": str(ledger_root),
        "markets": rows,
        "summary": summary,
        "repair_command": repair_command(target, snapshots_root, labels_csv, ledger_root, market_id_list if market_ids else None),
        "replay_status_repair_command": replay_status_repair_command(
            target,
            snapshots_root,
            market_id_list if market_ids else None,
        ),
    }


def label_source_for(row, labels, ledgers):
    slug = row.get("event_slug")
    folder_label = read_json(Path(row.get("settlement_json_path") or ""))
    return ledgers.get(slug) or folder_label or labels.get(slug) or {}


def repair_missing_settlements(
    *,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    labels_csv=DEFAULT_LABELS_CSV,
    ledger_root=DEFAULT_LEDGER_ROOT,
    target_date=None,
    as_of=None,
    market_ids=None,
    reconcile_polymarket=True,
):
    ledger_root = resolve_ledger_root(ledger_root)
    before = build_freshness_payload(
        snapshots_root=snapshots_root,
        labels_csv=labels_csv,
        ledger_root=ledger_root,
        target_date=target_date,
        as_of=as_of,
        market_ids=market_ids,
    )
    specs = selected_specs(market_ids)
    write_resolution_specs(Path(ledger_root) / "resolution_specs.json", specs=specs)
    labels = labels_by_slug(labels_csv)
    ledgers = ledger_by_slug(ledger_root, specs)
    labels_to_merge = []
    finalized = []
    restored_from_existing = []
    skipped = []

    for row in before["markets"]:
        if not row.get("needs_finalization"):
            continue
        folder = Path(row["folder_path"])
        if not row.get("folder_exists") or not row.get("snapshots_long_exists"):
            skipped.append({
                "event_slug": row.get("event_slug"),
                "market_id": row.get("market_id"),
                "reason": "missing_folder_or_snapshots_long",
            })
            continue

        source = label_source_for(row, labels, ledgers)
        if source:
            source = dict(source)
            if not row.get("ledger_exists"):
                path = upsert_ledger_record(source, ledger_root)
                source["ledger_path"] = str(path)
                ledgers[source["event_slug"]] = source
            if not row.get("settlement_json_exists"):
                write_folder_label(folder, source)
            if not row.get("labels_csv_exists"):
                labels_to_merge.append(source)
                labels[source["event_slug"]] = source
            restored_from_existing.append(row.get("event_slug"))
            continue

        label = finalize_folder(
            folder,
            reconcile_polymarket=reconcile_polymarket,
            ledger_root=ledger_root,
        )
        if label:
            labels_to_merge.append(label)
            labels[label["event_slug"]] = label
            ledgers[label["event_slug"]] = label
            finalized.append(label["event_slug"])
        else:
            skipped.append({
                "event_slug": row.get("event_slug"),
                "market_id": row.get("market_id"),
                "reason": "finalize_folder_returned_no_label",
            })

    if labels_to_merge:
        merge_labels_csv(labels_csv, labels_to_merge)

    after = build_freshness_payload(
        snapshots_root=snapshots_root,
        labels_csv=labels_csv,
        ledger_root=ledger_root,
        target_date=target_date,
        as_of=as_of,
        market_ids=market_ids,
    )
    after["repair"] = {
        "attempted": before["summary"]["needs_finalization_count"],
        "finalized_event_slugs": finalized,
        "restored_from_existing_event_slugs": restored_from_existing,
        "skipped": skipped,
        "before_summary": before["summary"],
        "after_summary": after["summary"],
    }
    return after


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Settled-Day Freshness",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        f"Target date: `{payload.get('target_date')}`",
        f"Snapshots root: `{payload.get('snapshots_root')}`",
        f"Labels CSV: `{payload.get('labels_csv')}`",
        f"Ledger root: `{payload.get('ledger_root')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Expected markets", summary.get("expected_market_count")],
            ["Complete markets", summary.get("complete_market_count")],
            ["Incomplete markets", summary.get("incomplete_market_count")],
            ["Needs finalization", summary.get("needs_finalization_count")],
            ["Needs replay-status repair", summary.get("needs_replay_status_repair_count")],
            ["Missing labels", summary.get("missing_label_count")],
            ["Missing ledgers", summary.get("missing_ledger_count")],
            ["Missing folder settlements", summary.get("missing_settlement_json_count")],
            ["Missing replay status", summary.get("missing_replay_status_count")],
            ["Missing replay inputs", summary.get("missing_replay_inputs_count")],
            ["Missing source status", summary.get("missing_source_status_count")],
            ["Missing tapes", summary.get("missing_tape_count")],
            ["Source-lag warnings", summary.get("source_lag_warning_count")],
            ["Repair command", payload.get("repair_command")],
            ["Replay-status repair command", payload.get("replay_status_repair_command")],
        ],
    )
    lines += ["", "## Markets", ""]
    lines += markdown_table(
        [
            "Market",
            "Complete",
            "Needs Finalization",
            "Needs Replay Repair",
            "Missing",
            "Source",
            "Daily Summary",
            "Winning Band",
            "Material Coverage",
            "Promotion Countable",
        ],
        [
            [
                row.get("market_id"),
                row.get("canonical_complete"),
                row.get("needs_finalization"),
                row.get("needs_replay_status_repair"),
                ", ".join(row.get("missing_requirements") or []) or "-",
                row.get("settlement_source") or "-",
                (row.get("daily_summary") or {}).get("status"),
                row.get("winning_band") or "-",
                row.get("material_coverage_grade") or "-",
                row.get("promotion_countable"),
            ]
            for row in payload.get("markets") or []
        ],
    )
    repair = payload.get("repair") or {}
    if repair:
        lines += [
            "",
            "## Repair",
            "",
        ]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Attempted", repair.get("attempted")],
                ["Finalized", ", ".join(repair.get("finalized_event_slugs") or []) or "-"],
                ["Restored from existing", ", ".join(repair.get("restored_from_existing_event_slugs") or []) or "-"],
                ["Skipped", len(repair.get("skipped") or [])],
            ],
        )
    lines.append("")
    return "\n".join(lines)


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def write_outputs(payload, json_out, report_out):
    json_path = write_json(json_out, payload)
    report_path = write_report(report_out, payload)
    return json_path, report_path


def parse_market_ids(value):
    if not value:
        return None
    return [part.strip() for part in str(value).split(",") if part.strip()]


def add_common_args(parser):
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--target-date", default="")
    parser.add_argument("--as-of", default="")
    parser.add_argument("--markets", default="")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def cmd_report(args):
    payload = build_freshness_payload(
        snapshots_root=args.snapshots_root,
        labels_csv=args.labels_csv,
        ledger_root=args.ledger_root,
        target_date=args.target_date,
        as_of=args.as_of,
        market_ids=parse_market_ids(args.markets),
    )
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(f"Settled-day freshness: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 2 if payload["status"] == "FAIL" else 0


def cmd_repair(args):
    payload = repair_missing_settlements(
        snapshots_root=args.snapshots_root,
        labels_csv=args.labels_csv,
        ledger_root=args.ledger_root,
        target_date=args.target_date,
        as_of=args.as_of,
        market_ids=parse_market_ids(args.markets),
        reconcile_polymarket=not args.skip_polymarket_reconciliation,
    )
    json_path, report_path = write_outputs(payload, args.json_out, args.report_out)
    print(f"Settled-day freshness: {payload['status']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 2 if payload["status"] == "FAIL" else 0


def build_parser():
    parser = argparse.ArgumentParser(description="Report and repair settled-day finalization freshness.")
    sub = parser.add_subparsers(dest="command", required=True)
    report = add_common_args(sub.add_parser("report"))
    report.set_defaults(func=cmd_report)
    repair = add_common_args(sub.add_parser("repair"))
    repair.add_argument("--skip-polymarket-reconciliation", action="store_true")
    repair.set_defaults(func=cmd_repair)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
