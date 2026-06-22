# Location Performance Model Audit - 2026-06-22

## Scope

Audit the active weather model evidence by location, split locations by performance, and compare the better performing locations against the worse ones. This review used local backtest outputs, shadow outputs, promotion decisions, operational gates, feature quality reports, model artifact manifests, and run logs available in this workspace.

The primary location comparison is based on market-day performance, not raw row counts. Row-level slices are used only to explain likely drivers.

## Evidence Used

- `data/backtest/location_trust.json`
- `data/backtest/item50_pooled_candidate_shadow_variants.csv`
- `data/backtest/active_variant_shadow_long.csv`
- `data/backtest/f_family_promotion_refresh.json`
- `data/backtest/hourly_model_performance.json`
- `data/backtest/ten_minute_model_performance.json`
- `data/backtest/distribution_stage_attribution.json`
- `data/backtest/feature_quality_quarantine.json`
- `data/backtest/price_free_model_learning.json`
- `data/backtest/predawn_weak_slot_repair.json`
- `data/backtest/source_state_ablation_shadow_variants.csv`
- `data/backtest/item147_time_split_alpha_staged_serving_promotion_refresh.json`
- `data/backtest/item147_blocked_market_repair_actions_report.md`
- `data/backtest/item147_blocked_markets_winner_underpricing_casebook_report.md`
- `data/backtest/item147_blocked_markets_variant_basket_selection_validation_report.md`
- `data/backtest/item147_blocked_markets_variant_basket_with_item32_validation_report.md`
- `data/backtest/daily_learning.json`
- `data/backtest/settled_day_freshness.json`
- `data/backtest/data_layer_audit.json`
- `data/backtest/ingest_quality_gate.json`
- `data/backtest/fleet_observability.json`
- `data/backtest/source_family_inventory.json`
- `data/mm_runs/daily_roll_console.log`
- `data/taker_runs/daily_roll_console.log`
- `config/model_variant_registry.json`
- `artifacts/manifests/model_artifact_registry.json`
- active model artifacts under `artifacts/models/hgb/`
- `docs/roadmap/audits/early-hour-model-performance-audit-2026-06-22.md`
- `docs/roadmap/core-model-audit-2026-06-20.md`

Derived audit tables:

- `scratch/location_audit/market_day_metrics.csv`
- `scratch/location_audit/market_summary.csv`

## Executive Findings

The active no-market F-family model is not uniformly bad. Atlanta, San Francisco, and Denver are near market performance on the active shadow split, while Miami, NYC, and Seattle are the weakest locations versus market. The weak locations are not simply suffering from stale source status or high forecast disagreement. The dominant pattern is winner under-centering, especially before and around the middle of the day.

The best repair evidence is not the current pooled candidate by itself. The no-market candidate gives small improvements but remains outside market tolerance in the worst locations. The only variant that closes the bottom-location gap is the CLOB raw OOF overlay, and it is market-informed with partial coverage, so it should be treated as a quote-risk/trading overlay rather than evidence that the weather model itself is fixed.

The staged item147 and predawn repair artifacts show a credible no-market repair path, but the existing blocked-market basket/guard experiments still fail held-out market tolerance. The immediate production posture should be: promote only markets that passed the current location promotion gate, keep San Francisco in shadow, block the other markets from broad promotion, and build a bottom-location early/midday centering repair with item147/predawn evidence as the seed.

## Location Split

Current active shadow, using `item50_pooled_candidate_shadow_variants.csv`.

