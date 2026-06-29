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


from weather.operations.tape_backup_manifest import *  # noqa: F403
from weather.operations.tape_backup_dedup import *  # noqa: F403
from weather.operations.tape_backup_cleanup import *  # noqa: F403


def export_backup(
    source_root=REPO_ROOT,
    backup_root=DEFAULT_BACKUP_ROOT,
    dry_run=False,
    capacity_preflight=True,
    capacity_margin_bytes=DEFAULT_CAPACITY_MARGIN_BYTES,
):
    source_root = Path(source_root)
    backup_root = Path(backup_root)
    # Reuse the prior manifest's sha256 for source files whose size+mtime are
    # unchanged, so we do not re-hash ~200k files every run (the reason the
    # backup never completed). Changed files are re-hashed and re-copied.
    prior_manifest, _ = load_backup_manifest(backup_root)
    manifest = build_backup_manifest(source_root, prior_manifest=prior_manifest)
    latest_root = backup_root / LATEST_DIR
    copied = 0
    copied_paths = set()
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
        if backup_copy_unchanged(dst, entry):
            skipped += 1
            continue
        shutil.copy2(src, dst)
        copied += 1
        copied_paths.add(entry["path"])
    if not dry_run:
        # Record the backup manifest from the backed-up copies. Files copied this
        # run are re-hashed from the destination so the entry reflects the actual
        # backed-up bytes even if the source changed between manifest build and
        # copy. Files that were skipped (size+mtime unchanged) are byte-identical
        # to their source entry -- whose sha256 was itself reused from the prior
        # manifest -- so reuse it rather than re-hashing every untouched file.
        backed_up_entries = []
        for entry in manifest["files"]:
            dst = latest_root / entry["path"]
            if not dst.exists():
                continue
            if entry["path"] in copied_paths:
                backed_up_entries.append(file_entry(dst, entry["path"], entry.get("classes") or []))
            else:
                backed_up_entries.append(entry)
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
            durable_restore_proof_path=args.durable_restore_proof or None,
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


def cmd_prove_unmanifested(args):
    plan = None
    if args.plan:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    payload = run_unmanifested_durable_restore_proof(
        backup_root=args.backup_root,
        source_root=args.source_root,
        plan=plan,
        backend=args.backend,
        repository=args.repository or None,
        executable=args.executable,
        password_file=args.password_file or None,
        restore_root=args.restore_root or None,
        keep_restore=args.keep_restore,
        out=args.out,
        report=args.report,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        f"Tape backup unmanifested durable restore proof: {payload.get('status')} "
        f"verified={(payload.get('summary') or {}).get('verified_files', 0)}"
    )
    print(f"JSON written to {args.out}")
    print(f"Report written to {args.report}")
    return 0 if payload.get("status") == "PASS" else 2


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
    prune.add_argument("--durable-restore-proof", default="")
    prune.add_argument("--out", default=str(DEFAULT_UNMANIFESTED_CLEANUP_OUT))
    prune.add_argument("--report", default=str(DEFAULT_UNMANIFESTED_CLEANUP_REPORT))
    prune.set_defaults(func=cmd_prune_unmanifested)

    proof = sub.add_parser("prove-unmanifested")
    proof.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    proof.add_argument("--source-root", default=str(REPO_ROOT))
    proof.add_argument("--plan", default="")
    proof.add_argument("--restore-root", default="")
    proof.add_argument("--keep-restore", action="store_true")
    proof.add_argument("--out", default=str(DEFAULT_UNMANIFESTED_DURABLE_PROOF_OUT))
    proof.add_argument("--report", default=str(DEFAULT_UNMANIFESTED_DURABLE_PROOF_REPORT))
    _add_dedup_common_args(proof)
    proof.set_defaults(func=cmd_prove_unmanifested)

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
