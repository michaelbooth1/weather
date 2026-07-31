"""CLI parser and command handlers for daily refresh."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from weather.operations import capture_resource_gate, nightly_health_checks
from weather.io import write_json_atomic
from weather.operations.daily_refresh_resources import bounded_resume_command
from weather.paths import data_path
from weather.reporting.scorecards import live_variant_settlement_scorecard
from weather.schema_registry import schema_version


STALE_LOCK_REPAIR_SCHEMA_VERSION = schema_version("daily_refresh_stale_lock_repair")

_DEPENDENCY_NAMES = {
    "DEFAULT_SNAPSHOTS_ROOT",
    "DEFAULT_BACKTEST_ROOT",
    "DEFAULT_STATUS_OUT",
    "DEFAULT_REPORT_OUT",
    "DEFAULT_LOCK_PATH",
    "DEFAULT_STAGE_A_MANIFEST",
    "DEFAULT_STAGE_B_MANIFEST",
    "DEFAULT_EVIDENCE_TASK_NAME",
    "DEFAULT_LONG_JOB_STATE_PATH",
    "DEFAULT_LONG_JOB_LOCK_PATH",
    "DEFAULT_HEAVY_STEP_TIMEOUT_SECONDS",
    "DEFAULT_HEAVY_STEP_WORKING_SET_MAX_MB",
    "DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB",
    "DEFAULT_STAGE_A_MAX_COMMIT_PERCENT",
    "DEFAULT_MAKER_PAPER_LATEST_ACTIVE_RUNS",
    "DEFAULT_MAKER_PAPER_MAX_INPUT_BYTES",
    "DEFAULT_LABELS_CSV",
    "DEFAULT_LEDGER_ROOT",
    "STEP_ORDER",
    "STAGE_CHOICES",
    "progress_audit",
    "active_variant_shadow_refresh",
    "frozen_baseline_replay_trend",
    "hourly_model_performance",
    "model_market_disagreement_analysis",
    "ten_minute_model_performance",
    "settled_day_root_cause",
    "winner_rank_parity",
    "june23_location_bias_repair",
    "taker_bot",
    "taker_tail_casebook",
    "trading_evidence",
    "exchange_economics",
    "promotion_refresh",
    "clob_order_book_tiering",
    "daily_roll_log_hygiene",
    "fleet_observability",
    "event_metadata_validation",
    "data_retention_inventory",
    "run_daily_refresh",
    "trigger_evidence_stage_after_lock",
    "load_status",
    "lock_preflight",
    "lock_diagnostic",
    "acquire_lock",
    "release_lock",
    "_remove_lock_if_verified_stale",
    "clear_stale_long_job_state",
    "utc_iso",
}


def configure(dependencies):
    missing = sorted(name for name in _DEPENDENCY_NAMES if not hasattr(dependencies, name))
    if missing:
        raise ValueError(f"daily refresh CLI dependencies missing: {', '.join(missing)}")
    globals().update({name: getattr(dependencies, name) for name in _DEPENDENCY_NAMES})
    return dependencies


def _strict_stage_a_reserve(value):
    parsed = int(value)
    if parsed < DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB:
        raise argparse.ArgumentTypeError(
            "Stage-A reserve cannot be lower than "
            f"{DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB} MiB"
        )
    return parsed


def _strict_stage_a_commit_ceiling(value):
    import math

    parsed = float(value)
    if (
        not math.isfinite(parsed)
        or parsed <= 0
        or parsed > DEFAULT_STAGE_A_MAX_COMMIT_PERCENT
    ):
        raise argparse.ArgumentTypeError(
            "Stage-A commit ceiling must be finite, positive, and no higher "
            f"than {DEFAULT_STAGE_A_MAX_COMMIT_PERCENT}%"
        )
    return parsed


def build_run_parser(parser, dependencies=None):
    if dependencies is not None:
        configure(dependencies)
    parser.add_argument("folders", nargs="*", help="Optional snapshot folders for settlement finalization.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--roadmap", default=str(progress_audit.DEFAULT_ROADMAP))
    parser.add_argument("--status-out", default=str(DEFAULT_STATUS_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--lock-path", default=str(DEFAULT_LOCK_PATH))
    parser.add_argument("--stage", default="all", choices=STAGE_CHOICES)
    parser.add_argument("--stage-a-manifest", default=str(DEFAULT_STAGE_A_MANIFEST))
    parser.add_argument("--stage-b-manifest", default=str(DEFAULT_STAGE_B_MANIFEST))
    parser.add_argument("--evidence-task-name", default=str(DEFAULT_EVIDENCE_TASK_NAME))
    parser.add_argument("--disable-stage-trigger", action="store_true")
    parser.add_argument("--force-lock", action="store_true")
    parser.add_argument("--long-job-state", default=str(DEFAULT_LONG_JOB_STATE_PATH))
    parser.add_argument("--long-job-lock", default=str(DEFAULT_LONG_JOB_LOCK_PATH))
    parser.add_argument("--long-job-priority", default="below_normal", choices=["normal", "below_normal", "idle"])
    parser.add_argument("--disable-long-job-guard", action="store_true")
    parser.add_argument("--force-long-job-lock", action="store_true")
    parser.add_argument("--scheduler-task-name", default="")
    parser.add_argument("--scheduler-task-executable", default="")
    parser.add_argument("--scheduler-task-working-directory", default="")
    parser.add_argument(
        "--scheduler-invocation-topology",
        choices=("direct", "delegated_child"),
        default="direct",
    )
    parser.add_argument("--scheduler-task-action-arguments-b64", default="")
    parser.add_argument("--scheduler-process-executable", default="")
    parser.add_argument("--scheduler-correlation-seconds", type=float, default=120.0)
    parser.add_argument(
        "--producer-sla-seconds",
        type=float,
        default=0.0,
        help="Predeclared terminal SLA for this exact scheduled stage; zero is non-countable.",
    )
    parser.add_argument("--active-release-pointer", default="")
    parser.add_argument("--releases-root", default="")
    parser.add_argument("--repo-root", default="")
    parser.set_defaults(heavy_step_subprocess=True)
    parser.add_argument("--heavy-step-subprocess", dest="heavy_step_subprocess", action="store_true")
    parser.add_argument("--disable-heavy-step-subprocess", dest="heavy_step_subprocess", action="store_false")
    parser.add_argument(
        "--heavy-step-timeout-seconds",
        type=float,
        default=DEFAULT_HEAVY_STEP_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--heavy-step-working-set-max-mb",
        type=int,
        default=DEFAULT_HEAVY_STEP_WORKING_SET_MAX_MB,
    )
    parser.add_argument(
        "--stage-a-min-available-reserve-mb",
        type=_strict_stage_a_reserve,
        default=DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB,
        help=(
            "Physical RAM that must remain available in addition to each "
            "isolated Stage-A child's declared working-set budget."
        ),
    )
    parser.add_argument(
        "--stage-a-max-commit-percent",
        type=_strict_stage_a_commit_ceiling,
        default=DEFAULT_STAGE_A_MAX_COMMIT_PERCENT,
        help="Fail closed before an isolated Stage-A child at or above this host commit percentage.",
    )
    parser.add_argument(
        "--capture-resource-mode",
        choices=capture_resource_gate.CAPTURE_MODES,
        default="live",
        help=(
            "Host role for pre-heavy-work admission. Use offline_host only on "
            "an explicitly non-capture research host."
        ),
    )
    parser.add_argument("--capture-resource-disk-path", default="")
    parser.add_argument("--capture-resource-out", default="")
    parser.add_argument("--capture-resource-report", default="")
    parser.add_argument(
        "--capture-resource-min-free-memory-bytes",
        type=int,
        default=capture_resource_gate.DEFAULT_MIN_FREE_MEMORY_BYTES,
    )
    parser.add_argument(
        "--capture-resource-min-free-disk-bytes",
        type=int,
        default=capture_resource_gate.DEFAULT_MIN_FREE_DISK_BYTES,
    )
    parser.add_argument(
        "--capture-resource-daily-disk-growth-bytes",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--capture-resource-min-disk-headroom-days",
        type=float,
        default=capture_resource_gate.DEFAULT_MIN_DISK_HEADROOM_DAYS,
    )
    parser.add_argument(
        "--capture-resource-active-window-start-hour",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--capture-resource-active-window-end-hour",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--captured-input-parity-served",
        action="append",
        default=[],
        help="Explicit live-served prediction row file; repeat for multiple files.",
    )
    parser.add_argument(
        "--captured-input-parity-replay",
        action="append",
        default=[],
        help=(
            "Explicit prediction rows regenerated from the exact captured inputs; "
            "missing rows block heavy work."
        ),
    )
    parser.add_argument("--captured-input-parity-out", default="")
    parser.add_argument("--captured-input-parity-report", default="")
    parser.add_argument(
        "--captured-input-parity-max-age-hours",
        type=float,
        default=live_variant_settlement_scorecard.DEFAULT_PARITY_MAX_INPUT_AGE_HOURS,
    )
    parser.add_argument("--skip-captured-input-replay-parity", action="store_true")
    parser.add_argument(
        "--production-readiness-evidence",
        action="append",
        default=[],
        metavar="NAME=PATH",
    )
    parser.add_argument(
        "--production-readiness-served-artifact",
        action="append",
        default=[],
        metavar="ROLE=PATH",
    )
    parser.add_argument("--production-readiness-served-route", default="")
    parser.add_argument("--production-readiness-out", default="")
    parser.add_argument("--production-readiness-report", default="")
    parser.add_argument("--skip-production-readiness-gate", action="store_true")
    parser.add_argument(
        "--fail-on-production-readiness-block",
        action="store_true",
        help="Return a blocking pipeline status when the final read-only readiness gate is not PASS.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--resume-from-step", default="", choices=("", *STEP_ORDER))
    parser.add_argument("--fail-on-fleet-critical", action="store_true")
    parser.add_argument("--fail-on-nightly-health-critical", action="store_true")
    parser.add_argument("--fail-on-ingest-quality", action="store_true")
    parser.add_argument("--fail-on-data-layer-audit", action="store_true")
    parser.set_defaults(fail_on_hourly_performance_gate=True)
    parser.add_argument("--fail-on-hourly-performance-gate", dest="fail_on_hourly_performance_gate", action="store_true")
    parser.add_argument("--allow-hourly-performance-gate", dest="fail_on_hourly_performance_gate", action="store_false")
    parser.set_defaults(fail_on_ten_minute_performance_gate=True)
    parser.add_argument(
        "--fail-on-ten-minute-performance-gate",
        dest="fail_on_ten_minute_performance_gate",
        action="store_true",
    )
    parser.add_argument(
        "--allow-ten-minute-performance-gate",
        dest="fail_on_ten_minute_performance_gate",
        action="store_false",
    )
    parser.add_argument("--fail-on-snapshot-evaluation", action="store_true")
    parser.add_argument("--fail-on-shadow-ab-alert", action="store_true")
    parser.set_defaults(fail_on_variant_evidence_alert=True)
    parser.add_argument("--fail-on-variant-evidence-alert", dest="fail_on_variant_evidence_alert", action="store_true")
    parser.add_argument("--allow-variant-evidence-alert", dest="fail_on_variant_evidence_alert", action="store_false")
    parser.add_argument("--fail-on-daily-learning-blocker", action="store_true")
    parser.add_argument("--fail-on-daily-flow-analysis-blocker", action="store_true")
    parser.add_argument("--skip-shadow-ab-monitor", action="store_true")
    parser.add_argument("--ab-current-tol", type=float, default=0.003)
    parser.add_argument("--ab-market-tol", type=float, default=0.003)
    parser.add_argument("--skip-model-variant-evidence-growth", action="store_true")
    parser.add_argument("--skip-active-variant-shadow", action="store_true")
    parser.add_argument(
        "--active-variant-shadow-sources",
        default="",
        help="Comma-separated current active variant row paths used to build active_variant_shadow_long.csv.",
    )
    parser.add_argument(
        "--active-variant-shadow-window-dates",
        type=int,
        default=active_variant_shadow_refresh.DEFAULT_EVIDENCE_WINDOW_DATES,
        help="Replay registry shadow variants over only the newest N distinct "
             "target dates of the promotion corpus (recent-skill evidence "
             "window; caps the step's cost as the corpus grows). 0 replays "
             "the full corpus.",
    )
    parser.add_argument("--skip-proper-scoring-reliability-scorecard", action="store_true")
    parser.add_argument("--skip-live-variant-settlement-scorecard", action="store_true")
    parser.set_defaults(fail_on_live_variant_settlement_scorecard=True)
    parser.add_argument(
        "--fail-on-live-variant-settlement-scorecard",
        dest="fail_on_live_variant_settlement_scorecard",
        action="store_true",
        help="Mark the daily refresh critical when an available live tape fails canonical settlement scoring.",
    )
    parser.add_argument(
        "--allow-live-variant-settlement-scorecard-block",
        dest="fail_on_live_variant_settlement_scorecard",
        action="store_false",
        help="Diagnostic-only: preserve the BLOCK artifact without making the parent refresh critical.",
    )
    parser.add_argument(
        "--live-variant-settlement-tapes",
        default="",
        help="Comma-separated live variant tape paths. Default selects only --settled-analysis-target-date under snapshots root.",
    )
    parser.add_argument(
        "--live-variant-settlement-target-date",
        default="",
        help="Exact target date to score; defaults to the pinned settled-analysis target date.",
    )
    parser.add_argument(
        "--live-variant-settlement-expected-variants-manifest",
        default="",
        help="Optional immutable release manifest/registry pinning variants expected in every selected tape.",
    )
    parser.add_argument(
        "--live-variant-settlement-observed-variants-only",
        action="store_true",
        help="Diagnostic-only coverage over observed variants; emits DIAGNOSTIC and can never authorize promotion.",
    )
    parser.add_argument(
        "--live-variant-settlement-allow-derived-release-id",
        action="store_true",
        help="Diagnostic legacy mode only; production scoring requires explicit release_id rows.",
    )
    parser.add_argument("--live-variant-settlement-simplex-tolerance", type=float, default=1e-6)
    parser.add_argument("--live-variant-settlement-max-tapes", type=int, default=None)
    parser.add_argument("--live-variant-settlement-max-tape-bytes", type=int, default=None)
    parser.add_argument("--live-variant-settlement-max-total-bytes", type=int, default=None)
    parser.add_argument("--live-variant-settlement-json-out", default="")
    parser.add_argument("--live-variant-settlement-report-out", default="")
    parser.add_argument("--variant-registry", default=str(active_variant_shadow_refresh.DEFAULT_REGISTRY_PATH))
    parser.add_argument(
        "--variant-evidence-current",
        default="",
        help="Comma-separated current variant long-table paths; defaults to active_variant_shadow_long.csv.",
    )
    parser.add_argument(
        "--variant-evidence-baseline",
        default="",
        help=(
            "Comma-separated baseline variant long-table paths; defaults to "
            "model_variant_evidence_baseline_active_shadow_long.csv when present, "
            "then the legacy item 70/71 long CSV."
        ),
    )
    parser.add_argument("--variant-evidence-min-unique-observations", type=int, default=1)
    parser.add_argument("--variant-evidence-min-market-days", type=int, default=1)
    parser.add_argument("--variant-evidence-rolling-7d-min-market-days", type=int, default=1)
    parser.add_argument("--variant-evidence-per-shadow-market-min-days", type=int, default=4)
    parser.add_argument("--skip-frozen-baseline-replay-trend", action="store_true")
    parser.add_argument(
        "--frozen-baseline-current-predictions",
        default="",
        help="Comma-separated current prediction exports; defaults to active_variant_shadow_long.csv.",
    )
    parser.add_argument(
        "--frozen-baseline-baseline-predictions",
        default="",
        help="Comma-separated pinned baseline prediction exports; defaults to the frozen baseline manifest.",
    )
    parser.add_argument(
        "--frozen-baseline-manifest",
        default="",
        help="Frozen baseline manifest path; defaults to <backtest-root>/frozen_baseline_manifest.json.",
    )
    parser.add_argument(
        "--frozen-baseline-current-variant-id",
        default="item50_pooled_forecast_v3_candidate",
    )
    parser.add_argument("--frozen-baseline-baseline-variant-id", default="")
    parser.add_argument("--frozen-baseline-code-identity", default="")
    parser.add_argument(
        "--frozen-baseline-trend-jsonl",
        default="",
        help="Trend JSONL output; defaults to <backtest-root>/frozen_baseline_replay_trend.jsonl.",
    )
    parser.add_argument(
        "--frozen-baseline-json-out",
        default="",
        help="Trend JSON output; defaults to <backtest-root>/frozen_baseline_replay_trend.json.",
    )
    parser.add_argument(
        "--frozen-baseline-report-out",
        default="",
        help="Trend report output; defaults to <backtest-root>/frozen_baseline_replay_trend_report.md.",
    )
    parser.add_argument("--as-of", default=None)
    parser.add_argument(
        "--settled-analysis-target-date",
        default="",
        help="Settled market day for post-finalization analysis; defaults to --as-of minus one day.",
    )
    parser.add_argument("--quality-grades", default="complete,manual_override")
    parser.add_argument("--skip-hourly-model-performance", action="store_true")
    parser.add_argument("--skip-ten-minute-model-performance", action="store_true")
    parser.add_argument("--skip-price-free-model-learning", action="store_true")
    parser.add_argument("--skip-model-market-disagreement-rehydration", action="store_true")
    parser.add_argument(
        "--model-market-disagreement-log",
        default=str(model_market_disagreement_analysis.DEFAULT_LOG_PATH),
        help="Append-only model-market disagreement audit log for post-settlement rehydration.",
    )
    parser.add_argument(
        "--model-market-disagreement-min-pattern-cases",
        type=int,
        default=1,
        help="Minimum cases required before disagreement-analysis patterns become recommendations.",
    )
    parser.add_argument("--skip-settled-day-analysis-barrier", action="store_true")
    parser.add_argument("--skip-settled-day-root-cause", action="store_true")
    parser.add_argument("--skip-winner-rank-parity", action="store_true")
    parser.add_argument("--winner-rank-parity-days", type=int, default=winner_rank_parity.DEFAULT_DAYS)
    parser.add_argument(
        "--winner-rank-parity-min-snapshots",
        type=int,
        default=winner_rank_parity.DEFAULT_MIN_SNAPSHOTS,
    )
    parser.add_argument("--skip-june23-location-bias-repair", action="store_true")
    parser.add_argument(
        "--june23-location-bias-repair-date",
        default=june23_location_bias_repair.DEFAULT_TARGET_DATE,
    )
    parser.add_argument(
        "--settled-root-cause-date",
        default="",
        help="Target date for settled-day root-cause report; defaults to --as-of or yesterday UTC.",
    )
    parser.add_argument("--taker-root", default=str(settled_day_root_cause.DEFAULT_TAKER_ROOT))
    parser.add_argument("--mm-root", default=str(settled_day_root_cause.DEFAULT_MM_ROOT))
    parser.add_argument("--skip-taker-finalization-watchdog", action="store_true")
    parser.add_argument(
        "--taker-finalization-date",
        default="",
        help="Optional taker target date to finalize; default scans all taker runs for newly labelable tapes.",
    )
    parser.add_argument(
        "--taker-finalization-sla-hours",
        type=float,
        default=taker_bot.DEFAULT_FINALIZATION_SLA_HOURS,
    )
    parser.add_argument(
        "--taker-finalization-min-free-bytes",
        type=int,
        default=taker_bot.DEFAULT_MIN_FREE_BYTES,
    )
    parser.add_argument(
        "--taker-finalization-no-finalize",
        action="store_true",
        help="Report taker finalization state without writing missing settled artifacts.",
    )
    parser.add_argument("--skip-taker-bakeoff", action="store_true")
    parser.add_argument("--taker-bakeoff-strategies", default=taker_bot.DEFAULT_BAKEOFF_STRATEGIES)
    parser.add_argument("--taker-champion-strategy-id", default=taker_bot.ACTIVE_DEFAULT_STRATEGY_ID)
    parser.add_argument(
        "--taker-champion-min-complete-label-days",
        type=int,
        default=taker_bot.DEFAULT_CHAMPION_MIN_COMPLETE_LABEL_DAYS,
    )
    parser.add_argument(
        "--taker-champion-min-settled-orders",
        type=int,
        default=taker_bot.DEFAULT_CHAMPION_MIN_SETTLED_ORDERS,
    )
    parser.add_argument("--skip-taker-tail-casebook", action="store_true")
    parser.add_argument("--skip-taker-edge-permission-map", action="store_true")
    parser.add_argument(
        "--taker-edge-permission-map-out",
        default="",
        help="Output path for the regenerated taker edge-permission map; defaults to <backtest-root>/taker_edge_permission_map.json.",
    )
    parser.add_argument("--taker-edge-permission-min-settled-orders", type=int, default=5)
    parser.add_argument("--taker-edge-permission-min-independent-days", type=int, default=3)
    parser.add_argument("--taker-edge-permission-min-after-fee-skill", type=float, default=0.0)
    parser.add_argument(
        "--taker-tail-casebook-date",
        default="",
        help="Optional target date under --taker-root for the tail-loss casebook; default scans all runs.",
    )
    parser.add_argument(
        "--taker-tail-casebook-max-runs",
        type=int,
        default=0,
        help="Limit tail casebook to the most recent N taker runs; 0 means all discovered runs.",
    )
    parser.add_argument("--skip-maker-paper-score", action="store_true")
    parser.add_argument(
        "--maker-paper-latest-active-runs",
        type=int,
        default=DEFAULT_MAKER_PAPER_LATEST_ACTIVE_RUNS,
        help="Score only the latest N active-day maker runs in the scheduled refresh.",
    )
    parser.add_argument(
        "--maker-paper-max-input-bytes",
        type=int,
        default=DEFAULT_MAKER_PAPER_MAX_INPUT_BYTES,
        help="Fail closed before maker scoring when selected quote inputs exceed this byte budget.",
    )
    parser.add_argument("--skip-exchange-economics-rule-drift", action="store_true")
    parser.add_argument(
        "--exchange-economics-template",
        default=str(exchange_economics.DEFAULT_TEMPLATE),
        help="Tracked exchange-economics source template used to stamp target-date proof.",
    )
    parser.add_argument(
        "--exchange-economics-snapshot",
        default="",
        help="Current exchange economics snapshot; defaults to <backtest-root>/exchange_economics_snapshot.json.",
    )
    parser.add_argument(
        "--exchange-economics-accepted-snapshot",
        default="",
        help="Previously accepted exchange economics snapshot for material-drift comparison.",
    )
    parser.add_argument("--exchange-economics-platform", default="polymarket_us")
    parser.add_argument("--skip-settlement-source-audit", action="store_true")
    parser.add_argument(
        "--fail-on-observed-floor-safety",
        action="store_true",
        help=(
            "Fail closed when the observed-floor monitor reports ALERT or BLOCK. "
            "Defaults off during the temporary pre-lock alert-only posture."
        ),
    )
    parser.add_argument("--skip-trading-evidence", action="store_true")
    parser.add_argument("--markets", default="", help="Comma-separated market IDs for price-free diagnostics.")
    parser.add_argument(
        "--promotion-min-artifact-free-bytes",
        type=int,
        default=promotion_refresh.DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES,
        help="Daily-refresh preflight minimum free bytes before promotion refresh artifact exports.",
    )
    parser.add_argument(
        "--replay-cache",
        default="read_write",
        choices=["read_write", "write_only", "off"],
        help="Per-market-day replay cache mode for promotion and active variant shadow replays.",
    )
    parser.add_argument(
        "--replay-cache-root",
        default="",
        help="Replay cache root. Defaults to <backtest-root>/replay_cache.",
    )
    parser.add_argument("--disable-replay-cache-sentinel", action="store_true")
    parser.add_argument("--hourly-min-rows", type=int, default=hourly_model_performance.DEFAULT_MIN_ROWS)
    parser.add_argument("--hourly-top-hours", type=int, default=hourly_model_performance.DEFAULT_TOP_HOURS)
    parser.add_argument("--hourly-min-regime-market-days", type=int, default=hourly_model_performance.DEFAULT_MIN_REGIME_MARKET_DAYS)
    parser.add_argument(
        "--hourly-early-brier-regression-tolerance",
        type=float,
        default=hourly_model_performance.DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--hourly-early-logloss-regression-tolerance",
        type=float,
        default=hourly_model_performance.DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
    )
    parser.add_argument("--hourly-early-ece-max", type=float, default=hourly_model_performance.DEFAULT_EARLY_ECE_MAX)
    parser.add_argument("--ten-minute-min-rows", type=int, default=ten_minute_model_performance.DEFAULT_MIN_ROWS)
    parser.add_argument("--ten-minute-top-slots", type=int, default=ten_minute_model_performance.DEFAULT_TOP_SLOTS)
    parser.add_argument(
        "--ten-minute-min-weak-market-days",
        type=int,
        default=ten_minute_model_performance.DEFAULT_MIN_WEAK_MARKET_DAYS,
    )
    parser.add_argument(
        "--ten-minute-weak-brier-regression-tolerance",
        type=float,
        default=ten_minute_model_performance.DEFAULT_WEAK_BRIER_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--ten-minute-weak-logloss-regression-tolerance",
        type=float,
        default=ten_minute_model_performance.DEFAULT_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--ten-minute-candidate-rows",
        default=str(ten_minute_model_performance.DEFAULT_ITEM147_ROWS),
    )
    parser.add_argument(
        "--ten-minute-candidate-min-weak-market-days",
        type=int,
        default=ten_minute_model_performance.DEFAULT_MIN_WEAK_MARKET_DAYS,
    )
    parser.add_argument(
        "--ten-minute-candidate-weak-brier-improvement-min",
        type=float,
        default=ten_minute_model_performance.DEFAULT_CANDIDATE_WEAK_BRIER_IMPROVEMENT_MIN,
    )
    parser.add_argument(
        "--ten-minute-candidate-weak-market-regression-tolerance",
        type=float,
        default=ten_minute_model_performance.DEFAULT_CANDIDATE_WEAK_MARKET_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--ten-minute-candidate-weak-logloss-regression-tolerance",
        type=float,
        default=ten_minute_model_performance.DEFAULT_CANDIDATE_WEAK_LOGLOSS_REGRESSION_TOLERANCE,
    )
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--allow-unsettled", action="store_true")
    parser.add_argument("--skip-serving-gauntlet", action="store_true")
    parser.add_argument("--require-exact-identity", action="store_true")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--daily-summary", default="")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--settle", action="append", default=[])
    parser.add_argument("--interval-minutes", type=float, default=10.0)
    parser.add_argument("--tolerance", type=float, default=1.5)
    parser.add_argument("--skip-polymarket-reconciliation", action="store_true")
    parser.add_argument("--skip-replay-status-backfill", action="store_true")
    parser.add_argument("--skip-closed-day-parquet-incremental", action="store_true")
    parser.add_argument("--closed-day-parquet-plan-only", action="store_true")
    parser.add_argument("--closed-day-parquet-max-scan-folders", type=int, default=25)
    parser.add_argument("--closed-day-parquet-archive-root", default="")
    parser.add_argument("--skip-clob-order-book-tiering", action="store_true")
    parser.add_argument("--clob-tiering-settled-before", default="")
    parser.add_argument(
        "--clob-tiering-min-free-bytes",
        type=int,
        default=clob_order_book_tiering.DEFAULT_MIN_FREE_BYTES,
    )
    parser.add_argument("--clob-tiering-limit", type=int, default=None)
    parser.set_defaults(clob_tiering_delete_source=True)
    parser.add_argument("--clob-tiering-delete-source", dest="clob_tiering_delete_source", action="store_true")
    parser.add_argument("--keep-clob-order-book-source", dest="clob_tiering_delete_source", action="store_false")
    parser.add_argument("--overwrite-replay-status", action="store_true")
    parser.add_argument("--reconstruct-missing-replay-inputs", action="store_true")
    parser.add_argument("--include-active-replay-status", action="store_true")
    parser.add_argument("--no-clob-casebook", action="store_true")
    parser.add_argument("--collection-interval-minutes", type=float, default=10.0)
    parser.add_argument("--collection-tolerance", type=float, default=1.5)
    parser.add_argument("--audit-target-month", type=int, default=None)
    parser.add_argument("--audit-target-day", type=int, default=None)
    parser.add_argument("--audit-years", default="")
    parser.add_argument("--skip-historical-audits", action="store_true")
    parser.add_argument("--skip-nightly-health-checks", action="store_true")
    parser.add_argument("--skip-daily-roll-log-hygiene", action="store_true")
    parser.add_argument(
        "--daily-roll-log-window-hours",
        type=float,
        default=daily_roll_log_hygiene.DEFAULT_CURRENT_WINDOW_HOURS,
    )
    parser.add_argument(
        "--daily-roll-log-sources",
        default="",
        help="Comma-separated loop=path entries for Streamlit, daily-refresh, collection, taker, and maker logs.",
    )
    parser.add_argument(
        "--daily-roll-log-incidents",
        default="",
        help="Historical incident JSONL path; defaults to <backtest-root>/daily_roll_log_incidents.jsonl.",
    )
    parser.add_argument(
        "--daily-roll-current-log-root",
        default="",
        help="Directory for current-window per-loop log files; defaults to <backtest-root>/daily_roll_current_logs.",
    )
    parser.add_argument("--nightly-health-alert-root", default=str(nightly_health_checks.DEFAULT_ALERT_ROOT))
    parser.add_argument("--nightly-health-timezone", default=nightly_health_checks.DEFAULT_TIMEZONE)
    parser.add_argument(
        "--nightly-health-date",
        default="",
        help="Expected local bot target date for health checks; defaults to today's date in --nightly-health-timezone.",
    )
    parser.add_argument(
        "--nightly-health-max-bot-activity-age-seconds",
        type=float,
        default=nightly_health_checks.DEFAULT_MAX_BOT_ACTIVITY_AGE_SECONDS,
    )
    parser.add_argument(
        "--nightly-health-startup-grace-seconds",
        type=float,
        default=nightly_health_checks.DEFAULT_STARTUP_GRACE_SECONDS,
    )
    parser.add_argument("--skip-ingest-quality-gate", action="store_true")
    parser.add_argument("--ingest-quality-years", default="", help="Comma-separated years; default 2000-2025.")
    parser.add_argument("--skip-event-metadata-validation", action="store_true")
    parser.add_argument(
        "--event-metadata-target-date",
        default="",
        help="Target date for Polymarket event metadata validation; defaults to --as-of or today UTC.",
    )
    parser.add_argument(
        "--event-metadata-markets",
        default="all",
        help="Comma-separated market IDs for event metadata validation, or all.",
    )
    parser.add_argument("--event-metadata-locations", default=str(event_metadata_validation.DEFAULT_LOCATIONS))
    parser.add_argument("--event-metadata-config", default=str(event_metadata_validation.DEFAULT_EVENT_METADATA))
    parser.set_defaults(event_metadata_live_fetch=True)
    parser.add_argument("--event-metadata-live-fetch", dest="event_metadata_live_fetch", action="store_true")
    parser.add_argument("--event-metadata-no-live-fetch", dest="event_metadata_live_fetch", action="store_false")
    parser.add_argument("--event-metadata-timeout-seconds", type=float, default=10.0)
    parser.add_argument(
        "--event-metadata-max-age-hours",
        type=float,
        default=event_metadata_validation.DEFAULT_MAX_AGE_HOURS,
    )
    parser.add_argument("--skip-public-wu-settlement-restore", action="store_true")
    parser.add_argument(
        "--wu-settlement-restore-markets",
        default="all",
        help="Comma-separated market IDs for completed-day WU settlement restore; default all.",
    )
    parser.add_argument("--wu-settlement-restore-sleep", type=float, default=0.2)
    parser.add_argument("--wu-settlement-restore-timeout", type=float, default=30.0)
    parser.add_argument(
        "--wu-settlement-restore-retries",
        type=int,
        default=2,
        help=(
            "Extra attempts per range when the failure classifies as transient; 0 disables. "
            "A single timeout here blocks label finalization for every market."
        ),
    )
    parser.add_argument(
        "--wu-settlement-restore-retry-backoff",
        type=float,
        default=5.0,
        help="Seconds before the first transient retry; doubles each further attempt.",
    )
    parser.set_defaults(wu_settlement_restore_skip_existing=True)
    parser.add_argument(
        "--wu-settlement-restore-skip-existing",
        dest="wu_settlement_restore_skip_existing",
        action="store_true",
        help="Reuse existing target-date raw WU payloads and rebuild normalized outputs.",
    )
    parser.add_argument(
        "--wu-settlement-restore-refetch",
        dest="wu_settlement_restore_skip_existing",
        action="store_false",
        help="Fetch target-date WU payloads even when local raw payloads already exist.",
    )
    parser.set_defaults(wu_settlement_restore_continue_on_error=True)
    parser.add_argument(
        "--wu-settlement-restore-continue-on-error",
        dest="wu_settlement_restore_continue_on_error",
        action="store_true",
        help="Record per-market WU restore failures and continue through remaining markets.",
    )
    parser.add_argument(
        "--wu-settlement-restore-stop-on-error",
        dest="wu_settlement_restore_continue_on_error",
        action="store_false",
        help="Abort the restore step on the first WU restore failure.",
    )
    parser.add_argument("--skip-reanalysis-refresh", action="store_true")
    parser.add_argument("--reanalysis-lag-days", type=int, default=10)
    parser.add_argument("--reanalysis-chunk-days", type=int, default=5)
    parser.add_argument("--reanalysis-sleep", type=float, default=0.2)
    parser.add_argument("--reanalysis-timeout", type=float, default=30)
    parser.add_argument("--reanalysis-end-date", default="")
    parser.add_argument("--skip-data-layer-audit", action="store_true")
    parser.add_argument("--skip-data-retention-inventory", action="store_true")
    parser.add_argument("--distribution-stage-min-rows", type=int, default=20)
    parser.add_argument(
        "--data-retention-min-free-bytes",
        type=int,
        default=data_retention_inventory.DEFAULT_MIN_FREE_BYTES,
    )
    parser.add_argument(
        "--data-retention-lookback-hours",
        type=float,
        default=data_retention_inventory.DEFAULT_LOOKBACK_HOURS,
    )
    parser.add_argument("--data-retention-top-n", type=int, default=data_retention_inventory.DEFAULT_TOP_N)
    parser.add_argument("--skip-daily-learning", action="store_true")
    parser.add_argument("--skip-market-beating-objective-scoreboard", action="store_true")
    parser.add_argument("--skip-daily-flow-analysis", action="store_true")
    parser.add_argument("--data-layer-historical-start", default="2000-01-01")
    parser.add_argument("--data-layer-historical-end", default="")
    return parser


def exit_code_for_status(status):
    if status in {"error", "unreadable"}:
        return 1
    if status in {"critical", "deferred", "interrupted"}:
        return 2
    return 0


def cmd_run(args):
    lock = None
    payload = None
    _redirect_default_dry_run_outputs(args)
    if not args.dry_run:
        preflight = lock_preflight(args)
        lock_audit = {}
        lock = acquire_lock(args.lock_path, force=args.force_lock, audit=lock_audit)
        setattr(args, "_daily_refresh_lock_acquisition", lock_audit)
        if lock is None:
            blocked = lock_preflight(args)
            print(f"Daily refresh lock blocks run: {args.lock_path}", file=sys.stderr)
            print(json.dumps(blocked.get("daily_refresh_lock") or {}, indent=2, sort_keys=True), file=sys.stderr)
            print(f"Repair command: {blocked.get('repair_command')}", file=sys.stderr)
            return 3
        preflight["daily_refresh_lock_after_acquire"] = lock_diagnostic(
            args.lock_path,
            kind="daily_refresh_lock",
        )
        setattr(args, "_daily_refresh_cli_lock_preflight", preflight)
    try:
        payload, status_path, report_path = run_daily_refresh(args)
    finally:
        release_lock(lock)
    trigger = trigger_evidence_stage_after_lock(args, payload)
    print(f"Daily refresh: {payload['status']}")
    print(f"Status written to {status_path}")
    print(f"Report written to {report_path}")
    if trigger.get("status") not in {"SKIPPED", "PENDING"}:
        print(f"Evidence trigger: {trigger.get('status')} ({trigger.get('task_name')})")
    return exit_code_for_status(payload["status"])


def _is_default_path(value, default):
    try:
        return Path(value) == Path(default)
    except TypeError:
        return False


def _redirect_default_dry_run_outputs(args):
    if not getattr(args, "dry_run", False):
        return
    backtest_root = Path(args.backtest_root)
    if _is_default_path(getattr(args, "status_out", None), DEFAULT_STATUS_OUT):
        args.status_out = str(backtest_root / "daily_refresh_dry_run_status.json")
    if _is_default_path(getattr(args, "report_out", None), DEFAULT_REPORT_OUT):
        args.report_out = str(backtest_root / "daily_refresh_dry_run_report.md")


def cmd_status(args):
    status = load_status(args.status_out)
    if not status.get("exists"):
        print(f"No daily refresh status at {status['path']}")
        return 1
    print(json.dumps(status, indent=2, sort_keys=True, default=str))
    return exit_code_for_status(status.get("status"))


def repair_stale_locks(args):
    daily = _remove_lock_if_verified_stale(args.lock_path, kind="daily_refresh_lock")
    long_job = _remove_lock_if_verified_stale(
        getattr(args, "long_job_lock", DEFAULT_LONG_JOB_LOCK_PATH),
        kind="long_job_guard_lock",
    )
    long_job_state = clear_stale_long_job_state(
        getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
    )
    status_repair = _repair_interrupted_status(args, long_job_state, daily)
    return {
        "schema_version": STALE_LOCK_REPAIR_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "daily_refresh_lock": daily,
        "long_job_lock": long_job,
        "long_job_state": long_job_state,
        "removed_lock_count": sum(1 for row in (daily, long_job) if row.get("removed")),
        "verified_stale_lock_count": sum(1 for row in (daily, long_job) if row.get("stale")),
        "cleared_state_count": 1 if long_job_state.get("cleared") else 0,
        "resume_from_step": (
            getattr(args, "resume_from_step", "")
            or ("promotion_refresh" if getattr(args, "stage", "all") == "evidence" else STEP_ORDER[0])
        ),
        "daily_refresh_status": status_repair,
    }


def _matching_pid(left, right):
    try:
        return int(left) == int(right)
    except (TypeError, ValueError):
        return False


def _recover_completed_isolated_child(payload):
    current = payload.get("current_step") or {}
    step_name = str(current.get("name") or "")
    if not step_name:
        return {"recovered": False, "reason": "current_step_missing"}
    resource_row = next(
        (
            row
            for row in reversed(payload.get("resource_steps") or [])
            if row.get("step") == step_name
        ),
        None,
    )
    if not resource_row:
        return {"recovered": False, "reason": "resource_step_missing"}
    result_value = ((resource_row.get("child_invocation") or {}).get("result_json"))
    if not result_value:
        return {"recovered": False, "reason": "child_result_path_missing"}
    result_path = Path(result_value)
    backtest_root = Path((payload.get("config") or {}).get("backtest_root") or "")
    try:
        resolved_result = result_path.resolve()
        resolved_root = backtest_root.resolve()
        if not resolved_result.is_relative_to(resolved_root):
            return {"recovered": False, "reason": "child_result_outside_backtest_root"}
        child = json.loads(resolved_result.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"recovered": False, "reason": "child_result_unavailable"}
    expected_pid = resource_row.get("child_pid") or current.get("child_pid")
    valid = (
        child.get("schema_version") == schema_version("daily_refresh_step_child")
        and child.get("status") == "ok"
        and child.get("step") == step_name
        and _matching_pid(child.get("pid"), expected_pid)
        and bool(child.get("finished_at_utc"))
    )
    if not valid:
        return {"recovered": False, "reason": "child_terminal_validation_failed"}
    result = child.get("result")
    if not isinstance(result, dict):
        result = {"value": result}
    resource_row.update({
        "status": "ok_recovered_after_parent_interruption",
        "finished_at_utc": child.get("finished_at_utc"),
        "child_terminal": {
            key: child.get(key)
            for key in (
                "schema_version",
                "status",
                "step",
                "pid",
                "started_at_utc",
                "finished_at_utc",
            )
        },
    })
    result["resource_execution"] = dict(resource_row)
    if not any(
        row.get("name") == step_name and row.get("status") == "ok"
        for row in payload.get("steps") or []
    ):
        payload.setdefault("steps", []).append({
            "name": step_name,
            "status": "ok",
            "started_at_utc": child.get("started_at_utc"),
            "finished_at_utc": child.get("finished_at_utc"),
            "duration_seconds": (resource_row.get("subprocess") or {}).get(
                "duration_seconds"
            ),
            "result": result,
            "recovered_from_child_terminal": True,
        })
    return {
        "recovered": True,
        "step": step_name,
        "pid": child.get("pid"),
        "result_path": str(resolved_result),
    }


def _repair_interrupted_status(args, long_job_state, daily_lock):
    status_path = Path(getattr(args, "status_out", DEFAULT_STATUS_OUT))
    if not long_job_state.get("stale"):
        return {
            "updated": False,
            "reason": "long_job_owner_not_verified_dead",
            "path": str(status_path),
        }
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "updated": False,
            "reason": "daily_refresh_status_unavailable",
            "path": str(status_path),
        }
    if payload.get("status") not in {"running", "interrupted"}:
        return {
            "updated": False,
            "reason": "daily_refresh_status_not_running",
            "path": str(status_path),
            "status": payload.get("status"),
        }
    stale_pid = long_job_state.get("pid")
    status_owner_pid = payload.get("owner_pid")
    if daily_lock.get("owner_running") is True:
        return {
            "updated": False,
            "reason": "daily_refresh_lock_owner_running",
            "path": str(status_path),
            "owner_pid": daily_lock.get("pid"),
        }
    if not _matching_pid(status_owner_pid, stale_pid):
        return {
            "updated": False,
            "reason": "daily_refresh_status_owner_mismatch",
            "path": str(status_path),
            "status_owner_pid": status_owner_pid,
            "stale_long_job_pid": stale_pid,
        }
    if daily_lock.get("pid") not in (None, "") and not _matching_pid(
        daily_lock.get("pid"), stale_pid
    ):
        return {
            "updated": False,
            "reason": "daily_refresh_lock_owner_mismatch",
            "path": str(status_path),
            "daily_lock_pid": daily_lock.get("pid"),
            "stale_long_job_pid": stale_pid,
        }
    resume_contract = payload.get("resume_contract") or {}
    preserved_run_after_repair = bool(getattr(args, "run_after_repair", False))
    for key, value in (resume_contract.get("arguments") or {}).items():
        if key != "func" and not str(key).startswith("_"):
            setattr(args, key, value)
    args.run_after_repair = preserved_run_after_repair
    if isinstance(resume_contract.get("argv"), list) and resume_contract["argv"]:
        args._original_cli_argv = list(resume_contract["argv"])
    configured_stage = str((payload.get("config") or {}).get("stage") or "")
    if configured_stage:
        args.stage = configured_stage
    pinned_target = str(
        ((payload.get("config") or {}).get("settled_analysis_target_date")) or ""
    )
    if pinned_target and not getattr(args, "settled_analysis_target_date", ""):
        args.settled_analysis_target_date = pinned_target
    requested_step = getattr(args, "resume_from_step", "") or ""
    stage = str(getattr(args, "stage", "all") or "all")
    first_stage_step = "promotion_refresh" if stage == "evidence" else STEP_ORDER[0]
    final_stage_step = (
        "fleet_observability"
        if stage == "settlement"
        else STEP_ORDER[-1]
    )
    progress = (long_job_state.get("payload") or {}).get("progress") or {}
    recovered_child = _recover_completed_isolated_child(payload)
    if recovered_child.get("recovered"):
        progress = dict(progress)
        progress.update({
            "last_completed_step": recovered_child["step"],
            "last_completed_step_status": "ok",
            "recovered_child_terminal": recovered_child,
        })
    last_completed_step = str(progress.get("last_completed_step") or "")
    last_completed_status = str(progress.get("last_completed_step_status") or "").lower()
    step_name = requested_step or first_stage_step
    resume_selection = "requested_step" if requested_step else "fallback_step"
    if (
        last_completed_step in STEP_ORDER
        and last_completed_status in {"complete", "ok", "skipped"}
    ):
        last_index = STEP_ORDER.index(last_completed_step)
        if last_completed_step == final_stage_step:
            step_name = final_stage_step
            resume_selection = "verified_final_step_replay"
        elif last_index + 1 < len(STEP_ORDER):
            candidate = STEP_ORDER[last_index + 1]
            candidate_index = last_index + 1
            requested_index = (
                STEP_ORDER.index(requested_step)
                if requested_step in STEP_ORDER
                else -1
            )
            within_stage = not (
                (stage == "settlement" and candidate_index > STEP_ORDER.index("fleet_observability"))
                or (stage == "evidence" and candidate_index < STEP_ORDER.index("promotion_refresh"))
            )
            if within_stage and candidate_index >= requested_index:
                step_name = candidate
                resume_selection = "verified_last_completed_step"
    resume = bounded_resume_command(args, step_name)
    args.resume_from_step = step_name
    now = utc_iso()
    owner_pid = long_job_state.get("pid")
    payload.update({
        "status": "interrupted",
        "terminal": True,
        "generated_at_utc": now,
        "finished_at_utc": now,
        "current_step": {
            "name": step_name,
            "status": "interrupted",
            "owner_pid": owner_pid,
            "last_progress": progress,
            "last_progress_at_utc": (long_job_state.get("payload") or {}).get("last_progress_at_utc"),
            "requested_resume_step": requested_step,
            "resume_selection": resume_selection,
            "recovered_child_terminal": recovered_child,
            "resume_command": resume,
        },
        "interruption": {
            "status": "RESUMABLE",
            "reason": "verified_dead_daily_refresh_owner",
            "owner_pid": owner_pid,
            "verified_owner_running": long_job_state.get("owner_running"),
            "verified_at_utc": now,
            "last_completed_step": last_completed_step,
            "last_completed_step_status": last_completed_status,
            "requested_resume_step": requested_step,
            "selected_resume_step": step_name,
            "resume_selection": resume_selection,
            "recovered_child_terminal": recovered_child,
            "resume_command": resume,
            "repair_source": "repair-stale-locks",
        },
    })
    write_json_atomic(status_path, payload, trailing_newline=True)
    return {
        "updated": True,
        "path": str(status_path),
        "status": "interrupted",
        "owner_pid": owner_pid,
        "selected_resume_step": step_name,
        "resume_selection": resume_selection,
        "recovered_child_terminal": recovered_child,
        "resume_command": resume,
    }


def cmd_repair_stale_locks(args):
    payload = repair_stale_locks(args)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    if getattr(args, "run_after_repair", False):
        status_repair = payload.get("daily_refresh_status") or {}
        if status_repair.get("updated") is not True:
            print(
                "Refusing --run-after-repair without a correlated, updated "
                "daily-refresh resume status.",
                file=sys.stderr,
            )
            return 4
        setattr(args, "_prior_lock_repair_outcomes", payload)
        return cmd_run(args)
    return 0


def build_parser(dependencies):
    configure(dependencies)
    parser = argparse.ArgumentParser(description="Run or inspect the daily settlement-to-promotion refresh.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = build_run_parser(sub.add_parser("run"))
    run.set_defaults(func=cmd_run)
    status = sub.add_parser("status")
    status.add_argument("--status-out", default=str(DEFAULT_STATUS_OUT))
    status.set_defaults(func=cmd_status)
    repair = build_run_parser(sub.add_parser("repair-stale-locks"))
    repair.add_argument("--run-after-repair", action="store_true")
    repair.set_defaults(func=cmd_repair_stale_locks)
    return parser


def _enable_crash_forensics():
    """Persist native-crash tracebacks for hidden scheduled-task runs.

    The 2026-07-04 chain vanished mid-step with nothing in the status file,
    Windows Error Reporting, or the task history. Scheduled tasks run pythonw
    with no visible stderr, so a native fault (or hard kill) leaves no trace;
    faulthandler at least captures segfault-class deaths, and the log names
    which run was live. Best effort — never blocks the run.
    """
    import faulthandler
    from datetime import datetime, timezone

    try:
        log_dir = Path(str(data_path())) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        handle = (log_dir / f"daily_refresh_faulthandler_{stamp}.log").open(
            "w", encoding="utf-8"
        )
        handle.write(f"daily_refresh pid={os.getpid()} started {stamp}\n")
        handle.flush()
        faulthandler.enable(file=handle, all_threads=True)
        return handle
    except OSError:
        return None


def main(argv=None, dependencies=None):
    if dependencies is None:
        raise ValueError("daily refresh CLI dependencies are required")
    parser = build_parser(dependencies)
    original_argv = list(argv) if argv is not None else list(sys.argv[1:])
    args = parser.parse_args(original_argv)
    args._original_cli_argv = original_argv
    if getattr(args, "command", "") in {"run", "repair-stale-locks"}:
        _enable_crash_forensics()
    return args.func(args)
