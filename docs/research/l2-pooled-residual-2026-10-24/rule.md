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

## Amendment 2 — 2026-10-24 (coordinator rulings 1-2; appended before any U0 row or comparator row exists)

The P0-P3 decision above is final (P3 picked) and is not revisited. This amendment adds arms and a new
headline comparison on the same 11,550 rows (centre 2026-11-24, US 11, cutoffs 07-20, same blocked
leave-one-year-out folds, same label and loss functions).

- **U0 (unpooled):** the P0 design, steps 1-6 unchanged (same features, hyperparameters, inner-LOYO
  scale, floor censoring, 2% climatology mix), but each fit uses only that market's rows at hour h with
  year != Y from the 11-24 window.
- **Comparators,** taken without modification from lane L3's `weather.calibration.r0_ols_floor_challenger`
  at 171717d5f (merged, not forked), `score_market(market, 2026-11-24, the three Oct-Dec manifests)`:
  - (a) `ols_floor` (OLS on forecast_high, high_so_far, current_temp; discretised normal; no mass below
    the floor);
  - (e) `r0_baseline_floor` (the trainer baseline with the hard floor);
  - (f) `bias_corrected_forecast_floor`;
  - descriptive: `r0_floor` (R0 with the hard floor) and lane D's `hgb_floored_log_loss` rows
    (C:\wt\r0v\artifacts\candidates\retrain-r0-floor-msl20-2026-11-24\<market>\) when they exist.
  - Row gate: L3's row keys (market, hour, validation_date) must equal the R0 row set exactly, and its
    `r0_repro_log_loss` must equal the L2 R0 recomputation per row (abs diff <= 1e-9); otherwise no
    comparator result is reported.
- **Headline (decisive for this amendment):** P3 vs (a) and P3 vs (f). delta(m) = mean over market m's
  07-12 rows of (loss_P3 - loss_ref); fleet = equal-weight mean over the 11 markets. Date-clustered
  bootstrap, 2,000 draws, seed 20261024. P3 **beats** ref only if the fleet 97.5% two-sided percentile
  interval (Bonferroni over the two references) lies entirely below 0 AND no market's 95% interval lies
  entirely above 0. Otherwise: "P3 does not beat ref" (if the fleet interval lies entirely above 0:
  "P3 is worse than ref").
- **Reported, not decisive:** per hour 07-20 with hour 12 called out (its own 95% interval); P3 vs (e),
  vs r0_floor, vs lane D floored rows; U0 vs P3 (the pooling effect), U0 vs (a) and (f); Brier; crossed
  date x market interval for the two headline deltas.
- Nothing here is edge over the market; the market is not scored.

## Amendment 3 — 2026-10-24 (coordinator ruling 3: dev scorecard vs served; appended before any L2 dev-window distribution exists)

Decisive end-to-end test against the served vector, on lane L3's dev path (its dev_rule.md sha
cf75eced..., code 171717d5f), reusing L3's helpers unchanged (imported, not forked).

- **Scorer and population:** exactly L3's `dev-score` (`weather.reporting.scorecards.dev_scorecard`
  from 4be7c077c, unchanged), layout C:\swarm\v3layout, 2026-08-01..09-29, default folds (scoring from
  08-15), per-snapshot band Brier, equal (date, market) cells, the rule-4 floor mask, served fallback on
  uncovered snapshots; candidates declared trained through 2025-12-31. R = Brier / Brier_market;
  dR = R_candidate - R_served on the same cells.
