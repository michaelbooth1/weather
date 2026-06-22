# 35. Unified Continuous-Density Model [PARTIAL 2026-06-22 - V0.7 DIAGNOSTICS REFRESHED, TARGET-DAY SIGNAL BLOCKED]

Goal: one model for all cities; C/F becomes serving-only (audit Option B).

Source: Track B production-model roadmap and the core model architecture
audits, which called out duplicated family-specific probability machinery and
unit-sensitive band projection as a long-term calibration risk.

Why this matters: a continuous native-temperature density can share evidence
across sparse markets while projecting into each market's native bands at serve
time. The item remains active until that architecture beats current serving
per market instead of only simplifying the model shape.

- [x] Predict a fine canonical-grid / continuous max-temp density pooled across
  all 12 cities plus city features.
- [x] Add the serving-time discretization foundation that integrates a fine
  canonical-F density over each market's native rounded bands without C/F
  leakage.
- [x] Wire explicit continuous-density payloads through serving/replay so each
  market's native bands are computed from the canonical-F density at serve time.
- [x] Keep existing market-bin calibration on density-projected band
  probabilities.
- [x] Train a first pooled continuous-density candidate artifact and emit
  serving/replay-compatible density payloads.
- [x] Integrate the density artifact as a named pinned-replay/promotion
  candidate lane.
- [x] Port exact-distribution calibration and floor logic from integer buckets
  to the continuous representation before any promotion gate can rely on it.
- [x] Add a unit-aware all-market direct market-band baseline lane so density
  projection failures can be compared against a model trained on native replay
  band outcomes.
- [ ] Prove it rescues the data-poor C/Canada family (Toronto borrows US-city
  structure).

Acceptance: the unified model matches or beats the family models per-market and
lifts the data-poor side.

## 2026-06-16 update

- Added `weather.model.continuous_density` as the first Item 35 foundation. It
  uses a fine canonical Fahrenheit grid, normalizes density weights, maps
  round-half-up native settlement buckets to half-open continuous intervals, and
  discretizes C or F market bands only at serving/projection time.
- Added tests covering stable grid construction, exact/lte/gte boundaries,
  Celsius serving conversion from the canonical-F grid, range bands, and
  probability conservation over exhaustive market bands:
  `python -m pytest tests/model/test_continuous_density.py -q` passed.
- Remaining work is still substantial: train the pooled continuous-density
  candidate, move calibration/floors off integer buckets, integrate replay and
  serving, and prove per-market lift including Toronto.

## 2026-06-16 serving/replay adapter update

- Added an explicit `continuous_density_f` payload shape in
  `weather.model.continuous_density`, including guarded detection so legacy
  native `{bucket: probability}` distributions cannot be misread as canonical
  densities.
- `PresentationMixin.bin_probability` now accepts those density payloads,
  projects them to the active market's native C/F rounded band, and then applies
  the existing market-bin calibration layer. The replay helper
  `band_model_probability` uses the same serving path, so continuous-density
  candidates can be replay-scored without a parallel probability implementation.
- Added tests for helper extraction, Toronto Celsius serving projection, US
  Fahrenheit serving projection, and replay-band probability projection:
  `python -m pytest tests/model/test_continuous_density.py tests/model/test_market_units.py tests/backtesting/test_replay.py -q`
  passed.
- Remaining work: train the pooled density candidate, make exact-distribution
  calibration/floor operations operate directly on the continuous
  representation, run the pinned replay/promotion gates, and prove per-market
  lift including Toronto.

## 2026-06-16 all-market density candidate update

- Added `--objective density` to `pooled_feature_model`. The density objective
  defaults to `--family-unit all`, converts temperature-like training features
  and targets to canonical Fahrenheit, trains hourly pooled HGB regressors over
  all configured markets, and emits `continuous_density_f` Gaussian-residual
  payloads on the canonical-F grid.
- Registered `pooled_continuous_density_hgb_v0.1` and added report/artifact
  defaults for the new candidate lane.
- Added tests for Toronto C-to-F canonicalization, mixed Toronto/NYC density
  training, payload prediction, and density evaluation.
- Real-data smoke:
  `python -m src.pooled_feature_model --objective density --hours 12 --max-days-per-market 30 --holdout-year 2025 --artifact data/backtest/item35_density_smoke.pkl --out data/backtest/item35_density_smoke_report.md`
  trained over 360 source rows, 30 per market across all 12 markets. The smoke
  artifact reports schema `pooled_continuous_density_hgb_v0.1`, prediction mode
  `continuous_density_f`, grid `43.0` to `113.0` F at `0.1` F, and one 12:00
  model with 360 final train rows.
- Smoke holdout metrics are not promotion evidence yet: 12:00 held-out rows had
  aggregate density logloss `3.2464`, winner-bucket Brier `0.7158`, and MAE
  `1.9354` F. Remaining work is to run full-hour pinned replay, compare against
  current family models per market, and port continuous-native floor/calibration
  before any promotion decision.

## 2026-06-16 replay/promotion lane update

- Added a `continuous_density_f` candidate path to
  `pooled_candidate_replay`. Density artifacts now rebuild the same pinned
  snapshot features as the existing candidates, predict one canonical-F density
  payload per snapshot, and project that payload onto each replay row's native
  C/F market band.
- Density replay artifacts default to the named shadow lane
  `pooled_continuous_density_hgb_v0_1` / `pooled_continuous_density`; F-family
  band artifacts keep the existing `pooled_f_candidate` lane defaults.
- Extended `promotion_refresh` so `--family-unit all` includes every configured
  market and candidate shadow-variant lane arguments pass through to replay.
- Real pinned-smoke replay:
  `python -m src.pooled_candidate_replay --corpus data/backtest/item35_density_replay_smoke_corpus.json --artifact data/backtest/item35_density_smoke.pkl --out data/backtest/item35_density_replay_smoke_report.md --json-out data/backtest/item35_density_replay_smoke.json --replay-report= --candidate-variant-out data/backtest/item35_density_shadow_variants_smoke.csv --skip-microstructure-overlay --disable-long-job-guard`
  scored the Toronto/NYC two-day corpus as an all-market density artifact and
  wrote the named variant CSV. Because the smoke artifact only contains a 12:00
  hour model, it scored 55 of 1,771 replay rows and correctly remained `BLOCK`.
- Promotion-wrapper smoke:
  `python -m src.promotion_refresh data\snapshots\highest-temperature-in-toronto-on-june-3-2026 data\snapshots\highest-temperature-in-nyc-on-june-7-2026 --family-unit all --artifact data/backtest/item35_density_smoke.pkl --candidate-variant-out data/backtest/item35_density_promotion_variants_smoke.csv --corpus-out data/backtest/item35_density_promotion_smoke_corpus.json --candidate-report data/backtest/item35_density_promotion_candidate_report.md --candidate-json data/backtest/item35_density_promotion_candidate.json --current-replay-report= --skip-serving-gauntlet --skip-microstructure-overlay --out data/backtest/item35_density_promotion_smoke.json --report data/backtest/item35_density_promotion_smoke_report.md --quality-grades all --disable-long-job-guard`
  produced an all-market promotion refresh with the density lane wired through:
  0 promote, 10 shadow, 2 blocked; readiness stayed `OPEN`.
- Remaining blockers are now narrower: train full-hour density artifacts and
  prove per-market lift before using this lane for promotion.

## 2026-06-16 continuous floor/calibration update

- Added `apply_continuous_density_calibration` to
  `probability_calibration`. It mirrors the exact-bucket calibration semantics
  for `continuous_density_f` payloads: it zeroes canonical-F density mass below
  the lower edge of the observed native rounded floor bucket, applies the same
  hour-aware temperature/prior shape to eligible grid points, and preserves
  normalized density payloads for serving/replay.
- `PresentationMixin.bin_probability` now applies the continuous density
  calibration path when a density payload is served with a probability
  calibration context, then projects to native C/F market bands and applies the
  existing binary market-bin calibration.
- The pinned density replay lane applies the same continuous floor/calibration
  helper from rebuilt snapshot features before projecting the candidate payload
  to each market band, so replay and serving use the same floor semantics.
- Added tests for C-native floor conversion, continuous density floor
  projection, raw density projection without calibration context, and density
  replay integration. The latest Toronto/NYC smoke still blocks as expected:
  55 of 1,771 rows scored, candidate Brier `0.1334`, current Brier `0.1063`,
  market Brier `0.0768`.

## 2026-06-16 full density replay update

- Trained a full-hour all-market density artifact:
  `python -m src.pooled_feature_model --objective density --holdout-year 2025 --artifact data/backtest/item35_density_full_candidate.pkl --out data/backtest/item35_density_full_candidate_report.md`
  wrote schema `pooled_continuous_density_hgb_v0.1`, prediction mode
  `continuous_density_f`, family unit `all`, canonical grid `35.0` to `122.0`
  F at `0.1` F, and hourly models for 07:00 through 20:00.
- Replayed that artifact against the pinned promotion corpus:
  `python -m src.pooled_candidate_replay --corpus data/backtest/promotion_corpus.json --artifact data/backtest/item35_density_full_candidate.pkl --out data/backtest/item35_density_full_replay_report.md --json-out data/backtest/item35_density_full_replay.json --replay-report= --candidate-variant-out data/backtest/item35_density_full_shadow_variants.csv --skip-microstructure-overlay --disable-long-job-guard`
  scored all 76,879 market rows across 51 market-days with no missing candidate
  rows and wrote the named shadow-variant CSV.
- The full replay blocked cutover rather than proving the acceptance target:
  aggregate candidate Brier `0.0524` versus current `0.0427` and market
  `0.0373`, so the candidate regressed current by `+0.0097` and market by
  `+0.0151`.
- Toronto, the explicit C/Canada proof target, also blocked: 9,449 rows over 7
  days had candidate Brier `0.0425`, current `0.0369`, market `0.0334`, delta
  versus current `+0.0056`, and delta versus market `+0.0091`.
- The implementation lane is now replay-complete and fully covered on the
  pinned corpus, but the proof checkbox remains open until a density variant
  beats current family models per market and lifts Toronto.

## 2026-06-18 audit disposition

The Python audit confirmed the continuous-density code path is implemented
through training, serving projection, calibration/floor logic, pinned replay,
promotion-lane wiring, and regression tests. The remaining unchecked item is an
empirical acceptance condition: the trained density variant must beat current
family models per market and lift Toronto. The latest full replay failed that
condition, so this item stays open until a new candidate design earns promotion
evidence rather than being marked complete by code-only work.

## 2026-06-18 holdout-sigma update

The audit found a math-quality issue in the density candidate: the Gaussian
residual width used for serving/replay was estimated from in-sample HGB
residuals, which can make the canonical-F density too sharp. The density
artifact schema is now `pooled_continuous_density_hgb_v0.2`; when
`--holdout-year` provides enough validation rows, final hourly models use the
holdout residual RMSE for `sigma_f` while still fitting the mean regressor on
all rows. Sparse holdout hours fall back to the prior in-sample residual RMSE
and record that fallback explicitly. This is a candidate-quality fix, not proof
of acceptance; the checkbox remains open until a regenerated artifact and
pinned replay beat current family models per market and lift Toronto.

