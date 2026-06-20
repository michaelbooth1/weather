# 157. Live-Forward Snapshot Cadence SLO Closure [PARTIAL 2026-06-20 - CADENCE PROOF ADDED, CLEAN ACTIVE DAY PENDING]

Goal: eliminate active-day snapshot cadence gaps so broad live-forward evidence
can count for all selected markets.

Source: the 2026-06-19/2026-06-20 fleet observability audit. The latest
`data/backtest/fleet_observability_report.md` is `CRITICAL` because all 12
markets are `PARTIAL` from snapshot cadence gaps. The broad live-forward SLO
therefore remains `BLOCK` even though the snapshot, CLOB, and
observation-trigger loops are currently running on the latest runtime identity
with zero consecutive errors.

Why this matters: a loop can be alive and still fail the evidence standard.
Promotion and daily learning need a full active day with provable per-market
cadence, not only a current healthy heartbeat after the fact.

## Design

1. Make snapshot cadence gaps a first-class per-market active-day artifact:
   gap count, max gap, start/end times, latest snapshot id, and root cause.
2. Split root causes into process down, stale-code restart, duplicate-writer
   block, long iteration, provider/source delay, disk/backpressure, and unknown.
3. Teach the supervisor or fleet report to distinguish gaps that are recoverable
   same-day from gaps that make the day non-countable.
4. Add a same-day cadence repair checklist that can restart the snapshot loop,
   verify current runtime identity, and rerun fleet observability.
5. Require a fresh active day where `snapshot_coverage_gap` has zero blocked
   markets before broad live-forward evidence is countable.

- [x] Add a per-market snapshot-gap detail table to fleet observability JSON and
  Markdown, including gap windows and root-cause classification.
- [x] Add tests for the June 19 blocked shape: 12 markets blocked by
  `snapshot_coverage_gap` while loops are otherwise running.
- [x] Add a same-day repair command or operator checklist that proves the loop
  is current-code, single-writer, and within cadence after repair.
- [x] Add a "cadence proof" section to daily learning so the broad SLO blocker
  cannot be reduced to only `snapshot_tracker --status`.
- [ ] Collect one future active day with 12/12 markets passing snapshot cadence.

2026-06-20 update: fleet observability now emits `snapshot_cadence_proof`
in JSON and Markdown, and daily learning carries the same proof into the
broad live-forward SLO recovery section. The latest regenerated report still
blocks broad countability: `snapshot_coverage_gap` blocked markets `12`,
total gap count `71`, max gap `28.46` minutes, and root cause
`unknown_snapshot_gap` for all 12 markets. Observed gap windows are marked
non-recoverable for the active day; the repair checklist uses
`python -m weather.collection.snapshot_tracker --restart`, then
`python -m weather.collection.snapshot_tracker --status`, then the fleet
observability rerun to prove current-code, single-writer, zero-gap cadence.

Acceptance: `data/backtest/fleet_observability_report.md` shows
`live_forward_slo` `PASS`, `snapshot_coverage_gap` blocked markets `0`, all
selected markets have max counted gaps within threshold for the active window,
and `daily_learning_report.md` marks broad live-forward evidence countable.

2026-06-20 follow-up: after the snapshot restart, the tracker status was
healthy (`RUNNING`, current runtime identity, fresh heartbeat, zero consecutive
errors). The regenerated fleet reports
`data/backtest/fleet_observability_after_snapshot_restart_report.md` and
`data/backtest/fleet_observability_after_observation_lock_fix_report.md`
still block broad countability because the June 19 gap windows remain
non-recoverable: `snapshot_coverage_gap` blocks all 12 markets, with 71 total
gaps and max gap `28.46` minutes. Loop integrity is now clean, so the next
unblock is not another same-day repair command; it is collecting a future
active day where this section reports zero blocked markets.

2026-06-20 post-resume refresh: the full daily-refresh resume regenerated
`data/backtest/fleet_observability.json` and kept the same live-forward blocker
shape. `live_forward_slo` is still `BLOCK`; snapshot cadence still blocks all
12 markets, with `71` total gaps, max gap `28.46219113333333` minutes, and
`unknown_snapshot_gap` as the root cause for all 12 markets. Source status is no
longer the cadence blocker; the remaining acceptance evidence is a future
active day with zero snapshot-coverage-gap blocked markets.
