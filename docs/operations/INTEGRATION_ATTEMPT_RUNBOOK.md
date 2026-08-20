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
    -> immutable FAIL/closure receipt
    -> classify and review
    -> new attempt (same tip once, or a new repaired tip)
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
01:00-03:40 and at least 30 minutes after the suite trigger. The manifest also
freezes hashes for the installed suite and merge orchestration, so an
unreviewed script change between registration and execution fails closed.

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
off; a missed task must not wake later in a protected window.

## Success contract

The suite receipt is PASS only when both logs exist, their hashes match, the
preflight ends in its exact PASS verdict, and the full suite ends in its exact
all-chunks PASS verdict. The merge task independently verifies:

- its own and the suite task's exact S4U/Limited action;
- the manifest path and SHA256 in both actions;
- the suite task's same-day success and receipt/run-time correlation;
- the unchanged branch tip and the current orchestration hashes;
- the guarded quiet merge's `pushed` report and documentation transaction;
- source-tip ancestry, local/remote master equality, and three-worker capture
  recovery after publication.

It copies the mutable latest quiet-merge report into the attempt directory and
hashes that immutable copy. Only a PASS `merge-receipt.json` plus its SHA256 is
downstream authority.

## Recover without losing the night

Never edit a failed manifest, append to its logs, replace its receipts, reuse
its task names, or move its task action to a new tip.

If a task crashed before writing a receipt, or an operator abandons an attempt,
close it:

```powershell
.\scripts\ops\close_integration_attempt.ps1 `
  -ManifestPath <failed-manifest.json> `
  -ExpectedManifestSha256 <manifest-sha256> `
  -Reason <specific-failure> `
  -ReviewReference <operator-review>
```

The closer refuses while either task is running, refuses a PASS merge, verifies
both task actions before disabling them, and preserves hashes of all evidence
that exists. Its closure receipt is a FAIL receipt suitable for `-RepairOfReceiptPath`.

Create attempt N+1 after classification:

| Repair class | Enforced scope |
| --- | --- |
| `retry_unchanged` | No source change. Allowed once after a reviewed transient failure; a second consecutive unchanged retry is refused. |
| `schema_registry` | Additions or modifications only in the three static schema-registry shards. |
| `ownership_metadata` | The module ownership map and its exact ratchet test only. |
| `orchestration_wrapper` | Repository-owned PowerShell wrappers plus their operation tests and owning runbooks. |
| `manual_reviewed_change` | A linked, explicitly reviewed change outside the mechanical classes. |

Every non-initial attempt must point to an immutable FAIL receipt. Mechanical
repair classes validate the Git name/status diff between the failed tip and the
new tip. They cannot delete or rename files. After the repair is committed,
reviewed, and checked out cleanly in the isolated worktree, call
`new_integration_attempt.ps1` with the new id, times, `-RepairClass`, and
`-RepairOfReceiptPath`, then register the new tasks.

An unchanged retry is for a classified timeout, resource refusal, scheduler
interruption, or other transient host failure. It is not a way to rerun a known
deterministic pytest failure. When that one retry also fails, diagnose or repair
before spending another attempt.

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
suite-gated path for already registered historical work. No integration
attempt reads credential values or authorizes live exchange mutation.

## Verification and adoption

Before merging this procedure, parse every changed PowerShell file, run the
focused operation tests, the documentation audit, roadmap lint, compileall,
and the exact full suite in an admitted heavy-work window. Editing these files
does not register, disable, start, or delete any host task. Adopt the registrar
only under a separate explicit scheduler authorization.

## Update when

Update this runbook when attempt schemas, repair classes, task identity,
evidence filenames, time windows, suite ordering, merge proof, or downstream
authority changes.
