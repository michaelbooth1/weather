# Scheduled Operations Instructions

These instructions apply to `scripts/ops/`.

- These PowerShell files are the source of truth for Windows scheduled-task
  names, default cadences, actions, required arguments, working directories,
  and recovery settings. Read the complete script and its `param(...)` block
  before changing or invoking it.
- Do not publish a bare registration command when the script has mandatory
  evidence, artifact, route, or production-readiness parameters. The default
  `Full` parameter sets for `register_daily_refresh.ps1` and
  `register_nightly_retrain.ps1` require such inputs. Both nightly registrars
  also require all eight explicit all-market base-retrain bindings before they
  can create a task; the direct topology is fixed to `offline_host`. Daily refresh has one
  explicit transitional exception: `-ProvenanceOnly` registers both wrapper
  tasks with scheduler provenance and release arguments while deliberately
  omitting the production-evidence contract. Never describe that mode as FULL
  evidence or production readiness.
- Canonical scripts live here. Files directly under `scripts/` are compatibility
  shims unless another owning document says otherwise.
- Recurring task actions must execute a repository-owned script or module. A
  host-local file may hold logs or queue data, but must not be the only copy of
  executable task logic. Merge queues use `merge_queue_driver.ps1` and bind
  every approved branch to a full reviewed SHA; movable branch-only queues are
  unsupported.
- New scheduled integrations use `new_integration_attempt.ps1` and
  `register_integration_attempt.ps1`. Each attempt binds a reviewed full tip,
  isolated worktree, complete repository-owned orchestration-helper hashes,
  unique one-shot task names, logs, and receipts. A failed attempt stays
  immutable; recovery first closes its exact tasks, then emits a reviewed
  dispatch, and a single atomic predecessor claim authorizes the new attempt
  under the enforced class in the integration-attempt runbook. Existing
  scheduled roll-sensitive work may retain `suite_gated_quiet_merge.ps1`, but
  a task exit code without the correlated exact full-suite verdict is never
  merge evidence.
- Do not add `StartWhenAvailable` to integration-attempt tasks. A missed
  one-shot must fail visibly instead of waking in a protected window. Status
  must distinguish a currently running suite, a suite that ran without a
  receipt, a suite that never ran, and a merge trigger that passed without a
  receipt. Closing a crashed attempt may disable only its exact hash-bound,
  non-running tasks; it never deletes or replaces them.
- An integration merge consumer may wait without a workload lease for its
  exact suite task to reach terminal evidence, but only through the documented
  03:40 merge reserve. A running suite is not a failure before that deadline;
  terminal FAIL evidence and a disabled never-run suite are. A PASS receipt
  observed while Task Scheduler still reports Running receives only a bounded
  two-minute exit grace. A non-running task with immutable PASS and a stale
  Scheduler transient result records the disagreement and proceeds only to the
  full receipt/task-time checks; other nonzero results fail. At the deadline or
  grace expiry the consumer re-verifies and stops only its own exact hash-bound
  suite task, records the stop in its receipt, and requires Task Scheduler to
  report `Ready` or `Disabled` before treating the stop as proved. A transient
  `Queued`, `Unknown`, or other non-terminal state waits before the reserve but
  is stopped at it; it never advances from stale PASS metadata. Recovery
  dispatch never edits source or changes the scheduler and requires an active
  reviewed operator or coding agent.
- A merge that is already published but lacks a final proof is
  `MERGED_UNVERIFIED`, not an ordinary FAIL. It may not be closed, dispatched,
  or retried. `reconcile_integration_attempt.ps1` preserves that historical
  status, rechecks current Git and three-worker capture health, disables only
  the exact receipt-bound tasks, and writes a separate immutable
  `MERGED_RECONCILED` receipt with downstream authority still false.
- `quiet_window_merge.ps1` must record the exact local merge through
  `weather.operations.documentation_transaction` after capture recovery and
  before publication. Failure leaves the merge unpushed; stacked overnight
  integrations share one pending closeout due by 09:00.
