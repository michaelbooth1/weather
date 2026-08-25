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
- Load-bearing attempt evidence must use the shared bounded single-open
  snapshot reader: the same retained bytes supply strict UTF-8 text, JSON, and
  SHA-256. Never reintroduce separate hash and parse opens. New v2 attempt
  mutations must also revalidate the canonical dated `AttemptRoot` and sibling
  `.preparation` chain as exact non-reparse directories immediately after
  creation and at runtime boundaries. Keep structural v1 manifest reading and
  damage-tolerant exact-task closure independent of that strict v2 check.
- `prepare_integration_attempt.ps1` is the preferred one-line interactive
  entry point when a reviewed topic still needs publication. It requires
  exact case-sensitive literals
  `AUTHORIZE_EXACT_NON_FORCE_TOPIC_PUBLICATION` for the topic push and
  `AUTHORIZE_DISABLED_INTEGRATION_TASK_REGISTRATION` for disabled registration
  and `AUTHORIZE_EXACT_INTEGRATION_TASK_ACTIVATION` for enabling the exact pair, runs in
  the admitted window for a later suite date, and
  requires an exact Job-contained preflight plus full-suite qualification and
  at least 100 minutes remaining before the independent 09:00 hard stop. The
  future schedule freezes the measured-or-90-minute ceiling plus ten minutes
  of execution margin and a separate five-minute Scheduler launch grace before
  manifest/task creation. Its exact new task
  names must be absent at preparation; readiness/activation may recognize them
  only after exact Disabled registration. Every other Disabled integration task
  needs exact retirement or FAIL-closure evidence regardless of its demand-start
  setting. It revalidates live
  refs, baseline, worktree, and helper hashes after qualification, serializes preparation with a host-global
  open-handle lock, rejects any enabled integration-attempt collision, and may
  report PASS only after immutable readiness and final preparation receipts. Composite
  registration creates both tasks Disabled; readiness writes the exact
  manifest-bound execution token, then the activator enables and re-attests
  both tasks and atomically writes the final PASS preparation receipt. Suite
  and merge wrappers require both the token and that post-enable receipt, so a hard stop at any intermediate instruction is
  fail-closed. Its sibling `.preparation` evidence directory is spent and must not
  be rewritten after failure. A post-manifest preparation failure must run the
  canonical closer and hash its terminal receipt; an unproved close is a loud
  blocker, never a preparation result. Before publication it invokes the
  canonical creator's non-publishing preflight path; after publication it reruns
  the ordinary creator so all mutable premises are checked before freezing.
  The creator and registrar remain the lower-level canonical primitives.
  Invoke every attempt entry point through the preparer's contained Windows
  PowerShell child contract so any child `exit`, hang, or parent termination
  cannot bypass final receipt handling or canonical closure. Creator preflight,
  post-qualification creator, registrar, readiness, activator, and closer each
  use a separate kill-on-close Job and a fresh frozen five-minute hard stop.
  Their bounded stdout/stderr files remain behind retained no-write/no-delete
  handles until the Job is explicitly terminated, its active-process count is
  observed at zero, and its handle closes successfully; only then are the exact
  strict-UTF-8 bytes and SHA-256 captured for diagnostics and the owned files
  removed. Child-written
  immutable JSON remains the authority; redirected output never substitutes
  for it. The preparer also holds the verified child script itself open with
  read-only sharing from SHA-256 verification through process completion, so
  `powershell.exe -File` cannot reopen a replaced generation.
  The prepublication creator writes its exact plan create-only at the canonical
  sibling `.preparation` path; stdout is not evidence. The preparer retains one
  bounded snapshot and SHA-256. That plan binds both the creator and shared
  preparation-contract hashes, and the ordinary creator must consume and
  revalidate that exact plan before immutable manifest creation. V2 manifests
  retain its canonical path/SHA-256, and strict runtime preparation validation
  rejects a missing or changed plan without making structural closure depend on
  dereferencing it. Keep creator-frozen tracked test, Python-source, and
  PowerShell-source inventory counts/SHA-256 values load-bearing through
  qualification, manifest, and scheduled repeat. Qualification and repeat must
  also match retained Python-environment and toolchain fingerprints exactly;
  the toolchain fingerprint covers the absolute Git, approved same-installation
  Git LFS, Python plus `pythonw.exe`, and PowerShell executable hashes and
  reported runtime identity. Before the first Python child, retain the exact two
  reviewed production-venv `.pth` files through the suite, force stdlib
  distutils, and prove the candidate worktree source wins over the editable
  production-source path. Every Python launch scopes and restores the frozen
  local-only Git config/protocol environment and refuses topology redirects.
  Ignored-shadow checks are bounded to root singleton controls and executable
  extensions plus `app/`, `scripts/`, `src/`, `tests/`, `tools/`, compatibility
  `weather/`, and top-level roots derived from tracked Python/native parents;
  ignored `data/` evidence is outside import authority and must not become a
  false blocker. Preserve bounded
  `evidence_validation_error` diagnostics and treat any such error as
  unconditional non-PASS. Keep the
  deterministic integration-preflight inventory owned by the bounded runner;
  consumers derive its file/chunk plan from the same retained immutable log
  snapshot instead of copying a count into an orchestrator.