Smoke evidence:
`python -m weather.calibration.pooled_feature_model --objective density --hours 12 --max-days-per-market 30 --holdout-year 2025 --artifact data\backtest\item35_density_sigma_smoke.pkl --out data\backtest\item35_density_sigma_smoke_report.md`
trained over 360 rows and wrote schema `pooled_continuous_density_hgb_v0.2`.
The 12:00 model recorded `sigma_source=holdout_residual_rmse` with 180
holdout residuals and final `sigma_f=2.4629`, replacing the sharper in-sample
sigma path for this smoke artifact.

Full replay evidence:
`python -m weather.calibration.pooled_feature_model --objective density --holdout-year 2025 --artifact data\backtest\item35_density_full_candidate_v0_2.pkl --out data\backtest\item35_density_full_candidate_v0_2_report.md`
trained a full-hour v0.2 artifact with hourly models from 07:00 through 20:00.
Every hourly model used `sigma_source=holdout_residual_rmse` with 180 holdout
residuals. The paired pinned replay then scored the artifact with:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item35_density_full_candidate_v0_2.pkl --out data\backtest\item35_density_full_replay_v0_2_report.md --json-out data\backtest\item35_density_full_replay_v0_2.json --replay-report= --candidate-variant-out data\backtest\item35_density_full_shadow_variants_v0_2.csv --candidate-variant-id pooled_continuous_density_hgb_v0_2 --candidate-variant-family pooled_continuous_density --skip-microstructure-overlay --source-state-ablation-variant-out data\backtest\item35_density_source_state_ablation_v0_2.csv --bridge-variant-out data\backtest\item35_density_bridge_shadow_variants_v0_2.csv --disable-long-job-guard`.

The v0.2 candidate remains blocked on the empirical acceptance condition:
validation verdict `BLOCK`, market-only verdict `BLOCK`, cutover decision
`DO_NOT_CUT_OVER`. It scored all 81,444 market rows across 54 market-days with
no missing candidate rows. Aggregate candidate Brier was `0.0522` versus
current `0.0420` and market `0.0366`; daily-first equal-day average also had
candidate Brier `0.0522`, current `0.0420`, market `0.0366`, and delta versus
current `+0.0102`, above the `0.0030` regression tolerance. Toronto still
blocked with 14,014 rows over 10 days: candidate Brier `0.0441`, current
`0.0348`, market `0.0306`, delta versus current `+0.0094`, and delta versus
market `+0.0135`. The conservative bridge shadow policy improved the base
candidate to Brier `0.0443`, but still regressed current by `+0.0023` and
market by `+0.0077`, so it is not promotion evidence.

## 2026-06-18 density replay floor-context fix

The replay adapter was corrected so continuous-density candidates derive
`observed_floor_bucket` and `late_lockin_strength` through the same
`band_prediction_record` path used by the band candidate before applying
continuous density calibration. The old v0.2 replay passed raw snapshot
features directly, so the claimed floor semantics were under-applied in the
density lane. Added a regression test where half of the canonical-F density is
below the observed native floor and the projected market probability only
passes when that floor context is derived.

Corrected pinned replay:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item35_density_full_candidate_v0_2.pkl --out data\backtest\item35_density_full_replay_v0_2_floorfix_report.md --json-out data\backtest\item35_density_full_replay_v0_2_floorfix.json --replay-report= --candidate-variant-out data\backtest\item35_density_full_shadow_variants_v0_2_floorfix.csv --candidate-variant-id pooled_continuous_density_hgb_v0_2_floorfix --candidate-variant-family pooled_continuous_density --skip-microstructure-overlay --source-state-ablation-variant-out data\backtest\item35_density_source_state_ablation_v0_2_floorfix.csv --bridge-variant-out data\backtest\item35_density_bridge_shadow_variants_v0_2_floorfix.csv --disable-long-job-guard`.

The fix improved but did not unblock the item. The corrected replay scored
76,879 rows across 51 market-days with no missing candidate rows, but the
verdict stayed `BLOCK` / `DO_NOT_CUT_OVER`: aggregate candidate Brier `0.0516`
versus current `0.0427` and market `0.0373`; daily-first candidate Brier
`0.0507` versus current `0.0420`, delta `+0.0087` above the `0.0030`
tolerance. Toronto improved from the stale-floor replay but still blocked:
9,449 rows over 7 days, candidate Brier `0.0418`, current `0.0369`, market
`0.0334`, delta versus current `+0.0049`. The remaining failure is still
winner-bucket underpricing: settlement-distance `0` Brier is `0.4259` versus
current `0.3444` and market `0.2784`.

## 2026-06-18 holdout winner-brier sigma tuning

The density trainer now emits schema `pooled_continuous_density_hgb_v0.3`.
Instead of using holdout residual RMSE directly as the serving/replay Gaussian
width, each hourly density model grid-searches a small set of sigma scales and
selects the width with the best holdout winner-bucket Brier. This keeps the
same `continuous_density_f` serving contract while aligning the width selection
with the market-band replay gate that blocked v0.2.

Implementation details:

- `train_pooled_density_models` records `sigma_policy.preferred` as
  `holdout_winner_brier_grid_search`, stores per-hour `sigma_tuning` metadata,
  and falls back to in-sample residual RMSE only when holdout rows are too
  sparse.
- Density candidate shadow-lane defaults now derive from the artifact schema
  when present, so a v0.3 artifact defaults to
  `pooled_continuous_density_hgb_v0_3`.
- `schema_registry` marks `pooled_continuous_density_hgb_v0.3` active and
  preserves v0.2/v0.1 as legacy schemas.

Smoke evidence:
`python -m weather.calibration.pooled_feature_model --objective density --hours 12 --max-days-per-market 30 --holdout-year 2025 --artifact data\backtest\item35_density_sigma_tuned_smoke.pkl --out data\backtest\item35_density_sigma_tuned_smoke_report.md`
trained over 360 rows. The 12:00 model selected
`sigma_source=holdout_winner_brier_grid_search`, reducing the smoke holdout
winner-bucket Brier from `0.7150` at RMSE sigma to `0.7133` at the selected
sigma `0.9104` F. This is directionally correct but small; it is not promotion
evidence.

Full-hour v0.3 training/replay in this continuation:
`python -m weather.calibration.pooled_feature_model --objective density --holdout-year 2025 --artifact data\backtest\item35_density_full_candidate_v0_3.pkl --out data\backtest\item35_density_full_candidate_v0_3_report.md`
now completes after `blocked_validation_audit` was changed to summarize split
groups directly instead of materializing every train/validation index list for
the high-cardinality leave-one-market-day audit. The full artifact trained over
76,957 source rows with hourly models from 07:00 through 20:00. Every hourly
blocked-validation audit passed with zero leaks, and the v0.3 holdout grid
search improved holdout winner-bucket Brier versus RMSE sigma for every hour.

The paired full pinned replay still blocks the item:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item35_density_full_candidate_v0_3.pkl --out data\backtest\item35_density_full_replay_v0_3_report.md --json-out data\backtest\item35_density_full_replay_v0_3.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --skip-microstructure-overlay --source-state-ablation-variant-out= --bridge-variant-out= --disable-long-job-guard`.

The v0.3 replay scored all 76,879 market rows across 51 market-days with no
missing candidate rows, but the verdict stayed `BLOCK`, market-only verdict
`BLOCK`, and cutover decision `DO_NOT_CUT_OVER`. Aggregate candidate Brier was
`0.0585` versus current `0.0427` and market `0.0373`; daily-first candidate
Brier was `0.0575` versus current `0.0420`, a `+0.0155` regression above the
`0.0030` tolerance. Every market blocked. Toronto, the explicit data-poor
Canada proof target, regressed to candidate Brier `0.0597` versus current
`0.0369` and market `0.0334`. The largest slice failures are early rows
(`0.0888` candidate versus `0.0645` current), midday rows (`0.0809` versus
`0.0596`), and exact-winner settlement-distance `0` rows (`0.3909` versus
`0.3444` current and `0.2784` market).

Interpretation: v0.3 fixed training throughput and proved that holdout
winner-brier sigma tuning alone is the wrong direction. It narrows the density
enough to improve the small holdout winner-bucket objective but over-concentrates
the replay distribution. The next internal model step should be a replay-aware
probability calibration/spread policy that keeps exact-winner mass useful
without worsening early and midday non-winner bands.

Verification:
`python -m pytest tests/calibration/test_blocked_validation.py tests/calibration/test_pooled_feature_model.py tests/calibration/test_pooled_candidate_replay.py tests/operations/test_schema_registry.py -q`
passes with `69 passed`.

## 2026-06-18 holdout market-band sigma update

The v0.3 replay showed that optimizing sigma only for the true winner bucket
over-concentrated the density and damaged early/midday replay rows. The active
density trainer now emits schema `pooled_continuous_density_hgb_v0.4` with
objective `canonical_f_density_gaussian_holdout_market_band_brier_sigma`.
Instead of selecting width by winner-bucket Brier alone, v0.4 builds synthetic
native market bands (`eq`, range, `lte`, `gte`) around each holdout row and
selects sigma by holdout market-band Brier. The replay path was also tightened:
density predictions are batched by cutoff hour, and replay caches each
snapshot's calibrated density CDF so band projection uses binary-search
integration instead of repeatedly normalizing and scanning the same grid.

Smoke evidence:
`python -m weather.calibration.pooled_feature_model --objective density --hours 12 --max-days-per-market 30 --holdout-year 2025 --artifact data\backtest\item35_density_market_band_smoke_v0_4.pkl --out data\backtest\item35_density_market_band_smoke_v0_4_report.md`
trained over 360 rows and wrote schema `pooled_continuous_density_hgb_v0.4`.
At 12:00 the market-band selector chose a wider sigma (`1.4224` F) than RMSE
sigma (`1.1380` F), improving holdout market-band Brier from `0.1134` to
`0.1120`.

Full training evidence:
`python -m weather.calibration.pooled_feature_model --objective density --holdout-year 2025 --artifact data\backtest\item35_density_full_candidate_v0_4.pkl --out data\backtest\item35_density_full_candidate_v0_4_report.md`
completed over 76,957 source rows. The full v0.4 artifact has hourly models
from 07:00 through 20:00, every hourly blocked-validation audit passed with
zero leaks, and every hour used
`holdout_market_band_brier_grid_search`. Relative to v0.3, v0.4 selects wider
pre-noon/midday sigmas (for example 07:00 `1.3980` F versus v0.3 `0.9786`,
12:00 `0.9723` F versus v0.3 `0.7480`) while retaining tight late-day sigmas
where holdout market-band Brier still prefers them.

Full replay evidence:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item35_density_full_candidate_v0_4.pkl --out data\backtest\item35_density_full_replay_v0_4_report.md --json-out data\backtest\item35_density_full_replay_v0_4.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --skip-microstructure-overlay --source-state-ablation-variant-out= --bridge-variant-out= --disable-long-job-guard`
completed when run with monitored background polling rather than the 10-minute
foreground timeout. Current-serving replay reconstruction was the long pole:
subset timing showed about `0.15s` per pinned snapshot, so the 6,989-snapshot
corpus needs roughly 18 minutes before candidate scoring. The optimized density
prediction/projection path is no longer the blocker: feature/freshness building
took about 19.5 seconds and batched density prediction took about 6.6 seconds.

