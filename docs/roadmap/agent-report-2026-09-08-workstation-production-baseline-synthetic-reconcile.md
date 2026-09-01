# Workstation production-baseline synthetic reconciliation report

**Verdict: NO-GO. Do not run the production reconciliation candidate.**

The exact adopted-boot topology is viable without reaching its
`reset --hard` fallbacks, and an incident-bound implementation plus adversarial
fixtures was retained. There is still no production handoff for three reasons:

1. exact first merge `M` must be the published target plus only the two
   generated configs, so it retains adopted target `T`'s unconditional
   instruction to run `WeatherOneShotPush` whenever local `master` is ahead;
   the scheduled health watchdog republishes that instruction even after the
   sole authorized invocation may be spent;
2. the candidate bounds poll sleeps and canonical Git network children, but its
   ScheduledTasks Start, Stop, Get, Info, and Export cmdlets remain synchronous
   parent-process RPCs and can hang across PT15M or 04:00; and
3. the repository-required focused, compile, and full-suite gates were refused
   before Python launch because this host/principal is not the assigned
   non-capture workstation.

Production, real Scheduler state, credentials, providers, exchanges, PR #9,
and PR #7 were not touched.

## Immutable mission and source identity

| Item | Exact value |
| --- | --- |
| Reviewed parent branch | `origin/codex/workstation-production-baseline-reconciliation-2026-09-83a` |
| Reviewed parent tip | `d2ab532a5bebd0868754322c5b34f72ebff8293b` |
| Reviewed parent tree | `ad46b85e1409618c573b66f77ca31ad2ed877ed5` |
| Result branch | `codex/workstation-production-baseline-synthetic-reconcile-2026-09-84a` |
| Source implementation commit | `ac1882f3ee48657769953d441f183b497f80b9a2` |
| Source implementation tree | `87c0a6513a637b57922011cad7f04a5fed433091` |
| Materialized `quiet_window_merge.ps1` SHA-256 | `c567776c53ea32cfc6f1c3ea10fe27ca924190867d41490b69f65c84df36eeba` |
| Production local baseline `L` | `3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac` |
| Published target `T` | `c932b54f8747df5cdefc4cc42f8454b6797f09ae` |
| `T` tree | `6df5bac16d8c780c35b4601941eaca1137ea7070` |
| Adopted boot Git blob | `8465de619d7c88fded5144d8903595fb4f8cc93a` |
| Adopted boot SHA-256 | `253ab48e38a24af8cf8c8a5fde33f223b6e298b7acf91bbc56ad4c4a0ea8dc4a` |

The report commit is intentionally a report-only successor to the source
implementation commit. Its exact final tip and tree are supplied in the branch
handback after that successor exists; a commit cannot contain its own final
object ID.

## P0 adopted-boot proof

Let `C` be the temporary config-only child of `L` and `M` the only acceptable
synthetic merge with ordered parents `[C,T]`.

Before `M`, every marker keeps the existing
`quiet_window_merge_in_progress_v0.1` schema with:

- `baseline_commit=expected_baseline=L`;
- `expected_tip=resolved_branch_tip=T`;
- `pre_merge_commit=T` as a deliberate refusal sentinel;
- reconciliation-specific precommit phases; and
- additive reconciliation evidence that adopted boot ignores safely.

`L` is a strict ancestor of `T`, but `T` has two parents and changes files
outside the two generated-config allowlist. It therefore cannot satisfy the
adopted boot script's one-parent config-child validation. Without `MERGE_HEAD`,
boot refuses and preserves the state. With `MERGE_HEAD`, boot may invoke
`merge --abort`; whether that succeeds or fails, both marker-derived hard-reset
predicates remain false.

The implementation creates and proves exact `C`, stages `T`, proves capture
recovery while the merge is uncommitted, creates exact `M=[C,T]`, and proves
that `M` differs from `T` only at the two captured config blobs. Only then does
one atomic marker replacement expose real `pre_merge_commit=C` in the existing
`merge_committed_unpublished` phase. At and after that cutover, the adopted
committed-recovery predicate is true and preserves exact `M`; every later
marker replacement retains the complete predicate.

The exact adopted-boot replay fixture covers these interruption boundaries:

