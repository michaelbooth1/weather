"""Canonical active-variant shadow refresh.

This module builds the scheduled active-variant shadow artifact consumed by
daily evidence-growth reporting. It deliberately fails closed when active
registry variants are absent instead of falling back to stale item-specific
bakeoff exports.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import config_path, data_path
from weather.reporting.formatting import markdown_table
from weather.reporting.multi_variant_shadow import (
    build_payload as build_multi_variant_payload,
    read_prediction_rows,
    write_attribution_sidecar,
    write_json as write_multi_variant_json,
    write_long_csv,
)
from weather.reporting.variant_registry import (
    active_export_paths,
    active_registry_variants,
    audit_registry,
    load_registry,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("active_variant_shadow_refresh")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_REGISTRY_PATH = config_path("model_variant_registry.json")
DEFAULT_LONG_OUT = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_long.csv"
DEFAULT_ATTRIBUTION_SIDECAR_OUT = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_attribution.jsonl"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "active_variant_shadow.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_report.md"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_rows(paths: list[str | Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    existing = []
    missing = []
    for value in paths:
        path = Path(value)
        if path.exists():
            stat = path.stat()
            existing.append({
                "path": str(path),
                "exists": True,
                "bytes": stat.st_size,
                "modified_at_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
        else:
            missing.append({"path": str(path), "exists": False})
    rows = read_prediction_rows([row["path"] for row in existing]) if existing else []
    return rows, existing + missing


def _filter_active_or_control_rows(
    rows: list[dict[str, Any]],
    active_ids: set[str],
) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        variant_id = str(row.get("variant_id") or "")
        is_control = str(row.get("is_control") or "").strip().lower() in {"1", "true", "yes", "y"}
        if variant_id in active_ids or is_control:
            selected.append(row)
    return selected


def build_payload(
    prediction_paths: list[str | Path] | tuple[str | Path, ...] | None,
    *,
    registry_path: str | Path = DEFAULT_REGISTRY_PATH,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    registry = load_registry(registry_path)
    if not prediction_paths:
        prediction_paths = active_export_paths(registry)
    contract_audit = audit_registry(registry, evidence_paths=[str(path) for path in (prediction_paths or [])])
    active_variants = active_registry_variants(registry)
    active_ids = {str(row.get("variant_id")) for row in active_variants if row.get("variant_id")}
    raw_rows, source_paths = _path_rows([str(path) for path in (prediction_paths or [])])
    selected_rows = _filter_active_or_control_rows(raw_rows, active_ids)
    multi_variant = build_multi_variant_payload(
        selected_rows,
        variant_registry=registry,
        dedupe_shared_controls=True,
        duplicate_observation_policy="warn",
    )
    reported_ids = {
        str(row.get("variant_id"))
        for row in multi_variant.get("rows") or []
        if row.get("variant_id") and not row.get("is_control")
    }
    missing_active_ids = sorted(active_ids - reported_ids)
    status = "OK"
    blockers = []
    if not prediction_paths:
        status = "BLOCK"
        blockers.append("no active-variant export paths configured in registry")
    if contract_audit.get("status") == "ERROR":
        status = "BLOCK"
        blockers.append("active registry export contract audit failed")
    if not selected_rows:
        status = "BLOCK"
        blockers.append("no active registry variant rows were found in source paths")
    if missing_active_ids:
        status = "BLOCK"
        blockers.append("active registry variants missing from canonical shadow output")
    if multi_variant.get("status") == "ERROR":
        status = "ERROR"
        blockers.append("multi-variant shadow scorer reported errors")
    elif status == "OK" and multi_variant.get("status") == "WARN":
        status = "WARN"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "status": status,
        "blockers": blockers,
        "source_paths": source_paths,
        "registry": {
            "path": registry.get("path"),
            "exists": registry.get("exists"),
            "contract_status": contract_audit.get("status"),
            "active_variant_count": len(active_variants),
            "active_variant_ids": sorted(active_ids),
            "reported_active_variant_ids": sorted(reported_ids),
            "missing_active_variant_ids": missing_active_ids,
        },
        "contract_audit": contract_audit,
        "summary": {
            "source_path_count": len(source_paths),
            "raw_rows": len(raw_rows),
            "selected_rows": len(selected_rows),
            "canonical_rows": len(multi_variant.get("rows") or []),
            "missing_active_variant_count": len(missing_active_ids),
            "multi_variant_status": multi_variant.get("status"),
            "unique_observation_count": (multi_variant.get("summary") or {}).get("unique_observation_count", 0),
            "market_day_count": (multi_variant.get("summary") or {}).get("market_day_count", 0),
            "deduplicated_rows": (multi_variant.get("summary") or {}).get("deduplicated_rows", 0),
        },
        "multi_variant_shadow": multi_variant,
    }


def write_json(path: str | Path, payload: dict[str, Any], *, include_rows: bool = False) -> Path:
    copy = dict(payload)
    multi = dict(copy.get("multi_variant_shadow") or {})
    if not include_rows:
        multi.pop("rows", None)
    copy["multi_variant_shadow"] = multi
    return write_multi_variant_json(path, copy, include_rows=True)


def write_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    registry = payload.get("registry") or {}
    summary = payload.get("summary") or {}
    lines = [
        "# Active Variant Shadow Refresh",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        "",
        "## Summary",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Source paths", summary.get("source_path_count")],
                ["Raw rows", summary.get("raw_rows")],
                ["Selected rows", summary.get("selected_rows")],
                ["Canonical rows", summary.get("canonical_rows")],
                ["Unique observations", summary.get("unique_observation_count")],
                ["Market-days", summary.get("market_day_count")],
                ["Deduplicated rows", summary.get("deduplicated_rows")],
                ["Missing active variants", summary.get("missing_active_variant_count")],
            ],
        ),
        "",
        "## Active Registry Coverage",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Registry", registry.get("path")],
                ["Contract audit", registry.get("contract_status")],
                ["Active variants", ", ".join(registry.get("active_variant_ids") or []) or "-"],
                ["Reported active variants", ", ".join(registry.get("reported_active_variant_ids") or []) or "-"],
                ["Missing active variants", ", ".join(registry.get("missing_active_variant_ids") or []) or "-"],
            ],
        ),
        "",
        "## Blockers",
        "",
    ]
    blockers = payload.get("blockers") or []
    lines.extend([f"- {blocker}" for blocker in blockers] or ["- none"])
    lines.extend(["", "## Source Paths", ""])
    lines.extend(markdown_table(
        ["Path", "Exists", "Bytes", "Modified UTC"],
        [
            [
                row.get("path"),
                row.get("exists"),
                row.get("bytes"),
                row.get("modified_at_utc"),
            ]
            for row in payload.get("source_paths") or []
        ],
    ))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_outputs(
    payload: dict[str, Any],
    *,
    long_out: str | Path = DEFAULT_LONG_OUT,
    attribution_sidecar_out: str | Path = DEFAULT_ATTRIBUTION_SIDECAR_OUT,
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
) -> tuple[Path, Path, Path, Path]:
    rows = (payload.get("multi_variant_shadow") or {}).get("rows") or []
    long_path = write_long_csv(long_out, rows)
    sidecar_path = write_attribution_sidecar(attribution_sidecar_out, rows)
    json_path = write_json(json_out, payload, include_rows=False)
    report_path = write_report(report_out, payload)
    return long_path, sidecar_path, json_path, report_path


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Build canonical active-variant shadow refresh artifacts.")
    parser.add_argument("predictions", nargs="*", help="Current active variant shadow row CSV/JSON/JSONL paths.")
    parser.add_argument("--variant-registry", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--long-out", default=str(DEFAULT_LONG_OUT))
    parser.add_argument("--attribution-sidecar-out", default=str(DEFAULT_ATTRIBUTION_SIDECAR_OUT))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)

    payload = build_payload(args.predictions, registry_path=args.variant_registry)
    long_path, sidecar_path, json_path, report_path = write_outputs(
        payload,
        long_out=args.long_out,
        attribution_sidecar_out=args.attribution_sidecar_out,
        json_out=args.json_out,
        report_out=args.report_out,
    )
    print(f"Active variant shadow refresh: {payload['status']}")
    print(f"Long table written to {long_path}")
    print(f"Attribution sidecar written to {sidecar_path}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return payload


if __name__ == "__main__":
    main()
