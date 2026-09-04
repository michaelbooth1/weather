# Unattended workstation Codex mission runner

Status: repository-owned contract for one bounded delegated workstation attempt.

`scripts/ops/invoke_workstation_codex_mission.ps1` runs a sealed Codex mission
from a clean detached controller worktree and validates its handback before it
can report success. It is a workstation control plane. It grants no production,
capture, Scheduler, credential, provider, exchange, live-order, merge, push,
release, promotion, or retry authority.

## Attempt contract

Run mode requires absolute paths and explicit SHA-256 values for the sealed
mission and selected `codex.exe`. It also requires the exact source commit,
tree, sole parent, base commit, expected result ref and worktree, report and
receipt paths, complete bundle path, and an absolute UTC deadline no more than
24 hours ahead. The runner resolves regular non-reparse files and directories,
rejects pre-existing output/ref/worktree paths, and keeps its claim, status,
heartbeat, logs, child records, terminal receipt, and bare verification
repository outside every Git worktree.

The repository root may contain unrelated tracked or untracked changes. The
runner uses it only as the local object database and creates a detached
controller worktree at the exact source commit. That controller must remain
clean and unchanged. The delegated mission creates and commits only its named
result branch/worktree.

The selected Codex path is explicit. A new app version or multiple installed
version directories cannot silently change selection. The immutable claim
records the executable path and digest along with the runner, Windows
PowerShell, Git, and Job-helper paths and digests; source/base/result identities;
host, principal, and boot hashes; runner and contained-child identities; every
output path; start time; heartbeat interval; and deadline.

The runner launches a private Windows PowerShell child suspended, assigns it to
the existing repository-owned kill-on-close Job Object, and then resumes it.
The child waits for the immutable claim before starting the pinned executable.
Its create-only start record binds the actual Codex PID and process creation
time to the claim. Standard output and error stream into reader-shareable files.
The parent terminates only its Job; it never discovers or kills processes by
name or an unbound PID. Deadline, interruption, ordinary child exit, and error
paths all query the Job until its active-process count reaches zero.

## Status and immutable evidence

`status.json` and `heartbeat.json` are mutable views. Each publication writes
and flushes a same-directory temporary file, then uses Windows
`MoveFileEx(REPLACE_EXISTING | WRITE_THROUGH)`. Readers therefore see the old
or new complete JSON document. Both documents bind the claim hash and mission
identity and carry a strictly increasing sequence, UTC observation time, and
monotonic elapsed milliseconds.

The claim, prompt, child start/result, interrupt request, and terminal receipt
use create-only writes. Output collision stops the attempt. A failed attempt is
never overwritten, resumed, or retried by this runner. A separately
commissioned successor must use a new attempt root, controller path, and the
repository's classified retry contract in
[`INTEGRATION_ATTEMPT_RUNBOOK.md`](INTEGRATION_ATTEMPT_RUNBOOK.md); this script
does not create that authority.

Status mode reads only the exact claim, status, heartbeat, and current process/
boot identity. It takes no writer-exclusive handle and performs no recursive
scan:

```powershell
.\scripts\ops\invoke_workstation_codex_mission.ps1 `
  -Mode Status `
  -MissionId <mission-id> `
  -AttemptRoot <absolute-attempt-root> `
  -Attempt 1 `
  -ExpectedClaimSha256 <claim-sha256> `
  -StaleAfterSeconds 30
```

A fresh heartbeat reports the writer state. A stale heartbeat on the same boot
with the exact runner process gone reports
`ABRUPT_WRAPPER_EXIT_OR_CLIENT_DISCONNECT`; a changed boot hash reports
`ABRUPT_HOST_REBOOT`; and a live exact runner with a stale heartbeat reports
`RUNNING_STALE`. The combined same-boot abrupt state is deliberate: immutable
local files cannot distinguish a forcibly terminated wrapper from an SSH host
that killed the wrapper when its client disconnected. A clean SSH disconnect
that leaves the process alive does not interrupt supervision.

Ctrl-C and PowerShell pipeline interruption terminalize as `INTERRUPTED` when
PowerShell delivers the exception. An operator or test may instead create
`interrupt-request.json` with exclusive creation and these exact bindings:

```json
{
  "schema_version": "workstation_codex_mission_interrupt_v0.1",
  "mission_id": "<mission-id>",
  "attempt": 1,
  "claim_sha256": "<claim-sha256>",
  "requested_at_utc": "<ISO-8601 UTC time>",
  "reason": "<non-empty reason>"
}
```

