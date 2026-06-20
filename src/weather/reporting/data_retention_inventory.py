"""Data-tree ownership, retention, and disk-budget inventory."""

from __future__ import annotations

import argparse
import fnmatch
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("data_retention_inventory")
DEFAULT_DATA_ROOT = data_path()
DEFAULT_BACKUP_STATUS_PATH = DEFAULT_DATA_ROOT / "backtest" / "tape_backup_status.json"
DEFAULT_OUT = DEFAULT_DATA_ROOT / "backtest" / "data_retention_inventory.json"
DEFAULT_REPORT = DEFAULT_DATA_ROOT / "backtest" / "data_retention_inventory_report.md"
DEFAULT_MIN_FREE_BYTES = 5_000_000_000
DEFAULT_LOOKBACK_HOURS = 24.0
DEFAULT_TOP_N = 25


@dataclass(frozen=True)
class DataRetentionPolicy:
    name: str
    owner: str
    patterns: tuple[str, ...]
    durability: str
    local_ttl: str
    archive_ttl: str
    restore_requirement: str
    regeneration_path: str
    prune_policy: str
    backup_class: str = ""
    deletion_requires_restore: bool = False
    local_delete_allowed: bool = False


POLICIES = (
    DataRetentionPolicy(
        "snapshots",
        "collection/model/market",
        ("snapshots/**",),
        "irreplaceable live snapshot, feature, source-status, and CLOB evidence",
        "keep active and recent settled days locally; archive older proof-grade folders after restore proof",
        "permanent external archive for proof-grade live tapes",
        "requires current tape backup manifest and restore-drill proof before deletion",
        "not regenerable from providers after the fact",
        "delete only from an explicit manifest after restore proof; prefer gzip tiering for full-depth books",
        backup_class="snapshot_tapes",
        deletion_requires_restore=True,
    ),
    DataRetentionPolicy(
        "tape_backups",
        "operations/tape_backup",
        ("tape_backups/**",),
        "backup mirror and restore evidence",
        "bounded latest plus timestamped manifests; same-disk partials must be pruned",
        "external/NAS/cloud root with growth headroom",
        "same-workstation backup roots are not durable deletion proof",
        "not applicable; this is the restore source",
        "use weather.operations.tape_backup prune-unmanifested for failed-copy debris",
        local_delete_allowed=True,
    ),
    DataRetentionPolicy(
        "backtest",
        "reporting/calibration",
        ("backtest/**",),
        "mixed: promotion corpora and reports are durable; row exports may be rebuildable",
        "keep manifests, reports, promotion corpora, and current evidence; review large row exports after 30 days",
        "retain promotion corpora/manifests permanently; large rebuildable CSVs may be externalized",
        "deletion of promotion corpora requires artifact/restore proof; generated row exports require paired reports",
        "large row exports can usually be rebuilt from retained corpus, artifact, and report",
        "use backtest_artifact_retention cleanup manifest; never delete orphaned evidence by hand",
        backup_class="promotion_corpora",
        local_delete_allowed=True,
    ),
    DataRetentionPolicy(
        "settlements",
        "backtesting/market",
        ("settlements/**",),
        "irreplaceable settlement and label provenance",
        "retain locally with promotion corpora; archive after restore proof",
        "permanent external archive",
        "requires current tape backup and restore-drill proof before deletion",
        "not safely regenerable without settlement-source history and manual overrides",
        "delete only from a reviewed manifest after restore proof",
        backup_class="settlement_ledgers",
        deletion_requires_restore=True,
    ),
    DataRetentionPolicy(
        "mm_runs",
        "market",
        ("mm_runs/**",),
        "irreplaceable market-making paper/live-forward lifecycle evidence",
        "retain locally through active review; archive after restore proof",
        "permanent external archive for countable live/paper evidence",
        "requires current tape backup and restore-drill proof before deletion",
        "not regenerable because quote/fill/markout timing is live-only",
        "delete only from a reviewed manifest after restore proof and promotion windows close",
        backup_class="market_making_runs",
        deletion_requires_restore=True,
    ),
    DataRetentionPolicy(
        "taker_runs",
        "market",
        ("taker_runs/**",),
        "irreplaceable taker strategy, fill, and settlement evidence",
        "retain locally through strategy bakeoff and settlement finalization",
        "permanent external archive for countable trading evidence",
        "requires current tape backup and restore-drill proof before deletion",
        "not regenerable because fills and account snapshots are live-only",
        "delete only from a reviewed manifest after restore proof",
        deletion_requires_restore=True,
    ),
    DataRetentionPolicy(
        "ops",
        "operations",
        ("ops/**",),
        "operational reports, status, and local run diagnostics",
        "keep latest statuses and incident evidence; rotate noisy logs after 30 days",
        "archive incident reports with related run evidence",
        "restore proof required only for incident evidence; routine status is regenerable",
        "routine health reports are regenerated by daily refresh and fleet observability",
        "rotate only with an incident manifest or after confirming regenerated status exists",
        local_delete_allowed=True,
    ),
    DataRetentionPolicy(
        "provider_caches",
        "sources/model",
        (
            "forecast_archive/**",
            "forecast_history/**",
            "cache/**",
            "open_meteo/**",
            "weather_com/**",
            "source_cache/**",
        ),
        "mostly regenerable provider cache; some forecast archives are evidence",
        "keep recent cache within provider TTL; keep forecast archives used by training until archived",
        "archive forecast snapshots that participate in settled replay evidence",
        "cache deletion is allowed when no replay/promotion artifact references it",
        "regenerate from provider only where API history is available; live-issued forecasts may not be recoverable",
        "delete TTL-expired cache only; do not delete archived forecast snapshots without lineage review",
        local_delete_allowed=True,
    ),
    DataRetentionPolicy(
        "historical_sources",
        "sources",
        (
            "wunderground/**",
            "metar/**",
            "asos/**",
            "ghcnh/**",
            "noaa_ghcnh/**",
            "power/**",
            "nasa_power/**",
            "meteostat/**",
            "eccc/**",
            "eccc_swob/**",
        ),
        "historical weather source rows and provenance manifests",
        "retain canonical source histories locally; archive raw mirrors after restore proof",
        "permanent archive for raw/provenance source rows",
        "requires source manifest and restore proof before raw deletion",
        "some provider history is backfillable, but canonical settled-source provenance is not safely assumed regenerable",
        "delete only duplicate raw mirrors after manifest and restore proof",
        backup_class="source_manifests",
        deletion_requires_restore=True,
    ),
    DataRetentionPolicy(
        "reanalysis",
        "sources/calibration",
        ("reanalysis/**",),
        "large gridded/reanalysis source cache and derived sidecars",
        "retain sidecars and latest cache windows; externalize large raw gridded files when manifest-backed",
        "archive raw pressure/gridded files used by trained artifacts",
        "restore or re-download proof required before removing raw NetCDF/GRIB cache",
        "raw gridded files may be re-downloaded when upstream retains the exact vintage; sidecars are rebuildable",
        "externalize raw files with checksums; rebuild sidecars after restore",
        local_delete_allowed=True,
    ),
    DataRetentionPolicy(
        "logs",
        "operations",
        ("logs/**",),
        "local operational logs",
        "rotate after incident review",
        "archive only incident-linked logs",
        "manual owner review required before deletion",
        "routine logs are not evidence unless referenced by an incident report",
        "rotate with operator approval",
        local_delete_allowed=True,
    ),
)


