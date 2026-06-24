"""Fail-closed cleanup preflight for local data deletion manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.operations.storage_classes import classification_payload
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


CLEANUP_MANIFEST_SCHEMA_VERSION = schema_version("cleanup_manifest")
CLEANUP_PREFLIGHT_SCHEMA_VERSION = schema_version("cleanup_preflight")
DEFAULT_DATA_ROOT = data_path()
DEFAULT_BACKUP_STATUS = DEFAULT_DATA_ROOT / "backtest" / "tape_backup_status.json"
DEFAULT_OUT = DEFAULT_DATA_ROOT / "backtest" / "cleanup_preflight.json"
DEFAULT_REPORT = DEFAULT_DATA_ROOT / "backtest" / "cleanup_preflight_report.md"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    path = Path(path)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _root_relative_path(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _classification_path(rel_path: str, root: Path) -> str:
    root_name = root.name.lower()
    if root_name in {"backtest", "snapshots", "mm_runs", "taker_runs", "logs", "ops"}:
        return f"{root_name}/{rel_path}"
    return rel_path


def _review_ok(manifest: dict[str, Any]) -> tuple[bool, str]:
    review = manifest.get("operator_review") or {}
    if review.get("approved") is not True:
        return False, "operator_review.approved must be true"
    if not review.get("note"):
        return False, "operator_review.note is required"
    if not review.get("approved_by"):
        return False, "operator_review.approved_by is required"
    return True, "ok"


def _backup_ok(backup_status: dict[str, Any]) -> tuple[bool, str]:
    status = backup_status.get("status")
    if status != "OK":
        return False, f"backup status is {status or 'MISSING'}"
    if backup_status.get("restore_drill_sla_status") != "OK":
        return False, f"restore drill SLA is {backup_status.get('restore_drill_sla_status') or 'MISSING'}"
    if int(backup_status.get("missing_critical_files") or 0) > 0:
        return False, "latest backup manifest is missing critical files"
    if int(backup_status.get("missing_critical_bytes") or 0) > 0:
        return False, "latest backup manifest is missing critical bytes"
    if backup_status.get("checksum_failures"):
        return False, "backup checksum failures are present"
    return True, "ok"


def _manifest_entry_map(backup_status: dict[str, Any]) -> dict[str, dict[str, Any]]:
    manifest_path = backup_status.get("manifest_path")
    manifest = _load_json(manifest_path)
    return {
        str(row.get("path")): row
        for row in manifest.get("files") or []
        if row.get("path")
    }


def _backup_contains_candidate(
    candidate: dict[str, Any],
    backup_status: dict[str, Any],
    backup_entries: dict[str, dict[str, Any]],
) -> tuple[bool, str]:
    status_hash = backup_status.get("manifest_hash")
    candidate_hash = candidate.get("backup_manifest_hash")
    if not candidate_hash:
        return False, "candidate backup_manifest_hash is required"
    if candidate_hash != status_hash:
        return False, "candidate backup_manifest_hash does not match latest backup status"
    restore_hash = candidate.get("restore_drill_hash")
    drill = backup_status.get("last_restore_drill") or {}
    if not restore_hash:
        return False, "candidate restore_drill_hash is required"
    if restore_hash != drill.get("manifest_hash"):
        return False, "candidate restore_drill_hash does not match latest restore drill"
    data_path_value = str(candidate.get("data_path") or candidate.get("path") or "")
    candidates = [data_path_value]
    if not data_path_value.startswith("data/"):
        candidates.append(f"data/{data_path_value}")
    for key in candidates:
        entry = backup_entries.get(key)
        if not entry:
            continue
        if candidate.get("sha256") and entry.get("sha256") != candidate.get("sha256"):
            return False, "backup manifest SHA-256 does not match cleanup candidate"
        return True, "ok"
    return False, "candidate file is absent from latest backup manifest"


def cleanup_manifest_for_paths(
    paths: list[str | Path] | tuple[str | Path, ...],
    *,
    root: str | Path = DEFAULT_DATA_ROOT,
    classification_prefix: str | None = None,
    deletion_reason: str,
    operator_review: dict[str, Any],
    backup_status: dict[str, Any] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    candidates = []
    backup_status = backup_status or {}
    restore = backup_status.get("last_restore_drill") or {}
    for item in paths:
        path = Path(item)
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        root_resolved = root.resolve()
        path.relative_to(root_resolved)
        rel_path = _root_relative_path(path, root_resolved)
        data_path_value = f"{classification_prefix.strip('/')}/{rel_path}" if classification_prefix else _classification_path(rel_path, root_resolved)
        classification = classification_payload(data_path_value)
        size = path.stat().st_size if path.exists() else 0
        sha = sha256_file(path) if path.exists() else None
        candidates.append({
            "path": rel_path,
            "data_path": data_path_value,
            "storage_class": classification["storage_class"],
            "retention_class": classification["retention_class"],
            "artifact_family": classification["artifact_family"],
            "deletion_reason": deletion_reason,
            "rebuild_source": classification["rebuild_source"],
            "bytes": int(size),
            "sha256": sha,
            "backup_manifest_hash": backup_status.get("manifest_hash"),
            "restore_drill_hash": restore.get("manifest_hash"),
        })
    return {
        "schema_version": CLEANUP_MANIFEST_SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "root": str(root),
        "operator_review": operator_review,
        "candidates": candidates,
    }


def build_cleanup_preflight(
    cleanup_manifest: dict[str, Any],
    *,
    root: str | Path | None = None,
    backup_status: dict[str, Any] | None = None,
    backup_status_path: str | Path | None = DEFAULT_BACKUP_STATUS,
) -> dict[str, Any]:
    root = Path(root or cleanup_manifest.get("root") or DEFAULT_DATA_ROOT).resolve()
    backup_status = backup_status if backup_status is not None else _load_json(backup_status_path)
    backup_entries = _manifest_entry_map(backup_status)
    review_pass, review_detail = _review_ok(cleanup_manifest)
    backup_pass, backup_detail = _backup_ok(backup_status)
    raw_candidates = cleanup_manifest.get("candidates") or cleanup_manifest.get("selected") or []
    has_canonical_candidate = any(
        (
            candidate.get("storage_class")
            or classification_payload(candidate.get("data_path") or _classification_path(str(candidate.get("path") or ""), root))["storage_class"]
        )
        == "canonical_evidence"
        for candidate in raw_candidates
    )
    checks = [{
        "check": "operator_review",
        "status": "PASS" if review_pass else "BLOCK",
        "detail": review_detail,
    }]
    if has_canonical_candidate and (backup_status or {}).get("status") == "MISSING_CRITICAL_FILES":
        checks.append({
            "check": "missing_critical_files",
            "status": "BLOCK",
            "detail": "latest tape backup status reports missing critical files",
            "missing_critical_files": backup_status.get("missing_critical_files"),
            "missing_critical_bytes": backup_status.get("missing_critical_bytes"),
            "missing_samples": backup_status.get("missing_critical_file_samples") or [],
        })
    candidate_rows = []
    for candidate in raw_candidates:
        rel_path = Path(str(candidate.get("path") or ""))
        row_checks: list[dict[str, Any]] = []
        if rel_path.is_absolute():
            row_checks.append({"check": "relative_path", "status": "BLOCK", "detail": "candidate path must be relative"})
            path = rel_path
        else:
            path = (root / rel_path).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                row_checks.append({"check": "path_within_root", "status": "BLOCK", "detail": "candidate path escapes root"})
        if not path.exists():
            row_checks.append({"check": "file_exists", "status": "BLOCK", "detail": "candidate file is missing"})
        else:
            size = int(path.stat().st_size)
            actual_sha = sha256_file(path)
            if candidate.get("bytes") is not None and int(candidate.get("bytes") or 0) != size:
                row_checks.append({"check": "bytes", "status": "BLOCK", "expected": candidate.get("bytes"), "actual": size})
            if candidate.get("sha256") and candidate.get("sha256") != actual_sha:
                row_checks.append({"check": "sha256", "status": "BLOCK", "detail": "candidate checksum changed"})
        classification = classification_payload(candidate.get("data_path") or _classification_path(rel_path.as_posix(), root))
        storage_class = candidate.get("storage_class") or classification["storage_class"]
        if candidate.get("storage_class") and candidate.get("storage_class") != classification["storage_class"]:
            row_checks.append({
                "check": "storage_class",
                "status": "BLOCK",
                "expected": candidate.get("storage_class"),
                "actual": classification["storage_class"],
            })
        if not candidate.get("deletion_reason"):
            row_checks.append({"check": "deletion_reason", "status": "BLOCK", "detail": "deletion_reason is required"})
        if storage_class == "canonical_evidence":
            if not backup_pass:
                row_checks.append({"check": "backup_restore_status", "status": "BLOCK", "detail": backup_detail})
            contains, detail = _backup_contains_candidate(candidate, backup_status, backup_entries)
            row_checks.append({"check": "backup_manifest_coverage", "status": "PASS" if contains else "BLOCK", "detail": detail})
        elif storage_class == "analysis_projection":
            rebuild_source = candidate.get("rebuild_source")
            if not rebuild_source or rebuild_source == "unknown":
                row_checks.append({"check": "rebuild_source", "status": "BLOCK", "detail": "analysis projection cleanup requires rebuild_source"})
        elif storage_class == "operator_cache":
            row_checks.append({"check": "operator_cache_cleanup", "status": "PASS"})
        else:
            row_checks.append({"check": "storage_classified", "status": "BLOCK", "detail": "candidate is unclassified"})
        if not row_checks:
            row_checks.append({"check": "candidate_shape", "status": "PASS"})
        row_status = "BLOCK" if any(check.get("status") == "BLOCK" for check in row_checks) else "PASS"
        candidate_rows.append({
            "path": str(candidate.get("path") or ""),
            "storage_class": storage_class,
            "artifact_family": candidate.get("artifact_family") or classification["artifact_family"],
            "status": row_status,
            "checks": row_checks,
        })
    status = "BLOCK" if any(check.get("status") == "BLOCK" for check in checks) or any(row["status"] == "BLOCK" for row in candidate_rows) else "PASS"
    return {
        "schema_version": CLEANUP_PREFLIGHT_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": status,
        "delete_permission": status == "PASS",
        "root": str(root),
        "backup_status": {
            "status": backup_status.get("status") or "MISSING",
            "manifest_hash": backup_status.get("manifest_hash"),
            "restore_drill_sla_status": backup_status.get("restore_drill_sla_status"),
            "missing_critical_files": backup_status.get("missing_critical_files"),
            "missing_critical_bytes": backup_status.get("missing_critical_bytes"),
        },
        "checks": checks,
        "candidates": candidate_rows,
    }


def render_report(payload: dict[str, Any]) -> str:
    backup = payload.get("backup_status") or {}
    lines = [
        "# Cleanup Preflight",
        "",
        f"Generated: `{payload.get('generated_at_utc')}`",
        f"Status: **{payload.get('status')}**",
        f"Delete permission: `{payload.get('delete_permission')}`",
        f"Root: `{payload.get('root')}`",
        "",
        "## Backup Gate",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Status", backup.get("status")],
                ["Manifest hash", backup.get("manifest_hash")],
                ["Restore drill SLA", backup.get("restore_drill_sla_status")],
                ["Missing critical files", backup.get("missing_critical_files")],
                ["Missing critical bytes", backup.get("missing_critical_bytes")],
            ],
        ),
        "",
        "## Candidates",
        "",
        *markdown_table(
            ["Path", "Storage Class", "Family", "Status"],
            [
                [row.get("path"), row.get("storage_class"), row.get("artifact_family"), row.get("status")]
                for row in payload.get("candidates") or []
            ],
        ),
    ]
    blockers = [
        check
        for check in payload.get("checks") or []
        if check.get("status") == "BLOCK"
    ]
    for row in payload.get("candidates") or []:
        blockers.extend(
            {**check, "path": row.get("path")}
            for check in row.get("checks") or []
            if check.get("status") == "BLOCK"
        )
    if blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(
            f"- `{row.get('path') or row.get('check')}` {row.get('check')}: {row.get('detail') or row.get('status')}"
            for row in blockers[:50]
        )
    lines.append("")
    return "\n".join(lines)


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed cleanup preflight for deletion manifests.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--root", default="")
    parser.add_argument("--backup-status", default=str(DEFAULT_BACKUP_STATUS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = _load_json(args.manifest)
    payload = build_cleanup_preflight(
        manifest,
        root=args.root or None,
        backup_status_path=args.backup_status,
    )
    out = write_json(args.out, payload)
    report = write_report(args.report, payload)
    print(f"Cleanup preflight: {payload['status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
