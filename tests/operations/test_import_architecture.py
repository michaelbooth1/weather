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
    Path("src/weather/calibration/pooled_candidate_replay_diagnostics.py"),
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
    Path("src/weather/market/mm_paper_aggregation.py"),
    Path("src/weather/market/mm_paper_evidence.py"),
    Path("src/weather/market/mm_paper_reports.py"),
    Path("src/weather/market/mm_paper_scoring.py"),
    Path("src/weather/market/mm_policy.py"),
    Path("src/weather/market/mm_scoring_projection.py"),
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
    Path("src/weather/operations/structure_inventory.py"),
    Path("src/weather/reporting/data_quality/data_auditor.py"),
    Path("src/weather/reporting/daily/daily_learning_render.py"),
    Path("src/weather/reporting/data_quality/data_layer_audit.py"),
    Path("src/weather/reporting/data_quality/data_layer_audit_collectors.py"),
    Path("src/weather/reporting/data_quality/data_layer_audit_remediation.py"),
    Path("src/weather/reporting/data_quality/data_layer_audit_report.py"),
    Path("src/weather/reporting/casebooks/disagreement_casebook.py"),
    Path("src/weather/reporting/fleet/fleet_observability.py"),
    Path("src/weather/reporting/location_analysis/location_trust.py"),
    Path("src/weather/reporting/candidate_lifecycle/multi_variant_shadow.py"),
    Path("src/weather/reporting/overview_helpers.py"),
    Path("src/weather/reporting/candidate_lifecycle/price_free_model_learning.py"),
    Path("src/weather/reporting/scorecards/progress_audit.py"),
    Path("src/weather/reporting/promotion/promotion_corpus.py"),
    Path("src/weather/reporting/promotion/promotion_gauntlet.py"),
    Path("src/weather/reporting/promotion/promotion_refresh.py"),
    Path("src/weather/reporting/candidate_lifecycle/shadow_ab_monitor.py"),
    Path("src/weather/reporting/scorecards/snapshot_evaluation.py"),
    Path("src/weather/reporting/source_gates/source_redundancy.py"),
    Path("src/weather/reporting/validation/wu_max_since_7_validation.py"),
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


