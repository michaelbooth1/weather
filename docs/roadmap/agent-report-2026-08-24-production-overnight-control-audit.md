# Production overnight control audit -- 2026-08-24

This is dated audit evidence, not the canonical current-state page. Current
operations remain owned by `docs/operations/STATE_OF_PLAY.md`.

## Verdict

The production safety controls worked: neither the failed integration attempt
nor the stale settlement-recovery task changed production, started a live
exchange action, or exposed a credential value. The overnight plan nevertheless
failed its operational objective because readiness was asserted before every
remaining operator dependency and time-sensitive binding had been proved.

The central classification error was treating each of these as progress:

- a reviewed local repair that had not been published;
- a recovery dispatch that explicitly required an active agent;
- a host-local resume helper that nobody had acknowledged running; and
- an enabled future task whose boot and source bindings had already become
  stale.

None of those states is unattended readiness.

## Evidence-backed timeline

| Local time | Event | Actual outcome |
| --- | --- | --- |
| 2026-08-23 20:38 | Credential-reconciliation candidate `75b0b8954fd14fb275ed983ae984bf1cf6b13749` committed | No Python verification was permitted in the protected host window. |
| 20:56 | Attempt `credential-reconcile-0824-a1` frozen | Exact manifest scheduled the suite for 00:30 and merge for 03:10. |
| 21:14 | Both attempt tasks registered | Registration was valid, but it proved task identity rather than branch correctness. |
| 2026-08-24 00:30--00:31 | Integration preflight ran | 139 tests ran; three assertions exposed two deterministic governance defects. The full suite did not start. |
| 00:50 | August 17 settlement recovery fired | It refused before child launch because the frozen post-boot proof described the prior boot. Its frozen workload-admission hash was also stale. |
| 01:21 | Failed integration attempt closed and dispatched | Both exact tasks were disabled. The dispatch required reviewed active-agent recovery. |
| 01:25 | Repair `cb1745d2524145ba77786d37332d6ebc9e9c20f0` committed | Its focused 139-test preflight passed locally. |
| 01:32 | Host-local resume helper created | It still required an interactive publication and registration action. No acknowledgement followed. |
| 09:00 | Documentation transaction deadline | The transaction from the prior production merge became overdue. |
| 09:30--11:47 | Repository-owned Stage A ran | It completed 17/25 steps, terminalized `RESUMABLE` at `ten_minute_model_performance`, and its absolute deadline returned Scheduler `0x4B`; the isolated child is gone. Host protection worked, but the chain did not complete. |

Morning proof showed that `origin/codex/credential-reconcile-20260823` remained
at `75b0b8954fd14fb275ed983ae984bf1cf6b13749`, no `a2` attempt or task existed,
and production remained at `4feef39a44f920affcb05387a8882fb5f735cfa0`.

## Pre-overnight precursor failures

The overnight miss was the end of a longer preparation chain, not an isolated
00:30 defect:

- Hook installation was initially discussed as if it proved enforcement. A new
  Codex hook is skipped until the restarted session reviews and trusts it; the
  independent one-minute S4U guard remained the backstop. The later restart
  proved the hook active. Future handoffs must distinguish installed bytes,
  trusted configuration, and an observed policy decision.
- Early credential-import wrappers collapsed typed validation failures into a
  generic `RuntimeError`, then passed two SDK-overlay flags to the older
  production CLI that did not accept them. Those were interface/version and
  diagnostic-contract failures, not bad credentials.
- After the live-readiness code landed, the create-only importer correctly
  found pre-existing canonical Credential Manager targets and refused to
  overwrite them. The assistant initially treated that safe refusal as another
  import defect instead of recognizing that compare-only reconciliation was
  now the required operation.
- The first owner-approved guarded merge at 19:23 recovered all three capture
  workers but found the execution-tape worker still on stale source. The guard
  rolled the merge back and proved complete baseline recovery. Root cause was
  a supervisor restart budget that counted six refused, no-child starts as
  recoveries and imposed a 3,600-second backoff. A reviewed fix preserved real
  failed-launch protection while excluding those no-mutation refusals; the
  19:59 retry restarted the worker onto new source and published the 20:04
  merge. The guard worked, but the defect should have been exercised before an
  exceptional production-window merge.
- Repository timezone was incorrectly used conversationally as evidence that
  the host was in Ontario. It is only scheduling configuration. Physical
  location and jurisdiction eligibility require separate action-time evidence.
- User approval of a live test, credential handling, or a one-time timing
  exception was discussed as prose rather than compiled into one exact
  executable authorization/readiness transaction. Conversely, credentials in
  `.env` did not authorize secret disclosure, overwriting existing fixed
  targets, exchange contact, or an unattended order. The workflow needed to
  distinguish those authorities explicitly instead of repeatedly asking the
  operator to bridge hidden technical states.

## What failed and why it was missed

### 1. Candidate qualification was weaker than the scheduled preflight

The candidate added an intentional process-local `except ImportError` boundary
without its architecture exception and expanded a large module without updating
the ownership count/map. Static review missed both. The scheduled preflight
correctly found them and stopped the full suite.