- Every new integration attempt requires the preparer's exact authorization;
  explicit `preparation: null` is not legacy compatibility. Registration is
  always staged Disabled while the manifest-bound execution token is still
  absent; readiness creates it only after exact disabled-task attestation.
  Activation accepts only a fresh readiness receipt and that token,
  then repeats live topic/master, clean worktree, baseline, and quiet-merge
  preflight checks before enabling either task. Suite, merge, and closure must
  refresh their load-bearing remote refs successfully; a fetch failure is a
  blocker, never permission to consume stale tracking state.
  Creator plan/manifest writes, each registrar mutation, every suite phase, and
  final readiness/activation boundaries must repeat their complete canonical
  live/local/worktree/inventory/ignored tuple, not a one-field sentinel. Quiet
  merge retains and hash-binds every PowerShell dependency and its exact
  Git/Git-LFS/Python executable generation through last use, disables Git hooks
  on mutations, and runs Python proof stages only through bounded Job/output
  containment with loaded-source identity and state sandwiches. Each sandwich
  rejects skip-worktree/assume-unchanged flags and binds every tracked regular
  working byte together with index mode/blob identity and explicit Git LFS
  pointer-versus-hydrated identity; the reported loaded-source fingerprint is
  recomputed from retained stage bytes before the proof is accepted. Every
  production quiet merge, including a direct/manual invocation, requires an
  exact `origin/<topic>` ref, fresh canonical live topic/master observations,
  and an exact two-ref fetch; a failed refresh never falls back to stale
  tracking refs.
- Current attempts require one canonical GitHub HTTPS origin with no
  `remote.origin.pushurl` and no effective `url.*.insteadOf` or
  `url.*.pushInsteadOf` rule in any Git config scope. Live ref evidence must use
  the repository-independent canonical query helper, and production publication
  is not proved by a locally advanced `origin/master` alone. The shared remote
  helper refuses ambient Git identity, object-store, config, executable,
  TLS, askpass, SSH/proxy, and trace controls at both local merge and remote
  boundaries. Remote children start suspended, enter a kill-on-close Job before
  resume, and expose stdout/stderr only through retained bounded handles that
  deny replacement until parsing is complete; backing files are then deleted.
  A timeout, output overflow, normal wrapper exit, or attempt-wrapper hard stop
  may claim teardown only after explicit Job termination, an observed zero
  active-process count, and a checked successful Job-handle close. A top-level
  child exit alone is never descendant-termination proof.
- Integration suite and merge tasks are exact-date, non-demand-startable
  one-shots. Their wrappers reject a different local calendar date, and
  closure may disable/certify only exact `Ready` or `Disabled` task states.
  Missed or ambiguously observed attempts require review and a successor.
  Compute preparation lead, suite/merge spacing, launch reserve, hard-stop
  reserve, and protected-merge overlap from timezone-offset instants; never
  count a daylight-saving wall-clock jump as elapsed execution time.
  Every enabled `Ready` attempt/bootstrap task is a collision regardless of
  null, due, or past `NextRunTime`. `AllowOwnExactTasks` exempts only the exact
  own pair while staged `Disabled`; enabled own tasks and due protected merge
  drivers remain blockers. Re-fetch an enabled protected driver's exact state
  after its separate task-info read and once more before admission; a state,
  action, or `NextRunTime` transition is a collision, never a future-run proof.
