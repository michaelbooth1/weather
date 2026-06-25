# 272. Taker Daily-Roll Liveness And Artifact Restart [COMPLETE 2026-06-23]

Goal: make the taker daily roll fail and restart on useful tape inactivity, not
on process existence.

Source: the June 21-23 taker log audit found `daily_roll_status.json` reporting
an alive PID while useful tape activity was stale, and
`data/taker_runs/2026-06-23/taker-20260623-124b5e18/` existed without usable
artifacts. The same audit found the current smoke run dominated by stale-book
blocks, so data collection can appear alive while producing little or no
learning signal.

Why this matters: the fastest way to collect taker evidence is to keep the loop
writing fresh candidate/fill rows. A PID-only health check lets the system burn
calendar days without producing settlement-scoreable data.

## Design

1. Promote useful tape writes to the primary liveness signal: `orders_long.csv`,
   `budget_ledger.jsonl`, `daily_pnl.json`, `strategy_summary.json`, and
   heartbeat metadata must refresh inside the configured cadence window.
2. Treat empty run folders, missing `orders_long.csv`, and stale strategy
   summaries as restartable failures.
3. Add a daily-roll status root-cause class that distinguishes stale PID,
   stale book input, stale model input, empty artifact folder, and no-edge
   policy idle.
4. Make `--force` relaunches retire or quarantine the previous empty/stale run
   folder so the next run cannot inherit a misleading run id.
5. Add a compact operator report showing last useful write time, latest
   candidate rows, latest fill count, and restart recommendation.

- [x] Fail daily-roll liveness on stale useful tape writes, not only dead PID.
- [x] Quarantine empty or artifact-incomplete run folders before relaunch.
- [x] Add root-cause classes for stale PID, stale book, stale model, empty
  artifacts, and policy no-edge.
- [x] Add tests for idle alive-PID, empty-folder, and stale-artifact restart
  paths.

Acceptance: a taker loop that is alive but not writing current candidate or
strategy artifacts is marked restart-required, and the next forced launch
cannot silently reuse or mask the stale/empty run state.

Completion evidence (2026-06-23):

- `taker_bot_daily_roll` now ignores console-log writes for taker activity
  liveness and only considers useful run artifacts.
- Latest-run artifact health now fails on no run folder, empty run folder,
  missing `orders_long.csv`, missing/stale heartbeat metadata, missing/stale
  strategy summary, stale book input, and stale model input.
- Policy no-edge idle is classified separately and does not recommend restart.
- Forced same-day relaunch quarantines the latest unhealthy run folder under
  `_quarantine` before starting the next process.
- Operator status now reports latest run folder, latest useful write, candidate
  rows, fill count, top skip reasons, and restart recommendation.
- Live status check against the current taker daily-roll state classified the
  active stale run as `idle_process` with
  `root_cause_class=empty_run_artifact_folder`, `first_failing_gate=artifact_liveness`,
  and `restart_recommended=true`.

Validation:

- `python -m pytest tests\operations\test_taker_bot_daily_roll.py -q`
- `python -m pytest tests\operations\test_taker_bot_daily_roll.py tests\reporting\test_roadmap_backlog.py -q`
- `python -m py_compile src\weather\operations\taker_bot_daily_roll.py`

Related: items 161, 239, 256.

## 2026-06-24 Follow-Up Gap

The 2026-06-24 taker audit found a narrower blind spot that should not reopen
this completed item directly. The taker daily roll could show an alive process
and useful-artifact liveness `PASS` while the current run had
`latest tick rows=0`, zero-trade root cause `crashed_before_scoring`, and dead
upstream snapshot/CLOB dependencies. Item 311 now owns that pre-settlement
latest-tick/evidence-starvation gate.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.
