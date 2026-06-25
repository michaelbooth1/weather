"""Local retention report for generated backtest artifacts."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.operations.cleanup_preflight import build_cleanup_preflight, cleanup_manifest_for_paths
from weather.paths import data_path
from weather.reporting.formatting import markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("backtest_artifact_retention")
CLEANUP_SCHEMA_VERSION = schema_version("backtest_artifact_cleanup")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "backtest_artifact_retention.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "backtest_artifact_retention_report.md"
DEFAULT_CLEANUP_MANIFEST = DEFAULT_BACKTEST_ROOT / "backtest_artifact_cleanup_manifest.json"
DEFAULT_MIN_FREE_BYTES = 1_000_000_000
DEFAULT_LARGE_FILE_BYTES = 25_000_000
DEFAULT_POOLED_VARIANT_EXPORT_STEMS = {
    "source_state_ablation_shadow_variants",
    "clob_overlay_shadow_variants",
    "conservative_bridge_shadow_variants",
}


def _format_bytes(value: int | float | None) -> str:
    if value is None:
        return "-"
    value = float(value)
    units = ("B", "KB", "MB", "GB", "TB")
    idx = 0
    while abs(value) >= 1024.0 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return f"{value:.1f} {units[idx]}" if idx else f"{int(value)} B"


def classify_artifact(path: Path, root: Path, large_file_bytes: int = DEFAULT_LARGE_FILE_BYTES) -> dict[str, Any]:
    stat = path.stat()
    name = path.name.lower()
    suffix = path.suffix.lower()
    size = int(stat.st_size)
    relative_path = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    is_large = size >= int(large_file_bytes)

    category = "other"
    retention_action = "retain"
    reason = "unclassified artifact; retain until an owner reviews it"

    if suffix == ".pkl":
        category = "model_artifact"
        retention_action = "retain_or_externalize"
        reason = "model artifact; keep local or move under the model artifact storage policy"
    elif suffix in {".md", ".txt"} or "report" in name:
        category = "evidence_report"
        retention_action = "retain"
        reason = "human-readable evidence or report"
    elif any(token in name for token in ("manifest", "corpus", "inventory", "registry", "trust")):
        category = "manifest_or_index"
        retention_action = "retain"
        reason = "manifest/index input needed to reproduce evidence"
    elif suffix == ".csv" and any(token in name for token in ("variant", "shadow", "multi_variant")):
        category = "generated_row_export"
        retention_action = "review_delete_rebuildable"
        reason = "large row-level replay/shadow export; usually rebuildable from retained corpus and artifact"
    elif suffix == ".csv" and "source_state_ablation" in name:
        category = "generated_row_export"
        retention_action = "review_delete_rebuildable"
        reason = "large source-state ablation row export; rebuildable from retained replay artifact and report"
    elif suffix == ".json" and any(token in name for token in ("multi_variant_shadow", "shadow_variants", "bridge_multi_variant")):
        category = "generated_shadow_payload"
        retention_action = "review_delete_rebuildable"
        reason = "large generated shadow payload; retain paired report/manifests before deleting"
    elif suffix == ".json" and is_large:
        category = "large_json_payload"
        retention_action = "review_before_retaining"
        reason = "large JSON artifact needs owner classification"
    elif suffix == ".csv" and is_large:
        category = "large_csv_payload"
        retention_action = "review_before_retaining"
        reason = "large CSV artifact needs owner classification"

    return {
        "path": relative_path,
        "name": path.name,
        "suffix": suffix,
        "size_bytes": size,
        "size_human": _format_bytes(size),
        "last_modified_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        "category": category,
        "retention_action": retention_action,
        "safe_delete_candidate": retention_action == "review_delete_rebuildable",
        "reason": reason,
    }


def _existing_evidence(root: Path, names: list[str]) -> list[str]:
    evidence = []
    for name in names:
        path = root / name
        if path.exists() and path.is_file():
            evidence.append(str(path.relative_to(root)))
    return evidence


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    output = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _stem_tokens(stem: str) -> set[str]:
    ignored = {
        "rows",
        "row",
        "variant",
        "variants",
        "export",
        "shadow",
        "long",
        "full",
        "all",
        "direct",
        "band",
    }
    return {
        token
        for token in stem.lower().replace("-", "_").split("_")
        if len(token) > 1 and token not in ignored
    }


def token_matched_variant_export_evidence(root: Path, base_stem: str) -> list[str]:
    """Find renamed variant-export evidence for a rebuildable row export.

    Some diagnostics write compact row-export names while the paired export
    report keeps the full artifact stem. Require at least three shared
    significant tokens and both JSON/report files to keep this conservative.
    """
    tokens = _stem_tokens(base_stem)
    if len(tokens) < 3:
        return []
    evidence = []
    for export_json in sorted(root.glob("*variant_export.json")):
        candidate_tokens = _stem_tokens(export_json.stem)
        if not tokens.issubset(candidate_tokens):
            continue
        report = export_json.with_name(f"{export_json.stem}_report.md")
        if not report.exists() or not report.is_file():
            continue
        evidence.extend([
            str(export_json.relative_to(root)),
            str(report.relative_to(root)),
        ])
    return evidence


def reports_referencing_artifact(root: Path, artifact_name: str) -> list[str]:
    """Return retained Markdown reports that explicitly name an artifact file."""
    if not artifact_name:
        return []
    matches = []
    for report in sorted(root.glob("*.md")):
        if report.name.startswith("backtest_artifact_retention"):
            continue
        if report.name.startswith("backtest_artifact_cleanup"):
            continue
        try:
            text = report.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if artifact_name in text:
            matches.append(str(report.relative_to(root)))
    return matches


def paired_evidence_for_cleanup(row: dict[str, Any], root: str | Path) -> list[str]:
    """Return retained reports/manifests that make a rebuildable artifact deletable."""
    root = Path(root)
    path = Path(str(row.get("path") or ""))
    stem = path.stem
    suffix = path.suffix.lower()
    names: list[str] = []

    if row.get("category") == "generated_shadow_payload" and suffix == ".json":
        names.extend([f"{stem}_report.md", f"{stem}_manifest.json"])
    if row.get("category") == "generated_row_export" and suffix == ".csv":
        if stem.endswith("_long"):
            base = stem[:-5]
            names.extend([f"{base}.json", f"{base}_report.md"])
        if stem.endswith("_variant_rows"):
            base = stem[: -len("_variant_rows")]
            names.extend([f"{base}_variant_export.json", f"{base}_variant_export_report.md"])
        if stem.endswith("_shadow_variants"):
            base = stem[: -len("_shadow_variants")]
            names.extend([f"{base}_report.md", f"{base}.json"])
        if stem in DEFAULT_POOLED_VARIANT_EXPORT_STEMS:
            names.extend([
                "pooled_candidate_replay_report.md",
                "pooled_candidate_replay_latest_report.md",
                "promotion_corpus.json",
            ])

    evidence = _existing_evidence(root, names)
    if row.get("category") == "generated_row_export" and stem.endswith("_variant_rows"):
        base = stem[: -len("_variant_rows")]
        evidence.extend(token_matched_variant_export_evidence(root, base))
    if row.get("category") in {"generated_row_export", "generated_shadow_payload"}:
        evidence.extend(reports_referencing_artifact(root, path.name))
    return _dedupe(evidence)


def build_payload(
    root: str | Path = DEFAULT_BACKTEST_ROOT,
    min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    large_file_bytes: int = DEFAULT_LARGE_FILE_BYTES,
    top_n: int = 40,
) -> dict[str, Any]:
    root = Path(root)
    files = []
    if root.exists():
        files = [path for path in root.rglob("*") if path.is_file()]
    rows = [
        classify_artifact(path, root=root, large_file_bytes=large_file_bytes)
        for path in files
    ]
    rows.sort(key=lambda row: row["size_bytes"], reverse=True)

    usage = shutil.disk_usage(root if root.exists() else root.parent)
    total_size = sum(row["size_bytes"] for row in rows)
    cleanup_candidates = [
        row for row in rows
        if row["safe_delete_candidate"] and row["size_bytes"] >= int(large_file_bytes)
    ]
    review_candidates = [
        row for row in rows
        if row["retention_action"].startswith("review") and row["size_bytes"] >= int(large_file_bytes)
    ]
    free_shortfall = max(0, int(min_free_bytes) - int(usage.free))
    status = "PASS" if free_shortfall == 0 else "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "status": status,
        "min_free_bytes": int(min_free_bytes),
        "large_file_bytes": int(large_file_bytes),
        "disk": {
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
            "free_human": _format_bytes(usage.free),
            "free_shortfall_bytes": free_shortfall,
            "free_shortfall_human": _format_bytes(free_shortfall),
        },
        "summary": {
            "file_count": len(rows),
            "total_artifact_bytes": total_size,
            "total_artifact_human": _format_bytes(total_size),
            "cleanup_candidate_count": len(cleanup_candidates),
            "cleanup_candidate_bytes": sum(row["size_bytes"] for row in cleanup_candidates),
            "cleanup_candidate_human": _format_bytes(sum(row["size_bytes"] for row in cleanup_candidates)),
            "review_candidate_count": len(review_candidates),
            "review_candidate_bytes": sum(row["size_bytes"] for row in review_candidates),
            "review_candidate_human": _format_bytes(sum(row["size_bytes"] for row in review_candidates)),
        },
        "largest_files": rows[: int(top_n)],
        "cleanup_candidates": cleanup_candidates[: int(top_n)],
        "review_candidates": review_candidates[: int(top_n)],
    }


def build_cleanup_manifest(
    payload: dict[str, Any],
    root: str | Path = DEFAULT_BACKTEST_ROOT,
    target_bytes: int = 0,
) -> dict[str, Any]:
    root = Path(root)
    selected = []
    skipped = []
    selected_bytes = 0
    for row in payload.get("cleanup_candidates") or []:
        evidence = paired_evidence_for_cleanup(row, root)
        if not evidence:
            skipped.append({
                "path": row.get("path"),
                "size_bytes": row.get("size_bytes"),
                "size_human": row.get("size_human"),
                "reason": "no paired report/manifest matched conservative cleanup rules",
            })
            continue
        selected.append({
            "path": row.get("path"),
            "size_bytes": int(row.get("size_bytes") or 0),
            "size_human": row.get("size_human"),
            "category": row.get("category"),
            "retention_action": row.get("retention_action"),
            "paired_evidence": evidence,
            "action": "delete_rebuildable_generated_artifact",
            "status": "PLANNED",
        })
        selected_bytes += int(row.get("size_bytes") or 0)
        if target_bytes and selected_bytes >= int(target_bytes):
            break
    operator_review = {
        "approved": True,
        "approved_by": "weather.reporting.data_quality.backtest_artifact_retention",
        "approved_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Projection-only generated-artifact cleanup; paired evidence is retained by conservative manifest rules.",
    }
    preflight_shape = cleanup_manifest_for_paths(
        [root / str(row.get("path")) for row in selected],
        root=root,
        classification_prefix="backtest",
        deletion_reason="delete rebuildable generated backtest projection after paired evidence is retained",
        operator_review=operator_review,
        backup_status={},
    )
    candidates_by_path = {
        row.get("path"): row
        for row in preflight_shape.get("candidates") or []
    }
    for row in selected:
        row.update(candidates_by_path.get(row.get("path")) or {})

    return {
        "schema_version": preflight_shape["schema_version"],
        "legacy_schema_version": CLEANUP_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "operator_review": operator_review,
        "target_bytes": int(target_bytes),
        "status": "READY" if selected else "NO_ELIGIBLE_ARTIFACTS",
        "apply_required": True,
        "selected_count": len(selected),
        "selected_bytes": selected_bytes,
        "selected_human": _format_bytes(selected_bytes),
        "selected": selected,
        "candidates": selected,
        "skipped": skipped,
    }


def apply_cleanup_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    root = Path(manifest["root"]).resolve()
    preflight = build_cleanup_preflight(manifest, root=root, backup_status={})
    manifest["cleanup_preflight"] = preflight
    if preflight.get("status") != "PASS":
        manifest["applied_at_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["status"] = "BLOCKED_BY_CLEANUP_PREFLIGHT"
        manifest["deleted_count"] = 0
        manifest["deleted_bytes"] = 0
        manifest["deleted_human"] = _format_bytes(0)
        return manifest
    deleted_bytes = 0
    deleted_count = 0
    for row in manifest.get("selected") or []:
        relative = Path(str(row.get("path") or ""))
        if relative.is_absolute():
            raise ValueError(f"cleanup path must be relative: {relative}")
        path = (root / relative).resolve()
        path.relative_to(root)
        evidence = [root / item for item in row.get("paired_evidence") or []]
        if not evidence or not any(item.exists() and item.is_file() for item in evidence):
            row["status"] = "SKIPPED_MISSING_EVIDENCE"
            continue
        if not path.exists():
            row["status"] = "SKIPPED_MISSING_ARTIFACT"
            continue
        size = int(path.stat().st_size)
        path.unlink()
        row["status"] = "DELETED"
        row["deleted_bytes"] = size
        row["deleted_human"] = _format_bytes(size)
        deleted_count += 1
        deleted_bytes += size
    manifest["applied_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["status"] = "APPLIED"
    manifest["deleted_count"] = deleted_count
    manifest["deleted_bytes"] = deleted_bytes
    manifest["deleted_human"] = _format_bytes(deleted_bytes)
    return manifest


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_report(payload: dict[str, Any]) -> str:
    disk = payload.get("disk") or {}
    summary = payload.get("summary") or {}
    lines = [
        "# Backtest Artifact Retention Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", payload.get("status")],
            ["Root", payload.get("root")],
            ["Free space", disk.get("free_human")],
            ["Free-space shortfall", disk.get("free_shortfall_human")],
            ["Backtest artifact size", summary.get("total_artifact_human")],
            ["Files scanned", summary.get("file_count")],
            ["Cleanup candidates", f"{summary.get('cleanup_candidate_count')} / {summary.get('cleanup_candidate_human')}"],
            ["Review candidates", f"{summary.get('review_candidate_count')} / {summary.get('review_candidate_human')}"],
        ],
    )
    lines += [
        "",
        "## Largest Files",
        "",
    ]
    lines += markdown_table(
        ["Path", "Size", "Action", "Reason"],
        [
            [
                row.get("path"),
                row.get("size_human"),
                row.get("retention_action"),
                row.get("reason"),
            ]
            for row in payload.get("largest_files") or []
        ],
    )
    lines += [
        "",
        "## Rebuildable Cleanup Candidates",
        "",
    ]
    lines += markdown_table(
        ["Path", "Size", "Reason"],
        [
            [
                row.get("path"),
                row.get("size_human"),
                row.get("reason"),
            ]
            for row in payload.get("cleanup_candidates") or []
        ],
    )
    lines += [
        "",
        "Deletion is not automatic. Delete only after confirming the paired report, corpus, and model artifact are retained or externally archived.",
        "",
    ]
    return "\n".join(lines)


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Report local backtest artifact disk pressure and cleanup candidates.")
    parser.add_argument("--root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--min-free-bytes", type=int, default=DEFAULT_MIN_FREE_BYTES)
    parser.add_argument("--large-file-bytes", type=int, default=DEFAULT_LARGE_FILE_BYTES)
    parser.add_argument("--top-n", type=int, default=40)
    parser.add_argument("--cleanup-manifest", default="")
    parser.add_argument("--cleanup-target-bytes", type=int, default=0)
    parser.add_argument("--apply-cleanup", action="store_true")
    args = parser.parse_args(argv)
    payload = build_payload(
        root=args.root,
        min_free_bytes=args.min_free_bytes,
        large_file_bytes=args.large_file_bytes,
        top_n=args.top_n,
    )
    cleanup_path = Path(args.cleanup_manifest) if args.cleanup_manifest else None
    if cleanup_path:
        cleanup = build_cleanup_manifest(
            payload,
            root=args.root,
            target_bytes=args.cleanup_target_bytes,
        )
        if args.apply_cleanup:
            cleanup = apply_cleanup_manifest(cleanup)
            payload = build_payload(
                root=args.root,
                min_free_bytes=args.min_free_bytes,
                large_file_bytes=args.large_file_bytes,
                top_n=args.top_n,
            )
        write_json(cleanup_path, cleanup)
    out = write_json(args.out, payload)
    report = write_report(args.report, payload)
    print(f"Backtest artifact retention: {payload['status']}")
    print(f"JSON written to {out}")
    print(f"Report written to {report}")
    if cleanup_path:
        print(f"Cleanup manifest written to {cleanup_path}")


if __name__ == "__main__":
    main()
