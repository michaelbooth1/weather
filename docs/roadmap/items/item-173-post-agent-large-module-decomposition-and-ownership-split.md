# 173. Post-Agent Large Module Decomposition And Ownership Split [OPEN]

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

- [ ] Split `weather.market.taker_bot` into strategy registry, strategy
  evaluation, sizing/risk, bakeoff/reporting, tape IO, and CLI facade modules.
- [ ] Split `weather.reporting.promotion_refresh` into gate readers,
  mitigation evaluation, report rendering, and orchestration modules.
- [ ] Split `weather.calibration.pooled_feature_model` into feature assembly,
  training, validation, artifact IO, and serving helpers.
- [ ] Review `fleet_observability` and `hourly_model_performance` for shared
  slot scoring, gate rendering, and report utility extraction.
- [ ] Keep compatibility facades until import architecture tests and active
  callers prove the new surfaces are stable.
- [ ] Add a "no new 2k-line module" architecture warning or audit report.

Acceptance: the largest operational files are decomposed around stable
runtime/reporting/model boundaries, existing CLIs continue to work, and package
dependency ratchets document the new ownership model.

