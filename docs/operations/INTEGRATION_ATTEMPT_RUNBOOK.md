# Immutable Integration Attempts

This runbook owns overnight branch integration. Its core rule is:

> Freeze an attempt, not the night.

An attempt binds one reviewed branch tip, one isolated worktree, one preflight,
one full suite, one guarded merge, and one evidence directory. Nothing may
rewrite or rebind that attempt. A failure is preserved, classified, and closed;
a reviewed repair or one bounded transient retry receives a new attempt id,
new task names, new logs, and new receipts.

This replaces host-local freeze-and-recovery prompts that treated the first tip
as immutable for the whole night. It does not weaken the exact-tip suite gate,
the 01:00-04:00 quiet-window gate, capture recovery, documentation transaction,
or `origin/master` acknowledgement.

## State machine

```text
REVIEWED TIP
    -> frozen manifest
    -> integration preflight
    -> exact full suite
    -> guarded quiet merge
    -> immutable PASS merge receipt
    -> separately authorized downstream work

Any failure
    -> immutable FAIL receipt
    -> disable exact tasks and write closure receipt
    -> reviewed recovery dispatch
    -> one atomic successor claim
    -> new attempt (exact same commit once, or a descendant repaired tip)
```

The full suite is confirmation, not discovery. The preflight runs the strict
schema registry, module ownership, import architecture, agent-document,
PowerShell-wrapper, roadmap, and UI-roadmap ratchets first. A preflight failure
never starts the full suite. A preflight PASS explicitly does not authorize a
merge.

## Repository-owned entry points

| Entry point | Responsibility |
| --- | --- |
| `new_integration_attempt.ps1` | Validate the exact clean worktree and reviewed tip; create a fresh manifest and evidence namespace. |
| `register_integration_attempt.ps1` | Register unique one-shot S4U/Limited suite and merge tasks. It starts nothing and creates no downstream task. |
| `integration_attempt_suite.ps1` | Run the deterministic integration preflight and then the exact full suite under bounded child-tree containment. |
| `integration_attempt_merge.ps1` | Require the suite task and immutable PASS receipt, then invoke `quiet_window_merge.ps1` and preserve its report. |
| `close_integration_attempt.ps1` | Disable the exact non-running attempt tasks and emit a closure receipt when a task crashed or the attempt is abandoned. |
| `dispatch_integration_attempt_recovery.ps1` | Bind a reviewed failure class to the closure hash and emit one machine-readable successor instruction; it edits no source and touches no task. |
| `assert_integration_attempt_success.ps1` | Revalidate manifest, receipt hashes, current `master == origin/master`, ancestry, and all three capture workers before downstream work. |

The shared schema, path, hash, and immutable-write rules live in
`integration_attempt_contract.ps1`. Attempt runtime evidence belongs in an
ignored host-local directory such as `data/integration_attempts/<date>/<id>`;
it is not assumed to exist in a clean checkout.

## Create and register attempt N

First obtain the roll verdict through the repository script, prepare an
isolated registered worktree, make it clean, and review the full commit SHA.
Do not derive roll sensitivity by hand.

Create the dated evidence parent yourself; `AttemptRoot` must not already
exist, and production `master` must equal `origin/master`. Then create the
immutable manifest:

```powershell
$attemptParent = Join-Path $PWD "data\integration_attempts\<date>"
New-Item -ItemType Directory -Path $attemptParent -Force | Out-Null
$attemptRoot = Join-Path $attemptParent "<attempt-id>"
.\scripts\ops\new_integration_attempt.ps1 `
  -AttemptRoot $attemptRoot `
  -AttemptId <attempt-id> `
  -BranchRef <branch> `
  -WorktreeRoot <isolated-worktree> `
  -ExpectedTip <full-reviewed-sha> `
  -SuiteAtLocal <local-datetime> `
  -MergeAtLocal <local-datetime> `
  -ReviewReference <pr-or-operator-review>
```