## Terminal states

| State | Exit | Meaning |
| --- | ---: | --- |
| `COMPLETE_VALIDATED` | 0 | Child exit, identity recheck, handback bindings, complete bundle, and strict fsck all passed. |
| `CHILD_FAILURE` | 20 | Codex returned nonzero or the contained child exited without its immutable result. |
| `DEADLINE` | 21 | The absolute deadline fired and complete Job teardown passed. |
| `INTERRUPTED` | 22 | A bound interrupt request or catchable PowerShell interruption fired and teardown passed. |
| `INVALID_HANDBACK` | 23 | Exit zero was followed by a missing, malformed, dirty, incomplete, or mismatched handback. |
| `IDENTITY_DRIFT` | 24 | Mission, executable, runner/helper, controller, source, or child identity changed. |
| `TEARDOWN_FAILURE` | 25 | The owned Job could not prove zero active processes. |
| `RUNNER_FAILURE` | 26 | The wrapper raised another caught exception and retained the exact detail. |

An uncatchable wrapper termination or power loss can leave the last atomic
`RUNNING` view and no terminal receipt. Status mode classifies that state using
the immutable runner creation and boot identities. Process supervision does
not survive a host power loss. Resuming after reboot would require a separately
authorized Scheduler, service, or other persistent control plane; this runner
does not implement, register, or imply one.

## Success validation

Exit code zero is only permission to begin validation. Success additionally
requires all of the following:

- the expected local result ref exists, equals the named result worktree HEAD,
  descends from the exact source tip, and has a clean worktree;
- the required report and handback receipt are regular tracked files at that
  result tip;
- the handback receipt uses
  `workstation_unattended_mission_handback_v0.1` and binds the mission,
  source/base commits and trees, result ref, implementation commit/tree,
  changed paths, passing tests, script digests, terminal semantics, measured
  evidence, prohibited actions, and reboot boundary;
- every declared changed path equals the actual source-to-result diff and each
  declared script digest matches the result worktree bytes;
- the bundle path and receipt paths are exact; and
- an empty short-path bare repository can verify and fetch the result ref from
  the bundle, find the base/source/implementation/final commits, and pass
  `git fsck --strict --full --no-dangling`.

The receipt containing itself cannot embed its own final commit/tree or the
SHA-256 of the bundle that contains that commit. It must instead contain:

```json
"external_binding": {
  "rule": "terminal_receipt_binds_final_result_tip_tree_and_bundle_sha256",
  "final_tip": null,
  "final_tree": null,
  "bundle_sha256": null
}
```

The immutable terminal receipt supplies those three final values after strict
verification. This avoids a recursive hash claim while preserving an exact
external binding.

## Run example

Run from the repository-owned script in a reviewed checkout. Use a unique,
absent attempt root and controller path. The result ref/worktree and bundle
must also be absent:

```powershell
.\scripts\ops\invoke_workstation_codex_mission.ps1 `
  -Mode Run `
  -MissionId <mission-id> `
  -MissionPath <absolute-mission.md> `
  -ExpectedMissionSha256 <mission-sha256> `
  -AttemptRoot <absolute-external-attempt-root> `
  -Attempt 1 `
  -RepositoryRoot <absolute-local-repository> `
  -ControllerWorktree <absolute-new-controller-worktree> `
  -ExpectedSourceTip <source-commit> `
  -ExpectedSourceTree <source-tree> `
  -ExpectedSourceParent <source-parent> `
  -ExpectedBaseTip <published-base> `
  -ResultRef refs/heads/codex/<result-branch> `
  -ResultWorktree <absolute-new-result-worktree> `
  -RequiredReportPath docs/roadmap/<report.md> `
  -RequiredReceiptPath docs/roadmap/<receipt.json> `
  -BundlePath <absolute-new-final.bundle> `
  -CodexPath <absolute-codex.exe> `
  -ExpectedCodexSha256 <codex-sha256> `
  -DeadlineUtc <absolute-UTC-instant> `
  -HeartbeatSeconds 5
```

The command performs local Git worktree, ref, bundle, and object validation
only. It does not fetch, push, open a pull request, merge, clean worktrees,
contact production, or mutate Scheduler.

## Update when

Update this document when claim/status/receipt schemas, executable selection,
controller isolation, deadline/teardown behavior, terminal classifications,
handback validation, bundle verification, or restart boundaries change.
