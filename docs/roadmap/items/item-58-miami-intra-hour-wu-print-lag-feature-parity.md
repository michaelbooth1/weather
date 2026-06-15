# 58. Miami Intra-Hour WU Print-Lag Feature Parity [NEW - AUDIT]

Goal: stop the feature model from serving stale printed-cutoff state when WU
history has already printed a settlement-relevant intra-hour row.

Miami audit source (2026-06-15): at 14:09 ET, WU history had a fresh 12:53 row
at 93 F and WU current/max-since-7am also showed 93 F, but the HGB feature
vector still served cutoff 12 with `high_so_far=91` and `current_temp=91`.
`effective_intraday_cutoff_hour` only advances when the latest WU row is at or
after the exact hour boundary, so a `12:53` settlement print is excluded from
the 13h model and from the 12h feature extractor. The resulting model gave
92-93 F about 29% versus the market at 96%.

- [ ] Add a feature-serving rule for WU hourly rows near the next hour boundary:
  a fresh `:53` settlement-source row should be eligible for the next cutoff
  when the wall clock has passed that cutoff and the row is on the target date.
- [ ] Keep train/serve parity explicit. Either mirror the same aliasing in
  historical feature construction or add a separate trained feature that marks
  printed-row recency and allows the model to learn the offset safely.
- [ ] Add a replay regression fixture for
  `highest-temperature-in-miami-on-june-15-2026` around
  `20260615T140914-0400`: WU history max 93, latest row 12:53, wall time 14:09,
  and current feature vector incorrectly reading 91.
- [ ] Verify the fix on the full pinned F-family promotion corpus and the
  current-serving gauntlet; the Miami row should move toward the observed 93 F
  state without reopening any market-level `BLOCK`.
- [ ] Add dashboard/model-explanation diagnostics that show both the selected
  feature cutoff and the latest settlement-source row time so this class of
  stale feature state is visible during live audits.

Acceptance: the Miami 2026-06-15 replay row no longer serves a 91 F feature
state after a fresh 93 F WU settlement-source print, and the pinned gauntlet
proves no aggregate regression or hidden train/serve skew.