| Rank | Market | Days | Current Brier | Market Brier | Current Excess vs Market | Current Winner Gap |
|---:|---|---:|---:|---:|---:|---:|
| 1 | atlanta | 4 | 0.0367 | 0.0395 | -0.0027 | -0.0166 |
| 2 | san-francisco | 4 | 0.0430 | 0.0412 | +0.0017 | -0.0054 |
| 3 | denver | 4 | 0.0506 | 0.0450 | +0.0055 | -0.0331 |
| 4 | dallas | 4 | 0.0668 | 0.0607 | +0.0061 | -0.0283 |
| 5 | houston | 4 | 0.0505 | 0.0444 | +0.0061 | -0.0153 |
| 6 | austin | 4 | 0.0426 | 0.0362 | +0.0064 | -0.0050 |
| 7 | chicago | 4 | 0.0455 | 0.0363 | +0.0092 | -0.0371 |
| 8 | los-angeles | 4 | 0.0396 | 0.0291 | +0.0105 | -0.0499 |
| 9 | miami | 4 | 0.0386 | 0.0238 | +0.0148 | -0.0107 |
| 10 | nyc | 4 | 0.0591 | 0.0361 | +0.0231 | -0.1779 |
| 11 | seattle | 4 | 0.0483 | 0.0241 | +0.0242 | -0.1362 |

Top cohort: Atlanta, San Francisco, Denver.

- Mean market-day excess: +0.0015
- Median market-day excess: -0.0001
- Positive excess days: 6 of 12
- Mean winner gap: -0.0182
- Candidate improvement vs current: -0.0012 Brier

Bottom cohort: Miami, NYC, Seattle.

- Mean market-day excess: +0.0206
- Median market-day excess: +0.0191
- Positive excess days: 10 of 12
- Mean winner gap: -0.1079
- Candidate improvement vs current: -0.0026 Brier

The bottom cohort is about +0.0191 Brier worse than market at the median market-day level and underprices the winning bucket by about 10.8 probability points on average.

## What The Better Locations Do Differently

### 1. Better locations preserve winner mass much earlier in the day

By cutoff regime:

| Cohort | Regime | Current Excess vs Market | Winner Gap |
|---|---|---:|---:|
| top | early | +0.0013 | -0.0290 |
| top | midday | +0.0007 | +0.0123 |
| top | late | +0.0023 | -0.0288 |
| bottom | early | +0.0290 | -0.1563 |
| bottom | midday | +0.0325 | -0.1548 |
| bottom | late | +0.0025 | -0.0196 |

The bottom-location failure is concentrated in early and midday snapshots. Late-day performance is much closer to market.

This lines up with the independent time gates:

- Hourly gate is blocked because early-hour Brier trails market by +0.0159 and early-hour log-loss trails by +0.1693.
- Early-hour Seattle gap is +0.0393 Brier, NYC is +0.0251, Miami is +0.0178.
- Ten-minute gate is blocked on weak slots from 03:00 through 05:50 with model winner probability 0.2417 vs market winner probability 0.3464.
- `item147_time_split_alpha` improves weak-slot Brier from 0.0670 to 0.0626, nearly matching market at 0.0615, and moves winner probability from 0.2776 to 0.3244.

### 2. Source freshness problems amplify the gap but do not explain it

By source freshness:

| Cohort | Source State | Current Excess vs Market | Winner Gap |
|---|---|---:|---:|
| top | all_fresh | +0.0008 | -0.0145 |
| top | failed:wu_history | -0.0011 | -0.0051 |
| bottom | all_fresh | +0.0203 | -0.1077 |
| bottom | failed:wu_history | +0.0314 | -0.1259 |

The bottom cohort is still bad when every source is fresh. WU-history failures make it worse, but freshness repair alone will not close the location gap.

### 3. Forecast disagreement is not the main explanation

Bottom locations underperform even in low-disagreement cases:

| Cohort | Disagreement Bucket | Current Excess vs Market | Winner Gap |
|---|---|---:|---:|
| top | low_disagreement | -0.0093 | +0.0659 |
| top | moderate_disagreement | +0.0159 | -0.1043 |
| top | high_disagreement | +0.0010 | -0.0218 |
| bottom | low_disagreement | +0.0224 | -0.0526 |
| bottom | moderate_disagreement | +0.0283 | -0.1434 |
| bottom | high_disagreement | +0.0153 | -0.1092 |

