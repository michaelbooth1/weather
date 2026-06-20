# 183. Correlated Forecast-Source Clustering On Fallback Path [OPEN]

Goal: stop the empirical fallback distribution path from counting correlated NWP
forecasts as independent evidence.

Source: `docs/roadmap/core-model-audit-2026-06-20.md` finding M4. On the
empirical/non-feature path, `distribution_live_signals` emits a separate
multiplicative Gaussian bump for `weather_forecast_max`, `open_meteo_max`,
`nws_forecast_max`, `global_ensemble_max`, and `eccc_forecast_high`
([model_distribution.py:939-971](../../../src/weather/model/model_distribution.py#L939)),
and `apply_live_signals` multiplies them all in independently
([model_distribution.py:1023](../../../src/weather/model/model_distribution.py#L1023)).

Why this matters: these sources largely share an NWP backbone, so stacking them
as independent votes over-concentrates the consensus bucket — classic
correlated-evidence overconfidence. The primary ML path already solves this with
the explicit "peak cluster"
([model_distribution.py:906-928](../../../src/weather/model/model_distribution.py#L906)),
but the fallback path never got the same treatment, so any market/day that falls
back to empirical serves an overconfident forecast consensus.

## Design

1. Reuse the peak-cluster collapse on the empirical fallback path: combine the
   forecast sources into one clustered vote sized by agreement and source count,
   not N independent bumps.
2. Keep genuinely independent observations (WU history, SWOB, METAR) as separate
   signals.
3. Replay-validate on days that actually fall back to empirical (feature gate off
   or artifacts absent), since healthy ML-path days are unaffected.

- [ ] Apply a single clustered forecast vote on the empirical fallback path.
- [ ] Preserve independent observation signals.
- [ ] Replay on fallback-path days and confirm reduced overconfidence.

Acceptance: the empirical fallback applies one clustered forecast vote, and
replay on fallback days shows lower log-loss on misses (less overconfidence) with
no aggregate regression.

Related: item 182; `[[model-audit-2026-06-09]]`.
