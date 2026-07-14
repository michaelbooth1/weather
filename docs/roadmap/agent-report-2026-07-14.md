# Agent Report - 2026-07-14

Branch: `evidence-plumbing-2026-07-14`

Isolated worktree:
`C:\Users\micha\Desktop\github\weather-evidence-plumbing-2026-07-14`

Base: current `master` at
`7269ffab59dbcbb397a2a162e7295dbb6556c8ae`.

This run did not start or signal collection loops, run a scheduler or
registration action, promote a release, run a migration, access a network
collector, enable live trading, or modify runtime tapes, ledgers, active
release state, or the main worktree. Verification used synthetic releases and
temporary directories only.

## Task 1 - captured-input parity evidence generator

Status: **COMPLETE**.

Commit: `f658ec77` (`Add release-bound captured-input parity evidence`).

- Added the bounded one-market-day command
  `python -m weather.reporting.scorecards.captured_input_parity_evidence`.
- Required a runtime-verified active release, exact serving-role binding,
  stable active pointer, base-model binding, market route, release identity,
  serving fingerprint, and fresh self-hashed captured inputs before replay.
- Rebuilt replay rows through the verified base and variant serving bundle.
  Served rows are independently sliced from the canonical live variant tape;
  served probabilities are never used to construct replay probabilities.
- Wrote stable per-market JSON evidence under
  `data/backtest/captured_input_parity/<market>/`. Each side is atomically
  replaced, self-hashed, row-set hashed, peer-bound, and stamped with release
  ID, manifest SHA-256, pointer identity, sequence, serving fingerprint,
  market/date coverage, source hashes, and declared bounds.
- Made the canonical comparator authenticate the envelope and exact row
  metadata. Self-hashed generation time is the primary 48-hour freshness
  proof, with file mtime retained as a secondary check; served and replay pair
  timestamps must agree.
- Declared a 768 MiB default process ceiling, a 256-2048 MiB reviewed range,
  byte/row/band limits, and an exact one-market-day scope suitable for the
  15.7 GiB host.
- Added fail-closed coverage for absent/invalid release state, stale or missing
  inputs, release/fingerprint drift, source mutation, incomplete coverage,
  metadata mismatch, tampering, output collision, and active-pointer/release
  store protection.

## Task 2 - registration-parameter emitter

Status: **COMPLETE**.

Commit: `45c716b9` (`Emit verified task registration parameters`).

- Added the read-only command
  `python -m weather.reporting.serving_gates.registration_parameters`.
- Resolves and verifies the active release twice, derives the exact declared
  serving `ROLE=PATH` inventory and route path, and requires one existing
  stable parity pair for every promoted or shadow-routed market.
- Emits structured JSON plus ready-to-run PowerShell blocks for
  `register_daily_refresh.ps1` and `register_nightly_retrain.ps1` using the
  scripts' exact parameter names.
- Fails closed for missing/corrupt release state, pointer drift, incomplete or
  mismatched serving roles, a missing route, invalid route decisions, and
  missing parity evidence.

The command was tested only as a read-only renderer. Neither registration
script was invoked.

## Task 3 - isolated experiment executor

Status: **COMPLETE** within the repository's trusted Python experiment-module
boundary.

Commit: `d332dd7f` (`Add bounded isolated experiment executor`).

- Added the deliberate, unscheduled command
  `python -m weather.operations.experiment_executor` for exactly one verified
  `executable_experiment_manifest` queue entry.
- Re-verifies the queue/manifest/release, admits only the 01:00-08:30 Toronto
  quiet window, requires commit below 70%, reserves at least 50 GiB disk plus
  declared writes, and applies declared CPU, memory, timeout, input-copy,
  process-tree I/O, and child-output limits.
- Reuses Windows Job Object containment, suspended launch, kill-on-close,
  process-tree memory sampling, lifetime I/O accounting, CPU affinity, and
  bounded pipe draining. Fast children without a live sample are accepted only
  when quiescent Job Object lifetime accounting proves the budget.
- Stages repository source, the verified immutable release, and only declared
  inputs into a unique candidate workspace. The Python audit policy permits
  mutation only under the declared candidate output plus explicit temp/home
  roots; staged source, release, corpus, and inputs are read-only.
