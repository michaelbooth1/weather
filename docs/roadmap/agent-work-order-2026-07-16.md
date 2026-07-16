# Agent Work Order — 2026-07-16 (bounded hourly scorer)

Composed by the operations master agent after the July 16 daily chain resumed
past the fixed `taker_edge_permission_map` (streaming reader, 32.6 s) and then
failed honestly at `hourly_model_performance`: its isolated child hit the
3 GiB private-memory Job Object limit (observed 3,222,274,048 bytes, ~1 MB
over) 26 seconds in, with 193 MB of input reads. Containment worked; the step
needs the same bounded rewrite the ten-minute scorer received on 2026-07-13.
Do not raise the cap.

## Prompt

You are working in `c:\Users\micha\Desktop\github\weather` (Windows 11,
PowerShell 5.1, venv at `venv\`). Read `docs/operations/HOST_LOAD_POLICY.md`
first; its constraints apply. Work in a NEW git worktree on branch
`hourly-bounded-2026-07-16` (`git worktree add ..\weather-hourly-bounded
hourly-bounded-2026-07-16` from the repo root), base it on current `master`,
commit only to that branch, and never touch the main worktree, scheduler
tasks, capture loops, release state, or `data/`. Focused tests only, with
`data\logs\memory_commit_guard_status.json` showing commit_percent < 70
before each batch.

### Task — market-day-streaming hourly model performance

`weather/reporting/hourly/hourly_model_performance.py` (driver) currently
accumulates every labeled folder's scored rows (via
`hourly_model_scoring.score_folder`) across the full multi-week corpus before
aggregating. Peak private memory grew with the corpus: ~3,071 MB on July 13
(barely inside the 3 GiB cap), 3,222 MB on July 16 (killed). It will now fail
every scheduled day until bounded.

Rewrite the driver to aggregate market-day by market-day, mirroring the
in-tree reference implementation
`weather/reporting/hourly/ten_minute_model_performance.py` (bounded on
2026-07-13; its regression test proves flat peak memory vs day count):

- Fold each folder's scored rows into the per-hour / per-slot / partition /
  reliability accumulators immediately, then release the rows and the pandas
  frame before opening the next folder. Never retain the full scored-row
  population.
- Preserve output schema, fields, grouping, gate thresholds, checkpoint-row
  semantics (`hourly_checkpoint_rows` first-per-hour selection must produce
  identical results when applied per market-day-band — verify this
  equivalence explicitly: the current implementation selects per
  (market, date, band, hour), which is already market-day-local), and
  countability rules exactly. Schema version bump only if row semantics
  change (they should not).
- Keep the declared 3 GiB private / 2 GiB working-set budget untouched.
- Add a regression test mirroring the ten-minute pattern: synthetic corpora
  at two sizes (e.g. 5 vs 50 market-days) with peak traced memory
  approximately flat.
- Check `candidate_hourly_performance.py` for the same accumulation pattern;
  if it shares the driver, bound it in the same change; if it is a separate
  copy, note it in the report and bound it too if the session allows.

### Verification

`python -m pytest tests/reporting/test_hourly_model_performance.py
tests/reporting/test_ten_minute_model_performance.py -q` (plus any suite
covering files you touched), `python -m compileall -q src tests`, and
`python -m weather.operations.agent_docs_audit`. Record counts.

### Reporting

Write `docs/roadmap/agent-report-2026-07-16.md` in your branch: what changed,
the equivalence argument for checkpoint-row selection, test counts, branch and
commit ids. Do NOT merge or push; the operations master agent audits, merges,
and resumes the daily chain (its persisted resume command starts at
`--resume-from-step hourly_model_performance` with
`--settled-analysis-target-date 2026-07-15`).

---

*Context: the settled-day barrier holds July 15 (and the pending July 12/14
historical completions) non-countable until this step passes. The streak
clock toward the first production candidate does NOT depend on this step —
labels finalize earlier in the chain — but model-skill evidence does.*

*Post-adoption queue owned by the operations master agent (not you):
resume July 15's chain from `hourly_model_performance`; then the July 14
historical completion (all 12 markets have `settlement bucket missing` —
its `public_wu_settlement_restore` never ran because July 15's chain died
early; the freshness repair on 2026-07-16 confirmed local sources absent
while Polymarket winners exist); then the July 12 barrier completion via
its recorded resume commands.*