The v0.4 replay scored all 76,879 market rows across 51 market-days with no
missing candidate rows, but the verdict stayed `BLOCK`, market-only verdict
`BLOCK`, and cutover decision `DO_NOT_CUT_OVER`. Aggregate candidate Brier was
`0.0531` versus current `0.0427` and market `0.0373`; daily-first candidate
Brier was `0.0522` versus current `0.0420`, a `+0.0102` regression above the
`0.0030` tolerance. Toronto remains blocked: candidate Brier `0.0520` versus
current `0.0369` and market `0.0334`. v0.4 improved the v0.3 over-concentration
failure (`0.0585` aggregate candidate Brier down to `0.0531`) but still does
not beat the v0.2 floor-context replay or the current model. Exact-winner
settlement-distance `0` remains the core slice failure: `0.3864` candidate
Brier versus `0.3444` current and `0.2784` market.

The next internal model step should move beyond scalar Gaussian sigma policy.
The replay evidence says the density mean/postprocess is still wrong in early,
midday, and Toronto rows; a candidate needs replay-aware probability
calibration or a direct density-shape/mixture policy, then another full pinned
replay, before the proof checkbox can close.

Verification:
`python -m pytest tests/calibration/test_pooled_feature_model.py tests/calibration/test_pooled_candidate_replay.py tests/operations/test_schema_registry.py -q`
passes as part of the broader focused suite:
`python -m pytest tests/calibration/test_blocked_validation.py tests/calibration/test_pooled_feature_model.py tests/calibration/test_pooled_candidate_replay.py tests/calibration/test_promotion_refresh.py tests/operations/test_schema_registry.py -q`
with `91 passed`.

## 2026-06-18 density-shape v0.5 full replay update

The scalar-Gaussian follow-up is now implemented as a v0.5 artifact contract,
and has full pinned-replay evidence. The active density trainer emits
`pooled_continuous_density_hgb_v0.5` with objective
`canonical_f_density_shape_holdout_market_band_brier`. Each hourly bundle can
carry a `density_shape` selected by holdout market-band Brier across Gaussian,
tail-mixture, forecast-anchor mixture, and climatology-anchor mixture
candidates. Replay prediction reads that shape from the artifact before the
existing continuous floor calibration projects probabilities into market bands.

Smoke training:
`python -m weather.calibration.pooled_feature_model --objective density --hours 12 --max-days-per-market 30 --holdout-year 2025 --artifact data\backtest\item35_density_shape_smoke_v0_5.pkl --out data\backtest\item35_density_shape_smoke_v0_5_report.md`
completed over 360 rows. The 12:00 selector chose `forecast_w30`, a 30%
forecast-high anchor mixture, with final sigma `1.4224` F. On the smoke
holdout, market-band Brier improved from the RMSE-sigma Gaussian baseline
`0.1134` to `0.1054`.

Smoke replay:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\item35_density_replay_smoke_corpus.json --artifact data\backtest\item35_density_shape_smoke_v0_5.pkl --out data\backtest\item35_density_shape_replay_smoke_v0_5_report.md --json-out data\backtest\item35_density_shape_replay_smoke_v0_5.json --replay-report data\backtest\item35_density_shape_replay_smoke_v0_5_current_report.md --disable-candidate-variant-export --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --skip-microstructure-overlay --disable-long-job-guard`
ran against the existing two-day Item 35 smoke corpus. It still returned
`BLOCK` / `DO_NOT_CUT_OVER`: 55 scored rows, candidate Brier `0.1143` versus
current `0.1063` and market `0.0768`, with daily-first regression
`+0.0080` versus current. Coverage was intentionally narrow because the smoke
artifact only has a 12:00 model.

Full training:
`python -m weather.calibration.pooled_feature_model --objective density --holdout-year 2025 --artifact data\backtest\item35_density_full_candidate_v0_5.pkl --out data\backtest\item35_density_full_candidate_v0_5_report.md`
completed over 76,957 rows. The artifact has 14 hourly models from 07:00
through 20:00, every hourly blocked-validation audit passed with zero leaks,
and every hour used `holdout_market_band_brier_shape_grid_search`. The selector
chose `forecast_w30` for 07:00-13:00, `forecast_w15` at 14:00, and Gaussian for
15:00-20:00.

Full replay:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item35_density_full_candidate_v0_5.pkl --out data\backtest\item35_density_full_replay_v0_5_report.md --json-out data\backtest\item35_density_full_replay_v0_5.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --disable-candidate-variant-export --skip-microstructure-overlay --disable-long-job-guard`
scored all 76,879 market rows across 51 market-days with no missing candidate
rows. Verdict stayed `BLOCK`, market-only verdict was `PARTIAL_PASS`, and
cutover remained `DO_NOT_CUT_OVER`. Aggregate candidate Brier improved to
`0.0469` from v0.4's `0.0531`, but still trails current `0.0427` and market
`0.0373`. Daily-first candidate Brier was `0.0461` versus current `0.0420`, a
`+0.0041` regression above the `0.0030` tolerance. Toronto improved from v0.4
candidate Brier `0.0520` to `0.0448`, but still trails current `0.0369` and
market `0.0334`. Exact-winner settlement-distance `0` improved from v0.4
`0.3864` to `0.3552`, but remains worse than current `0.3444` and market
`0.2784`.

Current blocker: v0.5 proves the density-shape path and materially improves the
full replay, but it still regresses current and market overall. Next work
should move from shape tuning to replay-aware probability calibration or direct
market-band training, with special attention to exact-winner rows, early/midday
regimes, degraded-source rows, and Toronto.

Verification:
`python -m pytest tests/calibration/test_pooled_feature_model.py tests/calibration/test_pooled_candidate_replay.py tests/operations/test_schema_registry.py -q`
passed with `69 passed`, and the broader focused suite
`python -m pytest tests/calibration/test_blocked_validation.py tests/calibration/test_pooled_feature_model.py tests/calibration/test_pooled_candidate_replay.py tests/calibration/test_promotion_refresh.py tests/operations/test_schema_registry.py -q`
passed with `94 passed`.

## 2026-06-18 density postprocess v0.6 update

The replay-aware calibration follow-up is now implemented as
`pooled_continuous_density_hgb_v0.6`, but the data rejected it. The v0.6 trainer
fits candidate density market-band postprocess policies on holdout projections:
adjacent-band shrinkage, exact-winner catch-up, and optional replay-style
partition normalization. It then selects a policy only if holdout market-band
Brier beats the raw density projection by the configured margin.

Smoke evidence:
`python -m weather.calibration.pooled_feature_model --objective density --hours 12 --max-days-per-market 30 --holdout-year 2025 --artifact data\backtest\item35_density_postprocess_smoke_v0_6.pkl --out data\backtest\item35_density_postprocess_smoke_v0_6_report.md`
trained over 360 rows. A naive normalized postprocess initially worsened smoke
replay, so the selector was tightened to reject partition normalization and
make exact-winner catch-up boost-only. After that guard, the smoke artifact
selected `disabled`: baseline holdout band Brier `0.1012`, selected `0.1012`.
Smoke replay matched v0.5 exactly and still blocked: candidate `0.1143` versus
current `0.1063` and market `0.0768`.

Full training evidence:
`python -m weather.calibration.pooled_feature_model --objective density --holdout-year 2025 --artifact data\backtest\item35_density_full_candidate_v0_6.pkl --out data\backtest\item35_density_full_candidate_v0_6_report.md`
completed over 76,957 rows. The postprocess selector saw 237,208 calibration
rows, 285 adjacent contexts, and 792 exact-winner contexts, but still selected
`disabled`: baseline holdout band Brier `0.0421`, selected `0.0421`. Exact
catch-up strength was `0.0`; adjacent-only and normalized policies were worse.

Full replay evidence:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item35_density_full_candidate_v0_6.pkl --out data\backtest\item35_density_full_replay_v0_6_report.md --json-out data\backtest\item35_density_full_replay_v0_6.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --disable-candidate-variant-export --skip-microstructure-overlay --disable-long-job-guard`
scored all 76,879 rows with no missing candidate rows. Because postprocess was
disabled, aggregate metrics match v0.5: candidate `0.0469` versus current
`0.0427` and market `0.0373`; daily-first delta `+0.0041`; Toronto `0.0448`
versus current `0.0369` and market `0.0334`.

The useful new evidence is diagnostic. Density replay now attaches
forecast-profile slice context. The worst forecast-relative failures are
near-forecast bands (`0.1665` candidate versus `0.1571` current and `0.1393`
market, `+0.0094` vs current), low-disagreement rows (`+0.0078` vs current),
and moderate-disagreement rows (`+0.0051` vs current). That points away from a
post-hoc density calibration layer and toward direct market-band training or a
forecast-relative probability model that learns band outcomes instead of trying
to repair a projected continuous density.

Verification:
`python -m pytest tests/calibration/test_blocked_validation.py tests/calibration/test_pooled_feature_model.py tests/calibration/test_pooled_candidate_replay.py tests/calibration/test_promotion_refresh.py tests/operations/test_schema_registry.py -q`
passed with `96 passed`.

## 2026-06-18 forecast-relative postprocess v0.7 update

The direct follow-up to the v0.6 diagnostic is implemented as
`pooled_continuous_density_hgb_v0.7`. It adds a density-band postprocess
candidate keyed on serve-time forecast-relative contexts: band-vs-forecast
pressure, forecast disagreement, source count, hour, market, band kind/width,
and floor gap. Replay applies the layer only when the artifact selector enables
it, and reports now expose whether the forecast-relative layer was actually
selected separately from the fitted context count.

Smoke training:
`python -m weather.calibration.pooled_feature_model --objective density --hours 12 --max-days-per-market 30 --holdout-year 2025 --artifact data\backtest\item35_density_forecast_relative_smoke_v0_7.pkl --out data\backtest\item35_density_forecast_relative_smoke_v0_7_report.md`
trained over 360 rows and fit 122 forecast-relative contexts. With the initial
loose selector, synthetic holdout band Brier improved from `0.1012` to
`0.0992`, selecting `forecast_relative`.

Pinned smoke replay rejected that loose selection:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\item35_density_replay_smoke_corpus.json --artifact data\backtest\item35_density_forecast_relative_smoke_v0_7.pkl --out data\backtest\item35_density_forecast_relative_replay_smoke_v0_7_report.md --json-out data\backtest\item35_density_forecast_relative_replay_smoke_v0_7.json --replay-report data\backtest\item35_density_forecast_relative_replay_smoke_v0_7_current_report.md --disable-candidate-variant-export --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --skip-microstructure-overlay --disable-long-job-guard`
worsened the smoke replay to candidate Brier `0.1156` versus current `0.1063`
and market `0.0768`.

The selector now requires at least `0.003` holdout market-band Brier
improvement before enabling any density postprocess policy. Regenerating the
same v0.7 smoke artifact records the forecast-relative contexts but selects
`disabled`: baseline `0.1012`, selected `0.1012`. The guarded smoke replay
matches v0.5/v0.6 again: candidate `0.1143` versus current `0.1063` and market
`0.0768`, so the item remains blocked.

Interpretation: forecast-relative factors are useful diagnostics, but synthetic
holdout rows are not strong enough evidence to enable them. The next density
candidate should train market-band probabilities directly on replay-shaped
rows, or add a replay-selected calibration set, rather than trying to repair
continuous-density projections with post-hoc factors.