The suite trigger must be inside 00:30-09:00. The merge trigger must be inside
01:00-03:40 and at least 30 minutes after the suite trigger. The merge task does
not fail merely because a valid suite is still running at its trigger: it waits
without holding the heavy-work lease until the suite reaches terminal evidence,
or until the 03:40 merge reserve. A terminal FAIL stops immediately. If the
suite task is disabled without a receipt, the consumer fails immediately
instead of waiting out the window. A PASS receipt observed while Task Scheduler
still reports `Running` gets a bounded two-minute task-exit grace. If the task
is already non-running but its result still carries Scheduler's transient
`0x41301`/`0x41303`, the immutable PASS receipt is the stronger candidate
evidence: the consumer records the disagreement and proceeds only into the
existing full receipt/task-time validation. Any other nonzero result fails.
Otherwise at 03:40, or after the running-state grace expires, the merge
consumer re-verifies and stops only that attempt's exact suite task, waits for
it to leave `Running`, records the stop in the immutable merge receipt, and
fails the merge. The current merge window is then spent, but the contained test
tree cannot run until 09:00 and the attempt can be closed immediately for a
reviewed next-window successor.
Trigger times inside an invalid or ambiguous daylight-saving wall-clock hour
are refused at creation, manifest validation, and registration. Manifest
schedule values are local wall clocks and may not carry `Z` or a numeric offset.

The manifest freezes hashes for every repository-owned PowerShell dependency
used by registration, suite containment, workload admission, roll verdict,
merge, recovery dispatch, and downstream validation. An unreviewed helper
change between registration and execution therefore fails closed, not only a
change to the top-level wrapper. It also freezes the exact worktree's tracked
pytest-file count, 20-file chunk size, and derived chunk count; both the
full-suite plan line and final equal, nonzero `n/n` verdict must match that
inventory. Ignored or untracked `test_*.py` files cannot inflate the plan.

Record the printed manifest SHA256. Registration is an external scheduler
change and requires explicit operator authorization:

```powershell
.\scripts\ops\register_integration_attempt.ps1 `
  -ManifestPath <manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256>
```

The registrar refuses to replace an existing task. It registers the merge
consumer first: if suite registration then fails, the merge has no PASS receipt
to consume and cannot mutate the tree. `StartWhenAvailable` is deliberately
off; a missed task must not wake later in a protected window. The merge task's
four-hour execution limit contains the bounded suite-wait plus quiet-merge path.

## Success contract

The suite receipt is PASS only when both logs exist, their hashes match, the
preflight ends in its exact PASS verdict, and the full suite ends in its exact
all-chunks PASS verdict. Suite log timestamps are emitted with invariant
culture so their exact evidence format cannot drift with the task account's
regional time separator. The merge task independently verifies:

- the attempt tip contains the exact production baseline frozen at creation,
  production has exact `master` checked out, and HEAD/local/remote production
  do not advance during registration, preflight, full-suite execution, suite
  waiting, or guarded-merge entry;
- its own and the suite task's exact S4U/Limited action;
- the manifest path and SHA256 in both actions;
- the suite task's same-day success and receipt/run-time correlation;
- the unchanged branch tip and the current orchestration hashes, checked again
  after any bounded suite wait and immediately before child launch;
- the guarded quiet merge's `pushed` report and documentation transaction;
- source-tip ancestry, local/remote master equality, and three-worker capture
  recovery after publication.

The quiet-merge child receives the frozen baseline explicitly, rechecks it
inside its own process, and acquires the shared heavy-work lease before any Git
precondition or generated-config commit. This serializes all repository-owned
guarded merge drivers across the final baseline check and production mutation.
Its report carries structural merge-commit and documentation-transaction
fields; the attempt consumer does not infer either proof from a mutable log
phrase.

It copies the mutable latest quiet-merge report into the attempt directory and
hashes that immutable copy. Only a PASS `merge-receipt.json` plus its SHA256 is
downstream authority.

## Recover without losing the night

Never edit a failed manifest, append to its logs, replace its receipts, reuse
its task names, or move its task action to a new tip.

After any failed or crashed attempt, close it before creating a successor. This
also covers attempts that already have suite or merge FAIL receipts: closure is
the proof that every exact task is absent or disabled and can no longer race its
replacement.

```powershell
.\scripts\ops\close_integration_attempt.ps1 `
  -ManifestPath <failed-manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256> `
  -Reason <specific-failure> `
  -ReviewReference <operator-review>
```