- Its one-time `production_baseline_reconciliation_v0.1` mode is not a generic
  integration attempt or resume path. It is bound to the exact reviewed
  `3361520f... -> c932b54f...` incident, an isolated source tip/tree/self hash,
  the 01:00-04:00 window, raw snapshots of exactly two generated configs, and
  at most one already-provisioned `WeatherOneShotPush` invocation. Precommit
  markers must keep the fail-closed published-target sentinel; only the proved
  merge `M=[C,S]` may atomically expose real `C`, where `S` is the frozen
  reviewed safety tip and a strict descendant of published target `T`. `M` must
  equal `S` plus only the two captured config contents. Never route this marker
  through generic attempt reconciliation or add a hard-reset fallback.
  Reconciliation may access ScheduledTasks only through
  `production_baseline_scheduler_rpc.ps1`, launched inside the repository's
  kill-on-close Job. Immediately before every RPC launch, the parent re-hashes
  the helper against its exact `S`-pinned dependency SHA-256. The helper request
  deadline is eight seconds before the applicable PT15M/04:00 boundary, leaving
  five clamped seconds for `TerminateAndWait` proof and a further three seconds
  for bounded result parsing. The child brackets each structured task read with
  the same name/path `Export-ScheduledTask` plus UTF-8 hash path used by the
  parent freeze, counts only non-null triggers, re-resolves and fully attests
  the exact task twice, rechecks the bound marker, and mutation uses only the
  final `InputObject`; the parent independently validates bounded structured
  output.
  Journal the exact Start request before launch. Immediately before mutation
  the helper atomically creates a fixed one-use Start claim (or one claim for
  each of the two Stop ordinals); claims are never removed automatically. Claim
  creation and durable flush are followed by one immediate nonblocking deadline
  recheck before the direct `InputObject` mutation. If the flush consumed the
  request budget, the claim is spent/unknown and Scheduler is not called.
  A claim collision, or any cmdlet throw once a durable claim exists, is
  authority-claimed with dispatch unknown and spent, never a false no-dispatch.
  Any missing, failed, lost, or timed-out Start response likewise spends the
  sole authority, cannot PASS even if publication later appears exact, and is
  never retried. Before the first Stop claim, every post-Start Scheduler
  read identity is bounded to `pushContainmentStopAt`, preserving the complete
  30-second mutation reserve; a slow or hung read is killed before that edge.
  If a Stop identity or its budget cannot be created, exhaust Stop authority
  locally without recording a false attempt or dispatch. Write no post-boundary
  marker, and retain the lease plus read-only drain until exact terminal proof
  or the absolute report boundary. Successful Stop requests remain capped at
  two; any missing/lost/timed-out Stop response is terminal non-PASS and is not
  retried. Reconciliation Python and canonical remote-Git
  probes also run as deadline-clamped Job children, and every mutating stage
  rechecks the fixed quiet-window boundary. No concurrent manual
  `WeatherOneShotPush` caller is allowed across the final Ready/start boundary.
  The adopted `S` status/watchdog classify exact guarded, attempted, and
  acknowledged markers and never turn this incident into generic push/retry
  guidance. An unreadable or lookup-failed active marker is invalid evidence,
  never absence. Invalid incident evidence counts unpushed state only from cached
  `origin/master`; an unreadable comparison emits a neutral warning instead of
  silently becoming zero. A production command still requires the exact fully verified
  reviewed handoff; a green branch alone is not run authority.
- Registration scripts assume the repository root, its `venv`, and Windows
  Task Scheduler. Re-registration replaces the named task; it is an external
  system change, not a harmless validation step.
- Registration sources for unattended recurring work must explicitly bind a
  current-user `S4U` / `Limited` principal. Re-running a registrar must not
  replace an unattended task with an interactive-logon dependency. The
  credential-vault push and mirror tasks are the intentional interactive
  exceptions; do not convert them to S4U because that session cannot access the
  vault.
- Default repository roots from the registrar's own `PSScriptRoot`, and bind
  S4U to `$env:USERNAME`. Do not hard-code the production checkout or account;
  registrars must remain safe when reviewed from an isolated worktree.
- Editing a script does not authorize registering, disabling, starting, or
  deleting a task. Make those changes only when the user explicitly places the
  host scheduler in scope.

The three streak-critical capture supervisors are snapshot, CLOB, and
observation-trigger. The auxiliary public execution-tape producer has its own
supervisor only after it is explicitly armed; it does not change three-worker
streak grading. Keep all armed task names and `ensure` arguments aligned with
`docs/operations/OPERATIONS_DESIGN.md`. An intentional stop must account for
both the detached worker and the supervisor that can revive it.
After a held producer's roll-sensitive repair, use
`adopt_execution_tape_after_merge.ps1`; it binds adoption to the exact guarded
merge, remote/local master agreement, core capture recovery, scheduler
identity, and worker/status/lock proof, and tears back down on disagreement.
For an integration-attempt merge it additionally requires the manifest and
merge-receipt SHA256 values and calls the read-only downstream gate.

Choose one retraining topology per host:

- `register_nightly_retrain.ps1` directly schedules retraining and does not stop
  capture.