Verification:
`python -m pytest tests/calibration/test_pooled_feature_model.py tests/calibration/test_pooled_candidate_replay.py tests/operations/test_schema_registry.py -q`
passed with `73 passed`.

## 2026-06-18 all-market direct-band baseline smoke

The v0.6/v0.7 density evidence pointed away from post-hoc density repair and
toward direct market-band training. The trainer now supports an explicit
all-market native-unit band baseline without mixing Celsius and Fahrenheit
synthetic supports. `synthetic_band_rows_for_record` selects support by the
row's native unit, `train_pooled_band_models(..., family_unit="all")` records
`family_unit: all`, and the new artifact schema
`pooled_all_market_band_hgb_v0.1` is registered in `weather.schema_registry`.
The CLI allows `--objective band --family-unit all` only for this Item 35
baseline and rejects F-family shadow-lane combinations.

Smoke training:
`python -m weather.calibration.pooled_feature_model --objective band --family-unit all --hours 12 --max-days-per-market 30 --holdout-year 2025 --artifact data\backtest\item35_direct_band_all_market_smoke.pkl --out data\backtest\item35_direct_band_all_market_smoke_report.md`
wrote an all-market direct-band artifact over 360 source rows. It has one
12:00 model, prediction mode `band_binary`, schema
`pooled_all_market_band_hgb_v0.1`, feature schema
`toronto_feature_store_v1.6`, support units `C` and `F`, and both Toronto and
US-market feature columns. The 12:00 blocked-validation audit passed with zero
leaks.

Smoke replay:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\item35_density_replay_smoke_corpus.json --artifact data\backtest\item35_direct_band_all_market_smoke.pkl --out data\backtest\item35_direct_band_all_market_smoke_replay_report.md --json-out data\backtest\item35_direct_band_all_market_smoke_replay.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --disable-candidate-variant-export --skip-microstructure-overlay --disable-long-job-guard`
scored the existing Toronto/NYC two-day smoke corpus. Coverage is intentionally
limited because the smoke artifact only has a 12:00 model: 55 scored rows out
of 1,771 all-market rows. The replay stayed `BLOCK / DO_NOT_CUT_OVER` with
candidate Brier `0.106422`, current `0.106310`, and market `0.076773`.

This does not complete Item 35, but it creates the direct training lane that
the density diagnostics called for. The next unblock step is a full-hour
all-market direct-band artifact and pinned replay, then compare it against the
best density full replay (`0.0469` aggregate candidate Brier, daily-first
`+0.0041` versus current) and against Toronto's current-serving baseline.

Verification:
`python -m pytest tests\calibration\test_pooled_feature_model.py tests\operations\test_schema_registry.py -q`
passed with `39 passed`, and
`python -m weather.schema_registry audit --paths src\weather\calibration\pooled_feature_model.py src\weather\schema_registry.py --strict`
reported `unregistered_versions=0`.

## 2026-06-18 all-market direct-band full replay

The full-hour direct market-band baseline is now trained and replayed on the
pinned promotion corpus. This is the strongest full-corpus Item 35 evidence so
far: it beats current serving overall and materially improves on the best
continuous-density replay, but it still fails the acceptance target because it
trails market and does not lift Toronto safely.

Full training:
`python -m weather.calibration.pooled_feature_model --objective band --family-unit all --max-days-per-market 0 --holdout-year 2025 --artifact data\backtest\item35_direct_band_all_market_full_candidate.pkl --out data\backtest\item35_direct_band_all_market_full_training_report.md`
completed over 76,957 source rows. The artifact uses schema
`pooled_all_market_band_hgb_v0.1`, feature schema
`toronto_feature_store_v1.6`, objective
`binary_native_market_band_brier_all_market_source_reliability`, family unit
`all`, prediction mode `band_binary`, native support for both `C` and `F`, and
hourly models from 07:00 through 20:00. Every hourly blocked-validation audit
passed with zero leaks. The weak input-family preflight stayed `WARN` because
several rich weather families remain low-coverage or diagnostic-only.

Full replay:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item35_direct_band_all_market_full_candidate.pkl --out data\backtest\item35_direct_band_all_market_full_replay_report.md --json-out data\backtest\item35_direct_band_all_market_full_replay.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --disable-candidate-variant-export --skip-microstructure-overlay --disable-long-job-guard`
scored all 76,879 all-market rows across 51 market-days with zero missing
candidate rows and zero excluded non-family rows. The replay verdict stayed
`BLOCK`, market-only verdict was `PARTIAL_PASS`, and cutover remained
`DO_NOT_CUT_OVER`.

Aggregate replay improved versus current but not market: candidate Brier
`0.041865`, current `0.042739`, market `0.037323`, delta versus current
`-0.000874`, and delta versus market `+0.004542`. Daily-first equal-day
average was similar: candidate `0.041124`, current `0.041986`, market
`0.036667`, delta versus current `-0.000863`, and delta versus market
`+0.004457`. The conservative bridge was not promotion evidence either:
bridge Brier `0.0417` versus market `0.0373`.

Per-market action is mixed. `atlanta`, `denver`, `houston`, and `los-angeles`
are candidate cutover-ready in this replay; `dallas` and `miami` should
continue shadow; `austin`, `chicago`, `nyc`, `san-francisco`, `seattle`, and
`toronto` remain blocked. Toronto is the critical acceptance failure: candidate
Brier `0.0401` versus current `0.0369` and market `0.0334`, so it regresses
current by `+0.0032`, just above the `0.0030` tolerance, and trails market by
`+0.0067`.

Interpretation: Item 35 should not continue as a density-only effort. The
direct native-band lane is substantially better than the v0.6/v0.7 density
path and finally beats current in aggregate, but the acceptance condition
still requires per-market/current safety and data-poor Toronto lift. The next
unblock is a hybrid or guardrailed direct-band repair focused on Toronto,
Austin, Chicago, NYC, San Francisco, Seattle, and the early/midday market gaps,
then another full pinned replay before promotion.

## 2026-06-19 replay-blend diagnostic

The direct-band full replay was exported to row-level shadow evidence:
`data\backtest\item35_direct_band_all_market_full_variant_rows.csv`. A
diagnostic alpha sweep over those pinned replay rows selected a market-specific
current-blend schedule and wrote
`data\backtest\item35_direct_band_all_market_replay_blend_sweep_report.md` plus
`data\backtest\item35_direct_band_all_market_replay_blend_sweep.json`.

This is deliberately not promotion evidence because the alphas were selected on
the same pinned replay rows being scored. It is still useful model-repair
evidence: it shows the all-market direct-band lane can cross the aggregate
daily-first gate and can lift Toronto if the current-blend policy is selected
well.

Diagnostic artifact:
`data\backtest\item35_direct_band_all_market_replay_blend_candidate.pkl` keeps
the same trained direct-band models but changes the current-blend schedule to:
Atlanta `0.70`, Austin `0.80`, Chicago `0.85`, Dallas `0.00`, Denver `0.20`,
Houston `0.95`, Los Angeles `0.45`, Miami `0.00`, NYC `1.00`, San Francisco
`0.00`, Seattle `0.25`, and Toronto `0.30`.

