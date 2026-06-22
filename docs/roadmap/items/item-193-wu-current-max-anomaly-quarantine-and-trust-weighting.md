# 193. WU Current-Max Anomaly Quarantine And Trust Weighting [COMPLETE 2026-06-21 - TRUSTED SUPPORT-ONLY QUARANTINE FIELDS LIVE]

Goal: keep anomalous `wu_current_max_since_7am` values from warming the model
distribution unless they are independently confirmed by trusted observations.

Source: the settled June 20 root-cause audit. Several weak-window snapshots
had `wu_max_since_7am_c` values that were implausible relative to the final
settlement and surrounding observations. Examples: Houston at local `07:00`
had final `84-85 F`, `high_so_far=83`, `wu_current=81`, but
`wu_max_since_7am_c=93`; Seattle at local `07:00` had final `70-71 F`,
`high_so_far=57`, `wu_current=55`, but `wu_max_since_7am_c=81`. Those rows
coincided with warm model tops such as Houston `90-91 F` and Seattle
`74-75 F`.

Why this matters: the live-observation ledger can mark a current-max source as
support-only, but model features still expose the raw max-since-7 value. A
single stale or malformed WU max can therefore pull probability into impossible
warm bands and make both the model and taker policy overconfident.

## Design

1. Add a current-max anomaly detector comparing WU max-since-7 against trusted
   WU history, METAR, SWOB, current temp, and monotonic raw high.
2. Emit explicit feature fields for trusted current max, support-only current
   max, and quarantined current max instead of passing one ambiguous raw value.
3. Train and serve the model from trusted/support/quarantined current-max
   features, with quarantined values excluded from warm-tail centering.
4. Add a settled audit slice for days where WU current max exceeds final
   settlement by more than one band.
5. Backtest the detector on June 20 Houston, Seattle, Denver, Austin, and
   Toronto before serving it.

- [x] Add current-max anomaly flags to snapshot, feature, and taker tapes.
- [x] Exclude quarantined max-since-7 values from distribution centering and
  current-high lock-in features.
- [x] Add a June 20 fixture that reproduces Houston/Seattle warm anomalies.
- [x] Add a daily report table for current-max anomaly counts by provider and
  market.
- [x] Prove the anomaly guard reduces warm-tail probability on affected June 20
  snapshots without harming confirmed-current-high lock-in rows.

Acceptance: anomalous WU max-since-7 values are separated from trusted current
highs in both training and serving, June 20 Houston/Seattle no longer receive
warm-tail support from bad current-max rows, and daily learning reports the
number of quarantined current-max observations.

Completion note 2026-06-21: feature schema `toronto_feature_store_v1.13`
includes trusted/support-only/quarantined current-max fields plus diagnostics.
Live feature extraction and distribution centering consume `trusted_current_max`
instead of raw max-since-7 values, and the settled-day root-cause report now
emits current-max anomaly counts by market. Focused feature-store/live-floor
tests cover a large warm current-max gap and prove the floor is not applied.
