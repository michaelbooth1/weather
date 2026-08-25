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
    -> credible future schedule and immutable preparation intent
    -> exact non-force topic publication and remote acknowledgement
    -> exact pre-arming integration preflight and full-suite PASS qualification
    -> revalidated live refs, baseline, worktree, and helper hashes
    -> frozen manifest
    -> immutable pre-registration intent
    -> exact tasks registered Disabled and registration receipt
    -> immutable readiness PASS receipt and manifest-bound execution token
    -> exact task activation and final preparation PASS receipt
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

## Authority lifecycle audit matrix

Review the full row whenever a phase changes. A check in an earlier row is not
authority for a later row, and no mutable value may be sampled once and carried
across a mutation boundary.

| Phase | Authoritative inputs | Last recheck before authority/mutation | Immutable or retained proof | Fail-closed outcome |
| --- | --- | --- | --- | --- |
| Topic publication | canonical origin URL, exact topic commit, expected baseline | live topic acknowledgement plus live master; local clean exact worktree | exact non-force push result and canonical `ls-remote` bytes | no attempt namespace or task |
| Pre-arm qualification | exact worktree/tip, creator-frozen inventories, production baseline, deterministic environment/toolchain | complete local/live/local Git tuple, ignored import/config namespace, helper hashes before and after both runs | retained stdout/stderr/JUnit generations, plan, fingerprints, logs, PASS receipt | no manifest or Scheduler mutation |
| Manifest creation | qualification PASS, reviewed recovery/claim when applicable, future schedule | two complete authority tuples including live refs, worktree, inventories, ignored namespace | create-only manifest and predecessor claim | incomplete namespace is non-registrable and closable |
| Disabled registration | manifest, intent, exact task XML contract | remote/baseline/worktree/qualification plus absent task names immediately before registration | create-only intent and read-back registration receipt | disable only exact created tasks; record partial failure |
| Readiness and activation | registration PASS, exact disabled future tasks | full authority tuple before readiness receipt, again before token, before first enable, and before final PASS | readiness receipt, one exact execution token, final preparation receipt | roll back exact tasks to Disabled; never infer PASS |
| Overnight suite | manifest, token, qualification inventory/fingerprint | exact task/date window, source/ref/baseline/helper hashes before each phase and all mutable inventories after final chunk | repeated retained logs/JUnit/fingerprints and suite receipt | terminal FAIL; merge cannot start |
| Quiet merge | suite PASS, exact baseline/topic, roll verdict, capture identities | canonical live refs, origin/Git controls, clean production, task and immutable evidence immediately before Git mutation and push | mutation journal, report, documentation snapshot, recovery proof | recover baseline or preserve one reviewed unpublished state |
| Publication and downstream | recovered merge commit and exact push task | `HEAD == master == origin/master`, canonical remote acknowledgement, capture and required auxiliary producer health | PASS merge receipt and separately checked downstream assertion | `MERGED_UNVERIFIED`/reconciliation; no downstream authority |
| Closure/reconciliation | exact terminal evidence and exact task pair | one Scheduler snapshot plus post-disable Git/evidence recheck under mutex | create-only closure, retirement, or reconciliation receipt | frozen blocker; never retry or overwrite in place |

For every row, review identity, bytes, time, process lifetime, external I/O,
Scheduler state, cleanup, and crash recovery as separate failure dimensions.
Every defect found in one dimension requires a positive regression and an
adversarial refusal regression; source-string assertions alone do not close a
row.

The scheduled full suite is confirmation, not first discovery. Before a
manifest or task can exist, the preparer runs both the exact integration
preflight and bounded full suite against the published tip. The preflight runs the strict
schema registry, module ownership, import architecture, agent-document,
PowerShell-wrapper, roadmap, and UI-roadmap ratchets first. A preflight failure
never starts the full suite. A preflight PASS explicitly does not authorize a
merge. The scheduled wrapper repeats both runs for environment drift and may
PASS only when its inventories and aggregate JUnit counts match qualification.

## Repository-owned entry points