Pinned replay:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item35_direct_band_all_market_replay_blend_candidate.pkl --out data\backtest\item35_direct_band_all_market_replay_blend_report.md --json-out data\backtest\item35_direct_band_all_market_replay_blend.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --disable-candidate-variant-export --skip-microstructure-overlay --disable-long-job-guard`.

Result: validation verdict `PARTIAL_PASS`, market-only verdict `PARTIAL_PASS`,
and cutover decision `PER_MARKET_ONLY`. The blocked-validation gate itself
passes: aggregate candidate Brier `0.040297` versus current `0.042739` and
market `0.037323`, while daily-first candidate Brier `0.039593` is within
market tolerance at `+0.002926` versus market and beats current by `-0.002394`.
The source-state ablation gate also moves to `READY`.

Most importantly for the Item 35 acceptance target, Toronto moves from blocked
to PASS in this diagnostic replay: candidate Brier `0.036239` versus current
`0.036925` and market `0.033427`, delta versus current `-0.000686`, and delta
versus market `+0.002812`. Austin also moves to PASS. Candidate cutover-ready
markets are now Atlanta, Austin, Denver, Houston, Los Angeles, and Toronto;
Dallas and Miami remain shadow; Chicago, NYC, San Francisco, and Seattle remain
blocked by daily-first market tolerance.

Next unblock: replace the replay-selected alpha schedule with a predeclared or
out-of-sample selection policy. The strongest direction is a guarded
direct-band hybrid that learns or validates market alphas without looking at
the scored replay rows, then specifically repairs Chicago, NYC, San Francisco,
and Seattle market gaps.

Promotion-refresh boundary check:
`data\backtest\item35_replay_blend_promotion_refresh_report.md` wraps the same
diagnostic artifact in the all-market promotion-refresh machinery. It reports
readiness `OPEN`, candidate verdict `PARTIAL_PASS`, market-only verdict
`PARTIAL_PASS`, and cutover decision `PER_MARKET_ONLY`: Atlanta, Austin,
Denver, Houston, Los Angeles, and Toronto would promote; Dallas and Miami
remain shadow; Chicago, NYC, San Francisco, and Seattle remain blocked. This
does not change acceptance because the alpha schedule is replay-selected and
the promotion refresh still has model-market, live-forward SLO, backup-capacity,
and hourly-performance blockers.

## 2026-06-19 time-split current-blend validation

The replay-selected alpha sweep was converted into a repeatable anti-overfit
check in `weather.reporting.current_blend_validation`. The report reads
`data\backtest\item35_direct_band_all_market_full_variant_rows.csv`, reconstructs
the raw direct-band probability where the baseline artifact did not fully fall
back to current, selects market alphas only on earlier target dates, and scores
them on later target dates. This is still development evidence, not promotion
evidence, because both sides come from the pinned replay corpus.

Generated report:
`data\backtest\item35_current_blend_time_split_validation_report.md`.
It blocks. The earlier-date-selected alpha schedule is Atlanta `0.70`, Austin
`0.05`, Chicago `1.00`, Dallas `0.00`, Denver `0.00`, Houston `0.95`, Los
Angeles `0.05`, Miami `0.00`, NYC `1.00`, San Francisco `0.00`, Seattle
`0.10`, and Toronto `0.00`. On later-date holdout rows, candidate Brier is
`0.045052` versus current `0.046663` and market `0.039270`: the policy beats
current by `-0.001611` but trails market by `+0.005782`. The daily-first
holdout gap is also `+0.005788` versus market. Austin, Chicago, Los Angeles,
NYC, San Francisco, Seattle, and Toronto block the holdout gate.

The selected schedule was then written to
`data\backtest\item35_direct_band_all_market_time_split_blend_candidate.pkl`
and replayed through the normal pinned gate:
`data\backtest\item35_direct_band_all_market_time_split_blend_report.md`.
That full replay also blocks: aggregate candidate Brier `0.040707` versus
current `0.042739` and market `0.037323`, daily-first candidate Brier
`0.039998` versus market `0.036667` (`+0.003331`). Atlanta and Houston pass;
Dallas, Denver, Los Angeles, and Miami remain shadow; Austin, Chicago, NYC,
San Francisco, Seattle, and Toronto block. Toronto is especially important:
the time-split policy falls back to current, so it no longer regresses current
but also no longer proves the required Toronto lift.

Conclusion: alpha selection alone is not a stable Item 35 unblock. The next
candidate should repair the direct-band model itself for Austin, Chicago, NYC,
San Francisco, Seattle, and Toronto, then rerun the time-split validation and
full pinned replay before any promotion refresh is treated as evidence.

## 2026-06-19 holdout market-bias repair

The direct-band training path now fits a conservative
`market_bias_calibration` from held-out historical market-band rows rather than
from replay rows. The calibration uses only inference-available context
fallbacks (`market`, cutoff-hour bucket, and band kind), is smoothed, and is
enabled only if the historical holdout improves without material market-level
regression. Tests cover the fit/apply path and the replay report now exposes
the calibration summary.

Full all-market training wrote
`data\backtest\item35_direct_band_all_market_market_bias_candidate.pkl` and
`data\backtest\item35_direct_band_all_market_market_bias_training_report.md`.
The holdout gate enabled the repair with 240 contexts: historical holdout
Brier improved from `0.033564` to `0.032008` (`-0.001556`) with no market
regression in that gate.

Pinned replay did not transfer enough:
`data\backtest\item35_direct_band_all_market_market_bias_replay_report.md`
reports `BLOCK / PARTIAL_PASS / DO_NOT_CUT_OVER`. Aggregate candidate Brier is
`0.041721` versus current `0.042739` and market `0.037323`; daily-first
candidate Brier is `0.040986` versus current `0.041986` and market `0.036667`,
so the daily-first market gap is still `+0.004319`. The repair does move
Austin and Los Angeles to PASS alongside Atlanta and Houston, but Dallas,
Denver, and Miami remain shadow, while Chicago, NYC, San Francisco, Seattle,
and Toronto remain blocked.

The Toronto acceptance target still fails: candidate Brier `0.038703` versus
current `0.036925` and market `0.033427`, a current regression of `+0.001778`
and market gap `+0.005277`. The source-state ablation gate also falls to
`SHADOW` because degraded-source rows regress current serving. Conclusion:
holdout market-bias calibration is useful model-repair evidence, but not the
Item 35 unblock. The next candidate needs source-state/Toronto guardrails or a
deeper direct-band model change that preserves the Austin/Los Angeles lift
without degrading Toronto and degraded-source rows.

## 2026-06-19 source-freshness guardrail replay

The next guardrail variant keeps the same holdout-trained market-bias artifact
but blends every non-`all_fresh` source-state row fully back to current serving:
`data\backtest\item35_direct_band_all_market_market_bias_source_guard_candidate.pkl`.
This is not a promotion claim; it tests whether source-state safety can be
restored without discarding the Austin/Los Angeles lift.

Pinned replay:
`data\backtest\item35_direct_band_all_market_market_bias_source_guard_replay_report.md`
still reports `BLOCK / PARTIAL_PASS / DO_NOT_CUT_OVER`, but the source-state
ablation gate returns to `READY`. Degraded-source rows are now candidate
`0.058294` versus current `0.058294` and market `0.055415`, so current safety
is restored. Aggregate candidate Brier is `0.041675` versus current
`0.042739` and market `0.037323`; daily-first candidate Brier is `0.040942`
versus market `0.036667` (`+0.004275`).

Market movement is narrower and cleaner: Atlanta, Austin, Houston, and Los
Angeles pass; Dallas, Denver, and Miami remain shadow; Chicago, NYC, San
Francisco, Seattle, and Toronto remain blocked. Toronto improves relative to
the unguarded market-bias replay but still fails the acceptance target:
candidate `0.038274` versus current `0.036925` and market `0.033427`.

Conclusion: the source-state blocker is now separable from the core model
quality blocker. The next Item 35 candidate should keep the source-freshness
guardrail, preserve Austin/Los Angeles, and target Toronto plus
Chicago/NYC/San Francisco/Seattle directly.

## 2026-06-19 source-guard Toronto-alpha probe

The next diagnostic probe keeps the source-freshness guardrail and adds a
Toronto-specific current-blend alpha of `0.30`:
`data\backtest\item35_direct_band_all_market_source_guard_toronto_alpha_candidate.pkl`.
This alpha is borrowed from the prior replay-selected sweep, so it is not
promotion evidence. The purpose is narrower: prove whether the source-guarded
direct-band candidate still has enough Toronto/current error offset to rescue
Toronto without reopening the degraded-source blocker.

Pinned replay:
`data\backtest\item35_direct_band_all_market_source_guard_toronto_alpha_replay_report.md`
reports `BLOCK / PARTIAL_PASS / DO_NOT_CUT_OVER`. It is the cleanest Item 35
boundary so far for Toronto and source-state safety: source-state ablation
stays `READY`, and Toronto moves to PASS with candidate Brier `0.035937`
versus current `0.036925` and market `0.033427`, a current lift of
`-0.000988` and market gap `+0.002511`.

Aggregate replay still blocks: candidate Brier `0.041388` versus current
`0.042739` and market `0.037323`; daily-first candidate Brier `0.040664`
versus market `0.036667`, leaving a `+0.003997` daily-first market gap.
Cutover-ready markets are now Atlanta, Austin, Houston, Los Angeles, and
Toronto. Dallas, Denver, and Miami remain shadow. The remaining hard model
blockers are Chicago, NYC, San Francisco, and Seattle.

Conclusion: Toronto can be rescued while preserving source-state safety, but
the current alpha is replay-diagnostic. The next non-diagnostic unblock needs a
predeclared or holdout-selected Toronto blend policy plus direct repair for
Chicago, NYC, San Francisco, and Seattle.

## 2026-06-19 source-guard time-split rejection

The source-guard row-level replay export was materialized for validation as
`data\backtest\item35_market_bias_source_guard_variant_rows.csv`; it was later
removed by `data\backtest\backtest_artifact_cleanup_manifest_4.json` as a
rebuildable row artifact after retaining paired evidence. The retained replay
metadata is
`data\backtest\item35_direct_band_all_market_market_bias_source_guard_variant_export.json`
and its Markdown report. The follow-up time-split validation
`data\backtest\item35_source_guard_time_split_validation_report.md` selected
current-blend alphas on earlier market-days and evaluated them on later
market-days.

That anti-overfit check rejects the Toronto-alpha diagnostic as a promotion
path. Readiness is `BLOCK`; selected eval-row candidate Brier is `0.045334`
versus current `0.046663` and market `0.039270`, leaving a market gap of
`+0.006064`. Daily-first is similar: candidate `0.045320` versus market
`0.039248`, gap `+0.006072`.

The selected source-guard alphas are Atlanta `0.55`, Austin `0.00`, Chicago
`1.00`, Dallas `0.00`, Denver `0.00`, Houston `0.90`, Los Angeles `0.00`,
Miami `0.00`, NYC `1.00`, San Francisco `0.00`, Seattle `0.10`, and Toronto
`0.00`. Toronto is the key failure: the earlier-date split does not select the
diagnostic `0.30` alpha, falls back fully to current, and still blocks versus
market on later rows (`0.051904` candidate/current versus `0.043225` market,
gap `+0.008679`).

Conclusion: keep the source-freshness guardrail, but do not promote or
predeclare the replay-selected Toronto alpha. The next Item 35 unblock needs a
new Toronto policy that is selected by earlier-date evidence, plus direct
market-gap repairs for Austin, Chicago, Houston, Los Angeles, NYC, San
Francisco, Seattle, and Toronto.

## 2026-06-19 source-guard blocker-market diagnostics

The remaining source-guard blockers were replayed one market at a time against
`data\backtest\item35_direct_band_all_market_market_bias_source_guard_candidate.pkl`
using single-market pinned corpora. The market-scoped replays generated compact
row exports and all stayed `BLOCK / DO_NOT_CUT_OVER`:

| Market | Days | Rows | Candidate | Current | Market | Delta current | Delta market | Daily market gap |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Chicago | 4 | 6,182 | 0.039629 | 0.045551 | 0.036314 | -0.005922 | +0.003315 | +0.003334 |
| NYC | 4 | 6,138 | 0.055162 | 0.058342 | 0.036058 | -0.003180 | +0.019104 | +0.019111 |
| San Francisco | 4 | 6,094 | 0.046408 | 0.046408 | 0.041240 | +0.000000 | +0.005168 | +0.005107 |
| Seattle | 4 | 6,116 | 0.038628 | 0.038914 | 0.024133 | -0.000286 | +0.014495 | +0.014542 |
| Toronto | 7 | 9,449 | 0.038274 | 0.036925 | 0.033427 | +0.001349 | +0.004847 | +0.004286 |

`data\backtest\item35_source_guard_blocker_repair_diagnostics_report.md`
then classified 33,979 blocker rows:

| Market | Classification | Current fallback share | Daily gap vs market | Winner gap vs market |
| :--- | :--- | ---: | ---: | ---: |
| Chicago | market_gap_without_clear_winner_signal | 0.3293 | +0.0033 | -0.0382 |
| NYC | winner_underpricing_vs_market | 0.1763 | +0.0191 | -0.1748 |
| San Francisco | current_fallback_trails_market | 1.0000 | +0.0051 | -0.0475 |
| Seattle | winner_underpricing_vs_market | 0.3373 | +0.0145 | -0.1151 |
| Toronto | market_gap_without_clear_winner_signal | 0.3734 | +0.0043 | -0.0477 |

This narrows the next Item 35 work. NYC and Seattle need direct
winner-probability repair, especially exact/settlement-distance-0 early rows.
San Francisco needs non-current signal because source-guard replay falls back
fully to current and still trails market. Chicago and Toronto need broader
market-gap repair, with Toronto also regressing current in this candidate. The
source-freshness guard remains useful as a safety constraint, but it is not the
quality unlock by itself.

## 2026-06-19 all-market exact-winner source-guard diagnostic

The direct-band training CLI now supports an explicit Item 35 source-freshness
guardrail (`--source-freshness-guardrail`) and allows all-market
exact-winner catch-up without inheriting the older Item 70/F-family shadow
blend policy. The new all-market exact-winner path keeps the Item 35
current-blend market alphas, applies the all-fresh-only source-state guardrail,
and still fits holdout market-bias calibration.

A full no-cap training attempt for
`data\backtest\item35_all_market_exact_winner_source_guard_candidate.pkl` was
stopped after roughly 14 minutes without an artifact. A full pinned replay of
the capped artifact was also stopped after roughly 17 minutes without output.
That makes this a development diagnostic, not promotion evidence. The bounded
candidate
`data\backtest\item35_all_market_exact_winner_source_guard_recent40_candidate.pkl`
trained successfully over 6,720 recent source rows with 713 exact-winner
contexts, selected strength `1.00`, and market-bias holdout Brier
`0.0340 -> 0.0332`.

Market-scoped replays against the prior blocker corpora improved the targeted
markets but still blocked:

| Market | Source-guard candidate | Exact+source-guard candidate | Current | Market | Delta vs source guard | Exact gap vs market | Daily exact gap |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| NYC | 0.055162 | 0.052357 | 0.058342 | 0.036058 | -0.002805 | +0.016299 | +0.016298 |
| Seattle | 0.038628 | 0.037886 | 0.038914 | 0.024133 | -0.000742 | +0.013753 | +0.013807 |
| Toronto | 0.038274 | 0.037871 | 0.036925 | 0.033427 | -0.000403 | +0.004445 | +0.003904 |

`data\backtest\item35_exact_source_guard_recent40_repair_diagnostics_report.md`
shows the same blocker classes after the improvement: NYC and Seattle remain
`winner_underpricing_vs_market`, and Toronto remains
`market_gap_without_clear_winner_signal`. Winner gaps shrink but remain large:
NYC `-0.1592`, Seattle `-0.1036`, and Toronto `-0.0453` versus market.

Conclusion: all-market exact-winner catch-up is directionally useful and should
be kept as a candidate family, but the capped artifact is not enough. The next
real attempt needs a longer full-window training/replay run plus a stronger
winner repair for NYC/Seattle and a separate Toronto current-regression guard.
San Francisco is unchanged by this path because the source-guard policy still
falls fully back to current there.

## 2026-06-19 split-safe winner-boost policy search

`weather.reporting.winner_boost_validation` now evaluates simple
inference-available EQ-row boost policies on chronological market splits. It
selects a policy/factor on earlier target dates, evaluates later target dates,
and re-normalizes candidate probabilities within each snapshot. This is still
development evidence because it uses replay row exports, but it avoids direct
later-date tuning.

Running it on the recent-40 exact-winner source-guard NYC, Seattle, and Toronto
row exports:
`data\backtest\item35_exact_source_guard_recent40_winner_boost_validation_report.md`
tested `none`, `all_eq`, `early_eq`, and `off_forecast_eq` across factors
`1.0` through `8.0`. The result remains `BLOCK`.

| Market | Selected policy | Factor | Baseline eval | Candidate eval | Market | Delta market | Status |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| NYC | all_eq | 1.00 | 0.051495 | 0.051495 | 0.023601 | +0.027894 | BLOCK |
| Seattle | all_eq | 8.00 | 0.042253 | 0.041105 | 0.026360 | +0.014745 | BLOCK |
| Toronto | all_eq | 1.00 | 0.047088 | 0.047088 | 0.043225 | +0.003864 | BLOCK |

Daily-first holdout moves only from `+0.012904` to `+0.012619` versus market.
This rules out a shallow global/slice EQ multiplier as the next unblock. Seattle
can absorb stronger winner mass but remains far outside market tolerance. NYC
and Toronto do not even select a boost on earlier dates, so their fix needs a
richer market/synoptic/source signal or a model architecture change, not a
generic exact-row multiplier.

## 2026-06-19 contextual winner calibration rejection

`weather.reporting.contextual_winner_validation` now tests a richer version of
the exact-winner repair idea without using later-date leakage. It fits
context-specific exact-row factors on earlier market-days, normalizes
probabilities within each snapshot, and evaluates later market-days. Context
keys are restricted to inference-available row columns: market id, cutoff
regime, forecast bucket pressure, forecast disagreement bucket, forecast source
count bucket, and source-freshness state.

Running it on the recent-40 exact-winner source-guard NYC, Seattle, and Toronto
row exports:
`data\backtest\item35_exact_source_guard_recent40_contextual_winner_validation_report.md`
still reports `BLOCK`.

| Market | Selected template | Factors | Baseline eval | Candidate eval | Market | Delta market | Status |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| NYC | `cutoff_regime+forecast_bucket_pressure` | 8 | 0.0515 | 0.0505 | 0.0236 | +0.0269 | BLOCK |
| Seattle | `cutoff_regime+forecast_bucket_pressure+forecast_disagreement_bucket` | 22 | 0.0423 | 0.0481 | 0.0264 | +0.0218 | BLOCK |
| Toronto | `market` | 1 | 0.0471 | 0.0478 | 0.0432 | +0.0046 | BLOCK |

Daily-first holdout worsens from the baseline `+0.0129` market gap to
`+0.0145`. This rules out another tempting postprocess path: existing
forecast-pressure/disagreement/source-state row contexts can overfit early
dates and do not provide a stable winner repair. The next unblock remains a
new model/source signal or architecture change for NYC/Seattle winner
underpricing, plus a Toronto current-regression guard, rather than a more
granular exact-row multiplier.

## 2026-06-19 market-anchor boundary check

`weather.reporting.market_anchor_validation` now tests market-informed anchor
repairs on the same chronological split. It separates sparse CLOB midpoint
anchoring from full `market_yes` anchoring. This is development evidence, not
promotion evidence: CLOB midpoint and `market_yes` are live market inputs, and
`market_yes` anchoring measures serving-safety rather than model edge.

For the recent-40 exact-winner source-guard NYC, Seattle, and Toronto row
exports, CLOB-only selection still blocks:
`data\backtest\item35_exact_source_guard_recent40_clob_anchor_validation_report.md`.
Earlier-date selection chooses `candidate:0.00` for every market, so the
later-date score is unchanged at a `+0.0129` daily-first market gap. The
expanded CLOB stability table explains why: train-side CLOB midpoint coverage
is `0.0000`, while eval-side coverage is `0.1761`. On eval rows with CLOB
midpoint, CLOB Brier is `0.0492` versus candidate `0.0909`, so the signal is
useful when present but absent from the selection split. The eval-only oracle
shows latent CLOB value but not enough stability: daily-first gap would shrink
to `+0.0056`, and Toronto's oracle CLOB anchor would beat market by `-0.0004`,
but NYC and Seattle would still block at `+0.0095` and `+0.0134`.

Allowing full `market_yes` anchoring improves the boundary but remains
diagnostic:
`data\backtest\item35_exact_source_guard_recent40_market_anchor_validation_report.md`.
The split-selected policy moves daily-first holdout to candidate `0.0352`
versus market `0.0341`, gap `+0.0011`, with Seattle and Toronto passing. NYC
still blocks: selected `market_yes:0.75` gives candidate `0.0281` versus market
`0.0236`, gap `+0.0045`. Because this path uses market price itself, it cannot
prove model edge; it only says market-informed serving/risk anchoring could
stabilize Seattle/Toronto while NYC still needs direct model repair.

Follow-up root-cause audit:
`data\backtest\item35_exact_source_guard_recent40_clob_coverage_audit_report.md`
inspected the underlying snapshot folders rather than only the row exports. It
confirms the CLOB stability blocker is a collection/logging continuity problem:
9 of 15 folders are classified `missing_raw_clob_tape_and_token_map`, including
NYC/Seattle June 7-8 and Toronto June 3-8. June 12/13 folders do have raw books
and token maps, but coverage is still partial: NYC June 12 is
`one_sided_books_no_midpoint`, while June 13 has midpoint coverage around
`0.4675`; Seattle June 12 has only `0.0344` midpoint coverage and June 13
`0.4277`; Toronto June 12 has `0.0117` and June 13 `0.4637`.

This means CLOB cannot be used to unblock Item 35 until collection continuity
creates train-side midpoint evidence. Existing generated empty
`clob_features_long.csv` files are not enough; the raw `order_books` and
`clob_tokens` tapes must be present before the split-safe selector can learn a
market-informed policy.

## 2026-06-19 bounded exact/source-guard training refresh

The all-market exact-winner/source-guard lane was pushed beyond the earlier
recent-40 diagnostic without treating full-history training as a hidden
requirement. A no-cap all-market run of
`weather.calibration.pooled_feature_model --objective band --family-unit all
--exact-winner-catchup --source-freshness-guardrail` was tried twice with a
30-minute execution window and produced no artifact. The full unbounded history
is therefore a training-throughput problem for this candidate shape, not a
usable proof path.

`pooled_feature_model` now precomputes exact-winner strength-selection
partitions and row factors instead of recomputing contexts and normalization
for every strength candidate. Regression coverage:
`python -m pytest tests\calibration\test_pooled_feature_model.py -q` passed
with `39 passed`.

Two larger bounded artifacts were then trained and replayed against the pinned
promotion corpus without row-level variant exports:

- `data/backtest/item35_all_market_exact_winner_source_guard_recent120_candidate.pkl`
  trained on 20,160 source rows. Replay stayed `BLOCK / DO_NOT_CUT_OVER`:
  aggregate candidate Brier `0.041011` versus current `0.042739` and market
  `0.037323`; daily-first candidate `0.040278` versus market `0.036667`, gap
  `+0.003611`.
- `data/backtest/item35_all_market_exact_winner_source_guard_recent365_candidate.pkl`
  trained on 61,311 source rows. Replay also stayed `BLOCK / DO_NOT_CUT_OVER`
  and was worse than recent-120: aggregate candidate `0.041347`, market gap
  `+0.004024`; daily-first candidate `0.040613`, market gap `+0.003946`.

The recent-365 run confirms that simply widening the training window is not the
Item 35 unblock. It still underprices exact winners: settlement-distance-0
winner probability is `0.5362` versus current `0.5230` and market `0.5806`.
The largest market gaps remain NYC `+0.0166`, Seattle `+0.0137`, San Francisco
`+0.0052`, Austin `+0.0051`, and Toronto `+0.0046`. Toronto also regresses
current by `+0.0011`.

Conclusion: keep the optimized calibration path and the recent-120 artifact as
the better bounded exact/source-guard evidence, but do not spend the next pass
on wider all-market history. The next useful Item 35 work remains direct
NYC/Seattle winner repair, a Toronto current-regression guard, non-current San
Francisco skill, and CLOB train-side collection continuity.

## 2026-06-19 CLOB raw-artifact gate

The CLOB continuity blocker now has a durable data-layer guard instead of only
an ad hoc folder audit. `data_layer_audit` records `clob_tokens.csv`,
`clob_tokens.jsonl`, `order_books_summary.csv`, `order_books.jsonl`, and
`order_books_long.csv` presence for every snapshot folder, reports composite
token/raw-book day counts, and the live-pilot market-making preflight rejects a
target date that has derived `clob_features_long.csv`/book rows but lacks raw
token and raw book artifacts.

Fresh evidence:
`data\backtest\data_layer_audit_after_clob_raw_artifact_gate_report.md`
reports `96/177` folders with token artifacts and `84/177` with raw-book
artifacts; among `165` training-ready folders, only `84` have token artifacts
and `72` have raw-book artifacts. The audit gate status remains `WARN` because
the raw CLOB counts are now surfaced for continuity and live-pilot gating, not
retroactively required for every historical folder.

Verification:
`python -m pytest tests\market\test_market_making_run.py tests\reporting\test_data_layer_audit.py -q`
passed with `42 passed`, including the regression case where derived CLOB
features exist but the raw token/book artifacts are absent. This still does
not unblock Item 35: it prevents future false positives, while the historical
June train-side CLOB gaps still need real collection/backfill evidence before
a market-informed selector can be split-stable. That continuity work is now
tracked explicitly in Item 156 so the next Item 35 attempt does not treat
eval-only CLOB value as promotion evidence.

Follow-up capture-status tape update: `weather.market.market_microstructure`
now writes `clob_capture_status.jsonl` for every CLOB token/book capture
attempt, including failure-stage rows before exceptions re-raise. The refreshed
fleet audit
`data\backtest\data_layer_audit_after_clob_capture_status_report.md` reports
`12/177` folders with capture-status rows, but `0/165` training-ready folders
with capture-status rows; token/raw-book coverage remains `96/177` and
`84/177` overall, `84/165` and `72/165` training-ready. This improves future
root-cause logging but does not change the Item 35 model gate: CLOB-informed
repairs still need threshold-clearing train-side midpoint evidence before they
can support a split-stable selector.

## 2026-06-19 full density v0.7 replay rejection

The full continuous-density lane was trained and replayed, so Item 35 is no
longer blocked by missing full-corpus density evidence. The artifact
`data\backtest\item35_density_full_candidate_v0_7.pkl` was trained with
`weather.calibration.pooled_feature_model --objective density --holdout-year
2025` over `76,865` rows and reports schema
`pooled_continuous_density_hgb_v0.7`, feature schema
`toronto_feature_store_v1.6`, prediction mode `continuous_density_f`, and
hour models `07` through `20`.

The pinned replay
`data\backtest\item35_density_full_replay_v0_7_report.md` scored all `6,989`
snapshots / `76,879` market rows with zero missing candidate rows and returned
`BLOCK / DO_NOT_CUT_OVER`. Corpus pinning passed, replay fidelity passed with
the existing no-exact-identity warning, and daily-first leakage audit passed
over `53` audited splits.

Replay scores reject this artifact as a cutover candidate:

- Aggregate: candidate Brier `0.045390`, current `0.042669`, market `0.037323`
  (`+0.002721` versus current, `+0.008067` versus market).
- Daily-first: candidate `0.044628`, current `0.041916`, market `0.036667`
  (`+0.002713` versus current, `+0.007961` versus market).
- Toronto still regresses: candidate `0.039948`, current `0.036774`, market
  `0.033427`.
- Forecast-profile guardrails block Austin, Denver, NYC, San Francisco,
  Seattle, and Toronto.

The conservative bridge shadow policy improves the full-density artifact but
does not clear the model gate: bridge aggregate Brier is `0.042463`, only
`-0.000206` better than current and still `+0.005140` worse than market. It is
serving-safety evidence, not proof that the unified density model beats current
per market or lifts Toronto. The next Item 35 unblock remains a direct model or
source-signal repair for the remaining market gaps plus a Toronto regression
guard; rerunning the same full density lane is now a measured dead end.

## 2026-06-19 blocked-market repair-action diagnostic

The blocked-market diagnostic now emits structured `repair_actions`,
`candidate_regresses_current`, and `primary_repair_action` fields instead of
only Brier tables. It is registered as
`blocked_market_repair_diagnostics_v0.1` and remains development evidence, not
promotion evidence.

I regenerated the retained later-date blocked-market export:
`python -m weather.reporting.blocked_market_repair_diagnostics data\backtest\item147_blocked_markets_time_split_alpha_variant_rows.csv --out data\backtest\item147_blocked_market_repair_actions.json --report data\backtest\item147_blocked_market_repair_actions_report.md --min-slice-rows 200 --top-slices 6`.

The report scores `30,569` rows across Austin, Los Angeles, NYC, San Francisco,
and Seattle. It confirms that the next useful model work is not another broad
density replay:

- Austin, Los Angeles, and San Francisco are `current_fallback_trails_market`
  with `1.0000` current-fallback share, so they need non-current forecast,
  source-state, or microstructure signal.
- Seattle is `winner_underpricing_vs_market`; the top repair is
  `repair_winner_probability_mass`, especially EQ / settlement-distance-0 rows.
- NYC is no longer a pure winner-underpricing case in this later-date export;
  its primary repair is `repair_largest_market_gap_slice`, led by
  settlement-distance-0 and near-forecast/cool-side slices.
- No market in this retained export regresses current, so the current-regression
  guard is wired and tested but does not fire on the Item 147 row set.

Verification:
`python -m pytest tests\reporting\test_blocked_market_repair_diagnostics.py tests\operations\test_schema_registry.py -q`
passed with `10 passed`, and
`python -m weather.schema_registry audit --paths src\weather\reporting\blocked_market_repair_diagnostics.py src\weather\schema_registry.py --strict`
reported `unregistered_versions=0`.

## 2026-06-19 forecast-side winner-boost rejection

The next split-safe winner repair was tested by extending
`weather.reporting.winner_boost_validation` beyond broad `all_eq`/`early_eq`
boosts. The validator now supports inference-available EQ policies split by
forecast-pressure side and cutoff regime (`near_forecast_eq`, `warm_side_eq`,
`cool_side_eq`, and early/midday variants). It still avoids
settlement-derived fields such as settlement-distance buckets.

Running the expanded policy grid on the retained blocked-market export:
`data\backtest\item147_winner_boost_forecast_side_validation_report.md`
returns `BLOCK`. The selector uses 2026-06-07/2026-06-08 rows for policy
selection and evaluates on 2026-06-12/2026-06-13. Later-date daily-first
performance worsens from the baseline candidate `0.0465` to `0.0519`, versus
current `0.0504` and market `0.0359`; the selected market gap is `+0.0160`.
Austin improves slightly but still blocks, while Los Angeles, NYC, San
Francisco, and Seattle all remain blocked and several regress the baseline
candidate.

This rejects another tempting postprocess path. The blocked markets need direct
model/source signal or better live microstructure continuity, not a simple
forecast-side EQ multiplier selected on earlier market-days.

## 2026-06-19 Item 32 branch basket check

The latest existing-variant basket check now includes the Item 32
reanalysis-rich no-pressure branch alongside Item 147 time-split alpha, Item
134 all-hour forecast profile, Item 135 cutoff-regime weighting, and current
serving:
`data\backtest\item147_blocked_markets_variant_basket_with_item32_validation_report.md`.
It is still development evidence, not promotion evidence, because selection is
performed among existing row exports on June 7/8 and evaluated on June 12/13.

The result remains `blocked`. Selected later-date daily-first Brier is `0.0465`
versus current `0.0505` and market `0.0359`, so the selected basket still
trails market by `+0.0106` and all five blocked markets remain blocked. Adding
Item 32 improves the diagnostic eval oracle from `+0.0092` to `+0.0085`, but
even the oracle remains outside market tolerance.

The one useful signal is Austin: the eval oracle would pick the Item 32 branch
with a `+0.0005` market gap, but the earlier-date selector picks current. That
means reanalysis may help Austin, but it is not yet split-stable enough to
support Item 35 or Item 48 promotion. NYC/Seattle still need direct winner or
slice repair, and San Francisco still needs a current-safe non-current signal.

The regenerated report now includes leave-one-market-day stability. Austin is
closer than the original split implied, but still not acceptable: Item 32 is
selected in 3 of 4 Austin held-out-day cuts, yet selected aggregate Brier is
`0.0416` versus current `0.0415` and market `0.0362`, a `+0.0054` market gap.
The eval oracle would pass at `-0.0002`, so the remaining Austin work is not
another broad branch selection pass; it is a guard or model feature that makes
the reanalysis lift stable across the weak June 7/13 cuts. Los Angeles also
gets Item 32 selected in 3 of 4 cuts but still misses market by `+0.0037`;
NYC, San Francisco, and Seattle remain outside tolerance even under the
leave-one-day oracle.

The added guarded-branch table gives the next Austin candidate shape. A fixed
Item 32 `all_fresh_midday_late` guard passes Austin locally at `+0.0024`
versus market while improving current by `-0.0024`. The train-selected guard
still blocks at `+0.0034`, just outside the `+0.0030` tolerance, because the
selector chooses `all_fresh` for the June 7 holdout and `all_fresh_midday_late`
for the other three cuts. This is development evidence only, but it is more
actionable than another all-branch basket: the next Item 35/48 model attempt
should test a predeclared Austin all-fresh midday/late reanalysis guard inside
the full replay/promotion harness, while keeping NYC/Seattle and
San Francisco/Los Angeles as separate repair tracks.

## 2026-06-19 replayed Austin reanalysis guard

The predeclared Austin guard was moved into a replayable artifact:
`data/backtest/item32_reanalysis_austin_all_fresh_midday_late_guard_candidate.pkl`.
`pooled_candidate_replay` now supports `current_blend_context_alpha` rules, so
the artifact keeps Austin on current serving except for all-fresh midday/late
rows where the Item 32 reanalysis branch is used. The full pinned replay is
`data/backtest/item32_reanalysis_austin_guard_replay_report.md`.

This is a measured improvement, not an Item 35 unblock. Aggregate candidate
Brier improves slightly versus the prior Item 32 no-pressure branch (`0.04302`
versus `0.04310`), and Austin moves to `PASS`: candidate `0.03849`, current
`0.04099`, market `0.03620`, with a `+0.00228` market gap inside tolerance.
Houston and Los Angeles also pass.

The replay still reports `BLOCK / DO_NOT_CUT_OVER`: aggregate daily-first
market gap is `+0.00512`, and Chicago, NYC, San Francisco, and Seattle remain
blocked. This narrows the unified-model repair backlog but does not satisfy
Item 35's acceptance requirement to beat current per market and lift the
data-poor side. The next model work should keep the Austin guard and focus on
NYC/Seattle winner/slice repair plus Chicago/San Francisco non-current skill.

## 2026-06-20 UTC combined guard/raw-alpha replay

The next unified-density diagnostic preserved the Austin all-fresh midpoint/late
reanalysis guard and reopened only Chicago and NYC to raw candidate alpha:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_candidate.pkl`.
San Francisco remained current-guarded because the earlier broad raw-alpha
test regressed current there.

