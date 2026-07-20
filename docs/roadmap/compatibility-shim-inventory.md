# Compatibility Shim Inventory

Generated for roadmap item 87 and retired by roadmap item 206. The historical
registry below records the migration from the flat `src.*` interface to
canonical `weather.*` package modules.

Policy: first-party app code, tests, README commands, scheduled tasks, GitHub
Actions, and reusable tools use canonical `weather.*`, `app/streamlit_app.py`,
`scripts/ops/*`, `scripts/launch/*`, or `tools/*` surfaces. Retired shim paths
must not be reintroduced.

## Expiration Policy

Migration window start: 2026-06-18.

Minimum migration window: 30 days.

Default expiration date: 2026-07-18.

Current removal status: **complete 2026-07-20**. The caller, scheduler,
desktop-launcher, CI, runbook, script, test, and reusable-tool scans found no
external dependency requiring retention. All 103 expired shims were removed.

The supported first-party surfaces are:

- `python -m weather...` module commands.
- `app/streamlit_app.py` for direct Streamlit execution.
- `scripts/ops/*` for scheduled-task registration.
- `scripts/launch/*` for dashboard launchers.
- `tools/*` for reusable helper scripts.

The former fallback paths (`python -m src.<module>`, root `app.py`, root helper
copies, and files directly under `scripts/`) are unsupported and absent.

## Shim Classes

| Historical class | Pre-removal count | Current count | Disposition |
| --- | ---: | ---: | --- |
| Flat Python module wrappers under `src/*.py` | 85 | 0 | Removed 2026-07-20. `src/__init__.py` remains as the intentional namespace/bootstrap file, not a wrapper. |
| Root Streamlit wrapper `app.py` | 1 | 0 | Removed 2026-07-20; use `app/streamlit_app.py`. |
| Root helper wrappers `backfill_all.py`, `scratch.py`, `train_all_markets.ps1` | 3 | 0 | Removed 2026-07-20; use the matching `tools/*` helper. |
| Root scheduled-task and dashboard scripts under `scripts/*` | 14 | 0 | Removed 2026-07-20; use matching `scripts/ops/*` or `scripts/launch/*` scripts. |

Current total: **0 compatibility shims**. Historical removal total: 103.
Retained shims: **none**.

The retirement ratchets live in:

- `tests/operations/test_import_architecture.py::test_compatibility_shim_surfaces_remain_retired`,
  which forbids all four retired filesystem classes.
- `tests/operations/test_import_architecture.py::test_first_party_surfaces_do_not_call_compatibility_shims`,
  which scans README, CI, app, canonical source, tests, tools, scripts, and
  active operations docs for retired command paths.
- `tests/operations/test_structure_inventory.py::test_repository_compatibility_shim_surfaces_are_retired`,
  which requires every inventory class and the exact path list to remain empty.

## 2026-07-20 Execution Record

- Fresh caller gate: `1 passed` before removal.
- Fresh structure inventory: `tracked=1457 source_py=405 shims=103`; schema
  `structure_inventory_v0.2` recorded 103 unique shim paths. The tracked count
  is one above the work-order pre-scan because the work-order file itself was
  added in the base commit.
- Task Scheduler: 215 actions checked across all tasks, including 17
  `Weather*` tasks; zero exact shim-path or `-m src.*` hits.
- Desktop: 11 top-level shortcuts checked; no weather launcher or shim target.
- Repository scan: no active README, operations-doc, CI, app, test, tool,
  script, or reusable-runbook dependency. One stale canonical reporting
  recommendation was migrated from `scripts/register_clob_supervisor.ps1` to
  `scripts/ops/register_clob_supervisor.ps1` before removal.
- Removed batches: 85 flat Python wrappers, one root Streamlit wrapper, three
  root helper wrappers, and 14 root scripts. No shim was retained.
- Post-removal structure inventory: `shims=0 paths=0`.

## Historical Non-Flat Shim Registry

The 18 removed non-flat paths were:

