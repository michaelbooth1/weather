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
        "boundary": "Compatibility facade that re-exports daily refresh registry, settled-day, status, and step-family adapters for existing callers.",
        "next_split": "Item 318 step-family split complete; keep facade stable and add new adapters in source, trading, or reporting family modules.",
    },
    "src/weather/operations/daily_refresh_source_steps.py": {
        "owner": "operations",
        "boundary": "Source-refresh, ingest quality, event metadata, settlement restore, and market-day label finalization step adapters.",
        "next_split": "Owner module for item 318; must not import the daily_refresh facade.",
    },
    "src/weather/operations/daily_refresh_trading_steps.py": {
        "owner": "operations",
        "boundary": "Exchange economics, taker/maker evidence, CLOB tiering, replay status, and closed-day archive step adapters.",
        "next_split": "Owner module for item 318; must not import the daily_refresh facade.",
    },
    "src/weather/operations/daily_refresh_reporting_steps.py": {
        "owner": "operations",
        "boundary": "Promotion, scorecard, lifecycle, observability, retention, snapshot evaluation, root-cause, daily learning, and daily flow step adapters.",
        "next_split": "Owner module for item 318; must not import the daily_refresh facade.",
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
        "boundary": "Compatibility facade for export, restore drill, backup-job, status-report, and CLI behavior.",
        "next_split": "Item 318 slice complete; manifest/status, dedup repository, and unmanifested cleanup helpers live in owner modules.",
    },
    "src/weather/operations/tape_backup_manifest.py": {
        "owner": "operations",
        "boundary": "Tape retention policy, manifest building, capacity checks, manifest validation, restore-drill SLA, backup status, and alert helpers.",
        "next_split": "Owner module for item 318; must not import the tape_backup facade.",
    },
    "src/weather/operations/tape_backup_dedup.py": {
        "owner": "operations",
        "boundary": "Deduplicated repository preflight, restic command execution, repository status, backup, restore drill, and dedup backup job helpers.",
        "next_split": "Owner module for item 318; must not import the tape_backup facade.",
    },
    "src/weather/operations/tape_backup_cleanup.py": {
        "owner": "operations",
        "boundary": "Unmanifested backup cleanup planning, durable restore proof verification, cleanup apply gates, and cleanup report rendering.",
        "next_split": "Owner module for item 318; must not import the tape_backup facade.",
    },
    "src/weather/reporting/daily/daily_learning.py": {
        "owner": "reporting",
        "boundary": "Daily learning synthesis, retrain recommendations, output writing, CLI wiring, and compatibility exports for scorecard helpers.",
        "next_split": "WARN in the 2026-07-03 audit; input readers, gates, experiment queues, and scorecard assembly already live in daily_learning_scorecard, so the next slice should move learning-lane builders, promotion-confidence helpers, or retrain-plan assembly behind another daily-learning owner module.",
    },
    "src/weather/reporting/daily/daily_learning_scorecard.py": {
        "owner": "reporting",
        "boundary": "Daily-learning artifact readers, input freshness/coverage/consistency gates, experiment queue item builders, label countability, calibration monitoring, and scorecard assembly.",
        "next_split": "Owner module for item 318; must not import the daily_learning facade.",
    },
    "src/weather/market/mm_paper.py": {
        "owner": "market",
        "boundary": "Market-making paper orchestration, report/evidence export, model-variant promotion summaries, and compatibility exports for scoring helpers.",
        "next_split": "WARN in the 2026-07-03 audit; tape ingestion, conservative fill accounting, queue simulation, and P&L scoring already live in mm_paper_scoring, so the next slice should move reward diagnostics, model-variant promotion gates, or fill-evidence completeness helpers out of the orchestration facade.",
    },
    "src/weather/market/mm_paper_scoring.py": {
        "owner": "market",
        "boundary": "Active-day paper score freshness, quote/trade/book/mark tape readers, conservative fill simulation, queue companion scoring, and P&L summaries.",
        "next_split": "Owner module for item 318; must not import the mm_paper facade.",
    },
    "src/weather/schema_registry.py": {
        "owner": "shared",
        "boundary": "Compatibility facade for schema version lookup, literal audit/check behavior, CLI rendering, and public registry-data exports.",
        "next_split": "Item 318 slice complete; static registry records live in schema_registry_data and schema_registry_recent_data.",
    },
    "src/weather/schema_registry_data.py": {
        "owner": "shared",
        "boundary": "Static registered schema records, exclusion records, and lookup maps for the schema registry facade.",
        "next_split": "WARN in the 2026-07-03 audit; acceptable as static registry data for now, but the next growth slice should move another schema family into schema_registry_recent_data or a new static shard without importing producer modules.",
    },
    "src/weather/schema_registry_recent_data.py": {
        "owner": "shared",
        "boundary": "Recent runtime, snapshot-sidecar, source-status, and taker schema records split from the main registry data shard.",
        "next_split": "Owner module for item 318; static data shard that imports only schema registry record types.",
    },
    "src/weather/schema_registry_types.py": {
        "owner": "shared",
        "boundary": "Dependency-free schema registry dataclasses and registry schema version constant.",
        "next_split": "Owner module for item 318; shared by registry data shards and the public facade.",
    },
    "src/weather/collection/snapshot_store.py": {
        "owner": "collection",
        "boundary": "Snapshot schema constants, readers, writers, and compatibility exports for backfill utilities.",
        "next_split": "WARN in the 2026-07-03 audit; backfill helpers and utility CLI wiring already live in snapshot_store_backfill, so the next slice should extract payload persistence, explanation sidecar, or replay-input helpers while preserving SnapshotStore's public surface.",
    },
    "src/weather/model/model_sources.py": {
        "owner": "model",
        "boundary": "Serving-time source fetch orchestration, retry/backoff policy, source-group integration, and live/local source parsing for model assembly.",
        "next_split": "WARN in the 2026-07-03 audit; move provider-specific fetch/parsing helpers toward weather.sources or source_adapters, keeping model_sources focused on serving-time source assembly.",
    },
    "src/weather/collection/snapshot_store_backfill.py": {
        "owner": "collection",
        "boundary": "Snapshot sidecar/cadence backfill helpers and snapshot-store utility CLI wiring.",
        "next_split": "Owner module for item 318; imports SnapshotStore lazily to avoid cycles.",
    },
    "src/weather/market/taker_bot_bakeoff.py": {
        "owner": "market",
        "boundary": "Taker bakeoff orchestration, report rendering, champion/challenger ledger, and compatibility exports for replay/scoring helpers.",
        "next_split": "Item 318 slice complete; replay input, profitability verification, and model-variant scoring helpers live in taker_bot_bakeoff_scoring.",
    },
    "src/weather/market/taker_bot_bakeoff_scoring.py": {
        "owner": "market",
        "boundary": "Replay input normalization, current replay profitability verification, and model-variant bakeoff row expansion.",
        "next_split": "Owner module for item 318; must not import the taker_bot_bakeoff facade.",
    },
    "src/weather/reporting/source_family_inventory.py": {
        "owner": "reporting",
        "boundary": "Source-family input readers, family/gate classification, payload assembly, and CLI.",
        "next_split": "Item 318 slice complete; Markdown rendering lives in source_family_inventory_report.",
    },
    "src/weather/reporting/source_family_inventory_report.py": {
        "owner": "reporting",
        "boundary": "Markdown rendering for source-family inventory artifacts.",
        "next_split": "Owner module for item 318; must not import the source-family inventory facade.",
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