This was not a failure of fail-closed execution. It was a planning error to
describe an unverified protected-window candidate as if the 00:30 preflight
were only confirmation. A night whose first permitted verification can still
discover a deterministic defect is a conditional attempt, not an unattended
completion plan.

### 2. Recovery state was confused with an armed successor

`READY_FOR_SUCCESSOR_REVIEW` means a human or coding agent may review and create
one successor. Canonical status rendered that as `RECOVERY_READY` and said it
was "ready for an active agent." The wording obscured that no successor manifest,
publication, registration receipt, or tasks existed. Freshness-based alert
demotion could later reduce the visibility of this unresolved state.

The audit then made the same mistake conversationally: it supplied a one-line
operator command after the operator had said they needed sleep, but did not
remain in `WAITING_FOR_OPERATOR`, obtain its output, or independently prove the
remote and task state before ending the handoff.

### 3. The resume helper was ordered incorrectly

The host-local helper checked and potentially published the repaired topic
before calculating whether enough of the same-night suite/merge window remained.
After expiry it could therefore mutate the remote and only then refuse to create
or register the successor.

The immediate local repair moves the complete time-window check ahead of all
network and Scheduler work, requires at least ten minutes of registration lead,
and exposes a no-mutation preflight mode. The durable replacement is repository
owned and permits PASS only after an independent composite readiness assertion.

### 4. Future one-shot bindings were not revalidated

The August 17 wrapper correctly bound a boot-specific authorization and frozen
dependency hashes. Those guards protected the host at runtime, but status only
observed that the task was enabled and scheduled. A later reboot invalidated the
boot identity, and a later production integration changed a frozen helper. Both
conditions were knowable hours before the trigger.

Future non-recurring missions need a standard readiness manifest and a shared
pre-run assertion that can report `STALE_BOOT_IDENTITY` or
`STALE_DEPENDENCY_HASH` before the task fires.

### 5. A known documentation deadline had no early hard escalation

Canonical status saw the pending transaction after the 20:04 production merge,
but treated every pre-deadline pending state as a warning. The watchdog promotes
flags, not warnings, so it did not create an actionable alert until after the
09:00 deadline. The audit also called it a separate non-blocker and never
assigned a closeout plan.

The durable correction adds an action-required lead interval and promotes a
still-pending transaction before the deadline, while useful time remains.

### 6. A checker's `PASS` described itself, not the attempt

The host-local overnight checker emitted `check_status=PASS` even when its
separate `attempt_status` was `REVIEW_REQUIRED`. That is syntactically
explainable but operationally misleading. The local repair now reports
`checker_executed=true`, marks `action_required`, and exits nonzero for an
actionable attempt state.

### 7. Registration proof was mistaken for activation safety

The initial hardening still allowed a newly emitted `preparation: null` to use
the historical enabled-registration path. It also let an activator consume an
old readiness receipt without repeating the live topic/master, production
baseline, clean-worktree, and quiet-merge preflight checks. A crash or remote
advance between readiness and activation could therefore arm decayed premises.

The durable correction makes composite preparation mandatory for every newly
created attempt, creates both Scheduler definitions Disabled in their first
mutation, freshness-bounds the readiness receipt, and repeats every mutable
premise immediately before enable. Suite, merge, guarded merge, and closure
now require a successful live remote refresh where their classification or
mutation depends on it; stale tracking refs are never fallback authority.

### 8. The generic one-shot design trusted each payload wrapper

The first design validated metadata but still scheduled the mission wrapper
directly and relied on that wrapper to remember runtime assertion, workload
admission, child-tree containment, and teardown. Its active manifest was the
only deletion anchor, so crash debris and eventual cleanup had no independent
history. Source-string tests checked that guard names appeared but did not
exercise kill points between intent, publication, resolution, and deletion.

The replacement schedules one canonical guarded launcher. It holds a shared
registry lock, revalidates execution state, acquires the heavy lease when
needed, rehashes every dependency from a retained write/delete-denying handle,
and owns the payload in a kill-on-close Windows Job until the absolute
deadline. Writers and lifecycle tools take the exclusive lock. Independent
create-only manifest/resolution index events, receipt-first compaction, strict
activation recovery, and reviewed invalid-debris reconciliation make each
crash point either resumable or loudly contradictory. Status checks the active
and compacted supersession graph and rejects missing edges and cycles without
an arbitrary generation limit.

The retained handles close a race found during the final audit: the earlier
validator hashed stable snapshots but disposed them before helper dot-source
and payload launch. A concurrent replacement could therefore have executed
bytes that were not hashed. Rehashing from handles held through teardown makes
the validation-to-use boundary continuous, including for light one-shots that
do not acquire the heavy-work lease.

### 9. Verification emphasized lexical ratchets over state transitions

The earlier review proved that files parsed and contained expected guard
strings. It did not simulate wrong-case flags, duplicate aliases, stale remote
advances, process death after each durable write, resolution-before-index,
successor-before-resolution, receipt-before-delete, or a semantically invalid
predecessor with structurally valid pending bytes. That is why plausible code
survived review until Scheduler or an independent reviewer exercised the real
control flow.

