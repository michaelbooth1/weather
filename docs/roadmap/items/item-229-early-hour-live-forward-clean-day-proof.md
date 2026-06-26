# 229. Early-Hour Live-Forward Clean-Day Proof [OPEN 2026-06-25 - CLEAN ACTIVE DAY EVIDENCE REQUIRED]

Goal: collect one clean current-code active day so early-hour model fixes can be
counted as production evidence rather than only backtest evidence.

Source: `docs/roadmap/audits/early-hour-model-performance-audit-2026-06-22.md`.
The audit separates model quality from operations proof: live-forward SLO,
current-code soak, snapshot cadence, fresh CLOB books, and source-status proof
must pass before production claims can count.

Why this matters: a candidate can be valid in replay and still lack usable
live-forward proof if the active-day tapes are incomplete, stale, or collected
under noisy restart conditions. Early-hour promotion needs both model skill and
countable evidence collection.

## Design

1. Use fleet observability as the canonical clean-day proof for snapshot
   cadence, CLOB freshness, source status, loop integrity, and current-code
   soak.
2. Require the active day to have zero `snapshot_coverage_gap` blocked markets
   and current-code soak within restart budgets.
3. Preserve operational blockers separately from model-skill blockers in
   promotion refresh and daily learning.
4. Add an early-hour proof section that shows whether the clean day includes
   enough 00:00-08:00 snapshots for the relevant markets.
5. Keep failed days non-countable while still retaining them for diagnostics.

- [ ] Rerun fleet observability after the next active window completes with
  current-code loops left running through restart-budget aging.
- [x] Add early-hour coverage counts to the clean-day proof.
- [x] Surface clean-day countability in promotion refresh, daily learning, and
  progress audit.
- [ ] Record the first clean active day that passes snapshot cadence, CLOB
  freshness, source status, and current-code soak.

Acceptance: `fleet_observability_report.md` shows live-forward SLO `PASS`,
`snapshot_coverage_gap` blocked markets `0`, fresh CLOB/source-status proof,
current-code soak `PASS`, and downstream promotion/daily-learning reports mark
the day countable for early-hour evidence without masking model-skill blockers.

Related: items 157, 161, 210, 212, 227.

## 2026-06-25 Clean-Day Proof Refresh

Fleet observability now runs quickly enough to serve as the clean-day proof
again, but the refreshed `data/backtest/fleet_observability.json` generated at
`2026-06-25T18:47:03Z` does not count for this item.

Current blocker cascade:

- `live_forward_slo=BLOCK` and `current_code_soak=BLOCK`.
- All 12 markets have nonrecoverable `snapshot_coverage_gap` evidence for
  June 25, with `max_gap_minutes=223.57417106666665`.
- Snapshot and CLOB are current and running after restart, but their 24-hour
  restart budgets do not age under threshold until June 26 UTC.
- The report's next unblock action is explicitly a future clean active day:
  `collect next active day with zero snapshot_coverage_gap blocked markets`.

No early-hour production proof should be counted from June 25. Keep this item
open until the next active day passes both live-forward cadence and current-code
soak.

## 2026-06-26 Implementation Wiring Refresh

Fleet observability now emits a strict `clean_active_day_countability` object
with 00:00-08:00 local early-hour coverage counts. Promotion refresh consumes
that object in `early_hour_promotion_blocker`, and daily learning plus progress
audit now surface the same countability state instead of inferring it from broad
live-forward status alone.

This does not close the item: the first actual clean active day still needs to
be collected and recorded after snapshot cadence, CLOB freshness, source status,
current-code soak, and early-hour coverage all pass.