| Entry point | Responsibility |
| --- | --- |
| `prepare_integration_attempt.ps1` | Preferred interactive entry point: inside 00:30-09:00, validate a later-date schedule, publish and qualify one exact tip, then create/register the attempt and, under a separate exact activation confirmation, enable its task pair before returning the final durable readiness result. |
| `assert_integration_attempt_ready.ps1` | Require the live exact remote tip, clean exact worktree, baseline, successor claim, disabled registration evidence, future task bindings, and absence of runtime/terminal evidence; write the immutable readiness receipt and exact execution token. |
| `new_integration_attempt.ps1` | Validate the exact clean worktree and reviewed tip; create a fresh manifest and evidence namespace. |
| `register_integration_attempt.ps1` | Journal, register, and read-back attest unique one-shot S4U/Limited suite and merge tasks. Composite preparation uses `-StageDisabled`; it starts nothing and creates no downstream task. |
| `activate_integration_attempt.ps1` | Under the terminal mutex, require the exact readiness PASS/token and the separate exact activation literal, enable merge then suite, re-attest both exact future bindings, and write the immutable final preparation PASS receipt. |
| `integration_attempt_suite.ps1` | Run the deterministic integration preflight and then the exact full suite under bounded child-tree containment. |
| `integration_attempt_merge.ps1` | Require the suite task and immutable PASS receipt, then invoke `quiet_window_merge.ps1` and preserve its report. |
| `close_integration_attempt.ps1` | Disable the exact non-running attempt tasks and emit a closure receipt when a task crashed or the attempt is abandoned. |
| `retire_integration_attempt_tasks.ps1` | Disable only the exact receipt-bound task pair of an already successful historical attempt; preserve PASS and emit a separate immutable retirement receipt. |
| `retire_legacy_integration_bootstrap_task.ps1` | Narrowly retire one of the two expired pre-manifest bootstrap tasks using its complete XML hash and exact terminal run evidence. |
| `dispatch_integration_attempt_recovery.ps1` | Bind a reviewed failure class to the closure hash and emit one machine-readable successor instruction; it edits no source and touches no task. |
| `assert_integration_attempt_success.ps1` | Revalidate manifest, receipt hashes, current `master == origin/master`, ancestry, and all three capture workers before downstream work. |

The shared schema, path, hash, and immutable-write rules live in
`integration_attempt_contract.ps1`. Attempt runtime evidence belongs in an
ignored host-local directory such as `data/integration_attempts/<date>/<id>`;
it is not assumed to exist in a clean checkout.

## Prepare, create, and register attempt N

First obtain the roll verdict through the repository script, prepare an
isolated registered worktree, make it clean, and review the full commit SHA.
Do not derive roll sensitivity by hand.

Create the dated evidence parent yourself. `AttemptRoot` must be exactly
`<RepoRoot>/data/integration_attempts/<suite-date>/<attempt-id>` and every
existing ancestor must be a non-reparse directory. `AttemptRoot` and its sibling
`<AttemptRoot>.preparation` must not already exist, and production `master`
must equal both refreshed `origin/master` and the live `refs/heads/master`.
After each root is created, v2 creator, registration, readiness, activation,
suite, and merge mutation boundaries revalidate the exact dated path and every
directory from `RepoRoot` through both roots. A junction or other reparse point
introduced after the initial precheck is a hard failure.
With three independent explicit authorities--exact topic publication, Disabled
Scheduler registration, and activation of the exact registered task pair--run
the preferred entry point from the user's interactive Windows session so Git
can use the credential vault:

```powershell
.\scripts\ops\prepare_integration_attempt.ps1 `
  -AttemptRoot <fresh-attempt-root> `
  -AttemptId <attempt-id> `
  -BranchRef origin/<topic-branch> `
  -WorktreeRoot <isolated-worktree> `
  -ExpectedTip <full-reviewed-sha> `
  -SuiteAtLocal <local-datetime> `
  -MergeAtLocal <local-datetime> `
  -ReviewReference <pr-or-operator-review> `
  -RepairClass <initial-or-reviewed-repair-class> `
  -RepairOfReceiptPath <predecessor-closure-receipt-if-required> `
  -PublicationConfirmation AUTHORIZE_EXACT_NON_FORCE_TOPIC_PUBLICATION `
  -SchedulerConfirmation AUTHORIZE_DISABLED_INTEGRATION_TASK_REGISTRATION `
  -ActivationConfirmation AUTHORIZE_EXACT_INTEGRATION_TASK_ACTIVATION
