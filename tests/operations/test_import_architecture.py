import ast
import re
import subprocess
from pathlib import Path


TARGET_MODULES = [
    Path("src/weather/io.py"),
    Path("src/weather/time.py"),
    Path("src/weather/backtesting/backtest.py"),
    Path("src/weather/backtesting/replay.py"),
    Path("src/weather/backtesting/replay_ablation.py"),
    Path("src/weather/backtesting/replay_backtest.py"),
    Path("src/weather/backtesting/settled_days.py"),
    Path("src/weather/backtesting/settlement_io.py"),
    Path("src/weather/backtesting/settlement_ledger.py"),
    Path("src/weather/backtesting/tape_scoring.py"),
    Path("src/weather/units.py"),
    Path("src/weather/calibration/family_secondary_artifacts.py"),
    Path("src/weather/calibration/feature_model.py"),
    Path("src/weather/calibration/feature_model_reports.py"),
    Path("src/weather/calibration/forecast_error_model.py"),
    Path("src/weather/calibration/intraday_calibration.py"),
    Path("src/weather/calibration/model_ensemble.py"),
    Path("src/weather/calibration/pooled_candidate_replay.py"),
    Path("src/weather/calibration/pooled_candidate_replay_report.py"),
    Path("src/weather/calibration/pooled_candidate_scoring.py"),
    Path("src/weather/calibration/pooled_feature_model.py"),
    Path("src/weather/calibration/pooled_feature_source_state.py"),
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
    Path("src/weather/market/mm_exchange.py"),
    Path("src/weather/market/mm_exchange_reports.py"),
    Path("src/weather/market/mm_paper.py"),
    Path("src/weather/market/mm_paper_evidence.py"),
    Path("src/weather/market/mm_paper_reports.py"),
    Path("src/weather/market/mm_policy.py"),
    Path("src/weather/market/polymarket_client.py"),
    Path("src/weather/model/calibration_runtime.py"),
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
    Path("src/weather/reporting/data_layer_audit_remediation.py"),
    Path("src/weather/reporting/data_layer_audit_report.py"),
    Path("src/weather/reporting/disagreement_casebook.py"),
    Path("src/weather/reporting/fleet_observability.py"),
    Path("src/weather/reporting/location_trust.py"),
    Path("src/weather/reporting/multi_variant_shadow.py"),
    Path("src/weather/reporting/overview_helpers.py"),
    Path("src/weather/reporting/price_free_model_learning.py"),
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
POOLED_FEATURE_SPLIT_MODULES = [
    Path("src/weather/calibration/pooled_feature_assembly.py"),
    Path("src/weather/calibration/pooled_density_training.py"),
    Path("src/weather/calibration/pooled_band_training.py"),
    Path("src/weather/calibration/pooled_training.py"),
    Path("src/weather/calibration/pooled_artifact_io.py"),
    Path("src/weather/calibration/pooled_reporting.py"),
    Path("src/weather/calibration/pooled_feature_cli.py"),
]
TAKER_BOT_SPLIT_MODULES = sorted(Path("src/weather/market").glob("taker_bot_*.py"))
PROMOTION_REFRESH_SPLIT_MODULES = sorted(Path("src/weather/reporting").glob("promotion_refresh_*.py"))
FLEET_OBSERVABILITY_SPLIT_MODULES = sorted(Path("src/weather/reporting").glob("fleet_observability_*.py"))
HOURLY_MODEL_SPLIT_MODULES = sorted(Path("src/weather/reporting").glob("hourly_model_*.py"))
DAILY_REFRESH_SPLIT_MODULES = sorted(Path("src/weather/operations").glob("daily_refresh_*.py"))
TARGET_MODULES.extend(
    POOLED_FEATURE_SPLIT_MODULES
    + TAKER_BOT_SPLIT_MODULES
    + FLEET_OBSERVABILITY_SPLIT_MODULES
    + HOURLY_MODEL_SPLIT_MODULES
    + PROMOTION_REFRESH_SPLIT_MODULES
    + DAILY_REFRESH_SPLIT_MODULES
    + [Path("src/weather/operations/location_config_refresh.py")]
)

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
    r"data_auditor|data_layer_audit_remediation|"
    r"feature_model_reports|feature_probability_calibration|feature_store|"
    r"forecast_archive|forecast_error_model|forecast_history|location_trust|"
    r"historical_schema|"
    r"market_config|market_making_run_constants|market_making_run_support|market_registry|"
    r"market_microstructure|market_microstructure_constants|"
    r"market_microstructure_features|mm_exchange|mm_exchange_reports|"
    r"mm_paper_constants|mm_paper_evidence|mm_paper_reports|"
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
    Path("src/weather/calibration/feature_model_reports.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.calibration\.feature_model|\.feature_model)\s+import\b|"
        r"import\s+weather\.calibration\.feature_model\b)",
        re.MULTILINE,
    ),
    Path("src/weather/calibration/pooled_candidate_scoring.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.calibration\.pooled_candidate_replay|\.pooled_candidate_replay)\s+import\b|"
        r"import\s+weather\.calibration\.pooled_candidate_replay\b)",
        re.MULTILINE,
    ),
    Path("src/weather/calibration/pooled_feature_source_state.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.calibration\.pooled_feature_model|\.pooled_feature_model)\s+import\b|"
        r"import\s+weather\.calibration\.pooled_feature_model\b)",
        re.MULTILINE,
    ),
    Path("src/weather/market/market_making_preflight.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.market\.market_making_run|\.market_making_run)\s+import\b|"
        r"import\s+weather\.market\.market_making_run\b)",
        re.MULTILINE,
    ),
    Path("src/weather/market/mm_exchange_reports.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.market\.mm_exchange|\.mm_exchange)\s+import\b|"
        r"import\s+weather\.market\.mm_exchange\b)",
        re.MULTILINE,
    ),
    Path("src/weather/market/mm_paper_evidence.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.market\.mm_paper|\.mm_paper)\s+import\b|"
        r"import\s+weather\.market\.mm_paper\b)",
        re.MULTILINE,
    ),
    Path("src/weather/reporting/data_layer_audit_remediation.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.reporting\.data_layer_audit|\.data_layer_audit)\s+import\b|"
        r"import\s+weather\.reporting\.data_layer_audit\b)",
        re.MULTILINE,
    ),
}
EXTRACTED_MODULE_IMPORT_RULES.update({
    path: re.compile(
        r"^\s*(?:from\s+(?:weather\.calibration\.pooled_feature_model|\.pooled_feature_model)\s+import\b|"
        r"import\s+weather\.calibration\.pooled_feature_model\b)",
        re.MULTILINE,
    )
    for path in POOLED_FEATURE_SPLIT_MODULES
})
EXTRACTED_MODULE_IMPORT_RULES.update({
    path: re.compile(
        r"^\s*(?:from\s+(?:weather\.market\.taker_bot|\.taker_bot)\s+import\b|"
        r"import\s+weather\.market\.taker_bot\b)",
        re.MULTILINE,
    )
    for path in TAKER_BOT_SPLIT_MODULES
})
EXTRACTED_MODULE_IMPORT_RULES.update({
    path: re.compile(
        r"^\s*(?:from\s+(?:weather\.reporting\.promotion_refresh|\.promotion_refresh)\s+import\b|"
        r"import\s+weather\.reporting\.promotion_refresh\b)",
        re.MULTILINE,
    )
    for path in PROMOTION_REFRESH_SPLIT_MODULES
})
EXTRACTED_MODULE_IMPORT_RULES.update({
    path: re.compile(
        r"^\s*(?:from\s+(?:weather\.reporting\.fleet_observability|\.fleet_observability)\s+import\b|"
        r"import\s+weather\.reporting\.fleet_observability\b)",
        re.MULTILINE,
    )
    for path in FLEET_OBSERVABILITY_SPLIT_MODULES
})
EXTRACTED_MODULE_IMPORT_RULES.update({
    path: re.compile(
        r"^\s*(?:from\s+(?:weather\.reporting\.hourly_model_performance|\.hourly_model_performance)\s+import\b|"
        r"import\s+weather\.reporting\.hourly_model_performance\b)",
        re.MULTILINE,
    )
    for path in HOURLY_MODEL_SPLIT_MODULES
})
EXTRACTED_MODULE_IMPORT_RULES.update({
    path: re.compile(
        r"^\s*(?:from\s+(?:weather\.operations\.daily_refresh|\.daily_refresh)\s+import\b|"
        r"import\s+weather\.operations\.daily_refresh\b)",
        re.MULTILINE,
    )
    for path in DAILY_REFRESH_SPLIT_MODULES
})