- Fingerprints protected serving state before, after, and immediately before
  terminal commit. Successful declared artifacts and the canonical self-hashed
  result commit in one directory rename. Failed, killed, superseded, or
  untrusted output is quarantined and cannot enter the candidate artifact set.
- Records exactly one terminal contract disposition from
  `resolved/rejected/regressed/inconclusive/superseded`; unmeasured killed or
  failed attempts carry an honest failure record rather than fabricated
  metrics.
- Uses an exclusive self-describing claim and releases every acquired claim on
  exit. Interrupted terminal persistence preserves bounded forensic scratch
  state instead of deleting evidence.

Safety boundary: this is a fail-closed Python audit policy plus Windows process
containment for allowlisted, trusted repository experiment modules. It is not
an operating-system sandbox for hostile native extensions. The queue is
reverified twice before terminal build, but an external writer could still
race the final check and atomic candidate commit; selected and final queue
evidence is retained for audit.

No experiment executor was scheduled and no non-synthetic experiment was run.

## Task 4 - worker release-binding verification (stretch)

Status: **COMPLETE**.

Commit: `62a89230` (`Bind paper workers to verified releases`).

- Added process-sticky verified serving-bundle binding to the taker and
  market-making paper workers when the active pointer is in scope.
- Before model probabilities are consumed, authenticates the raw snapshot
  against its self-hashed `replay_inputs.jsonl` record, exact release/manifest/
  pointer/sequence/base-model identity, market route, configured market-day
  folder and event slug, capture time, model version, and normalized recorded
  distribution.
- Stamps verified release ID, manifest SHA-256, pointer identity, sequence, and
  base-model binding into run configuration, summaries, order/quote tapes, and
  settled taker/counterfactual tapes.
- Preserves the historical release-unbound CSV header for diagnostic custom
  roots while rejecting partial or mixed lineage, mismatched append/recovery
  identity, stale process-sticky pointer state, and tampered probabilities.

Only synthetic worker fixtures were invoked. No live or persistent paper
worker was started or modified.

## Verification

The isolated worktree has no private virtual environment, so commands used the
existing interpreter at
`C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe` with the
evidence worktree as the working directory.

Host admission was checked before every executable batch. During final runs,
commit was 48.4-48.7%, free disk was 321.4-322.0 GiB, and observed free
physical memory remained above 2.4 GiB. All were inside the quiet window and
below/above the required thresholds.

Final focused results:

- Captured-input generator, registration emitter, and canonical comparator:
  `40 passed in 4.21s`.
- Experiment executor, experiment contract, and Job Object guard:
  `53 passed, 1 skipped in 5.48s`. The skip was the host's unavailable
  directory-symlink capability.
- Worker binding plus selected taker/MM append, recovery, and tape regressions:
  `15 passed, 3 subtests passed in 10.19s`.
- Import architecture and schema registry ratchets after the new files became
  tracked: `28 passed in 4.35s`.
- `python -m compileall -q src`: passed before each of the four implementation
  commits.
- Agent documentation audit: `PASS (18 agent files, 433 Markdown files)`.
- `git diff --check`: passed.

Intermediate verification found and corrected test-fixture defects only: a
relocated signed-pointer fixture did not use its injected verified bundle, an
executor fixture recreated an existing queue directory, and Windows newline
translation disagreed with a synthetic declared artifact hash. The complete
affected batches were rerun after each correction. The pre-commit architecture
ratchet initially reported the eight new files as untracked and passed after
the scoped commits tracked them.

No full test suite, soak, loop, scheduler, promotion, migration, network, or
live/persistent worker command was run.

## Isolation and merge notes

- The branch's changed-file set has zero intersection with
  `master...release-bootstrap-2026-07-13` and contains none of the prohibited
  supervisor/collection, `daily_refresh*`, forecast/CAS, or runtime-monitor
  modules.
- Rebase/merge remains the operations agent's job. The release branch owns the
  relevant README, nightly-retrain runbook, Item 321, and
  `weather.operations.nightly_retrain`; they were intentionally not edited
  here. After merge, reconcile its current
  `isolated_experiment_executor_not_implemented` status/documentation with the
  new deliberate executor command.
- The main worktree had pre-existing uncommitted changes, including its own
  `long_job_guard.py` and guard-test edits. They were never touched. The merge
  operator must reconcile those local edits separately from commit
  `d332dd7f`.
- `data/` and every operational tape/ledger remained untouched. All test
  artifacts were pytest temporary state.