The closer refuses while either task is running, refuses a PASS merge, verifies
both task actions and S4U/Limited principals against the immutable registration
receipt before disabling them, and preserves hashes of all evidence that
exists. It deliberately does not rebuild old task arguments through a possibly
changed helper, so a reviewed orchestration failure remains closable. Its
closure receipt is a FAIL receipt suitable for `-RepairOfReceiptPath`.
If registration created an exact task but its confirming read failed, the
receipt can say `registered = false` while the task exists. The closer still
disables that task only when every stored action/principal field matches, and
records the registration-receipt disagreement instead of leaving an armed task.

Hash that closure receipt, classify the failure, and write the reviewed dispatch:

```powershell
.\scripts\ops\dispatch_integration_attempt_recovery.ps1 `
  -ManifestPath <failed-manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256> `
  -ExpectedClosureReceiptSha256 <closure-receipt-sha256> `
  -FailureClass <transient_host|schema_registry|ownership_metadata|orchestration_wrapper|manual_reviewed_change> `
  -ReviewReference <operator-or-agent-review>
```

The dispatch is immutable and machine-readable. It maps the reviewed failure
class to one repair class, records the exact closure hash and allowed path
patterns, and explicitly grants neither automatic source edits nor scheduler
changes. It inventories current hashes against every frozen orchestration
binding. Because orchestration drift is itself a supported recovery case, this
explicit, non-scheduled recovery entry point records that drift instead of
requiring the failed orchestration set to remain executable; any detected drift
requires either the bounded `orchestration_wrapper` classification or the
explicitly reviewed `manual_reviewed_change` escape hatch. The mechanical
wrapper class reaches only the named item-329 attempt/merge PowerShell files,
their listed tests, and
`INTEGRATION_ATTEMPT_RUNBOOK.md`, `OPERATIONS_DESIGN.md`, `streak-soak.md`, and
the applicable agent guides; it cannot rewrite the reserved-window,
delegation, host-load, role, or state-of-play contracts.

A generic scheduler cannot safely review or repair code; same-night
deterministic recovery therefore requires an active operator or coding agent to
consume this dispatch. The dispatch removes ambiguity about the next action and
leaves one specific blocker when no safe successor is ready. `status.ps1`
surfaces `FAILED_NEEDS_CLOSE`, `CLOSED_NEEDS_DISPATCH`, `RECOVERY_READY`,
`SUCCESSOR_CLAIMED`, `MERGED_UNVERIFIED`, and `MERGED_RECONCILED` in human and
JSON output. A suite is missed only after a five-minute trigger grace when its
exact task has no current run and neither the preflight log nor a terminal
receipt exists; an actively running suite is not a false alarm. A suite that
did run but is now non-running without a receipt is a distinct actionable
failure. The same five-minute rule flags a non-running merge task after its
one-shot trigger when no merge or closure receipt exists, so an outage cannot
silently spend both triggers. It also flags unreadable task-bound
manifests/evidence. Actionable states are FLAGS for their first 24 hours, then
remain visible as warnings so immutable historical receipts cannot burn a
permanent alert.

Create attempt N+1 after classification:

| Repair class | Enforced scope |
| --- | --- |
| `retry_unchanged` | The exact same 40-character commit. Allowed once after a reviewed transient failure. |
| `schema_registry` | Additions or modifications only in the three static schema-registry shards. |
| `ownership_metadata` | The module ownership map and its exact ratchet test only. |
| `orchestration_wrapper` | Named item-329 attempt/merge PowerShell wrappers, their operation tests, and owning runbooks. Shared lease, roll-verdict, training, and unrelated status scripts require `manual_reviewed_change`. |
| `manual_reviewed_change` | A linked, explicitly reviewed change outside the mechanical classes. |