ROUND_HALF_UP_DEFINITION_RE = re.compile(r"^\s*def\s+round_half_up\s*\(", re.MULTILINE)
ROUND_HALF_UP_ALLOWED_DEFINITION_MODULES = {
    Path("src/weather/units.py"),
    # Compatibility method for the model facade; it must delegate to weather.units.
    Path("src/weather/model/model_base.py"),
}

IMPORT_ERROR_HANDLER_RE = re.compile(r"except\s+ImportError\b")
MODEL_RUNTIME_CALIBRATION_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+weather\.calibration\b|import\s+weather\.calibration\b)",
    re.MULTILINE,
)
COMPATIBILITY_FALLBACK_MARKERS = (
    "direct src compatibility",
    "compatibility-wrapper execution",
    "package/module execution fallback",
)
ALLOWED_OPTIONAL_IMPORT_ERROR_MODULES = {
    Path("src/weather/market/market_microstructure_capture.py"),
    Path("src/weather/sources/historical_coverage.py"),
}

PACKAGE_ROOTS = {
    "backtesting",
    "calibration",
    "collection",
    "market",
    "model",
    "operations",
    "reporting",
    "sources",
}

SHARED_PACKAGE_ROOTS = {
    "artifacts",
    "io",
    "paths",
    "schema_registry",
    "scoring",
    "time",
    "units",
    "variant_registry",
}