The focused suite now includes behavioral subprocess fixtures for these
interleavings and the repository-owned integration preflight explicitly lists
the new preparation, readiness, registry, and status ratchets. The tests are
written but the full focused pytest execution remains deferred to the next
admitted host window.

## Controls that worked

- Exact-tip manifest, registration intent, receipt, and live task binding.
- The integration preflight stopped the full suite on deterministic failure.
- Absence of a PASS suite receipt prevented the merge consumer from mutating Git.
- Closure disabled the exact task pair and preserved immutable failure evidence.
- Recovery dispatch granted no automatic source, Scheduler, credential, or
  exchange authority.
- Boot and dependency guards stopped the stale settlement wrapper before child
  launch, workload-lease acquisition, or mutation.
- Production `HEAD`, `master`, and `origin/master` stayed synchronized.
- No credential value was read and no exchange endpoint or order path was used.

## Implemented long-term controls

- `prepare_integration_attempt.ps1` is the new preferred interactive entry
  point. It checks the complete schedule with at least ten minutes of lead
  before publication, freezes an intent, pushes one exact non-force refspec,
  verifies the live remote, creates and registers the immutable attempt, and
  returns PASS only after readiness, activation, re-attestation, and the final
  preparation receipt all succeed.
- Every exit-bearing creator, registrar, readiness, activator, and closer script runs in
  a contained child PowerShell process. An independent pre-commit review found
  and corrected the initial direct-call implementation, which otherwise could
  have let a child's `exit` terminate the preparer before its final receipt or
  cleanup path.
- A post-manifest preparation failure invokes the canonical closer and records
  the exact terminal closure receipt. Failure to prove both exact tasks
  terminal and disabled remains a loud blocker rather than a preparation
  result.
- Canonical status now separates `AWAITING_SUCCESSOR`,
  `SUCCESSOR_UNPUBLISHED`, `SUCCESSOR_UNREGISTERED`,
  `SUCCESSOR_WINDOW_MISSED`, `SUCCESSOR_ARMED`, and `SUCCESSOR_ACTIVE`.
  Unresolved states remain flags regardless of evidence age, and the JSON
  exposes `publication_required`, `unattended_ready`, and `next_action`.
- A generic read-only one-shot validator has separate pre-trigger and
  execution-entry modes. The only schedulable action is the canonical guarded
  launcher; v0.4 separately binds payload path/arguments plus launcher,
  validator, Job helper, and workload-admission hashes. The launcher holds
  registry/readiness authority, the heavy lease, kill-on-close containment,
  and the absolute deadline. Stable blockers such as `STALE_BOOT_IDENTITY` and
  `STALE_DEPENDENCY_HASH` remain visible before trigger.
- The generic registry now has a permanent create-only index, transactional
  activation, exact terminal/supersession resolutions, receipt-first reviewed
  compaction, and reviewed reconciliation for invalid successor-pending debris.
  Status uses bounded enumeration and verifies active/compacted identity,
  hashes, replacement bindings, missing edges, and cycles.
- New integration manifests cannot opt into the legacy path. Tasks are born
  Disabled; readiness writes deterministic execution authority; activation
  freshness-bounds and repeats live remote, baseline, worktree, and merge
  preflight proof before enable. Runtime and closure treat live fetch failure
  as fatal rather than trusting stale remote-tracking state.
- Documentation transactions now enter an action-required state two hours
  before their 09:00 deadline, and the watchdog treats that state as high
  severity instead of waiting for an overdue flag.
- The host-local resume helper was date-locked and reordered so complete
  schedule viability is checked before any push or Scheduler action. The
  host-local checker now distinguishes successful checker execution from an
  actionable attempt and exits nonzero for the latter.

These bytes are currently local only. The repaired credential descendant and
hardening must pass the deferred admitted-window tests, be published, and land
through one final v1 successor before the new preparer can own later attempts.
The new flow cannot truthfully bootstrap itself from production code that does
not yet contain it.

## Durable acceptance criteria

An overnight integration may be described as armed only when one composite
assertion proves all of the following at the same observation boundary:

1. the complete suite/merge schedule remains future with conservative setup
   lead;
2. the clean isolated worktree and exact local topic commit match;
3. the live remote topic and refreshed remote-tracking ref match that commit;
4. repair attempts bind and atomically claim the exact predecessor evidence;
5. manifest, registration intent, and PASS receipt validate;
6. both exact tasks are enabled, `Ready`, future, and have not already run;
7. no terminal or partial runtime evidence contradicts a fresh attempt; and
8. no operator action remains pending.

Dispatch-only recovery must remain a persistent blocking state. Future
boot/hash-bound one-shots must expose a machine-readable pre-run readiness
result. Documentation closeout must escalate before, rather than after, its
deadline.

## Verification boundary

Implementation continued in the 12:00--18:00 graded window, so verification is
limited to PowerShell parsing, Python AST parsing, diff checks, source ratchets,
and isolated tempfile behavior. Focused pytest, the repository-owned bounded
suite, documentation audit, and any exact integration attempt must wait for a
repository-admitted 00:30--09:00 host window. No production write, Scheduler
mutation, network publication, credential action, exchange contact, or live
order is part of this audit implementation.
