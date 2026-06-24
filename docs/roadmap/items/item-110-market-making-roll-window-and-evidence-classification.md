# 110. Market-Making Roll Window And Evidence Classification [COMPLETE 2026-06-17 - EVIDENCE MODE GATE LIVE]

Goal: keep daily market-making rolls from producing misleading zero-quote
evidence when they run after the live target-day tapes have gone stale.

Source: 2026-06-16 settled-day audit. The June 16 daily roll started at
2026-06-17T00:31:18Z and produced `counts_toward_live_forward_gate=false`,
zero quote-permission rows, and only stale-input/no-information-event reasons.
The preflight remediation report grouped 18 incidents across the snapshot/model
loop and CLOB book supervisor.

Why this matters: a post-target-day roll can be useful for diagnostics, but it
should not look like failed live-forward trading evidence. The run needs to
classify whether it is active-day evidence, post-settlement evaluation, or an
operator drill, and the schedule should line up with the evidence type.

## Design

1. Add an explicit evidence mode to each market-making run:
   `active_day_live_forward`, `post_settlement_evaluation`, or
   `operator_drill`.
2. Derive the default evidence mode from target date, market timezone, run
   start time, market close/settlement window, and tape freshness.
3. Move the scheduled daily roll to the last useful active-day window, or split
   it into an active-day roll plus a separate post-settlement evaluation roll.
4. Update `run_summary.json` and markdown reports so zero-quote runs explain
   whether they are non-countable because of stale tapes, timing, platform
   gates, or policy.
5. Add a regression test for the June 16 pattern: after-market run, stale model
   and CLOB tapes, no live-forward credit.

- [x] Add evidence-mode classification to market-making run summaries.
- [x] Add schedule/timing checks for target-day versus post-target-day runs.
- [x] Split or reschedule the daily roll so live-forward credit is attempted
  only during valid active-day windows.
- [x] Make post-settlement evaluation runs opt in and non-countable by design.
- [x] Add regression coverage for stale-tape zero-quote daily rolls.

Acceptance: a daily roll report cannot be mistaken for live-forward evidence
when it actually ran after the target day's tapes were stale.

Completion notes (2026-06-17):
- Added `weather.market.market_making_evidence` with explicit
  `active_day_live_forward`, `post_settlement_evaluation`, and
  `operator_drill` classification.
- Daily roll status now records evidence classification and passes the
  classified mode to the market-making child process.
- `run_summary.json`, `run_config.json`, `preflight.json`, `live_forward_gate.json`,
  and `run_report.md` now explain evidence mode and distinguish raw
  live-forward gate results from evidence-adjusted countability.
- The Windows scheduled-task registration default moved to 19:30 local so
  active-day evidence is attempted before the 20:00 evidence cutoff.
- Regression coverage includes the delayed after-window pattern and verifies
  post-settlement runs are non-countable even when raw data gates pass.

Verification:
- `.\venv\Scripts\python.exe -m pytest -q tests\market\test_market_making_evidence.py tests\operations\test_market_making_daily_roll.py tests\market\test_market_making_run.py tests\operations\test_schema_registry.py`
- `.\venv\Scripts\python.exe -m pytest -q tests\market\test_mm_paper.py tests\market\test_mm_exchange.py tests\app\test_market_making_view.py tests\reporting\test_fleet_observability.py tests\reporting\test_daily_learning.py tests\reporting\test_snapshot_evaluation.py tests\operations\test_import_architecture.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-17 - EVIDENCE MODE GATE LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