- `app.py`, `backfill_all.py`, `scratch.py`, and `train_all_markets.ps1`.
- `scripts/register_clob_supervisor.ps1`
- `scripts/register_daily_refresh.ps1`
- `scripts/register_exchange_economics_refresh.ps1`
- `scripts/register_market_making_daily_roll.ps1`
- `scripts/register_market_making_daily_roll_supervisor.ps1`
- `scripts/register_model_market_disagreement_analysis.ps1`
- `scripts/register_nightly_retrain.ps1`
- `scripts/register_observation_trigger_supervisor.ps1`
- `scripts/register_snapshot_supervisor.ps1`
- `scripts/register_taker_bot_daily_roll.ps1`
- `scripts/register_taker_bot_daily_roll_supervisor.ps1`
- `scripts/start_weather_dashboard.cmd`
- `scripts/start_weather_dashboard.ps1`
- `scripts/start_weather_dashboard_silent.vbs`

## Historical Flat Python Wrapper Registry

The table below preserves the pre-removal target mapping. Its allowed-caller
and removal-condition columns describe the completed migration window; every
listed wrapper was removed on 2026-07-20.

| Wrapper | Target / Owner | Former Allowed Caller | Satisfied Removal Condition |
| --- | --- | --- | --- |
| `src/artifacts.py` | `weather.artifacts` | External/local legacy commands only | No first-party callers for one migration window |
| `src/backtest.py` | `weather.backtesting.backtest` | External/local legacy commands only | No first-party callers for one migration window |
| `src/canonical_history_guardrails.py` | `weather.sources.canonical_history_guardrails` | External/local legacy commands only | No first-party callers for one migration window |
| `src/clob_recon.py` | `weather.market.clob_recon` | External/local legacy commands only | No first-party callers for one migration window |
| `src/collection_health.py` | `weather.collection.collection_health` | External/local legacy commands only | No first-party callers for one migration window |
| `src/daily_refresh.py` | `weather.operations.daily_refresh` | External/local legacy commands only | No first-party callers for one migration window |
| `src/daily_summary.py` | `weather.sources.daily_summary` | External/local legacy commands only | No first-party callers for one migration window |
| `src/data_auditor.py` | `weather.reporting.data_quality.data_auditor` | External/local legacy commands only | No first-party callers for one migration window |
| `src/data_ingestion.py` | `weather.collection.data_ingestion` | External/local legacy commands only | No first-party callers for one migration window |
| `src/data_layer_audit.py` | `weather.reporting.data_quality.data_layer_audit` | External/local legacy commands only | No first-party callers for one migration window |
| `src/disagreement_casebook.py` | `weather.reporting.casebooks.disagreement_casebook` | External/local legacy commands only | No first-party callers for one migration window |
| `src/eccc_history.py` | `weather.sources.eccc_history` | External/local legacy commands only | No first-party callers for one migration window |
| `src/eccc_swob_history.py` | `weather.sources.eccc_swob_history` | External/local legacy commands only | No first-party callers for one migration window |
| `src/family_secondary_artifacts.py` | `weather.calibration.family_secondary_artifacts` | External/local legacy commands only | No first-party callers for one migration window |
| `src/feature_model.py` | `weather.calibration.feature_model` | External/local legacy commands only | No first-party callers for one migration window |
| `src/feature_probability_calibration.py` | `weather.calibration.feature_probability_calibration` | External/local legacy commands only | No first-party callers for one migration window |
| `src/feature_store.py` | `weather.model.feature_store` | External/local legacy commands only | No first-party callers for one migration window |
| `src/fleet_observability.py` | `weather.reporting.fleet.fleet_observability` | External/local legacy commands only | No first-party callers for one migration window |
| `src/forecast_archive.py` | `weather.collection.forecast_archive` | External/local legacy commands only | No first-party callers for one migration window |
| `src/forecast_error_model.py` | `weather.calibration.forecast_error_model` | External/local legacy commands only | No first-party callers for one migration window |
| `src/forecast_history.py` | `weather.sources.forecast_history` | External/local legacy commands only | No first-party callers for one migration window |
| `src/forecast_tracker.py` | `weather.collection.forecast_tracker` | External/local legacy commands only | No first-party callers for one migration window |
| `src/historical_backfill_plan.py` | `weather.collection.historical_backfill_plan` | External/local legacy commands only | No first-party callers for one migration window |
| `src/historical_backfill_runner.py` | `weather.collection.historical_backfill_runner` | External/local legacy commands only | No first-party callers for one migration window |
| `src/historical_coverage.py` | `weather.sources.historical_coverage` | External/local legacy commands only | No first-party callers for one migration window |
| `src/historical_schema.py` | `weather.sources.historical_schema` | External/local legacy commands only | No first-party callers for one migration window |
| `src/intraday_calibration.py` | `weather.calibration.intraday_calibration` | External/local legacy commands only | No first-party callers for one migration window |
| `src/location_trust.py` | `weather.reporting.location_analysis.location_trust` | External/local legacy commands only | No first-party callers for one migration window |
| `src/market_config.py` | `weather.market.market_config` | External/local legacy commands only | No first-party callers for one migration window |
| `src/market_day_labels.py` | `weather.market.market_day_labels` | External/local legacy commands only | No first-party callers for one migration window |
| `src/market_making_daily_roll.py` | `weather.operations.market_making_daily_roll` | External/local legacy commands only | No first-party callers for one migration window |
| `src/market_making_run.py` | `weather.market.market_making_run` | External/local legacy commands only | No first-party callers for one migration window |
| `src/market_microstructure.py` | `weather.market.market_microstructure` | External/local legacy commands only | No first-party callers for one migration window |
| `src/market_microstructure_features.py` | `weather.market.market_microstructure_features` | External/local legacy commands only | No first-party callers for one migration window |
| `src/market_registry.py` | `weather.market.market_registry` | External/local legacy commands only | No first-party callers for one migration window |
| `src/metar_history.py` | `weather.sources.metar_history` | External/local legacy commands only | No first-party callers for one migration window |
| `src/mm_exchange.py` | `weather.market.mm_exchange` | External/local legacy commands only | No first-party callers for one migration window |
| `src/mm_paper.py` | `weather.market.mm_paper` | External/local legacy commands only | No first-party callers for one migration window |
| `src/mm_policy.py` | `weather.market.mm_policy` | External/local legacy commands only | No first-party callers for one migration window |
| `src/mm_risk.py` | `weather.market.mm_risk` | External/local legacy commands only | No first-party callers for one migration window |
| `src/model_base.py` | `weather.model.model_base` | External/local legacy commands only | No first-party callers for one migration window |
| `src/model_climatology.py` | `weather.model.model_climatology` | External/local legacy commands only | No first-party callers for one migration window |
| `src/model_constants.py` | `weather.model.model_constants` | External/local legacy commands only | No first-party callers for one migration window |
| `src/model_distribution.py` | `weather.model.model_distribution` | External/local legacy commands only | No first-party callers for one migration window |
| `src/model_ensemble.py` | `weather.calibration.model_ensemble` | External/local legacy commands only | No first-party callers for one migration window |
| `src/model_features.py` | `weather.model.model_features` | External/local legacy commands only | No first-party callers for one migration window |
| `src/model_history.py` | `weather.reporting.scorecards.model_history` | External/local legacy commands only | No first-party callers for one migration window |
| `src/model_identity.py` | `weather.model.model_identity` | External/local legacy commands only | No first-party callers for one migration window |
| `src/model_presentation.py` | `weather.model.model_presentation` | External/local legacy commands only | No first-party callers for one migration window |
| `src/model_sources.py` | `weather.model.model_sources` | External/local legacy commands only | No first-party callers for one migration window |
| `src/multi_variant_shadow.py` | `weather.reporting.candidate_lifecycle.multi_variant_shadow` | External/local legacy commands only | No first-party callers for one migration window |
| `src/nightly_retrain.py` | `weather.operations.nightly_retrain` | External/local legacy commands only | No first-party callers for one migration window |
| `src/noaa_ghcnh_history.py` | `weather.sources.noaa_ghcnh_history` | External/local legacy commands only | No first-party callers for one migration window |
| `src/observation_trigger.py` | `weather.operations.observation_trigger` | External/local legacy commands only | No first-party callers for one migration window |
| `src/ops_monitor.py` | `weather.operations.ops_monitor` | External/local legacy commands only | No first-party callers for one migration window |
| `src/overview_helpers.py` | `weather.reporting.overview_helpers` | External/local legacy commands only | No first-party callers for one migration window |
| `src/polymarket_client.py` | `weather.market.polymarket_client` | External/local legacy commands only | No first-party callers for one migration window |
| `src/pooled_candidate_replay.py` | `weather.calibration.pooled_candidate_replay` | External/local legacy commands only | No first-party callers for one migration window |
| `src/pooled_feature_model.py` | `weather.calibration.pooled_feature_model` | External/local legacy commands only | No first-party callers for one migration window |
| `src/probability_calibration.py` | `weather.calibration.probability_calibration` | External/local legacy commands only | No first-party callers for one migration window |
| `src/progress_audit.py` | `weather.reporting.scorecards.progress_audit` | External/local legacy commands only | No first-party callers for one migration window |
| `src/promotion_corpus.py` | `weather.reporting.promotion.promotion_corpus` | External/local legacy commands only | No first-party callers for one migration window |
| `src/promotion_gauntlet.py` | `weather.reporting.promotion.promotion_gauntlet` | External/local legacy commands only | No first-party callers for one migration window |
| `src/promotion_refresh.py` | `weather.reporting.promotion.promotion_refresh` | External/local legacy commands only | No first-party callers for one migration window |
| `src/reanalysis_history.py` | `weather.sources.reanalysis_history` | External/local legacy commands only | No first-party callers for one migration window |
| `src/reanalysis_synoptic.py` | `weather.sources.reanalysis_synoptic` | External/local legacy commands only | No first-party callers for one migration window |
| `src/replay.py` | `weather.backtesting.replay` | External/local legacy commands only | No first-party callers for one migration window |
| `src/replay_ablation.py` | `weather.backtesting.replay_ablation` | External/local legacy commands only | No first-party callers for one migration window |
| `src/replay_backtest.py` | `weather.backtesting.replay_backtest` | External/local legacy commands only | No first-party callers for one migration window |
| `src/runtime_identity.py` | `weather.runtime_identity` | External/local legacy commands only | No first-party callers for one migration window |
| `src/schema_registry.py` | `weather.schema_registry` | External/local legacy commands only | No first-party callers for one migration window |
| `src/settled_days.py` | `weather.backtesting.settled_days` | External/local legacy commands only | No first-party callers for one migration window |
| `src/settlement_lag_model.py` | `weather.calibration.settlement_lag_model` | External/local legacy commands only | No first-party callers for one migration window |
| `src/settlement_ledger.py` | `weather.backtesting.settlement_ledger` | External/local legacy commands only | No first-party callers for one migration window |
| `src/shadow_ab_monitor.py` | `weather.reporting.candidate_lifecycle.shadow_ab_monitor` | External/local legacy commands only | No first-party callers for one migration window |
| `src/snapshot_analytics.py` | `weather.backtesting.snapshot_analytics` | External/local legacy commands only | No first-party callers for one migration window |
| `src/snapshot_evaluation.py` | `weather.reporting.scorecards.snapshot_evaluation` | External/local legacy commands only | No first-party callers for one migration window |
| `src/snapshot_tracker.py` | `weather.collection.snapshot_tracker` | External/local legacy commands only | No first-party callers for one migration window |
| `src/source_redundancy.py` | `weather.reporting.source_gates.source_redundancy` | External/local legacy commands only | No first-party callers for one migration window |
| `src/supplemental_station_validation.py` | `weather.sources.supplemental_station_validation` | External/local legacy commands only | No first-party callers for one migration window |
| `src/supplemental_stations.py` | `weather.sources.supplemental_stations` | External/local legacy commands only | No first-party callers for one migration window |
| `src/toronto_model.py` | `weather.model.toronto_model` | External/local legacy commands only | No first-party callers for one migration window |
| `src/variant_evidence_growth.py` | `weather.reporting.candidate_lifecycle.variant_evidence_growth` | External/local legacy commands only | No first-party callers for one migration window |
| `src/wu_history.py` | `weather.sources.wu_history` | External/local legacy commands only | No first-party callers for one migration window |
| `src/wu_max_since_7_validation.py` | `weather.reporting.validation.wu_max_since_7_validation` | External/local legacy commands only | No first-party callers for one migration window |
