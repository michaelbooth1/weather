# Early-Hour Model Performance Audit - 2026-06-22

## Executive Summary

The current serving model is genuinely weak in the early local-day window. The
failure is strongest from `03:00` through `05:50` local time and is not a
dashboard artifact. The model is worse than the market because it underweights
the eventual winning band and spreads probability over too many adjacent bands
while the observed high is still unavailable or untrusted.

The best current diagnosis is:

1. The early window is forecast-anchor dominated by design. From `00:00` through
   `06:00`, the current-max audit shows nearly all rows are
   `pre_reset_current_max_null`, so the model cannot lean on a trusted observed
   high. That is expected, but the forecast-relative distribution is not
   centered tightly enough.
2. The served distribution has had validation/serving skew. The core-model audit
   found serving-only ordinal smoothing and asymmetric validation leakage. Code
   fixes for smoothing and honest splits are partly live, but the active pooled
   artifact has not been re-exported and validated after those fixes.
3. Cheap postprocessors are mostly ruled out. Partition-power sharpening barely
   helps. Market-price blending helps, but it is quote-risk mitigation and cannot
   count as weather-model skill.
4. A no-market early-hour repair path exists but is not production-fixed. The
   `item147_time_split_alpha` candidate and predawn weak-slot repair both improve
   early-hour Brier and winner probability, but current promotion still blocks
   because the latest candidate trails market overall, per-market gaps remain,
   and current-serving hourly/10-minute gates are still blocked.
5. Operations are a separate blocker. Fleet observability is `CRITICAL` and live
   forward evidence is blocked by snapshot cadence/CLOB freshness gaps. This
   prevents production proof, but it does not explain away the settled backtest
   early-hour failure.

Bottom line: keep current-serving promotion blocked, promote the predawn repair
only through a full candidate replay/promotion gate, and prioritize a long-job
retrain/re-export with the validation and serving-skew fixes before claiming the
model is fixed.

## Evidence Reviewed

- `data/backtest/hourly_model_performance_report.md`
- `data/backtest/hourly_model_performance_by_hour.csv`
- `data/backtest/ten_minute_model_performance_report.md`
- `data/backtest/price_free_model_learning_report.md`
- `data/backtest/price_free_model_learning_current_max_carryover.csv`
- `data/backtest/item147_time_split_alpha_hourly_candidate_performance_report.md`
- `data/backtest/predawn_weak_slot_repair_report.md`
- `data/backtest/f_family_promotion_refresh_report.md`
- `data/backtest/pooled_candidate_replay_latest_report.md`
- `data/backtest/fleet_observability_report.md`
- `data/backtest/data_layer_audit_report.md`
- `data/backtest/feature_quality_quarantine_report.md`
- `data/backtest/distribution_stage_attribution_report.md`
- `data/backtest/daily_learning_report.md`
- `data/backtest/progress_audit_report.md`
- `data/backtest/settled_day_root_cause_report_2026-06-20.md`
- `docs/roadmap/core-model-audit-2026-06-20.md`
- `docs/roadmap/items/item-145-hourly-performance-gate-and-remediation-registry.md`
- `docs/roadmap/items/item-147-early-hour-winner-centering-candidate.md`
- `docs/roadmap/items/item-160-early-hour-model-skill-remediation-to-positive-daily-first-gate.md`
- `docs/roadmap/items/item-168-ten-minute-performance-gate-and-weak-slot-watchlist.md`
- `docs/roadmap/items/item-169-predawn-winner-centering-and-forecast-anchor-repair.md`
- `docs/roadmap/items/item-178-serving-ordinal-smoothing-train-serve-skew.md`
- `docs/roadmap/items/item-179-honest-blocked-validation-for-feature-model-tuning.md`
- `docs/roadmap/items/item-181-forecast-double-counting-and-dead-capture-hour.md`
- `docs/roadmap/items/item-193-wu-current-max-anomaly-quarantine-and-trust-weighting.md`

