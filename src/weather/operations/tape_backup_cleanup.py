"""Unmanifested local mirror cleanup helpers for tape backup."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from weather.operations.storage_classes import classification_payload
from weather.operations.tape_backup_dedup import (
    _run_restic,
    _snapshot_id_from_backup_output,
    dedup_repository_preflight,
)
from weather.operations.tape_backup_manifest import *  # noqa: F403
from weather.reporting.formatting import markdown_table


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
                "duplicate_evidence": row.get("duplicate_evidence"),
                "durable_restore_verified": row.get("durable_restore_verified"),
                "durable_restore_repository": row.get("durable_restore_repository"),
                "durable_restore_snapshot_id": row.get("durable_restore_snapshot_id"),
                "durable_restore_proof_hash": row.get("durable_restore_proof_hash"),
                "durable_restore_sha256": row.get("durable_restore_sha256"),
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


def _unmanifested_durable_restore_proof_hash_payload(payload):
    return {
        "schema_version": payload.get("schema_version"),
        "kind": payload.get("kind"),
        "backend": payload.get("backend"),
        "repository": payload.get("repository"),
        "snapshot_tag": payload.get("snapshot_tag"),
        "snapshot_id": payload.get("snapshot_id"),
        "latest_root": payload.get("latest_root"),
        "plan_hash": payload.get("plan_hash"),
        "entries": [
            {
                "rel_path": row.get("rel_path"),
                "size": row.get("size"),
                "backup_sha256": row.get("backup_sha256"),
                "restored_sha256": row.get("restored_sha256"),
                "status": row.get("status"),
            }
            for row in sorted(payload.get("entries") or [], key=lambda item: str(item.get("rel_path") or ""))
        ],
    }


def unmanifested_durable_restore_proof_hash(payload):
    encoded = json.dumps(
        _unmanifested_durable_restore_proof_hash_payload(payload),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_unmanifested_durable_restore_proof(path=None):
    if not path:
        return {"exists": False, "path": "", "status": "MISSING"}
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


def unmanifested_durable_restore_proof_sla_status(proof, max_restore_age_hours=168):
    proof = proof or {}
    if not proof.get("exists"):
        return "PROOF_MISSING", "no durable restore proof supplied"
    if proof.get("status") in {"UNREADABLE", "FAIL"}:
        return "PROOF_FAIL", proof.get("error") or "durable restore proof failed"
    if proof.get("status") != "PASS":
        return "PROOF_FAIL", f"unexpected durable restore proof status {proof.get('status')}"
    proof_hash = proof.get("proof_hash")
    computed_hash = unmanifested_durable_restore_proof_hash(proof)
    if not proof_hash:
        return "PROOF_CORRUPT", "durable restore proof has no proof_hash"
    if proof_hash != computed_hash:
        return "PROOF_CORRUPT", "durable restore proof hash does not match proof contents"
    age_hours = proof.get("age_hours")
    if age_hours is not None and float(age_hours) > float(max_restore_age_hours):
        return "PROOF_STALE", f"durable restore proof age {age_hours}h exceeds SLA {max_restore_age_hours}h"
    return "OK", "durable restore proof is current"


def _durable_restore_proof_entry_map(proof, max_restore_age_hours=168):
    status, detail = unmanifested_durable_restore_proof_sla_status(
        proof,
        max_restore_age_hours=max_restore_age_hours,
    )
    entries = {}
    if status != "OK":
        return entries, status, detail
    for entry in proof.get("entries") or []:
        rel = entry.get("rel_path")
        if not rel or entry.get("status") != "PASS":
            continue
        if not entry.get("backup_sha256") or entry.get("backup_sha256") != entry.get("restored_sha256"):
            continue
        entries[rel] = entry
    return entries, status, detail


def _valid_cleanup_rel_path(rel):
    rel_path = Path(str(rel or ""))
    return bool(rel) and not rel_path.is_absolute() and ".." not in rel_path.parts


def _unmanifested_rows_needing_durable_proof(plan):
    rows = []
    for row in plan.get("files") or []:
        if row.get("source_same_hash"):
            continue
        if not row.get("rel_path") or row.get("rel_path") in LATEST_CONTROL_FILES:
            continue
        rows.append(row)
    return rows


def _cleanup_empty_parents(path, stop_root):
    current = Path(path).parent
    stop_root = Path(stop_root).resolve()
    while True:
        try:
            current.resolve().relative_to(stop_root)
        except ValueError:
            return
        if current.resolve() == stop_root:
            return
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def write_unmanifested_durable_restore_proof_report(path, payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Tape Backup Unmanifested Durable Restore Proof",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: **{payload.get('status')}**",
        f"Backend: `{payload.get('backend')}`",
        f"Repository: `{payload.get('repository') or '-'}`",
        f"Snapshot tag: `{payload.get('snapshot_tag')}`",
        f"Snapshot id: `{payload.get('snapshot_id') or '-'}`",
        f"Proof hash: `{payload.get('proof_hash') or '-'}`",
        f"Latest root: `{payload.get('latest_root')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Selected files", summary.get("selected_files")],
            ["Selected MiB", round(int(summary.get("selected_bytes") or 0) / (1024 * 1024), 1)],
            ["Verified files", summary.get("verified_files")],
            ["Failed files", summary.get("failed_files")],
        ],
    )
    failures = [row for row in payload.get("entries") or [] if row.get("status") != "PASS"]
    lines += ["", "## Failures", ""]
    if failures:
        lines += markdown_table(
            ["Path", "Status", "Reason"],
            [[row.get("rel_path"), row.get("status"), row.get("reason")] for row in failures[:50]],
        )
    else:
        lines.append("- none")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_unmanifested_durable_restore_proof(
    *,
    backup_root=DEFAULT_BACKUP_ROOT,
    source_root=REPO_ROOT,
    plan=None,
    backend=DEDUP_BACKEND_RESTIC,
    repository=None,
    executable=DEDUP_BACKEND_RESTIC,
    password_file=None,
    restore_root=None,
    keep_restore=False,
    out=DEFAULT_UNMANIFESTED_DURABLE_PROOF_OUT,
    report=DEFAULT_UNMANIFESTED_DURABLE_PROOF_REPORT,
    env=None,
    timeout_seconds=3600,
):
    plan = plan or unmanifested_backup_cleanup_plan(
        backup_root=backup_root,
        source_root=source_root,
    )
    latest_root = Path(plan.get("latest_root") or Path(backup_root) / LATEST_DIR)
    rows = _unmanifested_rows_needing_durable_proof(plan)
    payload = {
        "schema_version": UNMANIFESTED_CLEANUP_SCHEMA_VERSION,
        "kind": "unmanifested_mirror_durable_restore_proof",
        "generated_at_utc": utc_iso(),
        "status": "FAIL",
        "backend": backend,
        "repository": str(repository or ""),
        "snapshot_tag": UNMANIFESTED_MIRROR_PROOF_RESTIC_TAG,
        "snapshot_id": None,
        "backup_root": str(backup_root),
        "latest_root": str(latest_root),
        "source_root": str(source_root),
        "plan_hash": plan.get("plan_hash"),
        "commands": {},
        "entries": [],
        "summary": {
            "selected_files": len(rows),
            "selected_bytes": sum(int(row.get("size") or 0) for row in rows),
            "verified_files": 0,
            "failed_files": 0,
        },
    }
    preflight, merged_env = dedup_repository_preflight(
        backend=backend,
        repository=repository,
        executable=executable,
        password_file=password_file,
        env=env,
    )
    payload["preflight"] = preflight
    payload["repository"] = preflight.get("repository") or payload["repository"]
    if not rows:
        payload["status"] = "PASS"
        payload["proof_hash"] = unmanifested_durable_restore_proof_hash(payload)
        write_json(out, payload)
        write_unmanifested_durable_restore_proof_report(report, payload)
        return payload
    if preflight["status"] != "PASS":
        payload["status"] = preflight["status"]
        payload["proof_hash"] = unmanifested_durable_restore_proof_hash(payload)
        write_json(out, payload)
        write_unmanifested_durable_restore_proof_report(report, payload)
        return payload

    selected = []
    for row in rows:
        rel = row.get("rel_path")
        path = Path(row.get("path") or latest_root / str(rel or ""))
        entry = {
            "rel_path": rel,
            "path": str(path),
            "size": int(row.get("size") or 0),
            "backup_sha256": row.get("backup_sha256"),
            "restored_sha256": None,
            "status": "PENDING",
            "reason": "",
        }
        if not _valid_cleanup_rel_path(rel):
            entry.update({"status": "FAIL", "reason": "relative path is invalid"})
        elif not _is_path_under(path, latest_root):
            entry.update({"status": "FAIL", "reason": "path escapes latest backup root"})
        elif not path.exists():
            entry.update({"status": "FAIL", "reason": "mirror file is missing"})
        elif int(path.stat().st_size) != int(row.get("size") or 0):
            entry.update({"status": "FAIL", "reason": "mirror file size changed after cleanup plan"})
        else:
            backup_sha = sha256_file(path)
            entry["backup_sha256"] = backup_sha
            if row.get("backup_sha256") and row.get("backup_sha256") != backup_sha:
                entry.update({"status": "FAIL", "reason": "mirror checksum changed after cleanup plan"})
            else:
                selected.append(entry)
        payload["entries"].append(entry)
    if not selected:
        payload["summary"]["failed_files"] = len(payload["entries"])
        payload["proof_hash"] = unmanifested_durable_restore_proof_hash(payload)
        write_json(out, payload)
        write_unmanifested_durable_restore_proof_report(report, payload)
        return payload

    with tempfile.TemporaryDirectory(prefix="weather-tape-mirror-proof-files-") as tmp:
        files_from = Path(tmp) / "files-from.txt"
        files_from.write_text(
            "\n".join(row["rel_path"] for row in selected) + "\n",
            encoding="utf-8",
        )
        backup = _run_restic(
            executable,
            [
                "backup",
                "--files-from",
                str(files_from),
                "--tag",
                UNMANIFESTED_MIRROR_PROOF_RESTIC_TAG,
                "--tag",
                POLICY_VERSION,
                "--json",
            ],
            cwd=latest_root,
            env=merged_env,
            timeout_seconds=timeout_seconds,
        )
    payload["commands"]["backup"] = backup
    payload["snapshot_id"] = _snapshot_id_from_backup_output(backup.get("stdout_tail") or backup.get("stdout") or "")
    if backup["status"] != "PASS" or not payload["snapshot_id"]:
        for entry in payload["entries"]:
            if entry.get("status") == "PENDING":
                entry.update({"status": "FAIL", "reason": "durable repository backup failed"})
        payload["summary"]["failed_files"] = sum(1 for row in payload["entries"] if row.get("status") != "PASS")
        payload["proof_hash"] = unmanifested_durable_restore_proof_hash(payload)
        write_json(out, payload)
        write_unmanifested_durable_restore_proof_report(report, payload)
        return payload

    temp_ctx = None
    if restore_root is None:
        temp_ctx = tempfile.TemporaryDirectory(prefix="weather-tape-mirror-proof-restore-")
        restore_root = Path(temp_ctx.name)
    else:
        restore_root = Path(restore_root)
        restore_root.mkdir(parents=True, exist_ok=True)
    try:
        by_rel = {row["rel_path"]: row for row in payload["entries"]}
        for entry in selected:
            rel = entry["rel_path"]
            restore = _run_restic(
                executable,
                ["restore", payload["snapshot_id"], "--target", str(restore_root), "--include", rel],
                env=merged_env,
                timeout_seconds=timeout_seconds,
            )
            payload["commands"].setdefault("restore", {})[rel] = restore
            restored_path = restore_root / rel
            target = by_rel[rel]
            if restore["status"] != "PASS":
                target.update({"status": "FAIL", "reason": "durable repository restore failed"})
                continue
            if not restored_path.exists():
                target.update({"status": "FAIL", "reason": "restored file is missing"})
                continue
            restored_size = restored_path.stat().st_size
            restored_sha = sha256_file(restored_path)
            target["restored_size"] = restored_size
            target["restored_sha256"] = restored_sha
            if int(restored_size) != int(target.get("size") or 0):
                target.update({"status": "FAIL", "reason": "restored file size mismatch"})
            elif restored_sha != target.get("backup_sha256"):
                target.update({"status": "FAIL", "reason": "restored file checksum mismatch"})
            else:
                target.update({"status": "PASS", "reason": "durable repository restored byte-identical mirror file"})
            if not keep_restore and restored_path.exists():
                restored_path.unlink()
                _cleanup_empty_parents(restored_path, restore_root)
    finally:
        if temp_ctx is not None and not keep_restore:
            temp_ctx.cleanup()

    payload["summary"]["verified_files"] = sum(1 for row in payload["entries"] if row.get("status") == "PASS")
    payload["summary"]["failed_files"] = sum(1 for row in payload["entries"] if row.get("status") != "PASS")
    payload["status"] = "PASS" if payload["summary"]["failed_files"] == 0 else "FAIL"
    payload["proof_hash"] = unmanifested_durable_restore_proof_hash(payload)
    write_json(out, payload)
    write_unmanifested_durable_restore_proof_report(report, payload)
    return payload


def unmanifested_backup_cleanup_plan(
    backup_root=DEFAULT_BACKUP_ROOT,
    source_root=REPO_ROOT,
    *,
    max_restore_age_hours=168,
    local_cache_retention_days=DEFAULT_LOCAL_MIRROR_CACHE_RETENTION_DAYS,
    durable_restore_proof_path=None,
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
    durable_proof = load_unmanifested_durable_restore_proof(durable_restore_proof_path)
    durable_entries, durable_status, durable_detail = _durable_restore_proof_entry_map(
        durable_proof,
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
        "durable_restore_proof": {
            "exists": durable_proof.get("exists"),
            "path": durable_proof.get("path"),
            "status": durable_proof.get("status"),
            "sla_status": durable_status,
            "sla_detail": durable_detail,
            "generated_at_utc": durable_proof.get("generated_at_utc"),
            "repository": durable_proof.get("repository"),
            "snapshot_id": durable_proof.get("snapshot_id"),
            "proof_hash": durable_proof.get("proof_hash"),
        },
        "max_restore_age_hours": max_restore_age_hours,
        "summary": {
            "unmanifested_files": 0,
            "unmanifested_bytes": 0,
            "candidate_files": 0,
            "candidate_bytes": 0,
            "blocked_files": 0,
            "blocked_bytes": 0,
            "durable_restore_candidate_files": 0,
            "durable_restore_candidate_bytes": 0,
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
        durable_entry = durable_entries.get(rel)
        durable_verified = bool(
            durable_entry
            and int(durable_entry.get("size") or -1) == int(size)
            and durable_entry.get("backup_sha256") == backup_sha
            and durable_entry.get("restored_sha256") == backup_sha
        )
        if source_same_hash:
            status = "candidate"
            reason = "unmanifested mirror duplicate; source counterpart exists and hash matches"
            duplicate_evidence = "source_counterpart"
        elif durable_verified:
            status = "candidate"
            reason = "unmanifested mirror file has verified durable repository restore proof"
            duplicate_evidence = "durable_repository_restore"
        elif not source_exists:
            status = "blocked_missing_source"
            reason = "unmanifested backup file has no source counterpart"
            duplicate_evidence = "missing"
        elif not source_same_size:
            status = "blocked_source_size_mismatch"
            reason = "source counterpart exists but size differs from mirror copy"
            duplicate_evidence = "mismatch"
        else:
            status = "blocked_source_hash_mismatch"
            reason = "source counterpart exists but SHA-256 differs from mirror copy"
            duplicate_evidence = "mismatch"
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
            "duplicate_evidence": duplicate_evidence,
            "durable_restore_verified": durable_verified,
            "durable_restore_repository": durable_entry.get("repository") or durable_proof.get("repository") if durable_entry else None,
            "durable_restore_snapshot_id": durable_entry.get("snapshot_id") or durable_proof.get("snapshot_id") if durable_entry else None,
            "durable_restore_proof_hash": durable_proof.get("proof_hash") if durable_entry else None,
            "durable_restore_proof_generated_at_utc": durable_proof.get("generated_at_utc") if durable_entry else None,
            "durable_restore_sha256": durable_entry.get("restored_sha256") if durable_entry else None,
            "status": status,
            "reason": reason,
        })
    candidate_rows = [row for row in rows if row.get("status") == "candidate"]
    durable_candidate_rows = [
        row for row in candidate_rows
        if row.get("duplicate_evidence") == "durable_repository_restore"
    ]
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
            "all unmanifested mirror files have source or durable-restore evidence"
            if not blocked_rows else "one or more unmanifested mirror files lack source or durable-restore evidence",
            blocked_files=len(blocked_rows),
            blocked_bytes=sum(int(row.get("size") or 0) for row in blocked_rows),
        ),
    ]
    if durable_candidate_rows:
        gates.append(_cleanup_gate_row(
            "durable_restore_proof_current",
            durable_status == "OK",
            durable_detail,
            durable_restore_candidate_files=len(durable_candidate_rows),
        ))
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
            "durable_restore_candidate_files": len(durable_candidate_rows),
            "durable_restore_candidate_bytes": sum(int(row.get("size") or 0) for row in durable_candidate_rows),
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
        "all dry-run rows are verified source or durable-restore candidates"
        if not blocked_rows else "dry-run includes rows without source or durable-restore evidence",
        blocked_files=len(blocked_rows),
    ))
    candidate_rows = [row for row in rows if row.get("status") == "candidate"]
    validation_actions = []
    for row in candidate_rows:
        action = {
            "path": row.get("path"),
            "rel_path": row.get("rel_path"),
            "size": int(row.get("size") or 0),
            "duplicate_evidence": row.get("duplicate_evidence") or "source_counterpart",
            "source_exists": bool(row.get("source_exists")),
            "source_same_size": bool(row.get("source_same_size")),
            "source_same_hash": bool(row.get("source_same_hash")),
            "durable_restore_verified": bool(row.get("durable_restore_verified")),
            "durable_restore_repository": row.get("durable_restore_repository"),
            "durable_restore_snapshot_id": row.get("durable_restore_snapshot_id"),
            "durable_restore_proof_hash": row.get("durable_restore_proof_hash"),
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
        elif row.get("duplicate_evidence") != "durable_repository_restore" and not source_path.exists():
            action["status"] = "blocked"
            action["reason"] = "source counterpart is missing"
        elif int(path.stat().st_size) != int(row.get("size") or 0):
            action["status"] = "blocked"
            action["reason"] = "mirror file size changed after dry-run"
        elif row.get("duplicate_evidence") == "durable_repository_restore":
            backup_sha = sha256_file(path)
            action["backup_sha256"] = backup_sha
            action["durable_restore_sha256"] = row.get("durable_restore_sha256")
            if not row.get("durable_restore_verified"):
                action["status"] = "blocked"
                action["reason"] = "durable restore proof is missing"
            elif row.get("backup_sha256") and row.get("backup_sha256") != backup_sha:
                action["status"] = "blocked"
                action["reason"] = "mirror checksum changed after dry-run"
            elif row.get("durable_restore_sha256") != backup_sha:
                action["status"] = "blocked"
                action["reason"] = "durable restore proof checksum differs from mirror file"
            elif not row.get("durable_restore_repository") or not row.get("durable_restore_snapshot_id"):
                action["status"] = "blocked"
                action["reason"] = "durable restore proof lacks repository or snapshot id"
            else:
                action["status"] = "ready"
                action["reason"] = "verified durable-restore-backed mirror file"
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
            "duplicate_evidence": row.get("duplicate_evidence"),
            "source_exists": bool(row.get("source_exists")),
            "source_same_size": bool(row.get("source_same_size")),
            "source_same_hash": bool(row.get("source_same_hash")),
            "durable_restore_verified": bool(row.get("durable_restore_verified")),
            "durable_restore_repository": row.get("durable_restore_repository"),
            "durable_restore_snapshot_id": row.get("durable_restore_snapshot_id"),
            "durable_restore_proof_hash": row.get("durable_restore_proof_hash"),
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
        f"Durable restore proof: `{((payload.get('durable_restore_proof') or {}).get('sla_status') or '-')}` "
        f"({((payload.get('durable_restore_proof') or {}).get('path') or '-')})",
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
            ["Durable restore candidate files", summary.get("durable_restore_candidate_files")],
            ["Durable restore candidate MiB", round(int(summary.get("durable_restore_candidate_bytes") or 0) / (1024 * 1024), 1)],
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
            ["Path", "Storage Class", "Delete Gate", "Evidence", "MiB", "Source Exists", "Same Size", "Same Hash"],
            [
                [
                    row.get("rel_path"),
                    row.get("storage_class"),
                    row.get("delete_gate"),
                    row.get("duplicate_evidence"),
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
            ["Path", "MiB", "Status", "Evidence", "Reason", "Source Exists", "Same Size", "Same Hash"],
            [
                [
                    row.get("rel_path"),
                    round(int(row.get("size") or 0) / (1024 * 1024), 1),
                    row.get("status"),
                    row.get("duplicate_evidence"),
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


__all__ = [
    "_cleanup_operator_review_ok",
    "_unmanifested_cleanup_plan_hash_payload",
    "unmanifested_cleanup_plan_hash",
    "_cleanup_gate_row",
    "_is_path_under",
    "_unmanifested_durable_restore_proof_hash_payload",
    "unmanifested_durable_restore_proof_hash",
    "load_unmanifested_durable_restore_proof",
    "unmanifested_durable_restore_proof_sla_status",
    "_durable_restore_proof_entry_map",
    "_valid_cleanup_rel_path",
    "_unmanifested_rows_needing_durable_proof",
    "_cleanup_empty_parents",
    "write_unmanifested_durable_restore_proof_report",
    "run_unmanifested_durable_restore_proof",
    "unmanifested_backup_cleanup_plan",
    "apply_unmanifested_backup_cleanup",
    "render_unmanifested_cleanup_report",
    "write_unmanifested_cleanup_report",
]