- Bounded suites refuse ambient Python/pytest controls, use one new empty
  non-reparse `PYTHONPYCACHEPREFIX`, disable bytecode writes, and remove only
  that owned empty cache root. Before import and again before PASS they reject
  ignored Python, pytest-config, sourceless-bytecode, and native-extension
  shadows, including `.git/info/exclude` and global-ignore matches. Capture and
  import probe JSON crosses the child boundary only in retained strict-UTF-8
  stdout bytes; JUnit parsing and SHA-256 likewise come from one retained file
  snapshot. Never restore separate parse/hash opens or result-path transport.
  Bind the protected evidence root separately from unique system-temp writes.
  The production capture admission child alone may carry the frozen read-only
  production-probe marker; it never grants evidence, production, `.env`, or
  credential writes.
  Creator, readiness, and activation repeat the shared ignored import/test-
  configuration namespace guard at their final authority boundaries. Under
  exact `WEATHER_INTEGRATION_TEST_OFFLINE=1`, every Scheduler mutation fails
  closed unless the exact verb resolves directly to an in-process `Function`
  mock; cmdlets, aliases, applications, and missing commands are forbidden.
  Quiet merge additionally refuses every non-dry-run invocation in that mode.
- Historical v1 PASS attempts may still have `AllowDemandStart` tasks after
  their one-shot trigger. Never relabel those attempts FAIL, delete their
  evidence, or ignore them in collision checks. Retire only their exact task
  pair with `retire_integration_attempt_tasks.ps1`; it requires the immutable
  PASS merge receipt, successful receipt-correlated Scheduler results, a review
  reference, and the exact retirement literal before disabling either task.
  Disabled demand-startable tasks remain collision blockers until the exact
  two-task retirement receipt validates, or until an exact immutable FAIL
  closure proves the attempt was abandoned and both tasks terminalized. The
  retirement writer must read its create-only receipt back before success;
  partial, missing, or corrupt retirement evidence never authorizes a successor.
  Collision readers must receive the target production repository root
  explicitly. They may be loaded from an isolated worktree whose ignored
  `data/` tree is not the production evidence namespace, so `$PSScriptRoot`
  is never evidence-root authority.
  Its preflight mode is read-only. Invoking the mutating mode still requires
  explicit user authority over the host Scheduler.
- The two 2026-08-22 bootstrap tasks predate attempt manifests and are not
  eligible for the PASS-attempt retirement path. Their narrowly allowlisted
  `retire_legacy_integration_bootstrap_task.ps1` path requires the complete
  exported-task XML hash, exact terminal run time/result, expired trigger,
  review reference, and a separate literal. Never generalize that exception to
  a task-name glob or use it to retire a future/running task.
- Generic one-shots always register
  `one_shot_guarded_launcher.ps1`, never a mission payload directly. Manifest
  v0.4 binds the launcher, payload and ordered arguments, validator,
  kill-on-close Job helper, and workload admission for heavy work. The launcher
  holds a shared registry lock across validation and payload execution, rehashes
  every dependency from a retained handle that denies write/delete through
  teardown, uses the shared heavy lease when required, and owns the payload's
  Job and absolute deadline. Writers, resolvers, activation recovery, compaction, and reviewed
  debris reconciliation take the exclusive lock and never recreate a missing
  durable lock. Manifest/resolution index events, resolution receipts, and
  compaction receipts are create-only history. Compaction requires exact task
  absence; Disabled is not enough. A valid successor-pending transaction is
  resumable and must never be deleted as debris.
- Do not add `StartWhenAvailable` to integration-attempt tasks. A missed
  one-shot must fail visibly instead of waking in a protected window. Status
  must distinguish a currently running suite, a suite that ran without a
  receipt, a suite that never ran, and a merge trigger that passed without a
  receipt. Closing a crashed attempt may disable only its exact hash-bound,
  provably `Ready` or already `Disabled` tasks; it never deletes or replaces
  them.
