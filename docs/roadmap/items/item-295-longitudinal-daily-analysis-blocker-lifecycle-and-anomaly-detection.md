# 295. Longitudinal Daily-Analysis: Closed-Loop Blocker Lifecycle, Chronic Escalation, And Metric Anomaly Detection [OPEN 2026-06-24 - LEDGER HISTORY DEAD-LOADED, NO BLOCKER LIFECYCLE OR ANOMALY DETECTION]

Goal: turn the daily analysis from a single-day status dump into a learning
loop. Mine the existing daily progress ledger history to track each blocker's
lifecycle (new, persisting, resolved), escalate chronic blockers, and detect
day-over-day metric anomalies.

Source: 2026-06-24 audit of the daily analysis script. `daily_flow_analysis`
already loads the entire `daily_progress_ledger.jsonl` history into
`payloads["daily_progress_ledger"]`
(`src/weather/reporting/daily/daily_flow_analysis.py:144-156`) but never uses it:
`build_flow_analysis` does only single-day analysis, so the history is
dead-loaded. `daily_learning`'s `first_uncleared_p0_gate` is single-day, and the
only recurrence handling is the narrow `settled_day_root_cause` issue-recurrence
path. There is no general blocker age/streak, no closed-loop "did the recommended
action clear it", and no anomaly detection on ledger numerics (a labels-to-zero
or corpus-shrink event passes today's pass/fail logic silently).

Why this matters: the same data needed to learn over time is already persisted
and already loaded; not using it wastes I/O and leaves the highest-value signal
(which problems are chronic, which recommendations actually worked, which metrics
just cracked) entirely unanalyzed.

Why it is not already covered: item 163 persists the ledger rows, item 198/207
own settled-day root-cause recurrence and active-owner routing for a specific
issue class, and item 117 owns the core-model trend claim, but none compute a
general blocker lifecycle, chronic escalation, or numeric anomaly detection
across the full daily-analysis blocker/learning set.

## Design

1. Diff today's blocker/learning set against the prior ledger rows to classify
   each as `new_today`, `persisting` (with `blocker_age_days`), or
   `resolved_today`, and attribute a `recommendation_outcome` when a prior
   recommended action preceded the resolution.
2. Escalate chronic blockers by age (for example P1 to P0 at >= 3 days, flag
   `chronic` at >= 7 days) and surface a "chronic blockers" section in the daily
   learning and flow reports.
3. Add robust day-over-day anomaly detection (median/MAD or step-change) on key
   ledger numerics (label total, corpus market-days, blocker count, candidate
   Brier, taker PnL, snapshot gaps) and emit a learning on a significant adverse
   step that the single-day status logic misses.
4. Persist each day's `decision_record` plus the realized next-day outcome so the
   resolved/regressed history is queryable for meta-learning.
5. Wire the existing loaded ledger into `daily_flow_analysis` (closing the
   dead-load) and add the lifecycle/anomaly outputs to both the JSON and the
   report.

- [ ] Add blocker lifecycle classification (new/persisting/resolved) with
  `blocker_age_days` from ledger history.
- [ ] Add chronic-blocker age escalation and a chronic-blockers report section.
- [ ] Add robust day-over-day anomaly detection on key ledger numerics.
- [ ] Persist decision/outcome history for meta-learning and consume the loaded
  ledger in `daily_flow_analysis`.
- [ ] Add tests with multi-day ledger fixtures covering resolution, chronic
  persistence, and a metric step-change.

Acceptance: the daily analysis classifies every blocker as new/persisting/
resolved with an age, escalates chronic blockers, detects adverse day-over-day
metric step-changes that single-day status misses, and consumes the already-loaded
ledger history instead of dead-loading it, all proven with multi-day fixtures.

Related: items 117, 163, 198, 207, 217, 269, 271.
