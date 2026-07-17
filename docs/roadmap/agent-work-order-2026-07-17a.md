# Agent Work Order — 2026-07-17a (bounded taker finalization watchdog)

Composed by the operations master agent. The bounded-scorer series
(permission map, ten-minute, hourly, maker-paper — all merged and live-proven
by 2026-07-16 evening) exposed one more materializing step, off the happy
path: `taker_finalization_watchdog` fails its resource budget only when the
settled-analysis target date points at the bloated-tape era (~Jul 12-14,
pre-item-322). It passes for current-era corpora (July-15/16 targets, twice
on 2026-07-16).

## Failure receipt (2026-07-17T00:38 UTC run, target 2026-07-14)

- Working-set peak 2,155,540,480 bytes vs 2,147,483,648 cap — killed 7.7 MB
  (0.375%) over.
- Private peak 3,692,261,376 vs 5,368,709,120 cap — 31% headroom remaining.
- Child killed hard mid-flight (no terminal receipt). Elapsed ~16 min of a
  3,600 s timeout.
- Budget rationale string: "target-day cumulative taker tapes plus
  seven-strategy bakeoff and settlement materialization".
- The kill is a working-set excursion while private memory was comfortably
  inside budget — cap geometry meets corpus-sized materialization. The fix is
  bounding the materialization, NOT adjusting either cap. Do not raise caps.

## Prompt

Same repository, isolation, and rules as
`docs/roadmap/agent-work-order-2026-07-16.md` (read it first): NEW worktree
on branch `taker-finalization-bounded-2026-07-17`, based on current `master`,
focused tests under commit_percent < 70, no main-worktree edits, no
scheduler/loop/release/data actions, no merge/push.

### Task — stream taker finalization and bakeoff per run/tape

Locate the step owner via `taker_finalization_watchdog` in
`weather/operations/daily_refresh_trading_steps.py`. The step currently
materializes the target day's cumulative taker tapes for finalization,
seven-strategy bakeoff scoring, and settlement materialization in one address
space. Rewrite to fold one run (or one tape/market-day) at a time into fixed
accumulators or disk-spilled indexes, releasing rows before the next input:

- Use `weather.io.iter_csv_rows` for tape reads wherever row-at-a-time
  consumption is possible.
- Two proven in-tree references:
  `weather/reporting/hourly/hourly_model_aggregation.py` and
  `weather/market/mm_paper_aggregation.py` (the 2026-07-16 rewrites —
  SQLite-spilled row stores, bounded page cache, atomic artifact publish).
- Preserve finalization semantics exactly: SLA behavior, the seven bakeoff
  strategies and their thresholds, settlement materialization outputs,
  countability rules, and output schemas. Schema bump only if row semantics
  change (they should not).
- Budgets stay untouched: 5 GiB private / 2 GiB working set / 3,600 s.
- Regression tests: streaming-vs-materialized equivalence on a synthetic
  multi-run fixture, and traced-memory flatness (few vs many runs, mirroring
  the hourly 5-vs-50 pattern).

### Reporting

`docs/roadmap/agent-report-2026-07-17a.md` in your branch: what changed, the
equivalence argument, test counts, branch/commit ids. Do NOT merge or push.

---

*Context: July-14's settlement truth is already restored (WU restore 12/12
markets, labels finalized 2026-07-16). Only its analysis tail (watchdog →
barrier) waits on this step; the recorded resume command starts at
`--resume-from-step taker_finalization_watchdog` with
`--settled-analysis-target-date 2026-07-14`. The streak clock (day 2 =
July 16, Toronto CLEAN) does not depend on this step.*
