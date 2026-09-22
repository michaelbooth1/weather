# Scheduled Operations Instructions

Scope: `scripts/ops/`. These PowerShell files are the source of truth for Windows
scheduled-task names, cadences, actions, required arguments, working directories,
and recovery settings. **Read the complete script and its `param(...)` block
before changing or invoking it.** Detail lives with the owners:
[operations design](../../docs/operations/OPERATIONS_DESIGN.md) (task names, topology),
[integration-attempt runbook](../../docs/operations/INTEGRATION_ATTEMPT_RUNBOOK.md),
[host load policy](../../docs/operations/HOST_LOAD_POLICY.md) (windows, lease, workstation wrapper).

## Registration safety

- Editing a script does not authorize registering, disabling, starting, or
  deleting a task; do that only when the user explicitly places the host
  scheduler in scope. Re-registration replaces the named task: it is an external
  system change, not a validation step.
- Do not publish a bare registration command when the script has mandatory
  evidence, artifact, route, or production-readiness parameters. The default
  `Full` parameter sets of `register_daily_refresh.ps1` and
  `register_nightly_retrain.ps1` require them; both nightly registrars also
  require all eight explicit all-market base-retrain bindings, and the direct
  topology is fixed to `offline_host`. The one transitional exception,
  `register_daily_refresh.ps1 -ProvenanceOnly`, registers both wrapper tasks
  with scheduler provenance and release arguments and deliberately omits the
  production-evidence contract. Never call it FULL evidence or production
  readiness.
- Canonical scripts live here. Files directly under `scripts/` are compatibility
  shims unless another owning document says otherwise.
- Recurring task actions must execute a repository-owned script or module; a
  host-local file may hold logs or queue data, never the only copy of task
  logic. Merge queues use `merge_queue_driver.ps1` and bind every approved
  branch to a full reviewed SHA; movable branch-only queues are unsupported.
- Unattended recurring work binds a current-user `S4U` / `Limited` principal;
  re-running a registrar must not introduce an interactive-logon dependency.
  The credential-vault push and mirror tasks are the intentional interactive
  exceptions (an S4U session cannot access the vault).
- Default repository roots from the registrar's own `PSScriptRoot` and bind S4U
  to `$env:USERNAME`. Never hard-code the production checkout or account;
  registrars must stay safe when reviewed from an isolated worktree.

## Integration attempts and merges

The runbook owns the state machine, wait rules, and recovery. Do not break:

- New scheduled integrations use `new_integration_attempt.ps1` and
  `register_integration_attempt.ps1`. Each attempt binds a reviewed full tip,
  isolated worktree, orchestration-helper hashes, and unique one-shot task
  names, logs, and receipts. A failed attempt stays immutable; recovery closes
  its exact tasks, emits a reviewed dispatch, and one atomic predecessor claim
  authorizes the next attempt. `suite_gated_quiet_merge.ps1` may remain for
  existing work, but a task exit code without the correlated exact full-suite
  verdict is never merge evidence.
- Never add `StartWhenAvailable` to attempt tasks: a missed one-shot must fail
  visibly, not wake in a protected window. Status must distinguish a running
  suite, a suite without a receipt, a suite that never ran, and a merge trigger
  that passed without a receipt. Closing a crashed attempt may disable only its
  exact hash-bound, non-running tasks; never delete or replace them.
- A merge consumer may wait without a workload lease for its exact suite task
  only up to the documented merge reserve. It stops only its own hash-bound
  suite task, records the stop, requires `Ready` or `Disabled` as proof, and
  never advances from stale PASS metadata. Recovery dispatch never edits source
  or the scheduler and requires an active reviewed operator or agent.
- A published merge without final proof is `MERGED_UNVERIFIED`, not FAIL; it may
  not be closed, dispatched, or retried. `reconcile_integration_attempt.ps1`
  preserves that status, rechecks Git and three-worker capture health, disables
  only the exact receipt-bound tasks, and writes a separate immutable
  `MERGED_RECONCILED` receipt with downstream authority still false.
- A manifest-less quiet-window merge published outside the wrapper is retired
  only by `reconcile_ordinary_quiet_merge.ps1` (hash-bound marker, Git-proved
  publication, capture health, immutable receipt; see streak-soak.md). Never
  hand-delete the marker: while it exists the wrapper refuses every merge and
  boot recovery hard-resets a master that moved past its merge commit.
- `quiet_window_merge.ps1` records the exact local merge through
  `weather.operations.documentation_transaction` after capture recovery and
  before publication. Failure leaves the merge unpushed; stacked overnight
  integrations share one pending closeout due by 09:00.
