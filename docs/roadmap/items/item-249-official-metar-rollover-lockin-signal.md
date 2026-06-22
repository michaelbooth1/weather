# 249. Official METAR Rollover Lock-In Signal [OPEN 2026-06-22 - LATE ROLLOVER IGNORED WHEN WU CURRENT IS FLAT]

Goal: Feed official METAR trend and rollover state into late-day high-has-stood logic when WU/current readings are rounded, stale, or still equal to the observed high.
Source: 2026-06-22 Austin weather-model disagreement audit. KAUS reached about 93.9F at 13:53 CDT, then the 14:53 CDT METAR was down near 93.0F. The model's live high/current features still treated the current reading as equal to the high, so late-day lock-in stayed inactive.
Why this matters: The official station is the settlement source. A fresh official drop below the standing high is stronger evidence than a rounded third-party current reading that has not moved, especially late in the market day.

## Design

1. Add official METAR freshness, latest temperature, latest high-relative delta, and monotonic high timestamp to the lock-in feature context.
2. Separate third-party current equality from official current equality so rounded WU/current values cannot suppress a rollover signal.
3. Add a soft official-rollover feature that activates when the high has stood and the latest official temperature is below the high.
4. Replay late-day snapshots with official-current availability, missingness, and stale states split out.
5. Add diagnostics that explain whether lock-in was blocked by forecast ceiling, source freshness, current equality, or missing official data.

- [ ] Austin 2026-06-22 14:53 CDT METAR drop is represented as official current below standing high.
- [ ] Lock-in diagnostics distinguish WU/current flatness from official METAR rollover.
- [ ] Official-rollover feature is tested for missing, stale, rounded, and fresh-below-high source states.
- [ ] Late-day replay demonstrates improved warm-overconcentration cases without suppressing legitimate late rebounds.
- [ ] Proof packets show the official METAR trend used by any lock-in or dampening decision.

Acceptance: The Austin case activates an official-rollover lock-in signal or explicit risk flag, and late-day settlement replay improves or remains neutral on Brier/logloss while reducing over-warm mass after official temperatures have rolled down.
Related: items 5, 40, 59, 77, 196, 215, 232, and 242.
