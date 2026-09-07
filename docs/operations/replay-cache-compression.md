# Bounded replay-cache compression

This runbook owns lossless NTFS compression of explicitly named cold replay
cache files. It retains every file, path and logical byte. It is not cache
eviction, archive acceptance, or authority to delete any evidence.

The owner approved implementation of the September 7 storage-reclaim review.
The scope is a one-file pilot followed by measured small batches, using the
existing capture-host window, shared lease, capture-health checks and resource
limits. [Item 325](../roadmap/items/item-325-tiered-data-retention-and-verified-archive-offload.md)
owns current qualification and execution results.

## Contract and admission

`scripts/ops/replay_cache_compression_run.ps1` is the attended production
entrypoint. Its Python child is `weather.operations.replay_cache_compression`.
Use a clean reviewed source worktree and an exact source commit; the wrapper
binds Python imports to that checkout while targeting the explicitly named
production repository. It does not modify production source or restart capture.
Git integration follows the separate canonical roll verdict and merge rules.

- Only `data/backtest/replay_cache/<event>/<consumer>__<12hex>__<12hex>__<12hex>.json`
  files named in the approved request are admitted. No recursive discovery.
- At most ten files, 64 MiB per file, 512 MiB total, last written at least thirty
  days earlier. The first production request names only one file. Age is an
  I/O-quiescence precaution, not a deletion or reachability rule.
- Native handles pin ancestors against rename/replacement and deny file writers
  and deletion for the entire hash/compress/hash operation. Hardlinks, reparse
  points, alternate streams, non-NTFS files, and unsupported attributes fail.
- The wrapper proves the dedicated capture host, takes the shared workload
  lease and contains its child tree in a kill-on-close Windows Job. Python
  verifies the live wrapper's PID/creation identity, its own ancestry and the
  actual OS-held lease file. A stale owner record cannot admit work.
- Both entrypoint and child require 00:30–09:00 America/Toronto. The wrapper
  additionally excludes **04:45–06:45**, reserving the shared lease for the
  canonical 05:00 projection / 06:00 raw-tape tiering jobs and their teardown.
  It reserves fifteen seconds before 04:45 or 09:00 for its own teardown;
  maximum child runtime is ten minutes. A cache batch must not make a larger
  scheduled reclaim skip at a busy lease. Recheck the actual tiering task
  definitions before attended execution; a changed schedule needs review of
  this reservation. No Stage-A or protected-window exception is provided.
- Require all three capture loops to be active, non-degraded and bound to
  matching live status/lock PIDs and process-creation identities. Heartbeats
  must be no more than 180 seconds old and cannot be future-dated. Snapshot's
  last clean iteration must be no more than 900 seconds old; a heartbeat alone
  cannot prove progress. Require at least 4 GiB physically available and
  host commit strictly below 70%. The child rechecks these at least once per
  second during streaming and between files. Any failure stops the batch.
- This bounded compression lane reserves **20 GiB for capture plus two complete
  64 MiB file images and 1 MiB for evidence**. No generic heavy-work disk floor
  is changed. The reservation is independent of the ordinary 50 GiB threshold;
  it cannot be used for training, replay, arbitrary compression or deletion.
- Hash reads use 1 MiB buffers at 8 MiB/s. Native compression itself is a
  synchronous call over at most 64 MiB and is not claimed to be rate-limited.
  The actual Python worker sets and verifies its own BelowNormal priority;
  lowering only the venv redirector is insufficient. Parent and child check a 384 MiB working/private
  memory ceiling. The native incompressible-file qualification owns measured
  allocation and timing evidence, not a claim that kernel work is zero-cost.

Windows documents this representation as transparent to ordinary readers:
[file compression](https://learn.microsoft.com/en-us/windows/win32/fileio/file-compression-and-decompression),
[handle-based compression](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_set_compression).
The native fixture tests also exercise the existing replay-cache reader.

## Exact request

Create a small request outside `data/` after observing the exact paths and
metadata. `mtime_ns` is a decimal string to preserve Windows timestamp precision
through JSON tooling. Approval expires within seventy-two hours. Each file has
only `path`, `size_bytes`, and `mtime_ns`; unknown fields are rejected.

```json
{
  "schema_version": "replay_cache_compression_request_v1",
  "production_repo_root": "C:\\absolute\\weather",
  "operation": "compress_and_retain",
  "approved_by": "operator identity and decision reference",
  "approved_at_utc": "2026-09-07T18:30:00+00:00",
  "expires_at_utc": "2026-09-08T13:00:00+00:00",
  "execution_host_id": "<exact dedicated capture host SHA-256 identity>",
  "files": [
    {
      "path": "backtest/replay_cache/<event>/<consumer>__<12hex>__<12hex>__<12hex>.json",
      "size_bytes": 53413071,
      "mtime_ns": "<exact observed Unix nanoseconds>"
    }
  ]
}
```

The example is deliberately not executable. Use actual observed metadata,
current approval times, exact source commit and the request file's SHA-256.

```powershell
& 'C:\reviewed\weather-source\scripts\ops\replay_cache_compression_run.ps1' -ProductionRepoRoot 'C:\absolute\weather' -RequestPath 'C:\approved\request.json' -RequestSha256 '<64hex>' -OutputRoot 'C:\absolute\weather\scratch\storage_reclaim\unique-plan-attempt' -ExpectedSourceTip '<40hex>'
```

Without `-Apply`, the operation produces a bounded hash/metadata plan and does
not compress. Review the child and wrapper PASS receipts, then hash the plan's
`wrapper-result.json`. Apply requires `-Apply -PlanReceiptPath <absolute-plan-wrapper-result.json>
-PlanReceiptSha256 <64hex>` with a **new output attempt**. The wrapper receipt
must prove successful teardown and bind the exact child result hash. The child
result must name precisely the approved files and the same source/request.
Before mutation, apply rechecks each file's hash and native identity against
that reviewed plan, including replacements that preserve size and timestamp.
The same unexpired approved request may be used if all bindings still match.
Plan and apply both need full admission; neither is a daytime scan. Old plan
receipts without the child-result hash cannot authorize apply.

## Evidence, failure and completion

Each attempt is create-only. Native directory handles keep the evidence path
and every ancestor in place throughout the child's operation. Wrapper checks
reject redirected evidence ancestors before dispatch and final publication.
`request.json` claims the child attempt; each
`NN-before.json` is flushed before mutation and binds path, native file identity,
size, timestamp, SHA-256 and allocation. `NN-after.json` proves unchanged
logical bytes/identity/time and native LZNT1 compression. `result.json` records
the batch outcome. An early child refusal is preserved in `refusal.json`.
`wrapper-result.json` independently records child completion, the exact child
result hash and proved zero-process Job teardown before success is claimed.
The wrapper rechecks source cleanliness/tip and the request hash at completion.

Report native allocation deltas separately from volume free-space deltas,
which include concurrent capture. Stop expansion on zero or negative savings.
A synthetic ratio is not a prediction for the real cache. First expansion is
at most ten files / 512 MiB; each later batch requires a new explicit request.

A failed or killed run is **retain and inspect**, never permission to delete,
force-recompress, clear the attempt, or manufacture success from free space.
Some files may already be compressed even if the batch failed. Preserve the
preimage receipts and independently verify their hashes under fresh admission
before any further action. Automatic resume and automatic decompression are
intentionally absent; decompression needs its own space and resource review.

## Update when

Update with changes to admission, path/byte limits, approval bindings, native
file semantics, the command surface, receipt schemas or failure handling.
