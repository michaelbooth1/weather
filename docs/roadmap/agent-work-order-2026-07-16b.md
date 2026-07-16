# Agent Work Order — 2026-07-16b (bounded maker-paper scorer)

Composed by the operations master agent. This is the LAST unbounded scorer on
the scheduled settlement chain: permission map (streamed 2026-07-16, ok in
32.6 s), ten-minute (bounded 2026-07-13), and hourly (bounded 2026-07-16, ok
at 1,520 MB vs a 3 GiB cap) are done. `maker_paper_score` now fails its 4 GiB
private cap after passing input preflight: 11 selected maker runs (~440 MB of
quote + variant CSV) inflated past 4,096 MB during load/scoring — the familiar
~9-10x list-of-dicts/frame inflation. Containment worked; do not raise either
the 512 MiB input cap or the 4 GiB private cap.

## Prompt

Same repository, isolation, and rules as
`docs/roadmap/agent-work-order-2026-07-16.md` (read it first): NEW worktree on
branch `maker-bounded-2026-07-16`, based on current `master`, focused tests
under commit_percent < 70, no main-worktree edits, no scheduler/loop/release/
data actions, no merge/push.

### Task — stream maker-paper scoring per run

`maker_paper_score` (owner around `weather.market` / the daily-refresh trading
step; locate via `run_maker_paper_score_step` in
`weather/operations/daily_refresh_trading_steps.py`) currently materializes
the selected maker runs' quote/variant CSVs and scores them in one address
space. Rewrite to fold one run (or one market-day within a run) at a time into
fixed accumulators, releasing each run's rows before opening the next —
mirroring `weather/reporting/hourly/hourly_model_aggregation.py` (the
2026-07-16 reference) and the ten-minute rewrite:

- Use `weather.io.iter_csv_rows` (streaming, legacy-encoding fallback) for
  tape reads wherever row-at-a-time consumption is possible.
- Preserve output schema/fields, evidence-window semantics (latest-N
  active-day run selection with recorded selected inputs), gate thresholds,
  and countability rules exactly. The input-byte preflight stays as a
  fail-closed guard; the declared budgets stay at 512 MiB input / 4 GiB
  private / 3 GiB working set.
- If exact per-run scoring requires cross-run state (e.g. dedupe or
  benchmark joins), keep that state as bounded aggregates or a disk-spilled
  index (the hourly rewrite's SQLite pattern), never as retained row lists.
- Regression tests: streaming-vs-materialized output equivalence on a
  synthetic multi-run fixture, and a traced-memory flatness test (few runs vs
  many runs, mirroring the hourly 5-vs-50 pattern).

### Reporting

`docs/roadmap/agent-report-2026-07-16b.md` in your branch: what changed, the
equivalence argument, test counts, branch/commit ids. The operations master
agent merges and then reruns the barrier resumes.

---

*Context: the settled-day barrier holds July 15 (and the queued July 14/12
historical completions) non-countable until this step passes with the
standard 14-run window. Interim runs used an 11-run window override; restore
default-window behavior after the rewrite. The streak clock toward the first
production candidate (day 2 = July 16 in progress; lockable ~July 29) does
not depend on this step.*
