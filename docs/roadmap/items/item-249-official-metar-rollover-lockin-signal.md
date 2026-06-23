# 249. Official METAR Rollover Lock-In Signal [COMPLETE 2026-06-22 - OFFICIAL ROLLOVER LOCK-IN LIVE]

Goal: Feed official METAR trend and rollover state into late-day high-has-stood logic when WU/current readings are rounded, stale, or still equal to the observed high.
Source: 2026-06-22 Austin weather-model disagreement audit. KAUS reached about 93.9F at 13:53 CDT, then the 14:53 CDT METAR was down near 93.0F. The model's live high/current features still treated the current reading as equal to the high, so late-day lock-in stayed inactive.
Why this matters: The official station is the settlement source. A fresh official drop below the standing high is stronger evidence than a rounded third-party current reading that has not moved, especially late in the market day.

## Design

1. Add official METAR freshness, latest temperature, latest high-relative delta, and monotonic high timestamp to the lock-in feature context.
2. Separate third-party current equality from official current equality so rounded WU/current values cannot suppress a rollover signal.
3. Add a soft official-rollover feature that activates when the high has stood and the latest official temperature is below the high.
4. Replay late-day snapshots with official-current availability, missingness, and stale states split out.
5. Add diagnostics that explain whether lock-in was blocked by forecast ceiling, source freshness, current equality, or missing official data.

- [x] Austin 2026-06-22 14:53 CDT METAR drop is represented as official current below standing high.
- [x] Lock-in diagnostics distinguish WU/current flatness from official METAR rollover.
- [x] Official-rollover feature is tested for missing, stale, rounded, and fresh-below-high source states.
- [x] Late-day replay demonstrates improved warm-overconcentration cases without suppressing legitimate late rebounds.
- [x] Proof packets show the official METAR trend used by any lock-in or dampening decision.

Acceptance: The Austin case activates an official-rollover lock-in signal or explicit risk flag, and late-day settlement replay improves or remains neutral on Brier/logloss while reducing over-warm mass after official temperatures have rolled down.
Related: items 5, 40, 59, 77, 196, 215, 232, and 242.

## Completion - 2026-06-22

Late-day lock-in context now accepts fresh official-current readings separately
from third-party current readings. A fresh METAR below the standing high can
activate lock-in even when WU/current remains rounded or flat at the high; stale
official readings stay diagnostic-only.

Evidence:

- `data/backtest/austin_weather_model_hardening.json`
- `data/backtest/austin_weather_model_hardening_report.md`

The Austin hardening packet passes item 249 gates:

- `official_rollover_activates_when_third_party_flat`: third-party current is
  flat at the high while METAR is `-0.9F` below the standing high, so the
  lock-in context activates with source `metar`.
- `stale_official_rollover_is_diagnostic_only`: stale METAR rollover is
  exposed as `official_current_stale` and does not activate.
- `late_rebound_ceiling_not_suppressed`: a high forecast ceiling still blocks
  lock-in so true late-warming cases keep a tail.
- `rollover_replay_reduces_warm_tail`: the deterministic late-day replay
  reduces above-high tail mass from `0.4800` to `0.0249`.

Verification:

```powershell
python -m weather.reporting.austin_weather_model_hardening
python -m pytest tests/reporting/test_austin_weather_model_hardening.py tests/model/test_late_day_lockin.py tests/model/test_estimate_distribution.py -q
```