## Definition Of The Problem

The primary affected window is local `00:00-08:00`, with the actionable weak
cluster at local `03:00-05:50`.

Current hourly audit:

| Window | Rows | Market-days | Model Brier | Market Brier | Model winner P | Market winner P | Model eff bands | Market eff bands |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `00:00-08:00` | 5,159 | 53 | 0.0670 | 0.0511 | 29.4% | 43.5% | 4.54 | 3.46 |
| `09:00-14:00` | 3,564 | 54 | 0.0646 | 0.0548 | - | - | 4.05 | 3.36 |
| `15:00-19:00` | 2,970 | 54 | 0.0433 | 0.0217 | - | - | 1.97 | 1.93 |
| `20:00-23:00` | 2,332 | 53 | 0.0205 | 0.0000 | - | - | 1.19 | 1.07 |

Worst hourly checkpoints:

| Hour | Model Brier | Market Brier | Model winner P | Market winner P | Eff-band gap | Forecast gap |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `03:00` | 0.0739 | 0.0600 | 23.4% | 33.6% | +1.00 | 14.92 |
| `04:00` | 0.0710 | 0.0597 | 25.0% | 34.1% | +1.18 | 12.14 |
| `05:00` | 0.0704 | 0.0586 | 24.7% | 35.3% | +1.49 | 12.14 |

Ten-minute audit:

- Weak slots are `03:00`, `03:10`, `03:20`, and `04:00` through `05:50`.
- Weak-slot model Brier is `0.0721` versus market `0.0592`.
- Weak-slot model winner probability is `24.2%` versus market `34.6%`.
- Weak-slot effective-band gap is `+1.27`.
- Weak-slot forecast gap is `12.25`.

## Root Cause Findings

| Finding | Status | Evidence | Severity | Confidence | Next validation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Early rows lack trusted observed-high signal, so the model must be forecast-anchor correct before heating starts. | Confirmed | `price_free_model_learning_current_max_carryover.csv`: `00:00-06:00` rows are almost entirely `pre_reset_current_max_null`; weak slots have high forecast gap. | High | High | Keep current-max null-before-reset; improve forecast-relative centering instead of forcing raw current max. |
| The current distribution is too diffuse and underweights the eventual winner. | Confirmed | Early model winner P `29.4%` vs market `43.5%`; model eff bands `4.54` vs market `3.46`; weak-slot winner P `24.2%` vs market `34.6%`. | High | High | Candidate must improve winner P, winner rank, adjacent mass, Brier, and log-loss. |
| Serving/train skew likely contributed to over-diffusion. | Confirmed as code issue, unproven as fully fixed in artifact | Item 178 removed serving-only ordinal smoothing, but retrain/re-export timed out and active artifact retained prior timestamps. | High | Medium-high | Complete long-job retrain/re-export, then rerun hourly/10-minute/promotion gates. |
| Prior validation overtrusted the ML model due to asymmetric blocked validation. | Confirmed as code issue, artifact still pending | Item 179 moved feature validation to holdout-year blocked splits, but re-export has not completed. | High | Medium | Re-export artifacts and compare legacy-vs-honest temperature/blend selections. |
| Forecast postprocessing/double counting was present on stale component tapes. | Partially confirmed | Item 181 scopes pull/floor to empirical fallback in current code, but distribution attribution still sees stale feature-model forecast-shape rows and zero current-code feature-model component rows. | Medium-high | Medium | Regenerate current-code component tapes and require `current_code_feature_model_forecast_shape_rows=0`. |
| Current-max/WU anomalies are a real secondary failure mode after reset. | Confirmed | Feature quarantine has 4,680 `current_max_exceeds_observed_support` rows; June 20 root cause has 689 `WU_CURRENT_MAX_ANOMALY` issues; Item 193 added trusted/support/quarantine fields. | Medium-high | High | Validate that retrained artifacts consume `trusted_current_max`, not raw max-since-7. |
| The failure is not only source freshness. | Confirmed | Latest promotion gap drivers show `source_freshness=all_fresh` is one of the largest weighted gaps; source-status proof has zero blocked promotion markets. | High | High | Do not treat WU 400/current-day availability alone as the fix. |
| Live-forward reliability prevents production proof. | Confirmed | Fleet observability is `CRITICAL`; snapshot coverage gaps block all 12 active markets; CLOB book freshness blocks all 12. | High for production evidence | High | Repair loops and require a clean active day before using live-forward evidence. |

