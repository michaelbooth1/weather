# Agent Report — 2026-07-13c Release Bootstrap

## Isolation And Branch

- Worktree: `C:\Users\micha\Desktop\github\weather-release-bootstrap`
- Branch: `release-bootstrap-2026-07-13`
- Base: `665ed2aabea2cec75e53789a97f7b8d0fe3aef6a`
- The dirty main worktree was not edited, staged, committed, reset, merged, or
  otherwise changed. This branch was not pushed or merged.
- No scheduler registration, loop control, real retrain, release promotion,
  active-pointer mutation, evidence deletion, or live trading action ran.

## Task Status

### Task 1 — bounded ten-minute scorecard: complete

Commit: `a9b74d542e2d990d533757d33ed0c9dab8d0c6cd`

The scorer now reads and aggregates one market-day at a time instead of
materializing the multi-week checkpoint population. Output fields, grouping,
gate thresholds, and countability rules are preserved. The regression compares
small and much larger synthetic histories and proves retained/peak Python
memory remains approximately flat with day count. Item 324 records that the
2026-07-12 settled-day analysis should continue through the barrier's recorded
resume commands after adoption.

### Task 2 — nightly production point-in-time integration: complete in software

Commit: `de0bf1b08ac0f71269423bf2fdafbf8017ec74a2`

`nightly_retrain` still defaults to `research_only`. Explicit `production`
mode now prelocks a candidate-independent bounded population and writes these
four candidate-local immutable roles:

- point-in-time Parquet corpus;
- materialization manifest;
- nested rolling validation plan;
- streaming locked evaluation.

The production pooled trainer emits chained, self-hashed receipts for feature
selection, scaling/imputation, model, calibration, postprocessing, and routing
for every outer and inner scope, plus a final-refit receipt bound to the exact
serialized serving bundle. The currently served calibration/postprocessing
policies are identity-disabled and routing is a predeclared single route, so
their receipts execute and bind the real canonical transforms without claiming
nonexistent learned parameters.

The most recent contiguous 14-day window is locked before selection. Candidate
verification rejects locked-date reuse, any selection date outside the exact
immutable universe, source/replay mutation after prelock, and a fresh report
over a stale or future target window. The latest target may be at most seven
days old. Family/market secondary artifacts are candidate-confined, content-
addressed, complete across all required scopes, and copied as release roles.
Candidate and immutable-release verification cross-check the exact model,
family outputs, normalized route, training graph, selection bindings, and PIT
role identities.

Replay/materialization uses an explicit market-day batch handoff: the writer
flushes and releases one day before the producer scores the next. Canonical row
hashing is incremental and Arrow writes are capped at 65,536 rows. Raw training
inputs are read one day at a time; the non-incremental HGB's retained normalized
population is declared honestly and separately capped at 60 × 1,000 source
rows under a 4 GiB private-memory declaration.

This closes the requested integration, not the operational evidence boxes. No
real production retrain, retained production corpus, scheduled locked window,
or candidate was created. Item 321 leaves those evidence boxes open for the
scheduled production-mode run.

### Task 3 — one-command rollback drill readiness: complete in software

Commit: `e15c8897106c76bdc4d25b2efad8ac40c97ccfeb`

The lifecycle `rollback` command verifies the recorded prior immutable
release, journals intent, atomically replaces the pointer, re-reads and emits
the post-rollback release identity, and writes
`data/backtest/release_rollback_drill.json`. The record includes target,
timing, pointer/manifest identities, and structured pending manual worker-
restart and post-restart health fields. An interrupted post-pointer record
write is recoverable by rerunning the same command without toggling back.

The Phase 1 roadmap checkbox correctly remains open until a real release exists
and operators complete the coordinated restart and health drill.

### Task 4 — isolated experiment executor: skipped cleanly

Tasks 1–3 and adversarial Task 2 hardening consumed the session. No executor
files or partial skeleton remain.

## Focused Verification

Every pytest batch first read the main-worktree
`data/logs/memory_commit_guard_status.json` and ran only while
`commit_percent < 70`. The final observed value was 53.8% at
2026-07-13 18:55:01 -04:00.

- `tests/reporting/test_ten_minute_model_performance.py`: **5 passed**.
- `tests/calibration/test_pooled_candidate_replay_streaming.py`: **6 passed,
  3 subtests passed**.
- `tests/calibration/test_family_secondary_artifacts.py` plus
  `tests/reporting/test_location_trust.py`: **24 passed**.
- Production pooled/preselection selectors plus
  `tests/calibration/test_pooled_feature_preselection_exclusion.py`: **7
  passed**.
- Production selection/freshness/resource selectors in
  `tests/reporting/test_point_in_time_evaluation.py`: **4 passed**.
- Production candidate subset of
  `tests/operations/test_release_candidate_contract.py`: **22 passed, 16
  deselected**.
- Production synthetic retrain and unchanged research default in
  `tests/operations/test_nightly_retrain.py`: **2 passed, 32 deselected**.
- `tests/operations/test_schema_registry.py`: **7 passed**.
- `tests/operations/test_release_lifecycle.py`: **14 passed**.
- `python -m compileall -q app src tests`: **PASS** before the Task 2 commit.
- `python -m weather.operations.agent_docs_audit`: **PASS** (18 agent files,
  431 Markdown files).
- `git diff --check`: **PASS**.

No full suite or heavy replay was run on the live-capture host.

## Morning Merge Notes

Merge or cherry-pick only after the operations automation's adoption commit is
present and its conflicts have been reviewed. The branch commit order is:

1. `a9b74d542e2d990d533757d33ed0c9dab8d0c6cd` — bounded scorer;
2. `e15c8897106c76bdc4d25b2efad8ac40c97ccfeb` — rollback readiness;
3. `de0bf1b08ac0f71269423bf2fdafbf8017ec74a2` — production PIT integration.

README, the nightly runbook, and Item 321 are intentionally touched by more
than one commit; preserve the final branch versions when resolving any morning
documentation conflict. After adoption, Item 324 can use its recorded barrier
resume commands. The first real production-mode nightly run should be observed
for the new 1,000-source-row/day trainer cap and must remain candidate-only;
do not close the operational evidence boxes until its retained artifacts and
locked evaluation are reviewed.
