# 210. Market-Maker Stale-Input Blackout Routing And Active-Day Evidence SLA [COMPLETE 2026-06-21 - CRITICAL SLA ROUTES LOST ACTIVE DAYS TO 161/157]

Goal: route the market-maker active-day stale-input blackout to a real
remediation owner and define an MM evidence-starvation SLA, so the MM track has
a visible path to countable paper-trading evidence instead of silently producing
zero on lost days.

Source: the settled 2026-06-20 log audit and the auto-generated
`data/backtest/settled_day_root_cause_2026-06-20.*`. The 06-20 MM run
(`20260620T233005288278Z`) was preflight `STALE` for all 12 markets (current
model snapshot stale; last CLOB book capture up to `10,260s` / ~2.85h old;
observation watcher stale), posted `0` fills, accumulated `66`
blocked-by-preflight legs, and reported `counts_toward_live_forward=false`,
i.e. **zero countable paper-trading market-days on an active trading day**. The
new root-cause report detects this as `MM_PREFLIGHT_STALE_BOOKS`, but its
roadmap mapping points the issue at **item 198 (the report module itself)**
rather than at a remediation owner.

Why this matters: the market-maker bot is the project end-goal. The
producer-side cause is loop-cadence staleness (item 161 soak `BLOCK`, ~1,226
restarts in the soak window) and snapshot cadence (item 157), but no item owns
the **consumer-side outcome**: the MM bot keeps getting zero countable evidence
on active days. If the only routing target is the report that detected the
blackout, the blackout recurs with no owner and the MM live-forward gates can
never accumulate the sample they require.

## Design

1. Fix the routing: map `MM_PREFLIGHT_STALE_BOOKS` and the underlying
   `model_freshness` / `clob_freshness` / `observation_trigger` MM preflight
   failures to remediation owners **161** (loop-cadence soak) and **157**
   (snapshot cadence SLO), not to the report module. Coordinate with item 207
   ("issues can map only to completed items").
2. Define an MM active-day evidence-starvation SLA: when MM preflight blocks
   more than a threshold fraction of an active trading day, raise a `CRITICAL`
   naming the exact stale loop, its age, and the recovery owner/command.
3. Surface the MM countable-paper-market-day count and the consecutive
   starved-active-day streak in fleet observability and daily progress, so a
   recurring blackout shows up as a trend instead of a single buried preflight
   line.
4. Document the remediation boundary explicitly: producer-side reliability
   stays with items 161/157; this item owns detection, correct routing, the
   starvation SLA, and the consumer-side evidence trend.

- [x] Add MM preflight-staleness issues to the issue-to-owner routing table
  with owners 161/157.
- [x] Implement the MM active-day evidence-starvation SLA and CRITICAL alert.
- [x] Surface MM countable-paper streak in fleet observability and daily
  progress.
- [x] Add a test from the 06-20 all-stale MM run fixture (0 countable markets).

Acceptance: the MM stale-input blackout routes to 161/157 (not the report), the
MM evidence-starvation SLA fires with the correct owner when an active day is
lost, and fleet/daily-progress track the MM countable-paper streak so the
blackout cannot recur unowned.

Related: items 161, 157, 207, 198, 44, 67, 152.

Completion notes (2026-06-21):

- `MM_PREFLIGHT_STALE_BOOKS` routing stays on active remediation owners
  210/161/157 and explicitly excludes item 198 as an owner for the recurrence.
- MM preflight remediation incidents now carry `roadmap_owner_items` for stale
  `model_freshness`, `clob_freshness`, and `observation_trigger` gates.
- Added `mm_evidence_starvation_v0.1` summarization over active-day MM run
  history. Lost active days now emit a CRITICAL alert naming the stale loop,
  stale age, owner items, and recovery command.
- Fleet observability and daily progress now expose MM countable paper
  market-days, starved active-day count/streak, latest blocked fraction, and
  recovery owner items.
- Regenerated `data/backtest/fleet_observability.json`,
  `data/backtest/fleet_observability_report.md`,
  `data/backtest/daily_progress_latest.json`, and
  `data/backtest/daily_progress_ledger_report.md`. The 2026-06-20 lost active
  day now reports `model_freshness` age `11399.0s`, owners `161,157`, and
  `12/12` markets blocked by stale preflight.
- Verified with:
  `python -m pytest tests\reporting\test_fleet_observability.py tests\reporting\test_daily_progress_ledger.py tests\reporting\test_settled_day_root_cause.py tests\market\test_market_making_run.py tests\market\test_mm_paper.py tests\operations\test_schema_registry.py -q`.
