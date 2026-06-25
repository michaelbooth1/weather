# 197. Startup Live-Observation Null And Unit Guard [COMPLETE 2026-06-21 - IMPLAUSIBLE STARTUP OBSERVATIONS QUARANTINED]

Goal: prevent missing startup live observations from entering F-market feature
rows as Celsius-like or sentinel values.

Source: the June 20 feature tape audit. The first local `00:05` feature rows
for Austin, Denver, Miami, and NYC had `high_so_far=17.0` and
`current_temp=17.0` in F markets while `live_reading_temp` was missing. Minutes
later those markets jumped to plausible F values such as Austin `79`, Denver
`62`, Miami `79`, and NYC `71`. These bad first rows produced extreme
`forecast_gap` values from `64` to `75` degrees.

Why this matters: even if those startup rows did not cause the June 20 taker
loss directly, they contaminate live-forward evaluation, daily scoring, and
training exports. Unit-safe missing-feature handling cannot be considered
complete while startup rows can silently encode missing F observations as
`17.0`.

## Design

1. Add startup feature validation for market unit, plausible temperature range,
   and live-reading availability.
2. Replace missing startup current observations with explicit missingness
   features, not numeric sentinels.
3. Quarantine snapshot rows whose high/current features violate market-unit
   plausibility before they reach training or trading.
4. Add a clean-start smoke test for all active markets at the first snapshot of
   a target date.
5. Backfill an audit of historical first-snapshot feature rows for similar
   sentinel leaks.

- [x] Add first-snapshot unit plausibility checks to feature assembly.
- [x] Add tests for June 20-style F-market startup sentinel rows.
- [x] Emit startup quarantine counts in settled-day root-cause reporting.
- [x] Exclude quarantined startup rows from live feature values unless
  explicitly requested.
- [x] Verify no active F market can emit `17.0` high/current rows solely because
  live observations are missing.

Acceptance: missing startup observations are represented as missing, not
temperature values; implausible first-snapshot rows are quarantined; and June 20
F-market startup sentinel rows are covered by tests.

Completion note 2026-06-21: live feature extraction now validates startup
current/high values against market-unit plausibility and live-reading
availability. Implausible startup readings are nulled before feature use and
emitted with `startup_feature_quarantined_flag` diagnostics. Focused tests cover
the F-market `17.0` sentinel leak, and the settled-day root-cause report maps
remaining historical startup issues to this item.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - IMPLAUSIBLE STARTUP OBSERVATIONS QUARANTINED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

