# 145. Hourly Performance Gate And Remediation Registry [COMPLETE 2026-06-18 - HOURLY GATE AND REGISTRY LIVE]

Goal: make hour-by-hour model performance and remediation probes a first-class
promotion and daily-learning gate.

Source: `src/weather/reporting/hourly_model_performance.py` and
`data/backtest/hourly_model_performance_report.md`. The June 18 hourly audit
showed that aggregate metrics can hide a sharp timing split: late hours such as
23:00, 22:00, and 20:00 are the strongest, while 03:00, 04:00, and 05:00 are
the weakest. It also falsified simple model-output reshaping as the main
remediation path because partition-power calibration barely improved the worst
hours.

Why this matters: a candidate can look acceptable on all-day Brier or log-loss
while making the early market-making window worse. The hourly audit should be a
repeatable gate, and remediation experiments should be tracked with enough
structure to separate real weather-model lift from market-aware risk overlays.

## Design

1. Run `weather.reporting.hourly_model_performance` after settled labels and
   the promotion corpus are refreshed.
2. Persist the report, JSON, and CSV outputs in the daily evidence bundle.
3. Define hour-regime gates for early 00:00-08:00, ramp 09:00-14:00, late
   15:00-19:00, and lock-in 20:00-23:00.
4. Track remediation probe families in a registry, starting with market blend
   and partition power, then adding forecast-dominant candidates from items
   134, 135, and 136.
5. Block candidate promotion when aggregate metrics improve but early-hour
   Brier, log-loss, or calibration error regresses beyond tolerance.
6. Feed the best/worst hour summary into progress audit and daily-learning
   status so operational readiness reflects timing risk.

- [x] Add the hourly audit to the daily refresh or promotion readiness command.
- [x] Store a machine-readable remediation registry with probe name, hour
  regime, metric delta, market count, row count, and interpretation.
- [x] Add promotion thresholds for early-hour regression and minimum settled
  market-day evidence.
- [x] Add a short daily summary of best hours, worst hours, and active
  remediation owners.
- [x] Add tests that fail if remediation probe fields disappear from the JSON
  output or report.

Acceptance: every promoted or rejected model candidate has hour-regime evidence
attached, early-hour regressions are explicit blockers, and remediation probe
results remain comparable across daily runs.

## Implementation update - 2026-06-18

`weather.reporting.hourly_model_performance` now emits
`hourly_model_performance_v0.3` with two first-class child contracts:
`hourly_performance_gate_v0.1` and `hourly_remediation_registry_v0.1`. The
gate evaluates early-hour Brier/log-loss regression, calibration error, and
minimum settled market-day evidence. The registry stores comparable probe rows
with probe name, hour regime, metric delta, log-loss delta, market count,
market-day count, row count, owner, market-price usage, claim lane, and
interpretation.

Daily refresh now runs the hourly audit before promotion refresh and writes
`data/backtest/hourly_model_performance.json`,
`data/backtest/hourly_model_performance_report.md`, and
`data/backtest/hourly_model_performance_by_hour.csv`. Promotion readiness reads
that JSON and adds a blocking `hourly_performance_gate` readiness blocker when
early-hour evidence regresses. Daily learning also reads the hourly artifact,
records the gate in the scorecard, promotes blocking hourly failures to P0
learnings, and carries early-hour remediation-registry rows into the retrain
plan with market-aware probes separated from weather-model probes.

The regenerated hourly artifact is intentionally blocking candidates today:
model Brier is `0.0536` versus market Brier `0.0373`; the first blocker is
`early_hour_brier_regression` because early-hour model Brier trails market by
`0.0159` above the `0.0030` tolerance, followed by
`early_hour_logloss_regression`. The daily summary reports best hours
`23:00`, `22:00`, and `20:00`, worst hours `03:00`, `04:00`, and `05:00`, and
active remediation owners `market-making risk overlay`, `model calibration`,
and `early-hour forecast-centering candidate`. The remediation registry now has
12 comparable rows across `forecast_centering`, `market_blend`, and
`partition_power`, explicitly marking market-blend rows as risk-overlay
evidence that cannot count toward weather-model promotion. The no-market
`forecast_centering` probe is the first weather-model remediation row that
clears the early-morning improvement threshold, with early-hour Brier delta
`-0.0032` and log-loss delta `-0.1012`.

Validation:

- `python -m pytest -q tests\reporting\test_hourly_model_performance.py tests\operations\test_daily_refresh.py tests\calibration\test_promotion_refresh.py tests\reporting\test_daily_learning.py tests\operations\test_schema_registry.py`
- `python -m weather.reporting.hourly_model_performance --json-out data\backtest\hourly_model_performance.json --report-out data\backtest\hourly_model_performance_report.md --csv-out data\backtest\hourly_model_performance_by_hour.csv`

## Candidate variant local-hour extension - 2026-06-19

`weather.reporting.candidate_hourly_performance` now provides the matching
candidate-side audit for Item-69-style shadow variant rows. It keeps the
production current-serving gate unchanged, but lets a candidate prove whether
it fixes the 00:00-08:00 local capture-hour failure before promotion.

The first use is Item 147's time-split alpha candidate:
`data/backtest/item147_time_split_alpha_hourly_candidate_performance_report.md`
reports `PASS` on 44 F-family market-days. Early-hour candidate Brier is
`0.0511` versus current `0.0555` and market `0.0519`; early-hour log-loss is
also better than market by `-0.0027`. The report explicitly notes that it does
not replace the production gate until the candidate is promoted.

`promotion_refresh` now accepts an optional
`--candidate-hourly-performance-report`. It suppresses a current-serving hourly
readiness blocker only when the candidate-hourly gate is `PASS` and the
candidate-hourly report's `variant_ids` include the replayed candidate's
`candidate_shadow_variants.variant_id`. The operational section still reports
both gates, so a blocked current-serving gate remains visible even when the
candidate-specific gate is used as mitigation.

Validation:
`python -m pytest tests\calibration\test_promotion_refresh.py tests\reporting\test_candidate_hourly_performance.py tests\operations\test_schema_registry.py -q`
passed with `34 passed`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - HOURLY GATE AND REGISTRY LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

