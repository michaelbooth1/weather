# 59. Afternoon High-Has-Stood Lock-In Model [COMPLETE 2026-06-15 - HIGH-HAS-STOOD LOCK-IN LIVE]

Goal: learn a same-day lock-in probability for afternoon states where the high
has printed, stood for a meaningful interval, and remaining forecasts are below
that high.

Miami audit source (2026-06-15): independent fair value for 92-93 F was about
89% at 14:17 ET, versus market 96% and current model about 29%. WU history had
already printed 93 F at 12:53, WU current had rolled down to 92 F, and remaining
forecast rows were below 94 F. Historical KMIA mid-June analogs supported a high
but not certain lock-in: final stayed 93 in 16/21 cases where the rounded high
was already 93 by about 14:10, 12/17 when current was 92-93, and 6/6 when the
93 F high had stood at least 60 minutes.

- [x] Build a market/day/cutoff training table with printed high, first time at
  high, minutes the high has stood, current-minus-high, remaining forecast
  ceiling, remaining degree-hours above high, wind regime, humidity/dewpoint,
  and final settlement bucket.
- [x] Train or calibrate a compact continuation/lock-in component for the
  probability that final high remains at the current WU floor versus reaches
  one or more buckets higher.
- [x] Integrate the component before or alongside late-day lock-in; it must be
  allowed to activate in the 13-15h window when the high has stood and forecasts
  have rolled below the floor, not only after the current 17h learned lock-in
  start.
- [x] Keep it separate from hard floors. A printed 93 F floor should eliminate
  lower buckets, while the lock-in component should decide how much mass belongs
  on 93 versus 94+.
- [x] Score the component on pinned F-family rows by market, cutoff hour,
  distance from floor, and forecast-gap state; do not promote it if it only
  improves the Miami audit row while hurting the corpus.

Acceptance: the Miami 2026-06-15 92-93 F row has a generated fair-value
explanation that reflects the printed high standing, live rollover, and
remaining forecast ceiling; settlement-scored replay shows the component is
neutral or positive on the pinned corpus and on similar afternoon floor rows.

Implementation update (2026-06-15): the runtime distribution path now builds the
high-has-stood context from the same replay/live source rows used by inference:
printed WU high, first max time, standing minutes, current-minus-high, remaining
forecast ceiling, remaining degree-hours above the high, forecast source count,
and settlement-lag revision-up rate. The calibrated trigger activates only from
13-15h when the printed high has stood at least 60 minutes, the live reading has
rolled below that high, at least two forecast sources are available, and the
remaining forecast ceiling does not clear the printed high. When active, it
feeds the existing soft late-day upper-tail lock-in path; hard WU floors remain
separate and continue to handle lower-bucket elimination.

Evidence:

- Miami replay snapshots `20260615T141003-0400` and `20260615T141922-0400`
  now expose an active high-has-stood explanation: WU high 93 F, stood 77/86
  minutes, current-minus-high -1 F, four forecast sources, remaining forecast
  ceiling 92.1 F, and zero remaining degree-hours above the high. The 92-93 F
  probability moves from about 22% without this component to 84% with it, and
  the top bucket moves from 94 F to 93 F.
- `data/backtest/item59_high_has_stood_lockin_report.md` scores only rows where
  the new component activates: 151 active snapshots, 1,661 band rows, enabled
  Brier 0.0060 versus disabled Brier 0.0197, for a -0.0137 improvement. The
  active-slice report flags small adverse slices for Denver and Miami, so future
  calibration should keep monitoring per-market activation behavior.
- `data/backtest/item59_promotion_gauntlet_report.md` passes as
  `PASS_WITH_SHADOWS`: corpus pin PASS, regression PASS, aggregate code effect
  -0.0111, no blocked markets, and Miami remains PASS with code effect -0.0081.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - HIGH-HAS-STOOD LOCK-IN LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