def _format_bytes(value: int | float | None) -> str:
    if value is None:
        return "-"
    size = float(value)
    units = ("B", "KB", "MB", "GB", "TB")
    index = 0
    while abs(size) >= 1024.0 and index < len(units) - 1:
        size /= 1024.0
        index += 1
    return f"{size:.1f} {units[index]}" if index else f"{int(size)} B"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _matches_any(rel_path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(rel_path, pattern) for pattern in patterns)


def classify_data_path(rel_path: str) -> DataRetentionPolicy:
    normalized = rel_path.replace("\\", "/")
    for policy in POLICIES:
        if _matches_any(normalized, policy.patterns):
            return policy
    return DataRetentionPolicy(
        "unclassified",
        "owner-review",
        (),
        "unclassified local data",
        "retain until owner review",
        "none until classified",
        "manual owner review required before deletion",
        "unknown",
        "do not delete until classified",
    )


def _backup_restore_ok(backup_status: dict[str, Any]) -> bool:
    return (
        backup_status.get("status") == "OK"
        and backup_status.get("restore_drill_sla_status") == "OK"
        and int(backup_status.get("missing_critical_files") or 0) == 0
        and int(backup_status.get("missing_critical_bytes") or 0) == 0
    )


def _policy_restore_gate(policy: DataRetentionPolicy, backup_status: dict[str, Any]) -> dict[str, Any]:
    if not policy.deletion_requires_restore:
        return {
            "status": "NOT_REQUIRED",
            "delete_permission": "allowed_by_policy_with_manifest" if policy.local_delete_allowed else "retain",
            "detail": policy.restore_requirement,
        }
    if _backup_restore_ok(backup_status):
        return {
            "status": "PASS",
            "delete_permission": "allowed_only_with_reviewed_manifest",
            "detail": "backup status and restore-drill SLA are OK",
        }
    return {
        "status": "BLOCK",
        "delete_permission": "blocked_until_restore_proof",
        "detail": "missing current OK tape backup status or restore-drill proof",
    }


