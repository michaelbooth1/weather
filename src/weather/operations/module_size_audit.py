"""Audit large Python modules and document ownership boundaries."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import REPO_ROOT, data_path, relative_to_repo
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("module_size_audit")
DEFAULT_SOURCE_ROOT = REPO_ROOT / "src" / "weather"
DEFAULT_OUT = data_path() / "backtest" / "module_size_audit.json"
DEFAULT_REPORT = data_path() / "backtest" / "module_size_audit_report.md"
DEFAULT_WARNING_LINES = 2_000

OWNERSHIP_NOTES = {
    "src/weather/calibration/pooled_feature_model.py": {
        "owner": "calibration",
        "boundary": "Compatibility facade for pooled feature model implementation slices.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/market/taker_bot.py": {
        "owner": "market",
        "boundary": "Compatibility facade for taker strategy, risk, tape, scoring, bakeoff, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/reporting/promotion_refresh.py": {
        "owner": "reporting",
        "boundary": "Compatibility facade for promotion readers, decisions, gap analysis, reports, orchestration, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/reporting/fleet/fleet_observability.py": {
        "owner": "reporting",
        "boundary": "Compatibility facade for fleet inventory, loop health, SLO gates, payload, rendering, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/reporting/hourly_model_performance.py": {
        "owner": "reporting",
        "boundary": "Compatibility facade for hourly scoring, slots, gates, context, rendering, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/operations/daily_refresh.py": {
        "owner": "operations",
        "boundary": "Compatibility facade for daily refresh orchestration, lock/preflight, reporting, and CLI owner modules.",
        "next_split": "Complete for item 205; keep scheduled command and public imports stable while owner modules settle.",
    },
    "src/weather/operations/daily_refresh_locks.py": {
        "owner": "operations",
        "boundary": "Daily refresh lock, stale-state repair, and disk-preflight helpers.",
        "next_split": "Owner module for item 205; must not import the daily_refresh facade.",
    },
    "src/weather/operations/daily_refresh_steps.py": {
        "owner": "operations",
        "boundary": "Daily refresh step adapter compatibility surface.",
        "next_split": "Item 318 slice complete; registry, settled-day barrier, and status aggregation live in owner modules.",
    },
    "src/weather/operations/daily_refresh_registry.py": {
        "owner": "operations",
        "boundary": "Daily refresh step order, planned-step rows, and resume filtering.",
        "next_split": "Owner module for item 318; must not import the daily_refresh facade or step adapters.",
    },
    "src/weather/operations/daily_refresh_settled_day.py": {
        "owner": "operations",
        "boundary": "Settled-day analysis barrier dependency graph, freshness countability, and exception contract.",
        "next_split": "Owner module for item 318; must not import the daily_refresh facade or step adapters.",
    },
    "src/weather/operations/daily_refresh_status.py": {
        "owner": "operations",
        "boundary": "Daily refresh step execution rows, rollup freshness, pipeline summary, and variant-learning gate.",
        "next_split": "Owner module for item 318; must not import the daily_refresh facade or step adapters.",
    },
    "src/weather/operations/daily_refresh_report.py": {
        "owner": "operations",
        "boundary": "Daily refresh status Markdown rendering and report file writing.",
        "next_split": "Owner module for item 205; must not import the daily_refresh facade.",
    },
    "src/weather/operations/daily_refresh_cli.py": {
        "owner": "operations",
        "boundary": "Daily refresh CLI parser and command handlers with facade-injected dependencies.",
        "next_split": "Owner module for item 205; must not import the daily_refresh facade.",
    },
    "src/weather/operations/tape_backup.py": {
        "owner": "operations",
        "boundary": "Tape manifest/status, retention/pruning, restore drill, and CLI orchestration.",
        "next_split": "Item 318 warning module; split manifest/status first, then retention/pruning and restore drill helpers.",
    },
    "src/weather/reporting/daily/daily_learning.py": {
        "owner": "reporting",
        "boundary": "Daily learning readers, synthesis, retrain recommendations, report rendering, and CLI wiring.",
        "next_split": "Item 318 warning module; split readers, synthesis/decision model, report rendering, and CLI wiring.",
    },
    "src/weather/market/mm_paper.py": {
        "owner": "market",
        "boundary": "Market-making paper tape ingestion, accounting/scoring, report rendering, evidence export, and CLI.",
        "next_split": "Item 318 warning module; split tape ingestion and accounting/scoring before report/evidence export.",
    },
    "src/weather/schema_registry.py": {
        "owner": "shared",
        "boundary": "Schema registry data, audit/check logic, and CLI rendering.",
        "next_split": "Item 318 warning module; defer until active 314/316/317 edits settle, then split registry data from audit/check behavior.",
    },
    "src/weather/collection/snapshot_store.py": {
        "owner": "collection",
        "boundary": "Snapshot schema constants, readers, writers, sidecar backfill/migration helpers, and repair CLI behavior.",
        "next_split": "Item 318 warning module; split schema constants/readers before writers and repair helpers.",
    },
    "src/weather/market/taker_bot_bakeoff.py": {
        "owner": "market",
        "boundary": "Taker bakeoff artifact readers, scoring, profitability verification, report rendering, and CLI.",
        "next_split": "Item 318 warning module; split artifact readers and scoring before report rendering.",
    },
    "src/weather/reporting/source_family_inventory.py": {
        "owner": "reporting",
        "boundary": "Source-family input readers, family/gate classification, report rendering, and CLI.",
        "next_split": "Item 318 warning module; split input readers and classification before report rendering.",
    },
}


def count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for _line in handle)
    except UnicodeDecodeError:
        return 0


def module_owner(path: Path) -> str:
    try:
        relative = path.relative_to(REPO_ROOT / "src" / "weather")
    except ValueError:
        return "unknown"
    return relative.parts[0] if len(relative.parts) > 1 else "shared"


def build_module_size_audit(
    source_root: str | Path = DEFAULT_SOURCE_ROOT,
    *,
    warning_lines: int = DEFAULT_WARNING_LINES,
    generated_at_utc: str | None = None,
) -> dict:
    source_root = Path(source_root)
    rows = []
    for path in sorted(source_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = relative_to_repo(path)
        lines = count_lines(path)
        note = OWNERSHIP_NOTES.get(rel, {})
        rows.append({
            "path": rel,
            "owner": note.get("owner") or module_owner(path),
            "lines": lines,
            "status": "WARN" if lines >= warning_lines else "OK",
            "boundary": note.get("boundary"),
            "next_split": note.get("next_split"),
        })
    over_threshold = [row for row in rows if row["status"] == "WARN"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "source_root": relative_to_repo(source_root),
        "warning_lines": int(warning_lines),
        "module_count": len(rows),
        "warning_count": len(over_threshold),
        "largest_modules": sorted(rows, key=lambda row: row["lines"], reverse=True)[:25],
        "ownership_map": [
            {"path": path, **note}
            for path, note in sorted(OWNERSHIP_NOTES.items())
        ],
    }


def write_json(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_report(payload: dict) -> str:
    lines = [
        "# Module Size Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Warning threshold: `{payload.get('warning_lines')}` lines",
        f"Warnings: `{payload.get('warning_count')}`",
        "",
        "## Largest Modules",
        "",
        "| Module | Owner | Lines | Status | Boundary | Next split |",
        "| :--- | :--- | ---: | :--- | :--- | :--- |",
    ]
    for row in payload.get("largest_modules") or []:
        lines.append(
            "| {path} | {owner} | {lines} | {status} | {boundary} | {next_split} |".format(
                path=row.get("path"),
                owner=row.get("owner"),
                lines=row.get("lines"),
                status=row.get("status"),
                boundary=row.get("boundary") or "-",
                next_split=row.get("next_split") or "-",
            )
        )
    lines.extend([
        "",
        "## Ownership Map",
        "",
        "| Module | Owner | Boundary | Next split |",
        "| :--- | :--- | :--- | :--- |",
    ])
    for row in payload.get("ownership_map") or []:
        lines.append(
            "| {path} | {owner} | {boundary} | {next_split} |".format(
                path=row.get("path"),
                owner=row.get("owner"),
                boundary=row.get("boundary"),
                next_split=row.get("next_split"),
            )
        )
    return "\n".join(lines) + "\n"


def write_report(path: str | Path, payload: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit Python module sizes and ownership split targets.")
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    parser.add_argument("--warning-lines", type=int, default=DEFAULT_WARNING_LINES)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)

    payload = build_module_size_audit(args.source_root, warning_lines=args.warning_lines)
    write_json(args.out, payload)
    write_report(args.report, payload)
    print(
        "Module size audit: modules={module_count} warnings={warning_count} threshold={warning_lines}".format(
            **payload
        )
    )
    return payload


if __name__ == "__main__":
    main()
