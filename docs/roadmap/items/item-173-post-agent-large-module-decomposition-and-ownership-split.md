# 173. Post-Agent Large Module Decomposition And Ownership Split [COMPLETE 2026-06-20 - FACADES SPLIT AND SIZE AUDIT RATIFIED]

Goal: split the newly grown large modules into explicit ownership boundaries
after active agent work is merged, without disrupting current in-flight edits.

Source: the 2026-06-20 full repository cleanup audit. Several modules have
grown past comfortable review and ownership size, including
`weather.calibration.pooled_feature_model`, `weather.market.taker_bot`,
`weather.reporting.promotion_refresh`,
`weather.reporting.fleet_observability`, and
`weather.reporting.hourly_model_performance`. `taker_bot` and
`promotion_refresh` are also actively modified by other agents.

Why this matters: these files now mix orchestration, schema definitions,
business rules, report rendering, CLI parsing, and test fixtures. Continuing to
add features in place will increase merge conflicts and make architecture
ratchets less useful.

## Design

1. Wait until active agent changes in the affected files are merged or clearly
   abandoned.
2. For each large file, write a one-page ownership map before moving code.
3. Split behavior behind existing public module or CLI facades so callers do
   not change in the same step.
4. Add focused tests around each extracted boundary before deleting old helper
   paths.
5. Update package-boundary documentation and dependency ratchets after the
   splits stabilize.

- [x] Split `weather.market.taker_bot` into strategy registry, strategy
  evaluation, sizing/risk, bakeoff/reporting, tape IO, and CLI facade modules.
- [x] Split `weather.reporting.promotion_refresh` into gate readers,
  mitigation evaluation, report rendering, and orchestration modules.
- [x] Split `weather.calibration.pooled_feature_model` into feature assembly,
  training, validation, artifact IO, and serving helpers.
- [x] Review `fleet_observability` and `hourly_model_performance` for shared
  slot scoring, gate rendering, and report utility extraction.
- [x] Keep compatibility facades until import architecture tests and active
  callers prove the new surfaces are stable.
- [x] Add a "no new 2k-line module" architecture warning or audit report.

Acceptance: the largest operational files are decomposed around stable
runtime/reporting/model boundaries, existing CLIs continue to work, and package
dependency ratchets document the new ownership model.

## 2026-06-20 completion

Completed the unlocked decomposition behind stable public facades:

- Extracted dynamic source-state feature transforms from
  `weather.calibration.pooled_feature_model` into
  `weather.calibration.pooled_feature_source_state`.
- Split `weather.calibration.pooled_feature_model` into
  `pooled_feature_assembly`, `pooled_density_training`,
  `pooled_band_training`, `pooled_training`, `pooled_artifact_io`,
  `pooled_reporting`, and `pooled_feature_cli`.
- Split `weather.market.taker_bot` into `taker_bot_strategy_registry`,
  `taker_bot_tape_io`, `taker_bot_strategy_evaluation`,
  `taker_bot_sizing`, `taker_bot_scoring`, `taker_bot_reporting`,
  `taker_bot_bakeoff`, `taker_bot_finalization`, and `taker_bot_cli`.
- Split `weather.reporting.promotion_refresh` into
  `promotion_refresh_readers`, `promotion_refresh_decisions`,
  `promotion_refresh_gap_analysis`, `promotion_refresh_report`,
  `promotion_refresh_orchestration`, and `promotion_refresh_cli`.
- Split `weather.reporting.fleet_observability` into
  `fleet_observability_inventory`, `fleet_observability_loops`,
  `fleet_observability_gates`, `fleet_observability_payload`,
  `fleet_observability_render`, and `fleet_observability_cli`.
- Split `weather.reporting.hourly_model_performance` into
  `hourly_model_scoring`, `hourly_model_slots`, `hourly_model_gate`,
  `hourly_model_context`, `hourly_model_render`, and `hourly_model_cli`.
- Kept the old public modules as compatibility facades, so current callers,
  CLIs, and tests continue to import the same public names.
- Added direct owner tests in
  `tests/calibration/test_pooled_feature_source_state.py`.
- Added an import-architecture guard so
  `pooled_feature_source_state` cannot import back from
  `pooled_feature_model`.
- Added `weather.operations.module_size_audit`, schema
  `module_size_audit_v0.1`, and the operator map
  `docs/operations/module-ownership-map.md`.

The generated audit command:

```powershell
python -m weather.operations.module_size_audit --out data\backtest\module_size_audit.json --report data\backtest\module_size_audit_report.md
```

reported `230` Python modules and `1` module above the `2000`-line warning
threshold. The remaining warning is `weather.operations.daily_refresh`, which
is tracked in the ownership map but is not one of the five item-173 target
modules.

Verification:

- `python -m pytest -q tests\market\test_taker_bot.py tests\calibration\test_pooled_feature_model.py tests\calibration\test_pooled_feature_source_state.py tests\calibration\test_promotion_refresh.py tests\reporting\test_fleet_observability.py tests\reporting\test_hourly_model_performance.py tests\operations\test_module_size_audit.py tests\operations\test_import_architecture.py`
  passed with 146 tests.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - FACADES SPLIT AND SIZE AUDIT RATIFIED`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

