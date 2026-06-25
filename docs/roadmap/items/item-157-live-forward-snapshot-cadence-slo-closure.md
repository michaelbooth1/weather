# 157. Live-Forward Snapshot Cadence SLO Closure [PARTIAL 2026-06-25 - JUNE 25 CADENCE BLOCKED, CLEAN DAY NEEDED]

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

2026-06-22 active-day closure refresh: fleet observability now reports whether
snapshot cadence blockers are same-day recoverable or require a clean future
day. The regenerated `snapshot_cadence_proof.summary` is still `BLOCK`: all 12
markets are nonrecoverable active-day blockers, total gap count is `54`, max
gap is `22.137341816666666` minutes, and the explicit next unblock action is
`collect next active day with zero snapshot_coverage_gap blocked markets`.
`recoverable_same_day_market_count` is `0`, so another restart/status rerun
cannot make this active day countable.

2026-06-22 maintenance refresh: after repairing malformed loop console logs and
restarting the managed loops on current source, fleet observability shows loop
artifact integrity `OK` with malformed lines `0` and duplicate writers `0`.
The live-forward SLO remains `BLOCK`, but the blocker is now cleanly the
nonrecoverable active-day cadence evidence: `snapshot_coverage_gap` still
blocks all 12 markets, with `54` total gaps, max gap
`22.137341816666666` minutes, `recoverable_same_day_market_count=0`, and
`nonrecoverable_active_day_blocked_market_count=12`. The next unblock action
remains `collect next active day with zero snapshot_coverage_gap blocked
markets`; another same-day restart cannot make the current active day
countable.

2026-06-22 midnight refresh: the regenerated
`data/backtest/fleet_observability.json` at `2026-06-22T04:20:04Z` shows the
new current-code loops are healthy and source/source-status freshness gates are
passing, but the broad live-forward SLO still cannot count. The target cadence
window remains the June 21 active day, and `snapshot_coverage_gap` blocks `8`
markets with nonrecoverable gaps: austin `1` gap max `19` minutes, chicago `6`
max `20`, dallas `4` max `20`, denver `5` max `22`, houston `7` max `20`,
los-angeles `3` max `20`, san-francisco `6` max `20`, and seattle `3` max `18`.
`recoverable_same_day_market_count=0`; another same-day restart cannot make the
June 21 window countable. The useful action is to keep collecting the June 22
active day on the current source and rerun fleet observability after the active
window has enough coverage to prove zero blocked snapshot-coverage-gap markets.

## 2026-06-24 Taker-Run Cadence Evidence

The 2026-06-24 taker audit added another non-countable active-day cadence
example. The regular snapshot loop was `DEAD` at review time, with the child
having exited on stale-code identity around 14:07 EDT and the latest taker
snapshot rows stopping around 13:58 EDT. `snapshot_tracker --status` reported
all 12 active markets as `PARTIAL/BLOCK`, with max same-day gaps around 142
minutes.

This does not change the design of the item, but it updates the current
blocker: the next acceptable evidence is still a fresh active day where all
selected markets pass snapshot cadence. The 2026-06-24 taker run should not
count as strategy-quality evidence because its late-day scoring tape was
starved by snapshot cadence failure.

## 2026-06-25 Cadence Evidence

The refreshed canonical fleet observability proof generated at
`2026-06-25T18:47:03Z` is runnable but still blocks the live-forward cadence SLO.
`live_forward_slo=BLOCK`, `counts_toward_live_forward_gate=False`, and the first
blocker is `snapshot_coverage_gap` for Toronto.

Snapshot cadence summary:

- `blocked_market_count=12`
- `snapshot_coverage_gap_blocked_market_count=12`
- `total_gap_count=12`
- `max_gap_minutes=223.57417106666665`
- `active_day_countable_market_count=0`
- `clean_active_day_required=True`
- `next_unblock_action=collect next active day with zero snapshot_coverage_gap blocked markets`

The snapshot loop was restarted onto current code and resumed fresh captures,
but the 11:00-14:44 local gap range is nonrecoverable for June 25. This item
remains partial until a future active day reports zero snapshot coverage gap
blocked markets.
