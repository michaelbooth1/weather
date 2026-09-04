# 331. Roll-Free Daytime Control Plane [PARTIAL]

Goal: stop spending overnight integration windows on work that cannot restart a
loaded production closure, while preserving the protected capture and
near-close windows.

Owner/package: `scripts/ops/`, `.github/workflows/`, and canonical operations
policy.

Source: the 2026-09-03 production audit. The documented roll-free exception
was not executable: `quiet_window_merge.ps1` rejected the graded window before
classification and the shared workload lease admitted no ordinary caller after
09:00. The same audit found that the failed September 3 reconciliation attempt
first encountered its Windows PowerShell/ScheduledTasks serializer mismatch at
01:00 even though it was deterministic and safe to probe during the day.

Why this matters: quiet hours are scarce recovery capacity. Spending them on
documentation-only merges or discovering a deterministic Windows wrapper
defect converts a small fix into a lost day while providing no additional
capture protection. The safer throughput gain is earlier discovery plus a
strictly classified, lease-serialized control plane—not more production compute.

## Scope

- [x] Serialize the frozen exact branch-tip classification under the same
  policy lease that protects later integration.
- [x] Reserve 09:00-11:55 for Stage A, then let an 11:55-18:00
  `roll_free_control_plane` candidate proceed beyond its read-only verdict gate
  only on fresh machine evidence exactly binding canonical roll-verdict exit 0,
  the frozen tip, synchronized base, invocation time, and required closures.
- [x] Keep the shared OS-held lease, so a Stage-A overrun and all heavy work
  take precedence over daytime integration.
- [x] Keep every nonzero/undecidable verdict in the 01:00-04:00 quiet window
  and retain the universal 18:00-00:30 near-close prohibition.
- [x] Add focused contract tests for the exact lane, fail-closed verdict JSON,
  delayed boundary crossings, and lease-before-verdict-before-mutation ordering.
- [x] Add a Windows PowerShell 5.1 CI job for operations-script parsing and
  focused Scheduler/lease/merge wrapper contracts; use full Git history
  without downloading LFS objects.
- [ ] Obtain focused Windows and Linux CI PASS on the exact published tip.
- [ ] Independently review the control-flow and merge the branch under the Git
  workflow.
- [ ] Run one exact roll-free production integration through the daytime lane
  and verify the receipt records `policy_window=roll_free_control_plane`.

Acceptance: roll-free Git integration can complete after Stage A without
competing for its reserved lease or opening a general-purpose heavy-work window,
while a roll-sensitive or undecidable tip cannot enter the lane. Deterministic Windows
wrapper mismatches are discovered by CI or a daytime no-mutation probe before
an overnight attempt is armed.

## Evidence

- Implementation branch:
  `codex/roll-free-daytime-control-plane-2026-09-03`, based on
  `c932b54f8747df5cdefc4cc42f8454b6797f09ae`.
- Runtime owners: `scripts/ops/quiet_window_merge.ps1` and
  `scripts/ops/workload_admission.ps1`.
- Focused contracts: `tests/operations/test_quiet_window_merge_script.py` and
  `tests/operations/test_workload_admission_script.py`.
- CI owner: `.github/workflows/ci.yml`.

## Completion notes

The lane is source-only until reviewed integration. It does not authorize
Scheduler registration, production runtime adoption, model work, live trading,
or a roll-sensitive daytime merge.
