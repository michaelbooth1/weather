# One-night retained-file storage recovery

Status: canonical. Owner: operations.

This controller composes the [qualified compression and retained verification
wrappers](cold-snapshot-compression.md) under explicit one-night authority.
It does not merge source, stop capture, delete files, upload archives, or grant
live trading authority. Ordinary attended compression remains available.

## Authority and preparation

Use a clean reviewed isolated source checkout and a full source Git SHA.
Qualify the exact source on the separate admitted workstation, including native
Windows wrapper containment and recovery tests, before host registration.
Production capture continues to import its own checkout.

The immutable plan uses the registry's `storage_recovery_night_plan` schema.
It binds one Toronto night, production root, MachineGuid-derived capture-host
identity, source root/full SHA, named approval before the night, and expiry at
09:00 that morning. Bind both a completed baseline closeout and its retained-file
ledger by exact path and SHA-256. Baseline reconciliation must have zero unmatched
preimages, unverified compressed files, active recovery processes and deletions.
Baseline bytes count toward the cumulative target, never as new overnight savings.

Name at most ninety exact cold-date groups, each containing one to twelve
built-in snapshot event directories. Inventory examines their immediate files.
Missing directories receive zero capacity credit; a partial inventory cannot
authorize compression. No recursive discovery or hot-file selection is allowed.
The two filenames `order_books.jsonl` and `order_books_long.csv` belong
exclusively to the existing scheduled gzip jobs and are excluded even when small
enough for NTFS compression. A baseline ledger containing either requires separate
reconciliation before this controller can be armed.
The planner retains the 1 MiB minimum, 64 MiB maximum file size, 256-file /
1 GiB batch bounds, dry-run pilot and positive verified pilot before expansion.

The plan also binds cumulative newly-reclaimed and free-disk targets, and
independent file, attempt, recovery, logical-input and evidence budgets. The
contract module owns their ceilings. A target is an objective, not a forecast.

## Registering the night

Run `scripts/ops/register_storage_recovery_night.ps1` with exact
`-ProductionRepoRoot`, `-PlanPath`, `-PlanSha256` and `-ExpectedSourceTip`.
First include `-PreflightOnly`. This creates a new S4U/Limited one-shot forty-five
seconds ahead. Wait for its task exit and hash-bound PASS receipt before running
the same registrar without that switch. Register at least five minutes before
00:30. Existing task or output names are spent and cannot be overwritten.

Preflight checks the actual wrapper owner PID/creation token and ancestry,
native host, source imports, source cleanliness, plan and baseline hashes,
ordinary evidence paths, and child-tree teardown. It reads no source payloads
and performs no compression, so it may run before the heavy-work window.

The two one-shot tasks are named
`WeatherStorageRecovery-<plan_id>-early` and
`WeatherStorageRecovery-<plan_id>-late`. They start at 00:30 and 06:45 Toronto,
with absolute controller deadlines 04:42 and 08:55. Starts over sixty seconds
late are refused. Scheduler limits are PT254M and PT134M, with wake enabled,
IgnoreNew, hidden execution and no late catch-up. These bounds protect the
existing 05:00/06:00 tiering jobs and the 09:00 heavy-work boundary.

Registration retains create-only intents, exact exported task XML and readback
receipts under `scratch/storage_recovery_nights/<plan_id>/registration-*`.
Verify the future triggers, exact actions, principal, settings, source tip and
plan hash again after arming. A successful registrar alone does not prove reclaim.

## Execution and recovery

The lightweight controller holds a kill-on-close Job over its complete child
tree. It does not hold the heavy-work lease while waiting. Each inventory,
dry run, apply or retained verification uses the existing wrapper and holds the
shared lease independently through teardown. Compression's optional
`-MaxRuntimeSeconds` can only shorten its existing 600-second ceiling; the night
controller selects 300 seconds for apply and 90 for dry run/verification.

Before dispatch the controller requires three headroom samples five seconds
apart: commit below 66% and at least 4.5 GiB physical availability. Children
retain the harder existing commit-below-70%, 4 GiB physical, capture health,
disk reservation, rate and deadline checks. No consumer may weaken those checks
to make a batch pass.

Only a busy lease before dispatch or explicit memory-only admission failure
with proved complete teardown may pause and resume automatically. Reconcile all
completed journals against fresh inventory before crediting interrupted work.
An unmatched durable preimage requires fresh inventory and the qualified
read-only verifier before further compression. Hash, native identity, source,
request, missing-receipt, hard-stop, capture-health, unexpected failure and
unproved-teardown disagreements stop the night. Spent attempts remain intact.

Late continuation requires a complete hash-bound safe early result and ledger,
zero-child teardown and a consistent group cursor. Existing early output without
that proof blocks continuation. If early output was never created, late starts
fresh and credits no early work. A safe partial early segment may carry a pending
file, but late must reconcile it before compression.

## Evidence and closeout

Each segment retains step intents, requests, wrapper and journal hashes, recovery
events, atomic `progress.json`, create-only `verified-files.json`, `result.json`
and the outer `wrapper-result.json`. Paths live under production ignored
`scratch/storage_recovery_nights/<plan_id>`; heavy attempts remain in their
existing inventory/compression families.

Outer PASS means contained orchestration ended in a recognized safe terminal,
including a resource-, window- or budget-limited partial result. Only
`target_met=true`, verified allocation deltas and actual free-disk evidence
establish the requested capacity outcome. Deduplicate retained path and native
identity across the baseline and both segments. Report unverified or uncredited
files explicitly; a blocked result uses unknown integrity status, never zero.

## Update when

Update when night authority, scheduler timing, budgets, automatic recovery,
containment, continuation or evidence contracts change. Record measured outcomes
and remaining work in item 325.