## Key Rule-Outs

- It is not just snapshot density. The hourly and 10-minute audits keep the
  first checkpoint per market-day-band-hour/slot.
- It is not a one-day label issue. The weak-slot pattern spans 52 settled
  market-days in complete/manual-override quality labels.
- It is not solved by generic sharpening. Partition-power changes weak-slot
  Brier by only about `-0.0007`, and the hourly registry shows early broad
  partition-power is not a meaningful fix.
- It is not solved by market blending as model evidence. Market blending reduces
  error, but it uses the benchmark and remains quote-risk/risk-overlay evidence.
- It is not production-fixed just because Item 169 passed. That report validates
  a scoped no-market repair artifact; current-serving hourly and 10-minute gates
  remain blocked in the latest promotion refresh.

## Candidate Evidence

`item147_time_split_alpha` candidate-hourly audit:

| Scope | Variant Brier | Current Brier | Market Brier | Winner variant P | Winner market P | Status |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| `00:00-08:00` | 0.0511 | 0.0555 | 0.0519 | 43.69% | 43.53% | PASS |

That candidate closes the early-hour gap on its candidate corpus, but broad
promotion is still blocked. The latest F-family refresh has candidate Brier
`0.0452` versus market `0.0379`, eight blocked markets, and current-serving
hourly/10-minute blockers still active.

Predawn weak-slot repair:

| Slice | Candidate Brier | Current Brier | Market Brier | Candidate winner P | Current winner P | Market winner P |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| All weak slots | 0.0620 | 0.0670 | 0.0615 | 31.59% | 27.76% | 32.96% |
| Eval weak slots | 0.0639 | 0.0695 | 0.0609 | 30.53% | 26.75% | 34.10% |

This is the best no-market repair path found so far. It should be promoted to a
candidate lane only after full replay and promotion gating, because the eval
market gap is right at the tolerance boundary and the repair is not yet active
serving behavior.

## Per-Market Risk

All 12 markets block on early-hour Brier and log-loss in the current-serving
hourly gate. Worst Brier gaps versus market are:

| Market | Model Brier | Market Brier | Gap | Model winner P | Market winner P |
| :--- | ---: | ---: | ---: | ---: | ---: |
| seattle | 0.0678 | 0.0286 | +0.0392 | 36.0% | 62.0% |
| nyc | 0.0838 | 0.0587 | +0.0251 | 17.7% | 36.5% |
| austin | 0.0648 | 0.0452 | +0.0196 | 32.5% | 46.0% |
| toronto | 0.0651 | 0.0469 | +0.0182 | 25.3% | 43.4% |
| miami | 0.0642 | 0.0464 | +0.0178 | 31.9% | 45.4% |

Latest promotion gaps are broader than early hours. The largest weighted
candidate gaps include `wu_lag_catchup_miss`, exact `eq` bands,
`source_freshness=all_fresh`, settlement-distance `0`, and cutoff hour `7`.
That combination points to winner/exact-band calibration and forecast/current
observation transition risk, not just stale-source handling.

## Recommended Fix Plan

### P0 - Keep Unsafe Promotion Blockers

Do not cut over current serving or the latest pooled candidate while the
following remain true:

- current-serving hourly gate is `BLOCK`
- current-serving 10-minute weak-slot gate is `BLOCK`
- candidate broad replay trails market materially
- live-forward SLO and current-code soak are blocked

Validation:

