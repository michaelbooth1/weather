"""Manifest, policy, status, and capacity helpers for tape backup."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
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
DEFAULT_UNMANIFESTED_DURABLE_PROOF_OUT = data_path() / "backtest" / "tape_backup_unmanifested_durable_restore_proof.json"
DEFAULT_UNMANIFESTED_DURABLE_PROOF_REPORT = data_path() / "backtest" / "tape_backup_unmanifested_durable_restore_proof_report.md"
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
UNMANIFESTED_MIRROR_PROOF_RESTIC_TAG = "weather-tape-unmanifested-mirror-proof"


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


def build_sha_cache(prior_manifest):
    """Map rel_path -> (size, mtime_utc, sha256) from a prior manifest so an
    unchanged source file (same size + mtime) can reuse its recorded sha256
    instead of being re-hashed. This is the standard rsync-style quick check and
    is what lets the backup of ~200k files complete in seconds instead of
    re-hashing everything every run."""
    cache = {}
    for entry in (prior_manifest or {}).get("files") or []:
        path = entry.get("path")
        sha = entry.get("sha256")
        if path and sha:
            cache[path] = (int(entry.get("size") or 0), str(entry.get("mtime_utc") or ""), sha)
    return cache


def file_entry(path, rel_path, classes, sha_cache=None):
    stat = Path(path).stat()
    size = stat.st_size
    mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
    sha = None
    if sha_cache is not None:
        cached = sha_cache.get(rel_path)
        if cached and cached[0] == size and cached[1] == mtime:
            sha = cached[2]
    return {
        "path": rel_path,
        "classes": sorted(classes),
        **classification_payload(rel_path),
        "size": size,
        "mtime_utc": mtime,
        "sha256": sha if sha is not None else sha256_file(path),
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


def build_backup_manifest(source_root=REPO_ROOT, prior_manifest=None):
    source_root = Path(source_root)
    sha_cache = build_sha_cache(prior_manifest)
    coverage_cutoff_utc = utc_iso()
    entries = []
    for path, rel in iter_candidate_files(source_root):
        classes = classify_path(rel)
        if classes:
            entries.append(file_entry(path, rel, classes, sha_cache=sha_cache))
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


def backup_copy_unchanged(path, entry):
    """True when the backed-up copy already matches the manifest entry by size +
    mtime. The backup is written with shutil.copy2 (preserves mtime), so an
    unchanged source file leaves the backup copy with the same size + mtime as
    the entry; a changed source file gets a new mtime and is re-copied. This
    replaces the per-file sha256 re-hash in the copy loop."""
    path = Path(path)
    if not path.exists():
        return False
    stat = path.stat()
    return (
        stat.st_size == int(entry.get("size") or 0)
        and datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat() == entry.get("mtime_utc")
    )


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


def latest_manifest_path(backup_root=DEFAULT_BACKUP_ROOT):
    return Path(backup_root) / LATEST_DIR / "tape_backup_manifest.json"


def load_backup_manifest(backup_root=DEFAULT_BACKUP_ROOT):
    path = latest_manifest_path(backup_root)
    if not path.exists():
        return None, path
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload, path


def default_dedup_manifest_path(source_root=REPO_ROOT):
    return Path(source_root) / "data" / "backtest" / DEFAULT_DEDUP_MANIFEST_NAME


def validate_manifest(manifest):
    if not manifest:
        return False, "missing manifest"
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        return False, f"unexpected schema {manifest.get('schema_version')}"
    expected = manifest_hash(manifest)
    if manifest.get("manifest_hash") != expected:
        return False, f"manifest hash mismatch: expected {expected}, found {manifest.get('manifest_hash')}"
    return True, "ok"


def verify_backup_files(manifest, backup_root=DEFAULT_BACKUP_ROOT, limit=None, deep=False):
    """Verify the backed-up copies against the manifest.

    Fast path (default): a backup copy whose size + mtime match the manifest is
    trusted -- the backup is written with shutil.copy2 (which preserves mtime),
    so a matching size+mtime means it is the verified copy and has not been
    truncated or replaced. Only files that are missing or whose size/mtime
    drifted are re-hashed. This keeps the daily verify proportional to changes so
    the run actually completes. Deep (full sha256) verification of every copy --
    which catches silent bitrot that leaves size+mtime intact -- is provided by
    the restore drill, which re-hashes every restored file; pass deep=True to
    force it here too.
    """
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
        if not deep:
            stat = path.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            if stat.st_size == int(entry.get("size") or 0) and mtime == entry.get("mtime_utc"):
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


__all__ = [
    "REPO_ROOT",
    "relative_to_repo",
    "data_path",
    "MANIFEST_SCHEMA_VERSION",
    "RESTORE_DRILL_SCHEMA_VERSION",
    "UNMANIFESTED_CLEANUP_SCHEMA_VERSION",
    "DEDUP_REPOSITORY_SCHEMA_VERSION",
    "POLICY_VERSION",
    "DEFAULT_CAPACITY_MARGIN_BYTES",
    "_env_int",
    "DEFAULT_LOCAL_MIRROR_CACHE_RETENTION_DAYS",
    "DEFAULT_BACKUP_ROOT",
    "DEFAULT_STATUS_OUT",
    "DEFAULT_REPORT_OUT",
    "DEFAULT_RESTORE_OUT",
    "DEFAULT_RESTORE_REPORT",
    "DEFAULT_UNMANIFESTED_CLEANUP_OUT",
    "DEFAULT_UNMANIFESTED_CLEANUP_REPORT",
    "DEFAULT_UNMANIFESTED_DURABLE_PROOF_OUT",
    "DEFAULT_UNMANIFESTED_DURABLE_PROOF_REPORT",
    "DEFAULT_DEDUP_MANIFEST_NAME",
    "DEFAULT_DEDUP_BACKUP_OUT",
    "DEFAULT_DEDUP_BACKUP_REPORT",
    "DEFAULT_DEDUP_STATUS_OUT",
    "DEFAULT_DEDUP_STATUS_REPORT",
    "DEFAULT_DEDUP_RESTORE_OUT",
    "DEFAULT_DEDUP_RESTORE_REPORT",
    "DEFAULT_TASK_NAME",
    "LATEST_DIR",
    "LATEST_CONTROL_FILES",
    "DEDUP_BACKEND_RESTIC",
    "DEDUP_RESTIC_TAG",
    "UNMANIFESTED_MIRROR_PROOF_RESTIC_TAG",
    "RetentionRule",
    "ClobArtifactPolicy",
    "CLOB_ARTIFACT_POLICIES",
    "RETENTION_RULES",
    "GLOBAL_EXCLUDES",
    "utc_now",
    "utc_iso",
    "sha256_file",
    "_posix",
    "_matches_any",
    "_excluded",
    "retention_policy_payload",
    "classify_path",
    "iter_candidate_files",
    "file_entry",
    "class_summaries",
    "_entry_without_hash",
    "_critical_classes",
    "local_candidate_entries",
    "_summarize_entries_by_class",
    "_manifest_entry_map",
    "_entry_mtime",
    "_manifest_cutoff",
    "_after_manifest_cutoff",
    "_clob_policy_for_path",
    "clob_artifact_coverage",
    "local_manifest_coverage_audit",
    "manifest_hash_payload",
    "manifest_hash",
    "build_backup_manifest",
    "_same_backup_file",
    "backup_copy_unchanged",
    "build_sha_cache",
    "TapeBackupCapacityError",
    "disk_usage_root",
    "backup_capacity_preflight",
    "coverage_capacity_preflight",
    "write_json",
    "latest_manifest_path",
    "load_backup_manifest",
    "default_dedup_manifest_path",
    "validate_manifest",
    "verify_backup_files",
    "_parse_time",
    "load_restore_drill_status",
    "restore_drill_sla_status",
    "backup_status",
    "backup_alerts",
    "_schema_check",
]
