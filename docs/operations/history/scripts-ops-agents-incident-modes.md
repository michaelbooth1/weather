# `scripts/ops/AGENTS.md` — spent incident mode and pasted contracts

> **HISTORICAL — not current authority.** The text below was moved verbatim out of the
> always-loaded `scripts/ops/AGENTS.md` on 2026-09-19. Section 1 describes a one-time incident
> mode whose start condition can no longer be met on `master`. Section 2 is a pasted copy of a
> contract whose owner is [`../HOST_LOAD_POLICY.md`](../HOST_LOAD_POLICY.md). Section 3 keeps the
long-form wording of two current rules that were condensed, for reviewers. The current scoped
> rules are in [`scripts/ops/AGENTS.md`](../../../scripts/ops/AGENTS.md).

**Read when:** you are editing or reviewing the `-ProductionBaselineReconciliation` code path in
`scripts/ops/quiet_window_merge.ps1`, `production_baseline_scheduler_rpc.ps1`, or the marker
classification in `status.ps1`, and need the review constraints that code was written under.
**Do not read** to decide how to run an integration, a push, or a retry today.

## Why the mode is spent, and why the code is still there

- The mode is hard-bound to one incident: local baseline `3361520f…` with published target
  `c932b54f…` (`scripts/ops/quiet_window_merge.ps1`, the `$reconciliationLocalBaseline` and
  `$reconciliationPublishedTarget` literals). It refuses to start unless `HEAD` and local
  `master` both equal that exact baseline.
- Both commits are ancestors of `master` (verify: `git merge-base --is-ancestor c932b54f HEAD`).
  The production baseline moved past the incident, so the start condition cannot hold again.
- The switch, its helper, its tests, and the status/watchdog marker classification remain in the
  tree. Removing them is a roll-sensitive code change that needs its own reviewed item; it was
  not part of the documentation move.
- The durable design description is owned by
  [`../OPERATIONS_DESIGN.md`](../OPERATIONS_DESIGN.md) (search
  `production_baseline_reconciliation_v0.1`); the measured background is in
  [`../ESTABLISHED_FINDINGS.md`](../ESTABLISHED_FINDINGS.md) (search `c932b54f`).

## 1. One-time `production_baseline_reconciliation_v0.1` mode (verbatim)

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

## 2. Pasted workstation heavy-wrapper contract (verbatim)

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

## 3. Long-form wording condensed on 2026-09-19 (verbatim)

These two passages describe **current** behavior; they were shortened in the scoped file, not
retired. The owners are
[`../INTEGRATION_ATTEMPT_RUNBOOK.md`](../INTEGRATION_ATTEMPT_RUNBOOK.md) ("Create and register
attempt N", "Recover without losing the night") and
[`../OPERATIONS_DESIGN.md`](../OPERATIONS_DESIGN.md). If this copy and an owner disagree, the
owner and the script win.

Merge-consumer wait rules:

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

Producer provenance:

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

Tiering registrars and training-window timing (owners:
[`../data-retention-policy.md`](../data-retention-policy.md),
[`../NIGHTLY_RETRAIN_RUNBOOK.md`](../NIGHTLY_RETRAIN_RUNBOOK.md)):

The repository-owned tiering registrars bind projection/raw work to 05:00/06:00,
1800/2400-second runner bounds, PT31M/PT41M scheduler limits, and no late
catch-up. Their post-registration readback must prove the exact canonical
action, trigger, S4U/Limited principal, and settings before claiming success.

All training candidates are run-specific: both registrars create a future
one-shot task with no late catch-up. On the capture host the one-shot is fixed
to 01:00, the daily restore remains fixed at 04:15 with late catch-up, and the
wrapper must refuse outside its bound time before stopping capture. Restoration
is successful only after checked enable/ensure exits and canonical 3/3 capture
recovery proof; failure must propagate out of `finally`.

## Update this file when

Do not update it. If the incident code path is removed, add one dated line under "Why the mode is
spent" naming the removing commit.
