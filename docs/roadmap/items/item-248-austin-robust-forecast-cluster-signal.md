# 248. Austin Robust Forecast-Cluster Signal [OPEN 2026-06-22 - FEATURE-PATH MAX CLUSTER OVERHEATS]

Goal: Replace or cap the feature-path forecast-cluster `max()` signal so a lone warm source cannot dominate the live distribution near a settlement boundary.
Source: 2026-06-22 Austin weather-model disagreement audit. At roughly 14:57 CDT, Weather.com was 94F, Open-Meteo was 93F, NWS was near 95F, and the global ensemble was 95.9F; the feature path converted the warmest input into a rounded 96F signal and left `96-97F` at 85.4% while independent fair value favored `94-95F`.
Why this matters: The fallback path already has correlated-source clustering, but the feature model can still overreact to the maximum of a mixed forecast cluster. This creates concentrated warm-side exposure exactly when the robust center is lower and the market is closer to settlement reality.

## Design

1. Reproduce the Austin 2026-06-22 afternoon snapshot from the feature tape and stage-attribution outputs.
2. Add a candidate feature-path cluster statistic that uses a robust median, trimmed high, or explicit lone-source cap instead of raw `max()`.
3. Gate the candidate on settlement-boundary sensitivity so one warm outlier cannot move the winning band unless the broader cluster agrees.
4. Replay Austin and the broader F-family warm-tail slices against market-relative and settlement-scored metrics.
5. Expose enough signal metadata to show raw max, robust center, trimmed high, and source-count agreement in proof packets.

- [ ] Austin replay isolates how much probability mass raw forecast-cluster `max()` adds to `96-97F`.
- [ ] Candidate robust-cluster signal is implemented behind a shadow flag or artifact variant, not served by default.
- [ ] Replay compares raw max, median, trimmed high, and capped-warm-source variants on exact-band Brier/logloss and market-relative error.
- [ ] Proof packet reports the selected cluster statistic and whether any warm source was capped as a lone outlier.
- [ ] Promotion gate requires no broad degradation on days where late warming legitimately continues after the audit hour.

Acceptance: The Austin case moves materially away from the 85% `96-97F` concentration while preserving skill on true warm-continuation days, and no feature-path candidate can promote unless it beats the active artifact and market/no-trade baselines on hard warm-tail slices.
Related: items 181, 183, 194, 195, 219, 232, 241, and 242.
