# Agent report 2026-09-111g — landing 110j C (compress on close)

**Verdict: READY FOR PRODUCTION REVIEW, roll-sensitive. The branch is merged with current `origin/master`,
the one conflict is resolved, and it is open as a draft PR. It is a small relief, not a fix: projected
~1.2 GiB/day against ~11 GB/day net decline. The measured NTFS ratio for token tapes is 2.3-2.7x, not the
72-74x gzip figure earlier storage notes imply.** CI status and head SHA are in the reply that hands this
report back (they postdate this commit).

- PR: https://github.com/michaelbooth1/weather/pull/142 (draft), branch `codex/compress-on-close-20260926`.
- Code tip reviewed here: `2ce00282f` (merge `e313195a` of `origin/master` `85092752a`, plus the regenerated
  correspondence index). This report and one runbook paragraph are committed on top.
- Handoff: `docs/roadmap/workstation-handoff-2026-09-111g-compress-on-close-landing.md` on
  `origin/codex/exam-fixes-handoffs-20260929`. Original build report: [110j C](agent-report-2026-09-110j-c.md).

## What the merge changed

- **Conflict 1:** `scripts/ops/cold_snapshot_compression_run.ps1`. Master's 91a added `-Nightly`, and this
  branch added `-CompressOnClose`, on the same lines. Both are kept. A new guard refuses the two together,
  because each selects a different child module and the last assignment would otherwise win silently.
- **Conflict 2:** `docs/roadmap/correspondence-index.md`. Took master's copy and regenerated it with
  `weather.reporting.roadmap.correspondence_index` after the merge commit.
- **Semantic fix:** master's 91a text in `docs/operations/cold-snapshot-compression.md` still said
  compress-on-close was "design only" and that `SnapshotStore` was unmodified. Both are false with this
  branch, so that paragraph now points at the implemented lane.
- `ntfs_file_compression.py` left the diff: 91a landed the same configurable handle limit on master.
- **Reader re-check:** no commit on master since the branch point (`965374a0`) added or changed a reference to the four
  retired CSVs (`snapshots_long`, `features_long`, `variant_predictions_long`, `snapshot_explanations_long`).
  The remaining unmigrated references in the merged tree are the ones the
  [projection reader contract](../operations/snapshot-projection-readers.md) already classifies. They are
  retention, schema or rebuild contracts, docstrings, a PIT CLI default resolved through
  `discover_settled_folders` → `projection_source`, and `clob_features_long` (a separate family).

## Expected reclaim (measured vs projected)

**Measured** on the workstation's frozen 2026-08-12 mirror (no reserved window; read-only copies into session
scratch, `compact /c`). Folders: Toronto 2026-08-08 and Seattle 2026-07-20. Sizes also taken for San
Francisco and Seattle 08-08 and SF/Toronto 07-20.

| File, one market-day | Logical | NTFS allocated | Ratio |
| --- | ---: | ---: | ---: |
| `clob_tokens.jsonl` (Toronto / Seattle) | 88.6 / 85.6 MB | 33.2 / 32.6 MB | 2.7x / 2.6x |
| `clob_tokens.csv` | 46.0 / 44.8 MB | 20.1 / 19.6 MB | 2.3x / 2.3x |
| `variant_predictions_long.csv` | 31.2 / 24.4 MB | 15.6 / 12.3 MB | 2.0x |
| `snapshot_explanations_long.csv` | 31.8 / 26.3 MB | 9.8 / 8.1 MB | 3.2x |

The sum of the four retired CSVs per market-day was 52.8-65.7 MB across six samples, mean 56.4 MB. The
two small ones are `snapshots_long.csv` (1.8-2.4 MB) and `features_long.csv` (0.25-0.30 MB).

**Projected.** These assume 12 markets (`BUILTIN_SPECS`) and July/August per-day sizes. Current per-day
sizes and the live market count were not measured, because the mirror is frozen.

- **Writer switch** (four CSVs no longer created on new days; the JSONL is already written): about 56 MB × 12
  ≈ **0.63 GiB/day**. It applies from the first capture day after adoption and needs no task.
- **Compress on close:** about 80 MB saved per market-day, which is ≈ 0.89 GiB/day if every token tape were processed.
  **Each invocation is capped at 1 GiB logical and 32 files**, so one invocation reclaims about **0.6 GiB**.
  One attended run a night therefore gives about 0.6 GiB/day, and two give about 0.9.
  Selection walks every closed folder, so a run spends its budget on the ~101 GiB token backlog (60 + 41 GiB
  logical on 09-24), in folder-name order, before it reaches the newest day.
- **Total:** about **1.2 GiB/day** with one run a night. At ~11 GB/day net decline, that moves the
  50 GiB suite floor by roughly half a day. The larger lever is still 91a's registered nightly lane
  (≥14-day folders, up to 32 GiB/night, which also covers the token backlog). Once 91a runs, compress-on-close adds a
  one-time ~12 GiB (days 1-13 compressed early) rather than a larger slope.
- After 91a compresses day-14+ folders, the writer switch's durable saving shrinks to the compressed residual
  (2.0-3.2x). Its first-14-day saving is the full logical size.

## Per-file roll verdict inputs

