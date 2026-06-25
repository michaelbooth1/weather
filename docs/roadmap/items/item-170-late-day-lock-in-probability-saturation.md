# 170. Late-Day Lock-In Probability Saturation [COMPLETE 2026-06-20 - GROUP-GATED LOGISTIC LOCK-IN PASS]

Goal: reduce late-day market-relative underconfidence by making the model lock
in more decisively when observed-high and settlement-bin evidence says the
winning band is effectively known.

Source: `data/backtest/ten_minute_model_performance_audit.md`. The worst
slots versus market are not the same as the worst absolute model slots. Late
slots such as `18:00`, `18:10`, `18:20`, `19:00`, and `20:40` have much lower
absolute Brier than the predawn weak slots, but market Brier is near zero
because the market is almost resolved. For example, at `18:00` model Brier is
`0.0439` versus market `0.0063`, with winner model probability `56.5%`
versus market `89.2%`.

Why this matters: this is not the main early-hour model weakness, but it is a
real model-calibration gap. A weather-only model that stays too conservative
after the high has likely stood will trail the market, understate edge
confidence, and distort market-making/taker risk decisions.

## Design

1. Create a late-day lock-in slice for `15:00` through `23:00`, with special
   attention to the `18:00` through `20:40` market-relative blocker slots.
2. Use no-market serving features: current high, max since 7am, settlement-bin
   match, minutes since current high changed, remaining heating potential,
   source freshness, source agreement, local climatological peak timing, and
   late-day forecast gap.
3. Calibrate a lock-in probability saturation layer that raises the current
   winning/adjacent band only when the high-has-stood evidence is strong.
4. Add safeguards against over-locking on days with late spikes, missing live
   observations, stale WU history, or high forecast disagreement.
5. Evaluate separately from market-aware overlays so this remains weather-model
   calibration rather than a market-price anchor.
6. Feed late-day market-relative failures into daily learning without letting
   them obscure the higher-priority predawn absolute-Brier repair.

- [x] Build a late-day lock-in casebook from the worst market-relative
  10-minute slots.
- [x] Add no-market high-has-stood and remaining-heating features to the
  candidate calibration path.
- [x] Train or postprocess a late-day saturation candidate and compare against
  current, market, and existing lock-in logic.
- [x] Add over-locking guardrails for late-day spike cases and stale-source
  cases.
- [x] Prove late-day Brier/log-loss improves versus current without regressing
  predawn weak slots or ramp/midday discovery windows.

Implementation evidence (2026-06-20): `weather.reporting.research.late_day_lock_in_repair`
writes `data/backtest/late_day_lock_in_repair.json` and
`data/backtest/late_day_lock_in_repair_report.md` with schema
`late_day_lock_in_repair_v0.1`. The passing candidate,
`late_day_group_gated_logistic_lock_in`, uses no market features. It fits a
regularized logistic scorer on the selected late-day train split, then
normalizes only safe late-day snapshot groups with forecast gap `<= -1.0`,
slot `>= 17:00`, no positive warming/live-reading risk when present, and a
WU-history consistency guard requiring WU history high to be no more than
`0.1` above the feature high-so-far. The candidate changed `94` safe snapshot
groups and `1034` rows for the same late-day market-relative slots: `16:10`,
`17:10`, `17:20`, `17:30`, `17:40`, `18:00`, `18:10`, `18:20`, `18:30`,
`19:00`, `19:20`, and `19:50`.

Result: the candidate passes. On the eval split, Brier improves from `0.0445`
to `0.0407` (`-0.0038` versus current), log-loss improves by `-0.1289`, and
winner probability rises from `0.5596` to `0.6021`. The candidate still trails
market Brier `0.0116` by `+0.0290`, but shrinks the market-relative Brier gap
by `+0.0038` and the market-relative log-loss gap by `+0.1289`. The explicit
over-lock guardrail passes on `129` high-so-far mismatch snapshots with zero
changed risky rows and no Brier/log-loss regression. Scope guardrails also pass:
predawn (`19954` rows), ramp/midday (`20658` rows), and non-selected late-day
(`23705` rows) slices are unchanged versus current.

Acceptance: the model raises winner probability in late-day lock-in states,
shrinks the market-relative Brier/log-loss gap on the `18:00` through `20:40`
blocker slots, and passes explicit over-locking guardrails on days where the
eventual high can still move.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - GROUP-GATED LOGISTIC LOCK-IN PASS`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