```

A recovery dispatch, branch commit, review reference, or earlier approval does
not satisfy any of the three confirmation literals. Each literal authorizes
only its named boundary in that exact invocation; none grants broader or later
network/topic-publication, Scheduler, credential, exchange, or production
authority.

Preparation may start only inside 00:30-09:00, no later than 07:20, and the
suite date must be later than the preparation date. The 07:20 boundary reserves
the full 90-minute qualification ceiling plus its ten-minute safety margin
before qualification's independent 09:00 kill-on-close hard stop. Before
publication, the schedule must contain the
larger of the measured qualification duration and a 90-minute planning ceiling,
plus a ten-minute safety margin for execution and a separate frozen five-minute
Scheduler launch grace, before both merge and 09:00 (105 minutes with the
default ceiling). The scheduled suite may launch only from its exact trigger
through that five-minute grace and must still retain the full execution reserve
from its actual start. The preparer also
requires ten minutes of ordinary lead and rechecks after qualification and
before registration; final PASS requires five minutes. One host-global open file
handle serializes preparation, and the preparer refuses while any other
integration suite or merge task is enabled.

All schedule interpretation uses the Windows time-zone rule set identified as
`Eastern Standard Time`; that is a scheduling clock, never evidence that the
host is physically in Ontario. The suite's shared execution budget is 5,400
monotonic seconds. Its Scheduler task limit is 5,700 seconds (`PT1H35M`),
leaving a 300-second child-tree teardown allowance, and 09:00 remains an
independent wall boundary. Preparation children freeze their own monotonic
allowance at launch as well as checking the wall deadline, so a backward clock
correction cannot extend them. Before and during qualification, each distinct
volume holding production, candidate, logs/evidence, temporary pytest state, or
Python cache must retain at least 50 GiB free.

At the preparation boundary the
new attempt's two exact task names must not exist at all; readiness and
activation recognize those names only after the registrar has created their
exact Disabled bindings. Every other Disabled integration task requires exact
terminal retirement or FAIL-closure evidence even when demand start is already
disallowed; manual disablement is not successor authority. Before publication it runs the
canonical creator in non-publishing `PreflightOnly` mode, covering worktree/test
inventory, repair ancestry and allowlist, predecessor-claim, baseline, and
orchestration-file validation. It reruns the ordinary creator after exact
publication and fetch so every premise, including `origin/<topic-branch>`, is
checked again immediately before immutable manifest creation. The prepublication
`PreflightOnly` process also runs in a separate kill-on-close Job with a fresh
frozen five-minute hard stop. It writes its exact plan create-only to canonical
`<AttemptRoot>.preparation/creator-preflight-plan.json`; stdout is not evidence.
The preparer retains one bounded snapshot and SHA-256, and the ordinary creator
must consume and revalidate that exact plan, including its creator and shared
preparation-contract hashes, before it may freeze the manifest.
The v2 manifest retains that canonical plan path and SHA-256. Runtime
preparation validation reopens one bounded snapshot and rejects drift, while
structural cleanup validation checks only the path/hash shape so lost evidence
cannot make exact closure unreadable.
Creator state sampling binds the exact tracked test, Python-source, and
PowerShell-source inventories, then closes with a complete branch/HEAD/master/
origin/topic and worktree HEAD/status tuple re-read. Both creator plan and
manifest publication are immediately sandwiched by the complete canonical live
topic/master plus local/worktree/inventory/ignored-namespace observation.
Readiness and activation
also reject ignored source, bytecode, native-extension, and test-configuration
shadows at their last mutation/receipt boundaries.
The ordinary creator, registrar, readiness assertion, activator, and failure
closer each receive their own fresh Job and five-minute hard stop as well. A
preparer crash closes the current Job handle and kills the child tree; a live
hang reaches the hard stop and returns through canonical failure/closure
handling. Each completed or stopped child is explicitly terminated as a Job,
and output is accepted only after Job accounting reports zero active processes
and the checked handle close succeeds. Its bounded stdout/stderr remain held
against write/delete replacement through that proof; the preparer then retains
strict-UTF-8 bytes and SHA-256 for useful failure diagnostics and removes those
owned transient files. Those diagnostics are never authority in place of the child's
create-only JSON evidence. Each verified child script remains open with
read-only sharing across hashing and the entire child lifetime, denying a
write/delete/rename swap before `powershell.exe -File` reopens it. It freezes a sibling
`preparation-intent.json`, publishes only
`<exact-sha>:refs/heads/<topic-branch>` without force, verifies the exact live
`ls-remote` result against the frozen URL, refreshes `origin/<topic-branch>`, and
only then invokes the
creator and registrar below. Before either, it runs the preflight and full suite
in a kill-on-close Job bounded by 09:00. The immutable qualification binds both
logs/verdicts, the worktree import hash, tracked Python/PowerShell syntax
inventories, both `test_*.py` and `*_test.py` inventories, every parsed JUnit,
and measured duration. Ambient Git/Python/pytest controls, shallow or replaced
history, malformed tracked source, all-skipped/deselected chunks, and deletion
of a baseline test fail closed. Live/MM diffs require the live-SDK contract.
After qualification the preparer rehashes helpers and revalidates live refs,
baseline, clean worktree, and quiet-merge prerequisites immediately before
manifest creation. The registrar creates both tasks Disabled. Immediately
before each individual Disabled `Register-ScheduledTask`, it repeats the strict
v2 canonical live topic/master, production/local tracking refs, registered
worktree status and inventories, ignored import/control namespace, and
immutable authority binding. Its
final assertion independently revalidates the remote, manifest (including the
predecessor's single successor claim), clean worktree, live production
baseline, PASS registration evidence, exact Disabled future task definitions,
and absence of suite/merge/closure evidence. It then writes a readiness PASS receipt and
the deterministic execution token whose path and SHA-256 were frozen in the
manifest. Only after that token exists does the activator accept the readiness
receipt within its two-minute transaction boundary, repeat the live topic and
master queries, production baseline, clean registered worktree, and exact
quiet-merge preflight, then enable and re-attest both tasks and atomically write
the final preparation PASS receipt. Every frozen creator, registrar,
readiness, activator, and closer script is hash-checked immediately before it
runs in a contained child process, so a child's `exit` cannot terminate the
preparer or bypass its closure/result path. Only that
activator writes `preparation-receipt.json` with status `PASS`; wrappers for a
composite-prepared manifest require both its exact execution token and its
post-enable final preparation receipt before doing any work. A hard stop after either
registration or enable therefore leaves tasks that are Disabled or wrappers
that fail closed. A failure records
its terminal stage and never reports PASS. If a manifest already exists, the
preparer invokes the canonical closer before publishing its FAIL result and
records the exact closure receipt hash; it reports task terminality as unproved
if closure cannot disable and prove every exact task. A preparation evidence
directory is immutable and spent even when manifest creation has not begun;
use a new attempt id after review rather than deleting or rewriting it.
The creator, registrar, closer, readiness, and activator entry points run in contained
Windows PowerShell child processes, so any child `exit` becomes a checked
result and cannot bypass the preparer's receipt or closure path.

The frozen repository identity is a transport contract, not merely the text of
`remote.origin.url`. Current attempts refuse any effective
`remote.origin.pushurl`, `url.*.insteadOf`, or `url.*.pushInsteadOf` rule from
system, global, local, worktree, or command scope. Exact live ref checks run
outside a repository with system/global Git configuration disabled and use the
canonical HTTPS URL directly. Topic publication and fetch use that URL rather
than the symbolic remote name. Immediately before a manifest-bound guarded
merge, the quiet-merge child independently requires the canonical live topic
head to equal the frozen expected tip and canonical live master to equal the
frozen baseline, then fetches both with explicit refspecs into their exact
`refs/remotes/origin/...` tracking refs. A successful URL-only fetch into
`FETCH_HEAD` is not remote-tracking evidence. The credential-bearing production push remains
the reviewed `WeatherOneShotPush` task, but a merge cannot record `pushed`
until an independent post-push canonical-URL query proves the exact new master
tip. Every bounded remote child timeout invokes Windows Job-tree termination and
accepts cleanup only after Job accounting reports zero active processes and its
non-inheritable handle closes successfully; an unproved descendant teardown is
a distinct fail-closed error. Remote children are created suspended, assigned
to that Job before resume, and expose bounded stdout/stderr through retained
handles that deny write/delete replacement until the exact bytes are parsed.
The ephemeral backing files are deleted after the retained handles close.
Canonical-origin inspection, every bounded remote operation, and quiet-merge
entry also refuse ambient Git identity/object/config, executable, TLS, askpass,
SSH/proxy, and trace controls before any load-bearing Git command.

The creator and registrar remain canonical internal primitives, but they are
not standalone operator shortcuts. Every new manifest requires
`-RequirePreparationAuthorization` plus the exact preparer-created intent path
and hash. Every registration requires `-StageDisabled`, a valid
manifest-bound execution-authorization plan, and proof that its token does not
exist yet. Readiness creates that token only after disabled registration is
fully attested; activation and both runtime wrappers then require it.
Immediately before enabling the exact pair, activation also requires the
independent literal
`AUTHORIZE_EXACT_INTEGRATION_TASK_ACTIVATION`; the readiness token and Disabled
registration literal are not activation authority. Omitting any of those values
or presenting a premature token is a hard failure. A
reviewed bootstrap of the preparer itself must use the already
production-adopted predecessor workflow; not-yet-landed bytes cannot attest
themselves. After this contract is production-adopted, use the preparer command
above for every new attempt rather than reconstructing its internal calls.
New writers emit `weather_integration_attempt_manifest_v2`, with mandatory
qualification hash, execution reserve, Scheduler launch grace, and total
schedule reserve. Explicit v1 manifests remain readable.
Structural manifest validation never dereferences qualification or predecessor
files, preserving exact-task closure after evidence loss; registration,
readiness, activation, and runtime boundaries perform strict validation.
Load-bearing text and JSON evidence is read once through a bounded regular-file
handle that permits read sharing only. Empty evidence, oversized evidence, and
invalid UTF-8 are rejected; parsing and SHA-256 always use the retained bytes
from that same open. Structural v1 reads and the exact closure path deliberately
do not acquire the new v2 runtime-root precondition.

The suite trigger must be inside 00:30-09:00. The merge trigger must be inside
01:00-03:40 and at least 30 minutes after the suite trigger. Both tasks disallow
demand start, and both wrappers reject any local calendar date other than the
immutable manifest date. A missed one-shot therefore requires closure and a
reviewed successor; it cannot be resurrected manually on a later day. The merge
task does not fail merely because a valid suite is still running at its trigger: it waits
without holding the heavy-work lease until the suite reaches terminal evidence,
or until the 03:40 merge reserve. A terminal FAIL stops immediately. If the
suite task is disabled without a receipt, the consumer fails immediately
instead of waiting out the window. A validated PASS receipt observed while Task Scheduler
still reports `Running` gets a bounded two-minute task-exit grace measured
from the receipt's immutable completion time, not from the 03:40 reserve. If the task
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
Lead time, suite-to-merge spacing, launch grace, protected-merge overlap, and
the reserve to the local 09:00 hard stop are measured between timezone-offset
instants, not by subtracting wall clocks. A spring-forward hour therefore never
counts as execution reserve. Historical v1 manifests retain their structural
wall-clock schedule check so exact closure evidence remains readable.
Canonical close/rollback also accepts only exact `Ready` or `Disabled` task
states; `Queued`, `Running`, `Unknown`, and future states are not terminal proof.
The suite wrapper's 09:00 hard stop and merge wrapper's 05:00 outer stop
explicitly terminate their child Jobs, require Job accounting to report zero
active processes, and require the handle close to succeed before reporting the
boundary failure. The same descendant-empty proof is required after an ordinary
wrapper exit before its exit code or evidence can be accepted.

The manifest freezes hashes for every repository-owned PowerShell dependency
used by registration, suite containment, workload admission, roll verdict,
merge, recovery dispatch, and downstream validation. An unreviewed helper
change between registration and execution therefore fails closed, not only a
change to the top-level wrapper. It also freezes the exact worktree's tracked
test, Python-source, and PowerShell-source inventory counts and SHA-256 values,
20-file chunk size, derived chunk count, and measured repeat reserve; both the
full-suite plan line and final equal, nonzero `n/n` verdict must match that
inventory. Every hash-bound JUnit must independently parse, contain an executed
test, and report zero failures, errors, and deselections. The runner rechecks the worktree tip, movable branch ref, clean
status, and tracked test inventory after the final chunk and before PASS.
The bounded runner is the sole owner of the deterministic integration-preflight
file list. Qualification consumers derive that mode's file and chunk counts
from the same retained plan/log snapshot; no copied count is an acceptance gate.
Ignored or untracked `test_*.py`/`*_test.py` files cannot inflate the plan. Immutable
attempts reject `AdditionalPythonPath`: ambient Python trees can change without
changing the reviewed commit. The general bounded runner retains that option
only for explicitly reviewed diagnostic work outside this attempt workflow.
The runner refuses ambient Python/pytest controls, gives the run one unique
empty non-reparse bytecode-cache prefix with bytecode writes disabled, restores
the prior environment, and deletes only its owned empty cache root. Initial and
post-chunk guards reject ignored Python/pytest configuration, `.pyc`/`.pyo`, and
native-extension shadows from repository, info/exclude, or global ignore rules.
That scan is bounded to root singleton controls and the actual `app`, `src`,
`tests`, and compatibility `weather` import/control roots; ignored operational
evidence under `data/` is neither import authority nor a false blocker.
Capture/import probe JSON is parsed and hashed from strict UTF-8 bytes read via
the same retained stdout handle; JUnit XML and SHA-256 come from one held file
snapshot. No result combines separately opened generations.
Qualification and the scheduled repeat also require exact equality of retained
Python-environment and toolchain fingerprints. The former binds interpreter,
`pythonw.exe`, implementation, import path, installed distributions, and the
exact two reviewed production-venv `.pth` bootstrap files. Those `.pth` handles
remain open through PASS; only the canonical guarded distutils line and exact
editable production `src` path are accepted, `SETUPTOOLS_USE_DISTUTILS=stdlib`
is restored afterward, and the import probe must still resolve `weather` from
the candidate worktree. The latter fingerprint binds the absolute `git.exe`,
approved same-installation `git-lfs.exe`, and PowerShell executables and hashes
plus their reported versions, CLR/architecture, and deterministic environment
controls. Every Python launch temporarily applies and then restores the frozen
no-system/no-global Git config, attributes, protocol, and no-topology-redirect
boundary. The canonical log parent is separately exposed as a protected
evidence root, never an allowed write root. Their
create-only JSON sidecars are hash-checked from the same suite log generation;
an `evidence_validation_error` is always non-PASS and retained for diagnosis.

During qualification, `WEATHER_INTEGRATION_TEST_OFFLINE=1` makes every attempt
or quiet-merge Scheduler mutation fail closed unless the exact verb resolves
directly to an in-process `Function` mock. A cmdlet, alias, application,
missing command, or non-dry-run quiet merge is forbidden. Normal historical
runtime outside that exact environment setting is unchanged. The Python
bootstrap latches the offline state before test imports, so clearing the
environment later cannot re-enable real Credential Manager or market transport
boundaries; socket interception is installed at the same startup boundary.
Test-child Git permits only local `file` transport with prompting disabled.
Only the contained production capture admission probe receives the explicit
read-only production-probe marker needed for production imports; candidate and
production equality in that mode does not permit production/evidence writes or
`.env`/credential reads, and the marker is restored immediately after the child.
The direct-PowerShell source scan is defense in depth, not a PowerShell parser
or an OS sandbox; Job containment, protected-write checks, stripped environment,
and exact executable binding remain independent controls. The Python bootstrap
likewise does not globally deny `os.kill` or `os.killpg`: signal-0 liveness probes
and teardown of the exact POSIX process groups created by
`run_isolated_subprocess` require those APIs. Real operational signal owners
enforce the offline external-I/O latch, but an arbitrary direct native signal is
a residual that the bootstrap does not claim to contain.
Before every bounded-suite host-admission import, the runner executes the
hash-bound quiet-merge preflight against production. Only its exact generated-
config drift allowlist may be present, and `WeatherOneShotPush` must still match
its reviewed task identity; only then may the production tree's canonical
capture-recovery checker establish three-worker health.

Before touching Scheduler, the registrar creates an immutable
`registration-intent.json` containing the exact user, actions, one-shot
triggers, wake and battery behavior, execution limits, and all other relevant
settings. Current attempts derive that user from the process
`WindowsIdentity`, freeze its authority-qualified account name, SID, machine,
and domain context, and refuse conflicting ambient `USERNAME`, `USERDOMAIN`, or
`COMPUTERNAME` values. Both registration mutations recheck that frozen
identity, and Scheduler readback is translated back to the exact SID rather
than trusting display-name equality. Read-back attestation also requires each
trigger's numeric UTC offset
to match the host time zone at that unambiguous frozen wall clock. Runtime
wrappers and recovery bind both tasks to that intent and the
registration receipt. The registrar refuses to replace an existing task. The
preferred composite path passes `-StageDisabled`, which sets the Scheduler
definition Disabled before each first registration call; there is no transient
enabled state. It registers the merge consumer first: if suite registration
then fails, the merge remains disabled and has no activation receipt; the pre-mutation
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
all-chunks PASS verdict. V2 repeats must also match qualification's exact
source/test inventories and aggregate executed/skipped counts. The suite
wrapper repeats the complete canonical live/local/worktree/inventory/ignored
observation at each phase boundary, not only before final PASS. Suite log
timestamps are emitted with invariant
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
- the unchanged canonical live topic head, explicitly refreshed topic/master
  tracking refs, and current orchestration hashes, checked again after any
  bounded suite wait and immediately before child launch;
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
attempt-local report directly with `CreateNew`, writes and `Flush(true)`s it
through one retained read/write handle, and hashes/parses that same byte
generation; it never copies evidence back out of the mutable latest-report
slot. The latest-report and append-only history files are explicitly
diagnostic-only. The authoritative report binds the original baseline, optional
generated-config commit, exact merge commit, documentation transaction,
affected-producer recovery, and publication acknowledgement.
The scheduled child also retains hash-bound read handles for its own script,
remote-Git, Job containment, workload admission, quiet preflight, roll verdict,
Git, Git LFS, Python, and PowerShell generations through their last use. Every
mutating Git command disables hooks while the approved Git LFS filter executable
remains pinned. Python recovery/documentation probes run only through the
bounded Job helper with the qualified interpreter hash, sanitized import
environment, retained stdout bytes, loaded-source identity validation, and
complete Git state before/after. Those state sandwiches reject every
skip-worktree/assume-unchanged index entry, hash all bounded tracked regular
working bytes with their index mode/blob identity, classify every Git LFS path
as an exact pointer or hydrated object, and repeat the index/LFS inventories.
Root executable shadows plus `app/`, `scripts/`, `src/`, `tests/`, `tools/`,
compatibility `weather/`, and tracked-derived top-level import roots are checked
for ignored or untracked authority artifacts; ignored `data/` evidence remains
outside that namespace. The child's reported loaded-module fingerprint is also
recomputed over the same retained stage paths, so a syntactically plausible
identity cannot substitute for the published bytes. Roll-verdict JSON is CreateNew output whose
exact object is frozen by retained handles before strict parsing/hash, with
checked cleanup that cannot replace the initiating error.
Direct/manual production use has the same live-ref boundary as a manifest
attempt: the branch must be `origin/<topic>`, both canonical live heads must be
observed, and the exact topic/master tracking refs must refresh successfully.
There is no last-fetched fallback.
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
Every marker transition uses a GUID-named `CreateNew` sibling, `Flush(true)`,
same-handle JSON/hash readback, a stable prior-marker snapshot, atomic replace,
an exact backup comparison, and checked cleanup. The documentation pending file,
its content-addressed snapshot, and the marker are each read once through a
retained handle at the final publication boundary; hashes and JSON are derived
from those same bytes.
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
suitable for `-RepairOfReceiptPath`. Successor preparation revalidates both
closure rows against one complete current Scheduler snapshot: an absence row
requires continued exact absence, while a present row requires the unchanged
intent-bound task to remain Disabled. A failure immediately after manifest
creation may therefore close with both tasks absent and no registration intent;
an appeared, re-enabled, missing, or drifted task invalidates that authority.
The closer holds the same OS-backed `heavy_workload.lock` used by guarded merge
drivers from its first production classification through that receipt, plus the
attempt terminal mutex shared with registration/reconciliation. An ad-hoc merge
or terminal classifier therefore cannot enter the last proof-to-receipt gap.
If registration created an exact task but its confirming read failed, the
receipt can say `registered = false` while the task exists. The closer still
disables that task only when every intent-bound identity field matches, and
records the registration-receipt disagreement instead of leaving an armed task.

Successful historical v1 attempts are not failure-closed with the command
above. Their already-passed triggers can remain `Ready` and enabled with
`AllowDemandStart`, so they are both a manual-resurrection risk and an honest
collision blocker for a new attempt. Retire each exact pair separately:

```powershell
.\scripts\ops\retire_integration_attempt_tasks.ps1 `
  -ManifestPath <successful-manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256> `
  -ExpectedMergeReceiptSha256 <pass-merge-receipt-sha256> `
  -ReviewReference <operator-or-agent-review> `
  -Confirmation RETIRE_EXACT_TERMINAL_INTEGRATION_TASKS
