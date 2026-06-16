import re
from pathlib import Path


TARGET_MODULES = [
    Path("src/weather/backtesting/backtest.py"),
    Path("src/weather/backtesting/replay.py"),
    Path("src/weather/backtesting/replay_ablation.py"),
    Path("src/weather/backtesting/replay_backtest.py"),
    Path("src/weather/backtesting/settled_days.py"),
    Path("src/weather/backtesting/settlement_io.py"),
    Path("src/weather/backtesting/settlement_ledger.py"),
    Path("src/weather/backtesting/tape_scoring.py"),
    Path("src/weather/calibration/family_secondary_artifacts.py"),
    Path("src/weather/calibration/feature_model.py"),
    Path("src/weather/calibration/forecast_error_model.py"),
    Path("src/weather/calibration/intraday_calibration.py"),
    Path("src/weather/calibration/model_ensemble.py"),
    Path("src/weather/calibration/pooled_candidate_replay.py"),
    Path("src/weather/calibration/pooled_candidate_replay_report.py"),
    Path("src/weather/calibration/pooled_candidate_scoring.py"),
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
    Path("src/weather/market/market_making_preflight.py"),
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
    Path("src/weather/model/model_contracts.py"),
    Path("src/weather/model/model_distribution.py"),
    Path("src/weather/model/model_distribution_signals.py"),
    Path("src/weather/model/model_features.py"),
    Path("src/weather/model/model_presentation.py"),
    Path("src/weather/model/model_sources.py"),
    Path("src/weather/model/source_adapters.py"),
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
    Path("src/weather/reporting/formatting.py"),
    Path("src/weather/scoring/metrics.py"),
    Path("src/weather/scoring/trading.py"),
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

APP_AND_TEST_MODULES = [
    *Path("app").rglob("*.py"),
    *(
        path
        for path in Path("tests").rglob("*.py")
        if path != Path("tests/operations/test_import_architecture.py")
    ),
]

SOURCE_MODULES_EXCEPT_BACKTEST_CLI = [
    path
    for path in Path("src/weather").rglob("*.py")
    if path != Path("src/weather/backtesting/backtest.py")
]

PATH_POLICY_MODULES = [
    *Path("src/weather").rglob("*.py"),
    *Path("app").rglob("*.py"),
    *Path("tools").rglob("*.py"),
]

WRAPPER_MODULE_NAMES = sorted(
    path.stem
    for path in Path("src").glob("*.py")
    if path.name != "__init__.py"
)

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

APP_TEST_LEGACY_IMPORT_RE = re.compile(
    r"^(?:from|import)\s+("
    + "|".join(re.escape(name) for name in WRAPPER_MODULE_NAMES)
    + r")\b",
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

BACKTEST_CLI_IMPORT_RE = re.compile(
    r"^\s*from\s+(?:weather\.backtesting\.backtest|\.\.backtesting\.backtest|\.\.backtest|\.backtest)\s+import\b",
    re.MULTILINE,
)

REPO_OWNED_RELATIVE_ROOT_RE = re.compile(r"Path\(\s*['\"](?:data|config|docs)['\"]\s*\)")

EXTRACTED_MODULE_IMPORT_RULES = {
    Path("src/weather/calibration/pooled_candidate_scoring.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.calibration\.pooled_candidate_replay|\.pooled_candidate_replay)\s+import\b|"
        r"import\s+weather\.calibration\.pooled_candidate_replay\b)",
        re.MULTILINE,
    ),
    Path("src/weather/market/market_making_preflight.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.market\.market_making_run|\.market_making_run)\s+import\b|"
        r"import\s+weather\.market\.market_making_run\b)",
        re.MULTILINE,
    ),
}


def test_migrated_modules_do_not_mutate_sys_path():
    offenders = []
    for path in TARGET_MODULES:
        text = path.read_text(encoding="utf-8")
        if "sys.path.insert" in text or "sys.path.append" in text:
            offenders.append(str(path))

    assert offenders == []


def test_app_and_tests_do_not_mutate_sys_path():
    offenders = []
    for path in APP_AND_TEST_MODULES:
        text = path.read_text(encoding="utf-8")
        if "sys.path.insert" in text or "sys.path.append" in text:
            offenders.append(str(path))
        if "os.sys.path.insert" in text or "os.sys.path.append" in text:
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


def test_app_and_tests_use_canonical_imports_for_internal_modules():
    offenders = {}
    for path in APP_AND_TEST_MODULES:
        text = path.read_text(encoding="utf-8")
        matches = [match.group(0) for match in APP_TEST_LEGACY_IMPORT_RE.finditer(text)]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}


def test_source_modules_do_not_import_backtest_cli_for_shared_helpers():
    offenders = {}
    for path in SOURCE_MODULES_EXCEPT_BACKTEST_CLI:
        text = path.read_text(encoding="utf-8")
        matches = [match.group(0) for match in BACKTEST_CLI_IMPORT_RE.finditer(text)]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}


def test_extracted_modules_do_not_import_orchestration_facades():
    offenders = {}
    for path, pattern in EXTRACTED_MODULE_IMPORT_RULES.items():
        text = path.read_text(encoding="utf-8")
        matches = [match.group(0) for match in pattern.finditer(text)]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}


def test_repo_owned_default_paths_use_weather_path_helpers():
    offenders = {}
    for path in PATH_POLICY_MODULES:
        text = path.read_text(encoding="utf-8")
        matches = [match.group(0) for match in REPO_OWNED_RELATIVE_ROOT_RE.finditer(text)]
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
