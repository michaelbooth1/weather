# Capture-host data offboarding plan — 2026-10-23

- **Owns:** the plan for moving old evidence off the 16 GB capture host's `data/` to the existing cold Drive tier, so that
  more markets fit: what may move, in which tranches, how each tranche is verified, and what the owner sees first.
- **Read when:** preparing or approving an offboarding tranche, or sizing disk for more markets.
- **Do not use for:** today's free space (`Get-Volume -DriveLetter C` on the host), lane mechanics (linked owners below), or
  any authority to move or delete. This is a plan. Nothing was moved, deleted or measured for it.

**Owner decisions this plan follows (2026-10-23, relayed):** offboard to the existing cold Drive tier with hash
verification; never delete; the owner sees the exact list before anything moves. Storage growth is accepted, and offboarding
is preferred. Earlier owner rulings that would *delete* (the `backtest/replay_cache` waiver, the `order_books_long.csv.gz`
twin deletes: DECISION_LOG.md:49, :95) are treated here as superseded by "never delete": those files go to Drive instead.
The owner should confirm this reading (gap G9).

Workstation desk work: tracked docs, code and manifests at `5bbdd4280` only. No file under `data/` was read, and no
script was run against the Scheduler, leases, Drive or remotes. **[M]** means measured, with its source and date. **[E]**
means estimated, with the method stated.

## 1. Biggest trees under the host's `data/`

No full measurement exists after 2026-10-02. Since then the 91a nightly has compressed old days in place: 20.4 GB on 10-08
and about 16 GiB on 10-11 (more-markets-desk-study-2026-10-14.md:156). So every on-disk figure below is an upper bound for
today. The last whole-volume reading in the repo is **158.4 GiB free at the 10-14 host stat** [M] (DATA_LAYER_V2_PLAN.md:20).
Whole `data/`: **4,441,260 files, 685 GiB logical** [M, 2026-09-24 stat-only walk] (storage-plan-2026-09-23.md:61).