The weak locations have a location-specific centering problem, not only a source disagreement problem.

### 4. The worst locations especially miss the exact and adjacent winning buckets

By settlement distance:

| Cohort | Settlement Distance Bucket | Current Excess vs Market | Current Brier |
|---|---:|---:|---:|
| top | 0 | +0.0259 | 0.3519 |
| top | 1 | -0.0167 | 0.1596 |
| bottom | 0 | +0.1654 | 0.3661 |
| bottom | 1 | +0.0315 | 0.1621 |

Bucket 0 is the actual winner row. Bottom markets are dramatically under-centered on the eventual winning bucket relative to the market.

### 5. Missingness/source state needs to become a first-class location gate

Feature missingness hash slices show that some states are disproportionately bad in the bottom cohort:

| Cohort | Feature Missingness Hash | Rows | Current Excess vs Market | Winner Gap |
|---|---|---:|---:|---:|
| top | `469d0c0f...` | 6,623 | -0.0039 | +0.0019 |
| bottom | `469d0c0f...` | 7,214 | +0.0256 | -0.1782 |
| top | `3184cdfa...` | 2,617 | +0.0157 | -0.0919 |
| bottom | `3184cdfa...` | 1,993 | +0.0518 | -0.1692 |

The same missingness state can be tolerable in top locations and damaging in bottom locations, so the model needs market-by-missingness gating or retraining evidence rather than a global missingness rule.

### 6. Source-state ablation helps but does not solve the bad locations

`source_state_ablation_shadow_variants.csv` compares a no-source-state current control against a dynamic source-state candidate on the same 67,430-row corpus.

| Market | Dynamic Candidate Brier | Current Brier | Market Brier | Dynamic Delta vs Market |
|---|---:|---:|---:|---:|
| atlanta | 0.0351 | 0.0367 | 0.0395 | -0.0044 |
| houston | 0.0470 | 0.0505 | 0.0444 | +0.0026 |
| nyc | 0.0540 | 0.0591 | 0.0361 | +0.0179 |
| seattle | 0.0454 | 0.0483 | 0.0241 | +0.0213 |
| miami | 0.0386 | 0.0386 | 0.0238 | +0.0148 |

Even on all-fresh rows, Seattle remains +0.0206 vs market and NYC remains +0.0182 vs market. Source state is a useful feature family, not the root fix.

## Variant Comparison

No-market candidates improve current modestly but do not close the bottom-location gap.

| Variant | Uses Market | Rows | Variant Brier | Delta vs Current | Delta vs Market | Winner Gap |
|---|---:|---:|---:|---:|---:|---:|
| clob_overlay_raw_oof | yes | 19,668 | 0.0300 | -0.0116 | +0.0002 | +0.0322 |
| clob_overlay_gated_taxonomy | yes | 67,430 | 0.0450 | -0.0024 | +0.0072 | -0.0470 |
| item50_pooled_forecast_v3_candidate | no | 67,430 | 0.0450 | -0.0023 | +0.0072 | -0.0470 |
| pooled_f_dynamic_source_state_v0_1 | no | 67,430 | 0.0453 | -0.0021 | +0.0074 | -0.0490 |
| pooled_continuous_density_hgb_v0_1 | no | 76,879 | 0.0566 | +0.0053 | +0.0147 | -0.1573 |

Bottom cohort:

| Variant | Uses Market | Delta vs Current | Delta vs Market | Winner Gap |
|---|---:|---:|---:|---:|
| clob_overlay_raw_oof | yes | -0.0228 | -0.0017 | +0.0685 |
| item50_pooled_forecast_v3_candidate | no | -0.0026 | +0.0181 | -0.1011 |
| pooled_f_dynamic_source_state_v0_1 | no | -0.0032 | +0.0175 | -0.0954 |
| pooled_continuous_density_hgb_v0_1 | no | +0.0046 | +0.0244 | -0.2011 |

