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
    "src/weather/calibration/pooled_training.py": {
        "owner": "calibration",
        "boundary": "Point-in-time pooled training evidence, fit receipts, final refit verification, and density/band model fitting.",
        "next_split": "Extract point-in-time receipt construction and verification into a pooled point-in-time contract module while preserving canonical hashes and fitted-bundle behavior.",
    },
    "src/weather/market/taker_bot.py": {
        "owner": "market",
        "boundary": "Compatibility facade for taker strategy, risk, tape, scoring, bakeoff, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/market/taker_bot_cli.py": {
        "owner": "market",
        "boundary": "Taker input discovery, run configuration, incremental benchmark persistence, run/recovery orchestration, loop control, and CLI dispatch.",
        "next_split": "Move incremental run construction and artifact recovery into a taker runner module; retain argument parsing and command dispatch in the CLI owner.",
    },
    "src/weather/market/taker_bot_finalization.py": {
        "owner": "market",
        "boundary": "Taker settlement reconciliation, next-run policy, retention planning, finalization watchdog, counterfactual reporting, and run finalization.",
        "next_split": "Extract finalization report rendering and watchdog inventory into dedicated modules while preserving settlement reconciliation and policy-gate payloads.",
    },
    "src/weather/reporting/promotion/promotion_refresh.py": {
        "owner": "reporting",
        "boundary": "Compatibility facade for promotion readers, decisions, gap analysis, reports, orchestration, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/reporting/fleet/fleet_observability.py": {
        "owner": "reporting",
        "boundary": "Compatibility facade for fleet inventory, loop health, SLO gates, payload, rendering, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/reporting/hourly/hourly_model_performance.py": {
        "owner": "reporting",
        "boundary": "Compatibility facade for hourly scoring, slots, gates, context, rendering, and CLI modules.",
        "next_split": "Complete for item 173; keep facade stable while extracted modules settle.",
    },
    "src/weather/reporting/hourly/ten_minute_model_performance.py": {
        "owner": "reporting",
        "boundary": "Ten-minute checkpoint scoring, bounded market-day aggregation, candidate comparison gates, report rendering, persistence, and CLI.",
        "next_split": "Extract report tables/rendering and candidate checkpoint readers from the bounded aggregation and scoring contract, preserving payload and CSV schemas.",
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
    "src/weather/operations/nightly_retrain.py": {
        "owner": "operations",
        "boundary": "Nightly retrain preflights, step planning/execution, experiment queue handling, candidate orchestration, SLA/status reporting, and CLI.",
        "next_split": "Extract SLA/report rendering and parser/status handlers behind the stable nightly command, leaving guarded pipeline orchestration in the owner module.",
    },
    "src/weather/operations/experiment_executor.py": {
        "owner": "operations",
        "boundary": "Verified experiment selection, host admission, isolated workspace construction, output validation, resource measurement, and candidate publication.",
        "next_split": "Extract bounded workspace copy, fingerprint, and cleanup mechanics into an experiment workspace module; keep claim, admission, execution, and publication policy fail-closed.",
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
        "boundary": "Genuine-execution admission and provenance-preserving trade normalization/deduplication, active-day paper score freshness, quote/trade/book/mark tape readers, conservative fill simulation, queue companion scoring, and P&L summaries.",
        "next_split": "WARN after the 2026-07-27 execution-evidence growth. Extract execution-evidence parsing, normalization, identity, and cross-source deduplication into a dedicated owner module that does not import the mm_paper facade; keep side-aware fill and P&L scoring in mm_paper_scoring.",
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
    "src/weather/collection/snapshot_tracker.py": {
        "owner": "collection",
        "boundary": "Snapshot capture orchestration, isolated fleet execution, managed-loop lifecycle, status reporting, and CLI dispatch.",
        "next_split": "Extract managed-loop status rendering and fleet-health aggregation behind the stable snapshot_tracker CLI while preserving worker isolation, writer-lock, and supervisor contracts.",
    },
    "src/weather/model/model_sources.py": {
        "owner": "model",
        "boundary": "Serving-time source fetch orchestration, retry/backoff policy, source-group integration, and live/local source parsing for model assembly.",
        "next_split": "WARN in the 2026-07-03 audit; move provider-specific fetch/parsing helpers toward weather.sources or source_adapters, keeping model_sources focused on serving-time source assembly.",
    },
    "src/weather/model/model_features.py": {
        "owner": "model",
        "boundary": "The FeatureModelMixin feature-assembly surface: building the trained feature vector from captured rows against the feature_store column contract, plus the US guidance replay diagnostics rendered from those rows.",
        "next_split": "Newly WARN in the 2026-08-09 audit at 2,014 lines, crossed when -09-43a routed eight previously dead base features. FeatureModelMixin is ~1,850 of those lines; extract the guidance-replay diagnostics builder and renderer first, since they are already standalone module-level functions with no mixin state, then split per-source feature routing from the assembled-vector contract.",
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
    "src/weather/reporting/source_gates/source_family_inventory.py": {
        "owner": "reporting",
        "boundary": "Source-family input readers, family/gate classification, payload assembly, and CLI.",
        "next_split": "Item 318 slice complete; Markdown rendering lives in source_family_inventory_report.",
    },
    "src/weather/reporting/source_gates/source_family_inventory_report.py": {
        "owner": "reporting",
        "boundary": "Markdown rendering for source-family inventory artifacts.",
        "next_split": "Owner module for item 318; must not import the source-family inventory facade.",
    },
    "src/weather/reporting/scorecards/live_variant_settlement_scorecard.py": {
        "owner": "reporting",
        "boundary": "Settled live-variant probability scoring, captured-input replay parity orchestration, persistence, report rendering, and CLI.",
        "next_split": "Move parity normalization, comparison, persistence, and rendering to reporting.validation.captured_input_replay_parity while preserving facade exports and byte-identical payloads.",
    },
    "src/weather/reporting/serving_gates/production_readiness_gate.py": {
        "owner": "reporting",
        "boundary": "Production-readiness child evidence validation, active-release verification, pointer attestation, parent gate composition, and report output.",
        "next_split": "Extract the child-evidence validator registry and active-release binding checks; leave first-blocker ordering and parent gate composition in the facade.",
    },
    "src/weather/reporting/validation/point_in_time_evaluation.py": {
        "owner": "reporting",
        "boundary": "Point-in-time materialization, validation planning, fold and fit receipts, streaming evaluation, persistence, and CLI.",
        "next_split": "After verifier consolidation, separate materialization, fit receipts, and the streaming evaluator behind stable frozen contracts without adding cross-owner cycles.",
    },
    "src/weather/calibration/residual_distribution_v1.py": {
        "owner": "calibration",
        "boundary": "ResidualDistributionV1 training, nested and locked evaluation, fit receipts, qualification orchestration, release construction, and CLI.",
        "next_split": "Extract receipt construction/verification and nested/locked evaluation; retain qualification orchestration and public release behavior in the facade.",
    },
    "src/weather/calibration/pooled_candidate_replay.py": {
        "owner": "calibration",
        "boundary": "Live candidate-replay orchestration, cache and sentinel handling, prediction attachment, result aggregation, variant export, and CLI.",
        "next_split": "Extract cache, sentinel, and result aggregation into a replay-cache owner that does not import the facade, preserving cache keys and forensic payloads.",
    },
    "src/weather/operations/event_day_manifest.py": {
        "owner": "operations",
        "boundary": "Event-day family inventory, manifest build/validation, storage-gate summaries, backfill reporting, and CLI.",
        "next_split": "Extract folder discovery, existing-state and storage-gate summaries, backfill reporting, and CLI while keeping manifest hash and validation behavior unchanged.",
    },
    "src/weather/market/market_microstructure.py": {
        "owner": "market",
        "boundary": "CLOB tape capture loops, tape audit, supervisor process lifecycle, status artifacts, compatibility exports, and CLI.",
        "next_split": "Extract tape audit and supervisor/process lifecycle behind the stable scheduled-task CLI, preserving lock, process, status, and audit behavior.",
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


def ownership_governance_errors(rows: list[dict]) -> list[dict]:
    """Return incomplete warning metadata and ownership notes for missing modules."""
    errors = []
    row_paths = {row["path"] for row in rows}
    for row in rows:
        if row["status"] != "WARN":
            continue
        missing = [field for field in ("owner", "boundary", "next_split") if not row.get(field)]
        if missing:
            errors.append({
                "kind": "warning_metadata_missing",
                "path": row["path"],
                "missing": missing,
            })
    for path in sorted(OWNERSHIP_NOTES):
        if path not in row_paths:
            errors.append({
                "kind": "ownership_note_orphaned",
                "path": path,
                "missing": [],
            })
    return errors


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
    governance_errors = ownership_governance_errors(rows)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or datetime.now(timezone.utc).isoformat(),
        "source_root": relative_to_repo(source_root),
        "warning_lines": int(warning_lines),
        "module_count": len(rows),
        "warning_count": len(over_threshold),
        "governance_status": "PASS" if not governance_errors else "WARN",
        "governance_errors": governance_errors,
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
        f"Ownership governance: `{payload.get('governance_status')}`",
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
    if payload.get("governance_errors"):
        lines.extend(["", "## Ownership Governance Errors", ""])
        for row in payload.get("governance_errors") or []:
            missing = ", ".join(row.get("missing") or [])
            suffix = f" (missing: {missing})" if missing else ""
            lines.append(f"- {row.get('kind')}: `{row.get('path')}`{suffix}")
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