```powershell
python -m weather.reporting.hourly_model_performance --json-out data\backtest\hourly_model_performance.json --report-out data\backtest\hourly_model_performance_report.md --csv-out data\backtest\hourly_model_performance_by_hour.csv
python -m weather.reporting.ten_minute_model_performance --json-out data\backtest\ten_minute_model_performance.json --report-out data\backtest\ten_minute_model_performance_report.md --csv-out data\backtest\ten_minute_model_performance_by_slot.csv
python -m weather.reporting.fleet_observability report --out data\backtest\fleet_observability.json --report data\backtest\fleet_observability_report.md
```

Success criterion: current gates either pass directly or are mitigated only by
matching candidate-specific hourly and 10-minute evidence.

### P0 - Re-Export The Model After Validation/Serving Fixes

Run the full pooled F-band retrain under a long-job-safe path. The prior
interactive attempt timed out and produced no valid artifact update.

Validation command from the retrain dry run:

```powershell
python -m weather.calibration.pooled_feature_model --family-unit F --objective band --holdout-year 2025 --artifact artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl --out data\backtest\f_family_pooled_band_model_v0_3_report.md
```

Then rerun:

```powershell
python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact artifacts\models\hgb\feature_model_hgb_f_pooled_v0_3.pkl --out data\backtest\pooled_candidate_replay_latest_report.md --json-out data\backtest\pooled_candidate_replay_latest.json
python -m weather.reporting.hourly_model_performance
python -m weather.reporting.ten_minute_model_performance
python -m weather.reporting.distribution_stage_attribution --out data\backtest\distribution_stage_attribution.json --report data\backtest\distribution_stage_attribution_report.md
```

Success criterion: regenerated artifact timestamps, honest blocked-validation
metrics in the training report, early-hour winner probability moves toward
market, and no ramp/late/lock-in regression beyond tolerance.

### P0 - Convert Predawn Repair Into A Candidate Gate, Not A Note

The scoped predawn repair is promising and should be tested as an explicit
candidate artifact.

Validation:

```powershell
python -m weather.reporting.predawn_weak_slot_repair --out data\backtest\predawn_weak_slot_repair.json --report data\backtest\predawn_weak_slot_repair_report.md
```

Success criterion:

- weak-slot Brier improves by at least `0.0030` versus current
- weak-slot Brier is within `0.0030` of market
- log-loss does not regress
- non-weak early, ramp, late, and lock-in guardrails pass
- candidate-specific hourly and 10-minute variant IDs match the promoted replay

### P1 - Regenerate Current-Code Component Tapes

Distribution attribution still cannot prove the forecast-shape scope because the
available feature-model component rows are stale. Regenerate component payloads
with current code and rerun attribution.

Success criterion:

- `current_code_feature_model_component_rows > 0`
- `current_code_feature_model_forecast_shape_rows = 0`
- no net Brier/log-loss regression by early, ramp, late, or market slices

### P1 - Repair Live-Forward Evidence Collection

Fleet observability blocks production proof independently of model quality.

Commands from current reports:

```powershell
python -m weather.collection.snapshot_tracker --restart
python -m weather.market.market_microstructure ensure
python -m weather.operations.loop_jsonl_repair repair C:\Users\micha\Desktop\github\weather\data\snapshots\loop_console.log
python -m weather.operations.loop_jsonl_repair repair C:\Users\micha\Desktop\github\weather\data\snapshots\observation_trigger_console.log
python -m weather.reporting.fleet_observability report --out data\backtest\fleet_observability.json --report data\backtest\fleet_observability_report.md
```

Success criterion: one clean active day with zero snapshot coverage-gap blocked
markets, fresh CLOB books, source status proof passing, and current-code soak
within restart budgets.

### P1 - Target Exact-Band And Settlement-Distance-0 Calibration

Latest gap drivers show exact `eq` bands and settlement-distance `0` dominate
remaining market gap. Do not rerun broad alpha sweeps already rejected in Item
147. Focus on:

