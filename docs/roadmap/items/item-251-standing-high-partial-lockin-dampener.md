# 251. Standing-High Partial Lock-In Dampener [OPEN 2026-06-22 - HIGH STOOD BUT FORECAST CEILING BLOCKS LOCK-IN]

Goal: Add a partial late-day dampener when the observed high has stood for at least 60 minutes and the latest official temperature is below that high, even if one or two forecast sources still imply another 1-2F of upside.
Source: 2026-06-22 Austin weather-model disagreement audit. The observed high had effectively stood, the latest official METAR had rolled down, but lock-in stayed inactive because live current/high state and a warm forecast ceiling kept the model focused on `96-97F`.
Why this matters: Late-day lock-in should not be all-or-nothing. A single remaining warm forecast can justify a tail, but it should not prevent the model from dampening mass above a standing observed high when official temperatures have already fallen.

## Design

1. Define a soft dampener curve using stood-high minutes, official current below-high delta, time of day, solar/ramp regime, and forecast-cluster agreement.
2. Preserve a nonzero one-up or two-up tail when the robust forecast cluster and physical regime support a rebound.
3. Downweight the dampener when official METAR data is stale, missing, or inconsistent with nearby live sources.
4. Add stage-attribution output that separates hard lock-in, partial dampening, and no-action states.
5. Replay late-day warm-tail cases with separate metrics for over-warm concentration and missed late climbs.

- [ ] Austin 2026-06-22 activates a partial dampener after the high has stood and official temperature is below the high.
- [ ] Dampener reduces concentrated mass above the standing high without zeroing plausible rebound buckets.
- [ ] Replay includes positive examples where late highs continue after an apparent stall.
- [ ] Stage attribution reports how much probability moved due to partial dampening.
- [ ] Promotion gate requires no degradation on late-day revision-up days and improvement on over-warm rollover days.

Acceptance: The partial dampener materially reduces Austin-style `96-97F` overconcentration after official rollover, while replay confirms it does not over-lock days that later make a new high.
Related: items 59, 170, 196, 232, 242, and 249.
