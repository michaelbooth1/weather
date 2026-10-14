# O9 book-summary transfer: production transfer plan

Written 2026-10-14 on the 32 GB workstation; accepted by master-agent the same night. This copy carries master's
decisions (below) and describes the tools that sit next to it in `night-plans/o9/`: `o9_stage.py` (host),
`verify_o9.py` (workstation), and `SHA256SUMS` over those three files. **Nothing in this plan has been executed on the
capture host.** The tools were tested only on the workstation against a synthetic fake repo root (see §12). Master runs
the host steps; the workstation runs only §6, §8 and §9.

Authority: DECISION_LOG 2026-10-07 row: "O9 book-summary transfer yes, by 10-13". **The 10-13 deadline has passed**;
the slip is disclosed (A10). Purpose: dense order-book summaries for every tape date 08-15..09-29. These power the M1
and M5 markouts for R4 and R5 (W2-STQ-report §1 and §8 Q2; STQ-defender item 7).

## Master's decisions (2026-10-14)

| # | Decision |
| --- | --- |
| D1 | **Preflight = 552 stat calls and nothing else.** `o9_stage.py preflight` makes exactly one `os.stat` per allowlisted `order_books_summary.csv`: no open, no read, no directory listing, and it writes nothing. It runs **tonight after N9 if there is room in the lease plan, otherwise the next night.** (`--probe-gz` adds one stat of the `.csv.gz` twin per absent `.csv`; it is off by default and not part of D1.) |
| D2 | **The main run (stage + verify-staged) is on the 10-19 night.** |
| D3 | **Master relays the `MANIFEST.json` sha256 to the workstation out of band.** `verify_o9.py` refuses to run without it. |
| D4 | **The 09-29 local-evening cutoff goes to the owner queue. Strict UTC stays the default** (§2.4, A6). The tools implement strict UTC only; a change needs an owner decision and a reviewed tool change. |

---

## 0. Estimates (basis for the slot)