- `quiet_window_merge.ps1 -ProductionBaselineReconciliation` is a **spent
  one-time incident mode**, hard-bound to one baseline/target commit pair that
  `master` has moved past. Never use it as a generic attempt, resume, push, or
  retry path, never route its marker through generic reconciliation, and never
  add a hard-reset fallback. Read
  [its preserved review constraints](../../docs/operations/history/scripts-ops-agents-incident-modes.md)
  before touching its code, helper, or status classification.

## Capture supervisors and training topology

The three streak-critical capture supervisors are snapshot, CLOB, and
observation-trigger. The auxiliary execution-tape producer has its own
supervisor only after it is explicitly armed and does not change three-worker
grading. Keep armed task names and `ensure` arguments aligned with the operations
design. An intentional stop must account for both the detached worker and the
supervisor that can revive it. After a held producer's roll-sensitive repair use
`adopt_execution_tape_after_merge.ps1`: it binds adoption to the exact guarded
merge, remote/local master agreement, capture recovery, scheduler identity, and
worker/status/lock proof, tears down on disagreement, and for an
integration-attempt merge also requires the manifest and merge-receipt SHA256
values and the read-only downstream gate.

Choose one retraining topology per host, never both for one workload
([nightly retrain runbook](../../docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md)):
`register_nightly_retrain.ps1` retrains directly without stopping capture;
`register_training_window.ps1` plus `training_window.ps1` stop and restore all
three capture loops behind an independent dead-man restore task. Both create a
run-specific one-shot with no late catch-up (capture host: fixed 01:00, refusing
outside its bound time *before* stopping capture; the 04:15 daily restore keeps
late catch-up). Preserve the `finally` restoration: it succeeds only after
checked enable/ensure exits and 3/3 capture recovery proof, and failure must
propagate.

## Leases, guards, and bounded wrappers

- Every heavyweight wrapper holds the shared lease from `workload_admission.ps1`
  across its expensive or capture-disrupting section. Headroom and time-window
  checks stay mandatory and independent; the lease only prevents overlap. A
  stale metadata file is not ownership — the open OS file handle is.
- The workstation path (`workstation_heavy.ps1`, `workstation_offline_v1`) and
  the sealed `portable_execution_v1` live lane are owned by the host load policy
  and [the portable execution-host runbook](../../docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md).
  Never generalize the live lane to another heavy command or unattended session.
- `install_codex_host_load_hook.ps1` owns the user-layer PreToolUse guard. It
  must never overwrite an existing `~/.codex/hooks.json`, must point at the
  repository-owned policy script, and must say that Codex needs review/trust on
  the next session. On an exact non-capture host it denies heavy commands not in
  the canonical absolute-path wrapper form. The hook prevents at launch; the
  one-minute S4U memory/process guard is the backstop. Both take role authority
  from the tracked MachineGuid-derived capture-host identity, never RAM, machine
  name, or portable assignment. The registrar proves that identity before
  Scheduler mutation and seals it into the task action; a bound guard exits
  before logging, enumeration, or termination on any other host. Legacy unbound
  actions keep enforcing until separately authorized re-registration.
- One-date settlement backfills use the canonical bounded daily-refresh slice
  ending at `market_day_labels_finalize`; never run the rest of the chain and
  kill it. Lock ownership is PID plus creation identity, not file existence.
- Tiering wrappers assign children to a kill-on-close Job, keep an absolute
  runtime bound, write latest status atomically, and append history; a
  busy-lease skip is not reclaim evidence. Their registrars bind fixed start
  times, runner bounds, and scheduler limits with no late catch-up (values:
  [data retention policy](../../docs/operations/data-retention-policy.md)) and
  must read back the exact action, trigger, principal, and settings.
- Producer provenance follows the topology: the nightly action is `direct`;
  daily-refresh and training-window Python processes are `delegated_child` of
  scheduled wrappers. Registration and wrapper build identical tokens through
  `daily_refresh_contract.ps1` / `training_window_contract.ps1`. Any missing or
  mismatched token, identity, executable, directory, running state, or run-time
  correlation stays non-countable; lineage is bounded to two ancestors, and
  child-supplied flags alone are never evidence.

## Verification

Validate PowerShell syntax without executing scripts (a clean parse does not
prove parameter binding), run the focused Python tests for the affected
operation, and update the operations design or owning runbook whenever a task
name, cadence, parameter, status path, or supervision contract changes.

## Update this file when

Update when task registration safety, canonical script locations, capture or
training topology, or PowerShell verification changes. Procedure detail belongs
in the owning runbook, not here.
