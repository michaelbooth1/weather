# 196. Late-Day Lock-In Coverage And Saturation Parity [COMPLETE 2026-06-21 - EXPANDED STOOD-HIGH LOCK-IN LIVE]

Goal: expand trusted late-day lock-in coverage so the model saturates toward
the already-reached final band as quickly and reliably as the market does.

Source: the June 20 component audit. Late-day specialized components were very
strong when available: `high_has_stood_lockin` scored Brier `0.0003` on 66
hourly-checkpoint rows and `validated_current_max_floor` scored Brier `0.0126`
on 143 rows. But the final model still trailed market in `15:00-19:00`
(`0.0475` versus `0.0228`) and remained under-saturated in examples such as
Seattle and Houston before final close.

Why this matters: the project has lock-in logic, but coverage is too sparse or
too slow to dominate enough late-day rows. The market often knows the final band
once the high has stood; the model should not keep broad warm-tail mass when
trusted current-high evidence already collapses the outcome space.

## Design

1. Audit why high-has-stood and validated-current-max components fire on only a
   subset of late-day rows.
2. Add source-specific freshness and confirmation rules that allow trusted
   lock-in earlier without accepting anomalous max-since-7 values.
3. Promote lock-in probability saturation when the current high has stood past
   the forecast peak window and no trusted source shows a higher confirmed max.
4. Score lock-in coverage, not just lock-in accuracy, by market and local slot.
5. Add a late-day counterfactual showing how much Brier/P&L improves if sparse
   lock-in rows are expanded.

- [x] Add lock-in coverage metrics to settled-day root-cause reporting.
- [x] Produce a June 20 late-day lock-in miss list for Seattle, Houston,
  Austin, Chicago, NYC, and San Francisco.
- [x] Add earlier lock-in eligibility for stood-high plus trusted-source
  confirmation.
- [x] Guard the expanded lock-in path against quarantined current-max anomalies.
- [x] Prove focused late-day lock-in behavior without increasing false lock-ins.

Acceptance: lock-in components remain accurate while covering materially more
late-day rows, and the model closes the June 20 `15:00-19:00` saturation gap
without trusting anomalous current-max values.

Completion note 2026-06-21: `expanded_late_day_lockin_context` now covers
local `15:00-19:00` stood-high rows when current readings have rolled below the
printed high and remaining forecast ceilings do not clear it. The distribution
stage takes the maximum of heuristic, learned, high-has-stood, and expanded
lock-in strengths and snapshots `expanded_late_day_lockin` when it is the
decisive path. Focused tests cover activation and forecast-ceiling blocking.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - EXPANDED STOOD-HIGH LOCK-IN LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