| Quantity | Estimate | Basis |
| --- | --- | --- |
| Market-days | **552** (46 dates x 12 markets). 96 of them overlap the 79a sample; 456 are new | 08-15..08-31 = 17 dates, 09-01..09-29 = 29 dates; the 12 79a/STQ markets |
| Source bytes read on the host | **~27.3 GB** (range 25.7-28.3 GB). If later dates are denser: up to ~55 GB (2x, upper bound) | Measured on the 79a sample `mi-books-sample.tgz`: 96 files, 4,754,771,146 B. Each file is 46.6-51.2 MB, mean 49.5 MB. Per-date totals are 584-602 MB, with no drift between 08-15 and 09-13. About 618 B/row (Atlanta 08-15: 80,675 lines, 49.8 MB) |
| Rows parsed on the host | ~45 M | 552 x ~81k |
| Staged and transferred bytes (gzip -6) | **~2.0 GB** (range 1.8-2.1 GB; upper bound ~4 GB) | Sample compression ratio 4,754,771,146 / 341,690,746 = **13.9x** |
| Host disk needed for staging | ~2.0 GB, upper bound 4 GB, outside `data\` | as above |
| Preflight (D1) | **< 1 min**, 552 stats, no lease content read | stat-only |
| Host lease hold, staging pass | **nominal ~25 min, planning figure 45 min, hard cap 90 min** (resumable, §5) | gzip -6 compression is the single-core bottleneck, assumed ~20-40 MB/s at BelowNormal under capture load; sha256 of 2 x 27 GB at ≥ 400 MB/s; csv parse of 45 M rows. **Not measured on the host**: the tool measures the first 5 files and projects (§5 step 4) |
| Host lease hold, staged self-verify | ~8-12 min | Decoding 27 GB, about as fast as the workstation STQ extract (4.75 GB tgz decoded and parsed in 106 s) |
| **Total host lease hold, main run** | **~35 min nominal, ~60 min planning, 2 h hard cap** | sum of the above |
| scp pull (workstation side, no host lease) | 1-5 min on a wired LAN (≤ 1 Gb/s); up to ~10 min on Wi-Fi | ~2 GB |
| Workstation verify (§9) | ~10-15 min | STQ extract throughput, scaled up 5.7x |
| Workstation disk | ~2 GB kept compressed (do NOT unpack: that would be 27 GB). Free at writing: 100 GB (90% used) | `df` on C: |
| Host memory | < 200 MB (streaming, one file at a time; a staged file is re-read whole in verify-staged, ~4 MB) | design |

**Slot constraints.** Master's slots are D1 and D2. In addition:
- The night of **10-16 00:30 is Phase B** and the night of **10-17 00:30 is the pyup C cutover**: neither is used.
- Every subcommand refuses outside **00:30-09:00** local (checked in code, and again before each file).
- Nothing in this plan runs in 12:00-18:00 or 18:00-00:30, and that includes the scp pull. The 09:30-11:55 Stage-A
  window is also avoided.
- The lease is exclusive. While it is held, quiet-window merges (01:00-04:00), the tiering reserve (04:45-06:45) and the
  cold-snapshot nightly (06:50-09:00, latest start 07:30) cannot take it. Master places the main run in a gap of at
  least 60 min in the 10-19 night's lease plan and sets `--stop-at` to the end of that gap.
- The tool stops between files at `--stop-at` and resumes in the next admitted slot (§5), so the work can be split.

---

## 1. Scope: exactly what moves

**Only** `order_books_summary.csv` (or its gzip-tiered twin `order_books_summary.csv.gz`) moves, from exactly 552
allowlisted event folders. Nothing else moves:
- no `order_books.jsonl` (raw books), `order_books_long.csv*`, `price_history*`, `market_ws*`, `execution_tape/` or
  `snapshots_long.csv`;
- no `settlement.json`, ledgers, `maker_evidence`, 88a or panel exports, or exam roots;
- no `.env*`, `*.cred`, `*.key`, `*.pem`, `config/local/*`, `.weathersync.cred`, or anything under the user profile.

### 1a. Market allowlist (12, the 79a/STQ set)
`atlanta, austin, chicago, dallas, denver, houston, los-angeles, miami, nyc, san-francisco, seattle, toronto`

### 1b. Date allowlist (46 target dates, explicit, no ranges computed at run time)
```
2026-08-15 2026-08-16 2026-08-17 2026-08-18 2026-08-19 2026-08-20 2026-08-21 2026-08-22 2026-08-23
2026-08-24 2026-08-25 2026-08-26 2026-08-27 2026-08-28 2026-08-29 2026-08-30 2026-08-31
2026-09-01 2026-09-02 2026-09-03 2026-09-04 2026-09-05 2026-09-06 2026-09-07 2026-09-08 2026-09-09
2026-09-10 2026-09-11 2026-09-12 2026-09-13 2026-09-14 2026-09-15 2026-09-16 2026-09-17 2026-09-18
2026-09-19 2026-09-20 2026-09-21 2026-09-22 2026-09-23 2026-09-24 2026-09-25 2026-09-26 2026-09-27
2026-09-28 2026-09-29
```
`o9_stage.py` embeds `MARKETS`, `DATES` and all 552 folder names (`ALLOWLIST_SLUGS`) as literals. `self_check()` runs
first in every subcommand and refuses (exit 2) unless: 12 unique markets; 46 dates, consecutive, first 2026-08-15, last
2026-09-29, all < 2026-09-30; the 552-name literal equals the MARKETS x DATES product exactly; every name parses back
with the anchored regex to an allowlisted date < 2026-09-30; and `CUTOFF_EPOCH_MS` equals the cutoff. The manifest
records `allowlist_sha256` = sha256 of the 552 names joined by LF with a final LF.

### 1c. Source paths on the host (derived from code; `<P>` = production repo root)
`MarketMicrostructureStore` writes `root / "order_books_summary.csv"`, where `root = data_path() / "snapshots" / event_slug`
(`src/weather/market/market_microstructure_capture.py:748,759,824`). The columns are `BOOK_SUMMARY_COLUMNS`
(`src/weather/market/market_microstructure_constants.py:73`). The slug date grammar is
`on-<monthname>-<d>-<yyyy>`, with the day not zero-padded (`clob_order_book_tiering.EVENT_DATE_RE`; seen in the 79a
member names, e.g. `...-on-september-6-2026`). For each allowlisted folder the tool **constructs** exactly these paths:

```
<P>\data\snapshots\highest-temperature-in-<market>-on-<monthname>-<d>-2026\order_books_summary.csv      (primary)
<P>\data\snapshots\highest-temperature-in-<market>-on-<monthname>-<d>-2026\order_books_summary.csv.gz   (gzip-tiered twin, only if the primary is absent; closed_day_projection_registry.py:185-191)
```
- **No directory listing of `data\snapshots`** (no `listdir`, `scandir`, `walk` or glob), and no other folder is
  stat'ed or opened, so a folder dated 2026-09-30 or later is never enumerated, stat'ed or opened. The only directory
  touched above the folders is one `isdir` stat of `<P>\data\snapshots`.
- A missing path is recorded as `missing`. The tool does not search for alternatives.
- The validated parquet in the closed-day archive (`data\archive\closed_market_days\v0.1\...`) and the encrypted cold
  archive are **out of scope**. A day present only there stays `missing`.

---

## 2. Hard refusals: dates 2026-09-30 and later

1. **By filename or folder date.** Every constructed name comes from the self-checked literal; `source_abspath()` and
   `stage_one()` re-parse the date and refuse a date ≥ 2026-09-30 as a second fence. The workstation verifier repeats
   the check on every received name and on every manifest entry (`o9_name_date_refused`).
2. **By content timestamps (row level), with the strict UTC cutoff `C = 2026-09-30T00:00:00Z`** (D4). Fields are parsed
   with `csv` (strict) after a latin-1 decode; ISO values must match
   `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$`. A row is **dropped as `ge_cutoff`** if any
   parseable value is at or after C:
   - `captured_at_utc` ≥ C;
   - `captured_at_local` converted to UTC ≥ C, **or** its literal local date ≥ 2026-09-30;
   - `book_time_utc` (if non-empty) ≥ C;
   - `book_timestamp` (if non-empty) ≥ **1790726400000** epoch ms (= C).

   Otherwise a row is **dropped as `unparseable`** (fail closed, counted separately) if the field count differs from
   the header, `captured_at_utc` or `captured_at_local` is empty or does not parse, or a non-empty `book_time_utc` /
   `book_timestamp` does not parse. A row whose `event_slug` differs from the folder name refuses the **whole file**
   (`refused:event_slug_mismatch`). Every other row is kept.
3. **Discarded rows are counts only.** Rows at or after C are parsed only far enough to discard them. `classify_row()`
   returns no values for them; the tool records only `rows_dropped_ge_cutoff`, never their values, min/max or content.
   This follows the OD17/Q14 owner ruling (WORKSTATION_STATE 2026-10-07): "parse-and-discard >=09-30 is not a read
   (counts only, disclosed)".
4. **Known consequence, now in the owner queue (D4).** For the 09-29 events, the last local hours of 09-29 fall on UTC
   09-30 and are dropped:
   - Toronto and NYC after 20:00 local;
   - Chicago, Dallas, Houston and Austin after 19:00;
   - Denver after 18:00;
   - LA, SF and Seattle after 17:00.

   This is the same issue the STQ Defender raised as a MUST-FIX for 111h (439 rows with UTC 09-30 timestamps). Any
   post-close rows in earlier folders that fall on or after C are also dropped. Strict UTC stays the default until the
   owner decides otherwise.
5. **A file that changes or ends early is `unstable`.** The tool re-stats each source against `SOURCE-MANIFEST.json`
   before opening it, reads **exactly** the stat size (a short read is unstable), then checks that one further read
   returns nothing and that `fstat` size and mtime are unchanged. A last line without a trailing newline is also
   unstable. An unstable file keeps no output and is retried on the next run, never in the same run. A source whose
   size or mtime differs from `SOURCE-MANIFEST.json` stays unstable on every resume; to take its new state, master
   starts a fresh `--out` directory.
6. **Corrupt gzip twin.** `refused:gzip_corrupt`; not retried.

---

## 3. Host read rules (master's requirements)

- **Shared-mode reads only.** Each source is opened through `CreateFileW(GENERIC_READ,
  FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN)` via `ctypes`, then
  `msvcrt.open_osfhandle(..., os.O_RDONLY | os.O_BINARY)` (`open_shared_read()`). CPython's default `open()` omits
  `FILE_SHARE_DELETE`, so it could block a concurrent replace or rename by capture or tiering; it is never used for
  sources. `os.stat` is the only other call that names a source path.
- **No exclusive lock, ever.** There is no `LockFileEx`, no `acquire_writer_lock` and no `raw_tape_guard`. The tool
  does not import `weather.*`: it is stdlib only and runs with `python -I -B`, so it cannot pick up repo locks,
  `sitecustomize` or the STALE_CODE fingerprint.
- **Never move, rename, truncate, recompress or delete a source file.** No write, rename or unlink call in the tool
  takes a source path. Writes and the only deletes (`*.partial`, a stale staged copy of a failed retry) are inside
  `--out`, and the tool refuses an `--out` that overlaps `--repo-root` (`out_dir_overlaps_repo_root`).
- **Byte-preserving filter.** Kept rows are written as their **original line bytes**. When no row is dropped, the
  decoded output is byte-identical to the source (or to the decoded `.csv.gz` twin), and the state says so
  (`byte_identical_to_source`).
- **Staging outside `data\`, outside the production tree:** `C:\tmp\o9-handoff\` (precedent: 79a staged at
  `C:\tmp\mi-handoff\`). The tools are copied to `C:\tmp\o9-tools\` from the reviewed commit, and master checks them
  against `night-plans/o9/SHA256SUMS` before the run.
- **Process.** The tool sets its own priority class to BelowNormal for `stage` and `verify-staged`. It takes no lease
  itself: master holds the shared lease in the parent PowerShell (§5).

---

## 4. Staged layout and manifests

```
C:\tmp\o9-handoff\
  SOURCE-MANIFEST.json   # stat-only list of all 552 sources; written by the first `stage` run BEFORE any copy
  RUN-RECEIPTS.jsonl     # one line per stage run: outcome, exit code, files, bytes, seconds, memory, free disk
  state\<slug>.json      # per-file state record (status, counts, hashes); written after each file
  books\<slug>\order_books_summary.csv.gz
  SHA256SUMS             # written by verify-staged: "<sha256>  books/<slug>/order_books_summary.csv.gz", LF, sorted
  MANIFEST.json          # written by verify-staged LAST, after every staged file has been re-checked
```
Only `MANIFEST.json`, `SHA256SUMS` and `books\` are pulled to the workstation.

Gzip settings: level 6, `mtime=0`, empty filename. Stored gzip bytes are not portable across zlib builds (owner
decision 8 in maker replay v2), so identity is the **decoded** sha256. The stored sha256 only checks transport.

**`SOURCE-MANIFEST.json`** (schema `o9_book_summary_source_manifest.v1`): host, repo root, script sha256, allowlist
sha256, dates, markets, cutoff, totals, and for each of the 552 folders its status (`present` | `missing` |
`refused:not_regular_file` | `error:stat_<errno>`), variant, relpath, bytes and mtime. A resumed run refuses unless the
allowlist sha, repo root, script sha and slug order all match (`source_manifest_mismatch_start_a_fresh_out_dir`). A
first run refuses a non-empty `--out` that has no source manifest.

**`MANIFEST.json`** (schema `o9_book_summary_transfer.v1`):
- **Header fields:** `created_utc`, `plan` and `plan_sha256` (passed by master), `host_id` (passed by master, e.g.
  `Get-WeatherExecutionHostId`, else `COMPUTERNAME`), `production_git_head` (passed by master, informational),
  `script_sha256`, `source_manifest_sha256`, `allowlist_sha256`, `dates`, `markets`, `cutoff_utc`, `cutoff_epoch_ms`,
  `"no_folder_dated_on_or_after_2026_09_30_constructed_or_opened": true`, `counts` (`expected 552 / staged / missing /
  unstable / refused / error`), `totals` (source bytes staged, staged bytes, decoded bytes, rows kept,
  `rows_dropped_ge_cutoff`, `rows_dropped_unparseable`), and `sha256sums_sha256`.
- **`files`:** all 552 entries in allowlist order. A staged entry carries `market`, `target_date`, `slug`,
  `source_variant` (`csv` | `csv.gz`), `source_relpath`, `source_bytes`, `source_mtime_ns`, `source_mtime_utc`,
  `source_sha256` (raw bytes as read; for `csv.gz` also `source_decoded_sha256`), `header_sha256`, `rows_total`,
  `rows_kept`, `rows_dropped_ge_cutoff`, `rows_dropped_unparseable`, `kept_captured_at_utc_min`,
  `kept_captured_at_utc_max`, `kept_book_time_utc_max`, `staged_relpath`, `staged_bytes`, `staged_sha256`,
  `decoded_bytes`, `decoded_sha256`, `byte_identical_to_source`, `seconds`, `status`. Other entries carry their status
  (`missing` | `unstable` + `detail` | `refused:<code>` | `error:<code>`).

**Anchor outside the workstation (D3).** `verify-staged` prints `manifest_sha256`. Master relays it to the workstation
out of band in the handback message; `verify_o9.py` requires it as an argument and never reads it from the inbox.

---

## 5. Host procedure (master executes; inside 00:30-09:00 only)

Exit codes for every subcommand: 0 done, 2 refused, 3 error, 4 disk-floor abort, 75 partial.

0. **Before the night (read-only, light):**
   - copy `o9_stage.py` from the reviewed commit to `C:\tmp\o9-tools\` and check its sha256 against
     `night-plans/o9/SHA256SUMS` (`night-plans/o9/.gitattributes` sets `-text`, so a checkout keeps the committed LF
     bytes even with `core.autocrlf=true`);
   - re-read the status line of `reserved-confirmation-window.md`. It does not affect pre-09-30 order-book summaries,
     but re-check it;
   - live free disk on the volume's free bytes (`(Get-PSDrive C).Free` or `fsutil volume diskfree C:`, not a
     directory walk).
1. **Preflight (D1: tonight after N9 if there is room, else the next night).** Stat only; it writes nothing.
   ```
   python -I -B C:\tmp\o9-tools\o9_stage.py preflight --repo-root <P>
   ```
   It prints one JSON line per folder (`slug`, `target_date`, `market`, `status`, `variant`, `bytes`, `mtime_utc`) and
   a totals line (`present`, `missing`, `source_bytes_total`, `projected_gzip_bytes`, `stat_calls` = 552). Master
   records the totals. **Stop and ask the owner if more than ~10% are missing** (A2). If many are missing, an optional
   second preflight with `--probe-gz` shows how many are gzip-tiered twins (adds ≤ 552 stats; outside D1, master's
   call).
2. **Main run (D2: the 10-19 night). Lease**, in one PowerShell process:
   ```powershell
   . <P>\scripts\ops\workload_admission.ps1
   $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot <P> -Workload o9_book_summary_stage
   try { <steps 3-4> } finally { Exit-WeatherHeavyWorkloadLease $lease }
   ```
   Do not pass `-AllowStageAWindow` or `-OwnerApprovedException`. A busy or refused lease means skip the night
   without retrying in a loop. Check `scripts\ops\status.ps1` shows the three capture workers healthy before and after.
3. **Stage:**
   ```
   python -I -B C:\tmp\o9-tools\o9_stage.py stage --repo-root <P> --out C:\tmp\o9-handoff --stop-at <end of gap, default 08:30>
   ```
   Gates checked in code (refuse, exit 2, or abort, exit 4):
   - local time in 00:30-09:00, at start and before each file; `--stop-at` must be 00:31-09:00;
   - available RAM ≥ 4 GiB and commit < 70%, at start and before each file;
   - free disk at start ≥ 20 GiB capture reserve + 1 GiB + 2 x (remaining source bytes / 13.9); during each file,
     rechecked every 64 MiB read: below 21 GiB free aborts with exit 4 and deletes only that file's `.partial`.

   Behaviour:
   - The first run writes `SOURCE-MANIFEST.json` (stats only) **before opening any source**.
   - Files are processed one at a time in allowlist order (date, then market). Before each file it projects that
     file's time (1.5 x bytes / rate; the rate is a 10 MB/s prior until 5 files are measured) and stops with exit 75
     (`PARTIAL_STOP_AT`) if it would pass `--stop-at`, or (`PARTIAL_MAX_RUNTIME`) the 120 min `--max-runtime-minutes`
     cap. After 5 files it prints a projection of the remaining time.
   - **Resume:** rerun the same command. A file whose state is `staged` and whose staged copy still matches its
     recorded size and sha256 is skipped; `refused:*` files are skipped; `unstable`, `error:*` and unprocessed files
     are attempted.
   - `--max-files N` limits a run to N files (used for a cautious first slice if master wants one).
   - Master retains the PID and polls it to exit. It is never abandoned; `Stop-Process` on overrun of the 2 h cap. A
     killed run leaves at most one `.partial`, which the next run overwrites and `verify-staged` refuses.
4. **Self-verify on the host** (same lease, after stage exits 0):
   ```
   python -I -B C:\tmp\o9-tools\o9_stage.py verify-staged --out C:\tmp\o9-handoff --host-id <id> --production-git-head <sha> --plan-sha256 <sha of this file>
   ```
   It requires a state for every present source (exit 75 if any are pending), requires `books\` to hold exactly the
   staged files (no `.partial`, nothing extra), re-hashes each stored file, decodes it, re-applies §2 to every row
   (all must be kept), and re-derives the decoded sha256, bytes, header sha256, row count and min/max. Only then does it
   write `SHA256SUMS` and `MANIFEST.json` (the manifest last) and print `manifest_sha256`.
5. **Release the lease** (the `finally` above). Check that `status.ps1` shows the capture workers healthy.
6. Master relays to the workstation, out of band (D3): the `MANIFEST.json` sha256, the staged/missing/unstable/refused
   counts, and the total staged bytes.

## 6. Transport (workstation pulls; precedent 79a and 111h: "transfer by scp from production, never through git")

The workstation pulls after master's relay, inside 00:30-09:00 (no host lease needed; it only reads the staging dir).
It uses the existing `production-pc` SSH alias in the workstation's `~/.ssh/config`; the key files are not opened:
```powershell
$D = 'C:\Users\Michael\Documents\github\weather\data\research_inbox\o9-book-summaries'
New-Item -ItemType Directory -Force $D | Out-Null
scp -o BatchMode=yes -o ConnectTimeout=10 production-pc:C:/tmp/o9-handoff/MANIFEST.json "$D/MANIFEST.json"
# check MANIFEST.json sha256 == the value master relayed BEFORE pulling the rest
scp -o BatchMode=yes -o ConnectTimeout=10 production-pc:C:/tmp/o9-handoff/SHA256SUMS "$D/SHA256SUMS"
scp -r -o BatchMode=yes -o ConnectTimeout=10 production-pc:C:/tmp/o9-handoff/books "$D/"
```
- **Destination:** `data\research_inbox\o9-book-summaries\` in the main checkout. `data\` is git-ignored, and the
  path follows the T12 inbox precedent. It is not the mirror and not `D:\weather-mirror`.
- `SOURCE-MANIFEST.json`, `RUN-RECEIPTS.jsonl` and `state\` stay on the host (the verifier refuses unlisted files).
- Files stay gzip-compressed. Analysis streams them.
- **Fallback, if `scp -r` misbehaves on Windows paths:** pull the files one at a time from the `SHA256SUMS` list. Do
  not tar on the host: that would need another ~2 GB of host disk.

## 7. Rollback

- **Workstation.** If verification fails, delete only `data\research_inbox\o9-book-summaries\`; it holds only what this
  transfer received. Then report the refusal code to master. No other workstation state is touched.
- **Host.** Sources are never modified, so there is nothing to roll back there. The staging dir `C:\tmp\o9-handoff\`
  is deleted by master **only after** the workstation reports PASS, or on abort. That removes only files this
  transfer created; master confirms the path before deleting. An aborted partial stage can be resumed (§5.3) or
  deleted.
- **Bad lease teardown.** If the lease teardown fails, the documented poison and recovery path applies
  (`Clear-WeatherHeavyWorkloadPoison` only per HOST_LOAD_POLICY). Nothing in this plan bypasses it.

## 8. Workstation verification commands (after the pull)

```powershell
$D = 'C:\Users\Michael\Documents\github\weather\data\research_inbox\o9-book-summaries'
(Get-FileHash -Algorithm SHA256 "$D\MANIFEST.json").Hash.ToLower()   # must equal master's relayed value
C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe -I -B <checkout of the reviewed commit>\night-plans\o9\verify_o9.py `
    --inbox $D --expected-manifest-sha256 <hex relayed by master> `
    --sample-tgz C:\Users\Michael\Documents\github\weather\scratch\missing-information-20260921\downloads\mi-books-sample.tgz `
    > C:\wt\workstation-chat\l-data\swarm-m\O9-verify-receipt.json
```
The verifier is light (one stream at a time, < 200 MB RAM) and not pytest. Under the workstation rules it may still be
wrapped in `workstation_heavy.ps1 -Kind weather_heavy` if the queue is busy.

## 9. Verifier: `verify_o9.py` (read-only, stdlib only)

- **Inputs:** `--inbox`, `--expected-manifest-sha256` (**required**: argparse exits 2 without it), optional
  `--sample-tgz`.
- **Writes nothing.** It prints one JSON receipt to stdout, including its own sha256 (`verifier_sha256`).
- **Exit codes:** 0 PASS, 2 REFUSED (a `refusal` code is printed), 3 ERROR. Checks stop at the first refusal.

1. **Anchor.** The expected value must be 64 lower-case hex (`o9_expected_sha_not_64_lower_hex`). Read the raw bytes
   of `MANIFEST.json` and hash them; refuse `o9_manifest_sha_mismatch` unless equal, then parse those same bytes (no
   second read).
2. **Scope.** Schema `o9_book_summary_transfer.v1` (`o9_manifest_schema`); the manifest's dates and markets must equal
   the verifier's own literals (`o9_manifest_scope_mismatch`); cutoff `2026-09-30T00:00:00Z` and `1790726400000`
   (`o9_manifest_cutoff_mismatch`); `allowlist_sha256` (`o9_manifest_allowlist_mismatch`); the 552 `files` entries in
   allowlist order (`o9_manifest_file_list_mismatch`); every entry's date < 2026-09-30 (`o9_name_date_refused`); every
   staged entry's path and hash fields well formed.
3. **File set.** Walk the inbox. Every name of the form `books/<slug>/order_books_summary.csv.gz` must parse to an
   allowlisted date < 2026-09-30 (`o9_name_date_refused`, checked before anything else about the set). The set must
   equal {`MANIFEST.json`, `SHA256SUMS`} plus every staged entry, exactly: `o9_unlisted_file` (this catches a stray
   `.env`, ledger or raw tape) or `o9_missing_file`.
4. **Transport integrity.** `SHA256SUMS` hashes to the manifest's `sha256sums_sha256`, every line is well formed and
   unique, and it lists exactly the staged entries with their `staged_sha256`.
5. **Identity.** Each stored file's size and sha256 equal the manifest (`o9_staged_hash_mismatch`). Stream-decode it:
   header sha256, decoded sha256 and bytes, and row count must equal the manifest.
6. **Content bounds (counts only).** Re-apply §2.2 (the same `parse_iso` and `classify_row` source as the host tool) to
   every row; `event_slug` must equal the folder. Any row at or after C refuses `o9_content_after_cutoff` with **only
   the count**; unparseable rows refuse `o9_unparseable_rows`. The kept min/max timestamps must equal the manifest's,
   and the manifest's row and decoded-byte totals must equal the sum.
7. **Cross-check against 79a (informational).** For tgz members named `.../<allowlisted, staged slug>/order_books_summary.csv`,
   stream and hash the member and compare it with the manifest's source identity (`source_decoded_sha256` for a `.gz`
   twin, else `source_sha256`). Members of out-of-scope folders are skipped without hashing. The receipt reports
   `sample_members_matched`, `sample_members_mismatched` and their slugs; a mismatch means the host file changed after
   09-21, is reported to master, and does not change the exit code.
8. **Receipt.** Verdict, manifest counts, files staged, rows kept, decoded bytes, and the host's dropped-at-cutoff and
   unparseable counts copied from the manifest (not re-derived), plus the 79a results.

No outcome, settlement or markout is computed by the verifier. Analysis (M1/M5) is a separate step after PASS.

---

## 10. Open assumptions master confirms on the host

- **A1. Path layout.** Summaries live at `<P>\data\snapshots\<slug>\order_books_summary.csv` with the slug grammar
  above. This is from code, and it matches the 79a member names. The D1 preflight confirms it.
- **A2. Presence after storage recovery.** `order_books_summary.csv` is classed as a *rebuildable* CLOB projection
  (`storage_classes.py:502-519`). Some 08-xx files may therefore have been gzip-tiered, NTFS-compressed (fine:
  transparent) or removed after a verified cold archive. Stage takes `.csv`, then `.csv.gz`. A file present only in
  the parquet archive, cold archive, or as raw `order_books.jsonl` stays **missing**. Rebuilding from raw books would be
  a heavier, separate action that needs its own decision.
- **A3. Market set.** The transfer is limited to the 12 79a/STQ markets. Other markets would be a scope change.
- **A4. Sizes.** Dates 09-14..09-29 have densities similar to the sample. If the 15 s near-close fast capture began
  after 09-13, bytes can roughly double; see the upper bounds in §0. The preflight gives exact source bytes.
- **A5. Host throughput.** The §0 runtime assumes gzip -6 at ~20-40 MB/s single core under BelowNormal. This is not
  measured on the host; the 5-file projection and `--stop-at` resume cover it.
- **A6. Strict UTC cutoff (D4: in the owner queue).** It loses the 09-29 local evening (§2.4). A local-date rule would
  contradict master's requirement 1 and needs an explicit owner decision plus a reviewed tool change. Default: strict
  UTC.
- **A7. Staging location.** `C:\tmp\o9-handoff\` exists or can be created on the host volume, outside `<P>`, and the
  disk floor holds (20 GiB reserve + ~4 GB).
- **A8. Transport.** The workstation's `production-pc` scp pull is still authorised for this use (79a and 111h
  precedent), and the host's OpenSSH server is still running.
- **A9. Scope of "O9".** The 10-07 DECISION_LOG row says "O9 book-summary transfer". The maker replay v2 `transfer.py`
  docstring also calls the bundle transfer O9 ("on HOLD"). **This plan covers book summaries only.** The maker replay
  v2 calibration-bundle transfer is not covered; master confirms it needs no separate plan under this approval.
- **A10. Deadline.** The approval said "by 10-13". The main run is on the 10-19 night (D2); master tells the owner
  about the slip.
- **A11. Python on the host.** The tools need CPython ≥ 3.9 on Windows (`ctypes`, `msvcrt`, `gzip`, `csv`); they were
  tested with 3.11.9. They import nothing from the repository.

## 11. Boundaries kept

- No host command was run, nothing was transferred, and `data\snapshots` (real) was not touched on either machine.
- Not read or opened: any 88a, panel or settlement data for 2026-09-30..10-15; any `.env*`, `*.cred`, `*.key`,
  `*.pem` or `config/local/*` file; `C:\wt\lfc-pinned-*`; port 8765.
- The commit carries these four files plus `night-plans/o9/.gitattributes` only; the synthetic test fixtures stayed in the workstation scratch directory.

## 12. Workstation test record (synthetic fixtures only)

Run 2026-10-14 ~01:26 EDT on the 32 GB workstation, Python 3.11.9 with `-I -B`, plain serial script, no pytest. The
fake repo root held: an in-range `.csv` (atlanta 08-15), a missing folder (austin 08-15), a `.gz`-only folder
(chicago 08-15), a file grown after the source manifest (houston 08-15), a file without a final newline (dallas 08-16),
a file with a foreign `event_slug` (denver 08-16), an in-range file with rows at/after C plus unparseable rows (nyc
09-29), folders dated 09-30 and 10-01 (one held under an exclusive no-share lock throughout), and a non-allowlisted
folder. Because the workstation had 3.4 GiB available RAM, the stage runs used a child that lowered only the 4 GiB RAM
floor; one run against the real floor confirmed the gate refuses. Results: **46/46 checks passed**, including:
- preflight: exactly 552 stats, all on `.csv` paths; with `--probe-gz` 552 + 547; no open, `listdir` or `scandir`
  under `snapshots` (audit hook), no stat of any 09-30/10-01/off-allowlist path, nothing written;
- `--out` inside the repo root refused; `--stop-at` already passed gave exit 75 with `SOURCE-MANIFEST.json` written and
  nothing copied; `--max-files 1` gave exit 75 with one file staged; resume gave exit 0 without reprocessing; a second
  resume retried only the two unstable files; one receipt line per run;
- nyc 09-29: 8 rows, 3 kept, 3 dropped `ge_cutoff` (by `captured_at_utc`, by UTC-converted local, by `book_timestamp`),
  2 dropped unparseable; staged content holds no 09-30 value; gz-only file staged with decoded identity; grown file and
  missing-newline file `unstable`; foreign slug `refused:event_slug_mismatch`; sources not moved or deleted;
- the 09-30 file could still be locked exclusively afterwards (never held open by the tool);
- verify-staged PASS, printed sha equals sha256(`MANIFEST.json`), counts staged 3 / missing 546 / unstable 2 /
  refused 1; a tampered staged file refused;
- verify_o9: right sha PASS (rows 7, 79a-style tgz member matched, 09-30 member skipped); **wrong sha refused
  `o9_manifest_sha_mismatch`**; missing `--expected-manifest-sha256` refused by argparse; malformed sha refused; extra
  file `o9_unlisted_file`; a 09-30-named file `o9_name_date_refused`; tampered content `o9_staged_hash_mismatch`;
  missing staged file `o9_missing_file`.