The file list and the per-file treatment are unchanged from the [110j C table](agent-report-2026-09-110j-c.md#per-file-roll-classification),
except that `ntfs_file_compression.py` has left the diff. My edits touch only `.ps1`, `docs/` and the
report, which are roll-free by contract. The load-bearing Python change is the capture writer switch in
`src/weather/collection/snapshot_store.py` (snapshot closure). `src/weather/schema_registry_recent_data.py` is in all four closures
and its change is **additive-only**: two new `SchemaSpec` rows, `compress_on_close_policy_v0.1` and
`compress_on_close_receipt_v0.1`. Treat it as a roll of every loop that is behaviourally inert for this family. Derive the actual
verdict on production:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch codex/compress-on-close-20260926
```

Land it through `scripts\ops\quiet_window_merge.ps1 -Branch codex/compress-on-close-20260926` in 01:00-04:00.
The whole branch goes together: do not land the writer switch without the readers.

## Production enable steps (after adoption; checked against current master)

**No registrar exists for this lane.** `register_cold_snapshot_nightly.ps1` registers only
`WeatherColdSnapshotNightly` (`-Nightly`). Compress-on-close is an **attended** wrapper invocation. It has its
own policy, 00:30-09:00 minus the 04:45-06:45 tiering reserve, a 600 s deadline, the shared
`cold_snapshot_compression` lease and a 50 GiB free floor. If `WeatherColdSnapshotNightly` is registered, it holds
that lease from 00:30 until at most 04:45. Run compress-on-close after it finishes, or at 06:45-09:00.
A scheduled lane would need a new registrar and a reviewed decision. That is not in this branch.

1. Write the policy once, as an immutable file (≤31 days; `max_bytes` ≤ 1073741824). `schema_version` must be
   `compress_on_close_policy_v0.1`. `execution_host_id` is `Get-WeatherExecutionHostId` from
   `scripts/ops/workload_admission.ps1` on the capture host. The exact field set is
   `schema_version, production_repo_root, execution_host_id, approved_by, approved_at_utc, expires_at_utc,
   operation="compress_and_retain", max_bytes`.
2. From the clean adopted production checkout (tip = adopted master), dry run and then apply. Each run needs a
   new, empty output folder directly under `scratch\cold_snapshot_compression`:

```powershell
$repo = (Resolve-Path .).Path
$tip = (git rev-parse HEAD).Trim()
$request = Join-Path $repo 'scratch\compress-on-close-approved.json'
$hash = (Get-FileHash -LiteralPath $request -Algorithm SHA256).Hash.ToLowerInvariant()
.\scripts\ops\cold_snapshot_compression_run.ps1 -CompressOnClose -ProductionRepoRoot $repo -RequestPath $request -RequestSha256 $hash -ExpectedSourceTip $tip -OutputRoot (Join-Path $repo 'scratch\cold_snapshot_compression\close-plan-01')
.\scripts\ops\cold_snapshot_compression_run.ps1 -CompressOnClose -Apply -ProductionRepoRoot $repo -RequestPath $request -RequestSha256 $hash -ExpectedSourceTip $tip -OutputRoot (Join-Path $repo 'scratch\cold_snapshot_compression\close-apply-01')
```

3. Review `result.json` and each `NNN-before/after.json` (`reclaimed_bytes`, equal hashes, unchanged
   file ID and mtime). Count only `VERIFIED` rows. A failed attempt is retained and inspected, never reused.
4. The writer switch needs no step. After the merge's capture recovery, confirm on the first new event day
   that capture made no `snapshots_long.csv` and that `snapshots.jsonl` grows.

## Verification

- Local focused suite, through `scripts\ops\workstation_heavy.ps1 -Kind pytest` with `--basetemp C:\tmp\pt111g`:
  **440 passed, 59 subtests passed.** It covered the branch tests, the 91a cold-snapshot compression,
  wrapper, nightly and verification tests, storage classes, daily refresh, the live-variant settlement
  scorecard, and the audits (agent docs, import architecture, knowledge structure, module size, path policy,
  schema registry, Python runtime).
- **Merge-induced failure fixed:** the merge left `daily_refresh_reporting_steps.py` at 2,001 lines, over
  the module-size warning threshold (≥ 2,000). The branch's stray top-of-file import moved into the
  `weather.*` group, and a now-redundant `exists()` guard came out, because `projection_glob` yields nothing
  for a missing root. The file is back to 1,999 lines, and the audit's allowance is untouched.
- A first run with a ~180-character `--basetemp` failed both native `test_compress_on_close` cases with
  `FileNotFoundError` on the writer-lock path, because the path passed Windows MAX_PATH. That was a test-harness path artefact
  and not a product defect. The cases pass with a short basetemp, as the 110j C qualification also used.
- Full GitHub CI on PR #142: conclusion in the handback reply.

## What was NOT done

No production access, no `data/` writes, no registration or Scheduler change, no restart, no merge to
master, and no force-push or rebase. The mirror was read only, and the measurement copies stayed in session scratch.

## Reproduce the ratio measurement (workstation)

```powershell
$src = '<mirror>\data\snapshots\highest-temperature-in-toronto-on-august-8-2026'
$dst = '<scratch>\lznt1'; New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item "$src\clob_tokens.jsonl","$src\clob_tokens.csv" $dst
compact /c /q "$dst\*" | Out-Null; compact "$dst\*"
```

On production, the apply receipts' verified allocation deltas replace this estimate.