- exact-band calibration under honest daily-first split
- settlement-distance-0 winner catch-up without one-above regression
- market-specific Seattle/NYC/Austin/Miami/San Francisco repairs
- no-market features for overnight forecast movement, source disagreement, and
time-to-heating

Success criterion: paired daily-first replay improves target slices and clears
aggregate/per-market market tolerance without worsening promoted/shadow markets.

## Experiment Plan

| Experiment | Hypothesis | Required evidence | Success metric | Fail/rollback |
| :--- | :--- | :--- | :--- | :--- |
| Long-job honest retrain | Removing serving-only smoothing and using honest splits fixes over-diffusion. | New HGB artifact/report, hourly/10-minute gates, promotion replay. | Early winner P rises; early Brier gap <= 0.003; no midday/late regression. | Keep current artifact; open child items 178/179. |
| Predawn candidate replay | Scoped logistic winner-centering is enough for `03:00-05:50`. | Candidate artifact rows, candidate hourly and 10-minute reports. | Weak-slot Brier improves >= 0.003 vs current and market gap <= 0.003. | Keep as research-only; mine failed markets. |
| Current-code stage attribution | Forecast pull/floor scope fix is effective in current serving. | Current-code component tapes and attribution report. | No feature-model forecast-shape rows after current-code replay; Brier/log-loss non-regression. | Reopen item 181 scope decision. |
| Current-max trust retrain | Trusted/support/quarantine current-max fields prevent warm-tail anomalies. | Retrained artifact and June 20 root-cause replay. | `WU_CURRENT_MAX_ANOMALY` and warm-tail issues decline without late lock-in loss. | Keep quarantines as feature-only diagnostics; revise feature use. |
| Per-market residual repair | Seattle/NYC/Austin/Miami/SF gaps are different enough to require market-specific features. | Market-scoped daily-first replay reports. | Each blocked market gap <= 0.003 and no aggregate regression. | Shadow per-market only; do not broad cutover. |
| Live-forward clean-day proof | Ops gaps are blocking evidence, not necessarily model skill. | Fleet observability and progress audit after clean active day. | Live-forward SLO PASS and current-code soak PASS. | Keep active-day evidence non-countable. |

## 30/60/90-Day Roadmap

### 30 Days

- Finish the long-job retrain/re-export for the active pooled F artifact.
- Promote the predawn weak-slot repair into a candidate replay, not serving.
- Rerun hourly, 10-minute, promotion refresh, distribution attribution, daily
  learning, and progress audit from the regenerated artifact.
- Repair live-forward collection gaps and require one clean active day.
- Keep all market-informed/CLOB overlays in quote-risk lanes only.

### 60 Days

- Close current-code component tape proof for item 181.
- Add exact-band and settlement-distance-0 repair candidates under daily-first
  blocked validation.
- Add per-market residual experiments for Seattle, NYC, Austin, Miami,
  San Francisco, and Los Angeles.
- Backfill snapshot explanations so weak-slot reports can join source,
  forecast, boundary, and model-explanation context without rerunning the model.

### 90 Days

- Move from postprocessor repairs to a unified validate-what-you-serve
  calibration head over the final served distribution.
- Advance continuous-density / exact-band modeling to reduce boundary and
  one-above regressions.
- Raise promotion-grade market-day evidence above the current 48-day shortfall.
- Require positive rolling daily-first skill before any broad model-improvement
  claim.

## Final Recommendation

Treat the early-hour problem as a model-calibration and forecast-centering
failure, with data-trust and live-forward reliability as blocking dependencies.
The most efficient path is not another broad sharpening sweep. It is:

1. retrain/re-export with honest validation and serving-parity fixes,
2. run the predawn weak-slot repair as a real candidate artifact,
3. prove current-code stage attribution,
4. keep promotion blocked until candidate-specific hourly and 10-minute gates
   pass and broad replay no longer trails market beyond tolerance,
5. repair live-forward collection so the next active day can count.

