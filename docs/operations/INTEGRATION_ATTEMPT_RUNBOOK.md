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
    -> immutable pre-registration intent
    -> exact task registration receipt
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
| `register_integration_attempt.ps1` | Journal, register, and read-back attest unique one-shot S4U/Limited suite and merge tasks. It starts nothing and creates no downstream task. |
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
is `Queued`, `Unknown`, or otherwise non-terminal, the consumer keeps waiting
before the reserve but cannot consume PASS evidence from that state. If the
task is already terminal but its result still carries Scheduler's transient
`0x41301`/`0x41303`, the immutable PASS receipt is the stronger candidate
evidence: the consumer records the disagreement and proceeds only into the
existing full receipt/task-time validation. Any other nonzero result fails.
Otherwise at 03:40, or after the running-state grace expires, the merge
consumer re-verifies and stops only that attempt's exact suite task, waits for
Task Scheduler to report `Ready` or `Disabled`, records the stop in the
immutable merge receipt, and fails the merge. The current merge window is then
spent, but the contained test tree cannot run until 09:00 and the attempt can
be closed immediately for a reviewed next-window successor.
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
inventory. The runner rechecks the worktree tip, movable branch ref, clean
status, and tracked test inventory after the final chunk and before PASS.
Ignored or untracked `test_*.py` files cannot inflate the plan. Immutable
attempts reject `AdditionalPythonPath`: ambient Python trees can change without
changing the reviewed commit. The general bounded runner retains that option
only for explicitly reviewed diagnostic work outside this attempt workflow.

The adopted bounded runner sets `WEATHER_INTEGRATION_TEST_OFFLINE=1` before
candidate Python starts, limits descendant Git transport to local `file`
remotes, disables Git credential prompting, and restores every inherited
environment value in `finally`. This is also the bootstrap boundary for a
candidate that strengthens the test sandbox itself: unmerged code may enforce
the marker, but it may not be the component that grants its own marker.

Record the printed manifest SHA256. Registration is an external scheduler
change and requires explicit operator authorization:

```powershell
.\scripts\ops\register_integration_attempt.ps1 `
  -ManifestPath <manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256>
```

Before touching Scheduler, the registrar creates an immutable
`registration-intent.json` containing the exact user, actions, one-shot
triggers, wake and battery behavior, execution limits, and all other relevant
settings. Read-back attestation also requires each trigger's numeric UTC offset
to match the host time zone at that unambiguous frozen wall clock. Runtime
wrappers and recovery bind both tasks to that intent and the
registration receipt. The registrar refuses to replace an existing task. It
registers the merge consumer first: if suite registration then fails, the merge
has no PASS receipt to consume and cannot mutate the tree; the pre-mutation
intent remains sufficient authority to disable only a task whose complete
identity matches. `StartWhenAvailable` is deliberately off and `WakeToRun` is
on. The merge task's four-hour execution limit contains the bounded suite-wait
plus quiet-merge path.
Registration holds the attempt terminal mutex from its closure/reconciliation
check through intent, Scheduler mutation, receipt, and final readback. Suite and
merge entry also refuse an attempt that already has either terminal receipt.

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
- its own and the suite task's exact user/S4U/Limited principal, action,
  one-shot trigger, and complete fail-closed settings;
- the manifest path and SHA256 in both actions and the hash-bound registration
  intent/receipt behind them;
- the suite task's same-day success and receipt/run-time correlation;
- the unchanged branch tip and the current orchestration hashes, checked again
  after any bounded suite wait and immediately before child launch;
- the guarded quiet merge's schema-validated `pushed` report, documentation
  transaction, core capture recovery, and execution-tape recovery whenever its
  loaded-module closure rolls;
- source-tip ancestry, local/remote master equality, and three-worker capture
  recovery after publication.

The quiet-merge child receives the frozen baseline and the attempt's unused
canonical report path explicitly, rechecks both inside its own process, and
acquires the shared heavy-work lease before any Git precondition or generated-
config commit. This serializes all repository-owned guarded merge drivers
across the final baseline check and production mutation. The child creates the
attempt-local report atomically and never copies evidence back out of the
mutable latest-report slot. Its report binds the original baseline, optional
generated-config commit, exact merge commit, documentation transaction,
affected-producer recovery, and publication acknowledgement.
The frozen orchestration set also includes both boot recovery and its task
registrar, so a changed startup delay or task action invalidates the attempt
instead of silently weakening crash recovery.

During mutation it also maintains
`data/alerts/quiet_window_merge_in_progress.json`. Boot recovery uses that
marker to abort an unverified merge back to the exact baseline while preserving
only the two allowlisted generated config contents, or to hold a recovery-
proved commit for reconciliation. A `merge_committed_unpublished` marker means
recovery passed and the exact two-parent commit exists, but the documentation
transaction may not yet have begun; it is never safe to edit or delete that
marker manually. `status.ps1` warns on a fresh marker and
flags one stale for more than 30 minutes. Only a PASS `merge-receipt.json` plus
its SHA256 is downstream authority.
If the child is killed after committing but before it can create the canonical
report, the parent deliberately withholds its generic FAIL receipt when the
unchanged marker, current Git, and exact two-parent merge all bind this attempt.
That leaves the stronger marker reachable through reviewed reconciliation
instead of letting a weaker FAIL receipt incorrectly outrank it.

## Recover without losing the night

Never edit a failed manifest, append to its logs, replace its receipts, reuse
its task names, or move its task action to a new tip.

After any failed or crashed attempt that did not leave a recovered integration
commit, close it before creating a successor. This normally includes attempts
that already have suite or merge FAIL receipts: closure is the proof that every
exact task is absent or disabled and can no longer race its replacement. The
exception is any exact `merged_unpushed` report that proves a recovered commit,
whether or not origin has acknowledged it yet, plus any matching post-commit
active marker. A hash-bound FAIL receipt may accompany the report. These
attempts must use reviewed publication resume/reconciliation below, not closure;
loss or rollback of the marker/current ref does not erase their durable commit
history or make a retry safe.

```powershell
.\scripts\ops\close_integration_attempt.ps1 `
  -ManifestPath <failed-manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256> `
  -Reason <specific-failure> `
  -ReviewReference <operator-review>
```

