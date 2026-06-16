import re
from pathlib import Path


TARGET_MODULES = [
    Path("src/weather/backtesting/backtest.py"),
    Path("src/weather/backtesting/replay.py"),
    Path("src/weather/backtesting/replay_ablation.py"),
    Path("src/weather/backtesting/replay_backtest.py"),
    Path("src/weather/backtesting/settled_days.py"),
    Path("src/weather/backtesting/settlement_ledger.py"),
    Path("src/weather/calibration/family_secondary_artifacts.py"),
    Path("src/weather/calibration/feature_model.py"),
    Path("src/weather/calibration/forecast_error_model.py"),
    Path("src/weather/calibration/intraday_calibration.py"),
    Path("src/weather/calibration/model_ensemble.py"),
    Path("src/weather/calibration/pooled_candidate_replay.py"),
    Path("src/weather/calibration/pooled_candidate_replay_report.py"),
    Path("src/weather/calibration/pooled_feature_model.py"),
    Path("src/weather/calibration/probability_calibration.py"),
    Path("src/weather/calibration/settlement_lag_model.py"),
    Path("src/weather/collection/collection_health.py"),
    Path("src/weather/collection/data_ingestion.py"),
    Path("src/weather/collection/forecast_archive.py"),
    Path("src/weather/collection/forecast_tracker.py"),
    Path("src/weather/collection/historical_backfill_plan.py"),
    Path("src/weather/collection/snapshot_store.py"),
    Path("src/weather/collection/snapshot_tracker.py"),
    Path("src/weather/market/market_config.py"),
    Path("src/weather/market/market_day_labels.py"),
    Path("src/weather/market/market_making_run.py"),
    Path("src/weather/market/market_making_run_constants.py"),
    Path("src/weather/market/market_making_run_support.py"),
    Path("src/weather/market/market_microstructure.py"),
    Path("src/weather/market/market_microstructure_capture.py"),
    Path("src/weather/market/market_microstructure_features.py"),
    Path("src/weather/market/mm_paper.py"),
    Path("src/weather/market/mm_paper_reports.py"),
    Path("src/weather/market/mm_policy.py"),
    Path("src/weather/market/polymarket_client.py"),
    Path("src/weather/model/model_climatology.py"),
    Path("src/weather/model/model_constants.py"),
    Path("src/weather/model/model_distribution.py"),
    Path("src/weather/model/model_distribution_signals.py"),
    Path("src/weather/model/model_features.py"),
    Path("src/weather/model/model_presentation.py"),
    Path("src/weather/model/model_sources.py"),
    Path("src/weather/model/toronto_model.py"),
    Path("src/weather/operations/daily_refresh.py"),
    Path("src/weather/operations/long_job_guard.py"),
    Path("src/weather/operations/market_making_daily_roll.py"),
    Path("src/weather/operations/nightly_retrain.py"),
    Path("src/weather/operations/observation_trigger.py"),
    Path("src/weather/operations/ops_monitor.py"),
    Path("src/weather/operations/tape_backup.py"),
    Path("src/weather/reporting/data_auditor.py"),
    Path("src/weather/reporting/data_layer_audit.py"),
    Path("src/weather/reporting/data_layer_audit_report.py"),
    Path("src/weather/reporting/disagreement_casebook.py"),
    Path("src/weather/reporting/fleet_observability.py"),
    Path("src/weather/reporting/location_trust.py"),
    Path("src/weather/reporting/multi_variant_shadow.py"),
    Path("src/weather/reporting/overview_helpers.py"),
    Path("src/weather/reporting/progress_audit.py"),
    Path("src/weather/reporting/promotion_corpus.py"),
    Path("src/weather/reporting/promotion_gauntlet.py"),
    Path("src/weather/reporting/promotion_refresh.py"),
    Path("src/weather/reporting/shadow_ab_monitor.py"),
    Path("src/weather/reporting/snapshot_evaluation.py"),
    Path("src/weather/reporting/source_redundancy.py"),
    Path("src/weather/reporting/wu_max_since_7_validation.py"),
    Path("src/weather/sources/canonical_history_guardrails.py"),
    Path("src/weather/sources/forecast_history.py"),
    Path("src/weather/sources/historical_coverage.py"),
    Path("src/weather/sources/metar_history.py"),
    Path("src/weather/sources/noaa_ghcnh_history.py"),
    Path("src/weather/sources/reanalysis_history.py"),
    Path("src/weather/sources/supplemental_station_validation.py"),
    Path("src/weather/sources/wu_history.py"),
]

NATIVE_RUNTIME_MODULES = [
    path
    for path in Path("src/weather/model").glob("*.py")
    if path.name != "feature_store.py"
] + [
    Path("src/weather/operations/observation_trigger.py"),
]

LEGACY_IMPORT_RE = re.compile(
    r"^(?:from|import)\s+("
    r"backtest|canonical_history_guardrails|collection_health|daily_summary|"
    r"data_auditor|feature_probability_calibration|feature_store|"
    r"forecast_archive|forecast_error_model|forecast_history|location_trust|"
    r"historical_schema|"
    r"market_config|market_making_run_constants|market_making_run_support|market_registry|"
    r"market_microstructure|market_microstructure_constants|"
    r"market_microstructure_features|mm_paper_constants|mm_paper_reports|"
    r"mm_policy|model_constants|model_identity|model_presentation|model_sources|"
    r"noaa_ghcnh_history|observation_trigger|polymarket_client|pooled_candidate_replay|"
    r"pooled_feature_model|probability_calibration|promotion_corpus|"
    r"promotion_gauntlet|reanalysis_history|replay|replay_backtest|"
    r"runtime_identity|settled_days|settlement_lag_model|settlement_ledger|"
    r"snapshot_store|snapshot_tracker|source_redundancy|supplemental_station_validation|"
    r"supplemental_stations|toronto_model|wu_history"
    r")\b",
    re.MULTILINE,
)

LEGACY_TEMPERATURE_READ_RE = re.compile(
    r"(?:\.get\(\s*['\"](?P<get>"
    r"temp_c|target_temp_c|max_c|max_temp_c|max_since_7am_c|same_day_max_c|"
    r"air_temp_c|forecast_high_c|day_max_c"
    r")['\"]|\[\s*['\"](?P<index>"
    r"temp_c|target_temp_c|max_c|max_temp_c|max_since_7am_c|same_day_max_c|"
    r"air_temp_c|forecast_high_c|day_max_c"
    r")['\"]\s*\](?!\s*=))"
)


def test_migrated_modules_do_not_mutate_sys_path():
    offenders = []
    for path in TARGET_MODULES:
        text = path.read_text(encoding="utf-8")
        if "sys.path.insert" in text or "sys.path.append" in text:
            offenders.append(str(path))

    assert offenders == []


def test_migrated_modules_use_package_imports_for_internal_modules():
    offenders = {}
    for path in TARGET_MODULES:
        text = path.read_text(encoding="utf-8")
        matches = [match.group(0) for match in LEGACY_IMPORT_RE.finditer(text)]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}


def test_model_runtime_uses_native_temperature_accessors():
    offenders = {}
    for path in NATIVE_RUNTIME_MODULES:
        text = path.read_text(encoding="utf-8")
        matches = [match.group(0) for match in LEGACY_TEMPERATURE_READ_RE.finditer(text)]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}