- raw snapshot before marker publication;
- preparation marker before config commit;
- after config commit;
- merge staging with successful and failed `merge --abort`;
- merge commit before postcommit marker cutover;
- complete postcommit marker;
- documentation publication;
- push-attempt publication;
- containment stop attempted;
- containment stop exhausted;
- terminal proof after 04:00 with a recorded breach;
- terminal unpublished state;
- origin acknowledgement before the published marker; and
- complete published marker.

The fixture executes the exact adopted boot bytes, intercepts every Git call,
and asserts that marker/config/evidence bytes remain preserved and no tested
path invokes `reset --hard`. Static source review by two independent agents
found no remaining boot/reset P0 defect. Dynamic execution of that fixture was
not admitted on this host, so it is implementation evidence, not a production
PASS.

## Retained implementation

The narrowly gated `production_baseline_reconciliation_v0.1` mode:

- binds exact L/T endpoint trees, config blobs, canonical origin, production
  `master`/HEAD identity, isolated source tip/tree/self hash, and adopted
  dependency hashes;
- accepts exactly unstaged modifications to
  `config/location_market_events.json` and `config/locations.json`;
- snapshots and hashes their raw bytes before marker or Git mutation and
  rechecks them after external task readback and immediately before dispatch;
- calls `roll_verdict.ps1` explicitly with `-Base L -Branch T` and treats every
  nonzero, missing, unreadable, stale, dormant, or incomplete result as
  roll-sensitive;
- performs no-mutation dry-run synthesis in a temporary shared clone before
  lease acquisition;
- uses only `merge --abort` plus `reset --mixed L` for safe precommit rollback;
  the ordinary synchronized path remains unchanged, including its existing
  rollback behavior;
- proves all affected capture workers and conditional execution-tape recovery
  before publication;
- binds the documentation transaction and content-addressed snapshot;
- validates the existing zero-trigger singleton push task's XML, action,
  working directory, principal, state, settings, and runtime information;
- persists `push_invocation_attempted=true`, start time, and containment
  deadline before its sole Start call;
- permits at most two Stop calls, records exhaustion/window breach, retains the
  lease until stable terminal proof, and never reports PASS after exhaustion or
  a 04:00 breach;
- bounds canonical remote acknowledgement in an owned 30-second Git process;
- preserves uncertain post-dispatch state and never rolls it back; and
- makes topic-side status and generic attempt consumers reject retry/close of
  incident-bound evidence.

The execution harness uses disposable local Git repositories, a fake bare
origin, raw config fixtures, mocked capture/documentation/Scheduler surfaces,
and no production path. It includes wrong SHA/ref/branch/origin/ancestry/config
cases; exact dirty-path and snapshot drift; roll exits 1/2/3 plus missing,
stale, missing-closure, and dormant-closure evidence; marker and post-replace
fault matrices; conflict/recovery/docs/task/start/push/ack failures; queued,
delayed, pre-dispatch-failure, stop-exhaustion, and post-04 readback cases; exact
parents/tree/raw bytes on success; and no-hard-reset assertions.

## Exact remaining safety boundaries

### 1. Adopted status/watchdog publishes a forbidden retry

At exact `T`, `scripts/ops/status.ps1` lines 1652-1658 add
`N commit(s) unpushed (run WeatherOneShotPush)` solely from
`origin/master..master > 0`. The reconciliation-specific operation mode does
not exist in `T`. Renaming the report stage to
`reconciliation_merged_unpublished` avoids only the separate, later
`merged_unpushed` branch; it cannot suppress the unconditional warning.

Exact `M` is required to be `T` plus the two production-generated configs, so
the topic status guard cannot be present in first-adoption production. This is
automated, not merely a manual-command concern: adopted
`scripts/ops/health_watchdog.ps1` invokes production `status.ps1 -Json` on its
scheduled pass, copies `status.warns` into host-health notes, and regenerates
`MORNING_BRIEFING.md` Standing notes. From local `C/M` onward it can advise a
premature push; after an attempted or failed push it can advise a forbidden
second invocation.

Operator prose or invoking the topic status script manually does not remove the
scheduled adopted surface. Closing this boundary needs a newly authorized and
reviewed topology or containment that preserves the required exact `M` tree
and the prohibition on Scheduler mutation.

### 2. Scheduler RPC calls are not wall-clock bounded