- An integration merge consumer may wait without a workload lease for its
  exact suite task to reach terminal evidence, but only through the documented
  03:40 merge reserve. A running suite is not a failure before that deadline;
  terminal FAIL evidence and a disabled never-run suite are. A PASS receipt
  observed while Task Scheduler still reports Running receives only a bounded
  two-minute exit grace measured from the validated receipt completion time. A non-running task with immutable PASS and a stale
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
  Every reconciliation Python probe, including idempotent marker cleanup and
  documentation resume, must use the suite-qualified interpreter hash through
  the kill-on-close bounded-process helper. Parse only retained stdout bytes,
  require exact module/runtime/loaded-source identity inside an unchanged
  production Git tuple, and record executable/output/source hashes in the
  reconciliation receipt; direct Python launches are forbidden.
  Reconciliation marker phase changes use create-new plus `Flush(true)` and
  atomic replacement, prove backup bytes equal the prior marker and published
  readback equals the intended bytes, and preserve any initiating error through
  checked cleanup.
- `quiet_window_merge.ps1` must record the exact local merge through
  `weather.operations.documentation_transaction` after capture recovery and
  before publication. Failure leaves the merge unpushed; stacked overnight
  integrations share one pending closeout due by 09:00. Quiet merge resolves
  exactly one absolute regular non-reparse `git.exe` and uses that executable
  for every checked local read, mutation, and rollback. Its attempt-local report
  is a create-new, flush-to-disk, same-handle JSON/hash generation; mutable
  latest/history outputs are diagnostic-only. Crash-marker replacements prove
  the exact prior backup and intended readback, and publication re-reads marker
  plus documentation pending/snapshot JSON from one retained generation each.
- `roll_verdict.ps1` routes every Git query through the shared pinned,
  sanitized, bounded-process helper. Preserve its public exit meanings
  (0 roll-free, 1 undecidable, 2 dormant-only, 3 roll-sensitive), and never
  restore a direct native Git invocation or `$LASTEXITCODE` dependency.
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
  S4U to the current `WindowsIdentity` name and SID, never to ambient
  `$env:USERNAME`. Freeze its authority-qualified name, SID, machine, and domain
  context in registration evidence; reject conflicting ambient account/host
  variables and translate Scheduler readback back to the exact SID. Do not
  hard-code the production checkout or account; registrars must remain safe
  when reviewed from an isolated worktree.
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
 identity, exact qualified `pythonw.exe` action, and retained worker/status/lock
 proof, and tears back down on disagreement. Invoke the manifest-bound success
 gate as a hash-pinned contained PowerShell child; disable and re-attest the
 supervisor before any rollback stop, and re-attest its full binding at every
 enable/start/final boundary.
For an integration-attempt merge it additionally requires the manifest and
merge-receipt SHA256 values and calls the read-only downstream gate. Its
capture, managed-status, and rollback-stop Python children must use the
canonical pinned repository interpreter and kill-on-close bounded-process
helper with sanitized environment, retained output, strict JSON, loaded-source
identity, and equal production Git tuples. Cleanup diagnostics may accompany a
refusal but must never replace its initiating reason.

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
Resource headroom and time-window checks remain mandatory and independent; the
lease prevents two individually admissible jobs from overlapping. A stale
metadata file is not ownership—the open OS file handle is.
The bounded worktree suite must obtain its three-worker admission result from
the production tree's canonical `weather.operations.capture_recovery_check`;
a duplicate status/lock PID counter is not process-instance proof and is
vulnerable to PID reuse. Before each such import, it must run the manifest-bound
quiet-merge preflight so tracked production code drift and a changed exact push
task fail closed before they can weaken the canonical checker.

`install_codex_host_load_hook.ps1` owns the production host's user-layer
PreToolUse guard. It must never overwrite an existing `~/.codex/hooks.json`,
must point at the repository-owned policy script, and must state that Codex
requires review/trust on the next session. The hook is prevention at launch;
the one-minute S4U memory/process guard remains the enforcement backstop.

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