ALLOWED_PACKAGE_EDGES = {
    ("backtesting", "market"),
    ("backtesting", "model"),
    ("backtesting", "sources"),
    ("calibration", "backtesting"),
    ("calibration", "market"),
    ("calibration", "model"),
    ("calibration", "sources"),
    ("collection", "market"),
    ("collection", "model"),
    ("collection", "operations"),
    ("collection", "sources"),
    ("market", "operations"),
    ("model", "market"),
    ("model", "sources"),
    ("operations", "backtesting"),
    ("operations", "collection"),
    ("operations", "market"),
    ("operations", "model"),
    ("operations", "sources"),
    ("reporting", "backtesting"),
    ("reporting", "collection"),
    ("reporting", "market"),
    ("reporting", "model"),
    ("reporting", "sources"),
    ("sources", "market"),
}

TRANSITIONAL_PACKAGE_EDGES = {
    ("backtesting", "collection"),
    ("backtesting", "operations"),
    ("backtesting", "reporting"),
    ("calibration", "operations"),
    ("calibration", "reporting"),
    ("collection", "backtesting"),
    ("market", "backtesting"),
    ("market", "collection"),
    ("market", "model"),
    ("operations", "reporting"),
    ("reporting", "calibration"),
    ("reporting", "operations"),
    ("sources", "model"),
}

PACKAGE_BOUNDARY_DOC = Path("docs/operations/package-boundaries.md")

PROJECT_CRITICAL_UNTRACKED_PATHS = [
    "src/weather",
    "tests",
    "app",
    "scripts/ops",
    "docs/operations",
    "tools",
]

FIRST_PARTY_SHIM_CALLER_ROOTS = [
    Path("README.md"),
    Path(".github"),
    Path("app"),
    Path("tests"),
    Path("tools"),
    Path("scripts"),
    Path("docs/operations"),
]

