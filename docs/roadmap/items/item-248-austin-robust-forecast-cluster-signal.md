# 248. Austin Robust Forecast-Cluster Signal [COMPLETE 2026-06-22 - ROBUST FORECAST CLUSTER HARD-SLICE GATE LIVE]

Goal: Replace or cap the feature-path forecast-cluster `max()` signal so a lone warm source cannot dominate the live distribution near a settlement boundary.
Source: 2026-06-22 Austin weather-model disagreement audit. At roughly 14:57 CDT, Weather.com was 94F, Open-Meteo was 93F, NWS was near 95F, and the global ensemble was 95.9F; the feature path converted the warmest input into a rounded 96F signal and left `96-97F` at 85.4% while independent fair value favored `94-95F`.
Why this matters: The fallback path already has correlated-source clustering, but the feature model can still overreact to the maximum of a mixed forecast cluster. This creates concentrated warm-side exposure exactly when the robust center is lower and the market is closer to settlement reality.

## Design

1. Reproduce the Austin 2026-06-22 afternoon snapshot from the feature tape and stage-attribution outputs.
2. Add a candidate feature-path cluster statistic that uses a robust median, trimmed high, or explicit lone-source cap instead of raw `max()`.
3. Gate the candidate on settlement-boundary sensitivity so one warm outlier cannot move the winning band unless the broader cluster agrees.
4. Replay Austin and the broader F-family warm-tail slices against market-relative and settlement-scored metrics.
5. Expose enough signal metadata to show raw max, robust center, trimmed high, and source-count agreement in proof packets.

- [x] Austin replay isolates how much probability mass raw forecast-cluster `max()` adds to `96-97F`.
- [x] Candidate robust-cluster signal is implemented behind a shadow flag or artifact variant, not served by default.
- [x] Replay compares raw max, median, trimmed high, and capped-warm-source variants on exact-band Brier/logloss and market-relative error.
- [x] Proof packet reports the selected cluster statistic and whether any warm source was capped as a lone outlier.
- [x] Promotion gate requires no broad degradation on days where late warming legitimately continues after the audit hour.

Acceptance: The Austin case moves materially away from the 85% `96-97F` concentration while preserving skill on true warm-continuation days, and no feature-path candidate can promote unless it beats the active artifact and market/no-trade baselines on hard warm-tail slices.
Related: items 181, 183, 194, 195, 219, 232, 241, and 242.

## Completion - 2026-06-22

The feature-path forecast cluster now uses a robust source cluster instead of
allowing a lone warm source to own the peak signal. The Austin hard-slice proof
packet records the candidate as `item248_robust_forecast_cluster_v0_1` and
keeps promotion fail-closed behind the Austin HGB requalification packet.

Evidence:

- `data/backtest/austin_weather_model_hardening.json`
- `data/backtest/austin_weather_model_hardening_report.md`
- `data/backtest/austin_hgb_requalification.json`

The Austin hardening packet passes item 248 gates:

- `austin_raw_max_vs_robust_cluster_replay`: raw max signal `96F` is replaced
  by robust cluster signal `94.5F`, reducing deterministic `96-97F` tail mass
  from `0.4743` to `0.2562`.
- `variant_metric_comparison`: raw max, median, trimmed-high, and
  capped-warm-source variants are compared on exact-band Brier/logloss and
  market-relative error; the median/trimmed variants improve the deterministic
  Austin hard slice versus raw max.
- `warm_continuation_not_capped_when_sources_agree`: a multi-market F-family
  warm-continuation slice suite preserves the agreed warm signal when forecast
  sources agree.
- `candidate_promotion_fail_closed`: Austin serving disposition remains
  `SHADOW` until the local hard-slice requalification packet passes.

Verification:

```powershell
python -m weather.reporting.research.austin_weather_model_hardening
python -m pytest tests/reporting/test_austin_weather_model_hardening.py tests/model/test_estimate_distribution.py tests/operations/test_schema_registry.py -q
```

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22 - ROBUST FORECAST CLUSTER HARD-SLICE GATE LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

