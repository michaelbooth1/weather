# 297. Calibration-Drift And Directional-Bias Daily Tracking [OPEN 2026-06-24 - NO DAILY CALIBRATION OR DIRECTIONAL-BIAS TREND]

Goal: track the served model's calibration quality and directional (warm/cold)
bias as first-class daily ledger columns so calibration drift is visible as a
trend, not just an occasional one-day status.

Source: 2026-06-24 audit of the daily analysis script. The daily progress ledger
stores skill, claim-gate, ops, and trading fields but no calibration column: a
grep for `ece`/`calibration_error`/`reliability_curve` in
`src/weather/reporting/daily/daily_progress_ledger.py` returns nothing, and the
7/14-day rollups only average rolling skill and snapshot gaps. The
model/taker audits found calibration to be the core weakness (model probabilities
badly miscalibrated, systematic warm bias), yet there is no daily calibration or
signed-bias trend in the analysis pipeline.

Why this matters: calibration error and directional bias are the most direct
levers on both Brier skill and trading edge. Without a daily trend they can drift
for weeks while single-day pass/fail gates stay green, and a regression is only
noticed after it has cost settled days.

Why it is not already covered: item 21 calibrates market-bin probabilities at
serving time, item 262 produces a proper-scoring/reliability scorecard, and items
134/136 calibrate forecast inputs, but none persist a daily calibration-quality
and directional-bias column with drift detection in the daily analysis ledger.

## Design

1. Pull or compute a daily served-model calibration metric (ECE/reliability) from
   the existing scorecard/hourly artifacts and a signed settlement-error bias
   (mean realized minus predicted, warm positive) for the settled day.
2. Add these as `daily_progress_ledger` columns with the same per-run-date upsert
   semantics as existing fields, and include them in the 7/14-day rollups.
3. Add a calibration/bias drift learning when the metric degrades beyond a
   configured threshold or trends adversely over the rolling window, and feed it
   into the anomaly detection from item 295.
4. Keep it fail-closed and diagnostic-only: missing calibration inputs are
   reported as `MISSING`, not silently zero, and the column is evidence for
   retrain prioritization rather than an automatic promotion gate.

- [ ] Add daily served-model calibration (ECE/reliability) and signed warm/cold
  bias columns to the ledger.
- [ ] Include calibration and bias in the 7/14-day rollups and report.
- [ ] Emit a calibration/bias drift learning on adverse threshold or trend.
- [ ] Add tests with improving and degrading calibration/bias fixtures.

Acceptance: each daily ledger row records served-model calibration quality and a
signed directional bias, the rollups and report show their trend, and an adverse
drift in either emits a learning, proven by fixtures with improving and
degrading calibration.

Related: items 21, 117, 134, 136, 262, 283, 295.
