# Agent report 2026-09-110v Part 2 — incremental Stage A

**PASS on fixture verification; production timing and roll-free qualification
remain to be measured by the production owner.**

Answers Part 2 of `workstation-handoff-2026-09-110v-efficiency-fixes.md` at
`795e87d6` on `origin/codex/handoff-110k-20260926`. Open questions: none.
Branch `codex/stage-a-incremental-20260927`, implementation `93642398`, base
`e3bc4dc8` on `origin/codex/integration-91a-110f-20260926`. Resolve full hashes
with `git rev-parse`; the draft PR declares this integration dependency until
master adoption. No Part 1 dependency or copied implementation.

## Result

- Hourly and ten-minute scoring share a per-folder JSON row cache, keyed by
  input path/size/nanosecond mtime, scorer schema, source signatures, label and
  thresholds. Features are included; payload corruption invalidates reuse.
  Cold and warm results preserve the scorer's rows and report aggregation.
- Replay-status backfill returns its exact existing-status response without
  parsing unchanged evidence. Changed inputs regenerate status. The default
  automatic window is seven target dates before/as of the requested date;
  explicit folders or `--recent-days 0` allow historical work. CSV line counts
  scan bytes, falling back to logical CSV parsing for quoted/multiline fields.
- Stage-A labels revisit recent or unlabeled folders, retain historical
  authoritative labels, verify ledger integrity before reuse, load each daily
  summary once, and preserve unprocessed CSV rows. Matched closed venue
  evidence goes through the existing reconciliation function again with the
  current local settlement; a changed bucket can mismatch. Unresolved labels
  take the ordinary reconciliation path. The settlement implementation and
  promotion gates were not modified.

The window is configurable by `--stage-a-recent-days`; zero or explicit folders
revisits history. Rebuildable caches are optional accelerators, not evidence.
Current finalization timestamps remain current for revisited folders; old
labels retain their original timestamps. No fresh venue read is claimed when
terminal venue evidence is reused.

## Verification and expected saving

The expanded fixture run passed **258 tests and 17 subtests**, including daily
refresh integration and repo-wide audits on every focused run. Repository
compileall and whitespace checks passed. Fixtures prove full/cold/warm hourly
and ten-minute report equality apart from generation timestamps; row equality;
label, feature, threshold, source/schema and corruption invalidation; exact
replay existing-status response equality; no repeated scoring or replay
parsing on a warm hit; label parity with a fixed clock; retained venue mismatch
handling; and one daily-summary read across folders.

Expected warm-run saving is **roughly 60–75 minutes per daily Stage A**, a
planning estimate from the supplied production audit, not a measured host
result. The audit attributes about 75 minutes overall to repeated historical
work (its individual 34/26/22-minute components overlap). Scoring-cache hits
remove repeated CSV scoring but not aggregation, recent labels still finalize,
and unresolved venue checks remain. First-run cache construction saves less;
production should use Part 6 profiling to establish actual minutes. These are
engineering fixtures, so market/date clusters and inferential intervals do
not apply.

## Reproduction

From the branch root, use the workstation wrapper from
[development](../development.md#separate-non-capture-workstation), with the
absolute approved project Python and root paths and base64-encoded JSON args:

```text
-m pytest -q
tests/reporting/test_stage_a_scored_cache.py
tests/operations/test_stage_a_incremental.py
tests/reporting/test_hourly_model_performance.py
tests/reporting/test_ten_minute_model_performance.py
tests/operations/test_replay_status_backfill.py
tests/market/test_market_day_labels.py
tests/operations/test_daily_refresh.py
tests/operations/test_agent_docs_audit.py
tests/operations/test_schema_registry.py
tests/operations/test_module_size_audit.py
tests/operations/test_import_architecture.py
tests/operations/test_path_policy.py
tests/operations/test_knowledge_structure_audit.py
tests/reporting/test_roadmap_backlog.py
--basetemp=<absolute-task-owned-temp-directory>
```

Compile args: `-m compileall -q app src tests`. Regenerate correspondence after
committing this report with `python -m weather.reporting.roadmap.correspondence_index`.
Capture qualification uses its admitted bounded suite, not direct pytest.

## Roll handback and boundaries

Local `scripts/ops/roll_verdict.ps1 -Branch codex/stage-a-incremental-20260927
-Base origin/codex/integration-91a-110f-20260926` returned **UNDECIDABLE**:
the fixture worktree has no retained live closures. The handoff intends a
roll-free Stage-A change; production must establish that mechanically before
adoption. No live closure membership is invented here.

| File | Per-file disposition |
| --- | --- |
| `src/weather/reporting/hourly/hourly_model_scoring.py` | Scoring owner; production closure verdict required. |
| `src/weather/reporting/hourly/scored_folder_cache.py` | New scoring helper; adopted with its importer. |
| `src/weather/operations/replay_status_backfill.py` | Offline backfill; production closure verdict required. |
| `src/weather/operations/stage_a_settlement.py` | New Stage-A helper; adopted with its importer. |
| `src/weather/operations/daily_refresh_source_steps.py` | Stage-A wiring; production closure verdict required. |
| `src/weather/operations/daily_refresh_trading_steps.py` | Stage-A wiring; production closure verdict required. |
| `src/weather/operations/daily_refresh_cli.py` | Stage-A CLI; production closure verdict required. |
| `tests/operations/test_stage_a_incremental.py` | Fixtures only; no live membership claimed. |
| `tests/reporting/test_stage_a_scored_cache.py` | Fixtures only; no live membership claimed. |
| `docs/operations/OPERATIONS_DESIGN.md` | Roll-free documentation. |
| This report and correspondence index | Roll-free documentation. |

No schema-registry change, registration, production data read/write, mirror
access, credential access, venue call, restart, merge, model fitting, release
promotion or live trading. Origin fetch/push and authorized draft PR creation
are the only network actions. Caches and outputs in verification use fixtures.