Every non-initial attempt must point to the predecessor's immutable closure
receipt and reviewed recovery dispatch. The new tip must descend from the
failed tip. Mechanical repair classes validate the Git name/status diff between
those two commits and cannot delete or rename files. `retry_unchanged` requires
commit-id equality, not merely an equal tree.

After all validation, the creator writes the successor manifest and atomically
creates `successor-claim.json` in the predecessor attempt. Registration and
execution revalidate that claim against both manifest hashes. A closure receipt
can therefore authorize only one successor, including under concurrent or
repeated recovery calls. An interrupted creator can leave an unclaimed manifest,
but that manifest is deliberately not registrable.

After the repair is committed, reviewed, and checked out cleanly in the
isolated worktree, call
`new_integration_attempt.ps1` with the new id, times, `-RepairClass`, and
`-RepairOfReceiptPath`, then register the new tasks.

An unchanged retry is for a classified timeout, resource refusal, scheduler
interruption, or other transient host failure. It is not a way to rerun a known
deterministic pytest failure. A retry attempt cannot itself receive another
transient retry, and the predecessor's single successor claim prevents sibling
retry fan-out. When that one retry also fails, diagnose or repair before
spending another attempt.

If the quiet-merge report proves `stage = pushed` and Git proves the frozen tip
is already in equal local/remote master, but a later final proof fails, the
receipt is `MERGED_UNVERIFIED`. This is deliberately not retryable: close and
dispatch refuse it because production already contains the tip. Preserve the
receipt and reconcile it only through:

```powershell
.\scripts\ops\reconcile_integration_attempt.ps1 `
  -ManifestPath <manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256> `
  -ExpectedMergeReceiptSha256 <merged-unverified-receipt-sha256> `
  -ReviewReference <operator-or-agent-review>
```

The reconciler revalidates the immutable publication evidence, exact checked-
out/local/remote history, current three-worker capture health, and both exact
task actions before disabling those tasks. It then writes a separate immutable
`MERGED_RECONCILED` receipt. It deliberately leaves
`historical_proof_upgraded = false` and `downstream_authorized = false`; current
health cannot manufacture the historical proof that was missing at merge time.
The original merge receipt stays `MERGED_UNVERIFIED`, so the downstream PASS
gate continues to refuse it. An ordinary FAIL means publication was not proven;
the two states must never use the same recovery recipe.

## Downstream gate

Do not pre-arm a held producer or other downstream mutation based on a planned
merge. After a PASS merge, hash the receipt and call the read-only validator at
the moment of adoption:

```powershell
.\scripts\ops\assert_integration_attempt_success.ps1 `
  -ManifestPath <manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256> `
  -ExpectedMergeReceiptSha256 <merge-receipt-sha256>
```

The execution-tape adoption wrapper accepts the same three attempt arguments
in addition to `ExpectedTip` and `MergeTaskName`. It retains the legacy
suite-gated path for already registered historical work. In attempt mode it
requires those two legacy identity arguments to equal the source tip and merge
task returned by the hash-bound attempt proof; an unrelated ancestor or copied
task action is not acceptable. No integration attempt reads credential values
or authorizes live exchange mutation. Receipts encode that static boundary as
`NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY`; they do not mislabel a hard-coded
boolean as a measured credential or exchange outcome.

## Verification and adoption

Before merging this procedure, parse every changed PowerShell file, run the
focused operation tests (including executable exact log-verdict, semantic
PowerShell binding, disabled/PASS-grace wait decisions, recovery-dispatch,
successor-claim, caller-level suite status, reconciliation, schedule-boundary,
and tamper cases), the documentation audit, roadmap lint,
compileall, and the exact full suite in an admitted heavy-work window. Editing
these files does not register, disable, start, or delete any host task. The
first landing of this machinery must use the established guarded merge path,
because production cannot freeze hashes for attempt scripts that do not exist
there yet. Adopt the registrar only afterwards and under separate explicit
scheduler authorization.

## Update when

Update this runbook when attempt schemas, repair classes, task identity,
evidence filenames, time windows, suite ordering, merge proof, or downstream
authority changes.