FIRST_PARTY_SHIM_CALL_RE = re.compile(
    r"pythonw?\.exe\s+-m\s+src\.|"
    r"python\s+-m\s+src\.|"
    r"-m\s+src\.|"
    r"streamlit\s+run\s+app\.py|"
    r"AppTest\.from_file\(\s*['\"]app\.py['\"]\s*\)|"
    r"(?:^|[\s`'\"])(?:\.\\)?scripts\\(?!ops\\|launch\\)"
    r"(?:register_[A-Za-z0-9_]+\.ps1|start_weather_dashboard\.(?:cmd|ps1|vbs))|"
    r"(?:^|[\s`'\"])(?:\./)?scripts/(?!ops/|launch/)"
    r"(?:register_[A-Za-z0-9_]+\.ps1|start_weather_dashboard\.(?:cmd|ps1|vbs))",
    re.MULTILINE,
)

FIRST_PARTY_SHIM_CALL_SCAN_EXCLUDED = {
    Path("tests/operations/test_import_architecture.py"),
}

ACTIVE_DOC_FILES = [
    Path("README.md"),
    Path(".github/workflows/retrain.yml"),
    Path("docs/operations/AGENT_CONTEXT.md"),
    Path("docs/operations/HISTORY_DATA_DESIGN.md"),
    Path("docs/operations/OPERATIONS_DESIGN.md"),
    Path("docs/operations/artifact-storage-policy.md"),
    Path("docs/operations/package-boundaries.md"),
    Path("docs/operations/path-policy.md"),
    Path("docs/research/MARKET_MAKING_LIVE_RUNBOOK_2026-06-15.md"),
    Path("docs/research/MM_INITIAL_TEST_RUN_DESIGN.md"),
]

ACTIVE_DOC_LEGACY_MODULE_RE = re.compile(
    r"(?:pythonw?\.exe\s+-m\s+src\.|python\s+-m\s+src\.|-m\s+src\.|`src\.[A-Za-z0-9_]+)",
    re.MULTILINE,
)

TEMP_DATA_FIXTURE_MARKERS = (
    "tmp_path",
    "tmpdir",
    "TemporaryDirectory",
    "monkeypatch.chdir",
    "os.chdir(tmp",
    "Path(tmp)",
)


def source_package(path):
    relative = path.relative_to(Path("src/weather"))
    if len(relative.parts) < 2:
        return None
    package = relative.parts[0]
    return package if package in PACKAGE_ROOTS else None


def imported_weather_package(module_name):
    if module_name == "weather" or not module_name.startswith("weather."):
        return None
    parts = module_name.split(".")
    if len(parts) < 2:
        return None
    package = parts[1]
    if package in PACKAGE_ROOTS or package in SHARED_PACKAGE_ROOTS:
        return package
    return None


def weather_import_modules(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


def observed_package_edges():
    edges = {}
    for path in Path("src/weather").rglob("*.py"):
        source = source_package(path)
        if not source:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module_name in weather_import_modules(tree):
            target = imported_weather_package(module_name)
            if not target or target == source:
                continue
            edges.setdefault((source, target), set()).add(str(path))
    return edges


def test_migrated_modules_do_not_mutate_sys_path():
    offenders = []
    for path in TARGET_MODULES:
        text = path.read_text(encoding="utf-8")
        if "sys.path.insert" in text or "sys.path.append" in text:
            offenders.append(str(path))

    assert offenders == []


def test_project_critical_files_are_tracked_or_ignored():
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            *PROJECT_CRITICAL_UNTRACKED_PATHS,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    offenders = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    assert offenders == []


def _first_party_caller_files():
    for root in FIRST_PARTY_SHIM_CALLER_ROOTS:
        if root in FIRST_PARTY_SHIM_CALL_SCAN_EXCLUDED:
            continue
        if root.is_file():
            yield root
            continue
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path not in FIRST_PARTY_SHIM_CALL_SCAN_EXCLUDED
            ):
                yield path