The CLOB raw overlay is the only variant that solves the bottom cohort on this split. Because it uses market information and has partial coverage, it should not be promoted as a weather model replacement.

## Promotion Evidence

`f_family_promotion_refresh.json` already made the correct location-specific call:

- Promote candidate: Atlanta, Houston
- Keep shadow: San Francisco
- Block candidate: Austin, Chicago, Dallas, Denver, Los Angeles, Miami, NYC, Seattle

Blocked examples:

| Market | Candidate Brier | Market Brier | Candidate Excess vs Market |
|---|---:|---:|---:|
| miami | 0.0386 | 0.0238 | +0.0148 |
| nyc | 0.0540 | 0.0361 | +0.0179 |
| seattle | 0.0454 | 0.0241 | +0.0213 |
| los-angeles | 0.0372 | 0.0291 | +0.0081 |
| dallas | 0.0668 | 0.0607 | +0.0061 |

The current evidence supports targeted promotion, not a broad F-family rollout.

## Repair Evidence

### Predawn repair

`predawn_weak_slot_repair.json` is the strongest no-market weak-slot repair found:

- Status: PASS
- Variant: `predawn_logistic_winner_centering_item147_blend`
- Uses market features: false
- Weak-slot Brier: current 0.0670, variant 0.0620, market 0.0615
- Weak-slot log-loss: current 0.2203, variant 0.1973, market 0.1993
- Winner probability: current 0.2776, variant 0.3159, market 0.3296
- Eval split delta vs market: +0.0030, right at the configured tolerance boundary

This is good enough for an active shadow candidate, not good enough for broad serving without the full promotion gate.

### Staged item147 promotion

`item147_time_split_alpha_staged_serving_promotion_refresh_report.md` is older than the current F-family refresh but useful as repair evidence:

- Cutover decision: PER_MARKET_ONLY
- Candidate hourly gate: PASS
- Promoted in that run: Atlanta, Chicago, Denver, Houston
- Shadow: Dallas, Miami
- Blocked: Austin, Los Angeles, NYC, San Francisco, Seattle
- Aggregate candidate still trailed market by +0.0024 Brier
- Live-forward SLO was still BLOCK

So item147 improves the repair lane, but it still does not clear the hard markets.

### Existing basket/guard shortcuts failed

The blocked-market basket validation tested current, item134, item135, item147, and item32 variants on earlier market-days and evaluated selected baskets on later market-days.

- Without item32, selected basket delta vs market was +0.0106; all 5 tested markets blocked.
- With item32 added, selected basket delta vs market was still +0.0106; all 5 tested markets blocked.
- Leave-one-market-day stability also blocked Austin, Los Angeles, NYC, San Francisco, and Seattle.
- Guarded branch policies remained blocked, including Seattle item147 at +0.0152 vs market and NYC item147 at +0.0035 vs market.

This rules out a simple "pick the best existing variant by market/slice" shortcut.

### Casebook evidence

`item147_blocked_markets_winner_underpricing_casebook_report.md` found 387 early winner-underpricing cases across Austin, Los Angeles, NYC, San Francisco, and Seattle. Seattle had the largest average winner gap at +0.2555 probability points between market and candidate, with repeated cases where the model ranked the eventual winner third or fourth while market ranked it first or second.

The repair diagnostics classify Seattle as `winner_underpricing_vs_market`; Austin, Los Angeles, and San Francisco are mostly `current_fallback_trails_market`; NYC is `market_gap_without_clear_winner_signal`. This means the blocked markets should not all get the same repair.

## Operational Evidence

Operational state is not clean enough to treat live evidence as fully current:

