"""Retention, backup, and restore-drill tooling for irreplaceable tapes."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import REPO_ROOT, relative_to_repo
from weather.schema_registry import SCHEMAS_BY_VERSION, schema_version


MANIFEST_SCHEMA_VERSION = schema_version("tape_backup_manifest")
RESTORE_DRILL_SCHEMA_VERSION = schema_version("tape_restore_drill")
POLICY_VERSION = "tape_retention_policy_v0.1"
DEFAULT_BACKUP_ROOT = Path(os.environ.get("WEATHER_TAPE_BACKUP_ROOT", "data/tape_backups"))
DEFAULT_STATUS_OUT = Path("data") / "backtest" / "tape_backup_status.json"
DEFAULT_REPORT_OUT = Path("data") / "backtest" / "tape_backup_status_report.md"
DEFAULT_RESTORE_OUT = Path("data") / "backtest" / "tape_restore_drill.json"
DEFAULT_RESTORE_REPORT = Path("data") / "backtest" / "tape_restore_drill_report.md"
LATEST_DIR = "latest"


@dataclass(frozen=True)
class RetentionRule:
    name: str
    recoverability: str
    retention: str
    critical: bool
    description: str
    patterns: tuple[str, ...]
    excludes: tuple[str, ...] = ()


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


def manifest_hash_payload(manifest):
    return {
        "schema_version": manifest.get("schema_version"),
        "policy_version": manifest.get("policy_version"),
        "source_root": manifest.get("source_root"),
        "files": manifest.get("files") or [],
        "class_summaries": manifest.get("class_summaries") or {},
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
    entries = []
    for path, rel in iter_candidate_files(source_root):
        classes = classify_path(rel)
        if classes:
            entries.append(file_entry(path, rel, classes))
    entries.sort(key=lambda row: row["path"])
    summaries = class_summaries(entries)
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "generated_at_utc": utc_iso(),
        "source_root": str(source_root),
        "policy": retention_policy_payload(),
        "class_summaries": summaries,
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


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def export_backup(source_root=REPO_ROOT, backup_root=DEFAULT_BACKUP_ROOT, dry_run=False):
    source_root = Path(source_root)
    backup_root = Path(backup_root)
    manifest = build_backup_manifest(source_root)
    latest_root = backup_root / LATEST_DIR
    copied = 0
    skipped = 0
    if not dry_run:
        latest_root.mkdir(parents=True, exist_ok=True)
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
    manifest["backup"] = {
        "backup_root": str(backup_root),
        "latest_root": str(latest_root),
        "dry_run": bool(dry_run),
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
    return payload


def backup_status(backup_root=DEFAULT_BACKUP_ROOT, max_age_hours=26, verify_checksums=False):
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
    status = "OK"
    if not valid:
        status = "CORRUPT_MANIFEST"
    elif verify["failures"]:
        status = "CHECKSUM_FAIL"
    elif missing:
        status = "MISSING_CRITICAL_CLASS"
    elif age_hours is not None and age_hours > float(max_age_hours):
        status = "STALE"
    restore = load_restore_drill_status(backup_root)
    if status == "OK" and restore.get("status") in {"FAIL", "UNREADABLE"}:
        status = "RESTORE_DRILL_FAIL"
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
        "file_count": (manifest.get("summary") or {}).get("file_count"),
        "total_bytes": (manifest.get("summary") or {}).get("total_bytes"),
        "class_summaries": manifest.get("class_summaries") or {},
        "missing_critical_classes": missing,
        "checksum_checked_files": verify.get("checked_files"),
        "checksum_failures": verify.get("failures") or [],
        "last_restore_drill": restore,
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
        "RESTORE_DRILL_FAIL",
    } else "warning"
    alerts.append({
        "severity": severity,
        "market_id": "fleet",
        "category": "tape_backup",
        "message": f"tape backup status is {state}",
        "detail": {
            "backup_root": (status or {}).get("backup_root"),
            "missing_critical_classes": (status or {}).get("missing_critical_classes") or [],
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


def write_status_report(path, payload):
    lines = [
        "# Tape Backup Status",
        "",
        f"Generated: {utc_iso()}",
        f"Status: **{payload.get('status')}**",
        f"Backup root: `{payload.get('backup_root')}`",
        f"Manifest age hours: `{payload.get('age_hours')}`",
        f"Files: `{payload.get('file_count')}`",
        "",
        "## Missing Critical Classes",
        "",
    ]
    for name in payload.get("missing_critical_classes") or ["-"]:
        lines.append(f"- {name}")
    lines += ["", "## Class Summary", "", "| Class | Critical | Files | Bytes |", "| :--- | :--- | :--- | :--- |"]
    for name, row in sorted((payload.get("class_summaries") or {}).items()):
        lines.append(f"| {name} | {row.get('critical')} | {row.get('file_count')} | {row.get('total_bytes')} |")
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
    )
    write_json(args.out, payload)
    write_status_report(args.report, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("status") == "OK" else 2


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
    export.set_defaults(func=cmd_export)

    status = sub.add_parser("status")
    status.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    status.add_argument("--max-age-hours", type=float, default=26.0)
    status.add_argument("--verify-checksums", action="store_true")
    status.add_argument("--out", default=str(DEFAULT_STATUS_OUT))
    status.add_argument("--report", default=str(DEFAULT_REPORT_OUT))
    status.set_defaults(func=cmd_status)

    drill = sub.add_parser("restore-drill")
    drill.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    drill.add_argument("--restore-root", default="")
    drill.add_argument("--keep-restore", action="store_true")
    drill.add_argument("--out", default=str(DEFAULT_RESTORE_OUT))
    drill.add_argument("--report", default=str(DEFAULT_RESTORE_REPORT))
    drill.set_defaults(func=cmd_restore_drill)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
