"""Historical feature-quality quarantine manifest.

This audit protects training and promotion evidence from legacy feature rows
that predate the live current-max and startup-observation guards. Runtime
serving can keep scoring those snapshots, but bad historical feature evidence
must be either reconstructed from raw observations or excluded from training
and promotion eligibility.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.paths import data_path
from weather.reporting.formatting import markdown_table


SCHEMA_VERSION = "feature_quality_quarantine_v0.1"
FOLDER_SCHEMA_VERSION = "feature_quality_quarantine_folder_v0.1"
SUMMARY_SCHEMA_VERSION = "feature_quality_quarantine_summary_v0.1"

DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_JSON_OUT = data_path() / "backtest" / "feature_quality_quarantine.json"
DEFAULT_CSV_OUT = data_path() / "backtest" / "feature_quality_quarantine.csv"
DEFAULT_REPORT_OUT = data_path() / "backtest" / "feature_quality_quarantine_report.md"

FEATURES_LONG = "features_long.csv"
SNAPSHOTS_LONG = "snapshots_long.csv"
REPLAY_INPUTS = "replay_inputs.jsonl"

STARTUP_FEATURE_FIELDS = ("high_so_far", "current_temp", "live_reading_temp")
FEATURE_CURRENT_MAX_FIELDS = (
    "trusted_current_max",
    "support_only_current_max",
    "quarantined_current_max",
)
SIDECAR_CURRENT_MAX_FIELDS = (
    "wu_max_since_7am_c",
    "max_since_7am_native",
    "max_since_7am_c",
)
SIDECAR_SUPPORT_FIELDS = (
    "wu_history_high_c",
    "wu_current_c",
    "eccc_swob_max_c",
)
CURRENT_MAX_GAP_THRESHOLD = 10.0

CSV_FIELDS = [
    "event_slug",
    "market_id",
    "target_date",
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "source_file",
    "feature_field",
    "observed_value",
    "comparison_value",
    "comparison_field",
    "reason",
    "disposition",
    "training_excluded",
    "promotion_excluded",
    "score_only",
    "raw_evidence_available",
    "backfill_status",
    "replay_input_present",
    "replay_input_feature_contaminated",
    "folder",
]


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def safe_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    number = safe_float(value)
    if number is None:
        return None
    return int(number)


def parse_dt(value):
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def folder_unit(folder):
    folder = Path(folder)
    settlement = folder / "settlement.json"
    if settlement.exists():
        try:
            payload = json.loads(settlement.read_text(encoding="utf-8"))
            unit = payload.get("settlement_unit")
            if unit:
                return str(unit).upper()
        except (OSError, json.JSONDecodeError):
            pass
    spec = spec_for_slug(folder.name)
    return str(getattr(spec, "display_unit", None) or "F").upper()


def plausible_temperature(value, unit):
    number = safe_float(value)
    if number is None:
        return True
    if str(unit).upper() == "F":
        return 30.0 <= number <= 125.0
    return -45.0 <= number <= 55.0


def raw_evidence_available(folder):
    folder = Path(folder)
    return any(
        (folder / name).exists()
        for name in (
            "observation_payloads_long.csv",
            "observation_payloads.jsonl",
            "observation_payloads",
        )
    )


def disposition_for_raw_evidence(has_raw):
    if has_raw:
        return "training_excluded_pending_backfill", "raw_observation_payload_available"
    return "training_excluded_no_raw_evidence", "raw_evidence_absent"


def folder_context(folder):
    folder = Path(folder)
    spec = spec_for_slug(folder.name)
    target_date = date_from_event_slug(folder.name)
    return {
        "event_slug": folder.name,
        "market_id": getattr(spec, "id", None),
        "target_date": target_date.isoformat() if target_date else None,
        "unit": folder_unit(folder),
        "raw_evidence_available": raw_evidence_available(folder),
    }


def first_nonempty(row, names):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value, name
    return None, None


def capture_hour(row):
    dt = parse_dt(row.get("captured_at_local")) or parse_dt(row.get("captured_at_utc"))
    if dt is not None:
        return dt.hour
    return safe_int(row.get("cutoff_hour"))


def make_row(folder, context, source_file, source, field, value, reason, *, comparison_value=None, comparison_field=None):
    disposition, backfill_status = disposition_for_raw_evidence(context["raw_evidence_available"])
    return {
        "event_slug": source.get("event_slug") or context["event_slug"],
        "market_id": context["market_id"],
        "target_date": source.get("target_date") or context["target_date"],
        "snapshot_id": str(source.get("snapshot_id") or ""),
        "captured_at_utc": source.get("captured_at_utc") or "",
        "captured_at_local": source.get("captured_at_local") or "",
        "source_file": source_file,
        "feature_field": field,
        "observed_value": value,
        "comparison_value": comparison_value,
        "comparison_field": comparison_field,
        "reason": reason,
        "disposition": disposition,
        "training_excluded": True,
        "promotion_excluded": True,
        "score_only": True,
        "raw_evidence_available": bool(context["raw_evidence_available"]),
        "backfill_status": backfill_status,
        "replay_input_present": False,
        "replay_input_feature_contaminated": False,
        "folder": str(folder),
    }


def feature_rows_for_folder(folder, context, feature_rows):
    output = []
    unit = context["unit"]
    for row in feature_rows:
        hour = capture_hour(row)
        startup_context = hour is not None and hour < 7
        for field in STARTUP_FEATURE_FIELDS:
            value = row.get(field)
            if value in (None, ""):
                continue
            if plausible_temperature(value, unit):
                continue
            reason = (
                "startup_live_observation_implausible"
                if startup_context or safe_float(value) == 17.0
                else "unit_implausible_live_observation"
            )
            output.append(make_row(folder, context, FEATURES_LONG, row, field, value, reason))

        disposition = str(row.get("current_max_disposition") or "").lower()
        flag = safe_float(row.get("current_max_quarantined_flag"))
        if disposition == "quarantined" or (flag is not None and flag > 0):
            value, field = first_nonempty(row, FEATURE_CURRENT_MAX_FIELDS)
            field = field or "current_max_disposition"
            reason = row.get("current_max_quarantine_reason") or "current_max_quarantined_by_feature_schema"
            output.append(make_row(folder, context, FEATURES_LONG, row, field, value, reason))
            continue

        current_max, field = first_nonempty(row, FEATURE_CURRENT_MAX_FIELDS)
        if field is None:
            continue
        current_max_value = safe_float(current_max)
        if current_max_value is None:
            continue
        if not plausible_temperature(current_max_value, unit):
            output.append(
                make_row(
                    folder,
                    context,
                    FEATURES_LONG,
                    row,
                    field,
                    current_max,
                    "implausible_current_max_unit",
                )
            )
            continue
        supports = [
            (name, safe_float(row.get(name)))
            for name in ("high_so_far", "current_temp", "live_reading_temp", "latest_wu_history_temp")
        ]
        supports = [(name, value) for name, value in supports if value is not None]
        if supports:
            comparison_field, comparison_value = max(supports, key=lambda item: item[1])
            if current_max_value - comparison_value >= CURRENT_MAX_GAP_THRESHOLD:
                output.append(
                    make_row(
                        folder,
                        context,
                        FEATURES_LONG,
                        row,
                        field,
                        current_max,
                        "current_max_exceeds_observed_support",
                        comparison_value=comparison_value,
                        comparison_field=comparison_field,
                    )
                )
    return output


def snapshot_contexts(snapshot_rows):
    contexts = {}
    for row in snapshot_rows:
        snapshot_id = str(row.get("snapshot_id") or "")
        if not snapshot_id:
            continue
        context = contexts.setdefault(snapshot_id, dict(row))
        for key, value in row.items():
            if context.get(key) in (None, "") and value not in (None, ""):
                context[key] = value
    return contexts


def feature_support_by_snapshot(feature_rows):
    support = {}
    for row in feature_rows:
        snapshot_id = str(row.get("snapshot_id") or "")
        if not snapshot_id:
            continue
        support[snapshot_id] = row
    return support


def sidecar_rows_for_folder(folder, context, snapshot_rows, feature_rows):
    output = []
    unit = context["unit"]
    feature_support = feature_support_by_snapshot(feature_rows)
    for snapshot_id, row in snapshot_contexts(snapshot_rows).items():
        current_max, field = first_nonempty(row, SIDECAR_CURRENT_MAX_FIELDS)
        current_max_value = safe_float(current_max)
        if field is None or current_max_value is None:
            continue
        if not plausible_temperature(current_max_value, unit):
            output.append(
                make_row(
                    folder,
                    context,
                    SNAPSHOTS_LONG,
                    row,
                    field,
                    current_max,
                    "implausible_current_max_unit",
                )
            )
            continue
        support_candidates = [(name, safe_float(row.get(name))) for name in SIDECAR_SUPPORT_FIELDS]
        feature = feature_support.get(snapshot_id) or {}
        support_candidates.extend(
            (name, safe_float(feature.get(name)))
            for name in ("high_so_far", "current_temp", "live_reading_temp")
        )
        support_candidates = [(name, value) for name, value in support_candidates if value is not None]
        if not support_candidates:
            continue
        comparison_field, comparison_value = max(support_candidates, key=lambda item: item[1])
        if current_max_value - comparison_value >= CURRENT_MAX_GAP_THRESHOLD:
            output.append(
                make_row(
                    folder,
                    context,
                    SNAPSHOTS_LONG,
                    row,
                    field,
                    current_max,
                    "current_max_exceeds_observed_support",
                    comparison_value=comparison_value,
                    comparison_field=comparison_field,
                )
            )
    return output


def replay_feature_contaminated(record, row):
    field = row.get("feature_field")
    expected = safe_float(row.get("observed_value"))
    if not field or expected is None:
        return False
    for key in ("feature_vector", "features", "model_features"):
        features = record.get(key)
        if not isinstance(features, dict):
            continue
        actual = safe_float(features.get(field))
        if actual is not None and abs(actual - expected) <= 1e-9:
            return True
    return False


def annotate_replay_presence(folder, rows):
    replay_path = Path(folder) / REPLAY_INPUTS
    wanted = {row.get("snapshot_id") for row in rows if row.get("snapshot_id")}
    if not rows or not replay_path.exists() or not wanted:
        return rows
    by_snapshot = defaultdict(list)
    for row in rows:
        by_snapshot[row.get("snapshot_id")].append(row)
    found = set()
    try:
        with replay_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                snapshot_id = str(record.get("snapshot_id") or "")
                if snapshot_id not in wanted:
                    continue
                found.add(snapshot_id)
                for row in by_snapshot[snapshot_id]:
                    row["replay_input_present"] = True
                    row["replay_input_feature_contaminated"] = replay_feature_contaminated(record, row)
                if found == wanted:
                    break
    except OSError:
        pass
    return rows


def dedupe_rows(rows):
    seen = set()
    output = []
    for row in rows:
        key = (
            row.get("event_slug"),
            row.get("snapshot_id"),
            row.get("source_file"),
            row.get("feature_field"),
            row.get("reason"),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def summarize_rows(rows, *, folder_count=0, scanned_feature_row_count=0, scanned_snapshot_row_count=0):
    reason_counts = Counter(row.get("reason") or "unknown" for row in rows)
    disposition_counts = Counter(row.get("disposition") or "unknown" for row in rows)
    source_counts = Counter(row.get("source_file") or "unknown" for row in rows)
    affected_folders = {row.get("folder") for row in rows if row.get("folder")}
    affected_markets = {row.get("market_id") for row in rows if row.get("market_id")}
    affected_snapshots = {
        (row.get("event_slug"), row.get("snapshot_id"))
        for row in rows
        if row.get("snapshot_id")
    }
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "folder_count": int(folder_count),
        "scanned_feature_row_count": int(scanned_feature_row_count),
        "scanned_snapshot_row_count": int(scanned_snapshot_row_count),
        "quarantine_row_count": len(rows),
        "training_excluded_row_count": sum(1 for row in rows if row.get("training_excluded")),
        "promotion_excluded_row_count": sum(1 for row in rows if row.get("promotion_excluded")),
        "score_only_row_count": sum(1 for row in rows if row.get("score_only")),
        "backfill_candidate_row_count": sum(
            1 for row in rows
            if row.get("disposition") == "training_excluded_pending_backfill"
        ),
        "raw_evidence_absent_row_count": sum(1 for row in rows if not row.get("raw_evidence_available")),
        "replay_input_impacted_count": sum(1 for row in rows if row.get("replay_input_present")),
        "replay_input_feature_contaminated_count": sum(
            1 for row in rows if row.get("replay_input_feature_contaminated")
        ),
        "affected_folder_count": len(affected_folders),
        "affected_market_count": len(affected_markets),
        "affected_snapshot_count": len(affected_snapshots),
        "reason_counts": dict(sorted(reason_counts.items())),
        "disposition_counts": dict(sorted(disposition_counts.items())),
        "source_file_counts": dict(sorted(source_counts.items())),
    }


def audit_folder_feature_quality(folder):
    folder = Path(folder)
    context = folder_context(folder)
    feature_rows = read_csv_rows(folder / FEATURES_LONG)
    snapshot_rows = read_csv_rows(folder / SNAPSHOTS_LONG)
    rows = []
    rows.extend(feature_rows_for_folder(folder, context, feature_rows))
    rows.extend(sidecar_rows_for_folder(folder, context, snapshot_rows, feature_rows))
    rows = annotate_replay_presence(folder, dedupe_rows(rows))
    summary = summarize_rows(
        rows,
        folder_count=1,
        scanned_feature_row_count=len(feature_rows),
        scanned_snapshot_row_count=len(snapshot_rows),
    )
    return {
        "schema_version": FOLDER_SCHEMA_VERSION,
        "folder": str(folder),
        "event_slug": context["event_slug"],
        "market_id": context["market_id"],
        "target_date": context["target_date"],
        "unit": context["unit"],
        "summary": summary,
        "rows": rows,
    }


def discover_snapshot_folders(snapshots_root):
    root = Path(snapshots_root)
    folders = {
        path.parent
        for pattern in (FEATURES_LONG, SNAPSHOTS_LONG)
        for path in root.glob(f"*/{pattern}")
    }
    return sorted(folders, key=lambda path: path.name)


def build_payload(snapshots_root=DEFAULT_SNAPSHOTS_ROOT, folders=None):
    selected = [Path(folder) for folder in folders] if folders else discover_snapshot_folders(snapshots_root)
    rows = []
    folder_summaries = []
    scanned_feature_rows = 0
    scanned_snapshot_rows = 0
    for folder in selected:
        audit = audit_folder_feature_quality(folder)
        summary = audit["summary"]
        scanned_feature_rows += int(summary.get("scanned_feature_row_count") or 0)
        scanned_snapshot_rows += int(summary.get("scanned_snapshot_row_count") or 0)
        rows.extend(audit["rows"])
        folder_summaries.append({
            "folder": audit["folder"],
            "event_slug": audit["event_slug"],
            "market_id": audit["market_id"],
            "target_date": audit["target_date"],
            "summary": summary,
        })
    summary = summarize_rows(
        rows,
        folder_count=len(selected),
        scanned_feature_row_count=scanned_feature_rows,
        scanned_snapshot_row_count=scanned_snapshot_rows,
    )
    by_market = []
    rows_by_market = defaultdict(list)
    for row in rows:
        rows_by_market[row.get("market_id") or "unknown"].append(row)
    for market_id, market_rows in sorted(rows_by_market.items()):
        market_summary = summarize_rows(market_rows)
        market_summary["market_id"] = market_id
        by_market.append(market_summary)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "snapshots_root": str(snapshots_root),
        "summary": summary,
        "by_market": by_market,
        "folders": folder_summaries,
        "rows": rows,
    }


def count_summary(values):
    return ", ".join(f"{key}: {value}" for key, value in sorted((values or {}).items())) or "-"


def render_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Feature Quality Quarantine",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Snapshots root: `{payload.get('snapshots_root')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Folders scanned", summary.get("folder_count")],
            ["Feature rows scanned", summary.get("scanned_feature_row_count")],
            ["Snapshot rows scanned", summary.get("scanned_snapshot_row_count")],
            ["Quarantined rows", summary.get("quarantine_row_count")],
            ["Training-excluded rows", summary.get("training_excluded_row_count")],
            ["Promotion-excluded rows", summary.get("promotion_excluded_row_count")],
            ["Backfill candidates", summary.get("backfill_candidate_row_count")],
            ["Raw evidence absent rows", summary.get("raw_evidence_absent_row_count")],
            ["Replay-input impacted rows", summary.get("replay_input_impacted_count")],
            ["Affected folders", summary.get("affected_folder_count")],
            ["Affected markets", summary.get("affected_market_count")],
            ["Affected snapshots", summary.get("affected_snapshot_count")],
            ["Reasons", count_summary(summary.get("reason_counts"))],
            ["Dispositions", count_summary(summary.get("disposition_counts"))],
            ["Sources", count_summary(summary.get("source_file_counts"))],
        ],
    )
    if payload.get("by_market"):
        lines += ["", "## By Market", ""]
        lines += markdown_table(
            ["Market", "Rows", "Training Excluded", "Backfill Candidates", "Reasons"],
            [
                [
                    row.get("market_id"),
                    row.get("quarantine_row_count"),
                    row.get("training_excluded_row_count"),
                    row.get("backfill_candidate_row_count"),
                    count_summary(row.get("reason_counts")),
                ]
                for row in payload.get("by_market") or []
            ],
        )
    lines += ["", "## Sample Rows", ""]
    lines += markdown_table(
        ["Market", "Date", "Snapshot", "Source", "Field", "Value", "Reason", "Disposition"],
        [
            [
                row.get("market_id"),
                row.get("target_date"),
                row.get("snapshot_id"),
                row.get("source_file"),
                row.get("feature_field"),
                row.get("observed_value"),
                row.get("reason"),
                row.get("disposition"),
            ]
            for row in (payload.get("rows") or [])[:50]
        ],
    )
    return "\n".join(lines) + "\n"


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, csv_out=DEFAULT_CSV_OUT, report_out=DEFAULT_REPORT_OUT):
    json_path = Path(json_out)
    csv_path = Path(csv_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(payload.get("rows") or [])
    report_path.write_text(render_report(payload), encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "report": str(report_path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit historical feature-quality quarantines.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("folders", nargs="*", help="Optional snapshot folders to scan.")
    args = parser.parse_args(argv)
    payload = build_payload(args.snapshots_root, folders=args.folders or None)
    paths = write_outputs(payload, args.json_out, args.csv_out, args.report_out)
    summary = payload["summary"]
    print(
        "Feature quality quarantine "
        f"{summary['quarantine_row_count']} rows, "
        f"{summary['training_excluded_row_count']} training-excluded rows, "
        f"{summary['backfill_candidate_row_count']} backfill candidates. "
        f"JSON: {paths['json']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
