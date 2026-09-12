# 331. Overnight Reliability Program [PARTIAL 2026-09-12 - IMPLEMENTATION STARTED; QUALIFICATION AND ADOPTION OPEN]

Owner/package: weather.operations, weather.reporting, scripts/ops
Source: September 12, 2026 owner-approved reliability audit and implementation plan.
Goal: Make required overnight outputs diagnosable, bounded and recoverable while
protecting capture continuity.
Why this matters: A launch or dependent-step failure currently prevents useful
work and can leave missing dates without automatic recovery.

Implement the owner's September 12 reliability decision: diagnose launch
failures before the overnight window, bound retained-corpus processing, keep
unfinished work recoverable, and separate stable capture from development.
Required outputs and evidence determine success; a successful task exit alone
does not establish completion. No live trading or promotion is authorized.

## Current work

The first candidate adds a selected Git path/hash/version to new integration
manifests, create-once bootstrap journals before deep launch validation, native
Windows regression tests, and an exact-candidate hosted Windows workflow.
Qualification and production adoption remain open. Hosted regression evidence
does not replace the currently required production bounded suite or actual-host
S4U proof. Native stdout/stderr containment is the next launch work package.

The initial branch is `codex/reliability-native-launch-20260912`, based on freshly
fetched `origin/master` at `f3814173775335adb546b7201a2e73ecec7703bf`.
Existing generated configuration edits are outside the implementation scope.

## Ordered work packages

| Package | Outcome | Acceptance / dependency |
| --- | --- | --- |
| R0 Baseline | Required outputs, deadlines, source identities and owners | Reconcile task success separately from output validity; keep the existing Stage-A deadline |
| R1 Launch | Reviewed Git executable, early diagnostics and bounded native stdout/stderr | Duplicate PATH entries work; changed executable fails; pre-logger failures survive; full child-tree cleanup and restricted handle inheritance |
| R2 Qualification | Windows plus Linux qualification before the adoption window | Bind candidate/tree/dependencies/artifacts; retain actual-host S4U smoke; explicitly review any acceptance-contract substitution |
| R3 Audit | Streaming/indexed settlement-source audit and bounded consumers | Preserve traversal/overlay semantics and gate decisions; representative corpus remains below its existing resource cap |
| R4 Capacity | Reserved non-capture worker capacity and sealed input handoff | Measure staging reserve and memory; do not rely on the frozen mirror; qualify a restricted host role before unattended batch deployment |
| R5 Job contracts | Logical work identity, immutable attempts, claims and publication reconciliation | Duplicate delivery and a stale owner cannot publish conflicting output; ambiguous publication is reconciled |
| R6 Dependencies | Actual required/advisory/prior-generation edges | Independent work continues; pending, stale and skipped work never becomes a passing gate |
| R7 Coordinator | Two read-only derived workflows in an isolated durable-workflow pilot | Failure injection and operating-burden decision before managed-service adoption |
| R8 Monitoring | External absence, output-deadline and backlog detection | Correct failure/recovery notifications without repeated unchanged-state alerts |
| R9 Shadow | Seven daily comparisons without publication authority | No unexplained semantic differences; one versioned routing owner |
| R10 First cutover | One derived-output family under durable scheduling | Seven scheduled cycles, interruption recovery and safe ownership rollback |
| R11 Historical repair | Confirmed missing dates remain in a persistent queue | Per-date evidence and next action; use the bounded slice ending at `market_day_labels_finalize` |
| R12 Stable capture | Immutable release separate from development checkout | Guarded selection and compatible rollback; three-worker and execution-tape recovery |
| R13 Remaining families | Incremental migration in dependency order | One producer per family, compatible consumers and unchanged readiness authority |
| R14 Retirement | Remove only superseded triggers and measure outcomes | Restore procedure retained; 30-day acceptance evidence |

R1, R2 and R3 deliver independently of a cloud subscription or hardware
purchase. R12 proceeds alongside job migration. The coordinator must wrap the
existing native containment, admission and publication contracts. A failed
managed-coordinator pilot may use a small local controller; do not maintain two
active schedulers for the same family.

## Delivery checklist

- [ ] Qualify and adopt the launch repair and early Windows checks.
- [ ] Bound the audit and establish measured non-capture capacity.
- [ ] Prove job identity, dependency and publication-recovery contracts.
- [ ] Pass the coordinator pilot, monitoring and first-family cutover.
- [ ] Reconcile the historical backlog and qualify a stable capture release.
- [ ] Migrate remaining eligible families and pass the 30-day acceptance gate.

## Existing ownership

- [Item 324](item-324-bounded-daily-settlement-refresh-resource-admission-and-step-isolation.md)
  owns daily resource and bounded-repair behavior.
- [Item 325](item-325-tiered-data-retention-and-verified-archive-offload.md)
  owns archive/storage evidence and recovery.
- [Item 329](item-329-immutable-overnight-integration-attempt-recovery.md)
  owns the established immutable integration framework; this program extends it.
- [Item 330](item-330-maker-economics-refocus-master-plan.md) retains W10/W12
  ownership for immutable deployment and dependency/reporting integration.

Do not convert the learning-coverage map into an execution DAG: some consumers
intentionally use compatible prior-run evidence. Retained audit optimization
must preserve last-encountered ledger rows and nonempty label overlays, not
substitute latest-timestamp semantics.

## Final acceptance

Acceptance:

- Every scheduled intent has a diagnosable disposition and next action.
- No partial, stale-owner or incompatible-generation output is accepted.
- Confirmed missing dates remain visible across restarts and later triggers.
- Qualified transient failures recover automatically within their recorded limits.
- At least 29 of 30 consecutive scored days meet the frozen required-output
  roster and deadlines, with misses and external-input causes separately shown.
- No routine manual rescheduling is required for covered migrated jobs during
  the observation period, and the migration causes no lost graded capture day.
- Controller restore and compatible capture rollback are rehearsed.

This is an initial operational target, not proof of long-term 99% reliability.
Subscription and hardware choices require measured need and their own concrete
deployment/purchase decision. Existing capture windows, workload leases, reserved
dates, release bindings, native settlement units and WU cutoff rules remain in force.

## Evidence and next gate

Source contracts and commands: [integration attempt runbook](../../operations/INTEGRATION_ATTEMPT_RUNBOOK.md).
Verification ownership: [development guide](../../development.md) and
[Windows workflow](../../../.github/workflows/windows-qualification.yml).
Next gate: native Windows regression results, cumulative review and exact-host
qualification before claiming R1 production adoption.