| Tree (path under `data/`) | Size GiB | Date, source | Class | Tranche |
| --- | --- | --- | --- | --- |
| `snapshots/<event>/` immediate files, all families | ~453 on disk, almost all uncompressed then | [M] 09-24, storage-plan:64-67 | mixed, below | below |
| · `replay_inputs.jsonl` | 82.5 uncompressed + 1.8 compressed | [M] 10-02, drive-offload-2026-10-02.md:28 | A | never (DL 09-26 #11) |
| · `clob_tokens.jsonl` + `clob_tokens.csv` | 67.3 + 41.0 uncompressed | [M] 10-02, drive-offload:35 | A | T3 |
| · `variant_predictions.jsonl` + `_long.csv` | 58.5 uncompressed + 5.0 compressed | [M] 10-02, drive-offload:33 | A (+B twin) | T5 |
| · `order_books_summary.csv` | 44.7 uncompressed + 4.0 compressed | [M] 10-02, drive-offload:34 | B | T4 |
| · `snapshot_explanations*` + `clob_capture_status.jsonl` | ~37 uncompressed | [M] 10-02, drive-offload:36 | A | T4 |
| · `order_books_long.csv.gz` | 34.7 (already gzip) | [M] 10-02, drive-offload:41 | B (A where no twin) | T2 |
| · `order_books.jsonl.gz` | 23.9 (gzip) | [M] 10-02, drive-offload:32 | A | keep (exam join); ≤07-30 later |
| · `price_history.jsonl` / `raw_manifest` / `.csv` | 7.89 | [M] 09-26, storage-value-assessment-2026-09-26.md:39 | A / B | T2 |
| · snapshot/feature long CSVs, `snapshots.jsonl`, manifests, markers | ~5.4 (compressed) | [M] 10-02, drive-offload:27 | A / B | never (label and replay readers) |
| `snapshots/<event>/forecast_payloads/` (nested, legacy) | 36.11 | [M] 09-26, SVA:34 | A (only issue-time archive, DL 10-15 Q15) | deferred |
| `snapshots/<event>/price_history_raw/` (nested, 3.46 M files) | 21.26 | [M] 09-26, SVA:38 | A | T8 |
| `mm_runs/` + `taker_runs/` (retired) | 51.4 logical, 26.2 on disk after NTFS | [M] 09-26, SVA:7 | A + B projections | T7 |
| `backtest/replay_cache/` | 32.28 (logical; called stale at item-325:562) | [M] 09-26, SVA:44 | C | T6 |
| `forecast_payload_cas/` | 13.1 | [M] 09-26, drive-offload:30 | A (shared CAS, GC disabled) | never |
| Historical source rows, WU history | 18.38 | [M] 09-26, SVA:47 | A, serving reads | never |
| `backtest/` root exports | 10.73 | [M] 09-26, SVA:45 | B | T9 |
| Rotated diagnostics JSONL (`snapshots/`) | 7.03 (`observation_triggers` 1.22 protected) | [M] 09-26, SVA:50 | C (DL 09-26 #7) | T9 |
| Rotated console logs | 5.56 | [M] 09-26, SVA:49 | C | T9 |
| 88a `maker_evidence`, `execution_tape`, `settlements`, `wallet_ledger`, labels | 3.71 | [M] 09-26, SVA:52 | A, live loops | never |
| `archive/closed_market_days` Parquet; `cold_archive` catalog | 2.46; 0.1 | [M] 09-26, SVA table | B; A | never |
| `maker_shadow/` (forward shadow, active 24/7) | not measured; 126-380 MB/day | [E] DATA_LAYER_V2_PLAN.md:126 | A, embargoed | never while embargoed |

Already on Drive: 1,989 files, 90.84 GiB. Another 32 files (1.55 GiB) are on Drive and still local [M, 09-13, `WHERE_DATA_IS.md` via drive-offload:45].

### 1a. Host measurement to run before any approval (the operator runs it; it was not run for this plan)

A stat-only, size-only survey. It opens no file and reads no contents. Directory enumeration supplies size, mtime and
attributes from the directory entries. Only NTFS-compressed or sparse files get one extra metadata call
(`GetCompressedFileSizeW`) to read their allocated bytes. The process runs at background CPU and I/O priority. It stops at
6,000,000 entries or 1,200 s, writing `partial`. The 2026-09-24 walk of 4.44 M files took 3 minutes. Within its own
process it skips reparse points. It aggregates by tree, by family and by a single mtime cut (before 2026-09-26 local, or
later). The embargoed and live trees (`maker_shadow`, `maker_evidence`, `execution_tape`, `settlements`, `wallet_ledger`)
get totals only, with no per-date split. Its output goes to `scratch\`, never under `data\`.

**Slot:** start 00:30-04:15 on a night with no landing, so that it ends before the 04:45 tiering reserve. Hold the shared
lease through `scripts/ops/workload_admission.ps1`. The wrapper below copies the
`closed_day_projection_twins_run.ps1` pattern.

Save as `scratch\offboarding_survey\survey.py` in the production repository:

```python
import ctypes, datetime as dt, json, os, shutil, sys, time
from ctypes import wintypes
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.SetPriorityClass(k32.GetCurrentProcess(), 0x00100000)  # PROCESS_MODE_BACKGROUND_BEGIN (low CPU and I/O)
k32.GetCompressedFileSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
k32.GetCompressedFileSizeW.restype = wintypes.DWORD
root, out = sys.argv[1], sys.argv[2]
MAX_ENTRIES, MAX_SECONDS, MAX_KEYS = 6_000_000, 1200, 20_000
CUT = dt.datetime(2026, 9, 26).timestamp()
TOTALS_ONLY = {"maker_shadow", "maker_evidence", "execution_tape", "settlements", "wallet_ledger"}
def allocated(path, st):
    if st.st_file_attributes & 0xA00:  # compressed or sparse: metadata call, no content read
        hi = wintypes.DWORD(0); lo = k32.GetCompressedFileSizeW(path, ctypes.byref(hi))
        if lo != 0xFFFFFFFF or ctypes.get_last_error() == 0:
            return (hi.value << 32) + lo
    return -(-st.st_size // 4096) * 4096
def key(parts):
    top = parts[0] if len(parts) > 1 else "<root files>"
    if top in TOTALS_ONLY: return top, "*"
    if top == "snapshots":
        return top, (parts[2] if len(parts) == 3 else "<nested>/" + parts[2] if len(parts) > 3 else "<root files>")
    return top, (parts[1] if len(parts) > 2 else "<files>")
agg, t0, n, skipped, errors, partial = {}, time.monotonic(), 0, 0, 0, None
free_before = shutil.disk_usage(root).free
stack = [(root, ())]
while stack:
    d, parts = stack.pop()
    try: it = os.scandir(d)
    except OSError: errors += 1; continue
    with it:
        for e in it:
            n += 1
            if n > MAX_ENTRIES or time.monotonic() - t0 > MAX_SECONDS:
                partial = "entry_or_time_bound"; stack.clear(); break
            st = e.stat(follow_symlinks=False)  # cached from the directory listing on Windows
            if st.st_file_attributes & 0x400: skipped += 1; continue  # reparse point: not followed
            p = parts + (e.name,)
            if e.is_dir(follow_symlinks=False): stack.append((e.path, p)); continue
            top, fam = key(p)
            bucket = "*" if fam == "*" else ("before_09-26" if st.st_mtime < CUT else "09-26_or_later")
            k = f"{top}|{fam}|{bucket}"
            if k not in agg and len(agg) >= MAX_KEYS: k = f"{top}|<other>|{bucket}"
            row = agg.setdefault(k, [0, 0, 0, 0])
            row[0] += 1; row[1] += st.st_size; row[2] += allocated(e.path, st); row[3] += bool(st.st_file_attributes & 0x800)
json.dump({"schema": "offboarding_size_survey_v1", "root": root, "entries": n, "partial": partial,
           "reparse_points_skipped": skipped, "dir_errors": errors, "seconds": round(time.monotonic() - t0, 1),
           "free_bytes_before": free_before, "free_bytes_after": shutil.disk_usage(root).free,
           "rows": {k: dict(zip(("files", "logical", "allocated", "ntfs_compressed_files"), v)) for k, v in sorted(agg.items())}},
          open(out, "x", encoding="utf-8"), indent=1)
```

Run from the production repository root:

```powershell
$repo = (Get-Location).Path; $ErrorActionPreference = 'Stop'
. .\scripts\ops\workload_admission.ps1; . .\scripts\ops\windows_kill_on_close_job.ps1; . .\scripts\ops\memory_guard_status_reader.ps1
$now = Get-Date
if ($now.TimeOfDay -lt [TimeSpan]'00:30' -or $now.TimeOfDay -ge [TimeSpan]'04:15') { throw 'outside the 00:30-04:15 survey slot' }
$mem = Read-WeatherMemoryGuardStatus -Path "$repo\data\logs\memory_commit_guard_status.json"
if (((Get-Date) - $mem.last_write_time).TotalMinutes -gt 5 -or [double]$mem.row.commit_percent -ge 70) { throw 'memory evidence blocks admission' }
$out = "$repo\scratch\offboarding_survey\survey-$($now.ToString('yyyyMMdd-HHmm')).json"
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload 'offboarding_size_survey'
if ($null -eq $lease) { throw 'lease busy' }
$job = $null; $child = $null
try {
    $job = New-WeatherKillOnCloseJob
    $tokens = @('-I', "$repo\scratch\offboarding_survey\survey.py", "$repo\data", $out)
    $child = Start-WeatherProcessInJob -Job $job -FilePath "$repo\venv\Scripts\python.exe" -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) -WorkingDirectory "$repo\scratch\offboarding_survey"
    $null = $child.Handle
    if (-not $child.WaitForExit(1500 * 1000)) { throw 'survey exceeded 25 minutes' }
    if ($child.ExitCode -ne 0) { throw "survey exit $($child.ExitCode)" }
} finally {
    try { if ($job) { $job.TerminateAndWait(5000) } } finally { if ($child) { $child.Dispose() }; if ($job) { $job.Dispose() } }
    Exit-WeatherHeavyWorkloadLease -Lease $lease
}
```

Use the survey's `allocated` bytes in the `before_09-26` bucket to replace every [E] in §4 before the first owner list.

## 2. Classification (policy that classifies each)

Classes come from `src/weather/operations/storage_classes.py` and the contract (data-storage-class-contract.md:18-22).

- **A, keep forever (may move cold, never deleted):** every `canonical_evidence` family, including snapshot JSONL,
  `replay_inputs`, raw forecast payloads, CLOB books and token maps, `clob_capture_status`, price-history source,
  `mm_runs` lifecycle and risk ledgers, taker ledgers, 88a journals (data-retention-policy.md:110-121), `forecast_history`,
  execution tape, settlements, labels and wallet ledger. Also anything under a hold: the 88a retention hold
  (STATE_OF_PLAY.md:62), the maker shadow embargo (:38-39), and the EF §8bb `mm_runs` dates 07-31..08-08 (SVA:41).
- **B, regenerable (contract:21).** Each item below gives the rebuild source and command.
  - `order_books_long.csv.gz`, where a same-folder `order_books.jsonl.gz` exists. Exactness proof:
    `closed_day_projection_twins_run.ps1 -Command plan-twins`, then `-Command prove-twins`
    (data-retention-policy.md:341-381). Never `-Command apply`, which unlinks. No file-writing rebuild CLI exists
    (gap G6), so recovery is a Drive restore. Cost: not measured. The proof is ≤ 1 GiB per night under its own budget.
  - `price_history.csv`, from `price_history.jsonl`.
  - `order_books_summary.csv`. Its rebuild source is the canonical books; the cost was never measured.
  - `mm_runs` scoring projections, from the sibling `quote_intents_long.csv`, bound by size and mtime in
    `mm_scoring_projection_manifest.json` (contract:87-95). Cost: not measured.
  - `backtest/` row exports, through `python -m weather.reporting.data_quality.backtest_artifact_retention`
    (data-retention-policy.md:150-152). Cost: not measured.
- **C, cache or scratch (`operator_cache`, contract:22):**
  - `backtest/replay_cache`: June-era keys, and nothing reads it (SVA:44). The owner's waiver is at contract:76-79.
  - Rotated console logs.
  - Rotated `clob_diagnostics.*` and `diagnostics.*` (owner decision 7, contract:63-66).
  - Under "never delete", C also goes cold rather than being deleted.

**May never leave local disk** (any tranche refuses them):
- Anything a live loop, serving, the 88a recorder, the maker shadow or the execution tape reads: open days, the last
  30 days, `wunderground/` and the historical source rows, `last_good_sources.json`, `forecast_payload_cas/` (shared,
  GC disabled, contract:124-130), `forecast_history/`, 88a, `execution_tape`, `wallet_ledger`, `settlements`,
  `maker_shadow`, and observation-trigger caches.
- What the Stage-A steps and label readers open: `snapshots.jsonl`, `snapshots_long.csv`, `source_status_long.csv`,
  `settlement.json`, `resolution_specs.json`, event-day manifests and markers (`settlement_ledger.py:1100-1137`,
  `settled_days.py:71-102`, `replay_status_backfill.py:84-85`).
- `replay_inputs.jsonl` (DL 09-26 #11) and the closed-day Parquet partitions.
- `data/cold_archive/` itself and status and lock files.
- The RE-1 campaign root, the exam roots `scratch\maker-replay-*`, pinned worktrees, `.git`, `venv`, `artifacts`, `config`,
  and every credential file.
- Every `observation_triggers` rotation.
- Every file dated in the hold or reservation windows (§5).

## 3. The cold-Drive route

**Existing route** (drive-offload:85-91; production-cold-archive-staging.md; cold-archive-locations.md:209-284):
- Copies go through an rclone crypt remote, with app-created-files scope only, one way (`copyto --immutable`, 8 MiB/s).
  There is no sync and no remote delete. Recovery keys are copied off Drive (DL 10-02).
- The host entrypoint is `scripts/ops/production_cold_archive_run.ps1 -Operation stage|transfer|upload|download|reclaim`.
- Encryption and restore run on the workstation: `workstation_cold_archive_stage`, `workstation_cold_archive_restore`,
  `bulk_cold_archive_crypt`.
- Location records are kept by `cold_archive_catalog` (`locate`, `inventory`, which refreshes `WHERE_DATA_IS.md`).
- **No archive task is registered.** The recurring-task decision is due ~11-05, after two manual runs and an uplink
  measurement (DL 10-02).

**Lane limits:**
- The stage CLI admits only `snapshots/<event>/<file>`, for events older than 30 days
  (`production_cold_archive_stage_cli.py:100-105`).
- Each chunk holds at most 1 GiB and 256 files, and jobs last at most 300 s.
- Staging refuses 04:45-06:45 (staging doc :69-77).
- Staging keeps 50 GiB plus the worst-case output as a reserve.
- Reclaim requires the reviewed archive-aware consumer files in `cold_archive_reclaim.py:27-39` to be adopted by all
  three capture workers.
- Nested paths, `mm_runs`, `backtest/` and folders with more than 10k files need the lane extension (drive-offload D7)
  first. That extension is not on master, so T6-T9 wait for it.

**Fit with 91a:**
- 91a (`WeatherColdSnapshotNightly`, 06:50, holds the lease to ~08:50, policy expires 10-30, renewal unchanged ~10-27) is
  local lossless compress-and-retain. It is not offboarding.
- It changes the yield. Once 91a has compressed a file, moving it frees only 28-61% of its logical size [E,
  drive-offload:74].
- Files that are already gzip are outside 91a's scope (cold-snapshot-compression.md:247-249), so moving them frees their
  full size. They therefore rank first.
- Moving a file also takes it out of 91a's future selection. CP-5 LZX (3.0-7.3x over LZNT1, EF §10s) would shrink the
  compressible families further and weaken the case for moving them.

**Per-tranche procedure** (one archive = one market-day and one family, `--chunk-grouping market_day_file_family_v1`):
1. **Select.** Run the bounded `storage_recovery_inventory` for exact files (storage-recovery-inventory.md), oldest
   first. Exclusions are in §2 and §5.
2. **Copy.** `stage` creates a tar.gz of the exact files and streams the SHA-256 of each pinned source into the
   production manifest (rereading and checking the archive). The workstation encrypts it, then the host runs `upload` and
   `download`. `upload` sends the ciphertext, the production manifest and the receipts to Drive as four objects.
   `download` re-hashes the ciphertext.
3. **Verify each file.** The workstation restore must be complete: `cryptcheck` plus a per-member SHA-256 against the
   production manifest. Drive's own hash covers ciphertext only, so only this step proves plaintext (drive-offload:180).
   The manifest is kept locally (the stage attempt and the catalog entry) and on Drive (the sidecar object). The handback
   publishes the verified metadata copies (cold-archive-locations.md:126).
4. **Owner list (§6),** then a signed exact-file approval.
5. **Local removal (A or C only, approved list only).** Run `reclaim` on the next admitted night, within 24 h of the
   restore and within 5 minutes of the source review. It re-pins and re-hashes every file before removal, then releases
   the three temporary spool copies (:258-284).
6. **Restore test.** Every archive gets a full restore before reclaim (step 3). For each tranche, also restore one
   randomly chosen archived market-day through the catalog publish into `restore_cache`, read it with a real
   archive-aware consumer, and record GiB per hour of restore. Repeat this monthly (drive-offload step 7).
7. **Receipts.** Keep:
   - the stage, crypt, upload, download, restore, custody, approval, source-review and reclaim receipts (intent,
     per-file, final, spool);
   - `Get-Volume` free bytes before and after each step;
   - the `WHERE_DATA_IS.md` refresh.

   One row per tranche goes into item 325, with counts and bytes only. Object IDs and tokens are never committed, because
   the repository is public.

## 4. Tranches, by GiB freed per unit of risk

**Methods.**
- *Eligible share s* = 0.80-0.95 of a family's 10-02 all-date size. It assumes ~113 market-days per market (1,357
  folders, drive-offload:60), of which the last 7 are excluded, and allows for later days being larger.
- *Residue r* = 0.28-0.61 if 91a has compressed the files and 1.0 for gzip or untouched files (drive-offload:74).
- The §1a survey replaces both.

| T | What | Class | Freed GiB | Risk and gate | Window |
| --- | --- | --- | --- | --- | --- |
| 1 | The 32 files already on Drive and still local (end-to-end drill) | A | ≤ 1.55 [M 09-13] | Lowest risk: the upload exists; needs a fresh restore. Measures uplink throughput | First non-landing night after the survey |
| 2 | `order_books_long.csv.gz` with a proved jsonl.gz twin; top-level `price_history.*` | B / A | 30-41 [E: 34.7·s, r = 1; plus 7.89·(0.28-1)] | Low: canonical twin stays local; nothing reads `price_history`; in-lane | Non-landing nights, 00:30-04:45 |
| 3 | `clob_tokens.jsonl` and `.csv`, closed days | A | 24-103 [E: 108.3·s·r] | Low-medium: needs a census of the open-day readers (DATA_LAYER_V2_PLAN.md:177) | same |
| 4 | `snapshot_explanations*`, `clob_capture_status`, `order_books_summary.csv` | A / B | ≈20-80 [E: 81.7·s·r + 4·s] | Medium: markouts, the residual corpus and the floor monitor read them; consumer list check | same |
| 5 | `variant_predictions` `.jsonl` + `_long.csv` | A | ≈17-61 [E: 58.5·s·r + 5·s] | Higher: D2 reader fixes (`discover_tapes`, parity evidence) first; a retrain-lane input | after D2 lands; not before the R0 decision |
| 6 | `backtest/replay_cache` | C | ≤ 32.3 [M 09-26 logical] | Low (no reader); blocked on the lane extension | after the extension |
| 7 | Retired `mm_runs`/`taker_runs`, excluding EF §8bb dates and remaining taker evidence (DL 09-26 #10) | A + B | ≈18-26 [E: 26.2 on disk minus exclusions] | Low; lane extension | after the extension |
| 8 | Nested `price_history_raw` (tar per event subtree) | A | ≈21 [M 09-26 logical] | Low (unread); lane extension and file count | after the extension |
| 9 | Rotated diagnostics (not `observation_triggers`), console logs, `backtest/` root exports (pinned baseline excluded, SVA:70) | C / B | ≈14-19 [E: SVA:45, :49-50] | Low; lane extension | after the extension |

**Deferred and not in scope:**
- Nested legacy `forecast_payloads` (36.11). It is the only issue-time archive, and FC-11 and NBM replay read it.
- `order_books.jsonl.gz` up to 07-30 (~7, unverified). Exam and panel join.
- `replay_inputs`.

**Total for T1-T9:** ≈180-385 GiB [E].

**Pace.** September ran 85 batches of 1 GiB in about 2 nights [M, drive-offload:111]. Plan for ≤ 6 GiB freed per night
[E, same] until two tranches complete cleanly.

## 5. Interactions

- **88a retention hold (UTC 09-27..10-30, STATE_OF_PLAY.md:62).** "Keep" plus "lossless compression ok" means the files
  stay local. Every tranche admits only files whose market-day and mtime are both ≤ 2026-09-25 local, which leaves a
  one-day UTC margin. The hold has no end date (G7), so dates after 09-25 become eligible only by an owner release.
- **Reserved confirmation window** (reserved-confirmation-window.md status line). MG-1 holds dates ≥ D0 2026-10-15, and
  the retrain window is armed. Offboarding is an outcome-blind operational step, which the exemption permits. It still
  never touches dates ≥ 10-15, so MG-1, EDGE-1 (D0 10-28) and the 12-21 reads find every input locally. The maker shadow
  embargo (UTC 09-30..11-13, STATE_OF_PLAY.md:38-39) keeps `maker_shadow` out entirely.
- **Stage-A (09:30-11:55).** No tranche job runs in it, and every host step ends by 04:45. Every Stage-A input stays local
  (§2). After each reclaim, check the first Stage-A run: step statuses, and no new `ArchivedInputRequired`. If that check
  fails, stop the campaign. Note that the event-manifest audit reports archived inputs as BLOCK by design
  (cold-archive-locations.md:176-186).
- **EF §10b sawtooth.** Judge free space at the trail's 24 h minimum (FINDINGS_DIGEST.md:129).
  - Every lane refuses at low free space. Staging needs 50 GiB plus its output, and each chunk briefly holds three spool
    copies until reclaim.
  - So start the campaign only while the 24 h low is Green (≥ 75 GiB, storage-plan:28-35). Stage no new chunk below
    60 GiB.
  - A tranche's gain shows at the next daily low, not at once.
  - Host steps also avoid 04:45-06:45 (tiering) and 06:50-09:00 (the 91a lease).
  - Landing nights are excluded. On the current calendar the earliest night is 10-28/29: C 10-23/24, N13 10-24/25,
    S2+S9 and S8 10-25..27, and the 88a restart 10-26/27 come first.
- **More-markets growth (1-3 GiB/day [C/E], model lane for M = 18-24).** Source:
  more-markets-phase2-scoping-2026-10-23.md:27-29 and :271-275, on branch `claude/docs-owner-1023-more-markets`.
  - At that rate, T1-T4 (≈75-225 GiB [E]) carry roughly 25-225 days of the added load.
  - The baseline burn without new cities was 4.5-8.6 GiB/day [M/E, *ibid.* :262]. The S8 write-path nights and the 91a
    steady state lower it.
  - East-Asian material hours fall inside 00:30-09:00. The lane's 16 MiB/s hash and 8 MiB/s network caps keep capture
    I/O light, but check capture reconnects in each tranche receipt.

## 6. Owner list template (shown before each tranche moves)

```text
OFFBOARDING TRANCHE <T#>-<n>   prepared <UTC time>   source tip <sha>   survey <file + sha256>
Family / class / policy row:   <family> / <A|B|C> / <storage_classes row; contract line>
Market-days (local):           <first> .. <last>   (all <= 2026-09-25; none held, embargoed or reserved)
Files: <count>   Logical: <bytes>   Allocated (to be freed): <bytes>   Archives: <count> (<= 1 GiB each)
Manifest: <local path> sha256 <..>   Drive copy: present (sidecar object; ID kept on host only)
Per-file SHA-256 verified on workstation restore: <restore receipt path + sha256>, <n>/<n> members match
Reader check: consumers of this family = <list>; archive-aware and adopted by all 3 workers: yes/no
Excluded by rule: <counts by reason: live-read, Stage-A input, hold, embargo, RCW, pinned/exam root>
Free space: 24 h low <GiB>; now <GiB>; expected after reclaim <GiB>
Restore drill: <market-day> restored in <minutes>; consumer read OK
Rollback: cold_archive_catalog locate + workstation restore + publish to restore_cache
Owner decision:  APPROVE exact list sha256 <..>  /  HOLD  /  REJECT        (signed, dated)
```

## 7. Gaps

- **G1.** No measured per-family size after 10-02, and no on-disk figure after 91a's October nights. §1a closes this.
- **G2.** Status of the drive-offload D1-D7 fixes on master is unverified. D7 (nested paths, `mm_runs`, more than 10k
  files) is visibly absent from the stage CLI.
- **G3.** `production-cold-archive-staging.md:15-19` and `verified-cold-archive.md:11-12` still say DISABLED, against
  DL 09-23 and 10-02.
- **G4.** Uplink throughput has not been measured. T1 measures it.
- **G5.** It is unverified which PC now holds the archive crypt configuration and the DPAPI secret, and where the custody
  record is.
- **G6.** No file-writing rebuild exists for `order_books_long`; only the proof does.
- **G7.** The 88a hold has no stated end.
- **G8.** The unexplained ~23 GiB burn of 10-02 (drive-offload:153).
- **G9.** The owner should confirm that "never delete" supersedes the replay_cache and twin delete approvals.
- **G10.** `WHERE_DATA_IS.md` has been stale since 09-13.