The polling loop is capped, but `Start-ScheduledTask`, `Stop-ScheduledTask`,
`Get-ScheduledTask`, `Get-ScheduledTaskInfo`, and `Export-ScheduledTask` execute
synchronously in the parent PowerShell process. If any RPC blocks, the script
cannot regain control to enforce PT15M or stop mutating at 04:00. Existing mocks
return or throw and therefore cannot prove this case.

A safe successor needs a killable child-process seam for every Scheduler RPC.
Each child must re-resolve and revalidate the exact singleton/XML/principal,
atomically journal before a mutating call, use `-InputObject` on its validated
task, and have a bounded parent wait/kill. A timed-out Start remains spent and
ambiguous; bounded Stop helpers may run only within the already-recorded count
and quiet-window budget. This is a design requirement, not authority to add or
change a scheduled task.

### 3. Required executable verification was not admitted

At 2026-09-01 15:58 America/Toronto, each required serial wrapper invocation
exited 1 before Python launch with:

```text
this host and Windows principal are not the assigned non-capture workstation
```

The guard was not bypassed. The following results are therefore truthful:

| Gate | Result |
| --- | --- |
| Focused reconciliation, status, and affected integration-attempt tests through `workstation_heavy.ps1` | **POLICY-BLOCKED before Python launch**, exit 1 |
| `compileall -q app src tests` through `workstation_heavy.ps1` | **POLICY-BLOCKED before Python launch**, exit 1 |
| Complete repository pytest suite through `workstation_heavy.ps1` | **POLICY-BLOCKED before Python launch**, exit 1 |
| PowerShell AST parse of the five changed operational scripts | **PASS**, zero parser errors |
| `git diff --check` | **PASS** |
| `STATE_OF_PLAY.md` size contract | **PASS**, exactly 90 lines |
| Agent-document audit | **NOT RUN**; the current 12:00-18:00 production graded window forbids this bulk Python scan |
| Roadmap lint/check | **NOT RUN** for the same protected-window bulk-scan boundary |
| Canonical source-branch `roll_verdict.ps1` | **UNDECIDABLE**, exit 1 |

The canonical roll command was not replaced by a hand-derived result. It
reported all four required closure files missing in this isolated worktree:

- `data\snapshots\loop_supervisor_status.json`;
- `data\snapshots\clob_loop_supervisor_status.json`;
- `data\snapshots\observation_trigger_supervisor_status.json`; and
- `data\snapshots\clob_enrichment_status.json`.

## Changed files

Source implementation commit `ac1882f3...` changes:

- `docs/operations/ESTABLISHED_FINDINGS.md`
- `docs/operations/OPERATIONS_DESIGN.md`
- `docs/operations/STATE_OF_PLAY.md`
- `docs/ops/streak-soak.md`
- `scripts/ops/AGENTS.md`
- `scripts/ops/close_integration_attempt.ps1`
- `scripts/ops/integration_attempt_merge.ps1`
- `scripts/ops/quiet_window_merge.ps1`
- `scripts/ops/reconcile_integration_attempt.ps1`
- `scripts/ops/status.ps1`
- `tests/operations/test_production_baseline_reconciler_execution.py`
- `tests/operations/test_production_baseline_reconciliation.py`
- `tests/operations/test_quiet_window_merge_script.py`
- `tests/operations/test_status_script.py`

This report adds:

- `docs/roadmap/agent-report-2026-09-08-workstation-production-baseline-synthetic-reconcile.md`

## Prohibited actions audit

- No production checkout or production `data/` path was targeted.
- No real scheduled task was started, stopped, registered, edited, enabled,
  disabled, rebound, or deleted.
- `WeatherOneShotPush` was not invoked.
- No credentials or credential values were read or exported.
- No provider, exchange, live market, or trading endpoint was contacted.
- PR #9 and PR #7 were not merged or modified.
- No promotion, release, training, replay, live order, force push, history
  rewrite, stash, checkout cleanup, rebase, squash, or cherry-pick occurred.

## Stop handoff

There is no production command in this NO-GO report. Keep production at
`master@3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac` with the two generated config
modifications intact. Do not run this branch's reconciliation mode, manually
fast-forward, retry a one-shot marker, or adopt PR #9/#7.

Resume only under a new reviewed mission that closes the adopted
status/watchdog instruction, implements killable bounded Scheduler RPCs,
passes the focused/compile/full gates on the assigned workstation, obtains
exact-head CI/review, and reruns canonical production closure classification.
The present owner authorization is not consumed, but this report is not
standing authority to use it.
