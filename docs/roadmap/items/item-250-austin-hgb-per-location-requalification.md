# 250. Austin HGB Per-Location Requalification [OPEN 2026-06-22 - ACTIVE ARTIFACT LOSES TO MARKET]

Goal: Block or shadow Austin HGB serving until the per-location artifact clears market-relative replay, exact-band replay, and live proof-packet gates.
Source: 2026-06-22 Austin weather-model disagreement audit and current calibration artifact evidence. The active Austin path concentrated `96-97F` at 85.4% while the market and independent fair value strongly favored `94-95F`; stored Austin replay already showed the artifact losing to the market baseline.
Why this matters: A location-specific artifact that already loses to market replay should not be trusted live during high-disagreement active days. The serving gate needs to fail closed at the location-artifact level, not only at broad family level.

## Design

1. Define the Austin HGB requalification packet: market-relative score, no-trade baseline, exact-band calibration, warm-tail concentration, and late-day lock-in attribution.
2. Add a fail-closed serving disposition for Austin HGB when the active artifact lacks current requalification evidence.
3. Require active-artifact evidence rather than historical-family evidence for promotion back to live serving.
4. Add shadow candidate tracking for repaired Austin artifacts so they can accumulate market-relative proof without trading authority.
5. Include the Austin disagreement case in the hard-slice replay set used by the decisive model proof packet.

- [ ] Austin HGB serving disposition is `BLOCK` or `SHADOW` when active artifact evidence loses to market/no-trade baselines.
- [ ] Requalification requires exact-band and settlement-distance-0 replay, not only aggregate multiclass score.
- [ ] Proof packet includes the Austin 2026-06-22 disagreement snapshot as a named hard slice.
- [ ] Serving logs show whether Austin is using HGB, fallback, blended, or no-trade disposition.
- [ ] Repaired artifacts cannot promote without beating market-relative and settlement-scored gates on Austin-specific replay.

Acceptance: Austin HGB cannot serve live solely on broad F-family permission after failing local market-relative replay; requalification requires a fresh per-location proof packet that beats the market/no-trade baselines on the hard slices that exposed the failure.
Related: items 48, 218, 219, 224, 230, 231, 241, and 242.
