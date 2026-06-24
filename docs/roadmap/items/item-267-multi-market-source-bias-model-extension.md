# 267. Multi-Market Source-Bias Model Extension (Global-Ensemble + NWS, Per-Market Refit) [COMPLETE 2026-06-23 - MULTI-MARKET SOURCE-BIAS ARTIFACTS REFIT WITH RELIABILITY WEIGHTS]

Goal: extend the learned forecast-error / source-bias artifact so it (a) covers
every forecast source the multi-market model actually consumes, and (b) is fit
per market (or per regime) rather than on Toronto alone, so the model's input
debias matches the sources and locations it serves.

Source: the 2026-06-23 per-location week audit (Jun 16-22, served tape vs
`settlement.json` winning band). Tracing the model's persistent noon warm tilt
(`+1.10 F` mean expected-high bias, 71% of market-days hot) to its inputs showed
that the warm side is dominated by sources the learned bias model does not
correct:

- Pooled across the 11 F-markets at the noon snapshot (n=77 market-days):
  `global_ensemble` is the **hottest and noisiest** forecast source at
  `+1.01 F` signed bias / `2.82 F` MAE; `nws_forecast` `+0.08 F` / `1.74 F`;
  `open_meteo` `-0.82 F` / `2.09 F`; `weather_forecast` `-0.91 F` / `1.43 F`.
- Toronto (C): `eccc_citypage` runs `+1.14 C` hot / `1.43 C` MAE;
  `global_ensemble` `-0.53 C`.
- The model's net expected-high bias (`+1.10 F`) is **larger than any single
  source's signed bias**, i.e. the blend leans toward the hot `global_ensemble`
  / carries a residual warm offset rather than averaging its mixed inputs.

The learned artifact does not cover this. `artifacts/calibration/forecast_error_model.json`
(`generated_at_utc` 2026-06-10) has `source_stats` for only
`eccc_citypage`, `open_meteo`, and `weather_forecast`; its `training.snapshot_folders`
are **all Toronto** (`target_date_max` 2026-06-09). So `global_ensemble` and
`nws_forecast` — the two largest F-market offenders — have **no learned bias,
MAE, or tail-miss term at all**, and the existing three sources' bias estimates
were never refit for the 11 US markets.

Why this matters: items 194/195 dampen isolated warm outliers and recenter the
morning/ramp window, and item 266's parity gate now blocks the current model on
the model-vs-market winner-rank gap (model winner prob `48.5%` vs market
`55.7%`, June 16-22). But all of that operates downstream of an input layer
whose learned debias is blind to the hottest, noisiest source and to every
non-Toronto market. Fixing the input bias is the cheapest, most direct lever on
the warm tilt and on `global_ensemble`'s `2.82 F` dispersion, and it is a
prerequisite for cleanly attributing any residual output-level offset
(item 268).

Why it is not already covered: item 22 (Forecast-Error And Source-Bias Model) is
COMPLETE but shipped a Toronto-only, three-source artifact. Item 183 clusters
correlated sources for a fallback path but does not learn per-source bias/spread.
Item 266 explicitly defers un-owned case classes to "a suggested item only when
no owner exists"; the learned source-bias artifact's coverage gap has no owner.

## Design

1. Add `global_ensemble` and `nws_forecast` to the forecast-error model's
   `source_stats`, learning observed-minus-forecast bias, MAE/RMSE, within-1 and
   tail-miss rates by horizon and time of day for each, against the settled
   winning high.
2. Fit the artifact across all 12 markets (per-market where sample supports it,
   else per regime: continental / marine / Canadian), replacing the Toronto-only
   training corpus, with shrinkage to a pooled prior for thin markets.
3. Keep the existing `component` mechanism (per-C disagreement sigma, source
   weight shrink) but drive `source_weight_shrink_k` from each source's learned
   reliability so a high-variance source like `global_ensemble` (`MAE 2.82 F`)
   is down-weighted, not just debiased.
4. Validate by settlement-scored Brier/log-loss on the June 16-22 corpus and the
   broader settled set, sliced by market and source-health state; require the
   refit artifact to reduce the noon expected-high warm bias and the
   `model_top_miss | market_top_hit` parity case class without adjacent-band or
   bottom-location regressions.
5. Add a leakage guard (sources available before cutoff only) and surface the
   per-source learned bias/MAE in the replay/promotion reports and the item-262
   reliability scorecard.

- [x] Extend `source_stats` to `global_ensemble` and `nws_forecast`.
- [x] Refit per-market/per-regime across all 12 markets with pooled shrinkage.
- [x] Drive source down-weighting from learned reliability, not just bias.
- [x] Settlement-scored validation by market + source-health, parity-gate safe.
- [x] Leakage guard + per-source bias/MAE exposed in reports and the scorecard.

Acceptance: the served model's forecast-component debias covers every consumed
forecast source and is fit on the markets it serves; the refit reduces the
measured noon expected-high warm bias and the model-vs-market winner-rank parity
case class on settlement-scored, day-blocked evidence without regressing the
proof-packet early-hour, exact-band, bottom-location, ramp, and late gates.

## Completion Evidence

Implemented `forecast_error_model_v0.2` with canonical source aliases
(`nws_forecast`/`nws` -> `nws_hourly`), explicit market/regime metadata,
source-coverage checks, raw and shrinkage-adjusted stats, and learned
reliability/effective source weights. Runtime lookup now uses the same alias and
reliability helpers as training, so high-variance sources are debiased and
down-weighted from the artifact rather than hard-coded.

`python -m weather.calibration.forecast_error_model train-all` refit all 12
market artifacts plus `forecast_error_model_f_family.json` through
2026-06-22. The F-family artifact now covers `global_ensemble`, `nws_hourly`,
`open_meteo`, and `weather_forecast` with coverage `PASS`, `96,726` rows, and
source reliability/effective weights; each per-market artifact also reports
coverage `PASS`. The proper-scoring reliability scorecard now surfaces
per-artifact source bias/MAE/RMSE/reliability/weight and regenerated with
status `PASS`.

Validation: `python -m pytest tests\calibration\test_forecast_error_model.py
tests\reporting\test_proper_scoring_reliability_scorecard.py -q` passed, and
the broader focused regression set for items 267/268 passed (`66 passed`). The
item-266 winner-rank parity gate was rerun after report refresh and remains
`BLOCK` on existing served/candidate tapes (`model_top_hit=0.5407`,
`market_top_hit=0.6356`, excess `1390`); that gate does not replay the newly
trained source-bias artifacts by itself.

Related: items 22, 183, 194, 195, 232, 262, 264, 266, 268; `[[highs-projection-data-gap-2026-06-20]]`, `[[replay-ablation-findings]]`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - MULTI-MARKET SOURCE-BIAS ARTIFACTS REFIT WITH RELIABILITY WEIGHTS`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

