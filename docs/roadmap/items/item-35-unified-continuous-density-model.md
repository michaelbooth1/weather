# 35. Unified Continuous-Density Model [PARTIAL 2026-06-18 - HOLDOUT SIGMA ADDED, EMPIRICAL LIFT BLOCKED]

Goal: one model for all cities; C/F becomes serving-only (audit Option B).

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
evidence rather than being closed by code-only work.

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
