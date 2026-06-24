"""Retention, backup, and restore-drill tooling for irreplaceable tapes."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from weather.operations.storage_classes import (
    artifact_family_registry_payload,
    classification_payload,
    storage_class_contracts_payload,
    summarize_storage_class_entries,
)
from weather.paths import REPO_ROOT, relative_to_repo, data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import SCHEMAS_BY_VERSION, schema_version


MANIFEST_SCHEMA_VERSION = schema_version("tape_backup_manifest")
RESTORE_DRILL_SCHEMA_VERSION = schema_version("tape_restore_drill")
UNMANIFESTED_CLEANUP_SCHEMA_VERSION = schema_version("tape_backup_unmanifested_cleanup")
DEDUP_REPOSITORY_SCHEMA_VERSION = schema_version("tape_dedup_repository")
POLICY_VERSION = "tape_retention_policy_v0.1"
DEFAULT_CAPACITY_MARGIN_BYTES = 1024 * 1024 * 1024


def _env_int(name, default):
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


DEFAULT_LOCAL_MIRROR_CACHE_RETENTION_DAYS = _env_int("WEATHER_TAPE_MIRROR_CACHE_RETENTION_DAYS", 7)
DEFAULT_BACKUP_ROOT = (
    Path(os.environ["WEATHER_TAPE_BACKUP_ROOT"])
    if os.environ.get("WEATHER_TAPE_BACKUP_ROOT")
    else data_path("tape_backups")
)
DEFAULT_STATUS_OUT = data_path() / "backtest" / "tape_backup_status.json"
DEFAULT_REPORT_OUT = data_path() / "backtest" / "tape_backup_status_report.md"
DEFAULT_RESTORE_OUT = data_path() / "backtest" / "tape_restore_drill.json"
DEFAULT_RESTORE_REPORT = data_path() / "backtest" / "tape_restore_drill_report.md"
DEFAULT_UNMANIFESTED_CLEANUP_OUT = data_path() / "backtest" / "tape_backup_unmanifested_cleanup.json"
DEFAULT_UNMANIFESTED_CLEANUP_REPORT = data_path() / "backtest" / "tape_backup_unmanifested_cleanup_report.md"
DEFAULT_DEDUP_MANIFEST_NAME = "tape_dedup_repository_manifest.json"
DEFAULT_DEDUP_BACKUP_OUT = data_path() / "backtest" / "tape_dedup_repository_backup.json"
DEFAULT_DEDUP_BACKUP_REPORT = data_path() / "backtest" / "tape_dedup_repository_backup_report.md"
DEFAULT_DEDUP_STATUS_OUT = data_path() / "backtest" / "tape_dedup_repository_status.json"
DEFAULT_DEDUP_STATUS_REPORT = data_path() / "backtest" / "tape_dedup_repository_status_report.md"
DEFAULT_DEDUP_RESTORE_OUT = data_path() / "backtest" / "tape_dedup_restore_drill.json"
DEFAULT_DEDUP_RESTORE_REPORT = data_path() / "backtest" / "tape_dedup_restore_drill_report.md"
DEFAULT_TASK_NAME = "WeatherTapeBackupAndRestoreDrill"
LATEST_DIR = "latest"
LATEST_CONTROL_FILES = {
    "tape_backup_manifest.json",
    "tape_restore_drill.json",
}
DEDUP_BACKEND_RESTIC = "restic"
DEDUP_RESTIC_TAG = "weather-tape"


@dataclass(frozen=True)
class RetentionRule:
    name: str
    recoverability: str
    retention: str
    critical: bool
    description: str
    patterns: tuple[str, ...]
    excludes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClobArtifactPolicy:
    name: str
    recoverability: str
    backup_required: bool
    description: str
    patterns: tuple[str, ...]
    per_file_warn_bytes: int | None = None
    total_warn_bytes: int | None = None


CLOB_ARTIFACT_POLICIES = (
    ClobArtifactPolicy(
        "tokens",
        "irreplaceable_capture_join_key",
        True,
        "Gamma/CLOB token mapping needed to join books back to model bands.",
        ("data/snapshots/*/clob_tokens.csv", "data/snapshots/*/clob_tokens.jsonl"),
    ),
    ClobArtifactPolicy(
        "order_book_summary",
        "irreplaceable_book_summary",
        True,
        "Per-token best bid/ask, spread, depth, and executable-size summaries.",
        ("data/snapshots/*/order_books_summary.csv",),
    ),
    ClobArtifactPolicy(
        "order_book_long",
        "irreplaceable_full_depth_book",
        True,
        "Full depth long-table order-book evidence, raw or gzip-tiered.",
        ("data/snapshots/*/order_books_long.csv", "data/snapshots/*/order_books_long.csv.gz"),
        per_file_warn_bytes=1_000_000_000,
        total_warn_bytes=100_000_000_000,
    ),
    ClobArtifactPolicy(
        "order_book_raw",
        "irreplaceable_raw_book_payload",
        True,
        "Raw order-book JSONL payloads and response metadata.",
        ("data/snapshots/*/order_books.jsonl",),
    ),
    ClobArtifactPolicy(
        "price_history",
        "irreplaceable_price_history",
        True,
        "CLOB price-history point tapes, hash manifests, and raw response blobs used for microstructure features and replay.",
        (
            "data/snapshots/*/price_history.csv",
            "data/snapshots/*/price_history.jsonl",
            "data/snapshots/*/price_history_raw_manifest.jsonl",
            "data/snapshots/*/price_history_raw/*.json",
            "data/snapshots/*/price_history_raw/**/*.json",
        ),
    ),
    ClobArtifactPolicy(
        "market_ws",
        "irreplaceable_market_websocket",
        True,
        "Market websocket event summaries and raw JSONL messages.",
        ("data/snapshots/*/market_ws_events.csv", "data/snapshots/*/market_ws.jsonl"),
    ),
    ClobArtifactPolicy(
        "derived_clob_features",
        "rebuildable_derived_features",
        False,
        "Derived CLOB feature rows; useful to retain, but rebuildable from raw book tapes.",
        ("data/snapshots/*/clob_features*.csv", "data/snapshots/*/clob_features*.jsonl"),
    ),
)


RETENTION_RULES = (
    RetentionRule(
        "snapshot_tapes",
        "irreplaceable_raw_live_tape",
        "retain permanently; append-only evidence for settlement and replay",
        True,
        "Snapshot, feature, component, source-status, forecast payload, and replay-input tapes.",
        (
            "data/snapshots/*/snapshots*.csv",
            "data/snapshots/*/snapshots*.jsonl",
            "data/snapshots/*/features*.csv",
            "data/snapshots/*/features*.jsonl",
            "data/snapshots/*/components*.csv",
            "data/snapshots/*/components*.jsonl",
            "data/snapshots/*/source_status*.csv",
            "data/snapshots/*/source_status*.jsonl",
            "data/snapshots/*/forecast_payloads*.csv",
            "data/snapshots/*/forecast_payloads*.jsonl",
            "data/snapshots/*/forecast_payloads/**/*",
            "data/snapshots/*/replay_inputs.jsonl",
            "data/snapshots/loop_status.json",
            "data/snapshots/diagnostics.jsonl",
        ),
    ),
    RetentionRule(
        "clob_tapes",
        "irreplaceable_raw_live_tape",
        "retain permanently; order-book/trade context cannot be reconstructed",
        True,
        "CLOB token, book, feature, trade, diagnostic, and loop-status tapes.",
        (
            "data/snapshots/clob*.json",
            "data/snapshots/clob*.jsonl",
            "data/snapshots/*/clob*.csv",
            "data/snapshots/*/clob*.jsonl",
            "data/snapshots/*/order_books*.csv",
            "data/snapshots/*/order_books*.csv.gz",
            "data/snapshots/*/order_books*.jsonl",
            "data/snapshots/*/price_history*.csv",
            "data/snapshots/*/price_history*.jsonl",
            "data/snapshots/*/price_history_raw/*.json",
            "data/snapshots/*/price_history_raw/**/*.json",
            "data/snapshots/*/market_ws*.csv",
            "data/snapshots/*/market_ws*.jsonl",
        ),
    ),
    RetentionRule(
        "observation_trigger_tapes",
        "irreplaceable_raw_live_tape",
        "retain permanently; urgent recompute evidence is live-only",
        True,
        "Observation-trigger events, diagnostics, status, and console traces.",
        (
            "data/snapshots/observation_trigger*.json",
            "data/snapshots/observation_trigger*.jsonl",
            "data/snapshots/observation_trigger*.log",
            "data/snapshots/*/observation_trigger*.jsonl",
        ),
    ),
    RetentionRule(
        "settlement_ledgers",
        "irreplaceable_label_evidence",
        "retain permanently; settlement and quality labels gate promotion",
        True,
        "Settlement ledgers, market-day labels, and resolution provenance.",
        (
            "data/settlements/**/*",
            "data/backtest/market_day_labels.csv",
            "data/backtest/*settlement*.json",
            "data/backtest/*settlement*.csv",
        ),
    ),
    RetentionRule(
        "promotion_corpora",
        "pinned_replay_contract",
        "retain permanently; corpus hashes define model-promotion evidence",
        True,
        "Pinned promotion corpora, location trust, promotion decisions, and gauntlet outputs.",
        (
            "data/backtest/promotion_corpus*.json",
            "data/backtest/*promotion_refresh*.json",
            "data/backtest/*promotion_gauntlet*.json",
            "data/backtest/*promotion_replay*.json",
            "data/backtest/location_trust.json",
        ),
    ),
    RetentionRule(
        "market_making_runs",
        "irreplaceable_live_forward_tape",
        "retain permanently; paper/live-forward order state is audit evidence",
        True,
        "Market-making run folders, quote tapes, fills, budgets, and run summaries.",
        (
            "data/mm_runs/**/*",
            "data/backtest/mm*.json",
            "data/backtest/*known_edge*.json",
        ),
    ),
    RetentionRule(
        "order_lifecycle_and_risk",
        "irreplaceable_live_forward_tape",
        "retain permanently; risk and lifecycle ledgers prove live-gate safety",
        True,
        "Order lifecycle, risk, budget, and remediation-event records inside run folders.",
        (
            "data/mm_runs/**/*order*",
            "data/mm_runs/**/*lifecycle*",
            "data/mm_runs/**/*risk*",
            "data/mm_runs/**/*budget*",
            "data/mm_runs/**/*remediation*",
        ),
    ),
    RetentionRule(
        "model_artifacts_and_manifests",
        "rebuildable_but_operationally_pinned",
        "retain at least through the corresponding promotion and live-forward window",
        False,
        "Model artifacts and manifests needed to replay the exact deployed state.",
        (
            "artifacts/**/*.json",
            "artifacts/**/*.pkl",
            "artifacts/manifests/**/*",
        ),
    ),
    RetentionRule(
        "source_manifests",
        "rebuildable_manifest_context",
        "retain with source data; helps prove source provenance after restore",
        False,
        "Historical source manifests and station metadata.",
        (
            "data/**/manifest.json",
            "data/**/station.json",
        ),
    ),
    RetentionRule(
        "closed_market_day_parquet_archives",
        "validated_closed_day_projection",
        "retain with corresponding raw source evidence; rebuildable but required for closed-day analysis restore drills",
        False,
        "Closed market-day Parquet partitions and their archive manifests.",
        (
            "data/archive/closed_market_days/**/*.parquet",
            "data/archive/closed_market_days/**/closed_market_day_archive_manifest.json",
        ),
    ),
    RetentionRule(
        "operational_status",
        "rebuildable_derived_status",
        "retain latest statuses; reports are regenerated during restore drills",
        False,
        "Latest operational JSON status artifacts; Markdown reports and scratch logs are excluded.",
        (
            "data/backtest/daily_refresh_status.json",
            "data/backtest/fleet_observability.json",
            "data/backtest/artifact_provenance_manifest.json",
            "data/backtest/data_layer_audit.json",
            "data/backtest/snapshot_evaluation.json",
            "data/backtest/shadow_ab_monitor.json",
            "data/backtest/progress_audit.json",
        ),
    ),
)

GLOBAL_EXCLUDES = (
    "data/tape_backups/**",
    "**/*.lock",
    "**/*.pid",
    "**/*.tmp",
    "**/__pycache__/**",
)


def utc_now():
    return datetime.now(timezone.utc)


def utc_iso():
    return utc_now().isoformat()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _posix(path):
    return Path(path).as_posix()


def _matches_any(rel_path, patterns):
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in patterns)


def _excluded(rel_path, extra_excludes=()):
    return _matches_any(rel_path, GLOBAL_EXCLUDES) or _matches_any(rel_path, extra_excludes)


def retention_policy_payload():
    return {
        "policy_version": POLICY_VERSION,
        "classes": [asdict(rule) for rule in RETENTION_RULES],
        "storage_class_contracts": storage_class_contracts_payload(),
        "artifact_families": artifact_family_registry_payload(),
        "global_excludes": list(GLOBAL_EXCLUDES),
    }


def classify_path(rel_path):
    classes = []
    for rule in RETENTION_RULES:
        if _excluded(rel_path, rule.excludes):
            continue
        if _matches_any(rel_path, rule.patterns):
            classes.append(rule.name)
    return classes


def iter_candidate_files(source_root=REPO_ROOT):
    source_root = Path(source_root)
    seen = set()
    for rule in RETENTION_RULES:
        for pattern in rule.patterns:
            for path in source_root.glob(pattern):
                if not path.is_file():
                    continue
                if path.stat().st_size == 0:
                    continue
                rel = path.relative_to(source_root).as_posix()
                if rel in seen or _excluded(rel, rule.excludes):
                    continue
                seen.add(rel)
                yield path, rel


def file_entry(path, rel_path, classes):
    stat = Path(path).stat()
    return {
        "path": rel_path,
        "classes": sorted(classes),
        **classification_payload(rel_path),
        "size": stat.st_size,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "sha256": sha256_file(path),
    }


def class_summaries(entries):
    summaries = {}
    by_name = {rule.name: rule for rule in RETENTION_RULES}
    for rule in RETENTION_RULES:
        summaries[rule.name] = {
            "critical": rule.critical,
            "recoverability": rule.recoverability,
            "retention": rule.retention,
            "file_count": 0,
            "total_bytes": 0,
        }
    for entry in entries:
        for class_name in entry.get("classes") or []:
            summary = summaries.setdefault(class_name, {
                "critical": bool((by_name.get(class_name) or RetentionRule(class_name, "", "", False, "", ())).critical),
                "file_count": 0,
                "total_bytes": 0,
            })
            summary["file_count"] += 1
            summary["total_bytes"] += int(entry.get("size") or 0)
    return summaries


def _entry_without_hash(path, rel_path, classes):
    stat = Path(path).stat()
    return {
        "path": rel_path,
        "classes": sorted(classes),
        **classification_payload(rel_path),
        "size": stat.st_size,
        "mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _critical_classes(classes):
    by_name = {rule.name: rule for rule in RETENTION_RULES}
    return [
        name for name in classes or []
        if (by_name.get(name) and by_name[name].critical)
    ]


def local_candidate_entries(source_root=REPO_ROOT):
    entries = []
    for path, rel in iter_candidate_files(source_root):
        classes = classify_path(rel)
        if classes:
            entries.append(_entry_without_hash(path, rel, classes))
    entries.sort(key=lambda row: row["path"])
    return entries


def _summarize_entries_by_class(entries):
    summary = {
        rule.name: {"files": 0, "bytes": 0}
        for rule in RETENTION_RULES
    }
    for entry in entries or []:
        for class_name in entry.get("classes") or []:
            row = summary.setdefault(class_name, {"files": 0, "bytes": 0})
            row["files"] += 1
            row["bytes"] += int(entry.get("size") or 0)
    return summary


def _manifest_entry_map(manifest):
    return {
        row.get("path"): row
        for row in (manifest or {}).get("files") or []
        if row.get("path")
    }


def _entry_mtime(entry):
    try:
        return datetime.fromisoformat(str(entry.get("mtime_utc")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _manifest_cutoff(manifest):
    try:
        value = (manifest or {}).get("coverage_cutoff_utc") or (manifest or {}).get("generated_at_utc")
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _after_manifest_cutoff(entry, manifest_paths, cutoff):
    if not cutoff or entry.get("path") in manifest_paths:
        return False
    mtime = _entry_mtime(entry)
    return bool(mtime and mtime > cutoff)


def _clob_policy_for_path(rel_path):
    return [
        policy for policy in CLOB_ARTIFACT_POLICIES
        if _matches_any(rel_path, policy.patterns)
    ]


def clob_artifact_coverage(source_root=REPO_ROOT, manifest=None, manifest_cutoff=None):
    source_root = Path(source_root)
    manifest_entries = _manifest_entry_map(manifest)
    manifest_paths = set(manifest_entries)
    cutoff = manifest_cutoff if manifest_cutoff is not None else _manifest_cutoff(manifest)
    rows = []
    all_missing_required = []
    for policy in CLOB_ARTIFACT_POLICIES:
        local_paths = set()
        local_bytes = 0
        largest_file = {"path": None, "size": 0}
        for pattern in policy.patterns:
            for path in source_root.glob(pattern):
                if not path.is_file():
                    continue
                rel = path.relative_to(source_root).as_posix()
                if _excluded(rel):
                    continue
                entry = {
                    "path": rel,
                    "mtime_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                }
                if _after_manifest_cutoff(entry, manifest_paths, cutoff):
                    continue
                local_paths.add(rel)
        for rel in sorted(local_paths):
            size = (source_root / rel).stat().st_size
            local_bytes += size
            if size > int(largest_file.get("size") or 0):
                largest_file = {"path": rel, "size": size}
        backed_paths = sorted(local_paths & manifest_paths)
        missing_paths = sorted(local_paths - manifest_paths)
        backed_bytes = sum(int((manifest_entries.get(rel) or {}).get("size") or 0) for rel in backed_paths)
        excluded_bytes = local_bytes if not policy.backup_required else 0
        warnings = []
        if policy.per_file_warn_bytes and int(largest_file.get("size") or 0) > policy.per_file_warn_bytes:
            warnings.append({
                "type": "per_file_size",
                "threshold_bytes": policy.per_file_warn_bytes,
                "path": largest_file.get("path"),
                "size": largest_file.get("size"),
            })
        if policy.total_warn_bytes and local_bytes > policy.total_warn_bytes:
            warnings.append({
                "type": "total_size",
                "threshold_bytes": policy.total_warn_bytes,
                "bytes": local_bytes,
            })
        if policy.backup_required:
            all_missing_required.extend(missing_paths)
        rows.append({
            "name": policy.name,
            "recoverability": policy.recoverability,
            "backup_required": policy.backup_required,
            "description": policy.description,
            "local_files": len(local_paths),
            "local_bytes": local_bytes,
            "backed_up_files": len(backed_paths),
            "backed_up_bytes": backed_bytes,
            "missing_files": len(missing_paths),
            "missing_bytes": sum((source_root / rel).stat().st_size for rel in missing_paths),
            "excluded_bytes": excluded_bytes,
            "largest_file": largest_file if largest_file.get("path") else None,
            "warning_count": len(warnings),
            "warnings": warnings,
            "missing_samples": missing_paths[:20],
        })
    return {
        "source_root": str(source_root),
        "classes": rows,
        "summary": {
            "required_class_count": sum(1 for policy in CLOB_ARTIFACT_POLICIES if policy.backup_required),
            "local_files": sum(row["local_files"] for row in rows),
            "local_bytes": sum(row["local_bytes"] for row in rows),
            "backed_up_files": sum(row["backed_up_files"] for row in rows),
            "backed_up_bytes": sum(row["backed_up_bytes"] for row in rows),
            "missing_required_files": len(all_missing_required),
            "missing_required_samples": all_missing_required[:20],
            "warning_count": sum(row["warning_count"] for row in rows),
        },
    }


def local_manifest_coverage_audit(source_root=REPO_ROOT, manifest=None):
    source_root = Path(source_root)
    if not source_root.exists():
        return {
            "source_root": str(source_root),
            "source_root_exists": False,
            "status": "SKIPPED",
            "reason": "source root does not exist on this host",
            "missing_critical_files": 0,
            "missing_critical_bytes": 0,
            "missing_critical_samples": [],
            "class_coverage": {},
            "clob_artifacts": {"classes": [], "summary": {}},
        }
    manifest_paths = set(_manifest_entry_map(manifest))
    cutoff = _manifest_cutoff(manifest)
    all_local_entries = local_candidate_entries(source_root)
    post_manifest_entries = [
        entry for entry in all_local_entries
        if _after_manifest_cutoff(entry, manifest_paths, cutoff)
    ]
    local_entries = [
        entry for entry in all_local_entries
        if not _after_manifest_cutoff(entry, manifest_paths, cutoff)
    ]
    local_by_class = _summarize_entries_by_class(local_entries)
    backed_by_class = _summarize_entries_by_class((manifest or {}).get("files") or [])
    missing_critical = []
    missing_critical_bytes = 0
    post_manifest_critical = []
    post_manifest_critical_bytes = 0
    for entry in post_manifest_entries:
        critical = _critical_classes(entry.get("classes") or [])
        if not critical:
            continue
        post_manifest_critical.append({**entry, "critical_classes": critical})
        post_manifest_critical_bytes += int(entry.get("size") or 0)
    for entry in local_entries:
        if entry.get("path") in manifest_paths:
            continue
        critical = _critical_classes(entry.get("classes") or [])
        if not critical:
            continue
        missing = {**entry, "critical_classes": critical}
        missing_critical.append(missing)
        missing_critical_bytes += int(entry.get("size") or 0)

    class_coverage = {}
    for rule in RETENTION_RULES:
        local = local_by_class.get(rule.name, {"files": 0, "bytes": 0})
        backed = backed_by_class.get(rule.name, {"files": 0, "bytes": 0})
        class_coverage[rule.name] = {
            "critical": rule.critical,
            "local_files": local.get("files", 0),
            "local_bytes": local.get("bytes", 0),
            "backed_up_files": backed.get("files", 0),
            "backed_up_bytes": backed.get("bytes", 0),
            "missing_files": max(0, int(local.get("files", 0)) - int(backed.get("files", 0))),
            "missing_bytes": max(0, int(local.get("bytes", 0)) - int(backed.get("bytes", 0))),
        }
    status = "PASS" if not missing_critical else "FAIL"
    return {
        "source_root": str(source_root),
        "source_root_exists": True,
        "status": status,
        "local_candidate_files": len(local_entries),
        "local_candidate_bytes": sum(int(row.get("size") or 0) for row in local_entries),
        "total_local_candidate_files": len(all_local_entries),
        "total_local_candidate_bytes": sum(int(row.get("size") or 0) for row in all_local_entries),
        "manifest_cutoff_utc": cutoff.isoformat() if cutoff else None,
        "post_manifest_candidate_files": len(post_manifest_entries),
        "post_manifest_candidate_bytes": sum(int(row.get("size") or 0) for row in post_manifest_entries),
        "post_manifest_critical_files": len(post_manifest_critical),
        "post_manifest_critical_bytes": post_manifest_critical_bytes,
        "post_manifest_critical_samples": post_manifest_critical[:50],
        "missing_critical_files": len(missing_critical),
        "missing_critical_bytes": missing_critical_bytes,
        "missing_critical_samples": missing_critical[:50],
        "class_coverage": class_coverage,
        "clob_artifacts": clob_artifact_coverage(source_root, manifest, manifest_cutoff=cutoff),
    }


def manifest_hash_payload(manifest):
    return {
        "schema_version": manifest.get("schema_version"),
        "policy_version": manifest.get("policy_version"),
        "coverage_cutoff_utc": manifest.get("coverage_cutoff_utc"),
        "source_root": manifest.get("source_root"),
        "files": manifest.get("files") or [],
        "class_summaries": manifest.get("class_summaries") or {},
        "storage_class_summaries": manifest.get("storage_class_summaries") or {},
    }


def manifest_hash(manifest):
    encoded = json.dumps(
        manifest_hash_payload(manifest),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_backup_manifest(source_root=REPO_ROOT):
    source_root = Path(source_root)
    coverage_cutoff_utc = utc_iso()
    entries = []
    for path, rel in iter_candidate_files(source_root):
        classes = classify_path(rel)
        if classes:
            entries.append(file_entry(path, rel, classes))
    entries.sort(key=lambda row: row["path"])
    summaries = class_summaries(entries)
    storage_summaries = summarize_storage_class_entries(entries)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "coverage_cutoff_utc": coverage_cutoff_utc,
        "generated_at_utc": utc_iso(),
        "source_root": str(source_root),
        "policy": retention_policy_payload(),
        "class_summaries": summaries,
        "storage_class_summaries": storage_summaries,
        "files": entries,
        "summary": {
            "file_count": len(entries),
            "total_bytes": sum(int(row.get("size") or 0) for row in entries),
            "critical_class_count": sum(1 for rule in RETENTION_RULES if rule.critical),
            "missing_critical_classes": [
                rule.name for rule in RETENTION_RULES
                if rule.critical and not summaries.get(rule.name, {}).get("file_count")
            ],
        },
    }
    manifest["manifest_hash"] = manifest_hash(manifest)
    return manifest


def _same_backup_file(path, sha256):
    path = Path(path)
    return path.exists() and sha256_file(path) == sha256


class TapeBackupCapacityError(RuntimeError):
    def __init__(self, preflight):
        self.preflight = preflight
        super().__init__(
            "insufficient backup capacity: "
            f"need {preflight.get('required_bytes')} bytes including margin, "
            f"free {preflight.get('free_bytes')} bytes"
        )


def disk_usage_root(path):
    path = Path(path)
    probe = path if path.exists() else path.parent
    while probe and not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe


def backup_capacity_preflight(
    manifest,
    backup_root=DEFAULT_BACKUP_ROOT,
    *,
    margin_bytes=DEFAULT_CAPACITY_MARGIN_BYTES,
    exact=True,
):
    backup_root = Path(backup_root)
    latest_root = backup_root / LATEST_DIR
    planned = []
    skipped = 0
    planned_bytes = 0
    largest = None
    for entry in manifest.get("files") or []:
        dst = latest_root / entry["path"]
        same = False
        if exact:
            same = _same_backup_file(dst, entry.get("sha256"))
        elif dst.exists():
            same = int(dst.stat().st_size) == int(entry.get("size") or 0)
        if same:
            skipped += 1
            continue
        size = int(entry.get("size") or 0)
        planned_bytes += size
        row = {"path": entry.get("path"), "size": size}
        planned.append(row)
        if largest is None or size > int(largest.get("size") or 0):
            largest = row
    usage_path = disk_usage_root(backup_root)
    usage = shutil.disk_usage(usage_path)
    required = planned_bytes + int(margin_bytes or 0)
    free = int(usage.free)
    status = "PASS" if free >= required else "INSUFFICIENT_BACKUP_CAPACITY"
    return {
        "status": status,
        "backup_root": str(backup_root),
        "latest_root": str(latest_root),
        "disk_usage_path": str(usage_path),
        "free_bytes": free,
        "required_bytes": required,
        "planned_copy_bytes": planned_bytes,
        "capacity_margin_bytes": int(margin_bytes or 0),
        "insufficient_bytes": max(0, required - free),
        "planned_copy_files": len(planned),
        "skipped_unchanged_files": skipped,
        "largest_planned_copy": largest,
        "planned_copy_samples": planned[:20],
    }


def coverage_capacity_preflight(
    coverage,
    backup_root=DEFAULT_BACKUP_ROOT,
    *,
    margin_bytes=DEFAULT_CAPACITY_MARGIN_BYTES,
):
    backup_root = Path(backup_root)
    usage_path = disk_usage_root(backup_root)
    usage = shutil.disk_usage(usage_path)
    missing_bytes = int((coverage or {}).get("missing_critical_bytes") or 0)
    required = missing_bytes + int(margin_bytes or 0)
    free = int(usage.free)
    status = "PASS" if missing_bytes == 0 or free >= required else "INSUFFICIENT_BACKUP_CAPACITY"
    return {
        "status": status,
        "backup_root": str(backup_root),
        "disk_usage_path": str(usage_path),
        "free_bytes": free,
        "required_bytes": required,
        "missing_critical_bytes": missing_bytes,
        "capacity_margin_bytes": int(margin_bytes or 0),
        "insufficient_bytes": max(0, required - free),
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def default_dedup_manifest_path(source_root=REPO_ROOT):
    return Path(source_root) / "data" / "backtest" / DEFAULT_DEDUP_MANIFEST_NAME


def _tail_text(text, limit=4000):
    text = str(text or "")
    if len(text) <= int(limit):
        return text
    return text[-int(limit):]


def _path_relative_to_root(path, root):
    path = Path(path).resolve()
    root = Path(root).resolve()
    return path.relative_to(root).as_posix()


def _dedup_env(repository=None, password_file=None, env=None):
    merged = dict(os.environ if env is None else env)
    repo = (
        str(repository or "").strip()
        or str(merged.get("WEATHER_TAPE_DEDUP_REPOSITORY") or "").strip()
        or str(merged.get("RESTIC_REPOSITORY") or "").strip()
    )
    if repo:
        merged["RESTIC_REPOSITORY"] = repo
    if password_file:
        merged["RESTIC_PASSWORD_FILE"] = str(password_file)
    elif merged.get("WEATHER_TAPE_DEDUP_PASSWORD_FILE") and not merged.get("RESTIC_PASSWORD_FILE"):
        merged["RESTIC_PASSWORD_FILE"] = str(merged["WEATHER_TAPE_DEDUP_PASSWORD_FILE"])
    if (
        merged.get("WEATHER_TAPE_DEDUP_PASSWORD")
        and not merged.get("RESTIC_PASSWORD")
        and not merged.get("RESTIC_PASSWORD_FILE")
        and not merged.get("RESTIC_PASSWORD_COMMAND")
    ):
        merged["RESTIC_PASSWORD"] = str(merged["WEATHER_TAPE_DEDUP_PASSWORD"])
    return merged, repo


def _restic_credential_sources(env):
    return [
        name for name in ("RESTIC_PASSWORD_FILE", "RESTIC_PASSWORD_COMMAND", "RESTIC_PASSWORD")
        if env.get(name)
    ]


def dedup_repository_preflight(
    *,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    env=None,
):
    merged_env, repo = _dedup_env(repository=repository, password_file=password_file, env=env)
    backend = str(backend or "").strip().lower()
    credential_sources = _restic_credential_sources(merged_env)
    binary_path = shutil.which(str(executable), path=merged_env.get("PATH"))
    failures = []
    if backend != DEDUP_BACKEND_RESTIC:
        failures.append({"check": "backend", "reason": f"unsupported backend {backend or '-'}"})
    if not repo:
        failures.append({
            "check": "repository",
            "reason": "set WEATHER_TAPE_DEDUP_REPOSITORY or RESTIC_REPOSITORY",
        })
    if not credential_sources:
        failures.append({
            "check": "credentials",
            "reason": "set RESTIC_PASSWORD_FILE, RESTIC_PASSWORD_COMMAND, or RESTIC_PASSWORD",
        })
    if not binary_path:
        failures.append({"check": "restic_binary", "reason": f"{executable} was not found on PATH"})
    return {
        "status": "PASS" if not failures else "CONFIGURATION_INCOMPLETE",
        "backend": backend,
        "repository": repo,
        "executable": str(executable),
        "binary_path": binary_path,
        "credential_sources": credential_sources,
        "credential_material_present": bool(credential_sources),
        "failures": failures,
    }, merged_env


def _run_restic(executable, args, *, cwd=None, env=None, timeout_seconds=3600):
    command = [str(executable), *[str(arg) for arg in args]]
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        return {
            "status": "MISSING_RESTIC_BINARY",
            "command": command,
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": str(exc),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "TIMEOUT",
            "command": command,
            "returncode": None,
            "stdout_tail": _tail_text(exc.stdout),
            "stderr_tail": _tail_text(exc.stderr or f"timed out after {timeout_seconds}s"),
        }
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stdout_tail": _tail_text(completed.stdout),
        "stderr_tail": _tail_text(completed.stderr),
    }


def _parse_restic_snapshots(stdout):
    try:
        payload = json.loads(stdout or "[]")
    except json.JSONDecodeError as exc:
        return [], str(exc)
    if isinstance(payload, dict):
        payload = payload.get("snapshots") or []
    if not isinstance(payload, list):
        return [], "restic snapshots JSON was not a list"
    snapshots = [row for row in payload if isinstance(row, dict)]
    return snapshots, None


def _latest_restic_snapshot(stdout):
    snapshots, error = _parse_restic_snapshots(stdout)
    if error:
        return None, snapshots, error
    latest = None
    latest_time = None
    for row in snapshots:
        parsed = _parse_time(row.get("time"))
        if parsed is None:
            continue
        if latest_time is None or parsed > latest_time:
            latest = row
            latest_time = parsed
    if latest is None and snapshots:
        latest = snapshots[-1]
    return latest, snapshots, None


def _snapshot_id_from_backup_output(stdout):
    snapshot_id = None
    for line in str(stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            snapshot_id = row.get("snapshot_id") or row.get("id") or snapshot_id
    return snapshot_id


def load_dedup_restore_drill_status(path=DEFAULT_DEDUP_RESTORE_OUT):
    path = Path(path)
    if not path.exists():
        return {"exists": False, "path": str(path), "status": "MISSING"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"exists": True, "path": str(path), "status": "UNREADABLE", "error": str(exc)}
    payload["exists"] = True
    payload["path"] = str(path)
    generated = _parse_time(payload.get("generated_at_utc"))
    if generated:
        payload["age_hours"] = round((utc_now() - generated).total_seconds() / 3600.0, 3)
    return payload


def dedup_restore_drill_sla_status(restore, snapshot_id=None, max_restore_age_hours=168):
    restore = restore or {}
    if not restore.get("exists"):
        return "RESTORE_DRILL_MISSING", "no dedup repository restore drill evidence recorded"
    if restore.get("status") in {"UNREADABLE", "FAIL"}:
        return "RESTORE_DRILL_FAIL", restore.get("error") or "dedup repository restore drill failed"
    if restore.get("status") != "PASS":
        return "RESTORE_DRILL_FAIL", f"unexpected restore drill status {restore.get('status')}"
    if snapshot_id and restore.get("snapshot_id") != snapshot_id:
        return "RESTORE_DRILL_STALE", "restore drill snapshot does not match latest dedup repository snapshot"
    age_hours = restore.get("age_hours")
    if age_hours is not None and float(age_hours) > float(max_restore_age_hours):
        return "RESTORE_DRILL_STALE", f"restore drill age {age_hours}h exceeds SLA {max_restore_age_hours}h"
    return "OK", "dedup repository restore drill evidence is current"


def dedup_repository_status(
    *,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    restore_drill_path=DEFAULT_DEDUP_RESTORE_OUT,
    max_age_hours=26,
    max_restore_age_hours=168,
    require_restore_drill=True,
    env=None,
    timeout_seconds=300,
):
    preflight, merged_env = dedup_repository_preflight(
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        env=env,
    )
    payload = {
        "schema_version": DEDUP_REPOSITORY_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "kind": "status",
        "status": preflight["status"],
        "backend": preflight["backend"],
        "repository": preflight["repository"],
        "preflight": preflight,
        "snapshot_tag": DEDUP_RESTIC_TAG,
        "snapshot_count": 0,
        "latest_snapshot": None,
        "latest_snapshot_age_hours": None,
        "commands": {},
        "last_restore_drill": load_dedup_restore_drill_status(restore_drill_path),
        "restore_drill_sla_status": "-",
        "restore_drill_sla_detail": "restore drill not checked",
    }
    if preflight["status"] != "PASS":
        return payload
    snapshots = _run_restic(
        executable,
        ["snapshots", "--json", "--tag", DEDUP_RESTIC_TAG],
        env=merged_env,
        timeout_seconds=timeout_seconds,
    )
    payload["commands"]["snapshots"] = snapshots
    if snapshots["status"] != "PASS":
        payload["status"] = "REPOSITORY_UNREACHABLE"
        return payload
    latest, parsed_snapshots, parse_error = _latest_restic_snapshot(snapshots.get("stdout") or snapshots.get("stdout_tail") or "")
    payload["snapshot_count"] = len(parsed_snapshots)
    if parse_error:
        payload["status"] = "SNAPSHOT_STATUS_UNREADABLE"
        payload["snapshot_parse_error"] = parse_error
        return payload
    if not latest:
        payload["status"] = "NO_SNAPSHOTS"
        return payload
    generated = _parse_time(latest.get("time"))
    age_hours = None
    if generated:
        age_hours = round((utc_now() - generated).total_seconds() / 3600.0, 3)
    payload["latest_snapshot"] = latest
    payload["latest_snapshot_age_hours"] = age_hours
    payload["status"] = "OK"
    if age_hours is not None and age_hours > float(max_age_hours):
        payload["status"] = "STALE"
    if require_restore_drill:
        restore_status, restore_detail = dedup_restore_drill_sla_status(
            payload["last_restore_drill"],
            snapshot_id=latest.get("id") or latest.get("short_id"),
            max_restore_age_hours=max_restore_age_hours,
        )
        payload["restore_drill_sla_status"] = restore_status
        payload["restore_drill_sla_detail"] = restore_detail
        if payload["status"] == "OK" and restore_status != "OK":
            payload["status"] = restore_status
    return payload


def write_dedup_status_report(path, payload):
    latest = payload.get("latest_snapshot") or {}
    lines = [
        "# Deduplicated Tape Repository Status",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Backend: `{payload.get('backend')}`",
        f"Repository: `{payload.get('repository') or '-'}`",
        f"Snapshot tag: `{payload.get('snapshot_tag')}`",
        f"Snapshot count: `{payload.get('snapshot_count')}`",
        f"Latest snapshot: `{latest.get('id') or latest.get('short_id') or '-'}`",
        f"Latest snapshot age hours: `{payload.get('latest_snapshot_age_hours')}`",
        f"Restore drill SLA: **{payload.get('restore_drill_sla_status') or '-'}**",
        f"Restore drill detail: `{payload.get('restore_drill_sla_detail') or '-'}`",
        "",
        "## Preflight",
        "",
    ]
    failures = (payload.get("preflight") or {}).get("failures") or []
    if failures:
        lines.extend(f"- `{row.get('check')}`: {row.get('reason')}" for row in failures)
    else:
        lines.append("- configuration complete")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_dedup_backup_report(path, payload):
    lines = [
        "# Deduplicated Tape Repository Backup",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Backend: `{payload.get('backend')}`",
        f"Repository: `{payload.get('repository') or '-'}`",
        f"Snapshot id: `{payload.get('snapshot_id') or '-'}`",
        f"Manifest hash: `{payload.get('manifest_hash') or '-'}`",
        f"Files listed: `{payload.get('files_from_count') or 0}`",
        f"Total bytes: `{payload.get('total_bytes') or 0}`",
        "",
        "## Missing Critical Classes",
        "",
    ]
    lines.extend(f"- {name}" for name in payload.get("missing_critical_classes") or ["-"])
    failures = (payload.get("preflight") or {}).get("failures") or []
    if failures:
        lines += ["", "## Preflight Failures", ""]
        lines.extend(f"- `{row.get('check')}`: {row.get('reason')}" for row in failures)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_dedup_backup(
    *,
    source_root=REPO_ROOT,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    manifest_out=None,
    out=DEFAULT_DEDUP_BACKUP_OUT,
    report=DEFAULT_DEDUP_BACKUP_REPORT,
    env=None,
    timeout_seconds=3600,
):
    source_root = Path(source_root)
    preflight, merged_env = dedup_repository_preflight(
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        env=env,
    )
    payload = {
        "schema_version": DEDUP_REPOSITORY_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "kind": "backup",
        "status": preflight["status"],
        "backend": preflight["backend"],
        "repository": preflight["repository"],
        "source_root": str(source_root),
        "preflight": preflight,
        "snapshot_tag": DEDUP_RESTIC_TAG,
        "commands": {},
    }
    if preflight["status"] != "PASS":
        write_json(out, payload)
        _write_dedup_backup_report(report, payload)
        return payload

    manifest = build_backup_manifest(source_root)
    manifest_out = Path(manifest_out) if manifest_out else default_dedup_manifest_path(source_root)
    manifest_rel = _path_relative_to_root(manifest_out, source_root)
    write_json(manifest_out, manifest)
    file_paths = [row["path"] for row in manifest.get("files") or []]
    if manifest_rel not in file_paths:
        file_paths.append(manifest_rel)
    file_paths = sorted(dict.fromkeys(file_paths))

    probe = _run_restic(
        executable,
        ["snapshots", "--json", "--tag", DEDUP_RESTIC_TAG],
        env=merged_env,
        timeout_seconds=timeout_seconds,
    )
    payload["commands"]["repository_probe"] = probe
    payload.update({
        "manifest_path": str(manifest_out),
        "manifest_rel_path": manifest_rel,
        "manifest_hash": manifest.get("manifest_hash"),
        "file_count": (manifest.get("summary") or {}).get("file_count"),
        "files_from_count": len(file_paths),
        "total_bytes": (manifest.get("summary") or {}).get("total_bytes"),
        "missing_critical_classes": (manifest.get("summary") or {}).get("missing_critical_classes") or [],
    })
    if probe["status"] != "PASS":
        payload["status"] = "REPOSITORY_UNREACHABLE"
        write_json(out, payload)
        _write_dedup_backup_report(report, payload)
        return payload

    with tempfile.TemporaryDirectory(prefix="weather-tape-restic-files-") as tmp:
        files_from = Path(tmp) / "files-from.txt"
        files_from.write_text("\n".join(file_paths) + "\n", encoding="utf-8")
        backup = _run_restic(
            executable,
            [
                "backup",
                "--files-from",
                str(files_from),
                "--tag",
                DEDUP_RESTIC_TAG,
                "--tag",
                POLICY_VERSION,
                "--json",
            ],
            cwd=source_root,
            env=merged_env,
            timeout_seconds=timeout_seconds,
        )
    payload["commands"]["backup"] = backup
    payload["snapshot_id"] = _snapshot_id_from_backup_output(backup.get("stdout_tail") or "")
    payload["status"] = "PASS" if backup["status"] == "PASS" else "BACKUP_FAILED"
    write_json(out, payload)
    _write_dedup_backup_report(report, payload)
    return payload


def _first_path_matching(entries, predicate):
    for entry in entries:
        path = entry.get("path") or ""
        if predicate(path, entry):
            return path
    return None


def select_dedup_restore_drill_paths(manifest, *, control_manifest_rel_path=None):
    entries = manifest.get("files") or []
    categories = {
        "raw_order_book_jsonl": _first_path_matching(
            entries,
            lambda path, entry: path.endswith("order_books.jsonl"),
        ) or _first_path_matching(
            entries,
            lambda path, entry: path.endswith(".jsonl") and bool(_critical_classes(entry.get("classes") or [])),
        ),
        "parquet_partition": _first_path_matching(entries, lambda path, entry: path.endswith(".parquet")),
        "archive_manifest": _first_path_matching(
            entries,
            lambda path, entry: path.endswith("closed_market_day_archive_manifest.json"),
        ) or _first_path_matching(entries, lambda path, entry: path.endswith("/manifest.json")),
        "replay_artifact": _first_path_matching(
            entries,
            lambda path, entry: path.startswith("artifacts/"),
        ) or _first_path_matching(
            entries,
            lambda path, entry: path.endswith("replay_inputs.jsonl") or path.endswith("replay_inputs_reconstructed.jsonl"),
        ),
    }
    paths = []
    if control_manifest_rel_path:
        paths.append(control_manifest_rel_path)
    for path in categories.values():
        if path:
            paths.append(path)
    return {
        "categories": categories,
        "missing_categories": [name for name, path in categories.items() if not path],
        "paths": sorted(dict.fromkeys(paths)),
    }


def _closed_archive_parquet_expectations(restore_root, selected_paths):
    restore_root = Path(restore_root)
    expectations = {}
    for rel in selected_paths:
        if not str(rel).endswith("closed_market_day_archive_manifest.json"):
            continue
        path = restore_root / rel
        if not path.exists():
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for family in manifest.get("artifact_families") or []:
            parquet = family.get("parquet") or {}
            parquet_rel = parquet.get("path")
            if not parquet_rel:
                continue
            try:
                key = (path.parent / parquet_rel).relative_to(restore_root).as_posix()
            except ValueError:
                continue
            expectations[key] = parquet.get("row_count")
    return expectations


def _parquet_row_count(path):
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        return {"status": "skipped", "reason": f"pyarrow unavailable: {exc}"}
    try:
        return {"status": "ok", "row_count": int(pq.ParquetFile(path).metadata.num_rows)}
    except Exception as exc:  # noqa: BLE001 - row-count validation must report the parser failure
        return {"status": "fail", "reason": str(exc)}


def _verify_dedup_restored_paths(restore_root, manifest, selected):
    restore_root = Path(restore_root)
    manifest_entries = _manifest_entry_map(manifest)
    expectations = _closed_archive_parquet_expectations(restore_root, selected)
    failures = []
    schema_checks = []
    parquet_checks = []
    verified = 0
    for rel in selected:
        if rel not in manifest_entries:
            continue
        entry = manifest_entries[rel]
        path = restore_root / rel
        if not path.exists():
            failures.append({"path": rel, "reason": "missing_restored_file"})
            continue
        verified += 1
        actual_sha = sha256_file(path)
        if actual_sha != entry.get("sha256"):
            failures.append({
                "path": rel,
                "reason": "restored_sha256_mismatch",
                "expected": entry.get("sha256"),
                "actual": actual_sha,
            })
        check = _schema_check(path)
        if check:
            schema_checks.append(check)
        if rel.endswith(".parquet"):
            parquet_check = {"path": rel, **_parquet_row_count(path)}
            expected = expectations.get(rel)
            if expected is not None and parquet_check.get("status") == "ok":
                parquet_check["expected_row_count"] = int(expected)
                if int(expected) != int(parquet_check.get("row_count") or -1):
                    parquet_check["status"] = "fail"
                    parquet_check["reason"] = "row_count_mismatch"
            parquet_checks.append(parquet_check)
    schema_failures = [row for row in schema_checks if row.get("status") not in {"ok"}]
    parquet_failures = [row for row in parquet_checks if row.get("status") == "fail"]
    return {
        "verified_files": verified,
        "checksum_failures": failures,
        "schema_checks": schema_checks,
        "schema_failures": schema_failures,
        "parquet_checks": parquet_checks,
        "parquet_failures": parquet_failures,
    }


def _write_dedup_restore_report(path, payload):
    lines = [
        "# Deduplicated Tape Repository Restore Drill",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Backend: `{payload.get('backend')}`",
        f"Repository: `{payload.get('repository') or '-'}`",
        f"Snapshot id: `{payload.get('snapshot_id') or '-'}`",
        f"Restore root: `{payload.get('restore_root') or '-'}`",
        f"Manifest hash: `{payload.get('manifest_hash') or '-'}`",
        f"Verified files: `{payload.get('verified_files') or 0}`",
        "",
        "## Drill Categories",
        "",
    ]
    for name, rel in (payload.get("drill_selection") or {}).get("categories", {}).items():
        lines.append(f"- `{name}`: `{rel or 'MISSING'}`")
    failures = (
        (payload.get("checksum_failures") or [])
        + (payload.get("schema_failures") or [])
        + (payload.get("parquet_failures") or [])
    )
    lines += ["", "## Failures", ""]
    if failures:
        lines.extend(f"- `{row.get('path')}`: {row.get('reason') or row.get('status')}" for row in failures)
    else:
        lines.append("- none")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_dedup_restore_drill(
    *,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    snapshot_id=None,
    manifest_rel_path=f"data/backtest/{DEFAULT_DEDUP_MANIFEST_NAME}",
    restore_root=None,
    keep_restore=False,
    out=DEFAULT_DEDUP_RESTORE_OUT,
    report=DEFAULT_DEDUP_RESTORE_REPORT,
    env=None,
    timeout_seconds=3600,
):
    status_payload = dedup_repository_status(
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        require_restore_drill=False,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    latest = status_payload.get("latest_snapshot") or {}
    snapshot_id = snapshot_id or latest.get("id") or latest.get("short_id")
    temp_ctx = None
    if restore_root is None:
        temp_ctx = tempfile.TemporaryDirectory(prefix="weather-tape-dedup-restore-")
        restore_root = Path(temp_ctx.name)
    else:
        restore_root = Path(restore_root)
        restore_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": DEDUP_REPOSITORY_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "kind": "restore_drill",
        "status": "FAIL",
        "backend": status_payload.get("backend"),
        "repository": status_payload.get("repository"),
        "snapshot_tag": DEDUP_RESTIC_TAG,
        "snapshot_id": snapshot_id,
        "restore_root": str(restore_root),
        "keep_restore": bool(keep_restore),
        "repository_status": status_payload,
        "commands": {},
        "manifest_rel_path": manifest_rel_path,
        "manifest_valid": False,
        "manifest_detail": "not restored",
        "manifest_hash": None,
        "verified_files": 0,
        "drill_selection": {"categories": {}, "missing_categories": [], "paths": []},
        "checksum_failures": [],
        "schema_checks": [],
        "schema_failures": [],
        "parquet_checks": [],
        "parquet_failures": [],
    }
    try:
        if status_payload.get("status") not in {"OK", "STALE"} or not snapshot_id:
            payload["failure_reason"] = "dedup repository has no restorable snapshot"
            write_json(out, payload)
            _write_dedup_restore_report(report, payload)
            return payload
        preflight, merged_env = dedup_repository_preflight(
            backend=backend,
            repository=repository,
            executable=executable,
            password_file=password_file,
            env=env,
        )
        if preflight["status"] != "PASS":
            payload["preflight"] = preflight
            payload["failure_reason"] = "dedup repository configuration incomplete"
            write_json(out, payload)
            _write_dedup_restore_report(report, payload)
            return payload
        restore_manifest = _run_restic(
            executable,
            ["restore", snapshot_id, "--target", str(restore_root), "--include", manifest_rel_path],
            env=merged_env,
            timeout_seconds=timeout_seconds,
        )
        payload["commands"]["restore_manifest"] = restore_manifest
        manifest_path = restore_root / manifest_rel_path
        if restore_manifest["status"] != "PASS" or not manifest_path.exists():
            payload["failure_reason"] = "control manifest was not restored"
            write_json(out, payload)
            _write_dedup_restore_report(report, payload)
            return payload
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        valid, detail = validate_manifest(manifest)
        payload["manifest_valid"] = valid
        payload["manifest_detail"] = detail
        payload["manifest_hash"] = manifest.get("manifest_hash")
        selection = select_dedup_restore_drill_paths(
            manifest,
            control_manifest_rel_path=manifest_rel_path,
        )
        payload["drill_selection"] = selection
        include_args = []
        for rel in selection.get("paths") or []:
            include_args.extend(["--include", rel])
        restore_selected = _run_restic(
            executable,
            ["restore", snapshot_id, "--target", str(restore_root), *include_args],
            env=merged_env,
            timeout_seconds=timeout_seconds,
        )
        payload["commands"]["restore_selected"] = restore_selected
        verification = _verify_dedup_restored_paths(
            restore_root,
            manifest,
            [rel for rel in selection.get("paths") or [] if rel != manifest_rel_path],
        )
        payload.update(verification)
        failures = (
            not valid
            or restore_selected["status"] != "PASS"
            or selection.get("missing_categories")
            or verification.get("checksum_failures")
            or verification.get("schema_failures")
            or verification.get("parquet_failures")
        )
        payload["status"] = "FAIL" if failures else "PASS"
        write_json(out, payload)
        _write_dedup_restore_report(report, payload)
        return payload
    finally:
        if temp_ctx is not None and not keep_restore:
            temp_ctx.cleanup()


def run_dedup_job(
    *,
    source_root=REPO_ROOT,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    manifest_out=None,
    backup_out=DEFAULT_DEDUP_BACKUP_OUT,
    backup_report=DEFAULT_DEDUP_BACKUP_REPORT,
    restore_out=DEFAULT_DEDUP_RESTORE_OUT,
    restore_report=DEFAULT_DEDUP_RESTORE_REPORT,
    status_out=DEFAULT_DEDUP_STATUS_OUT,
    status_report=DEFAULT_DEDUP_STATUS_REPORT,
    restore_root=None,
    keep_restore=False,
    env=None,
    timeout_seconds=3600,
):
    backup = run_dedup_backup(
        source_root=source_root,
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        manifest_out=manifest_out,
        out=backup_out,
        report=backup_report,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    restore = {"status": "SKIPPED", "reason": "backup did not pass"}
    if backup.get("status") == "PASS":
        restore = run_dedup_restore_drill(
            backend=backend,
            repository=repository,
            executable=executable,
            password_file=password_file,
            snapshot_id=backup.get("snapshot_id") or None,
            manifest_rel_path=backup.get("manifest_rel_path") or f"data/backtest/{DEFAULT_DEDUP_MANIFEST_NAME}",
            restore_root=restore_root,
            keep_restore=keep_restore,
            out=restore_out,
            report=restore_report,
            env=env,
            timeout_seconds=timeout_seconds,
        )
    status = dedup_repository_status(
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        restore_drill_path=restore_out,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    write_json(status_out, status)
    write_dedup_status_report(status_report, status)
    return {
        "schema_version": DEDUP_REPOSITORY_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "kind": "job",
        "status": "PASS" if backup.get("status") == "PASS" and restore.get("status") == "PASS" and status.get("status") == "OK" else "FAIL",
        "backup": backup,
        "restore_drill": restore,
        "repository_status": status,
        "backup_out": str(backup_out),
        "backup_report": str(backup_report),
        "restore_out": str(restore_out),
        "restore_report": str(restore_report),
        "status_out": str(status_out),
        "status_report": str(status_report),
    }


def export_backup(
    source_root=REPO_ROOT,
    backup_root=DEFAULT_BACKUP_ROOT,
    dry_run=False,
    capacity_preflight=True,
    capacity_margin_bytes=DEFAULT_CAPACITY_MARGIN_BYTES,
):
    source_root = Path(source_root)
    backup_root = Path(backup_root)
    manifest = build_backup_manifest(source_root)
    latest_root = backup_root / LATEST_DIR
    copied = 0
    skipped = 0
    preflight = None
    if not dry_run:
        latest_root.mkdir(parents=True, exist_ok=True)
        if capacity_preflight:
            preflight = backup_capacity_preflight(
                manifest,
                backup_root,
                margin_bytes=capacity_margin_bytes,
                exact=True,
            )
            if preflight["status"] != "PASS":
                manifest["backup"] = {
                    "backup_root": str(backup_root),
                    "latest_root": str(latest_root),
                    "dry_run": bool(dry_run),
                    "capacity_preflight": preflight,
                    "copied_files": 0,
                    "skipped_unchanged_files": preflight.get("skipped_unchanged_files", 0),
                }
                raise TapeBackupCapacityError(preflight)
    for entry in manifest["files"]:
        src = source_root / entry["path"]
        dst = latest_root / entry["path"]
        if dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if _same_backup_file(dst, entry["sha256"]):
            skipped += 1
            continue
        shutil.copy2(src, dst)
        copied += 1
    if not dry_run:
        backed_up_entries = []
        for entry in manifest["files"]:
            dst = latest_root / entry["path"]
            if not dst.exists():
                continue
            backed_up_entries.append(file_entry(dst, entry["path"], entry.get("classes") or []))
        manifest["files"] = backed_up_entries
        manifest["class_summaries"] = class_summaries(backed_up_entries)
        manifest["storage_class_summaries"] = summarize_storage_class_entries(backed_up_entries)
        manifest["summary"].update({
            "file_count": len(backed_up_entries),
            "total_bytes": sum(int(row.get("size") or 0) for row in backed_up_entries),
            "missing_critical_classes": [
                rule.name for rule in RETENTION_RULES
                if rule.critical and not manifest["class_summaries"].get(rule.name, {}).get("file_count")
            ],
        })
    manifest["backup"] = {
        "backup_root": str(backup_root),
        "latest_root": str(latest_root),
        "dry_run": bool(dry_run),
        "capacity_preflight": preflight,
        "copied_files": copied,
        "skipped_unchanged_files": skipped,
    }
    manifest["manifest_hash"] = manifest_hash(manifest)
    if not dry_run:
        write_json(latest_root / "tape_backup_manifest.json", manifest)
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        write_json(backup_root / "manifests" / f"tape_backup_manifest_{stamp}.json", manifest)
    return manifest


def latest_manifest_path(backup_root=DEFAULT_BACKUP_ROOT):
    return Path(backup_root) / LATEST_DIR / "tape_backup_manifest.json"


def load_backup_manifest(backup_root=DEFAULT_BACKUP_ROOT):
    path = latest_manifest_path(backup_root)
    if not path.exists():
        return None, path
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload, path


def _cleanup_operator_review_ok(review):
    review = review or {}
    if review.get("approved") is not True:
        return False, "operator_review.approved must be true"
    if not review.get("approved_by"):
        return False, "operator_review.approved_by is required"
    if not review.get("approved_at_utc"):
        return False, "operator_review.approved_at_utc is required"
    if not review.get("note"):
        return False, "operator_review.note is required"
    return True, "ok"


def _unmanifested_cleanup_plan_hash_payload(payload):
    return {
        "schema_version": payload.get("schema_version"),
        "backup_root": payload.get("backup_root"),
        "latest_root": payload.get("latest_root"),
        "source_root": payload.get("source_root"),
        "manifest_hash": payload.get("manifest_hash"),
        "manifest_valid": payload.get("manifest_valid"),
        "restore_drill_sla_status": payload.get("restore_drill_sla_status"),
        "files": [
            {
                "rel_path": row.get("rel_path"),
                "size": row.get("size"),
                "backup_sha256": row.get("backup_sha256"),
                "source_sha256": row.get("source_sha256"),
                "source_path": row.get("source_path"),
                "source_exists": row.get("source_exists"),
                "source_same_hash": row.get("source_same_hash"),
                "status": row.get("status"),
                "reason": row.get("reason"),
            }
            for row in payload.get("files") or []
        ],
    }


def unmanifested_cleanup_plan_hash(payload):
    encoded = json.dumps(
        _unmanifested_cleanup_plan_hash_payload(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cleanup_gate_row(check, passed, detail, **extra):
    row = {
        "check": check,
        "status": "PASS" if passed else "BLOCK",
        "detail": detail,
    }
    row.update(extra)
    return row


def _is_path_under(path, root):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def unmanifested_backup_cleanup_plan(
    backup_root=DEFAULT_BACKUP_ROOT,
    source_root=REPO_ROOT,
    *,
    max_restore_age_hours=168,
    local_cache_retention_days=DEFAULT_LOCAL_MIRROR_CACHE_RETENTION_DAYS,
):
    backup_root = Path(backup_root)
    source_root = Path(source_root)
    latest_root = backup_root / LATEST_DIR
    manifest, manifest_path = load_backup_manifest(backup_root)
    valid, detail = validate_manifest(manifest)
    restore = load_restore_drill_status(backup_root)
    restore_status, restore_detail = restore_drill_sla_status(
        restore,
        manifest_hash_value=manifest.get("manifest_hash") if manifest else None,
        max_restore_age_hours=max_restore_age_hours,
    )
    base = {
        "schema_version": UNMANIFESTED_CLEANUP_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "dry_run": True,
        "mirror_role": "local_restore_cache",
        "local_cache_retention_days": int(local_cache_retention_days or 0),
        "backup_root": str(backup_root),
        "latest_root": str(latest_root),
        "manifest_path": str(manifest_path),
        "source_root": str(source_root),
        "manifest_hash": manifest.get("manifest_hash") if manifest else None,
        "manifest_valid": valid,
        "manifest_detail": detail,
        "restore_drill": {
            "status": restore.get("status"),
            "path": restore.get("path"),
            "manifest_hash": restore.get("manifest_hash"),
            "generated_at_utc": restore.get("generated_at_utc"),
        },
        "restore_drill_sla_status": restore_status,
        "restore_drill_sla_detail": restore_detail,
        "max_restore_age_hours": max_restore_age_hours,
        "summary": {
            "unmanifested_files": 0,
            "unmanifested_bytes": 0,
            "candidate_files": 0,
            "candidate_bytes": 0,
            "blocked_files": 0,
            "blocked_bytes": 0,
            "source_same_size_files": 0,
            "source_same_hash_files": 0,
        },
        "files": [],
    }
    if not latest_root.exists():
        payload = {
            **base,
            "status": "SKIPPED",
            "reason": "latest backup root does not exist",
        }
        payload["apply_gates"] = [
            _cleanup_gate_row("latest_root_exists", False, "latest backup root does not exist"),
        ]
        payload["apply_permission"] = False
        payload["plan_hash"] = unmanifested_cleanup_plan_hash(payload)
        return payload
    if not manifest:
        payload = {
            **base,
            "status": "SKIPPED",
            "reason": "latest backup manifest does not exist",
        }
        payload["apply_gates"] = [
            _cleanup_gate_row("manifest_valid", False, "latest backup manifest does not exist"),
            _cleanup_gate_row("restore_drill_current", False, restore_detail),
        ]
        payload["apply_permission"] = False
        payload["plan_hash"] = unmanifested_cleanup_plan_hash(payload)
        return payload
    manifest_paths = set(_manifest_entry_map(manifest))
    rows = []
    for path in sorted(latest_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(latest_root).as_posix()
        if rel in LATEST_CONTROL_FILES or rel in manifest_paths:
            continue
        size = path.stat().st_size
        source_path = source_root / rel
        source_exists = source_path.exists()
        source_size = source_path.stat().st_size if source_exists else None
        source_same_size = bool(source_exists and int(source_size or 0) == size)
        backup_sha = sha256_file(path)
        source_sha = sha256_file(source_path) if source_same_size else None
        source_same_hash = bool(source_sha and backup_sha == source_sha)
        if source_same_hash:
            status = "candidate"
            reason = "unmanifested mirror duplicate; source counterpart exists and hash matches"
        elif not source_exists:
            status = "blocked_missing_source"
            reason = "unmanifested backup file has no source counterpart"
        elif not source_same_size:
            status = "blocked_source_size_mismatch"
            reason = "source counterpart exists but size differs from mirror copy"
        else:
            status = "blocked_source_hash_mismatch"
            reason = "source counterpart exists but SHA-256 differs from mirror copy"
        storage_meta = classification_payload(f"data/tape_backups/latest/{rel}")
        rows.append({
            "path": str(path),
            "rel_path": rel,
            **storage_meta,
            "size": size,
            "latest_manifest_hash": manifest.get("manifest_hash"),
            "backup_sha256": backup_sha,
            "source_path": str(source_path),
            "source_exists": source_exists,
            "source_size": source_size,
            "source_same_size": source_same_size,
            "source_sha256": source_sha,
            "source_same_hash": source_same_hash,
            "verified_duplicate": source_same_hash,
            "status": status,
            "reason": reason,
        })
    candidate_rows = [row for row in rows if row.get("status") == "candidate"]
    blocked_rows = [row for row in rows if row.get("status") != "candidate"]
    status = "WARN" if candidate_rows else "PASS"
    if blocked_rows:
        status = "WARN"
    gates = [
        _cleanup_gate_row("manifest_valid", valid, detail),
        _cleanup_gate_row("restore_drill_current", restore_status == "OK", restore_detail),
        _cleanup_gate_row(
            "blocked_rows",
            not blocked_rows,
            "all unmanifested mirror files have duplicate-source evidence"
            if not blocked_rows else "one or more unmanifested mirror files lack duplicate-source evidence",
            blocked_files=len(blocked_rows),
            blocked_bytes=sum(int(row.get("size") or 0) for row in blocked_rows),
        ),
    ]
    payload = {
        **base,
        "status": status,
        "reason": "ok" if rows else "no unmanifested backup files",
        "summary": {
            "unmanifested_files": len(rows),
            "unmanifested_bytes": sum(int(row.get("size") or 0) for row in rows),
            "candidate_files": len(candidate_rows),
            "candidate_bytes": sum(int(row.get("size") or 0) for row in candidate_rows),
            "blocked_files": len(blocked_rows),
            "blocked_bytes": sum(int(row.get("size") or 0) for row in blocked_rows),
            "source_same_size_files": sum(1 for row in candidate_rows if row.get("source_same_size")),
            "source_same_hash_files": sum(1 for row in candidate_rows if row.get("source_same_hash")),
        },
        "apply_gates": gates,
        "apply_permission": bool(rows) and all(row.get("status") == "PASS" for row in gates),
        "files": rows,
    }
    payload["plan_hash"] = unmanifested_cleanup_plan_hash(payload)
    return payload


def apply_unmanifested_backup_cleanup(
    payload,
    *,
    operator_review=None,
    max_age_hours=26,
    max_restore_age_hours=168,
):
    latest_root = Path(payload.get("latest_root") or Path(payload.get("backup_root") or DEFAULT_BACKUP_ROOT) / LATEST_DIR)
    backup_root = Path(payload.get("backup_root") or latest_root.parent)
    source_root = Path(payload.get("source_root") or REPO_ROOT)
    review = operator_review or payload.get("operator_review") or {}
    review_ok, review_detail = _cleanup_operator_review_ok(review)
    manifest, manifest_path = load_backup_manifest(backup_root)
    manifest_valid, manifest_detail = validate_manifest(manifest)
    manifest_hash_value = manifest.get("manifest_hash") if manifest else None
    manifest_paths = set(_manifest_entry_map(manifest)) if manifest else set()
    restore = load_restore_drill_status(backup_root)
    restore_status, restore_detail = restore_drill_sla_status(
        restore,
        manifest_hash_value=manifest_hash_value,
        max_restore_age_hours=max_restore_age_hours,
    )
    current_status = backup_status(
        backup_root=backup_root,
        max_age_hours=max_age_hours,
        max_restore_age_hours=max_restore_age_hours,
        source_root=source_root,
    )
    computed_plan_hash = unmanifested_cleanup_plan_hash(payload)
    plan_hash = payload.get("plan_hash") or computed_plan_hash
    plan_hash_valid = not payload.get("plan_hash") or payload.get("plan_hash") == computed_plan_hash
    plan_hash_detail = (
        "reviewed dry-run plan has no embedded hash; computed hash will be recorded"
        if not payload.get("plan_hash")
        else "reviewed dry-run plan hash matches plan contents"
        if payload.get("plan_hash") == computed_plan_hash
        else "reviewed dry-run plan hash does not match plan contents"
    )
    gates = [
        _cleanup_gate_row("dry_run_plan", payload.get("dry_run") is True, "reviewed dry-run cleanup plan is required"),
        _cleanup_gate_row(
            "dry_run_plan_hash",
            plan_hash_valid,
            plan_hash_detail,
            plan_hash=payload.get("plan_hash"),
            computed_plan_hash=computed_plan_hash,
        ),
        _cleanup_gate_row("operator_review", review_ok, review_detail),
        _cleanup_gate_row("manifest_valid", manifest_valid, manifest_detail),
        _cleanup_gate_row(
            "manifest_hash_matches_plan",
            bool(manifest_hash_value and manifest_hash_value == payload.get("manifest_hash")),
            "latest manifest hash matches reviewed dry-run plan"
            if manifest_hash_value == payload.get("manifest_hash")
            else "latest manifest hash does not match reviewed dry-run plan",
            current_manifest_hash=manifest_hash_value,
            plan_manifest_hash=payload.get("manifest_hash"),
        ),
        _cleanup_gate_row("restore_drill_current", restore_status == "OK", restore_detail),
        _cleanup_gate_row(
            "backup_status_ok",
            current_status.get("status") == "OK",
            f"backup status is {current_status.get('status') or 'MISSING'}",
            missing_critical_files=current_status.get("missing_critical_files"),
            missing_critical_bytes=current_status.get("missing_critical_bytes"),
        ),
    ]
    rows = payload.get("files") or []
    blocked_rows = [row for row in rows if row.get("status") != "candidate"]
    gates.append(_cleanup_gate_row(
        "blocked_rows",
        not blocked_rows,
        "all dry-run rows are verified duplicate candidates"
        if not blocked_rows else "dry-run includes rows without duplicate-source evidence",
        blocked_files=len(blocked_rows),
    ))
    candidate_rows = [row for row in rows if row.get("status") == "candidate"]
    validation_actions = []
    for row in candidate_rows:
        action = {
            "path": row.get("path"),
            "rel_path": row.get("rel_path"),
            "size": int(row.get("size") or 0),
            "source_exists": bool(row.get("source_exists")),
            "source_same_size": bool(row.get("source_same_size")),
            "source_same_hash": bool(row.get("source_same_hash")),
        }
        path = Path(row.get("path") or "")
        rel = str(row.get("rel_path") or "")
        rel_path = Path(rel)
        source_path = source_root / rel
        if not rel or rel_path.is_absolute() or ".." in rel_path.parts:
            action["status"] = "blocked"
            action["reason"] = "relative path is invalid"
        elif not _is_path_under(path, latest_root):
            action["status"] = "blocked"
            action["reason"] = "path escapes latest backup root"
        elif not _is_path_under(source_path, source_root):
            action["status"] = "blocked"
            action["reason"] = "source counterpart path escapes source root"
        elif not path.exists():
            action["status"] = "blocked"
            action["reason"] = "already missing"
        elif rel in LATEST_CONTROL_FILES or rel in manifest_paths:
            action["status"] = "blocked"
            action["reason"] = "path is now manifest-listed or reserved"
        elif not source_path.exists():
            action["status"] = "blocked"
            action["reason"] = "source counterpart is missing"
        elif int(path.stat().st_size) != int(row.get("size") or 0):
            action["status"] = "blocked"
            action["reason"] = "mirror file size changed after dry-run"
        elif int(source_path.stat().st_size) != int(path.stat().st_size):
            action["status"] = "blocked"
            action["reason"] = "source counterpart size differs"
        else:
            backup_sha = sha256_file(path)
            source_sha = sha256_file(source_path)
            action["backup_sha256"] = backup_sha
            action["source_sha256"] = source_sha
            if row.get("backup_sha256") and row.get("backup_sha256") != backup_sha:
                action["status"] = "blocked"
                action["reason"] = "mirror checksum changed after dry-run"
            elif row.get("source_sha256") and row.get("source_sha256") != source_sha:
                action["status"] = "blocked"
                action["reason"] = "source checksum changed after dry-run"
            elif backup_sha != source_sha:
                action["status"] = "blocked"
                action["reason"] = "source counterpart hash differs"
            else:
                action["status"] = "ready"
                action["reason"] = "verified duplicate-source mirror file"
        validation_actions.append(action)
    gates.append(_cleanup_gate_row(
        "candidate_revalidation",
        all(row.get("status") == "ready" for row in validation_actions),
        "all cleanup candidates revalidated"
        if all(row.get("status") == "ready" for row in validation_actions)
        else "one or more cleanup candidates failed revalidation",
    ))
    if not candidate_rows:
        gates.append(_cleanup_gate_row("candidate_rows", False, "no cleanup candidates in reviewed dry-run plan"))
    gate_pass = all(row.get("status") == "PASS" for row in gates)
    actions = []
    if gate_pass:
        for action in validation_actions:
            path = Path(action.get("path") or "")
            path.unlink()
            actions.append({**action, "status": "deleted", "reason": "deleted after guarded apply validation"})
    else:
        actions = [
            {
                **action,
                "status": "skipped" if action.get("status") == "ready" else "blocked",
                "reason": action.get("reason") if action.get("status") != "ready" else "apply gate blocked before deletion",
            }
            for action in validation_actions
        ]
        actions.extend({
            "path": row.get("path"),
            "rel_path": row.get("rel_path"),
            "size": int(row.get("size") or 0),
            "status": "skipped",
            "reason": row.get("reason") or "not a verified duplicate candidate",
            "source_exists": bool(row.get("source_exists")),
            "source_same_size": bool(row.get("source_same_size")),
            "source_same_hash": bool(row.get("source_same_hash")),
        } for row in blocked_rows)
    post_status = backup_status(
        backup_root=backup_root,
        max_age_hours=max_age_hours,
        max_restore_age_hours=max_restore_age_hours,
        source_root=source_root,
    )
    return {
        "enabled": True,
        "schema_version": UNMANIFESTED_CLEANUP_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if gate_pass else "BLOCK",
        "dry_run_plan_hash": plan_hash,
        "manifest_path": str(manifest_path),
        "manifest_hash": manifest_hash_value,
        "restore_drill_evidence": {
            "status": restore.get("status"),
            "path": restore.get("path"),
            "manifest_hash": restore.get("manifest_hash"),
            "generated_at_utc": restore.get("generated_at_utc"),
            "sla_status": restore_status,
            "sla_detail": restore_detail,
        },
        "operator_review": review,
        "gates": gates,
        "actions": actions,
        "post_cleanup_backup_status": {
            "status": post_status.get("status"),
            "manifest_hash": post_status.get("manifest_hash"),
            "restore_drill_sla_status": post_status.get("restore_drill_sla_status"),
            "missing_critical_files": post_status.get("missing_critical_files"),
            "missing_critical_bytes": post_status.get("missing_critical_bytes"),
        },
        "summary": {
            "deleted_files": sum(1 for row in actions if row.get("status") == "deleted"),
            "deleted_bytes": sum(int(row.get("size") or 0) for row in actions if row.get("status") == "deleted"),
            "skipped_files": sum(1 for row in actions if row.get("status") == "skipped"),
            "blocked_files": sum(1 for row in actions if row.get("status") == "blocked"),
        },
    }


def render_unmanifested_cleanup_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Tape Backup Unmanifested Cleanup",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: **{payload.get('status')}**",
        f"Backup root: `{payload.get('backup_root')}`",
        f"Latest root: `{payload.get('latest_root')}`",
        f"Manifest: `{payload.get('manifest_path')}`",
        f"Manifest hash: `{payload.get('manifest_hash') or '-'}`",
        f"Manifest valid: `{payload.get('manifest_valid')}` ({payload.get('manifest_detail') or '-'})",
        f"Restore drill SLA: **{payload.get('restore_drill_sla_status') or '-'}**",
        f"Apply permission: `{payload.get('apply_permission')}`",
        f"Dry-run plan hash: `{payload.get('plan_hash') or '-'}`",
        f"Mirror role: `{payload.get('mirror_role') or '-'}`",
        f"Local cache retention days: `{payload.get('local_cache_retention_days')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Unmanifested files", summary.get("unmanifested_files")],
            ["Unmanifested MiB", round(int(summary.get("unmanifested_bytes") or 0) / (1024 * 1024), 1)],
            ["Candidate files", summary.get("candidate_files")],
            ["Candidate MiB", round(int(summary.get("candidate_bytes") or 0) / (1024 * 1024), 1)],
            ["Blocked files", summary.get("blocked_files")],
            ["Source same-size files", summary.get("source_same_size_files")],
            ["Source same-hash files", summary.get("source_same_hash_files")],
        ],
    )
    gates = payload.get("apply_gates") or []
    if gates:
        lines += ["", "## Apply Gates", ""]
        lines += markdown_table(
            ["Check", "Status", "Detail"],
            [
                [row.get("check"), row.get("status"), row.get("detail")]
                for row in gates
            ],
        )
    candidates = [row for row in payload.get("files") or [] if row.get("status") == "candidate"]
    candidates.sort(key=lambda row: int(row.get("size") or 0), reverse=True)
    if candidates:
        lines += ["", "## Largest Candidates", ""]
        lines += markdown_table(
            ["Path", "Storage Class", "Delete Gate", "MiB", "Source Exists", "Same Size", "Same Hash"],
            [
                [
                    row.get("rel_path"),
                    row.get("storage_class"),
                    row.get("delete_gate"),
                    round(int(row.get("size") or 0) / (1024 * 1024), 1),
                    row.get("source_exists"),
                    row.get("source_same_size"),
                    row.get("source_same_hash"),
                ]
                for row in candidates[:50]
            ],
        )
    blocked = [row for row in payload.get("files") or [] if row.get("status") != "candidate"]
    blocked.sort(key=lambda row: int(row.get("size") or 0), reverse=True)
    if blocked:
        lines += ["", "## Blocked Rows", ""]
        lines += markdown_table(
            ["Path", "MiB", "Status", "Reason", "Source Exists", "Same Size", "Same Hash"],
            [
                [
                    row.get("rel_path"),
                    round(int(row.get("size") or 0) / (1024 * 1024), 1),
                    row.get("status"),
                    row.get("reason"),
                    row.get("source_exists"),
                    row.get("source_same_size"),
                    row.get("source_same_hash"),
                ]
                for row in blocked[:50]
            ],
        )
    apply_payload = payload.get("apply") or {}
    if apply_payload.get("enabled"):
        apply_summary = apply_payload.get("summary") or {}
        lines += ["", "## Apply", ""]
        lines += markdown_table(
            ["Metric", "Value"],
            [
                ["Status", apply_payload.get("status")],
                ["Deleted files", apply_summary.get("deleted_files")],
                ["Deleted MiB", round(int(apply_summary.get("deleted_bytes") or 0) / (1024 * 1024), 1)],
                ["Skipped files", apply_summary.get("skipped_files")],
                ["Blocked files", apply_summary.get("blocked_files")],
            ],
        )
        apply_gates = apply_payload.get("gates") or []
        if apply_gates:
            lines += ["", "### Apply Gate Details", ""]
            lines += markdown_table(
                ["Check", "Status", "Detail"],
                [
                    [row.get("check"), row.get("status"), row.get("detail")]
                    for row in apply_gates
                ],
            )
    lines.append("")
    return "\n".join(lines)


def write_unmanifested_cleanup_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_unmanifested_cleanup_report(payload), encoding="utf-8")
    return path


def validate_manifest(manifest):
    if not manifest:
        return False, "missing manifest"
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return False, f"unexpected schema {manifest.get('schema_version')}"
    expected = manifest_hash(manifest)
    if manifest.get("manifest_hash") != expected:
        return False, f"manifest hash mismatch: expected {expected}, found {manifest.get('manifest_hash')}"
    return True, "ok"


def verify_backup_files(manifest, backup_root=DEFAULT_BACKUP_ROOT, limit=None):
    latest_root = Path(backup_root) / LATEST_DIR
    failures = []
    checked = 0
    for entry in manifest.get("files") or []:
        if limit is not None and checked >= int(limit):
            break
        path = latest_root / entry["path"]
        checked += 1
        if not path.exists():
            failures.append({"path": entry["path"], "reason": "missing"})
            continue
        sha = sha256_file(path)
        if sha != entry.get("sha256"):
            failures.append({
                "path": entry["path"],
                "reason": "sha256_mismatch",
                "expected": entry.get("sha256"),
                "actual": sha,
            })
    return {"checked_files": checked, "failures": failures}


def _parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def load_restore_drill_status(backup_root=DEFAULT_BACKUP_ROOT):
    path = Path(backup_root) / LATEST_DIR / "tape_restore_drill.json"
    if not path.exists():
        return {"exists": False, "path": str(path), "status": "MISSING"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"exists": True, "path": str(path), "status": "UNREADABLE", "error": str(exc)}
    payload["exists"] = True
    payload["path"] = str(path)
    generated = _parse_time(payload.get("generated_at_utc"))
    if generated:
        payload["age_hours"] = round((utc_now() - generated).total_seconds() / 3600.0, 3)
    return payload


def restore_drill_sla_status(restore, manifest_hash_value=None, max_restore_age_hours=168):
    restore = restore or {}
    if not restore.get("exists"):
        return "RESTORE_DRILL_MISSING", "no restore drill evidence recorded"
    if restore.get("status") in {"UNREADABLE", "FAIL"}:
        return "RESTORE_DRILL_FAIL", restore.get("error") or restore.get("manifest_detail") or "restore drill failed"
    if restore.get("status") != "PASS":
        return "RESTORE_DRILL_FAIL", f"unexpected restore drill status {restore.get('status')}"
    if manifest_hash_value and restore.get("manifest_hash") != manifest_hash_value:
        return "RESTORE_DRILL_STALE", "restore drill manifest hash does not match latest backup manifest"
    age_hours = restore.get("age_hours")
    if age_hours is not None and float(age_hours) > float(max_restore_age_hours):
        return "RESTORE_DRILL_STALE", f"restore drill age {age_hours}h exceeds SLA {max_restore_age_hours}h"
    return "OK", "restore drill evidence is current"


def backup_status(
    backup_root=DEFAULT_BACKUP_ROOT,
    max_age_hours=26,
    verify_checksums=False,
    max_restore_age_hours=168,
    source_root=None,
):
    manifest, path = load_backup_manifest(backup_root)
    if manifest is None:
        return {
            "status": "MISSING",
            "backup_root": str(backup_root),
            "manifest_path": str(path),
            "missing_critical_classes": [rule.name for rule in RETENTION_RULES if rule.critical],
            "checksum_failures": [],
            "last_restore_drill": load_restore_drill_status(backup_root),
        }
    valid, detail = validate_manifest(manifest)
    generated = _parse_time(manifest.get("generated_at_utc"))
    age_hours = None
    if generated:
        age_hours = (utc_now() - generated).total_seconds() / 3600.0
    verify = verify_backup_files(manifest, backup_root) if verify_checksums else {"checked_files": 0, "failures": []}
    missing = (manifest.get("summary") or {}).get("missing_critical_classes") or []
    coverage_source_root = Path(source_root or manifest.get("source_root") or REPO_ROOT)
    coverage = local_manifest_coverage_audit(coverage_source_root, manifest)
    capacity = coverage_capacity_preflight(coverage, backup_root)
    status = "OK"
    if not valid:
        status = "CORRUPT_MANIFEST"
    elif verify["failures"]:
        status = "CHECKSUM_FAIL"
    elif missing:
        status = "MISSING_CRITICAL_CLASS"
    elif coverage.get("missing_critical_files") and capacity.get("status") != "PASS":
        status = "INSUFFICIENT_BACKUP_CAPACITY"
    elif coverage.get("missing_critical_files"):
        status = "MISSING_CRITICAL_FILES"
    elif age_hours is not None and age_hours > float(max_age_hours):
        status = "STALE"
    restore = load_restore_drill_status(backup_root)
    restore_status, restore_detail = restore_drill_sla_status(
        restore,
        manifest_hash_value=manifest.get("manifest_hash"),
        max_restore_age_hours=max_restore_age_hours,
    )
    if status == "OK" and restore_status != "OK":
        status = restore_status
    return {
        "status": status,
        "backup_root": str(backup_root),
        "manifest_path": str(path),
        "manifest_hash": manifest.get("manifest_hash"),
        "manifest_valid": valid,
        "manifest_detail": detail,
        "generated_at_utc": manifest.get("generated_at_utc"),
        "age_hours": round(age_hours, 3) if age_hours is not None else None,
        "max_age_hours": max_age_hours,
        "max_restore_age_hours": max_restore_age_hours,
        "file_count": (manifest.get("summary") or {}).get("file_count"),
        "total_bytes": (manifest.get("summary") or {}).get("total_bytes"),
        "class_summaries": manifest.get("class_summaries") or {},
        "storage_class_summaries": manifest.get("storage_class_summaries") or {},
        "local_manifest_coverage": coverage,
        "capacity_preflight": capacity,
        "clob_artifact_coverage": coverage.get("clob_artifacts") or {},
        "missing_critical_classes": missing,
        "missing_critical_files": coverage.get("missing_critical_files", 0),
        "missing_critical_bytes": coverage.get("missing_critical_bytes", 0),
        "missing_critical_file_samples": coverage.get("missing_critical_samples") or [],
        "checksum_checked_files": verify.get("checked_files"),
        "checksum_failures": verify.get("failures") or [],
        "last_restore_drill": restore,
        "restore_drill_sla_status": restore_status,
        "restore_drill_sla_detail": restore_detail,
    }


def backup_alerts(status):
    state = (status or {}).get("status")
    alerts = []
    if state == "OK":
        restore = status.get("last_restore_drill") or {}
        if not restore.get("exists"):
            alerts.append({
                "severity": "warning",
                "market_id": "fleet",
                "category": "tape_backup",
                "message": "no successful tape restore drill recorded",
                "detail": {"backup_root": status.get("backup_root")},
            })
        return alerts
    severity = "critical" if state in {
        "MISSING",
        "CORRUPT_MANIFEST",
        "CHECKSUM_FAIL",
        "MISSING_CRITICAL_CLASS",
        "MISSING_CRITICAL_FILES",
        "INSUFFICIENT_BACKUP_CAPACITY",
        "RESTORE_DRILL_MISSING",
        "RESTORE_DRILL_FAIL",
        "RESTORE_DRILL_STALE",
    } else "warning"
    alerts.append({
        "severity": severity,
        "market_id": "fleet",
        "category": "tape_backup",
        "message": f"tape backup status is {state}",
        "detail": {
            "backup_root": (status or {}).get("backup_root"),
            "missing_critical_classes": (status or {}).get("missing_critical_classes") or [],
            "missing_critical_files": (status or {}).get("missing_critical_files") or 0,
            "missing_critical_file_samples": (status or {}).get("missing_critical_file_samples") or [],
            "checksum_failures": (status or {}).get("checksum_failures") or [],
            "age_hours": (status or {}).get("age_hours"),
        },
    })
    return alerts


def _schema_check(path):
    if path.suffix.lower() != ".json":
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"path": relative_to_repo(path), "status": "invalid_json", "error": str(exc)}
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if not version:
        return None
    if version not in SCHEMAS_BY_VERSION:
        return {"path": relative_to_repo(path), "status": "unregistered_schema", "schema_version": version}
    return {"path": relative_to_repo(path), "status": "ok", "schema_version": version}


def write_restore_reports(restore_root, report_dir, manifest):
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    class_rows = []
    summaries = class_summaries(manifest.get("files") or [])
    for name, row in sorted(summaries.items()):
        class_rows.append(f"| {name} | {row.get('file_count')} | {row.get('total_bytes')} |")
    fleet_report = report_dir / "restored_fleet_inputs_report.md"
    promotion_report = report_dir / "restored_promotion_inputs_report.md"
    mm_report = report_dir / "restored_market_making_inputs_report.md"
    fleet_report.write_text(
        "\n".join([
            "# Restored Fleet Inputs",
            "",
            f"Restore root: `{restore_root}`",
            "",
            "| Tape Class | Files | Bytes |",
            "| :--- | :--- | :--- |",
            *class_rows,
            "",
        ]),
        encoding="utf-8",
    )
    promotion_files = [
        row["path"] for row in manifest.get("files") or []
        if "promotion_corpora" in (row.get("classes") or [])
    ]
    promotion_report.write_text(
        "\n".join([
            "# Restored Promotion Inputs",
            "",
            f"Promotion corpus/status files: `{len(promotion_files)}`",
            "",
            *[f"- `{path}`" for path in promotion_files[:200]],
            "",
        ]),
        encoding="utf-8",
    )
    mm_files = [
        row["path"] for row in manifest.get("files") or []
        if set(row.get("classes") or []) & {"market_making_runs", "order_lifecycle_and_risk"}
    ]
    mm_report.write_text(
        "\n".join([
            "# Restored Market-Making Inputs",
            "",
            f"Market-making files: `{len(mm_files)}`",
            "",
            *[f"- `{path}`" for path in mm_files[:200]],
            "",
        ]),
        encoding="utf-8",
    )
    return [fleet_report, promotion_report, mm_report]


def clob_restore_evidence(restore_root, manifest):
    restore_root = Path(restore_root)
    files = manifest.get("files") or []
    manifest_paths = {row.get("path"): row for row in files if row.get("path")}
    rows = []
    missing_required = []
    for policy in CLOB_ARTIFACT_POLICIES:
        paths = [
            rel for rel in sorted(manifest_paths)
            if _clob_policy_for_path(rel) and any(
                candidate.name == policy.name
                for candidate in _clob_policy_for_path(rel)
            )
        ]
        restored = []
        restored_bytes = 0
        for rel in paths:
            path = restore_root / rel
            if not path.exists():
                continue
            restored.append(rel)
            restored_bytes += path.stat().st_size
        if policy.backup_required and paths and not restored:
            missing_required.append(policy.name)
        rows.append({
            "name": policy.name,
            "backup_required": policy.backup_required,
            "recoverability": policy.recoverability,
            "manifest_files": len(paths),
            "restored_files": len(restored),
            "restored_bytes": restored_bytes,
            "sample_paths": restored[:5],
        })
    return {
        "classes": rows,
        "summary": {
            "required_classes_with_manifest_files": sum(
                1 for row in rows
                if row.get("backup_required") and row.get("manifest_files")
            ),
            "required_classes_restored": sum(
                1 for row in rows
                if row.get("backup_required") and row.get("restored_files")
            ),
            "missing_required_restore_classes": missing_required,
        },
    }


def run_restore_drill(
    backup_root=DEFAULT_BACKUP_ROOT,
    restore_root=None,
    out=DEFAULT_RESTORE_OUT,
    report=DEFAULT_RESTORE_REPORT,
    keep_restore=False,
):
    backup_root = Path(backup_root)
    manifest, manifest_path = load_backup_manifest(backup_root)
    valid, detail = validate_manifest(manifest)
    temp_ctx = None
    if restore_root is None:
        temp_ctx = tempfile.TemporaryDirectory(prefix="weather-tape-restore-")
        restore_root = Path(temp_ctx.name)
    else:
        restore_root = Path(restore_root)
        restore_root.mkdir(parents=True, exist_ok=True)
    copied = 0
    failures = []
    schema_checks = []
    generated_reports = []
    clob_evidence = {"classes": [], "summary": {}}
    try:
        if manifest and valid:
            latest_root = backup_root / LATEST_DIR
            for entry in manifest.get("files") or []:
                src = latest_root / entry["path"]
                dst = restore_root / entry["path"]
                if not src.exists():
                    failures.append({"path": entry["path"], "reason": "missing_backup_file"})
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
                sha = sha256_file(dst)
                if sha != entry.get("sha256"):
                    failures.append({
                        "path": entry["path"],
                        "reason": "restored_sha256_mismatch",
                        "expected": entry.get("sha256"),
                        "actual": sha,
                    })
                check = _schema_check(dst)
                if check:
                    schema_checks.append(check)
            generated_reports = write_restore_reports(
                restore_root,
                restore_root / "restore_reports",
                manifest,
            )
            clob_evidence = clob_restore_evidence(restore_root, manifest)
        missing_critical = (manifest.get("summary") or {}).get("missing_critical_classes") if manifest else []
        schema_failures = [
            row for row in schema_checks
            if row.get("status") not in {"ok"}
        ]
        status = "PASS"
        if not valid or failures or missing_critical or schema_failures:
            status = "FAIL"
        payload = {
            "schema_version": RESTORE_DRILL_SCHEMA_VERSION,
            "generated_at_utc": utc_iso(),
            "status": status,
            "backup_root": str(backup_root),
            "manifest_path": str(manifest_path),
            "manifest_hash": manifest.get("manifest_hash") if manifest else None,
            "manifest_valid": valid,
            "manifest_detail": detail,
            "restore_root": str(restore_root),
            "keep_restore": bool(keep_restore),
            "files_restored": copied,
            "missing_critical_classes": missing_critical or [],
            "checksum_failures": failures,
            "schema_checks": schema_checks,
            "schema_failures": schema_failures,
            "clob_restore_evidence": clob_evidence,
            "generated_reports": [str(path) for path in generated_reports],
        }
        write_json(out, payload)
        write_restore_report(report, payload)
        if valid:
            latest_root = backup_root / LATEST_DIR
            latest_root.mkdir(parents=True, exist_ok=True)
            write_json(latest_root / "tape_restore_drill.json", payload)
        return payload
    finally:
        if temp_ctx is not None and not keep_restore:
            temp_ctx.cleanup()


def write_restore_report(path, payload):
    lines = [
        "# Tape Restore Drill",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Backup root: `{payload.get('backup_root')}`",
        f"Manifest: `{payload.get('manifest_path')}`",
        f"Files restored: `{payload.get('files_restored')}`",
        "",
        "## Failures",
        "",
    ]
    failures = (payload.get("checksum_failures") or []) + (payload.get("schema_failures") or [])
    if failures:
        lines.extend(f"- `{row.get('path')}`: {row.get('reason') or row.get('status')}" for row in failures)
    else:
        lines.append("- none")
    lines += ["", "## Generated Reports", ""]
    lines.extend(f"- `{path}`" for path in payload.get("generated_reports") or [])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_backup_job(
    *,
    source_root=REPO_ROOT,
    backup_root=DEFAULT_BACKUP_ROOT,
    status_out=DEFAULT_STATUS_OUT,
    status_report=DEFAULT_REPORT_OUT,
    restore_out=DEFAULT_RESTORE_OUT,
    restore_report=DEFAULT_RESTORE_REPORT,
    restore_root=None,
    keep_restore=False,
    verify_checksums=True,
    max_age_hours=26,
    max_restore_age_hours=168,
    capacity_margin_bytes=DEFAULT_CAPACITY_MARGIN_BYTES,
):
    try:
        manifest = export_backup(
            source_root=source_root,
            backup_root=backup_root,
            capacity_margin_bytes=capacity_margin_bytes,
        )
    except TapeBackupCapacityError as exc:
        status = {
            "status": "INSUFFICIENT_BACKUP_CAPACITY",
            "backup_root": str(backup_root),
            "generated_at_utc": utc_iso(),
            "manifest_path": str(latest_manifest_path(backup_root)),
            "manifest_valid": False,
            "manifest_detail": "backup capacity preflight failed before export",
            "capacity_preflight": exc.preflight,
            "missing_critical_classes": [],
            "missing_critical_files": None,
            "missing_critical_bytes": None,
            "checksum_checked_files": 0,
            "checksum_failures": [],
            "last_restore_drill": load_restore_drill_status(backup_root),
            "restore_drill_sla_status": "-",
            "restore_drill_sla_detail": "restore drill skipped because export did not run",
        }
        write_json(status_out, status)
        write_status_report(status_report, status)
        return {
            "schema_version": "tape_backup_job_v0.1",
            "generated_at_utc": utc_iso(),
            "backup_root": str(backup_root),
            "manifest_hash": None,
            "export": {
                "backup_root": str(backup_root),
                "capacity_preflight": exc.preflight,
                "copied_files": 0,
                "skipped_unchanged_files": exc.preflight.get("skipped_unchanged_files", 0),
            },
            "restore_drill": {
                "status": "SKIPPED",
                "reason": "backup capacity preflight failed before export",
            },
            "status": status,
            "status_out": str(status_out),
            "status_report": str(status_report),
            "restore_out": str(restore_out),
            "restore_report": str(restore_report),
        }
    restore = run_restore_drill(
        backup_root=backup_root,
        restore_root=restore_root,
        out=restore_out,
        report=restore_report,
        keep_restore=keep_restore,
    )
    status = backup_status(
        backup_root=backup_root,
        max_age_hours=max_age_hours,
        verify_checksums=verify_checksums,
        max_restore_age_hours=max_restore_age_hours,
        source_root=source_root,
    )
    write_json(status_out, status)
    write_status_report(status_report, status)
    return {
        "schema_version": "tape_backup_job_v0.1",
        "generated_at_utc": utc_iso(),
        "backup_root": str(backup_root),
        "manifest_hash": manifest.get("manifest_hash"),
        "export": manifest.get("backup") or {},
        "restore_drill": {
            "status": restore.get("status"),
            "files_restored": restore.get("files_restored"),
            "manifest_hash": restore.get("manifest_hash"),
        },
        "status": status,
        "status_out": str(status_out),
        "status_report": str(status_report),
        "restore_out": str(restore_out),
        "restore_report": str(restore_report),
    }


def write_status_report(path, payload):
    restore = payload.get("last_restore_drill") or {}
    lines = [
        "# Tape Backup Status",
        "",
        f"Generated: {utc_iso()}",
        f"Status: **{payload.get('status')}**",
        f"Backup root: `{payload.get('backup_root')}`",
        f"Manifest age hours: `{payload.get('age_hours')}`",
        f"Files: `{payload.get('file_count')}`",
        f"Restore drill SLA: **{payload.get('restore_drill_sla_status') or '-'}**",
        f"Restore drill detail: `{payload.get('restore_drill_sla_detail') or '-'}`",
        f"Last restore drill: `{restore.get('status') or '-'}`",
        f"Restore generated: `{restore.get('generated_at_utc') or '-'}`",
        "",
        "## Capacity Preflight",
        "",
    ]
    capacity = payload.get("capacity_preflight") or {}
    if capacity:
        lines.extend([
            f"Status: **{capacity.get('status')}**",
            f"Disk usage path: `{capacity.get('disk_usage_path')}`",
            f"Free bytes: `{capacity.get('free_bytes')}`",
            f"Required bytes: `{capacity.get('required_bytes')}`",
            f"Insufficient bytes: `{capacity.get('insufficient_bytes')}`",
            f"Planned copy files: `{capacity.get('planned_copy_files') or '-'}`",
            f"Planned copy bytes: `{capacity.get('planned_copy_bytes') or '-'}`",
            "",
        ])
        largest = capacity.get("largest_planned_copy") or {}
        if largest:
            lines.extend([
                "Largest planned copy:",
                f"- `{largest.get('path')}` ({largest.get('size')} bytes)",
                "",
            ])
    else:
        lines.extend(["- no capacity preflight recorded", ""])
    lines += [
        "## Missing Critical Classes",
        "",
    ]
    for name in payload.get("missing_critical_classes") or ["-"]:
        lines.append(f"- {name}")
    lines += ["", "## Class Summary", "", "| Class | Critical | Files | Bytes |", "| :--- | :--- | :--- | :--- |"]
    for name, row in sorted((payload.get("class_summaries") or {}).items()):
        lines.append(f"| {name} | {row.get('critical')} | {row.get('file_count')} | {row.get('total_bytes')} |")
    lines += [
        "",
        "## Storage Class Summary",
        "",
        "| Storage Class | Files | Bytes | Backup-Required Files | Backup-Required Bytes | Artifact Families |",
        "| :--- | ---: | ---: | ---: | ---: | :--- |",
    ]
    for name, row in sorted((payload.get("storage_class_summaries") or {}).items()):
        lines.append(
            f"| {name} | {row.get('file_count')} | {row.get('total_bytes')} | "
            f"{row.get('backup_required_files')} | {row.get('backup_required_bytes')} | "
            f"{', '.join((row.get('artifact_families') or [])[:8])} |"
        )
    coverage = payload.get("local_manifest_coverage") or {}
    lines += [
        "",
        "## Local Manifest Coverage",
        "",
        f"Source root: `{coverage.get('source_root') or '-'}`",
        f"Status: **{coverage.get('status') or '-'}**",
        f"Manifest cutoff UTC: `{coverage.get('manifest_cutoff_utc') or '-'}`",
        f"Missing critical files: `{coverage.get('missing_critical_files') or 0}`",
        f"Missing critical bytes: `{coverage.get('missing_critical_bytes') or 0}`",
        f"Post-manifest critical files: `{coverage.get('post_manifest_critical_files') or 0}`",
        f"Post-manifest critical bytes: `{coverage.get('post_manifest_critical_bytes') or 0}`",
        "",
    ]
    missing_samples = coverage.get("missing_critical_samples") or []
    if missing_samples:
        lines += ["Missing critical sample paths:"]
        lines.extend(
            f"- `{row.get('path')}` ({row.get('size')} bytes; {', '.join(row.get('critical_classes') or [])})"
            for row in missing_samples[:20]
        )
    else:
        lines.append("- no missing critical local files")
    post_manifest_samples = coverage.get("post_manifest_critical_samples") or []
    if post_manifest_samples:
        lines += ["", "Post-manifest critical sample paths:"]
        lines.extend(
            f"- `{row.get('path')}` ({row.get('size')} bytes; {', '.join(row.get('critical_classes') or [])})"
            for row in post_manifest_samples[:20]
        )
    clob = payload.get("clob_artifact_coverage") or {}
    lines += [
        "",
        "## CLOB Artifact Coverage",
        "",
        "| Artifact | Required | Local Files | Local Bytes | Backed-Up Files | Backed-Up Bytes | Missing Files | Missing Bytes | Excluded Bytes | Warnings |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in clob.get("classes") or []:
        lines.append(
            f"| {row.get('name')} | {row.get('backup_required')} | "
            f"{row.get('local_files')} | {row.get('local_bytes')} | "
            f"{row.get('backed_up_files')} | {row.get('backed_up_bytes')} | "
            f"{row.get('missing_files')} | {row.get('missing_bytes')} | "
            f"{row.get('excluded_bytes')} | {row.get('warning_count')} |"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cmd_policy(args):
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "policy": retention_policy_payload(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for rule in RETENTION_RULES:
            marker = "critical" if rule.critical else "supporting"
            print(f"{rule.name}: {marker}; {rule.recoverability}; {rule.retention}")
    return 0


def cmd_export(args):
    manifest = export_backup(
        source_root=args.source_root,
        backup_root=args.backup_root,
        dry_run=args.dry_run,
        capacity_margin_bytes=args.capacity_margin_bytes,
    )
    print(
        f"Tape backup manifest {manifest.get('manifest_hash')} "
        f"files={manifest['summary']['file_count']} "
        f"missing_critical={manifest['summary']['missing_critical_classes']}"
    )
    return 0


def cmd_status(args):
    payload = backup_status(
        backup_root=args.backup_root,
        max_age_hours=args.max_age_hours,
        verify_checksums=args.verify_checksums,
        max_restore_age_hours=args.max_restore_age_hours,
        source_root=args.source_root or None,
    )
    write_json(args.out, payload)
    write_status_report(args.report, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") == "OK" else 2


def cmd_prune_unmanifested(args):
    if args.apply and args.reviewed_plan:
        payload = json.loads(Path(args.reviewed_plan).read_text(encoding="utf-8"))
    else:
        payload = unmanifested_backup_cleanup_plan(
            backup_root=args.backup_root,
            source_root=args.source_root,
            max_restore_age_hours=args.max_restore_age_hours,
            local_cache_retention_days=args.local_cache_retention_days,
        )
    if args.apply:
        if not args.reviewed_plan:
            payload["apply"] = {
                "enabled": True,
                "schema_version": UNMANIFESTED_CLEANUP_SCHEMA_VERSION,
                "generated_at_utc": utc_iso(),
                "status": "BLOCK",
                "gates": [
                    _cleanup_gate_row(
                        "reviewed_plan",
                        False,
                        "--apply requires --reviewed-plan pointing to an inspected dry-run JSON",
                    )
                ],
                "actions": [],
                "summary": {"deleted_files": 0, "deleted_bytes": 0, "skipped_files": 0, "blocked_files": 0},
            }
        else:
            operator_review = {
                "approved": bool(args.operator_approve),
                "approved_by": args.operator_approved_by,
                "approved_at_utc": args.operator_approved_at_utc or utc_iso(),
                "note": args.operator_note,
            }
            payload["operator_review"] = operator_review
            payload["apply"] = apply_unmanifested_backup_cleanup(
                payload,
                operator_review=operator_review,
                max_age_hours=args.max_age_hours,
                max_restore_age_hours=args.max_restore_age_hours,
            )
    else:
        payload["apply"] = {"enabled": False}
    write_json(args.out, payload)
    write_unmanifested_cleanup_report(args.report, payload)
    apply_status = (payload.get("apply") or {}).get("status")
    print(
        f"Tape backup unmanifested cleanup: {payload.get('status')} "
        f"candidates={(payload.get('summary') or {}).get('candidate_files', 0)} "
        f"apply={apply_status or 'disabled'}"
    )
    print(f"JSON written to {args.out}")
    print(f"Report written to {args.report}")
    if args.apply and apply_status != "PASS":
        return 2
    return 0 if payload.get("status") in {"PASS", "WARN", "SKIPPED"} else 2


def cmd_restore_drill(args):
    payload = run_restore_drill(
        backup_root=args.backup_root,
        restore_root=args.restore_root or None,
        out=args.out,
        report=args.report,
        keep_restore=args.keep_restore,
    )
    print(f"Tape restore drill: {payload['status']}")
    print(f"Report written to {args.report}")
    return 0 if payload["status"] == "PASS" else 2


def cmd_run(args):
    payload = run_backup_job(
        source_root=args.source_root,
        backup_root=args.backup_root,
        status_out=args.status_out,
        status_report=args.status_report,
        restore_out=args.restore_out,
        restore_report=args.restore_report,
        restore_root=args.restore_root or None,
        keep_restore=args.keep_restore,
        verify_checksums=args.verify_checksums,
        max_age_hours=args.max_age_hours,
        max_restore_age_hours=args.max_restore_age_hours,
        capacity_margin_bytes=args.capacity_margin_bytes,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if (payload.get("status") or {}).get("status") == "OK" else 2


def cmd_dedup_status(args):
    payload = dedup_repository_status(
        backend=args.backend,
        repository=args.repository or None,
        executable=args.executable,
        password_file=args.password_file or None,
        restore_drill_path=args.restore_drill_path,
        max_age_hours=args.max_age_hours,
        max_restore_age_hours=args.max_restore_age_hours,
        require_restore_drill=not args.no_require_restore_drill,
        timeout_seconds=args.timeout_seconds,
    )
    write_json(args.out, payload)
    write_dedup_status_report(args.report, payload)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "OK" else 2


def cmd_dedup_backup(args):
    payload = run_dedup_backup(
        source_root=args.source_root,
        backend=args.backend,
        repository=args.repository or None,
        executable=args.executable,
        password_file=args.password_file or None,
        manifest_out=args.manifest_out or None,
        out=args.out,
        report=args.report,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "PASS" else 2


def cmd_dedup_restore_drill(args):
    payload = run_dedup_restore_drill(
        backend=args.backend,
        repository=args.repository or None,
        executable=args.executable,
        password_file=args.password_file or None,
        snapshot_id=args.snapshot_id or None,
        manifest_rel_path=args.manifest_rel_path,
        restore_root=args.restore_root or None,
        keep_restore=args.keep_restore,
        out=args.out,
        report=args.report,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "PASS" else 2


def cmd_dedup_run(args):
    payload = run_dedup_job(
        source_root=args.source_root,
        backend=args.backend,
        repository=args.repository or None,
        executable=args.executable,
        password_file=args.password_file or None,
        manifest_out=args.manifest_out or None,
        backup_out=args.backup_out,
        backup_report=args.backup_report,
        restore_out=args.restore_out,
        restore_report=args.restore_report,
        status_out=args.status_out,
        status_report=args.status_report,
        restore_root=args.restore_root or None,
        keep_restore=args.keep_restore,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0 if payload.get("status") == "PASS" else 2


def _add_dedup_common_args(parser):
    parser.add_argument("--backend", default=DEDUP_BACKEND_RESTIC, choices=(DEDUP_BACKEND_RESTIC,))
    parser.add_argument("--repository", default="")
    parser.add_argument("--executable", default=DEDUP_BACKEND_RESTIC)
    parser.add_argument("--password-file", default="")
    parser.add_argument("--timeout-seconds", type=int, default=3600)


def build_parser():
    parser = argparse.ArgumentParser(description="Backup and restore-drill irreplaceable weather tapes.")
    sub = parser.add_subparsers(dest="command", required=True)
    policy = sub.add_parser("policy")
    policy.add_argument("--json", action="store_true")
    policy.set_defaults(func=cmd_policy)

    export = sub.add_parser("export")
    export.add_argument("--source-root", default=str(REPO_ROOT))
    export.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    export.add_argument("--dry-run", action="store_true")
    export.add_argument("--capacity-margin-bytes", type=int, default=DEFAULT_CAPACITY_MARGIN_BYTES)
    export.set_defaults(func=cmd_export)

    status = sub.add_parser("status")
    status.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    status.add_argument("--source-root", default="")
    status.add_argument("--max-age-hours", type=float, default=26.0)
    status.add_argument("--max-restore-age-hours", type=float, default=168.0)
    status.add_argument("--verify-checksums", action="store_true")
    status.add_argument("--out", default=str(DEFAULT_STATUS_OUT))
    status.add_argument("--report", default=str(DEFAULT_REPORT_OUT))
    status.set_defaults(func=cmd_status)

    prune = sub.add_parser("prune-unmanifested")
    prune.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    prune.add_argument("--source-root", default=str(REPO_ROOT))
    prune.add_argument("--apply", action="store_true")
    prune.add_argument("--reviewed-plan", default="")
    prune.add_argument("--operator-approve", action="store_true")
    prune.add_argument("--operator-approved-by", default="")
    prune.add_argument("--operator-approved-at-utc", default="")
    prune.add_argument("--operator-note", default="")
    prune.add_argument("--max-age-hours", type=float, default=26.0)
    prune.add_argument("--max-restore-age-hours", type=float, default=168.0)
    prune.add_argument("--local-cache-retention-days", type=int, default=DEFAULT_LOCAL_MIRROR_CACHE_RETENTION_DAYS)
    prune.add_argument("--out", default=str(DEFAULT_UNMANIFESTED_CLEANUP_OUT))
    prune.add_argument("--report", default=str(DEFAULT_UNMANIFESTED_CLEANUP_REPORT))
    prune.set_defaults(func=cmd_prune_unmanifested)

    drill = sub.add_parser("restore-drill")
    drill.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    drill.add_argument("--restore-root", default="")
    drill.add_argument("--keep-restore", action="store_true")
    drill.add_argument("--out", default=str(DEFAULT_RESTORE_OUT))
    drill.add_argument("--report", default=str(DEFAULT_RESTORE_REPORT))
    drill.set_defaults(func=cmd_restore_drill)

    run = sub.add_parser("run")
    run.add_argument("--source-root", default=str(REPO_ROOT))
    run.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    run.add_argument("--status-out", default=str(DEFAULT_STATUS_OUT))
    run.add_argument("--status-report", default=str(DEFAULT_REPORT_OUT))
    run.add_argument("--restore-out", default=str(DEFAULT_RESTORE_OUT))
    run.add_argument("--restore-report", default=str(DEFAULT_RESTORE_REPORT))
    run.add_argument("--restore-root", default="")
    run.add_argument("--keep-restore", action="store_true")
    run.add_argument("--verify-checksums", action="store_true")
    run.add_argument("--max-age-hours", type=float, default=26.0)
    run.add_argument("--max-restore-age-hours", type=float, default=168.0)
    run.add_argument("--capacity-margin-bytes", type=int, default=DEFAULT_CAPACITY_MARGIN_BYTES)
    run.set_defaults(func=cmd_run)

    dedup_status = sub.add_parser("dedup-status")
    _add_dedup_common_args(dedup_status)
    dedup_status.add_argument("--restore-drill-path", default=str(DEFAULT_DEDUP_RESTORE_OUT))
    dedup_status.add_argument("--max-age-hours", type=float, default=26.0)
    dedup_status.add_argument("--max-restore-age-hours", type=float, default=168.0)
    dedup_status.add_argument("--no-require-restore-drill", action="store_true")
    dedup_status.add_argument("--out", default=str(DEFAULT_DEDUP_STATUS_OUT))
    dedup_status.add_argument("--report", default=str(DEFAULT_DEDUP_STATUS_REPORT))
    dedup_status.set_defaults(func=cmd_dedup_status)

    dedup_backup = sub.add_parser("dedup-backup")
    _add_dedup_common_args(dedup_backup)
    dedup_backup.add_argument("--source-root", default=str(REPO_ROOT))
    dedup_backup.add_argument("--manifest-out", default="")
    dedup_backup.add_argument("--out", default=str(DEFAULT_DEDUP_BACKUP_OUT))
    dedup_backup.add_argument("--report", default=str(DEFAULT_DEDUP_BACKUP_REPORT))
    dedup_backup.set_defaults(func=cmd_dedup_backup)

    dedup_drill = sub.add_parser("dedup-restore-drill")
    _add_dedup_common_args(dedup_drill)
    dedup_drill.add_argument("--snapshot-id", default="")
    dedup_drill.add_argument("--manifest-rel-path", default=f"data/backtest/{DEFAULT_DEDUP_MANIFEST_NAME}")
    dedup_drill.add_argument("--restore-root", default="")
    dedup_drill.add_argument("--keep-restore", action="store_true")
    dedup_drill.add_argument("--out", default=str(DEFAULT_DEDUP_RESTORE_OUT))
    dedup_drill.add_argument("--report", default=str(DEFAULT_DEDUP_RESTORE_REPORT))
    dedup_drill.set_defaults(func=cmd_dedup_restore_drill)

    dedup_run = sub.add_parser("dedup-run")
    _add_dedup_common_args(dedup_run)
    dedup_run.add_argument("--source-root", default=str(REPO_ROOT))
    dedup_run.add_argument("--manifest-out", default="")
    dedup_run.add_argument("--backup-out", default=str(DEFAULT_DEDUP_BACKUP_OUT))
    dedup_run.add_argument("--backup-report", default=str(DEFAULT_DEDUP_BACKUP_REPORT))
    dedup_run.add_argument("--restore-out", default=str(DEFAULT_DEDUP_RESTORE_OUT))
    dedup_run.add_argument("--restore-report", default=str(DEFAULT_DEDUP_RESTORE_REPORT))
    dedup_run.add_argument("--status-out", default=str(DEFAULT_DEDUP_STATUS_OUT))
    dedup_run.add_argument("--status-report", default=str(DEFAULT_DEDUP_STATUS_REPORT))
    dedup_run.add_argument("--restore-root", default="")
    dedup_run.add_argument("--keep-restore", action="store_true")
    dedup_run.set_defaults(func=cmd_dedup_run)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