The full pinned replay
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_replay_report.md`
is still `BLOCK / DO_NOT_CUT_OVER`, so Item 35 remains `PARTIAL`. The useful
movement is that aggregate candidate Brier improves to `0.04141` versus
current `0.04349`, and daily-first market gap narrows to `+0.00353` from the
Austin-only guard's `+0.00512`. Candidate cutover-ready markets remain Austin,
Houston, and Los Angeles; Atlanta, Dallas, Denver, and Miami remain shadow;
Chicago, NYC, San Francisco, and Seattle remain blocked.

This does not meet the Item 35 closure bar because the candidate still does
not beat market/current constraints per market. Chicago and NYC now beat
current but miss market tolerance (`+0.00418` and `+0.01013`), San Francisco
still needs non-current signal, and Seattle remains the largest market gap.
The refreshed repair diagnostic
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_repair_actions_report.md`
points the next density-model work at Chicago slice repair, NYC/Seattle winner
probability mass, and independent San Francisco signal rather than another
broad alpha opening.

The current-blend time-split validator was updated to honor
`current_blend_context_alpha`, then rerun on the same combined replay rows:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_current_blend_validation_report.md`.
It remains `BLOCK`. Austin context rows are now counted as raw-candidate rows,
but earlier-date alpha selection worsens later-date performance versus the
combined baseline: selected daily-first market gap `+0.00527` versus baseline
`+0.00491`. This confirms Item 35 should not spend another pass on broad
current-blend alpha tuning; the remaining work is direct market-specific model
repair.

The follow-up context-guard scan
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_context_guard_validation_report.md`
tested inference-time raw/current guards over source freshness, cutoff regime,
forecast disagreement/pressure, forecast source count, and band type. It also
rejects this lane: selected daily-first market gap is `+0.00509`, worse than
the combined baseline's `+0.00491`. Chicago's best guard improves current but
still misses market tolerance, NYC and Seattle remain far outside market, and
San Francisco has no raw candidate rows to guard. Item 35 still needs new
model/source signal rather than policy selection over the current probability
export.

