# 223. Market-Stage Winner-Mass Attribution [COMPLETE 2026-06-22 - BOTTOM-LOCATION WINNER-MASS GUARDRAILS LIVE]

Goal: extend distribution stage attribution by market so Seattle, NYC, and
Miami can be audited for the exact stage that removes or fails to add winner
mass.

Source: `docs/roadmap/audits/location-performance-model-audit-2026-06-22.md`.
`feature_blend` improves Brier by `-0.0245` and increases winner probability by
`+0.1549`; `forecast_pull` improves Brier by `-0.0078` and increases winner
probability by `+0.0965` but worsens log-loss; `final_model` has more
Brier-worse rows than Brier-better rows and reduces winner probability by
`-0.0028` on average. Bottom locations are failing primarily on
settlement-distance bucket 0 and adjacent winner mass.

Why this matters: the stage attribution harness exists, but the audit needs
market-specific proof. A stage that is net neutral overall can still be the
reason Seattle, NYC, or Miami underprices the winner.

## Design

1. Add `market_id x stage` and `market_id x stage x cutoff_regime` outputs to
   `distribution_stage_attribution`.
2. Report winner-probability delta, adjacent-winner-mass delta, Brier delta,
   log-loss delta, and better/worse row counts by market.
3. Add a bottom-location guard: final model/postprocess stages may not reduce
   winner probability unless they reduce Brier and log-loss on the same
   market-day.
4. Feed stage-specific bottom-location failures into item 219 candidate design.

- [x] Extend the stage attribution JSON and report with market-level slices.
- [x] Add bottom-location winner-mass guardrail rows.
- [x] Add tests for market-specific stage attribution and guardrail status.
- [x] Regenerate attribution for Seattle, NYC, and Miami.

## Completion Notes

`distribution_stage_attribution` now emits `by_market_stage` and
`by_market_stage_cutoff_regime` slices with winner probability delta,
adjacent-winner-mass delta, Brier delta, log-loss delta, and better/worse row
counts. The report renders both sections and sorts market-stage rows so winner
mass reductions are visible instead of hidden by global Brier order.

The regenerated `data/backtest/distribution_stage_attribution.json` includes
`118` market-stage rows and `446` market-stage-cutoff-regime rows. It also
emits `bottom_location_winner_mass_guardrails`; the real snapshot tape currently
has `296` BLOCK rows for Miami, NYC, and Seattle where a final/postprocess
stage reduces winner probability without improving Brier and log-loss on the
same market-day. The top blocker is NYC `forecast_pull` in `final_lock_in` on
`2026-06-10`, with winner probability delta `-0.5292`, Brier delta `+0.0728`,
and log-loss delta `+1.7143`.

Daily refresh step results now surface market-stage row counts and bottom
location winner-mass blocker counts so item 219 repair work can target the
specific market, date, stage, and cutoff regime failures.

Verification:

- `python -m pytest tests\reporting\test_distribution_stage_attribution.py tests\operations\test_daily_refresh.py::TestDailyRefresh::test_distribution_stage_attribution_step_writes_outputs -q`
- `python -m weather.reporting.distribution_stage_attribution --json-out data\backtest\distribution_stage_attribution.json --report-out data\backtest\distribution_stage_attribution_report.md`

Acceptance: the attribution report identifies, by market and stage, where winner
mass is added or removed; Seattle/NYC/Miami final-stage winner-mass reductions
are explicit blockers unless Brier and log-loss improve on the same market-day.

Related: items 70, 147, 169, 182, 219.