The closer refuses while either task is running and refuses a PASS merge. For a
new attempt it verifies each root task's complete action, current-user
S4U/Limited principal, one-shot trigger, and settings against the immutable
registration intent before disabling it. A valid final receipt must hash that
intent; if the receipt is absent or torn, the independently manifest-derived
intent remains sufficient to close only the exact task and the discrepancy is
recorded. Legacy attempts without an intent retain their prior action/principal
close contract so an orchestration upgrade cannot strand them. The closer
preserves hashes of all evidence that exists, including the registration
intent. Before disabling tasks it always proves the production checkout is
branch `master`, with `HEAD`, local `master`, and `origin/master` at the
attempt's frozen baseline, and proves the frozen source tip is absent from both
local and remote master. Missing terminal merge evidence never substitutes for
that Git non-integration proof. After disabling, it refuses any task that is not
still exactly absent or terminal+Disabled (disabling does not stop an already
running instance), then immediately repeats the marker, `MERGE_HEAD`, checked-
out branch, baseline, and source-ancestry proofs before writing the receipt. The
post-disable proof is recorded in the closure receipt, which is a FAIL receipt
suitable for `-RepairOfReceiptPath`.
The closer holds the same OS-backed `heavy_workload.lock` used by guarded merge
drivers from its first production classification through that receipt, plus the
attempt terminal mutex shared with registration/reconciliation. An ad-hoc merge
or terminal classifier therefore cannot enter the last proof-to-receipt gap.
If registration created an exact task but its confirming read failed, the
receipt can say `registered = false` while the task exists. The closer still
disables that task only when every intent-bound identity field matches, and
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
failure. Status rechecks receipt existence after sampling the suite task, so a
receipt published during the status scan suppresses that interrupted-suite
alert while unreadable evidence retains its separate flag. The same five-minute
rule flags a non-running merge task after its
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