## 2026-06-20 UTC reproducible two-condition context-guard rejection

I replaced the ad hoc context-guard scan with the registered
`weather.reporting.context_guard_validation` tool and regenerated the report at
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_context_guard_validation_report.md`.
The new run tests two-condition no-market policies as well as single-condition
guards, selecting on earlier market-days and evaluating later market-days.

This still rejects context guarding as the next Item 35 model path. Selected
daily-first Brier worsens to `0.0439` versus market `0.0385` (`+0.0054`),
while the observed combined baseline is `0.0434` (`+0.0049`). The best eval
oracle policies still miss market tolerance for Chicago (`+0.0047`), NYC
(`+0.0195`), San Francisco (`+0.0056`, with no non-current rows), and Seattle
(`+0.0161`). The selected policy also newly blocks Austin/Houston/Los Angeles
on the holdout split, so the unified-density repair should not add another
context guard over this export. It needs new feature/model signal: Chicago
slice repair, NYC/Seattle winner-mass repair, San Francisco non-current signal,
and the Toronto lift requirement from the Item 35 acceptance bar.

## 2026-06-20 UTC winner-mass repair targeting

I regenerated the current-baseline winner-underpricing casebook after adding
full-case dominant-pattern reporting:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_winner_underpricing_casebook_report.md`.
The report finds `312` early cases where the market ranked the eventual winner
well but the combined candidate underweighted it or spread too much mass across
nearby bands.