- **Positive control first:** the scorecard's served-vs-market run must give pooled R 1.774 (all) and
  1.526 (00-16) on this layout (as in L3's rule); if not, nothing is claimed.
- **Serve-time inputs (identical to L3's main variant):** forecast_high = the 2026 Open-Meteo Previous
  Runs gfs_seamless previous_day1 from L3's dev PIT corpus, resolved at the snapshot's effective cutoff;
  current_temp and high_so_far from the captured METAR rows in data\inbox\replay-inputs-le0929 via L3's
  `scan_replay_observations` (raw DDHHMMZ time, local target date, observed at or before h:00, max since
  midnight); floor = round_half_up(high_so_far). Snapshots get a candidate only when the effective cutoff
  is 07-20 and the local hour is at or after it; everything else falls back to served.
- **P3d (decisive):** the P3 design (steps 1-6 of the original rule, same hyperparameters) restricted to
  the inputs available at serve with parity: forecast_high, high_so_far, current_temp (as features:
  high_so_far - mu0, current_temp - mu0, g, max(g, 0), mu0 - normal), station lat/lon/elevation, the
  market normal and bias, day-of-year sin/cos. Pooled over the US 11, one fit per cutoff hour on every
  record of the Aug-Sep 2021-25 corpus b455bd53... (centres 08-08, 08-23, 09-07, 09-22; all five years;
  the inner leave-one-year-out for the scale runs over those five years). Bias per (market, cutoff);
  normal per (market, centre), a dev date using the centre nearest its month-day. The 2% climatology mix
  uses that market's training buckets at the cutoff over the 09-07 payload's bucket_space. No 2026 row
  is used in any fit.
- **U0d (descriptive):** the same, fitted per market.
- **Verdict (L3's rule, applied to P3d):** P3d beats served only if pooled 07-12 dR < 0 with its 95%
  date-clustered CI upper bound < 0 AND no standard block (00-05, 06-09, 10-12, 13-16, 17-23, 00-16,
  all) has a pooled dR whose 95% date-clustered CI lower bound is > 0. The crossed date x market interval
  is reported beside it; on disagreement no claim is made beyond the date-clustered verdict.
- **Reported, not decisive:** U0d; per hour 07..20 with 12 called out; 12-16; per market; P3d beside L3's
  (a) and (f) dev results on the same layout when L3 publishes them.
- Not edge: the market is the scorecard's denominator only; no trading claim follows.

## Amendment 4 — 2026-10-24 (full-year arm on L1's corpus; appended before any Jan-Jul record or P3F row exists)

- **Corpus:** L1's full-year union 621bcd8e... Jan-Jul parts 3a7034d2... (2021), 672a1f57... (2022,
  2023, 2025), ece9d1c2... (2024), plus the Aug-Sep and Oct-Dec corpora already used. Each centre's
  +/-7-day window lies inside one season, so the trainer's year-keyed union is read per centre with the
  three Jan-Jul manifests (no year has two corpora within one centre).
- **Jan-Jul centres:** 01-08, 01-23, 02-07, 02-22, 03-09, 03-24, 04-08, 04-23, 05-08, 05-23, 06-07,
  06-22, 07-07, 07-22. A (centre, year) is used only if the corpus coverage file has a complete row at
  every cutoff 07-20 for every US-11 market on every day of the window; otherwise that year is excluded
  for that centre (all markets), via the trainer's explicit training-years restriction. A centre that
  still fails closed is dropped whole (amendment 1).
- **P3F:** the P3 design (steps 1-6, same hyperparameters, day-of-year on, no market id), trained per
  cutoff on every available centre (Jan-Jul, Aug-Sep, Oct-Dec) with year != Y, validated on the same
  11-24 rows. Bias and normal per (market, cutoff, centre) for P3F (season blocks are too coarse across
  Jan-Jul).
- **Comparisons:** P3F vs (a) and vs (f) under amendment 2's headline criterion (97.5% Bonferroni fleet
  interval below 0, no market 95% interval above 0) — a separate family from P3's; P3F vs P3 and vs raw R0
  descriptive. Per hour with 12 called out.

## Amendment 5 — 2026-10-25 (P3d_N for the MG-2 afternoon pick; appended before any P3d_N row exists)

Sha of this file before this amendment: 53ba558b50502fd51bf5565c448493169ae2c6524234b5f4439de6a92bde3a32.
Reason: MG-2 pick rule C:\t\mg2\afternoon_pick_rule.md (sha256 deb3eae31fb19cc96c90d1a9267f292e8a819fae1784c7b8b950071be99ceffb),
Clarification 2 (master approved option (N) of C:\t\mg2\forecast_analogue.md). The lead-1 Previous Runs forecast is
removed from P3d; it is re-specified on the captured NBM 07Z mean. L2 emits vectors only: L2 does NOT score P3d_N
against MG-1 or A_N, and does not open C:\t\mg2\control_refit_armA.json or any A_N vector. L3 runs the pick (dev-pick).

- **P3d_N:** the P3d design unchanged (amendment 3: steps 1-6, same hyperparameters, pooled per cutoff, day-of-year
  on, no market id; x features high_so_far and current_temp only; bias per (market, aug_sep), normal per (market,
  centre); 2% climatology mix over the 09-07 payload's bucket_space), with the anchor column fh := nbm_mean in place of
  forecast_high, in training and at serve. mu0 = nbm_mean + bias.
- **Training rows:** the same 45,873 Aug-Sep 2021-25 trainer records as P3d (union 744289be... of b455bd53...).
  nbm_mean = lane L9's `ols_floor_ladder.nbm_at_cutoff(load_nbm(corpus), market, target_date, cutoff_hour, tz)` on
  corpus 1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd (C:\t\l9\nbm_corpus\nbm_pit_corpus_rows.jsonl,
  07Z, LastModified <= the cutoff); when None it is imputed with the record's forecast_high (L9 IMPUTE "fc"; count
  reported). high_so_far / current_temp / label as P3d. No 2026 row.
- **Dev rows (A_N's rule, L3 `dev_emit` variant nbm_n2 at ecd8c9ba6):** every C:\swarm\v3layout snapshot with
  effective cutoff 07-20 and local_hour >= cutoff. Inputs, all from captured fields:
  - nbm_mean = `r0_ols_floor_devfit.usable_v2_mean` (layout v2_mean where v2_mean and v2_stddev are finite and
    v2_available_at <= captured_at_utc); not finite -> not emitted (served fallback).
  - high_so_far (feature, g and the floor) = `observed_running_max.running_max_since_midnight(station={},
    metar=sources.metar.data, target_date, tz, unit=display_unit, cutoff_hour=h, now=capture time, metar_only=True)`
    (file blob 40c84103... at fe4782e66, pick-rule C1 / binding rule C1) on the last replay snapshot captured in
    [h:00, h+1:00) of data\inbox\replay-inputs-le0929; None -> not emitted.
  - current_temp = latest captured METAR row observed at or before h:00 on that snapshot (L3 `observations_at_cutoff`,
    unchanged); None -> not emitted.
- **Cross-checks (recorded in the audit, do not change emission):** the 2026 corpus 85746b7a... read with
  `nbm_at_cutoff` vs the emitted nbm_mean (exact-match count per hour); snapshot set vs P3d's 79,403; METAR-only
  high_so_far vs P3d's main high_so_far (floor-differs count).
- **Output:** C:\t\l2\p3d_n_dev\dev_P3d_N.jsonl (same format as dev_P3d.jsonl; refuses to overwrite) and
  dev_emit_audit.json, with shas; serve-parity note C:\t\l2\p3d_n_serve_parity.md. Parity passes only if every model
  input at dev is computed from captured fields with the serve-time cutoff semantics, with no imputation at dev.

## Clarification 3 — 2026-10-25 (P3d_N forward-window refit: a spec freeze, not a selection; appended before any refit row exists)

Sha of this file before this clarification: b3f017bbf3d634b142e0d2eb2b1ae7ba38fd65b74b069c3cfee2d8cc5d19de68.
Reason: P3d_N won the MG-2 afternoon pick (C:\t\mg2\pick_result.json); the forward window is Oct-Dec. Nothing below is
chosen by any score. No refit row is scored on 2026 dev; no 2026 row enters training or is emitted.

- **(a) Training window: Aug-Dec 2021-25** (December rows exist for all 11 markets, so the Aug-Dec branch applies;
  decided from availability only). Centres 08-08, 08-23, 09-07, 09-22, 10-10, 10-25, 11-09, 11-24, 12-09, each +/-7 days
  (12-24 is dropped: it fails closed on atlanta 2023-12-29, amendment 1). Covered dates: 08-01..09-29 and 10-03..12-16;
  Dec 17-31 is in no corpus. Trainer records (WU labels, high_so_far, current_temp): Aug-Sep union 744289be... of
  b455bd53...; Oct-Dec corpora cd0ba2bb..., 23ac87fa..., 74807fbe... (the record set the coordinator cites as 674b12ac...).
  NBM: corpus 1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd unchanged (07Z; 135 days per year per
  market, no missing row in any record window), so no fetch and no new corpus id. nbm_mean via L9 `nbm_at_cutoff`;
  None -> the record's forecast_high (count reported). Years 2021-25 only; the fit refuses any other year. Per-market x
  month x year availability (days, rows) is written into the frozen state's provenance.
- **Model:** amendment 5's P3d_N unchanged except the window: per cutoff 07-20, pooled, day-of-year on, no market id,
  x features high_so_far and current_temp, bias per (market, season) with season_of = aug_sep (Aug-Sep) / oct_dec
  (Oct-Dec), normal per (market, centre), same hyperparameters, 2% climatology mix (alpha 0.10) over the per-market
  sorted union of the centres' bucket_space. Bias, normal and buckets are read at serve from the nearest centre by
  month-day (first centre wins a tie).
- **(b) Frozen artifact (L8 schema `mg2_p3d_n_state/1` as relayed by the coordinator on 2026-10-25, unchanged):**
  C:\t\l2\forward\state\p3d_n_state.pkl = pickle.dumps(state, protocol=4), sha256 of the file bytes, plus sidecar
  p3d_n_state.json (provenance + state_sha256), fit_kind "forward", exported by `pooled_residual_model forward-fit` from
  branch claude/pooled-residual-model-20261024. Both files are written once (refuse overwrite). The sha is entered in
  C:\t\l2\forward\frozen_record.json before D0; L8 binds that sha. Export parity: the state's reference serve math must
  reproduce the fitted MeanModel on sampled training rows to 1e-9, or the export fails.
- **(c) Units rule: `wu_whole_f_tgroup:half_up`.** Serve-time METAR temp_native (T-group C * 1.8 + 32) for high_so_far
  and current_temp is converted to WU whole F as round-half-up of the exact value 32 + 9t/50 (t = T-group tenths C),
  before g, the floor and the features. Evidence (training years only, Aug-Dec 2021-25, 11 markets; IEM T-group vs WU
  hourly temp joined on valid time; C:\t\l2\forward\wu_rounding.json sha256
  0a67338f9fff538bc0f41cc564fff875137b28daf5b314ee2713e0190764cbfd): half_up 227,969 / 227,999 rows (99.987%) and
  352 / 354 exact .5 ties; half_even 227,783 rows, 166 ties; half_down 227,619, 2 ties; ceil 126,224, 352 ties; floor
  125,755, 2 ties. Unambiguous. Training values are WU whole F already (no conversion; non-integer count reported).
- **(d) Late-report rule: `last_in_hour` (grace_minutes null).** At cutoff h, high_so_far and current_temp use METAR rows
  observed at or before h:00 as received in the last capture snapshot in [h:00, h+1:00) -- the rule P3d_N was emitted
  and picked on (amendment 5). In training: all WU rows observed at or before h:00 (the eventually-received set; WU
  2021-25 history carries no receipt time). The suggested receipt_by rule does not fit training: no receipt stamps
  exist in the training data, so it cannot be applied there, and at serve it diverges from the received-by-the-hour
  set. Evidence (capture-only, dev-window replay snapshots; C:\t\l2\forward\receipt_grace.json sha256
  ff90a1a2f4d21727039761934b5d48b925083e20037c8c52f3734b8f32a4ab8a): receipt_by grace 0/5/10/15/20 min agrees with
  last_in_hour features on 84.9 / 89.5 / 94.4 / 96.7 / 98.1% of 9,224 market-hours; denver 6.9 / 16.9 / 56.1 / 74.8 /
  87.3% (no grace reaches 99% fleet-wide). A serve process running at time t inside the hour uses the latest snapshot
  captured <= t (never a later one).
