"""Repair settled snapshot folders missing replay-input status artifacts.

Incremental evidence (daily refresh Stage A)
--------------------------------------------
Every pass builds one row per snapshot folder, and each row embeds
``folder_evidence`` (a full JSON parse of ``snapshots.jsonl``, replay inputs and
the reconstructed corpus) and, for folders that already carry a replay status,
``existing_status_summary``. On a mature snapshot tree that parse dominates the
step, although settled folders almost never change.

``EvidenceCache`` memoizes those two per-folder results in a sidecar beside the
step output (``EVIDENCE_CACHE_FILENAME``). An entry is reused only when the key
of every file the computation reads is unchanged: name, size and
``st_mtime_ns`` of each file, ``None`` for an absent file, and for an absent file
that has a cold-archive marker, the marker's and the resolved copy's identity.
Anything else (new folder, changed or missing key, unreadable stat, unresolvable
archived input) recomputes exactly as the uncached path does. The cached values
are the uncached function results, so the payload is identical either way; the
decision logic in ``repair_folder`` always runs live.

A cache whose ``format``, integer ``version`` or ``logic_key`` (a hash of the
cached functions' source) differs, or that cannot be parsed, is discarded: the
pass becomes a full recompute and re-seeds it. Folders that are not visited in a
pass are dropped from the rewritten cache. Bump ``EVIDENCE_CACHE_VERSION`` when
the meaning of a cached value changes in a way the source hash cannot see.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import inspect
import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

from weather.backtesting.replay import (
    RECONSTRUCTED_FILENAME,
    REPLAY_INPUTS_FILENAME,
    REPLAY_STATUS_FILENAME,
    REPLAY_STATUS_LONG_FILENAME,
    reconstruct_corpus_for_folder,
    write_replay_input_status,
)
from weather import io as weather_io
from weather.cold_archive_locations import marker_path, resolve_local_path
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
EVIDENCE_CACHE_FORMAT = "replay_status_backfill_evidence_cache"
EVIDENCE_CACHE_VERSION = 1
EVIDENCE_CACHE_FILENAME = "replay_status_backfill_evidence_cache.json"
SNAPSHOTS_FILENAME = "snapshots.jsonl"
SOURCE_STATUS_FILENAME = "source_status_long.csv"
EVIDENCE_INPUT_FILENAMES = (
    REPLAY_INPUTS_FILENAME,
    RECONSTRUCTED_FILENAME,
    SNAPSHOTS_FILENAME,
    SOURCE_STATUS_FILENAME,
)
STATUS_INPUT_FILENAMES = (REPLAY_STATUS_FILENAME, REPLAY_STATUS_LONG_FILENAME)
# The only summary fields repair_folder consumes (_status_fields and
# training_ready_from_status); the cache stores this projection, not the file.
STATUS_SUMMARY_KEYS = (
    "folder_status",
    "snapshot_count",
    "captured_count",
    "reconstructed_count",
    "evaluation_only_count",
    "counts",
)


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


def existing_status_summary(folder):
    folder = Path(folder)
    summary = read_json(folder / REPLAY_STATUS_FILENAME, default={}) or {}
    rows = _csv_row_count(folder / REPLAY_STATUS_LONG_FILENAME)
    if not summary and rows:
        summary = {"folder_status": "present", "snapshot_count": rows}
    return summary


def folder_evidence(folder):
    folder = Path(folder)
    replay_path = folder / REPLAY_INPUTS_FILENAME
    reconstructed_path = folder / RECONSTRUCTED_FILENAME
    snapshots_path = folder / SNAPSHOTS_FILENAME
    source_status_path = folder / SOURCE_STATUS_FILENAME
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


# Captured at import so a test double patched over a module global cannot
# change the key; the key describes the code that computes cached values.
_EVIDENCE_LOGIC_FUNCTIONS = (
    folder_evidence,
    existing_status_summary,
    _csv_row_count,
    _file_nonempty,
    weather_io.read_jsonl,
    weather_io.read_json,
)


def _evidence_logic_key():
    parts = [
        EVIDENCE_CACHE_FORMAT,
        str(EVIDENCE_CACHE_VERSION),
        *EVIDENCE_INPUT_FILENAMES,
        *STATUS_INPUT_FILENAMES,
        *STATUS_SUMMARY_KEYS,
    ]
    try:
        for function in _EVIDENCE_LOGIC_FUNCTIONS:
            parts.append(inspect.getsource(function))
    except (OSError, TypeError):
        return None
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


class _Uncacheable(Exception):
    """A file identity could not be established; compute without the cache."""


def _file_key(path):
    path = Path(path)
    try:
        stat = os.stat(path)
    except FileNotFoundError:
        stat = None
    except OSError as exc:
        raise _Uncacheable(str(exc)) from exc
    if stat is not None:
        return [path.name, stat.st_size, stat.st_mtime_ns]
    marker = marker_path(path)
    try:
        marker_stat = os.stat(marker)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _Uncacheable(str(exc)) from exc
    # A cold-archived input is read through its verified cache copy; key on
    # the marker and on the copy that the readers would actually open.
    try:
        resolved = Path(resolve_local_path(path))
        resolved_stat = os.stat(resolved)
    except FileNotFoundError:
        resolved, resolved_stat = None, None
    except Exception as exc:  # noqa: BLE001 - the uncached path must surface it
        raise _Uncacheable(str(exc)) from exc
    return [
        path.name,
        "archived",
        marker_stat.st_size,
        marker_stat.st_mtime_ns,
        str(resolved) if resolved is not None else None,
        resolved_stat.st_size if resolved_stat is not None else None,
        resolved_stat.st_mtime_ns if resolved_stat is not None else None,
    ]


def _files_key(folder, names):
    return [_file_key(Path(folder) / name) for name in names]


def _status_projection(summary):
    summary = summary or {}
    return {key: summary[key] for key in STATUS_SUMMARY_KEYS if key in summary}


EVIDENCE_CACHE_COUNTERS = (
    "evidence_reused",
    "evidence_computed",
    "evidence_uncacheable",
    "status_reused",
    "status_computed",
    "status_uncacheable",
)


class EvidenceCache:
    """Per-folder memo of ``folder_evidence`` and ``existing_status_summary``.

    See the module docstring for the reuse contract. ``load`` never raises on
    a bad cache: it returns an empty cache whose ``load_status`` names why.
    """

    def __init__(self, entries=None, *, load_status="empty"):
        self.logic_key = _evidence_logic_key()
        self.enabled = self.logic_key is not None
        self._previous = dict(entries or {}) if self.enabled else {}
        self._current = {}
        self.load_status = load_status if self.enabled else "disabled_no_logic_key"
        self.counts = Counter()

    @classmethod
    def empty(cls, load_status="empty"):
        return cls(load_status=load_status)

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls(load_status="missing")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            return cls(load_status="corrupt")
        if not isinstance(document, dict) or document.get("format") != EVIDENCE_CACHE_FORMAT:
            return cls(load_status="corrupt")
        version = document.get("version")
        if type(version) is not int or version != EVIDENCE_CACHE_VERSION:
            return cls(load_status="version_mismatch")
        entries = document.get("entries")
        if not isinstance(entries, dict) or not all(isinstance(value, dict) for value in entries.values()):
            return cls(load_status="corrupt")
        cache = cls(entries, load_status="loaded")
        if cache.enabled and document.get("logic_key") != cache.logic_key:
            cache._previous = {}
            cache.load_status = "logic_mismatch"
        return cache

    def _lookup(self, folder, kind, names, compute, *, transform=None, force=False):
        if not self.enabled:
            return compute(folder)
        try:
            key = _files_key(folder, names)
        except _Uncacheable:
            self.counts[f"{kind}_uncacheable"] += 1
            return compute(folder)
        folder_key = str(Path(folder))
        previous = self._previous.get(folder_key) or {}
        if not force and kind in previous and previous.get(f"{kind}_key") == key:
            self.counts[f"{kind}_reused"] += 1
            value = previous[kind]
        else:
            value = compute(folder)
            if transform is not None:
                value = transform(value)
            self.counts[f"{kind}_computed"] += 1
        entry = self._current.setdefault(folder_key, {})
        entry[f"{kind}_key"] = key
        entry[kind] = value
        return value

    def evidence(self, folder, *, force=False):
        return self._lookup(folder, "evidence", EVIDENCE_INPUT_FILENAMES, folder_evidence, force=force)

    def status_summary(self, folder):
        return self._lookup(
            folder,
            "status",
            STATUS_INPUT_FILENAMES,
            existing_status_summary,
            transform=_status_projection,
        )

    def document(self):
        return {
            "format": EVIDENCE_CACHE_FORMAT,
            "version": EVIDENCE_CACHE_VERSION,
            "logic_key": self.logic_key,
            "entries": {key: self._current[key] for key in sorted(self._current)},
        }

    def save(self, path):
        """Atomically replace the cache file (temp file + ``os.replace``)."""
        if not self.enabled:
            return None
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                # No sort_keys: cached summaries keep their source key order.
                json.dump(self.document(), handle, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        return path

    def stats(self):
        return {
            "load_status": self.load_status,
            "previous_entry_count": len(self._previous),
            "entry_count": len(self._current),
            "dropped_entry_count": len(set(self._previous) - set(self._current)),
            **{key: self.counts.get(key, 0) for key in EVIDENCE_CACHE_COUNTERS},
        }


def _evidence(folder, cache, *, force=False):
    return folder_evidence(folder) if cache is None else cache.evidence(folder, force=force)


def _existing_summary(folder, cache):
    return existing_status_summary(folder) if cache is None else cache.status_summary(folder)


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


def repair_folder(
    folder,
    *,
    as_of_date,
    overwrite=False,
    reconstruct_missing=False,
    include_active=False,
    evidence_cache=None,
):
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
            **_evidence(folder, evidence_cache),
        }

    status_path = folder / REPLAY_STATUS_LONG_FILENAME
    evidence = _evidence(folder, evidence_cache)
    if status_path.exists() and not overwrite:
        summary = _existing_summary(folder, evidence_cache)
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

    if reconstruct_missing and evidence.get("has_snapshot_metadata"):
        added, skipped = reconstruct_corpus_for_folder(folder)
        evidence = _evidence(folder, evidence_cache, force=True)
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
    evidence_cache=None,
):
    """Build the backfill payload.

    ``evidence_cache`` (an ``EvidenceCache``) only memoizes per-folder file
    reads; the payload is identical with or without it. The caller saves it.
    """
    as_of_date = parse_as_of(as_of)
    selected = [Path(folder) for folder in folders] if folders else discover_folders(snapshots_root)
    rows = [
        repair_folder(
            folder,
            as_of_date=as_of_date,
            overwrite=overwrite,
            reconstruct_missing=reconstruct_missing,
            include_active=include_active,
            evidence_cache=evidence_cache,
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
    )
    json_path, report_path = write_outputs(payload, json_out=args.json_out, report_out=args.report_out)
    print(f"Replay status backfill: wrote {payload['summary']['written_folder_count']} folder(s)")
    print(f"Status written to {json_path}")
    print(f"Report written to {report_path}")
    return 0 if payload["summary"].get("irreparable_folder_count", 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
