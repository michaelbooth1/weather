# Bounded storage recovery inventory

This is the metadata selection step for [verified cold archive](verified-cold-archive.md).
It measures candidate capacity; it grants no archive or cleanup eligibility.
Use an isolated clean reviewed source worktree and the production interpreter.

The optional `-OwnerApprovedException OWNER_APPROVED_STORAGE_RECOVERY_20260908`
uses the [September 8 owner exception](HOST_LOAD_POLICY.md#owner-storage-exception-september-8-2026).
It expires at 18:00 Toronto that day; all resource, lease, capture and teardown
checks remain mandatory. Without that exact dated argument the ordinary
overnight window and scheduled-tiering reserve apply.

## Request and execution

Create an expiring `storage_recovery_inventory_request` with the exact production
repository, capture-host identity, named approval, `operation=metadata_only`,
approval/expiry timestamps no more than 72 hours apart, and one to twelve exact
relative folders. Request fields and schema versions are enforced by
`weather.operations.storage_recovery_inventory_cli` and the schema registry.

Only built-in event folders strictly outside the 30-day hot window are accepted:
`snapshots/<event>` and `backtest/replay_cache/<event>`. The exact `backtest`
folder is also accepted for root files only, so caches cannot be counted twice.
No data-root walk, links, reparse points, or hardlinked files are accepted.

Run `scripts/ops/storage_recovery_inventory_run.ps1` from the reviewed source:
pass absolute normalized `-ProductionRepoRoot`, `-RequestPath`, and a new
`-OutputRoot` directly below production `scratch/storage_recovery_inventory`;
bind `-RequestSha256` and the full clean `-ExpectedSourceTip`.

The runner proves the dedicated capture identity and owns the shared workload
lease. Both wrapper and child retain the 00:30-09:00 Toronto window and avoid
04:45-06:45, reserved for scheduled tiering. The child requires current healthy
three-worker capture with process-creation/lock agreement, commit below 70%,
4 GiB available physical memory, and BelowNormal priority. Capture observations
are shared with cache compression; its existing disk gate is unchanged.

This metadata-only lane reserves 8 GiB for concurrent capture plus at most
24 MiB for the inventory and 2 MiB for other evidence. It stages no source
payload. The reservation applies only to this bounded read-only operation and
does not reduce the ordinary 50 GiB heavy-work floor or authorize an archive
export. Stop if capture, memory, expiry, or disk checks cease passing.

The inventory stops at 120 seconds, 25,000 directory entries, 15,000 entries in
one directory, depth eight, or the output bound. The wrapper bounds the complete
child tree to 150 seconds, clamps to the next protected boundary with teardown
reserve, monitors process memory, and owns children in a kill-on-close Windows
Job. A failed teardown poisons the lease.

## Evidence and interpretation

Retain each attempt, including failures. Request, inventory, result, refusal,
and wrapper receipts are create-only. The wrapper binds the source and request
before and after the child and requires proved child-tree teardown.

File rows retain exact relative path, logical size, allocated bytes, timestamp,
volume/device, file identity, and attributes. Compressed/sparse allocation uses
the native handle's compression information; ordinary files use standard
allocation information. See Microsoft's
[handle information classes](https://learn.microsoft.com/en-us/windows/win32/api/minwinbase/ne-minwinbase-file_info_by_handle_class).
Source payloads are never opened for content or hashed. Directories and file
metadata are checked for drift. Final serialization has its own hard bound.

Partial, changed, linked, failed, or unvisited folders contribute zero bytes to
the complete-folder totals. Even a complete inventory always reports zero
reclaimed bytes and `cleanup_eligible=false`. It is not the verified archive
manifest: source hashes, dependency closure, independent restore, and reviewed
exact-file cleanup remain required by the archive contract.

## Update when

Update when selection, bounds, admission, request fields, receipt interpretation,
or wrapper parameters change. Put measured capacity and reclaim in item 325.
