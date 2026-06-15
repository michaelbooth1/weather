# 59. Afternoon High-Has-Stood Lock-In Model [NEW - AUDIT]

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

- [ ] Build a market/day/cutoff training table with printed high, first time at
  high, minutes the high has stood, current-minus-high, remaining forecast
  ceiling, remaining degree-hours above high, wind regime, humidity/dewpoint,
  and final settlement bucket.
- [ ] Train or calibrate a compact continuation/lock-in component for the
  probability that final high remains at the current WU floor versus reaches
  one or more buckets higher.
- [ ] Integrate the component before or alongside late-day lock-in; it must be
  allowed to activate in the 13-15h window when the high has stood and forecasts
  have rolled below the floor, not only after the current 17h learned lock-in
  start.
- [ ] Keep it separate from hard floors. A printed 93 F floor should eliminate
  lower buckets, while the lock-in component should decide how much mass belongs
  on 93 versus 94+.
- [ ] Score the component on pinned F-family rows by market, cutoff hour,
  distance from floor, and forecast-gap state; do not promote it if it only
  improves the Miami audit row while hurting the corpus.

Acceptance: the Miami 2026-06-15 92-93 F row has a generated fair-value
explanation that reflects the printed high standing, live rollover, and
remaining forecast ceiling; settlement-scored replay shows the component is
neutral or positive on the pinned corpus and on similar afternoon floor rows.

