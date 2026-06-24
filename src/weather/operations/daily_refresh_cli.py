"""CLI parser and command handlers for daily refresh."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from weather.operations import nightly_health_checks
from weather.schema_registry import schema_version


STALE_LOCK_REPAIR_SCHEMA_VERSION = schema_version("daily_refresh_stale_lock_repair")

_DEPENDENCY_NAMES = {
    "DEFAULT_SNAPSHOTS_ROOT",
    "DEFAULT_BACKTEST_ROOT",
    "DEFAULT_STATUS_OUT",
    "DEFAULT_REPORT_OUT",
    "DEFAULT_LOCK_PATH",
    "DEFAULT_LONG_JOB_STATE_PATH",
    "DEFAULT_LONG_JOB_LOCK_PATH",
    "DEFAULT_LABELS_CSV",
    "DEFAULT_LEDGER_ROOT",
    "STEP_ORDER",
    "progress_audit",
    "active_variant_shadow_refresh",
    "frozen_baseline_replay_trend",
    "hourly_model_performance",
    "ten_minute_model_performance",
    "settled_day_root_cause",
    "winner_rank_parity",
    "taker_bot",
    "taker_tail_casebook",
    "trading_evidence",
    "promotion_refresh",
    "clob_order_book_tiering",
    "fleet_observability",
    "event_metadata_validation",
    "data_retention_inventory",
    "run_daily_refresh",
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
    parser.add_argument("--force-lock", action="store_true")
    parser.add_argument("--long-job-state", default=str(DEFAULT_LONG_JOB_STATE_PATH))
    parser.add_argument("--long-job-lock", default=str(DEFAULT_LONG_JOB_LOCK_PATH))
    parser.add_argument("--long-job-priority", default="below_normal", choices=["normal", "below_normal", "idle"])
    parser.add_argument("--disable-long-job-guard", action="store_true")
    parser.add_argument("--force-long-job-lock", action="store_true")
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
    parser.add_argument("--skip-proper-scoring-reliability-scorecard", action="store_true")
    parser.add_argument("--variant-registry", default=str(active_variant_shadow_refresh.DEFAULT_REGISTRY_PATH))
    parser.add_argument(
        "--variant-evidence-current",
        default="",
        help="Comma-separated current variant long-table paths; defaults to active_variant_shadow_long.csv.",
    )
    parser.add_argument(
        "--variant-evidence-baseline",
        default="",
        help="Comma-separated baseline variant long-table paths; defaults to item 70/71 long CSV.",
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
    parser.add_argument("--quality-grades", default="complete,manual_override")
    parser.add_argument("--skip-hourly-model-performance", action="store_true")
    parser.add_argument("--skip-ten-minute-model-performance", action="store_true")
    parser.add_argument("--skip-price-free-model-learning", action="store_true")
    parser.add_argument("--skip-settled-day-root-cause", action="store_true")
    parser.add_argument("--skip-winner-rank-parity", action="store_true")
    parser.add_argument("--winner-rank-parity-days", type=int, default=winner_rank_parity.DEFAULT_DAYS)
    parser.add_argument(
        "--winner-rank-parity-min-snapshots",
        type=int,
        default=winner_rank_parity.DEFAULT_MIN_SNAPSHOTS,
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
    parser.add_argument("--skip-settlement-source-audit", action="store_true")
    parser.add_argument("--skip-trading-evidence", action="store_true")
    parser.add_argument("--markets", default="", help="Comma-separated market IDs for price-free diagnostics.")
    parser.add_argument(
        "--promotion-min-artifact-free-bytes",
        type=int,
        default=promotion_refresh.DEFAULT_VARIANT_EXPORT_MIN_FREE_BYTES,
        help="Daily-refresh preflight minimum free bytes before promotion refresh artifact exports.",
    )
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
    parser.add_argument("--tape-backup-root", default=str(fleet_observability.tape_backup.DEFAULT_BACKUP_ROOT))
    parser.add_argument("--verify-tape-backup-checksums", action="store_true")
    parser.add_argument("--skip-nightly-health-checks", action="store_true")
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


def cmd_run(args):
    lock = None
    _redirect_default_dry_run_outputs(args)
    if not args.dry_run:
        preflight = lock_preflight(args)
        lock = acquire_lock(args.lock_path, force=args.force_lock)
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
    print(f"Daily refresh: {payload['status']}")
    print(f"Status written to {status_path}")
    print(f"Report written to {report_path}")
    if payload["status"] == "error":
        return 1
    if payload["status"] == "critical":
        return 2
    return 0


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
    if status.get("status") in {"error", "unreadable"}:
        return 1
    return 0


def repair_stale_locks(args):
    daily = _remove_lock_if_verified_stale(args.lock_path, kind="daily_refresh_lock")
    long_job = _remove_lock_if_verified_stale(
        getattr(args, "long_job_lock", DEFAULT_LONG_JOB_LOCK_PATH),
        kind="long_job_guard_lock",
    )
    long_job_state = clear_stale_long_job_state(
        getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
    )
    return {
        "schema_version": STALE_LOCK_REPAIR_SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "daily_refresh_lock": daily,
        "long_job_lock": long_job,
        "long_job_state": long_job_state,
        "removed_lock_count": sum(1 for row in (daily, long_job) if row.get("removed")),
        "cleared_state_count": 1 if long_job_state.get("cleared") else 0,
        "resume_from_step": getattr(args, "resume_from_step", "") or "daily_learning",
    }


def cmd_repair_stale_locks(args):
    payload = repair_stale_locks(args)
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    if getattr(args, "run_after_repair", False):
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


def main(argv=None, dependencies=None):
    if dependencies is None:
        raise ValueError("daily refresh CLI dependencies are required")
    parser = build_parser(dependencies)
    args = parser.parse_args(argv)
    return args.func(args)