The useful Item 35 repair split is now sharper:

- NYC is the strongest direct winner-mass target: `131` cases, `122` all-fresh,
  `91` high-disagreement, and repeated `eq:88.0-89.0` / `eq:94.0-95.0`
  underpricing with average winner gaps of `+0.2492` and `+0.1873`.
- Seattle is the second direct winner-mass target: `113` cases, `80`
  warm-side, with `eq:74.0-75.0` and `eq:64.0-65.0` carrying average winner
  gaps of `+0.2116` and `+0.2494`.
- Chicago still needs a slice repair first: it has `44` cases, but average
  spread gap is `-0.1355`, so the candidate is not simply too diffuse around
  the winner.
- San Francisco needs independent non-current signal: all `24` cases are
  `near_forecast` and `high_disagreement`, with a smaller average winner gap
  (`+0.0509`) but a large positive spread gap (`+0.6974`).

This does not change Item 35 status. The item remains `PARTIAL` until a
candidate beats current per market, clears the full pinned replay, and lifts
Toronto without replay-row tuning.

## 2026-06-20 UTC band-key contextual winner repair validation

I extended `weather.reporting.contextual_winner_validation` to
`contextual_winner_time_split_validation_v0.2` so it can fit split-safe
band-key contextual factors and report a diagnostic eval oracle. The current
combined replay artifact is:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_contextual_winner_validation_report.md`.

This is a useful direction but not an Item 35 unblock. On the full later-date
combined holdout, selected contextual factors improve daily-first Brier from
baseline `0.0434` to `0.0426` versus market `0.0385`, reducing the market gap
from `+0.0049` to `+0.0041`. However, it still leaves the key blocked markets
outside tolerance: Chicago `+0.0097`, NYC `+0.0207`, San Francisco `+0.0056`,
and Seattle `+0.0164`.

The eval-oracle section explains why static winner-mass postprocessing is not
enough. Future-selected band-key factors would clear these markets
diagnostically, but the selected train factors target the wrong bands on the
later dates. NYC train factors target `eq:80.0-81.0` and `eq:74.0-75.0`, while
the eval oracle needs `eq:94.0-95.0` and `eq:88.0-89.0`; Seattle train factors
target `eq:60.0-61.0`, while the eval oracle needs `eq:74.0-75.0`. This
narrows the next density-model requirement: add an inference-time signal that
predicts the correct target-day winner band context before applying contextual
mass, rather than fitting another prior-day exact-band multiplier.

Focused validation for the code path:
`python -m pytest tests\reporting\test_contextual_winner_validation.py tests\operations\test_schema_registry.py -q`
passed with 9 tests, and strict schema audit reported
`registered=197 discovered=210 unregistered_versions=0`.

## 2026-06-20 UTC nested winner-band row-signal rejection

I added and ran the registered nested row-signal validator:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_winner_band_signal_validation_report.md`.
It tests whether a pooled logistic row model over inference-time distribution
shape and forecast/source context can identify the target-day winner band
without eval-date selection. The no-leakage audit passes: transform selection
uses `2026-06-08`, then the final model is scored on `2026-06-12` and
`2026-06-13`.

The selected transform is `baseline`, so this is not an Item 35 candidate.
The selection holdout rejects `row_norm` (`0.0443` versus baseline `0.0383`).
On the later eval dates, `row_norm` is the best hindsight diagnostic
(`0.0424` versus baseline `0.0434` and contextual winner `0.0426`), but it is
not selectable and still leaves the density blocker intact: Chicago
`+0.0075`, NYC `+0.0175`, Seattle `+0.0180`, Houston `+0.0064`, and
Los Angeles `+0.0051` versus market. San Francisco improves to `+0.0024` in
that eval-only diagnostic, which is useful targeting evidence but not a
promotion path.

This rules out a generic row-shape classifier as the next continuous-density
repair. Item 35 still needs a real new signal that predicts the target-day band
shift, plus the existing acceptance bar: beat current per market, clear the
full pinned replay, and lift Toronto without replay-row tuning.

## 2026-06-20 UTC CLOB continuity blocks market-informed density repair

I regenerated the combined Item 32/35/48 CLOB coverage audit:
`data/backtest/item32_35_48_combined_replay_clob_coverage_audit_report.md`.
It now emits `clob_coverage_audit_v0.3`, uses the exact replay-window split
that the current combined candidate relies on, and scans all local tape-backup
manifests for restorable raw CLOB sources.

The audit blocks any CLOB-informed density repair on the current export. Train
coverage is `0.0000`: all `24` train-side folders are
`missing_raw_clob_tape_and_token_map`, with no raw-book folders, no token-map
folders, and no midpoint rows. Eval coverage is asymmetric and only diagnostic:
`16` folders have midpoint coverage, `8` are one-sided/no-midpoint, and eval
midpoint row coverage is `0.2380`.
The restore-source scan finds no local raw recovery path for the train split:
the June 7/8 train folders have feature shells in manifests, but `0/24` have
raw-book restore paths, token-map restore paths, or full raw restore
availability. All `24` June 12/13 eval folders do have full raw restore
sources.

This keeps Item 35 `PARTIAL`. CLOB may still be the right target-day
band-selection signal for NYC/Seattle winner-mass repair and San Francisco
non-current signal, but it cannot be selected or fitted split-safely until the
train side has raw CLOB continuity. The next density-model unblock is therefore
data work first: find an external/off-machine restore for the missing June 7/8
raw books and token maps, or collect new predeclared train/eval market days
with full CLOB continuity, then rerun the coverage audit before attempting
another market-informed density candidate.

## 2026-06-20 UTC v0.7 row-export repair diagnostic

I reran the full v0.7 density candidate replay with candidate variant-row
export enabled:
`data/backtest/item35_density_v0_7_row_export_replay_report.md` and
`data/backtest/item35_density_v0_7_variant_rows.csv`. The replay still returns
`BLOCK / DO_NOT_CUT_OVER` over `76,879` rows. Aggregate candidate Brier is
`0.04539` versus current `0.04267` and market `0.03732`; daily-first candidate
Brier is `0.04463` versus current `0.04192` and market `0.03667`.

The repair diagnostic
`data/backtest/item35_density_v0_7_repair_diagnostics_report.md` confirms that
the miss is not just one market or one missing export. The same nine markets
remain blocked versus current/market acceptance: Austin, Chicago, Denver,
Los Angeles, Miami, NYC, San Francisco, Seattle, and Toronto. Nine markets also
regress current on daily-first evidence: Austin, Chicago, Dallas, Denver,
Los Angeles, Miami, San Francisco, Seattle, and Toronto. Winner underpricing
versus market appears in eight markets: Austin, Chicago, Denver, Los Angeles,
Miami, NYC, San Francisco, and Seattle.

The strict early winner-underpricing casebook
`data/backtest/item35_density_v0_7_winner_underpricing_casebook_report.md`
finds `673` cases across Austin, Los Angeles, NYC, San Francisco, and Seattle.
Average winner probability gaps versus market are largest in NYC (`+0.2796`),
Los Angeles (`+0.1765`), Seattle (`+0.1463`), Austin (`+0.1362`), and
San Francisco (`+0.1051`). NYC remains the cleanest direct winner-mass repair
target, but most other blocked markets also need a split-safe current
regression guard or new target-day band-selection signal.

This keeps Item 35 `PARTIAL`. The useful unblock path is now explicit: do not
spend another pass on broad density blending alone. First restore or collect
split-safe CLOB/microstructure continuity, then train a target-day
band-selection repair that can lift winner mass and pass a current-regression
guard on later dates, including Toronto, before rerunning the full pinned
replay.

## 2026-06-22 v0.7 diagnostic refresh

I regenerated the lightweight diagnostics from the existing v0.7 density row
export, without starting another long retrain/replay:

- `data/backtest/item35_density_v0_7_repair_diagnostics.json`
- `data/backtest/item35_density_v0_7_repair_diagnostics_report.md`
- `data/backtest/item35_density_v0_7_winner_underpricing_casebook.json`
- `data/backtest/item35_density_v0_7_winner_underpricing_casebook_report.md`

The refreshed repair diagnostics still scan `76,879` v0.7 replay rows across
all 12 markets and keep the same fail-closed conclusion. Nine markets regress
current or miss market tolerance enough to need current-regression guarding:
Austin, Chicago, Denver, Los Angeles, Miami, San Francisco, Seattle, Toronto,
plus Dallas as a monitor/current-regression case. NYC is the cleanest direct
winner-mass repair target because the v0.7 candidate does not regress current
there but remains far outside market tolerance.

The strict early winner-underpricing casebook still finds `673` cases across
Austin, Los Angeles, NYC, San Francisco, and Seattle. Average winner-probability
gaps versus market remain largest in NYC (`+0.2796`), Los Angeles (`+0.1765`),
Seattle (`+0.1463`), Austin (`+0.1362`), and San Francisco (`+0.1051`). This is
development targeting evidence only, not promotion evidence.

Item 35 remains `PARTIAL`: the continuous-density serving, replay, calibration,
and v0.7 artifact paths are implemented, but the acceptance bar is empirical.
The latest candidate still fails the full pinned replay, regresses current in
too many markets, and does not lift Toronto. Another broad density blend is not
the next useful step; the next unblock is split-safe target-day band-selection
signal, likely after restoring/collecting CLOB continuity or another validated
source family that predicts winner-band movement without replay-row tuning.

Verification:

- `python -m pytest tests\model\test_continuous_density.py tests\model\test_market_units.py tests\calibration\test_probability_calibration.py tests\calibration\test_pooled_feature_model.py tests\calibration\test_pooled_candidate_replay.py tests\reporting\test_blocked_market_repair_diagnostics.py tests\reporting\test_winner_underpricing_casebook.py tests\operations\test_schema_registry.py -q`
  passed with `134 passed`, `16 warnings`.
