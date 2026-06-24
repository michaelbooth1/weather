# 58. Miami Intra-Hour WU Print-Lag Feature Parity [COMPLETE 2026-06-15 - PRINT-LAG PARITY FIXED]

Goal: stop the feature model from serving stale printed-cutoff state when WU
history has already printed a settlement-relevant intra-hour row.

Miami audit source (2026-06-15): at 14:09 ET, WU history had a fresh 12:53 row
at 93 F and WU current/max-since-7am also showed 93 F, but the HGB feature
vector still served cutoff 12 with `high_so_far=91` and `current_temp=91`.
`effective_intraday_cutoff_hour` only advances when the latest WU row is at or
after the exact hour boundary, so a `12:53` settlement print is excluded from
the 13h model and from the 12h feature extractor. The resulting model gave
92-93 F about 29% versus the market at 96%.

- [x] Add a feature-serving rule for WU hourly rows near the next hour boundary:
  a fresh `:53` settlement-source row should be eligible for the next cutoff
  when the wall clock has passed that cutoff and the row is on the target date.
- [x] Keep train/serve parity explicit. Either mirror the same aliasing in
  historical feature construction or add a separate trained feature that marks
  printed-row recency and allows the model to learn the offset safely.
- [x] Add a replay regression fixture for
  `highest-temperature-in-miami-on-june-15-2026` around
  `20260615T140914-0400`: WU history max 93, latest row 12:53, wall time 14:09,
  and current feature vector incorrectly reading 91.
- [x] Verify the fix on the full pinned F-family promotion corpus and the
  current-serving gauntlet; the Miami row should move toward the observed 93 F
  state without reopening any market-level `BLOCK`.
- [x] Add dashboard/model-explanation diagnostics that show both the selected
  feature cutoff and the latest settlement-source row time so this class of
  stale feature state is visible during live audits.

Implementation update (2026-06-15 UTC): serving now aliases a target-date WU
settlement-source print within 10 minutes before the next hour to that next
feature cutoff once wall time has passed the cutoff. Historical feature
construction already includes all rows `<= cutoff`, so `12:53` is part of the
13h trained printed path; the new regression test keeps that train/serve parity
explicit without adding trained columns.

Replay fixture/evidence:

- `tests/model/test_feature_skew.py::test_miami_20260615_140914_print_lag_aliases_to_13h_features`
  pins the Miami slug/snapshot shape and proves the 12:53 / 93 F print serves
  `cutoff_hour=13`, `high_so_far=93`, and `current_temp=93`.
- Direct replay-input verification for `20260615T140914-0400` now reports
  `cutoff_hour=13`, `high_so_far=93.0`, `current_temp=93.0`,
  `minutes_since_cutoff=69.0`, and latest WU history row `12:53` / `93.0`.
- `data/backtest/item58_promotion_gauntlet_report.md` is
  `PASS_WITH_SHADOWS`: corpus pin PASS, regression PASS with aggregate code
  effect `-0.0108` over 51 market-days / 6,989 snapshots / 76,879 band rows,
  no blocked markets, and Miami `PASS` with code effect `-0.0087`.

Diagnostics: feature audit rows now carry latest WU history time/minute/temp,
distribution component payloads carry the same selected-state diagnostics, and
the Streamlit model explanation panel shows the selected feature cutoff plus
the latest WU print.

Acceptance status: satisfied. The Miami 2026-06-15 replay row no longer serves
a 91 F feature state after the fresh 93 F WU settlement-source print, and the
pinned gauntlet proves no aggregate regression or market-level `BLOCK`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - PRINT-LAG PARITY FIXED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

