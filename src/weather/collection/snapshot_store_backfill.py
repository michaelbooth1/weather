"""Backfill helpers and CLI wiring for snapshot store artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.market.snapshot_cadence_quality import snapshot_cadence_quality
from weather.model.toronto_model import TORONTO_TZ


SNAPSHOT_INTERVAL = timedelta(minutes=10)
SNAPSHOT_CADENCE_QUALITY_COLUMNS = [
    "snapshot_cadence",
    "snapshot_cadence_quality_state",
    "snapshot_cadence_gap_count",
    "snapshot_cadence_max_gap_seconds",
    "snapshot_cadence_last_model_age_seconds",
    "snapshot_cadence_confidence_multiplier",
    "snapshot_cadence_permission",
    "snapshot_cadence_reason",
]


def _snapshot_store(root, event_slug=None):
    from weather.collection.snapshot_store import SnapshotStore

    return SnapshotStore(root=root, event_slug=event_slug or Path(root).name)


def backfill_explanations(root, *, event_slug=None, limit=None):
    return _snapshot_store(root, event_slug).backfill_snapshot_explanations(limit=limit)


def _parse_snapshot_captured_at(row):
    for key in ("captured_at_utc", "captured_at_local"):
        value = row.get(key)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TORONTO_TZ)
        return parsed.astimezone(timezone.utc)
    return None


def _cadence_backfill_fieldnames(fieldnames):
    fields = list(fieldnames or [])
    missing = [name for name in SNAPSHOT_CADENCE_QUALITY_COLUMNS if name not in fields]
    if not missing:
        return fields
    if "snapshot_cadence" in fields:
        insert_at = fields.index("snapshot_cadence") + 1
    elif "runtime_code_state" in fields:
        insert_at = fields.index("runtime_code_state") + 1
    elif "trigger_reason" in fields:
        insert_at = fields.index("trigger_reason")
    else:
        insert_at = min(len(fields), 8)
    for name in reversed(missing):
        fields.insert(insert_at, name)
    return fields


def backfill_snapshot_cadence_quality(folder, *, overwrite=False):
    folder = Path(folder)
    path = folder / "snapshots_long.csv"
    if not path.exists():
        return {
            "schema_version": "snapshot_cadence_quality_backfill_v0.1",
            "folder": str(folder),
            "status": "missing_snapshots_long",
            "changed": False,
            "updated_row_count": 0,
            "snapshot_count": 0,
        }
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        original_fields = list(reader.fieldnames or [])
        rows = list(reader)

    first_by_snapshot = {}
    for row in rows:
        snapshot_id = row.get("snapshot_id")
        if snapshot_id and snapshot_id not in first_by_snapshot:
            first_by_snapshot[snapshot_id] = row

    ordered = sorted(
        first_by_snapshot.items(),
        key=lambda item: (
            _parse_snapshot_captured_at(item[1]) or datetime.min.replace(tzinfo=timezone.utc),
            item[0],
        ),
    )
    quality_by_snapshot = {}
    previous_scheduled = None
    for snapshot_id, row in ordered:
        captured_at = _parse_snapshot_captured_at(row)
        cadence = str(row.get("snapshot_cadence") or "scheduled").strip().lower() or "scheduled"
        gap_seconds = None
        gap_count = 0
        if captured_at is not None and previous_scheduled is not None:
            gap_seconds = (captured_at - previous_scheduled).total_seconds()
            if cadence == "scheduled" and gap_seconds > SNAPSHOT_INTERVAL.total_seconds() * 1.5:
                gap_count = 1
        if cadence == "scheduled" and captured_at is not None:
            previous_scheduled = captured_at
        quality_by_snapshot[snapshot_id] = snapshot_cadence_quality({
            "snapshot_cadence": cadence,
            "snapshot_cadence_gap_count": gap_count,
            "snapshot_cadence_max_gap_seconds": gap_seconds if gap_count else None,
            "snapshot_cadence_last_model_age_seconds": 0.0,
        })

    updated_rows = 0
    for row in rows:
        quality = quality_by_snapshot.get(row.get("snapshot_id"))
        if not quality:
            continue
        changed = False
        for field in SNAPSHOT_CADENCE_QUALITY_COLUMNS:
            value = quality.get(field)
            value = "" if value is None else value
            if overwrite or row.get(field) in (None, ""):
                if row.get(field) != value:
                    row[field] = value
                    changed = True
        if changed:
            updated_rows += 1

    fieldnames = _cadence_backfill_fieldnames(original_fields)
    changed = updated_rows > 0 or fieldnames != original_fields
    if changed:
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        tmp_path.replace(path)

    return {
        "schema_version": "snapshot_cadence_quality_backfill_v0.1",
        "folder": str(folder),
        "status": "updated" if changed else "unchanged",
        "changed": changed,
        "updated_row_count": updated_rows,
        "snapshot_count": len(first_by_snapshot),
    }


def build_parser():
    parser = argparse.ArgumentParser(description="Snapshot persistence utilities.")
    sub = parser.add_subparsers(dest="command", required=True)
    core = sub.add_parser("backfill-core-sidecars")
    core.add_argument("folders", nargs="+", help="Snapshot folder(s) containing snapshots.jsonl.")
    core.add_argument("--limit", type=int, default=None)
    backfill = sub.add_parser("backfill-explanations")
    backfill.add_argument("folders", nargs="+", help="Snapshot folder(s) containing snapshots.jsonl.")
    backfill.add_argument("--limit", type=int, default=None)
    obs = sub.add_parser("backfill-observation-payloads")
    obs.add_argument("folders", nargs="+", help="Snapshot folder(s) containing forecast_payloads_long.csv.")
    cadence = sub.add_parser("backfill-cadence-quality")
    cadence.add_argument("folders", nargs="+", help="Snapshot folder(s) containing snapshots_long.csv.")
    cadence.add_argument("--overwrite", action="store_true", help="Recompute existing cadence quality values.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "backfill-core-sidecars":
        results = [
            _snapshot_store(folder).backfill_feature_component_sidecars(limit=args.limit)
            for folder in args.folders
        ]
        print(json.dumps({
            "schema_version": "snapshot_core_sidecar_backfill_batch_v0.1",
            "folder_count": len(results),
            "written_feature_row_count": sum(item.get("written_feature_row_count", 0) for item in results),
            "written_component_row_count": sum(item.get("written_component_row_count", 0) for item in results),
            "folders": results,
        }, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "backfill-explanations":
        results = [
            backfill_explanations(folder, limit=args.limit)
            for folder in args.folders
        ]
        print(json.dumps({
            "schema_version": "snapshot_explanation_backfill_batch_v0.1",
            "folder_count": len(results),
            "written_snapshot_count": sum(item.get("written_snapshot_count", 0) for item in results),
            "error_count": sum(item.get("error_count", 0) for item in results),
            "folders": results,
        }, indent=2, sort_keys=True, default=str))
        return 1 if any(item.get("error_count") for item in results) else 0
    if args.command == "backfill-observation-payloads":
        results = [
            _snapshot_store(folder).backfill_observation_payloads_from_forecast_payloads()
            for folder in args.folders
        ]
        print(json.dumps({
            "schema_version": "observation_payload_backfill_batch_v0.1",
            "folder_count": len(results),
            "written_row_count": sum(item.get("written_row_count", 0) for item in results),
            "folders": results,
        }, indent=2, sort_keys=True, default=str))
        return 0
    if args.command == "backfill-cadence-quality":
        results = [
            backfill_snapshot_cadence_quality(folder, overwrite=args.overwrite)
            for folder in args.folders
        ]
        print(json.dumps({
            "schema_version": "snapshot_cadence_quality_backfill_batch_v0.1",
            "folder_count": len(results),
            "changed_folder_count": sum(1 for item in results if item.get("changed")),
            "updated_row_count": sum(item.get("updated_row_count", 0) for item in results),
            "folders": results,
        }, indent=2, sort_keys=True, default=str))
        return 0
    return 2
