"""Dependency bundle construction for the stable daily-refresh CLI facade."""

from types import SimpleNamespace


DEPENDENCY_NAMES = (
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
)


def build_cli_dependencies(namespace):
    missing = [name for name in DEPENDENCY_NAMES if name not in namespace]
    if missing:
        raise RuntimeError(f"daily-refresh CLI dependencies missing: {missing}")
    return SimpleNamespace(**{name: namespace[name] for name in DEPENDENCY_NAMES})
