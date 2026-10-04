"""Repair settled snapshot folders missing replay-input status artifacts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from weather.backtesting.replay import (
    RECONSTRUCTED_FILENAME,
    REPLAY_INPUTS_FILENAME,
    REPLAY_STATUS_FILENAME,
    REPLAY_STATUS_LONG_FILENAME,
    reconstruct_corpus_for_folder,
    write_replay_input_status,
)
from weather.cold_archive_locations import load_location
from weather.io import read_json, read_jsonl, write_json_atomic
from weather.market.market_config import date_from_event_slug, market_id_from_slug
from weather.model.model_constants import TORONTO_TZ
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.time import utc_now


SCHEMA_VERSION = "replay_status_backfill_v0.1"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "replay_status_backfill.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "replay_status_backfill_report.md"
EVIDENCE_FILENAMES = (REPLAY_INPUTS_FILENAME, RECONSTRUCTED_FILENAME, "snapshots.jsonl", "source_status_long.csv")
STATUS_FILENAMES = (REPLAY_STATUS_FILENAME, REPLAY_STATUS_LONG_FILENAME)


def parse_as_of(value=None):
    if isinstance(value, date):
        return value
    if not value:
        return datetime.now(TORONTO_TZ).date()
    return date.fromisoformat(str(value)[:10])


def folder_target_date(folder):
    try:
        return date_from_event_slug(Path(folder).name)
    except Exception:  # noqa: BLE001 - invalid folders are reported as ineligible
        return None


def _csv_row_count(path):
    path = Path(path)
    if not path.exists():
        return 0
    try:
        # Fast physical-line scan for ordinary unquoted generated CSV. Retain
        # csv's logical-row semantics if quoted/multiline fields are present.
        lines, last, quoted = 0, b"", False
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                lines += chunk.count(b"\n")
                quoted |= b'"' in chunk
                last = chunk[-1:]
        if not quoted:
            return max(0, lines + int(bool(last) and last != b"\n") - 1)
        with path.open("r", encoding="utf-8", newline="") as handle:
            return sum(1 for _row in csv.DictReader(handle))
    except (OSError, csv.Error):
        return 0


def _file_nonempty(path):
    path = Path(path)
    return path.exists() and path.stat().st_size > 0


def discover_folders(snapshots_root):
    root = Path(snapshots_root)
    if not root.exists():
        return []
    return sorted(path for path in root.iterdir() if path.is_dir())


def archived_files(folder, names=(*EVIDENCE_FILENAMES, *STATUS_FILENAMES)):
    """name -> archive location for files that left this disk under a marker."""
    folder = Path(folder)
    found = {}
    for name in names:
        if not (folder / name).exists():
            location = load_location(folder / name)
            if location is not None:
                found[name] = location
    return found


def existing_status_summary(folder):
    folder = Path(folder)
    archived = archived_files(folder, STATUS_FILENAMES)
    summary = {} if REPLAY_STATUS_FILENAME in archived else (
        read_json(folder / REPLAY_STATUS_FILENAME, default={}) or {})
    rows = _csv_row_count(folder / REPLAY_STATUS_LONG_FILENAME)
    if not summary and rows:
        summary = {"folder_status": "present", "snapshot_count": rows}
    if not summary and archived:
        # The status exists off-site; reuse it without restoring its bytes.
        summary = {"folder_status": "archived"}
    return summary


def _archived_folder_evidence(folder, archived):
    """Evidence for a folder whose inputs are partly or wholly archived.

    Archived files are described from their markers (exact size), never read,
    so a reused status is not re-derived from inputs that are not on disk.
    """

    def records(name):
        return None if name in archived else read_jsonl(folder / name)

    def nonempty(name, rows):
        return archived[name].member["size_bytes"] > 0 if name in archived else bool(rows)

    def count(rows):
        return None if rows is None else len(rows)

    replay_records = records(REPLAY_INPUTS_FILENAME)
    reconstructed_records = records(RECONSTRUCTED_FILENAME)
    snapshot_records = records("snapshots.jsonl")
    source_status_path = folder / "source_status_long.csv"
    return {
        "snapshots_jsonl_exists": "snapshots.jsonl" in archived or (folder / "snapshots.jsonl").exists(),
        "snapshot_count": count(snapshot_records),
        "replay_inputs_exists": REPLAY_INPUTS_FILENAME in archived or (folder / REPLAY_INPUTS_FILENAME).exists(),
        "replay_input_count": count(replay_records),
        "reconstructed_exists": RECONSTRUCTED_FILENAME in archived or (folder / RECONSTRUCTED_FILENAME).exists(),
        "reconstructed_count": count(reconstructed_records),
        "source_status_exists": "source_status_long.csv" in archived or source_status_path.exists(),
        "source_status_row_count": None if "source_status_long.csv" in archived else _csv_row_count(source_status_path),
        "invalid_replay_inputs": replay_records is not None and _file_nonempty(folder / REPLAY_INPUTS_FILENAME)
        and not replay_records,
        "has_raw_replay_evidence": nonempty(REPLAY_INPUTS_FILENAME, replay_records)
        or nonempty(RECONSTRUCTED_FILENAME, reconstructed_records),
        "has_snapshot_metadata": nonempty("snapshots.jsonl", snapshot_records),
        "archived_inputs": sorted(archived),
    }


def folder_evidence(folder):
    folder = Path(folder)
    archived = archived_files(folder, EVIDENCE_FILENAMES)
    if archived:
        return _archived_folder_evidence(folder, archived)
    replay_path = folder / REPLAY_INPUTS_FILENAME
    reconstructed_path = folder / RECONSTRUCTED_FILENAME
    snapshots_path = folder / "snapshots.jsonl"
    source_status_path = folder / "source_status_long.csv"
    replay_records = read_jsonl(replay_path)
    reconstructed_records = read_jsonl(reconstructed_path)
    snapshot_records = read_jsonl(snapshots_path)
    invalid_replay_inputs = _file_nonempty(replay_path) and not replay_records
    return {
        "snapshots_jsonl_exists": snapshots_path.exists(),
        "snapshot_count": len(snapshot_records),
        "replay_inputs_exists": replay_path.exists(),
        "replay_input_count": len(replay_records),
        "reconstructed_exists": reconstructed_path.exists(),
        "reconstructed_count": len(reconstructed_records),
        "source_status_exists": source_status_path.exists(),
        "source_status_row_count": _csv_row_count(source_status_path),
        "invalid_replay_inputs": invalid_replay_inputs,
        "has_raw_replay_evidence": bool(replay_records or reconstructed_records),
        "has_snapshot_metadata": bool(snapshot_records),
    }


def training_ready_from_status(base_training_ready, status_summary, evidence):
    if not base_training_ready:
        return False, "not_training_ready_date"
    folder_status = (status_summary or {}).get("folder_status")
    if folder_status == "evaluation_only":
        return False, "replay_status_evaluation_only"
    if evidence.get("invalid_replay_inputs"):
        return False, "invalid_replay_inputs"
    if not evidence.get("has_raw_replay_evidence") and not evidence.get("has_snapshot_metadata"):
        return False, "missing_snapshot_and_replay_inputs"
    return True, "training_ready"


def _repair_signature(folder):
    signature = []
    for name in (REPLAY_INPUTS_FILENAME, RECONSTRUCTED_FILENAME, "snapshots.jsonl",
                 "source_status_long.csv", REPLAY_STATUS_FILENAME, REPLAY_STATUS_LONG_FILENAME):
        path = folder / name
        stat = path.stat() if path.exists() else None
        signature.append([str(path.resolve()), stat.st_size if stat else None,
                          stat.st_mtime_ns if stat else None])
    return signature


def repair_folder(folder, *, as_of_date, overwrite=False, reconstruct_missing=False,
                  include_active=False, incremental=True):
    folder = Path(folder)
    signature = _repair_signature(folder)
    cache_path = folder / ".replay_status_cache.json"
    target = folder_target_date(folder)
    options = [SCHEMA_VERSION, bool(target and target < as_of_date),
               reconstruct_missing, include_active]
    # Archiving changes the signature but not the evidence: reuse, never rewrite.
    archived = bool(archived_files(folder))
    cached = None
    if incremental and not overwrite:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            result = cached["result"]
            if ((cached["inputs"] == signature or archived) and cached["options"] == options
                    and ((folder / REPLAY_STATUS_LONG_FILENAME).exists() or archived)
                    and cached["sha256"] == hashlib.sha256(
                        json.dumps(result, sort_keys=True).encode()).hexdigest()):
                return result
        except (OSError, ValueError, KeyError, TypeError):
            cached = None
    result = _repair_folder_full(
        folder, as_of_date=as_of_date,
        overwrite=overwrite or bool(cached and cached.get("inputs") != signature and not archived),
        reconstruct_missing=reconstruct_missing, include_active=include_active)
    if incremental and result.get("status_path"):
        # Build exactly the old existing-status response after a successful
        # write, without reparsing any evidence.
        next_result = dict(result)
        if result["action"] == "written":
            for name in ("summary_path", "reconstructed_added", "reconstructed_skipped"):
                next_result.pop(name, None)
            next_result.update(action="skipped", reason="replay_status_exists")
        after = _repair_signature(folder)
        if signature[:4] == after[:4]:
            try:
                write_json_atomic(cache_path, {"inputs": after, "options": options,
                                              "result": next_result, "sha256": hashlib.sha256(
                                                  json.dumps(next_result, sort_keys=True).encode()).hexdigest()})
            except OSError:
                pass  # Cache availability cannot change a valid repair result.
    return result


def _repair_folder_full(folder, *, as_of_date, overwrite=False, reconstruct_missing=False, include_active=False):
    folder = Path(folder)
    target_date = folder_target_date(folder)
    market_id = market_id_from_slug(folder.name)
    base_training_ready = bool(target_date and target_date < as_of_date)
    if not base_training_ready and not include_active:
        return {
            "folder": str(folder),
            "event_slug": folder.name,
            "market_id": market_id,
            "target_date": target_date.isoformat() if target_date else None,
            "base_training_ready": base_training_ready,
            "training_ready": False,
            "action": "skipped",
            "reason": "not_training_ready_date",
            **folder_evidence(folder),
        }

    status_path = folder / REPLAY_STATUS_LONG_FILENAME
    evidence = folder_evidence(folder)
    status_present = status_path.exists() or load_location(status_path) is not None
    if status_present and not overwrite:
        summary = existing_status_summary(folder)
        training_ready, reason = training_ready_from_status(base_training_ready, summary, evidence)
        return {
            "folder": str(folder),
            "event_slug": folder.name,
            "market_id": market_id,
            "target_date": target_date.isoformat() if target_date else None,
            "base_training_ready": base_training_ready,
            "training_ready": training_ready,
            "action": "skipped",
            "reason": "replay_status_exists",
            "status_path": str(status_path),
            **evidence,
            **_status_fields(summary),
            "training_ready_reason": reason,
        }

    if evidence.get("archived_inputs") and not overwrite:
        # Writing a status needs the input bytes; restore first or pass --overwrite
        # to have the readers raise ArchivedInputRequired.
        return {
            "folder": str(folder),
            "event_slug": folder.name,
            "market_id": market_id,
            "target_date": target_date.isoformat() if target_date else None,
            "base_training_ready": base_training_ready,
            "training_ready": False,
            "action": "archived",
            "reason": "archived_inputs_require_restore",
            **evidence,
        }

    if reconstruct_missing and evidence.get("has_snapshot_metadata"):
        added, skipped = reconstruct_corpus_for_folder(folder)
        evidence = folder_evidence(folder)
    else:
        added, skipped = 0, 0

    if not evidence.get("has_raw_replay_evidence") and not evidence.get("has_snapshot_metadata"):
        return {
            "folder": str(folder),
            "event_slug": folder.name,
            "market_id": market_id,
            "target_date": target_date.isoformat() if target_date else None,
            "base_training_ready": base_training_ready,
            "training_ready": False,
            "action": "irreparable",
            "reason": "missing_snapshot_and_replay_inputs",
            "reconstructed_added": added,
            "reconstructed_skipped": skipped,
            **evidence,
        }

    summary = write_replay_input_status(folder)
    training_ready, reason = training_ready_from_status(base_training_ready, summary, evidence)
    return {
        "folder": str(folder),
        "event_slug": folder.name,
        "market_id": market_id,
        "target_date": target_date.isoformat() if target_date else None,
        "base_training_ready": base_training_ready,
        "training_ready": training_ready,
        "action": "written",
        "reason": reason,
        "status_path": str(folder / REPLAY_STATUS_LONG_FILENAME),
        "summary_path": str(folder / REPLAY_STATUS_FILENAME),
        "reconstructed_added": added,
        "reconstructed_skipped": skipped,
        **evidence,
        **_status_fields(summary),
        "training_ready_reason": reason,
    }


def _status_fields(summary):
    summary = summary or {}
    return {
        "folder_status": summary.get("folder_status"),
        "status_snapshot_count": summary.get("snapshot_count"),
        "captured_count": summary.get("captured_count"),
        "reconstructed_count": summary.get("reconstructed_count"),
        "evaluation_only_count": summary.get("evaluation_only_count"),
        "status_counts": summary.get("counts") or {},
    }


def build_backfill_payload(
    *,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    folders=None,
    as_of=None,
    overwrite=False,
    reconstruct_missing=False,
    include_active=False,
    recent_days=7,
    incremental=True,
):
    as_of_date = parse_as_of(as_of)
    if recent_days < 0:
        raise ValueError("recent_days must be non-negative")
    selected = [Path(folder) for folder in folders] if folders else discover_folders(snapshots_root)
    if recent_days and not folders:
        cutoff = as_of_date - timedelta(days=int(recent_days))
        selected = [folder for folder in selected
                    if (target := folder_target_date(folder)) is not None and cutoff <= target <= as_of_date]
    rows = [
        repair_folder(
            folder,
            as_of_date=as_of_date,
            overwrite=overwrite,
            reconstruct_missing=reconstruct_missing,
            include_active=include_active,
            incremental=incremental,
        )
        for folder in selected
    ]
    action_counts = Counter(row.get("action") or "unknown" for row in rows)
    status_counts = Counter(row.get("folder_status") or "unknown" for row in rows)
    market_counts = defaultdict(Counter)
    for row in rows:
        market_counts[row.get("market_id") or "unknown"][row.get("action") or "unknown"] += 1
    summary = {
        "folder_count": len(rows),
        "eligible_folder_count": sum(1 for row in rows if row.get("base_training_ready")),
        "training_ready_folder_count": sum(1 for row in rows if row.get("training_ready")),
        "written_folder_count": action_counts.get("written", 0),
        "existing_folder_count": sum(
            1 for row in rows
            if row.get("action") == "skipped" and row.get("reason") == "replay_status_exists"
        ),
        "irreparable_folder_count": action_counts.get("irreparable", 0),
        "evaluation_only_folder_count": sum(1 for row in rows if row.get("folder_status") == "evaluation_only"),
        "captured_folder_count": sum(1 for row in rows if row.get("folder_status") == "captured"),
        "reconstructed_folder_count": sum(1 for row in rows if row.get("folder_status") == "reconstructed"),
        "action_counts": dict(sorted(action_counts.items())),
        "folder_status_counts": dict(sorted(status_counts.items())),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now().isoformat(),
        "snapshots_root": str(snapshots_root),
        "as_of_date": as_of_date.isoformat(),
        "overwrite": bool(overwrite),
        "reconstruct_missing": bool(reconstruct_missing),
        "include_active": bool(include_active),
        "summary": summary,
        "markets": {
            market_id: dict(sorted(counts.items()))
            for market_id, counts in sorted(market_counts.items())
        },
        "folders": rows,
    }


def write_outputs(payload, *, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_path = write_json_atomic(json_out, payload, trailing_newline=True)
    report_path = Path(report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def render_report(payload):
    summary = payload.get("summary") or {}
    folder_rows = []
    for row in payload.get("folders") or []:
        if row.get("action") == "skipped" and row.get("reason") == "not_training_ready_date":
            continue
        folder_rows.append([
            row.get("market_id") or "-",
            row.get("target_date") or "-",
            row.get("action") or "-",
            row.get("folder_status") or "-",
            row.get("training_ready"),
            row.get("captured_count"),
            row.get("reconstructed_count"),
            row.get("evaluation_only_count"),
            row.get("reason") or "-",
        ])
    summary_rows = [
        ["Folders", summary.get("folder_count")],
        ["Eligible folders", summary.get("eligible_folder_count")],
        ["Training-ready folders", summary.get("training_ready_folder_count")],
        ["Written folders", summary.get("written_folder_count")],
        ["Existing folders", summary.get("existing_folder_count")],
        ["Irreparable folders", summary.get("irreparable_folder_count")],
        ["Evaluation-only folders", summary.get("evaluation_only_folder_count")],
        ["Captured folders", summary.get("captured_folder_count")],
        ["Reconstructed folders", summary.get("reconstructed_folder_count")],
    ]
    folder_headers = [
        "Market",
        "Date",
        "Action",
        "Folder status",
        "Training ready",
        "Captured",
        "Reconstructed",
        "Evaluation only",
        "Reason",
    ]
    lines = [
        "# Replay Status Backfill",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"As of date: `{payload.get('as_of_date')}`",
        f"Snapshots root: `{payload.get('snapshots_root')}`",
        "",
        "## Summary",
        "",
        *markdown_table(["Metric", "Value"], summary_rows),
        "",
        "## Eligible Folder Results",
        "",
        *(markdown_table(folder_headers, folder_rows) if folder_rows else ["-"]),
        "",
    ]
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(description="Backfill replay_input_status artifacts for snapshot folders.")
    parser.add_argument("folders", nargs="*", help="Snapshot folders to repair; defaults to all folders under --snapshots-root.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--as-of", default="")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--reconstruct-missing", action="store_true")
    parser.add_argument("--include-active", action="store_true")
    parser.add_argument("--recent-days", type=int, default=7, help="Automatic folder window; 0 scans all history.")
    parser.add_argument("--full-scan", action="store_true", help="Disable reuse of unchanged evidence caches.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    payload = build_backfill_payload(
        snapshots_root=args.snapshots_root,
        folders=args.folders,
        as_of=args.as_of,
        overwrite=args.overwrite,
        reconstruct_missing=args.reconstruct_missing,
        include_active=args.include_active,
        recent_days=args.recent_days,
        incremental=not args.full_scan,
    )
    json_path, report_path = write_outputs(payload, json_out=args.json_out, report_out=args.report_out)
    print(f"Replay status backfill: wrote {payload['summary']['written_folder_count']} folder(s)")
    print(f"Status written to {json_path}")
    print(f"Report written to {report_path}")
    return 0 if payload["summary"].get("irreparable_folder_count", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