- `settled_day_freshness.json` is FAIL for target date 2026-06-20. All 12 markets are missing replay status.
- `daily_learning.json` is BLOCKED with 8 blockers and 59 high-priority learning items.
- `fleet_observability.json` is CRITICAL with 28 critical alerts, 717 loop restarts, CLOB capture staleness, missing tape backup files, and market microstructure evidence starvation.
- `feature_quality_quarantine.json` excludes 4,857 rows from training/promotion/score-only paths. Seattle has the largest affected count at 709, but top markets are also affected, so quarantine volume is an amplifier rather than the full root cause.
- `data/mm_runs/daily_roll_console.log` and `data/taker_runs/daily_roll_console.log` show `OSError: [Errno 28] No space left on device`.
- The MM run recorded 0 quote rows and 132 no-quote rows with stale preflight for 2026-06-20.

These issues explain why live learning and microstructure evidence are blocked. They do not erase the historical location split, but they must be repaired before validating a production fix.

## Artifact Evidence

The old per-location HGB artifacts should not be used as promotion evidence without schema normalization:

- Several location artifacts use `toronto_feature_store_v0.2` with 24 features.
- Other location artifacts use v0.3 or v0.4 feature schemas.
- The active pooled item50 candidate uses `toronto_feature_store_v1.3` with 182 features.
- The dynamic source candidate uses 202 features.
- `artifacts/manifests/model_artifact_registry.json` marks many old per-location artifacts as unregistered runtime artifacts, while the active promoted artifacts are pooled or registered variants.

Comparing the old per-location models directly against the active pooled candidates would mix feature schema, training window, and registration status.

## Recommendations

### 1. Keep promotion location-specific and block broad rollout

Evidence:

- Atlanta is better than market on active shadow Brier by -0.0027.
- San Francisco is near market at +0.0017 but its candidate does not improve current.
- Denver is +0.0055 vs market and did not pass the promotion decision.
- Miami, NYC, and Seattle are +0.0148, +0.0231, and +0.0242 vs market.
- `f_family_promotion_refresh.json` promotes only Atlanta and Houston, keeps San Francisco in shadow, and blocks eight markets.

Validation method:

- Rerun the promotion refresh after replay status repair and the next complete settled day.
- Validate at the market-day level, not only row-level Brier.
- Require each market candidate to be within the configured market tolerance and not worsen winner gap.

Specific next action:

- Enforce the current promotion decision as the serving allowlist: promote Atlanta and Houston only, keep San Francisco shadowed, and keep Austin, Chicago, Dallas, Denver, Los Angeles, Miami, NYC, and Seattle blocked until they pass the same market-specific gate.

### 2. Build a bottom-location early/midday centering repair

Evidence:

- Bottom early regime has +0.0290 Brier excess and -0.1563 winner gap.
- Bottom midday regime has +0.0325 Brier excess and -0.1548 winner gap.
- Bottom late regime is only +0.0025 excess, so the issue is not uniform throughout the day.
- Hourly gate is blocked on early-hour Brier and log-loss.
- Ten-minute weak slots show winner probability 0.2417 vs market 0.3464.
- `item147_time_split_alpha` improves weak-slot Brier from 0.0670 to 0.0626 and winner probability from 0.2776 to 0.3244.
- `predawn_weak_slot_repair.json` passes with weak-slot Brier 0.0620 vs market 0.0615 and improves log-loss below market, but its eval split remains at +0.0030 vs market.
- The blocked-market basket validations still fail all five hard markets, so this must be a new candidate lane, not a serving shortcut.

Validation method:

- Run the hourly and ten-minute performance gates by market, with Seattle, NYC, and Miami broken out.
- Require weak-slot Brier to be within +0.003 of market and weak-slot log-loss within +0.010 of market.
- Require winner probability gap in weak slots to improve materially without overfitting late-day snapshots.

Specific next action:

- Move `item147_time_split_alpha` into active shadow for the 03:00-05:50 weak-slot window, then extend the same time-split calibration to early and midday Seattle, NYC, and Miami before considering broader promotion.
- Promote `predawn_logistic_winner_centering_item147_blend` to an explicit replay/shadow candidate with per-market reporting, and block serving unless Seattle/NYC/Miami and the aggregate weak-slot split clear tolerance.