- `register_training_window.ps1` schedules a bounded single-host window plus a
  dead-man restore; `training_window.ps1` stops and restores all three capture
  loops.

Do not leave both topologies enabled for the same workload. Preserve the
training window's `finally` restoration and independent restore task when
modifying it.
All training candidates are run-specific: both registrars create a future
one-shot task with no late catch-up. On the capture host the one-shot is fixed
to 01:00, the daily restore remains fixed at 04:15 with late catch-up, and the
wrapper must refuse outside its bound time before stopping capture. Restoration
is successful only after checked enable/ensure exits and canonical 3/3 capture
recovery proof; failure must propagate out of `finally`.

Every heavyweight wrapper must hold the shared lease from
`workload_admission.ps1` across its expensive or capture-disrupting section.
On the capture host, resource headroom and time-window checks remain mandatory
and independent; the
lease prevents two individually admissible jobs from overlapping. A stale
metadata file is not ownership—the open OS file handle is.
The one non-capture live exception is the sealed `portable_execution_v1`
International Stage 0/1 launcher described in
`docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md`. It must remain bound to the
current Windows installation, canonical live-stage workload name, and
dedicated-capture-host exclusion; never generalize that lane to another heavy
command or to an unattended session. Ordinary implementation, tests,
training, and replay on the same physical non-capture workstation are allowed
by its workstation role. Recognized heavy commands must use
`workstation_heavy.ps1`; its admission-only `workstation_offline_v1` profile
shares the live launcher's host-global mutex without claiming the portable live
profile or its evidence. Both profiles require the assignment's exact
non-capture Windows installation and attending principal, and both paths own
the complete child tree in a kill-on-close Windows Job.
Wrapped work and a launched live stage are mechanically exclusive through
cleanup. Finish heavy work before sealing as an operational attempt-
preservation rule.

`install_codex_host_load_hook.ps1` owns the host-role user-layer PreToolUse
guard. It protects the capture host and, on an exact non-capture Windows host,
denies recognized heavy commands unless they use the canonical workstation
wrapper form with absolute Python and repository paths. It must never overwrite
an existing `~/.codex/hooks.json`, must point at the repository-owned policy
script, and must state that Codex requires review/trust on the next session.
The hook is prevention at launch;
the one-minute S4U memory/process guard remains the enforcement backstop.
Both the hook and the S4U guard use the tracked MachineGuid-derived dedicated
capture-host identity, not RAM, machine name, or portable assignment, as role
authority. The registrar proves that identity before Scheduler mutation and
seals it into the task action; a bound guard exits before log creation,
process enumeration, or termination on any other host. Legacy task actions
without the binding keep enforcing until separately authorized
re-registration, so a source update cannot silently remove the capture-host
backstop.

One-date settlement backfills must use the canonical bounded daily-refresh
slice ending at `market_day_labels_finalize`; never run the remaining chain and
kill it after settlement. Lock ownership is PID plus creation identity, not
file existence or PID alone. Tiering wrappers must assign children to a
kill-on-close Job, retain an absolute runtime bound, write latest status
atomically, and append history; a busy-lease skip is not reclaim evidence.
The repository-owned tiering registrars bind projection/raw work to 05:00/06:00,
1800/2400-second runner bounds, PT31M/PT41M scheduler limits, and no late
catch-up. Their post-registration readback must prove the exact canonical
action, trigger, S4U/Limited principal, and settings before claiming success.

Producer provenance follows the chosen topology. The direct nightly action
passes `scheduler-invocation-topology=direct`. The daily-refresh tasks and
training window are scheduled PowerShell wrappers whose Python processes are
`delegated_child`. Daily registration and its wrapper must build the same
task-specific tokens through `daily_refresh_contract.ps1`; the training-window
pair uses `training_window_contract.ps1`. Both reuse the shared scheduled-task
argument string and base64 token-contract converters. Missing or mismatched
action tokens, task
identity, child executable, working directory, running state, or run-time
correlation must remain non-countable. Direct and delegated provenance both
observe the current PID, OS image, complete command line, current working
directory, creation time, optional exact venv redirector, and current scheduler
engine PID/instance. Delegated lineage continues to the registered wrapper
within the two-ancestor bound. Child-supplied flags alone are not evidence.

Validate PowerShell syntax without executing scripts, run the focused Python
tests for the affected operation, and update the operations design or owning
runbook whenever a task name, cadence, parameter, status path, or supervision
contract changes.

## Update this file when

Update when task registration safety, canonical script locations, capture or
training topology, or PowerShell verification changes.