def test_first_party_surfaces_do_not_call_compatibility_shims():
    offenders = {}
    for path in _first_party_caller_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        matches = [match.group(0).strip() for match in FIRST_PARTY_SHIM_CALL_RE.finditer(text)]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}


def test_active_docs_use_canonical_weather_commands():
    offenders = {}
    for path in ACTIVE_DOC_FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        matches = [match.group(0).strip() for match in ACTIVE_DOC_LEGACY_MODULE_RE.finditer(text)]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}


def test_tests_do_not_depend_on_repo_root_data_tree():
    offenders = {}
    for path in Path("tests").rglob("*.py"):
        if path == Path("tests/operations/test_import_architecture.py"):
            continue
        text = path.read_text(encoding="utf-8")
        has_temp_fixture = any(marker in text for marker in TEMP_DATA_FIXTURE_MARKERS)
        tree = ast.parse(text)
        matches = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            func_name = getattr(func, "id", None) or getattr(func, "attr", None)
            if func_name not in {"Path", "open"} or not node.args:
                continue
            first_arg = node.args[0]
            if not isinstance(first_arg, ast.Constant) or not isinstance(first_arg.value, str):
                continue
            normalized = first_arg.value.replace("\\", "/")
            if normalized == "data" or normalized.startswith("data/"):
                matches.append((node.lineno, first_arg.value))
        if matches and not has_temp_fixture:
            offenders[str(path)] = matches

    assert offenders == {}


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


def test_legacy_wrappers_forward_import_and_module_execution_to_weather_package():
    offenders = {}
    for path in Path("src").glob("*.py"):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        findings = []
        if "Compatibility wrapper for weather." not in text:
            findings.append("missing compatibility docstring")
        if '_TARGET = "weather.' not in text:
            findings.append("missing _TARGET weather module")
        if '_runpy.run_module(_TARGET, run_name="__main__")' not in text:
            findings.append("missing module execution forwarding")
        if findings:
            offenders[str(path)] = findings

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


def test_temperature_rounding_uses_canonical_helper():
    offenders = {}
    for path in Path("src/weather").rglob("*.py"):
        if path in ROUND_HALF_UP_ALLOWED_DEFINITION_MODULES:
            continue
        text = path.read_text(encoding="utf-8")
        matches = [match.group(0) for match in ROUND_HALF_UP_DEFINITION_RE.finditer(text)]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}


def test_package_modules_do_not_use_internal_compatibility_import_fallbacks():
    marker_offenders = {}
    import_error_offenders = {}
    for path in Path("src/weather").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        markers = [marker for marker in COMPATIBILITY_FALLBACK_MARKERS if marker in text]
        if markers:
            marker_offenders[str(path)] = markers
        matches = [match.group(0) for match in IMPORT_ERROR_HANDLER_RE.finditer(text)]
        if matches and path not in ALLOWED_OPTIONAL_IMPORT_ERROR_MODULES:
            import_error_offenders[str(path)] = matches

    assert marker_offenders == {}
    assert import_error_offenders == {}


def test_package_dependency_edges_follow_documented_ratchet():
    assert PACKAGE_BOUNDARY_DOC.exists()
    observed = observed_package_edges()
    documented = ALLOWED_PACKAGE_EDGES | TRANSITIONAL_PACKAGE_EDGES
    undocumented = {
        f"{source}->{target}": sorted(files)
        for (source, target), files in observed.items()
        if target not in SHARED_PACKAGE_ROOTS and (source, target) not in documented
    }
    stale_transitional = {
        f"{source}->{target}"
        for source, target in TRANSITIONAL_PACKAGE_EDGES
        if (source, target) not in observed
    }

    assert undocumented == {}
    assert stale_transitional == set()


def test_model_runtime_uses_calibration_runtime_boundary():
    offenders = {}
    for path in Path("src/weather/model").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        matches = [match.group(0) for match in MODEL_RUNTIME_CALIBRATION_IMPORT_RE.finditer(text)]
        if matches:
            offenders[str(path)] = matches

    assert offenders == {}