```

Use `-PreflightOnly` first for a read-only report. The mutating mode revalidates
the immutable PASS merge and suite receipts, exact v1 registration binding,
terminal `Ready`/`Disabled` state, result zero, and receipt-correlated last-run
times under the terminal mutex. It disables rather than deletes the tasks and
writes `task-retirement-receipt.json`; it does not rewrite the PASS receipt or
grant credential/exchange authority. The writer immediately reads that receipt
back through the production validator. The preparation collision gate ignores a
disabled demand-startable v1 task only when the current task still matches its
registration and either the exact two-task PASS retirement receipt or an exact
immutable FAIL closure validates. A missing, corrupt, one-task-only, or
wrong-attempt receipt remains a blocker. New v2 tasks disallow demand start and
therefore cannot be resurrected after their one-shot date, but every enabled
`Ready` attempt task remains a collision even when Scheduler reports a null,
due, or past `NextRunTime`. `AllowOwnExactTasks` exempts only the exact own pair
while both are staged `Disabled`; an enabled own task still blocks. Scheduler
retirement still requires
explicit user authority.

The two `WeatherIntegrationRecoveryBootstrap*Fixed0822` tasks predate attempt
manifests. The ordinary retirement script must reject them. If either remains
enabled, the preparation collision gate names it as a blocker. Use the separate
legacy bootstrap retirement script only with its reviewed exported-XML SHA-256,
exact last-run timestamp/result, and
`RETIRE_EXACT_EXPIRED_LEGACY_INTEGRATION_TASK`. It allowlists only those two
names, requires one expired trigger and terminal state, disables rather than
deletes, and records then reads back a separate immutable receipt. Disabled
legacy tasks with no valid exact receipt remain collision blockers. Collision
also treats a due, past, or null `NextRunTime` on any enabled protected
quiet-merge driver as a blocker; only a future non-overlapping run is admitted.
The gate re-reads that exact task after `Get-ScheduledTaskInfo` and again before
returning: a `Ready`-to-`Running` transition, action change, disappearance, or
advanced `NextRunTime` blocks the attempt instead of treating the next
recurrence as evidence that the current protected run is idle. Collision
validation receives the target production repository root explicitly; an
isolated worktree's `$PSScriptRoot` is code provenance, not authority for the
ignored runtime-evidence namespace. This is a bounded migration exception, not
a generic old-task cleanup mechanism.

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
surfaces `FAILED_NEEDS_CLOSE`, `CLOSED_NEEDS_DISPATCH`,
`AWAITING_SUCCESSOR`, `SUCCESSOR_UNPUBLISHED`, `SUCCESSOR_UNREGISTERED`,
`SUCCESSOR_WINDOW_MISSED`, `SUCCESSOR_ARMED`, `SUCCESSOR_ACTIVE`,
`MERGED_UNVERIFIED`, and `MERGED_RECONCILED` in human and JSON output. It also
keeps publication-only, unresolved preparation, and unproved-closure evidence
visible independently of task discovery, and flags any pair of exact armed
attempt schedules whose suite-to-merge intervals overlap. The JSON
also states whether publication is required, whether the attempt is actually
unattended-ready, the current live-origin revalidation disposition, and the
exact next action. The recurring status watchdog does not contact origin, so it
reports that check as `DEFERRED` and never converts local armed proof alone into
`unattended_ready=true`; the interactive final preparation assertion owns the
live remote proof. A suite is missed only after a
five-minute trigger grace when its
exact task has no current run and neither the preflight log nor a terminal
receipt exists; an actively running suite is not a false alarm. A suite that
did run but is now non-running without a receipt is a distinct actionable
failure. Status rechecks receipt existence after sampling the suite task, so a
receipt published during the status scan suppresses that interrupted-suite
alert while unreadable evidence retains its separate flag. The same five-minute
rule flags a non-running merge task after its
one-shot trigger when no merge or closure receipt exists, so an outage cannot
silently spend both triggers. It also flags unreadable task-bound
manifests/evidence. Historical terminal receipts may age out of flag severity,
but dispatch-only, unpublished, unregistered, missed-window, partial
preparation, and closure-unproved states remain FLAGS until resolved. Age never
turns an unresolved operator dependency into unattended readiness.

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
Capture recovery, execution-tape status, and documentation-transaction begin
never run as direct Python children in this recovery path. The reconciler
reopens the immutable full-suite Python-environment sidecar, requires its exact
repository interpreter path and SHA-256, and launches each module through the
kill-on-close bounded-process helper with retained stdout/stderr. Each child
uses a sanitized import/cache environment, strips credential-bearing variables,
reports its canonical module and loaded-source runtime identity, and is enclosed
by equal production branch/ref/status and ignored-shadow observations. The
receipt records interpreter, output, and loaded-source hashes for every such
invocation. The same contract protects the idempotent active-marker cleanup
check; a stopped reconciler cannot leave an uncontained probe behind.
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
reconciliation receipt. Marker phase transitions use a create-new sibling,
`Flush(true)`, and atomic replacement. Each replacement proves that its backup
bytes equal the prior marker and that the published readback equals the intended
bytes; checked cleanup preserves the initiating failure. The marker is retired
only after the reconciliation receipt exists, so another interruption remains
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
the two refs without the checked-out branch is insufficient. For current
attempts, the gate also exports the immutable full-suite interpreter and
`pythonw.exe` SHA-256 values; adoption pins both generations and requires the
exact launcher in every supervisor task re-attestation. Historical attempts pin
the current canonical repository launchers as a legacy-only fallback. The gate
itself executes as a manifest-hash-bound kill-on-close PowerShell child with its
dot-sourced dependency generations retained; v1's absent `remote_git` hash is
handled only as a contained current-generation compatibility fallback.
All two capture checks, the managed-status check, and the rollback stop run in
the pre-resume kill-on-close Job boundary with retained bounded stdout/stderr,
strict JSON, a sanitized import/cache/secret environment, loaded-source
fingerprint proof, and unchanged checked local Git tuples. A failed rollback
first disables and re-attests the exact supervisor task before the managed stop;
probe or task-disable readback is recorded as cleanup evidence without masking
the original adoption refusal. No integration attempt reads credential values
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
