# 258. Maker Active-Day Freshness Recovery And MM Preflight Proof [OPEN 2026-06-23 - JUNE 19-22 MAKER RUNS NON-COUNTABLE]

Goal: make active-day freshness recovery for snapshot/model rows, CLOB books,
and observation-trigger state a first-class maker workflow, then rerun
`market_making_run` preflight and require every selected market to produce
countable paper evidence.

Source:
`docs/roadmap/audits/trading-stack-performance-strategy-audit-2026-06-23.md`.
The June 19-22 maker audit found four of five recent maker runs blocked or
degraded by stale model rows, stale CLOB books, stale watcher state, or
non-countable evidence mode. The only clean preflight, June 19
`20260619T040103782099Z`, was an operator drill and still did not count toward
the live-forward gate.

Why this matters: the maker stack cannot be judged as a strategy until the
system reliably produces fresh, countable paper-live-forward evidence. June 22
is the clearest failure case: `12` CLOB-stale markets, `12` watcher-stale
markets, `2` model-stale markets, and zero quote rows.

## Design

1. Add or document a single active-day recovery flow that repairs
   snapshot/model freshness, CLOB book freshness, and observation-trigger
   freshness before maker sessions.
2. Run `weather.collection.snapshot_tracker --status`,
   `weather.market.market_microstructure audit --strict`,
   `weather.operations.observation_trigger status`, and
   `fleet_observability report --strict` as preflight evidence.
3. Rerun `market_making_run --mode paper-live-forward --once` only after the
   freshness checks are clean across the selected markets.
4. Make stale model/CLOB/watcher blockers explicit in `preflight.json`,
   `live_forward_gate.json`, and `run_report.md`.
5. Require every selected market to either produce countable paper evidence or
   have a documented fail-closed exclusion before the run can count.

- [ ] Define the operator recovery sequence for snapshot, CLOB, and watcher
  freshness.
- [ ] Add a preflight proof packet that records all freshness checks before
  rerunning maker sessions.
- [ ] Rerun a selected-market maker paper-live-forward session after recovery.
- [ ] Verify the live-forward gate counts the run and has no stale blockers.

Acceptance: a post-recovery `market_making_run --mode paper-live-forward
--once` over the selected markets passes preflight, produces countable paper
evidence for every selected market or an explicit fail-closed exclusion, and
writes `preflight.json`, `live_forward_gate.json`, and `run_report.md` showing
no stale model, CLOB, or watcher blockers.

Related: items 57, 157, 210, 211.
