# 258. Maker Active-Day Freshness Recovery And MM Preflight Proof [COMPLETE 2026-06-23 - SELECTED PAPER PROOF PASS]

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

- [x] Define the operator recovery sequence for snapshot, CLOB, and watcher
  freshness.
- [x] Add a preflight proof packet that records all freshness checks before
  rerunning maker sessions.
- [x] Rerun a selected-market maker paper-live-forward session after recovery.
- [x] Verify the live-forward gate counts the run and has no stale blockers.

Acceptance: a post-recovery `market_making_run --mode paper-live-forward
--once` over the selected markets passes preflight, produces countable paper
evidence for every selected market or an explicit fail-closed exclusion, and
writes `preflight.json`, `live_forward_gate.json`, and `run_report.md` showing
no stale model, CLOB, or watcher blockers.

Related: items 57, 157, 210, 211.

## 2026-06-23 Selected-Market Proof

Recovery sequence used for the countable proof:

1. Force fresh snapshot/model rows for the selected markets with
   `weather.collection.snapshot_tracker.capture_snapshot(force=True,
   market_id=...)`.
2. Refresh selected CLOB books with
   `python -m weather.market.market_microstructure capture --market <market>
   --no-price-history --no-websocket-events`.
3. Rerun paper-live-forward maker once the selected model and CLOB timestamps
   are in the same freshness window.

Proof run:

- `data/mm_runs/2026-06-23/item258-selected-20260623T1605/preflight.json`
- `data/mm_runs/2026-06-23/item258-selected-20260623T1605/live_forward_gate.json`
- `data/mm_runs/2026-06-23/item258-selected-20260623T1605/run_report.md`

Result:

- selected markets: `austin`, `chicago`, `dallas`.
- preflight status: `PASS`.
- live-forward gate status: `PASS`.
- counts toward live-forward gate: `true`.
- quote rows: `2`; no-quote rows: `31`.
- preflight remediation incidents: `0`.
- selected-market model-review evidence: `3/3` countable.
- selected-market paper-trading evidence: `3/3` countable.

Earlier same-day attempts documented the blocker and the fix:

- `item258-selected-20260623T1600`: `STALE`, blocked by stale CLOB books.
- `item258-selected-20260623T1603`: `WARN`, CLOB was fresh but Chicago and
  Dallas model rows were stale.
- `item258-selected-20260623T1605`: `PASS`, after targeted model and CLOB
  refresh.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - SELECTED PAPER PROOF PASS`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

