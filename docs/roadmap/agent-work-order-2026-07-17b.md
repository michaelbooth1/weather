# Agent Work Order — 2026-07-17b (bounded taker tail casebook)

Composed by the operations master agent. The bounded watchdog (work order
17a, merged 026bdb57) is live-proven on the July-14 bloated-era corpus:
private 1,403 MB vs the old 3,692 MB, working set 224 MB vs the old
2,155 MB kill. The July-14 analysis tail then advanced one step and found
the next materializer: `taker_tail_casebook` was budget-killed 268 KB
(0.013%) over its 2 GiB private cap in 46 seconds.

## Failure receipt (2026-07-17T03:04 UTC run, target 2026-07-14)

- Private peak 2,147,758,080 bytes vs 2,147,483,648 cap.
- Working set 840,769,536 vs 1,610,612,736 cap — comfortable.
- Budget rationale: "multi-run taker evidence scan"; 1,800 s timeout.
- Passes on current-era corpora (ran ok for the July-15/16 targets four
  times on 2026-07-16). Only bloated-era (~Jul 12-14) taker tapes breach.
- Do not raise either cap.

## Prompt

Same repository, isolation, and rules as
`docs/roadmap/agent-work-order-2026-07-16.md` (read it first): NEW worktree
on branch `taker-tail-casebook-bounded-2026-07-17`, based on current
`master`, focused tests under commit_percent < 70, no main-worktree edits,
no scheduler/loop/release/data actions, no merge/push.

### Task — stream the taker tail casebook scan

Locate the step owner via `taker_tail_casebook` in
`weather/operations/daily_refresh_trading_steps.py`. The step scans
multi-run taker evidence (order tapes / scored rows) for tail cases and
currently materializes the scan in one address space. Rewrite to fold one
run (or one tape) at a time into fixed accumulators or a disk-spilled
index, releasing rows before the next input:

- `weather.io.iter_csv_rows` for tape reads; three proven in-tree
  references: `weather/market/taker_bot_aggregation.py` (17a),
  `weather/market/mm_paper_aggregation.py` (16b),
  `weather/reporting/hourly/hourly_model_aggregation.py` (16).
- If casebook selection needs global ordering or top-N tail selection
  across runs, keep it as a bounded heap or SQLite-spilled index — never a
  retained row population.
- Preserve casebook output schema, case-selection semantics, evidence-window
  rules, and countability exactly. Budgets stay 2 GiB private / 1.5 GiB
  working set / 1,800 s.
- Regression tests: streaming-vs-materialized casebook equivalence on a
  synthetic multi-run fixture; traced-memory flatness (few vs many runs).

### While you are in there

Survey (do not rewrite) the remaining settlement-chain steps that consume
target-day taker or variant tapes — `price_free_model_learning`,
`model_market_disagreement_rehydration`, `live_variant_settlement_scorecard`
— and report which ones still materialize whole-corpus row lists. One
paragraph each in the report; that survey scopes any 17c.

### Reporting

`docs/roadmap/agent-report-2026-07-17b.md` in your branch: what changed,
the equivalence argument, test counts, the materialization survey, branch/
commit ids. Do NOT merge or push.

---

*Context: July-14's settlement truth is restored and its watchdog evidence
is now complete; the recorded resume for its analysis tail starts at
`--resume-from-step taker_tail_casebook` with
`--settled-analysis-target-date 2026-07-14`. July-12's full-chain
completion queues behind the same step. The streak clock (Toronto day 2 =
July 16 CLEAN) does not depend on this.*
