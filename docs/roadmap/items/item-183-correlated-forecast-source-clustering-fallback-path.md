# 183. Correlated Forecast-Source Clustering On Fallback Path [COMPLETE 2026-06-21 - FALLBACK CONSENSUS CLUSTER LIVE]

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

1. Reuse a forecast-family cluster on the empirical fallback path: combine the
   forecast sources into one consensus-centered vote sized by agreement and
   source count, not N independent bumps.
2. Keep genuinely independent observations (WU history, SWOB, METAR) as separate
   signals.
3. Replay-validate on days that actually fall back to empirical (feature gate off
   or artifacts absent), since healthy ML-path days are unaffected.

- [x] Apply a single clustered forecast vote on the empirical fallback path.
- [x] Preserve independent observation signals.
- [x] Replay on fallback-path days and confirm reduced overconfidence.

## Implementation

`distribution_live_signals` now emits one forecast-family signal on the
unweighted empirical fallback path instead of five independent forecast bumps.
The cluster uses the median forecast-family high as the consensus center, a
source-count cap of 2.40 once at least two forecast sources are present, and the
existing forecast-agreement spread penalty. Independent observation signals
remain separate: WU history, disabled paid-provider current, same-day current max, ECCC
SWOB, and METAR keep their own signal slots. The calibrated empirical path
remains minimal and unchanged.

## Validation

- `python -m pytest tests\model\test_estimate_distribution.py -q` -> 35 passed.
- Isolated fallback replay, forced through the unweighted empirical branch for
  stored unweighted empirical snapshots: 129 snapshots, 1,419 band rows, 86
  forecast-miss snapshots.
- Clustered current code vs a temporary legacy subclass restoring the five
  independent forecast bumps:
  - all rows: Brier delta -0.00000675, log-loss delta -0.00001998
  - forecast-miss rows: Brier delta -0.00001501, log-loss delta -0.00004575
  - losing rows: Brier delta +0.00000037, log-loss delta -0.00000633

Acceptance: the empirical fallback applies one clustered forecast vote, and
replay on fallback days shows lower log-loss on misses (less overconfidence) with
no aggregate regression.

Related: item 182; `[[model-audit-2026-06-09]]`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - FALLBACK CONSENSUS CLUSTER LIVE`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

