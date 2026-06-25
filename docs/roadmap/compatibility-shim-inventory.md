# Compatibility Shim Inventory

Generated for roadmap item 87. These wrappers are retained only for external or local legacy commands during the migration from the flat `src.*` interface to canonical `weather.*` package modules.

Policy: first-party app code, tests, README commands, scheduled tasks, GitHub Actions, and reusable tools should call the target `weather.*` module directly. The owner of each wrapper is the target module. Removal is allowed after one clean migration window with no first-party callers and no known external automation depending on the wrapper.

## Expiration Policy

Migration window start: 2026-06-18.

Minimum migration window: 30 days.

Default expiration date: 2026-07-18.

Current removal status: retain compatibility shims until 2026-07-18 as
external/local operator fallback only. After that date, any shim group whose
first-party caller scan is clean and has no known external automation
dependency is eligible for removal. Expired shims should be deleted in batches
instead of kept as permanent aliases.

The supported first-party surfaces during the migration window are:

- `python -m weather...` module commands.
- `app/streamlit_app.py` for direct Streamlit execution.
- `scripts/ops/*` for scheduled-task registration.
- `scripts/launch/*` for dashboard launchers.
- `tools/*` for reusable helper scripts.

The temporary operator fallback is the existing root-level shim surface:
`python -m src.<module>`, `app.py`, `backfill_all.py`, `scratch.py`,
`train_all_markets.ps1`, and root `scripts/*.ps1` or
`scripts/start_weather_dashboard.*` launchers. These fallback paths are
external/local legacy entrypoints only and should not be added to new runbooks,
tests, scheduled tasks, CI, or reusable tools.

## Shim Classes

| Class | Count | Owner | Allowed caller | Expiration | Removal status |
| --- | ---: | --- | --- | --- | --- |
| Flat Python module wrappers under `src/*.py` | 86 | Target `weather.*` module | External/local legacy commands only | 2026-07-18 | Retain until expiration, then remove wrappers whose caller scan stays clean. |
| Root Streamlit wrapper `app.py` | 1 | `app/streamlit_app.py` | External/local legacy dashboard launches only | 2026-07-18 | Retain until expiration; first-party launchers use `app/streamlit_app.py`. |
| Root helper wrappers `backfill_all.py`, `scratch.py`, `train_all_markets.ps1` | 3 | Matching `tools/*` helper | External/local legacy helper invocations only | 2026-07-18 | Retain until expiration; first-party docs use `tools/*`. |
| Root scheduled-task and dashboard scripts under `scripts/*` | 9 | Matching `scripts/ops/*` or `scripts/launch/*` script | External/local legacy operator invocations only | 2026-07-18 | Retain until expiration; first-party docs use `scripts/ops/*` and `scripts/launch/*`. |

The caller ratchet lives in
`tests/operations/test_import_architecture.py::test_first_party_surfaces_do_not_call_compatibility_shims`.
It scans README, CI, app, tests, tools, scripts, and active operations docs for
`python -m src.*`, direct `app.py` Streamlit/Test usage, and root script shim
paths.

## 2026-07-18 Review Checklist

Owner: roadmap item 206.

Before the removal window opens:

- [ ] Keep first-party docs, tests, CI, scheduled-task setup, and reusable tools
  on canonical `weather.*`, `app/streamlit_app.py`, `scripts/ops/*`,
  `scripts/launch/*`, and `tools/*` paths.
- [ ] Keep
  `tests/operations/test_import_architecture.py::test_first_party_surfaces_do_not_call_compatibility_shims`
  green.

On or after 2026-07-18:

- [ ] Run the first-party caller scan:
  `python -m pytest tests/operations/test_import_architecture.py::test_first_party_surfaces_do_not_call_compatibility_shims -q`.
- [ ] Run the structure inventory and save a local ignored report:
  `python -m weather.operations.structure_inventory --report data\backtest\structure_inventory_report.md`.
- [ ] Check local scheduled tasks, operator shortcuts, and desktop launch paths
  for direct shim usage outside Git.
- [ ] Remove shim batches whose first-party scan is clean and whose external
  dependency check has no known blocker.
- [ ] For every retained shim batch, update this inventory with owner,
  concrete dependency, next review date, and reason it could not be removed.

## Flat Python Wrappers

| Wrapper | Target / Owner | Current Allowed Caller | Removal Condition |
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
| `src/tape_backup.py` | `weather.operations.tape_backup` | External/local legacy commands only | No first-party callers for one migration window |
| `src/toronto_model.py` | `weather.model.toronto_model` | External/local legacy commands only | No first-party callers for one migration window |
| `src/variant_evidence_growth.py` | `weather.reporting.candidate_lifecycle.variant_evidence_growth` | External/local legacy commands only | No first-party callers for one migration window |
| `src/wu_history.py` | `weather.sources.wu_history` | External/local legacy commands only | No first-party callers for one migration window |
| `src/wu_max_since_7_validation.py` | `weather.reporting.validation.wu_max_since_7_validation` | External/local legacy commands only | No first-party callers for one migration window |