def test_documented_python_module_targets_exist():
    documents = [Path("README.md"), *Path("docs/operations").rglob("*.md")]
    command_pattern = re.compile(r"\bpython\s+-m\s+(weather(?:\.[A-Za-z_]\w*)+)")
    missing = []

    for document in documents:
        text = document.read_text(encoding="utf-8")
        for module in command_pattern.findall(text):
            target = Path("src").joinpath(*module.split("."))
            if target.with_suffix(".py").is_file() or (target / "__main__.py").is_file():
                continue
            missing.append(f"{document}: {module}")

    assert missing == []
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
PROMOTION_REFRESH_IMPL_MODULES = sorted(
    path for path in Path("src/weather/reporting/promotion").glob("*.py")
    if path.name != "__init__.py"
)
FLEET_OBSERVABILITY_SPLIT_MODULES = sorted(
    Path("src/weather/reporting/fleet").glob("fleet_observability_*.py")
)
HOURLY_MODEL_SPLIT_MODULES = sorted(
    Path("src/weather/reporting/hourly").glob("hourly_model_*.py")
)
REPORTING_HOURLY_MODULES = [
    *HOURLY_MODEL_SPLIT_MODULES,
    Path("src/weather/reporting/hourly/candidate_hourly_performance.py"),
    Path("src/weather/reporting/hourly/ten_minute_model_performance.py"),
]
REPORTING_SCORECARD_MODULES = [
    Path("src/weather/reporting/scorecards/distribution_stage_attribution.py"),
    Path("src/weather/reporting/scorecards/frozen_baseline_replay_trend.py"),
    Path("src/weather/reporting/scorecards/model_history.py"),
    Path("src/weather/reporting/scorecards/progress_audit.py"),
    Path("src/weather/reporting/scorecards/proper_scoring_reliability_scorecard.py"),
    Path("src/weather/reporting/scorecards/settled_day_root_cause.py"),
    Path("src/weather/reporting/scorecards/snapshot_evaluation.py"),
    Path("src/weather/reporting/scorecards/weather_only_model_proof_packet.py"),
    Path("src/weather/reporting/scorecards/winner_rank_parity.py"),
]
REPORTING_CASEBOOK_MODULES = [
    Path("src/weather/reporting/casebooks/disagreement_casebook.py"),
    Path("src/weather/reporting/casebooks/taker_tail_casebook.py"),
    Path("src/weather/reporting/casebooks/winner_underpricing_casebook.py"),
]
REPORTING_MARKET_MODULES = [
    Path("src/weather/reporting/market/market_beating_objective_scoreboard.py"),
    Path("src/weather/reporting/market/market_benchmark_residual_edge.py"),
    Path("src/weather/reporting/market/market_making_dashboard.py"),
    Path("src/weather/reporting/market/market_residual_repair_program.py"),
    Path("src/weather/reporting/market/trading_evidence.py"),
]
REPORTING_VALIDATION_MODULES = [
    Path("src/weather/reporting/validation/candidate_rank_sharpening_validation.py"),
    Path("src/weather/reporting/validation/context_guard_validation.py"),
    Path("src/weather/reporting/validation/contextual_winner_validation.py"),
    Path("src/weather/reporting/validation/current_blend_validation.py"),
    Path("src/weather/reporting/validation/forecast_pressure_tilt_validation.py"),
    Path("src/weather/reporting/validation/forecast_side_rank_validation.py"),
    Path("src/weather/reporting/validation/market_anchor_validation.py"),
    Path("src/weather/reporting/validation/variant_basket_selection_validation.py"),
    Path("src/weather/reporting/validation/winner_band_signal_validation.py"),
    Path("src/weather/reporting/validation/winner_boost_validation.py"),
    Path("src/weather/reporting/validation/wu_max_since_7_validation.py"),
]
REPORTING_RESEARCH_MODULES = [
    Path("src/weather/reporting/research/austin_hgb_requalification.py"),
    Path("src/weather/reporting/research/austin_weather_model_hardening.py"),
    Path("src/weather/reporting/research/blocked_market_repair_diagnostics.py"),
    Path("src/weather/reporting/research/bottom_location_winner_centering.py"),
    Path("src/weather/reporting/research/cross_hub_research_audit.py"),
    Path("src/weather/reporting/research/exact_band_distance_zero_calibration.py"),
    Path("src/weather/reporting/research/forecast_double_counting.py"),
    Path("src/weather/reporting/research/forecast_profile_calibration.py"),
    Path("src/weather/reporting/research/forecast_source_state_reliability.py"),
    Path("src/weather/reporting/research/item134_forecast_profile_disposition.py"),
    Path("src/weather/reporting/research/item135_cutoff_regime_disposition.py"),
    Path("src/weather/reporting/research/item136_source_state_disposition.py"),
    Path("src/weather/reporting/research/item138_weak_input_family_gate.py"),
    Path("src/weather/reporting/research/item147_winner_centering_disposition.py"),
    Path("src/weather/reporting/research/item160_candidate_viability_audit.py"),
    Path("src/weather/reporting/research/item186_soil_antecedent_gate.py"),
    Path("src/weather/reporting/research/item186_soil_antecedent_settlement_gate.py"),
    Path("src/weather/reporting/research/item224_active_timesplit_logistic_repair.py"),
    Path("src/weather/reporting/research/item224_no_market_ranked_winner_repair.py"),
    Path("src/weather/reporting/research/item224_no_market_seattle_warm_support_repair.py"),
    Path("src/weather/reporting/research/item48_promotion_readiness_acceptance.py"),
    Path("src/weather/reporting/research/late_day_lock_in_repair.py"),
    Path("src/weather/reporting/research/predawn_weak_slot_parameter_sweep.py"),
    Path("src/weather/reporting/research/predawn_weak_slot_repair.py"),
    Path("src/weather/reporting/research/reanalysis_synoptic_band_ablation.py"),
]
REPORTING_CANDIDATE_LIFECYCLE_MODULES = [
    Path("src/weather/reporting/candidate_lifecycle/active_variant_shadow_refresh.py"),
    Path("src/weather/reporting/candidate_lifecycle/candidate_variant_replay_summary.py"),
    Path("src/weather/reporting/candidate_lifecycle/current_max_trust_retrain_evidence.py"),
    Path("src/weather/reporting/candidate_lifecycle/current_max_trust_retrain_gate.py"),
    Path("src/weather/reporting/candidate_lifecycle/cutoff_regime_weighting.py"),
    Path("src/weather/reporting/candidate_lifecycle/model_market_disagreement_analysis.py"),
    Path("src/weather/reporting/candidate_lifecycle/model_market_disagreement_audit.py"),
    Path("src/weather/reporting/candidate_lifecycle/multi_variant_shadow.py"),
    Path("src/weather/reporting/candidate_lifecycle/price_free_model_learning.py"),
    Path("src/weather/reporting/candidate_lifecycle/repair_integration.py"),
    Path("src/weather/reporting/candidate_lifecycle/shadow_ab_monitor.py"),
    Path("src/weather/reporting/candidate_lifecycle/variant_evidence_growth.py"),
    Path("src/weather/reporting/candidate_lifecycle/variant_registry.py"),
]
REPORTING_SOURCE_GATE_MODULES = [
    Path("src/weather/reporting/source_gates/cross_hub_readiness.py"),
    Path("src/weather/reporting/source_gates/forecast_radiation_gate.py"),
    Path("src/weather/reporting/source_gates/forecast_smoke_gate.py"),
    Path("src/weather/reporting/source_gates/forecast_smoke_slice_prep.py"),
    Path("src/weather/reporting/source_gates/global_model_guidance_gate.py"),
    Path("src/weather/reporting/source_gates/marine_contrast_gate.py"),
    Path("src/weather/reporting/source_gates/nbm_probabilistic_tmax_gate.py"),
    Path("src/weather/reporting/source_gates/nbm_probabilistic_tmax_settlement_scoring.py"),
    Path("src/weather/reporting/source_gates/official_guidance_sparse_coverage.py"),
    Path("src/weather/reporting/source_gates/physical_feature_family_ratchet.py"),
    Path("src/weather/reporting/source_gates/settlement_source_audit.py"),
    Path("src/weather/reporting/source_gates/source_family_inventory.py"),
    Path("src/weather/reporting/source_gates/source_family_inventory_report.py"),
    Path("src/weather/reporting/source_gates/source_redundancy.py"),
    Path("src/weather/reporting/source_gates/weak_input_family_disposition.py"),
]
REPORTING_SERVING_GATE_MODULES = [
    Path("src/weather/reporting/serving_gates/early_hour_positive_daily_first_gate.py"),
    Path("src/weather/reporting/serving_gates/model_scoring_liveness.py"),
    Path("src/weather/reporting/serving_gates/runtime_identity_evidence.py"),
    Path("src/weather/reporting/serving_gates/runtime_identity_reconciliation.py"),
    Path("src/weather/reporting/serving_gates/served_distribution_calibration_contract.py"),
    Path("src/weather/reporting/serving_gates/serving_ordinal_smoothing_gate.py"),
]
REPORTING_LOCATION_ANALYSIS_MODULES = [
    Path("src/weather/reporting/location_analysis/extra_location_registry.py"),
    Path("src/weather/reporting/location_analysis/june23_location_bias_repair.py"),
    Path("src/weather/reporting/location_analysis/location_similarity_pooling.py"),
    Path("src/weather/reporting/location_analysis/location_trust.py"),
    Path("src/weather/reporting/location_analysis/no_market_location_transfer.py"),
    Path("src/weather/reporting/location_analysis/pooled_f_retrain_location_gate.py"),
]
REPORTING_ROADMAP_MODULES = [
    Path("src/weather/reporting/roadmap/roadmap_backlog.py"),
]
REPORTING_DATA_QUALITY_EXTRA_MODULES = [
    Path("src/weather/reporting/data_quality/backtest_artifact_retention.py"),
    Path("src/weather/reporting/data_quality/per_location_artifact_quarantine.py"),
]
REPORTING_RETIRED_ROOT_WRAPPER_NAMES = {
    "promotion_refresh_cli.py",
    "promotion_refresh_decisions.py",
    "promotion_refresh_gap_analysis.py",
    "promotion_refresh_orchestration.py",
    "promotion_refresh_readers.py",
    "promotion_refresh_report.py",
}
REPORTING_SAFE_SLICE_MODULES = [
    Path("src/weather/reporting/fleet/fleet_observability.py"),
    *FLEET_OBSERVABILITY_SPLIT_MODULES,
    Path("src/weather/reporting/data_quality/artifact_disk_budget.py"),
    *REPORTING_DATA_QUALITY_EXTRA_MODULES,
    Path("src/weather/reporting/data_quality/clob_coverage_audit.py"),
    Path("src/weather/reporting/data_quality/data_auditor.py"),
    Path("src/weather/reporting/data_quality/data_layer_audit.py"),
    Path("src/weather/reporting/data_quality/data_layer_audit_collectors.py"),
    Path("src/weather/reporting/data_quality/data_layer_audit_remediation.py"),
    Path("src/weather/reporting/data_quality/data_layer_audit_report.py"),
    Path("src/weather/reporting/data_quality/data_retention_inventory.py"),
    Path("src/weather/reporting/data_quality/feature_quality_quarantine.py"),
    Path("src/weather/reporting/data_quality/reanalysis_sidecar_coverage_audit.py"),
    Path("src/weather/reporting/daily/daily_flow_analysis.py"),
    Path("src/weather/reporting/daily/daily_learning.py"),
    Path("src/weather/reporting/daily/daily_learning_render.py"),
    Path("src/weather/reporting/daily/daily_learning_scorecard.py"),
    Path("src/weather/reporting/daily/daily_progress_ledger.py"),
    Path("src/weather/reporting/daily/daily_rollup_freshness.py"),
    *PROMOTION_REFRESH_IMPL_MODULES,
    *REPORTING_HOURLY_MODULES,
    *REPORTING_SCORECARD_MODULES,
    *REPORTING_CASEBOOK_MODULES,
    *REPORTING_MARKET_MODULES,
    *REPORTING_VALIDATION_MODULES,
    *REPORTING_RESEARCH_MODULES,
    *REPORTING_CANDIDATE_LIFECYCLE_MODULES,
    *REPORTING_SOURCE_GATE_MODULES,
    *REPORTING_SERVING_GATE_MODULES,
    *REPORTING_LOCATION_ANALYSIS_MODULES,
    *REPORTING_ROADMAP_MODULES,
]
REPORTING_SAFE_SLICE_ROOT_NAMES = {
    path.name
    for path in REPORTING_SAFE_SLICE_MODULES
    if path.name != "__init__.py"
} | REPORTING_RETIRED_ROOT_WRAPPER_NAMES
REPORTING_ROOT_SHARED_MODULES = {
    "__init__.py",
    "formatting.py",
    "overview_helpers.py",
}
DAILY_REFRESH_SPLIT_MODULES = sorted(Path("src/weather/operations").glob("daily_refresh_*.py"))
TARGET_MODULES.extend(
    POOLED_FEATURE_SPLIT_MODULES
    + TAKER_BOT_SPLIT_MODULES
    + FLEET_OBSERVABILITY_SPLIT_MODULES
    + REPORTING_SAFE_SLICE_MODULES
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
WRAPPER_MODULE_PATTERN = "|".join(re.escape(name) for name in WRAPPER_MODULE_NAMES) or r"(?!)"

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
    r"mm_paper_aggregation|mm_paper_constants|mm_paper_evidence|mm_paper_reports|mm_paper_scoring|"
    r"mm_policy|mm_scoring_projection|model_constants|model_identity|"
    r"model_presentation|model_sources|"
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
    + WRAPPER_MODULE_PATTERN
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
    Path("src/weather/calibration/pooled_candidate_replay_diagnostics.py"): re.compile(
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
    Path("src/weather/market/mm_paper_scoring.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.market\.mm_paper|\.mm_paper)\s+import\b|"
        r"import\s+weather\.market\.mm_paper\b)",
        re.MULTILINE,
    ),
    Path("src/weather/market/mm_paper_aggregation.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.market\.mm_paper|\.mm_paper)\s+import\b|"
        r"import\s+weather\.market\.mm_paper\b)",
        re.MULTILINE,
    ),
    Path("src/weather/reporting/data_quality/data_layer_audit_remediation.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.reporting\.data_quality\.data_layer_audit|\.data_layer_audit)\s+import\b|"
        r"import\s+weather\.reporting\.data_quality\.data_layer_audit\b)",
        re.MULTILINE,
    ),
    Path("src/weather/reporting/data_quality/data_layer_audit_collectors.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.reporting\.data_quality\.data_layer_audit|\.data_layer_audit)\s+import\b|"
        r"import\s+weather\.reporting\.data_quality\.data_layer_audit\b)",
        re.MULTILINE,
    ),
    Path("src/weather/reporting/daily/daily_learning_render.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.reporting\.daily\.daily_learning|\.daily_learning)\s+import\b|"
        r"import\s+weather\.reporting\.daily\.daily_learning\b)",
        re.MULTILINE,
    ),
    Path("src/weather/reporting/daily/daily_learning_scorecard.py"): re.compile(
        r"^\s*(?:from\s+(?:weather\.reporting\.daily\.daily_learning|\.daily_learning)\s+import\b|"
        r"import\s+weather\.reporting\.daily\.daily_learning\b)",
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
    for path in PROMOTION_REFRESH_SPLIT_MODULES + PROMOTION_REFRESH_IMPL_MODULES
})
EXTRACTED_MODULE_IMPORT_RULES.update({
    path: re.compile(
        r"^\s*(?:from\s+(?:weather\.reporting\.fleet\.fleet_observability|\.fleet_observability)\s+import\b|"
        r"import\s+weather\.reporting\.fleet\.fleet_observability\b)",
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
    "runtime_identity",
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
    ("operations", "calibration"),
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
    ("operations", "reporting"),
    ("reporting", "calibration"),
    ("reporting", "operations"),
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
    Path("src/weather"),
    Path("tests"),
    Path("tools"),
    Path("scripts"),
    Path("docs/operations"),
]

FIRST_PARTY_SHIM_CALL_RE = re.compile(
    r"pythonw?\.exe\s+-m\s+src\.|"
    r"python\s+-m\s+src\.|"
    r"-m\s+src\.|"
    r"(?:pythonw?\.exe|python)\s+(?:\.\\|\./)?(?:backfill_all|scratch)\.py|"
    r"(?:^|[\s`'\"])(?:&\s*)?(?:\.\\|\./)train_all_markets\.ps1|"
    r"streamlit\s+run\s+app\.py|"
    r"AppTest\.from_file\(\s*['\"]app\.py['\"]\s*\)|"
    r"(?:^|[\s`'\"])(?:\.\\)?scripts\\(?!ops\\|launch\\)"
    r"(?:register_[A-Za-z0-9_]+\.ps1|start_weather_dashboard\.(?:cmd|ps1|vbs))|"
    r"(?:^|[\s`'\"])(?:\./)?scripts/(?!ops/|launch/)"
    r"(?:register_[A-Za-z0-9_]+\.ps1|start_weather_dashboard\.(?:cmd|ps1|vbs))",
    re.MULTILINE,
)

FIRST_PARTY_SHIM_CALL_SCAN_EXCLUDED = {
    Path("src/weather/operations/structure_inventory.py"),
    Path("tests/operations/test_import_architecture.py"),
    Path("tests/operations/test_structure_inventory.py"),
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


def test_reporting_safe_slice_modules_stay_in_subpackages():
    missing = [
        str(path)
        for path in REPORTING_SAFE_SLICE_MODULES
        if not path.exists()
    ]
    root_offenders = sorted(
        path.name
        for path in Path("src/weather/reporting").glob("*.py")
        if path.name in REPORTING_SAFE_SLICE_ROOT_NAMES
    )

    assert missing == []
    assert root_offenders == []


def test_reporting_root_modules_are_shared_helpers_only():
    actual_root_modules = {
        path.name
        for path in Path("src/weather/reporting").glob("*.py")
    }

    assert actual_root_modules == REPORTING_ROOT_SHARED_MODULES


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


def test_paid_provider_weather_policy_terms_do_not_regress():
    forbidden_terms = [
        "Weather" + ".com",
        "api" + ".weather" + ".com",
        "DEFAULT_WU_PROVIDER" + "_API_KEY",
        "OPTIONAL_WEATHER_PROVIDER" + "_API_KEY",
    ]
    scan_roots = [Path("README.md"), Path("app"), Path("config"), Path("docs"), Path("src"), Path("tests")]
    offenders = {}
    for root in scan_roots:
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if not path.is_file():
                continue
            if "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            matches = [term for term in forbidden_terms if term in text]
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


def test_compatibility_shim_surfaces_remain_retired():
    offenders = [
        *(
            str(path)
            for path in Path("src").glob("*.py")
            if path.name != "__init__.py"
        ),
        *(
            str(path)
            for path in (
                Path("app.py"),
                Path("backfill_all.py"),
                Path("scratch.py"),
                Path("train_all_markets.ps1"),
            )
            if path.exists()
        ),
        *(str(path) for path in Path("scripts").glob("*") if path.is_file()),
    ]

    assert sorted(offenders) == []


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