### 3. Treat the CLOB raw overlay as a quote-risk overlay, not a weather model fix

Evidence:

- On the bottom cohort, `clob_overlay_raw_oof` improves Brier by -0.0228 vs current and beats market by -0.0017.
- It moves bottom winner gap from strongly negative to +0.0685.
- It is explicitly market-informed and only covers 19,668 rows, while the no-market candidate covers 67,430 rows and remains +0.0181 vs market in the bottom cohort.

Validation method:

- Keep market-informed and no-market tracks separated in shadow reporting.
- Validate CLOB overlay only under quote-diagnostic taxonomy gates and coverage reporting.
- Require no promotion claim to mix market-informed overlay performance into weather-only candidate promotion.

Specific next action:

- Wire `clob_overlay_raw_oof` only into quote-risk sizing or kill-switch logic for the taxonomy cases where its gate is valid. Keep it out of the no-market weather-model promotion path.

### 4. Add market-by-missingness and market-by-source gates

Evidence:

- Bottom locations are still +0.0203 Brier worse than market when all sources are fresh.
- Under `failed:wu_history`, bottom excess increases to +0.0314.
- The `469d0c0f...` missingness state is -0.0039 vs market in the top cohort but +0.0256 in the bottom cohort.
- The `3184cdfa...` missingness state is +0.0157 in the top cohort but +0.0518 in the bottom cohort.
- Source-state dynamic ablation improves current by -0.0022 aggregate, but still leaves NYC +0.0179 and Seattle +0.0213 vs market.

Validation method:

- Recompute active candidate metrics by `market_id`, `source_freshness_state`, `feature_missingness_hash`, and `forecast_source_count_bucket`.
- Decode each frequent `feature_missingness_hash` into the underlying missing feature set.
- Require Seattle, NYC, and Miami to pass both all-fresh and two-source slices before location promotion.

Specific next action:

- Add a location performance audit table to the reporting job with market/source/missingness slices, then block any candidate that only passes because weak bottom-location missingness states are averaged away.

### 5. Do not use the existing variant basket as a blocked-market shortcut

Evidence:

- The blocked-market basket selection validation remains blocked at +0.0106 Brier vs market on later-date evaluation.
- Adding item32 reanalysis rows does not change selected basket delta vs market; it remains +0.0106.
- All five tested blocked markets fail: Austin, Los Angeles, NYC, San Francisco, Seattle.
- Guarded branch policies also fail; Seattle remains +0.0149 to +0.0154 vs market depending on branch, and NYC item147 remains +0.0035 vs market.

Validation method:

- Continue using earlier-date selection and later-date evaluation, plus leave-one-market-day stability.
- Require selected basket delta vs market <= +0.0030 and no selected branch regression vs current.
- Treat oracle columns as diagnostic only, as the report already does.

Specific next action:

- Stop spending promotion effort on selecting among item134/item135/item147/item32 variants for the hard markets. Use those outputs only to generate repair features and casebook slices, then validate a new centering candidate under the same held-out selection protocol.

### 6. Audit stage-level winner mass loss by market

Evidence:

- `feature_blend` improves Brier by -0.0245 and increases winner probability by +0.1549.
- `forecast_pull` improves Brier by -0.0078 and increases winner probability by +0.0965, but worsens mean log-loss by +0.0717.
- `final_model` has more Brier-worse rows than Brier-better rows, 168,051 vs 114,912, and reduces winner probability by -0.0028 on average.
- Bottom locations are primarily failing by underpricing the winner, especially settlement-distance bucket 0.

Validation method:

- Extend `distribution_stage_attribution.json` to include `market_id x stage` output.
- For Seattle, NYC, and Miami, require final model/postprocess stages not to reduce winner probability unless they also reduce Brier and log-loss on the same market-day.

Specific next action:

- Run stage attribution for Seattle, NYC, and Miami and test an exact/adjacent winner catchup only on bottom-location early/midday snapshots where the final model reduces winner mass.

### 7. Retrain/re-export with serving-parity and honest blocked validation before claiming the core model is fixed

Evidence:

- The existing early-hour audit ties the weak-window failure to over-diffuse forecast-relative distributions.
- The core-model audit found serving-only ordinal smoothing that the tuning objective did not see.
- The core-model audit also found asymmetric validation: the baseline excluded the whole validation year while the ML path removed only the validation row.
- These issues predict the observed under-centering and make old validation lift unreliable for broad promotion claims.

Validation method:

- Re-export the active pooled F artifact after serving-parity and honest blocked-validation fixes.
- Rerun hourly, ten-minute, promotion refresh, distribution stage attribution, and location performance splits.
- Require regenerated artifact timestamps, weak-slot gate clearance, and no per-market market-tolerance regressions.

Specific next action:

- Run the long-job-safe pooled F retrain/re-export path, then make the new artifact compete against current, item147, and predawn repair on the same market-day split.

### 8. Repair evidence freshness before declaring a production improvement

Evidence:

- Settled-day freshness is FAIL for 2026-06-20 with missing replay status for all 12 markets.
- Fleet observability is CRITICAL.
- MM evidence starvation is CRITICAL.
- Disk-full errors appear in both MM and taker daily roll logs.
- CLOB captures are stale enough that quote-derived promotion evidence cannot be treated as live-current.

Validation method:

- Rerun settled-day freshness, replay backfill, data-layer audit, ingest quality gate, and fleet observability after cleanup.
- Recompute the location split after replay status is present and quarantine exclusions are applied.

Specific next action:

- Free disk or rotate artifacts, rerun replay status backfill and settled-day freshness repair, then rerun the location audit on the repaired 2026-06-20 evidence set.

Repair commands from the local artifacts:

```powershell
C:\Users\micha\Desktop\github\weather\venv\Scripts\pythonw.exe -m weather.operations.replay_status_backfill --snapshots-root C:\Users\micha\Desktop\github\weather\data\snapshots --as-of 2026-06-21
C:\Users\micha\Desktop\github\weather\venv\Scripts\pythonw.exe -m weather.operations.settled_day_freshness repair --target-date 2026-06-20 --snapshots-root C:\Users\micha\Desktop\github\weather\data\snapshots --labels-csv C:\Users\micha\Desktop\github\weather\data\backtest\market_day_labels.csv --ledger-root C:\Users\micha\Desktop\github\weather\data\settlements
```

### 9. Stop treating old per-location HGB artifacts as comparable production candidates

Evidence:

- Old per-location artifacts use mixed feature store versions, including v0.2, v0.3, and v0.4.
- Active pooled candidates use v1.3 or later schemas.
- The artifact registry marks many older per-location models as unregistered runtime artifacts.

Validation method:

- Require every candidate in a location comparison to have the same feature schema family, training cutoff policy, and registry status.
- Report old per-location models only in a historical section unless retrained under the active schema.

Specific next action:

- Retire or quarantine the old per-location HGB artifacts from promotion dashboards, or retrain all locations under the active v1.3/v1.4 feature schema before comparing them against pooled F-family variants.

## Decision

The better locations teach a specific lesson: the model works when winner mass is preserved early enough and when postprocessing does not flatten the exact/adjacent winner buckets. The worse locations teach that freshness, disagreement, and missingness are not sufficient explanations; Seattle, NYC, and Miami need location-aware early/midday centering and market-by-missingness validation. Existing variant baskets and guarded branch policies do not clear the hard markets.

Do not use the current no-market candidate as a broad production fix. Use targeted location promotion, add the predawn/item147 centering repair to shadow, keep CLOB overlay evidence separated as market-informed quote-risk logic, retrain/re-export under serving-parity validation, and rerun the audit after evidence freshness repair.