If publication is proven but the parent cannot finish its final receipt, the
attempt is `MERGED_UNVERIFIED`. The immutable input can be a
`MERGED_UNVERIFIED` merge receipt, the exact attempt-local `pushed` report when
the parent was killed before its receipt, or when production advanced after the
child released its merge lease but before the parent sampled refs, or the
SHA256-bound active marker at
phase `documented_unpublished`/`published` when Git independently proves
`HEAD == master == origin/master == marker.merge_commit`. It can also be the
exact FAIL merge receipt that hash-binds a v0.2 `merged_unpushed` report with
capture, conditional execution-tape, and documentation recovery proved. That
last form is accepted only after a separately reviewed push makes
`HEAD == master == origin/master == report.merge_commit` and Git proves the
frozen source tip is an ancestor. The active marker may help recovery but is
not required when the immutable FAIL receipt/report pair exists. This is deliberately
not retryable: close and dispatch refuse it because production already
contains the tip. Reconcile by supplying exactly one evidence hash:

```powershell
.\scripts\ops\reconcile_integration_attempt.ps1 `
  -ManifestPath <manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256> `
  -ExpectedMergeReceiptSha256 <merged-unverified-receipt-sha256> `
  -ReviewReference <operator-or-agent-review>
```

The same `-ExpectedMergeReceiptSha256` parameter accepts either the original
`MERGED_UNVERIFIED` receipt or that narrow recovered-unpushed FAIL receipt. Use
`-ExpectedQuietMergeReportSha256` when no merge receipt exists, or
`-ExpectedActiveMarkerSha256` for the narrower marker case. A marker-based
reconciliation consumes that global marker only after current Git, capture,
task, manifest, suite, documentation, and conditional execution-tape proofs
pass; the reconciliation receipt embeds its exact raw text and hash.
For attempts poisoned by the former retry behavior, only the exact same-attempt
`abort` report whose detail is the pre-existing-marker refusal, with no commit,
capture, documentation, or publication proof, may be subordinated to the
stronger post-commit marker. Its exact generic FAIL receipt, abort bytes, and
hash remain bound as weaker evidence; no other FAIL/abort form is accepted.

The reconciler revalidates the immutable publication evidence, exact checked-
out/local/remote history, current three-worker capture health, and both exact
task actions before disabling those tasks. It then writes a separate immutable
`MERGED_RECONCILED` receipt. It deliberately leaves
`historical_proof_upgraded = false` and `downstream_authorized = false`; current
health cannot manufacture the historical proof that was missing at merge time.
Any original merge receipt or report stays unchanged, and every reconciliation
form remains non-authorizing, so the downstream PASS gate continues to refuse
it. An ordinary FAIL without that recovered-unpushed proof means publication
was not proven; the two states must never use the same recovery recipe. Status
reports the strictly validated exceptional form as `MERGED_RECONCILED`, while
the original FAIL receipt remains unchanged and non-authorizing.
Every reconciliation form takes the guarded-merge `heavy_workload.lock` before
it reads terminal evidence and holds it through receipt publication and marker
retirement. This includes idempotent cleanup after an already-published receipt,
so reconciliation cannot race the quiet child between its published marker and
immutable report.

A power loss after the recovery-proved commit but before documentation uses an
explicit reviewed resume rather than manual Git or marker edits:

```powershell
.\scripts\ops\reconcile_integration_attempt.ps1 `
  -ManifestPath <manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256> `
  -ExpectedActiveMarkerSha256 <merge-committed-marker-sha256> `
  -ReviewReference <operator-or-agent-review> `
  -ResumePublication
```

`-ResumePublication` also accepts an exact recovered-unpushed FAIL receipt, or
a `merged_unpushed` report only when no receipt or active marker exists. In
addition to the already-held shared mutex, it enforces the repository-owned
heavy-work time window; rederives the baseline/preparation and exact
two merge parents; rechecks core capture and, when required, the canonical
execution-tape status, writer lock, process identity, source identity, and
evidence integrity; idempotently begins the documentation transaction if the
marker had not recorded it; then invokes `WeatherOneShotPush`. Only exact
`HEAD == master == origin/master == merge_commit` permits the non-authorizing
reconciliation receipt. Marker phase transitions are atomic, and the marker is
retired only after that receipt exists, so another interruption remains
recoverable from immutable evidence.
Immediately before starting the push task, the reconciler re-hashes the immutable
report, current marker, and documentation snapshot and revalidates the exact
exported `WeatherOneShotPush` definition, including its empty trigger set. A
concurrent evidence or task-definition change therefore cannot cross the push
boundary.

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
task action is not acceptable. The gate also requires the production checkout
itself to be branch `master` with `HEAD == master == origin/master`; equality of
the two refs without the checked-out branch is insufficient. No integration attempt reads credential values
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
