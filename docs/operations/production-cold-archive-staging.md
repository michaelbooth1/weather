# Production cold-archive staging

This lane stages exact cold snapshot files into bounded local archive objects.
It is a prerequisite for the off-site workflow in
[Verified cold archive](verified-cold-archive.md), not restore or deletion proof.

## Scope and evidence

A measured candidate selection records exact relative names, native file
identity, sizes, timestamps and allocated bytes. Planning reads this retained
metadata only. It validates accounting and creates deterministic whole-file
chunks of at most 1 GiB and 256 files. Files larger than 1 GiB are refused.
Plain CSV and compressed CSV halves are independent selected objects.

The production CLI admits only immediate files of recognized market-day
snapshot folders strictly older than thirty days. Each source is pinned on
NTFS against writes, deletion and ancestor replacement while streaming its
SHA-256 into a deterministic USTAR/gzip archive. The completed object is reread
and every ordered header, member, content hash, padding and footer is checked.
No archive is extracted on the capture host.

Every attempt is create-only. Claim, archive, manifest, inner receipt, copied
request, execution receipt and wrapper receipt remain available for review.
A failure preserves partial evidence and spends that attempt path.

## Execution

Use the project interpreter and exact reviewed source checkout. Metadata-only
planning is:

```powershell
.\venv\Scripts\python.exe -m weather.operations.production_cold_archive_stage_cli plan --selection <absolute-selection-path> --selection-sha256 <raw-sha256> --output-path <new-absolute-plan-path>
```

The plan's raw SHA-256 binds a request with exactly these fields:
`schema_version`, `production_repo_root`, `execution_host_id`, `operation`
(`stage_only`), `approved_by`, `approved_at_utc`, `expires_at_utc`,
`plan_path`, `plan_sha256`, `chunk_id`, and `source_git_sha`.
The request must be currently valid and expire within 72 hours of approval.

Run one request at a time through `scripts/ops/production_cold_archive_run.ps1`
with mandatory `-ProductionRepoRoot`, `-RequestPath`, `-RequestSha256`,
`-OutputRoot` and `-ExpectedSourceTip`. Output must be a new immediate child of
production `scratch/production_cold_archive`. Source must be the exact clean
reviewed worktree; imports, request, source tip and host identity are checked.

This payload lane uses the ordinary capture-host 00:30-09:00 timetable,
excluding 04:45-06:45 for existing tiering jobs. Dated inventory/compression
exceptions do not admit it. It holds the shared workload lease, owns the whole
child tree in a kill-on-close Windows Job, and stops within 300 seconds with
teardown reserved before the window boundary. Streaming is throttled to
16 MiB/s; admission requires healthy capture, commit below 70%, at least
4 GiB physical memory available, and the bounded process memory checks.
The core reserves worst-case output plus 20 GiB capture headroom and 16 MiB
evidence headroom, then checks remaining reserve on every write.

## What a PASS establishes

A staging PASS proves byte identity during its pinned reads and local archive
readback. It keeps `source_retained=true`, `cleanup_eligible=false`,
`upload_performed=false`, `restore_performed=false` and
`consumer_closure_proved=false`. The outer wrapper additionally proves complete
child-tree teardown. It reports zero reclaimed bytes.

Transport must separately prove encryption and recovery-key custody, private
remote destination and exact object identity, independent remote download and
full restore. A later deletion lane must also prove consumer closure, retained
restore metadata and fresh exact source identity. This staging CLI exposes no
upload or source deletion operation.

## Update when

Update when chunk format, request fields, admission, output evidence or the
relationship to transport and verified reclaim changes.
