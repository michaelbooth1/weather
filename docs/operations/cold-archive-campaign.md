# Resumable verified archive campaign

The campaign coordinates the [production archive owners](production-cold-archive-staging.md)
and [recovery/reclaim contracts](cold-archive-locations.md). It never supplies
new selection, window, credential, capture, source-adoption or deletion authority.

## Bound launch

Prepare one immutable `cold_archive_campaign_config` document. The canonical
validator in `weather.operations.cold_archive_campaign` owns its exact fields:
production and workstation source/host identities; literal transport paths;
approved execution intervals; original approval/proposal/selection/plan hashes;
successful baseline reclaim receipts; the authoritative progress pointer; and
private workstation credential paths. It contains no credential values.

Use exact clean reviewed source checkouts on both hosts. Launch from the source
checkout through the repository script:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File <source-repo>/scripts/ops/cold_archive_campaign_run.ps1 -Configuration <absolute-config.json> -ConfigurationSHA256 <raw-sha256> -ExpectedSourceTip <full-source-tip>
```

The lightweight launcher owns a host-global controller mutex and a complete-child
Windows Job. Each production payload phase separately acquires its existing
workload lease. That lease is released during workstation work. The workstation
RPC launches only the canonical archive entry points through
`workstation_heavy.ps1`, preserving its assigned non-capture host/principal,
shared live/heavy mutex and child-tree containment. No Scheduler entry is created
by this launcher. The caller must retain and poll its process to terminal exit.

## Phase order and accounting

For each untouched whole chunk: stage, copy to workstation, encrypt, upload,
independent download, complete materialized restore, production catalog
publication, workstation recovery custody, verified workstation scratch cleanup,
fresh production protection review and original reclaim, then private recovery
metadata backup with independent download verification.

The controller reuses the original approved plan. Every chunk containing an
already reclaimed file is isolated as a whole; its residual bytes remain visible
and are not silently counted as capacity. A changed plan or conditional reserve
needs its own qualified binding. Only the canonical original-reclaim progress
counter counts toward the owner's target. Stage spools, workstation copies,
compression savings and synthetic fixtures do not count.

The first three batches must each contain at least 900 MiB of real logical
source data and complete every phase with 20% measured time margin before bulk
continuation. The optional `-MaximumBatches` bounds an attended qualification
invocation. It does not remove the three-batch gate on a later full invocation.

## Resource and time limits

Capture reads retain 16 MiB/s, 1 GiB/256-member chunks, existing output reserves,
384 MiB per-process monitoring, healthy capture and 300-second phase Jobs.
The archive-only memory policy is [owned by Host Load Policy](HOST_LOAD_POLICY.md#archive-only-memory-policy-approved-september-10):
80% system commit, 78% start margin over five two-second samples, and the
unchanged 4 GiB physical-memory floor.

Workstation archive verification and cleanup use 64 MiB/s local reads; cleanup
has 600 seconds, bridge encryption/restore 600 seconds, and network phases
900 seconds. Network caps stay 8 MiB/s; network budget calculations use a
conservative 2 MiB/s baseline. Required full hashes and full independent restore
are retained. Credential preparation refreshes only a fresh encrypted config,
checks enough token lifetime for the phase, then pins that prepared copy.
Production rate and deadline defaults do not inherit workstation settings.

## Stop and resume

Create `scratch/ac-control/<campaign-id>/STOP` to request a stop before the next
phase. The controller finishes its active phase first. Keep the exact config,
source checkouts, receipts and existing attempt namespaces when resuming.
Remove only that deliberate STOP marker after renewed resume authorization.

Each phase has an immutable claim and an atomically published completion.
A claimed phase is reconciled from its exact result and completed child-tree
receipt; it is never blindly dispatched again. Successful earlier phases use
their retained metadata. A missing, failed or ambiguous terminal record pauses
for inspection. A successful remote upload must never be repeated to repair
catalog, custody, cleanup or bookkeeping.

The workstation publishes its RPC completion only after the canonical child
wrapper exits and the enclosing Job is empty. SSH disconnection alone is not
termination proof. Inspect the retained exact completion record on recovery.

Recovery bundles retain catalog, restore, custody, reclaim and phase receipts,
plus current original progress and location inventory. They contain no payload
or credential values. The workstation keeps the bundle, and its private Drive
copy must be independently downloaded and byte-verified before the batch is
reported complete. The actual catalog and recovery-key custody remain the
authority for restoring archived inputs.

## Update this file when

Update when configuration, phase order, resume semantics, resource profiles,
qualification or backup/accounting contracts change.

After three qualifying batches, progress includes a conservative remaining active-work
estimate from verified reclaimed bytes and phase timings of the last three batches,
using the slowest observed rate plus 20 percent. It explicitly excludes resource
admission waits and closed schedule windows; no numerical ETA is emitted before
real-batch qualification.
