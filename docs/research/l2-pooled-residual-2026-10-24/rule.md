# L2 pooled residual model: pre-declared pass/pick rule (2026-10-24)

Written 2026-10-24 15:25 EDT, before any pooled-model fit, any per-row loss of a pooled arm, and any
R0 recomputation exists. Authority: coordinator lane L2 brief (10-24). Branch
claude/pooled-residual-model-20261024 from e1d1f3200. Module weather.calibration.pooled_residual_model.

## Population and rows (identical for every arm)

- Markets: the US 11 of r0_scope.R0_MARKET_IDS (atlanta, austin, chicago, dallas, denver, houston,
  los-angeles, miami, nyc, san-francisco, seattle).
- Validation rows: exactly the R0 trainer's rows at centre 2026-11-24 (prior-year +/-7-day window,
  years 2021-2025, PIT corpora cd0ba2bb / 23ac87fa / 74807fbe = union 674b12ac..., r0 allowlist,
  cutoff hours 07..20, one deterministic wall offset per (day, hour)), built by the trainer's own
  functions (build_feature_records_for_model on TorontoHighTempModel(target_date=2026-11-24)).
  A row is (market, cutoff hour, validation date). Label: the record's final_bucket.
- Validation: blocked leave-one-year-out (the trainer's holdout_year plan). For held-out year Y every
  arm trains only on rows with year != Y; every per-market bias, normal, climatology, imputer and
  scale model is fit inside that training fold (and inner folds inside it), never on year Y.

## Arms

- **R0 (comparator):** the trainer's per-market HGB arm, leaf 20, exactly as `_train_main` scores it:
  HistGradientBoostingClassifier (make_feature_hgb, min_samples_leaf 20) on fold-local matrices,
  blended 0.80 with the fold climatology smoothed_dist(alpha 0.10) over bucket_space; loss by
  feature_model.log_loss / brier_score. Recomputed by the L2 module with the trainer's functions (one
  fit per (market, hour, held-out year), which is identical to the trainer's per-row refit because the
  training set depends only on the year). **Parity gate:** for every market where lane D's
  feature_model_blocked_validation_rows_<market>.jsonl (C:\wt\r0v\...\retrain-r0-pick-msl20-2026-11-24)
  exists, the recomputed hgb_log_loss must match it per row (abs diff <= 1e-9). If parity fails, no
  result is reported as a comparison until the cause is found.
- **Pooled arms** (shared definition, fixed before any result; no hyperparameter is tuned on held-out
  rows). Per cutoff hour h and held-out year Y, training rows = all US 11 markets at hour h with
  year != Y from the arm's centres:
  1. Bias per market (and per season block for P3), per cutoff, in fold: b = mean(final_bucket -
     forecast_high) over training rows with a forecast; mu0 = forecast_high + b; if forecast_high is
     missing, mu0 = the market's in-fold mean final_bucket (its normal).
  2. Floor F = high_so_far (observed running WU high at the cutoff); g = F - mu0.
  3. Stage 1 pooled OLS: (y - mu0) ~ 1 + g + max(g, 0).
  4. Stage 2 HistGradientBoostingRegressor on the stage-1 residual (max_iter 200, learning_rate 0.05,
     max_leaf_nodes 15, min_samples_leaf 40, l2_regularization 1.0, early_stopping False,
     random_state 42). Features: the r0 allowlist columns common to all 11 markets; the temperature
     levels high_so_far, current_temp, live_reading_temp minus mu0; g, max(g, 0); mu0 minus the
     market normal; station lat, lon, elevation (config); the in-fold market normal and bias.
     Mean: yhat = mu0 + stage1 + stage2.
  5. Scale: inner leave-one-year-out over the training years (steps 1-4 refit inside each inner fold)
     gives out-of-fold errors e = y - yhat. A HistGradientBoostingRegressor (max_iter 100,
     learning_rate 0.05, max_leaf_nodes 7, min_samples_leaf 40, random_state 42) fit on |e| with the
     same features plus yhat - F gives s = max(0.5, pred * sqrt(pi/2)). Standardised errors z = e / s.
  6. Predictive distribution: Y = yhat + s * Z, Z the empirical z set smoothed by a Gaussian kernel of
     bandwidth 0.25. Bucket k gets P(k - 0.5 <= Y < k + 0.5). Hard floor: all mass below bucket
     round_half_up(F) is moved onto that bucket. Final p = 0.98 * p + 0.02 * p_clim, p_clim the
     trainer's in-fold smoothed_dist(alpha 0.10) of that market's training buckets over bucket_space.
- **P0:** pooled, centre 2026-11-24 window only (the R0 training rows), no market id.
- **P1:** P0 plus market id as a categorical feature.
- **P2:** P0 trained on the whole Oct-Dec corpus: centres 10-10, 10-25, 11-09, 11-24, 12-09, 12-24
  (each +/-7 days, years 2021-2025, same corpora), with day-of-year sin/cos added. Validation rows are
  still only the 11-24 rows.
- **P3:** P2 plus the Aug-Sep corpus b455bd53... (centres 08-08, 08-23, 09-07, 09-22); bias and
  normal per (market, cutoff, season block). Validation rows unchanged.

## Metric, window, CI

- Primary metric: per-row multi-class log loss over integer native buckets (feature_model.log_loss).
  Brier (feature_model.brier_score) is reported, not decisive.
- Window: cutoff hours 07..12 inclusive.
- delta_A(m) = mean over market m's 07-12 rows of (loss_A - loss_R0). Fleet delta_A = equal-weight
  mean over the 11 markets of delta_A(m).
- CIs: bootstrap over validation-date clusters (a resampled date carries all its markets and hours),
  2,000 draws, seed 20261024, percentile intervals.

## Decision

- An arm A in {P0, P1, P2, P3} **passes** only if both hold:
  1. the fleet delta_A upper bound of the Bonferroni-adjusted interval (four arms: 98.75% two-sided,
     percentiles 0.625 / 99.375) is < 0; and
  2. no market has a delta_A(m) 95% CI lower bound > 0 (no market worse than R0 beyond its CI).
- **Pick:** among passing arms, the lowest fleet delta_A point estimate (exact tie: the simpler arm in
  the order P0, P1, P2, P3). If none passes: no pooled model replaces R0 on this evidence (KILL for
  this population and centre).
- Robustness, reported but not decisive: the picked arm's fleet delta under a crossed date x market
  bootstrap (EF section 5); if its 95% interval includes 0 the report says so explicitly.
- Reported descriptively: every arm per hour 07..20 and per market, with 07 and 12 called out; Brier;
  the trainer baseline arm on the same rows; date and market cluster counts.
- No re-fit, no hyperparameter change and no extra arm after the first result may be scored under this
  rule; any later variant needs its own pre-declared rule and is labelled post-hoc here.

## Amendment 2026-10-24 16:04 EDT (appended before any pooled-arm loss or R0 recomputation exists for the full run)

Extraction of centre 2026-12-24 failed closed on the corpus contract (CorpusVerificationError: no
cutoff-valid PIT daily forecast for atlanta 2023-12-29 07:00). The trainer path is not relaxed. Any
P2/P3 centre whose extraction fails closed this way is dropped as a whole, for every market, and the
report lists the dropped centres. P2 is therefore Oct-Dec centres 10-10, 10-25, 11-09, 11-24, 12-09
(unless another fails); P3 adds whichever Aug-Sep centres extract. Nothing else changes (arms,
metric, window, CI, Bonferroni over four arms, decision).
