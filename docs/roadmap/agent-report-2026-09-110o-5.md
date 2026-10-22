# 110o part 5 — workstation Git repack with retention guards

**Verdict: IMPLEMENTED, NOT EXECUTED.** This branch adds a distinct `git_maintenance` kind to the workstation heavy wrapper and a fixed Python operation for the non-capture clone. The operation refuses direct invocation, uses the existing workstation host/principal admission, shared lease and kill-on-close Job, refuses active Git operations and alternates, and verifies that refs, worktrees, reflogs and the complete object-id inventory are unchanged. No repack or GC was run here: the wrapper rejected this session's host/principal as not the assigned non-capture workstation. No direct fallback was used. Production closure membership is unverified.

## Preservation contract

The only admitted arguments are `-m weather.operations.workstation_git_maintenance`, with no operation/path overrides. The fixed commands are `git repack -a -d --keep-unreachable` and `git -c gc.reflogExpire=never -c gc.reflogExpireUnreachable=never -c gc.worktreePruneExpire=never gc --no-prune --no-detach`. The route prints before/after `git count-objects -vH` output and a JSON receipt comparing refs, linked worktree registration, reflog entries and a SHA-256 digest of all listed object ids. It fails closed if any preserved set changes. Git LFS paths are never inspected or passed to Git; history-changing commands and `--prune=now` are not admitted. Git's documented `--keep-unreachable` mode retains unreachable packed and loose objects when repacking, and `--no-prune` prevents loose-object pruning; the `gc.*Expire=never` settings also suppress reflog expiration and worktree pruning.

The operation is fixture-tested only. The new wrapper integration test initializes a small temporary Git repository and invokes the route through the wrapper, so it tests the actual host-assignment fixture, lease, child Job and result receipt without touching this repository's object database. CI is the available qualification path while workstation wrapper admission is unavailable here. The four required repository audits remain part of the full CI qualification; no local pytest run was attempted.

## Per-file roll classification

| File | Classification | Reason |
| --- | --- | --- |
| `scripts/ops/workstation_heavy.ps1` | Roll-free under the repository `.ps1` rule | Adds a separate exact operation kind; preserves the existing admission and child-Job flow. |
| `scripts/ops/workload_admission.ps1` | Roll-free under the repository `.ps1` rule | Allows the new exact lease workload name; adds no capture or production behavior. |
| `src/weather/operations/workstation_git_maintenance.py` | Roll-sensitive | The fixed route changes the workstation clone's Git object packing, so it is gated and preservation-checked. |
| `tests/operations/test_workload_admission_script.py` | Roll-free | Verifies that only the exact module and no arguments use the new kind. |
| `tests/operations/test_workstation_git_maintenance.py` | Roll-free | Fixture-only preservation and fail-closed tests. |
| `docs/roadmap/agent-report-2026-09-110o-5.md` | Roll-free | Handoff record only. |

No production closure membership was verified from this workstation.

## Exact workstation procedure

On the assigned non-capture workstation only, in the intended clone, run the exact wrapper with the project interpreter and repository root. Use FIFO admission if another heavy job is active:

```powershell
$argsJson = '["-m","weather.operations.workstation_git_maintenance"]'
$argsBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($argsJson))
& .\scripts\ops\workstation_heavy.ps1 `
  -Kind git_maintenance `
  -PythonPath C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe `
  -ArgumentsBase64 $argsBase64 `
  -RepoRoot C:\Users\Michael\Documents\github\weather `
  -Queue
```

Retain the JSON receipt and exit code. A nonzero result or any false preservation field means stop and investigate; do not retry with direct Git commands. The operation is workstation-only and must never run on the production capture host. No scheduler, production data, credentials, venue access, network source, or live-trading action is part of this change.