def _newest_mtime(paths: list[dict[str, Any]]) -> str | None:
    if not paths:
        return None
    return max(row["modified_at_utc"] for row in paths)


def _file_row(path: Path, root: Path, policy: DataRetentionPolicy) -> dict[str, Any]:
    stat = path.stat()
    rel = path.relative_to(root).as_posix()
    return {
        "path": rel,
        "policy": policy.name,
        "owner": policy.owner,
        "bytes": int(stat.st_size),
        "size_human": _format_bytes(stat.st_size),
        "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def build_payload(
    root: str | Path = DEFAULT_DATA_ROOT,
    *,
    backup_status_path: str | Path | None = DEFAULT_BACKUP_STATUS_PATH,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
    top_n: int = DEFAULT_TOP_N,
) -> dict[str, Any]:
    root = Path(root)
    generated_at = datetime.now(timezone.utc)
    cutoff = generated_at - timedelta(hours=float(lookback_hours))
    backup_status = _load_json(backup_status_path)
    usage_path = root if root.exists() else root.parent
    usage = shutil.disk_usage(usage_path)
    policies = {policy.name: policy for policy in POLICIES}
    summaries: dict[str, dict[str, Any]] = {}
    top_dirs: dict[str, dict[str, Any]] = {}
    recent_dirs: dict[str, dict[str, Any]] = {}
    largest_files: list[dict[str, Any]] = []
    recent_files: list[dict[str, Any]] = []
    file_count = 0
    total_bytes = 0

    if root.exists():
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            policy = classify_data_path(rel)
            row = _file_row(path, root, policy)
            file_count += 1
            total_bytes += row["bytes"]
            summary = summaries.setdefault(policy.name, {
                "policy": policy.name,
                "owner": policy.owner,
                "file_count": 0,
                "bytes": 0,
                "size_human": "0 B",
                "largest_file": None,
                "new_file_count": 0,
                "new_bytes": 0,
                "new_size_human": "0 B",
                "newest_modified_at_utc": None,
                "restore_gate": {},
            })
            summary["file_count"] += 1
            summary["bytes"] += row["bytes"]
            if not summary["largest_file"] or row["bytes"] > summary["largest_file"]["bytes"]:
                summary["largest_file"] = row
            modified = datetime.fromtimestamp(stat.st_mtime, timezone.utc)
            if modified >= cutoff:
                summary["new_file_count"] += 1
                summary["new_bytes"] += row["bytes"]
                recent_files.append(row)
                dir_key = rel.split("/", 1)[0]
                recent_dir = recent_dirs.setdefault(dir_key, {"path": dir_key, "file_count": 0, "bytes": 0})
                recent_dir["file_count"] += 1
                recent_dir["bytes"] += row["bytes"]
            dir_key = rel.split("/", 1)[0]
            top_dir = top_dirs.setdefault(dir_key, {"path": dir_key, "file_count": 0, "bytes": 0})
            top_dir["file_count"] += 1
            top_dir["bytes"] += row["bytes"]
            largest_files.append(row)

    for name, summary in summaries.items():
        policy = policies.get(name) or classify_data_path("")
        summary["size_human"] = _format_bytes(summary["bytes"])
        summary["new_size_human"] = _format_bytes(summary["new_bytes"])
        summary["restore_gate"] = _policy_restore_gate(policy, backup_status)
        if summary["largest_file"]:
            summary["newest_modified_at_utc"] = _newest_mtime([summary["largest_file"]])

    largest_files.sort(key=lambda row: row["bytes"], reverse=True)
    recent_files.sort(key=lambda row: row["bytes"], reverse=True)
    largest_dirs = sorted(top_dirs.values(), key=lambda row: row["bytes"], reverse=True)
    new_dirs = sorted(recent_dirs.values(), key=lambda row: row["bytes"], reverse=True)
    for rows in (largest_dirs, new_dirs):
        for row in rows:
            row["size_human"] = _format_bytes(row["bytes"])

    free_shortfall = max(0, int(min_free_bytes) - int(usage.free))
    restore_blocks = [
        row for row in summaries.values()
        if (row.get("restore_gate") or {}).get("status") == "BLOCK"
        and row.get("bytes", 0) > 0
    ]
    status = "PASS"
    if free_shortfall:
        status = "BLOCK"
    elif restore_blocks:
        status = "WARN"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at.isoformat(),
        "status": status,
        "root": str(root),
        "root_exists": root.exists(),
        "lookback_hours": float(lookback_hours),
        "min_free_bytes": int(min_free_bytes),
        "disk": {
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
            "free_human": _format_bytes(usage.free),
            "free_shortfall_bytes": int(free_shortfall),
            "free_shortfall_human": _format_bytes(free_shortfall),
        },
        "backup_status": {
            "path": str(backup_status_path) if backup_status_path else "",
            "status": backup_status.get("status") or "MISSING",
            "restore_drill_sla_status": backup_status.get("restore_drill_sla_status") or "-",
            "restore_ok": _backup_restore_ok(backup_status),
        },
        "summary": {
            "file_count": file_count,
            "total_bytes": total_bytes,
            "total_human": _format_bytes(total_bytes),
            "policy_count": len(summaries),
            "restore_block_count": len(restore_blocks),
            "recent_file_count": len(recent_files),
            "recent_bytes": sum(row["bytes"] for row in recent_files),
            "recent_human": _format_bytes(sum(row["bytes"] for row in recent_files)),
        },
        "policies": [asdict(policy) for policy in POLICIES],
        "policy_summaries": sorted(summaries.values(), key=lambda row: row["bytes"], reverse=True),
        "largest_directories": largest_dirs[: int(top_n)],
        "recent_directories": new_dirs[: int(top_n)],
        "largest_files": largest_files[: int(top_n)],
        "recent_files": recent_files[: int(top_n)],
    }


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    disk = payload.get("disk") or {}
    backup = payload.get("backup_status") or {}
    lines = [
        "# Data Retention Inventory",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Root: `{payload.get('root')}`",
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Files scanned", summary.get("file_count")],
                ["Total size", summary.get("total_human")],
                ["Recent growth window", f"{payload.get('lookback_hours')} hours"],
                ["Recent bytes", summary.get("recent_human")],
                ["Free space", disk.get("free_human")],
                ["Free-space shortfall", disk.get("free_shortfall_human")],
                ["Backup status", backup.get("status")],
                ["Restore drill SLA", backup.get("restore_drill_sla_status")],
                ["Restore OK for deletion gates", backup.get("restore_ok")],
                ["Restore-blocked classes", summary.get("restore_block_count")],
            ],
        ),
        "",
        "## Ownership And Retention",
        "",
        *markdown_table(
            ["Class", "Owner", "Files", "Size", "New bytes", "Restore gate", "Delete permission"],
            [
                [
                    row.get("policy"),
                    row.get("owner"),
                    row.get("file_count"),
                    row.get("size_human"),
                    row.get("new_size_human"),
                    (row.get("restore_gate") or {}).get("status"),
                    (row.get("restore_gate") or {}).get("delete_permission"),
                ]
                for row in payload.get("policy_summaries") or []
            ],
        ),
        "",
        "## Largest Directories",
        "",
        *markdown_table(
            ["Directory", "Files", "Size"],
            [[row.get("path"), row.get("file_count"), row.get("size_human")] for row in payload.get("largest_directories") or []],
        ),
        "",
        "## Recent Growth",
        "",
        *markdown_table(
            ["Directory", "Files", "Size"],
            [[row.get("path"), row.get("file_count"), row.get("size_human")] for row in payload.get("recent_directories") or []],
        ),
        "",
        "## Largest Files",
        "",
        *markdown_table(
            ["Path", "Class", "Size", "Modified"],
            [
                [row.get("path"), row.get("policy"), row.get("size_human"), row.get("modified_at_utc")]
                for row in payload.get("largest_files") or []
            ],
        ),
        "",
        "## Operator Procedure",
        "",
        "Deletion is blocked for restore-required classes until backup status and restore-drill SLA are OK. Use the generated class table to pick the owning procedure, then create a reviewed cleanup manifest before removing local files. Prefer tiering or externalization for large historical JSONL/CSV evidence.",
        "",
    ]
    return "\n".join(lines)


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory data ownership, retention policy, and disk growth.")
    parser.add_argument("--root", default=str(DEFAULT_DATA_ROOT))
    parser.add_argument("--backup-status", default=str(DEFAULT_BACKUP_STATUS_PATH))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--lookback-hours", type=float, default=DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    args = parser.parse_args(argv)
    payload = build_payload(
        args.root,
        backup_status_path=args.backup_status,
        min_free_bytes=args.min_free_bytes,
        lookback_hours=args.lookback_hours,
        top_n=args.top_n,
    )
    out = write_json(args.out, payload)
    report = write_report(args.report, payload)
    print(f"Data retention inventory: {payload['status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")
    return 0 if payload["status"] in {"PASS", "WARN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
