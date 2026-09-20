# Host Load Policy — expired dated exceptions

> **HISTORICAL — not current authority.** Every exception below was bound to one local date (or
> one UTC interval) that has passed. None grants anything today. The current policy is
> [`../HOST_LOAD_POLICY.md`](../HOST_LOAD_POLICY.md). Moved here verbatim on 2026-09-19 so the
> always-read policy carries only rules that still bind.

**Read when:** you are tracing why a dated token or literal exists in an ops script, or auditing
what an owner exception authorized at the time. **Do not read** to decide whether work may run now.

## The code paths still exist, and are date-bound

The literals were not removed when the dates passed. Each comparison is against a fixed date, so
each path now always refuses. Do not reuse, extend or re-date a token; a new exception needs a new
dated owner decision and a reviewed code change.

| Exception | Where the literal lives | Why it can no longer admit |
| --- | --- | --- |
| `OWNER_APPROVED_PROTECTED_WINDOW_MERGE_20260823` | `scripts/ops/workload_admission.ps1` (`Get-WeatherHeavyWorkloadPolicyWindow`), `scripts/ops/quiet_window_merge.ps1` (two checks, the second also pins the branch) | local date must equal `2026-08-23`, else it throws "invalid or expired" |
| `OWNER_APPROVED_STORAGE_RECOVERY_20260908` / `_20260909` | `scripts/ops/workload_admission.ps1` (`$storageExceptionDates`, and the workload restriction near the lease acquisition), `scripts/ops/storage_recovery_inventory_run.ps1`, `scripts/ops/cold_snapshot_compression_run.ps1` | local date must equal the token's date and the minute must fall in 09:00–18:00 |
| September 10 overnight 8 GiB reserve | `src/weather/operations/production_cold_archive_stage_cli.py` (`OVERNIGHT_RESERVE_BYTES`, `load_plan_with_reserve`) | applies only inside 2026-09-10 04:00–13:00 UTC |

The **plan-pinned 20 GiB July-archive reserve** (`APPROVED_ARCHIVE_RESERVE_BYTES` in the same
Python module) is *not* date-bound and is therefore still described in the live policy, not here.

---

## 2026-08-23 — one protected-window merge (was Rule 2, last paragraph)

One repository-owner exception on 2026-08-23 permits only the exact
`codex/live-readiness-closure-20260823` lineage rooted at
`71f7e46690e822a498f80412c11d550bcee949d2`, against production baseline
`9d54f94760855a5f91ac603f3f14b02ba06ae239`, to acquire the merge lease in
the protected window under the literal dated token. The code path expires
with that local date and grants no reusable authority.

## Owner storage exception: September 8, 2026

At 11:47 Toronto the owner authorized capacity recovery now rather than waiting
another day, conditional on the agent judging the risk reasonable. The literal
`OWNER_APPROVED_STORAGE_RECOVERY_20260908` token permits only
`storage_recovery_inventory` and `cold_snapshot_compression` on the assigned
dedicated capture host from 09:00 until 18:00 Toronto on that date.
Both attended wrappers require the explicit `-OwnerApprovedException` token;
the child must match its dated policy against the independently proved live lease.
This is a one-date inventory/compress-and-retain exception, not archive/delete,
cache, testing, training, merge, Stage-A, workstation, or live authority.

All ordinary resource and capture checks remain: shared lease, BelowNormal
priority, 384 MiB child ceiling, at least 4 GiB available RAM, commit below 70%,
fresh healthy capture identities, lane-specific disk reserve, and bounded
kill-on-close teardown. The absolute deadline reserves teardown before 18:00.
Stop on any failed admission, changed content/identity, or nonpositive pilot
savings. No source file is deleted. The ordinary timetable resumes at expiry.

## Owner storage exception: September 9, 2026

After reviewing the failed overnight attempt and a verified attended pilot,
the owner explicitly authorized bounded storage work on September 9 until
18:00 Toronto. The literal `OWNER_APPROVED_STORAGE_RECOVERY_20260909` token
permits only `storage_recovery_inventory` and `cold_snapshot_compression`
on the assigned dedicated capture host from 09:00 until 18:00 that date.
It is independent of the expired September 8 token; neither token authorizes
another date.

Both wrappers require the explicit token, and the child independently binds
it to the matching live lease policy. The shared lease, healthy capture,
commit below 70%, at least 4 GiB available RAM, BelowNormal priority, child
memory ceiling, disk reservation, retained-file verification and complete
bounded teardown remain unchanged. The absolute deadline reserves teardown
before 18:00. No source deletion, archive export, training, test, merge,
Stage-A, workstation or live authority is added.

## September 10 bounded archive recovery

The owner's September 10 full overnight authorization includes saving recovery
keys and using only existing PC storage plus private Google Drive. The exact
primary plan and selection pinned by the archive CLI may use an 8 GiB reserve
through 13:00 UTC that day. All chunk, evidence/output, memory, capture, lease,
time-window and teardown checks remain required. The controller must account
for every temporary local copy before admitting ingress.
See [the staging runbook](../production-cold-archive-staging.md) for the bounded
unattended archive credential and workstation launch path.

## Update this file when

Another dated exception in `HOST_LOAD_POLICY.md` expires (move it here verbatim and add its row to
the table), or a listed literal is finally removed from code (say so in the table).
