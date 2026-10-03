# Google Drive offload study — 2026-10-02

- **Owns:** the 7-agent study of which data stays local, what can move to the 2 TB Drive through the existing rclone crypt lane, and how to restore for retrains.
- **Read when:** disk planning after the 91a backlog (~10-20..24), offload, or restore-on-demand work.
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)) or decisions in force ([DECISION_LOG](../../operations/DECISION_LOG.md)).

Read-only agents; no exam-blackout data read; numbers are MEASURED only where marked. Owner decisions are in DECISION_LOG.

## Synthesis

**Verdict:** Yes, a lot can move to the 2 TB Drive and come back for retrains. Moving it now is optional; we need it after 91a's backlog runs out (about 10-20 to 10-24). Use the encrypted rclone lane the repo already has. It moved 79.1 GB off the disk in September. What actually limits us is reader code and gaps in the lane, not Drive space. Retrains need little raw data (under 25 GiB, ESTIMATED), and that stays local. The large families are evidence for replay, parity and audits, and they can be restored on demand on the workstation.

**Checked this session (MEASURED):**
- C: has 111,502,512,128 B free (103.8 GiB).
- `data\backtest\replay_cache` still exists.
- `docs/operations/production-cold-archive-staging.md:15-19` still says "Status: DISABLED … Do not run any operation below without a new owner decision".
- No archive task is registered. `WeatherDataMirror`, `WeatherMirrorRestoreVerify` and `WeatherOneShotMirror` are Disabled. `WeatherColdSnapshotNightly`, `WeatherClobTiering` and `WeatherClobRawTapeTiering` are Ready.

## A. Tier table

D = on-disk GiB. Values marked (A) were measured on 09-26 and are UNVERIFIED now. All others come from the 10-02 inventory (MEASURED).

| Family | D GiB | Growth | Tier | Who reads it | Restore need |
|---|---|---|---|---|---|
| WU history and historical source rows | 18.4 (A) | small | **HOT** | Serving and base retrain (`model_climatology.py:100-151`). A missing month is skipped silently, so the forecast changes with no error | Never offload |
| 88a maker_evidence, execution_tape, settlements, wallet_ledger, labels | 3.7 (A) | ~85 MB/day | **HOT** | Exam, informed maker, accounting | Never offload (canon). Drive copy only as a second copy |
| snapshots_long / features_long CSV, snapshots.jsonl, event-day manifests, markers | ~5.4 (M, compressed) | ~0.5 GiB/day logical | **HOT** | Label finalize, replay, centering | Readers treat a missing file as "the day never happened" |
| replay_inputs.jsonl | 82.5 uncompressed + 1.8 compressed | ~0.9 GiB/day | **HOT** (owner decision 11) | Replay, parity, residual corpus | Needs an owner reversal and code changes before it can move |
| closed_market_days Parquet, cold_archive catalog, .git, venv | ~5 (A) | small | **HOT** | PIT lane (hash-checked), map of what is on Drive | — |
| forecast_payload_cas | 13.1 (A) | growing | HOT/WARM | NBM replay | Keep. Garbage collection is disabled |
| Last 14 days of everything | — | — | **HOT** | Live join key, markouts | — |
| order_books.jsonl.gz from 07-31 on | part of 23.9 | 21 MiB per city-day | HOT/WARM | Exam, execution-tape join | Keep until after the exam |
| variant_predictions .jsonl + _long.csv | 58.5 uncompressed + 5.0 compressed | 79 MiB per city-day | WARM, then COLD after 30 d | Parity, studies | Per study, on the workstation (`_long.csv` is in the hot set until reader fixes) |
| order_books_summary.csv | 44.7 uncompressed + 4.0 compressed | 48 MiB per city-day | WARM for 14 d, then COLD | Markouts, MM inputs | Rarely |
| clob_tokens.jsonl and .csv | 67.3 + 41.0 uncompressed | ~1.5 GiB/day together | **COLD** for closed days | Audits only. The key is also in the book tape | Rarely |
| snapshot_explanations, clob_capture_status | ~37 uncompressed | ~40 MiB per city-day | COLD | Audits | Rarely |
| Legacy nested forecast_payloads | 36.1 (A) | 0 | WARM/COLD | NBM layer 2/3 replay | For that study only |
| mm_runs (retired) | 26.2 (A) | 0 | COLD | EF §8bb, 07-31..08-08 only | Rarely |
| price_history_raw + price_history.* | 21.3 + 7.9 (A) | 0 | COLD | Nothing | Almost never |
| order_books.jsonl.gz up to 07-30 | ~7 (UNVERIFIED) | 0 | COLD | Panels | Rarely |
| order_books_long.csv.gz | 34.7 | 19 MiB per city-day | **DELETABLE** where a jsonl.gz twin proves parity (decision 6) | Nothing | None |
| backtest/replay_cache | 32.3 (A) | 0 | **DELETABLE** (waiver 09-26) | Nothing | None |
| Logs and diagnostics; worktrees, staging, failed tarballs | ~9; ~3–5 (A) | small | DELETABLE / COLD | Nothing | None |

Already on Drive (`WHERE_DATA_IS.md`, 09-13, MEASURED): 1,989 files, 90.84 GiB. Another 32 files (1.55 GiB) are on Drive and still local.

## B. How much can move, and the free-space projection

**Now, without code changes (exam-safe, outside UTC 09-27..10-14):**

| What | Action | GiB |
|---|---|---:|
| replay_cache | Delete with an owner-signed exact manifest | 32.3 |
| order_books_long.csv.gz | Delete where the twin proves parity | ~29 (UNVERIFIED) |
| Logs, diagnostics, failed stages, worktrees | Delete or archive | ~12 |
| price_history top-level | Drive (the only family the lane accepts today) | 7.9 |
| LOCAL_WITH_CLOUD_COPY files | Reclaim after a fresh restore check | 1.55 |
| **Total** | | **~80 GiB** |

Only about 9.5 GiB of that total actually goes to Drive; the rest is deletion. More families (`clob_tokens.jsonl`, `market_ws`, `order_books*`, `variant_predictions.jsonl`) are safe for their readers once archived (`order_book_tape.py:135` and `execution_tape_markout.py:370` handle the archive error). They are still blocked by the lane: only 48 of 1,357 folders have event-day manifests, and the lane cannot take nested paths or folders with more than 10k files. These limits are documented and still UNVERIFIED as current.

**After the exam and the lane fixes:**

| Family | GiB |
|---|---:|
| clob_tokens, closed days older than 30 d | ~50–75 |
| variant_predictions and explanations | ~40–59 (needs reader fixes) |
| Legacy forecast_payloads | 36 |
| mm_runs | 26 |
| price_history_raw | 21 |
| order_books.jsonl.gz up to 07-30 | 7 |
| **Total** | **~180–225 GiB** (ESTIMATED) |

Once 91a has compressed a family, moving it to Drive recovers only the remaining 28–61% of its logical size.

**Projection (ESTIMATED, central case):**
- From 104 GiB now, the 91a backlog brings free space to about 264 GiB by 10-22.
- The ~80 GiB of deletions above (not in 91a's scope) raise that to about 340 GiB.
- After the backlog, net burn is about 4.5 GiB/day, plus about 1.2 GiB/day of expansion from mid-November. Free space reaches 100 GiB around early-to-mid January.
- The post-exam Drive wave (~200 GiB) adds about 35 days.
- After that, holding flat needs about 175 GiB/month to Drive. That is about 110 GiB/month in the optimistic case and about 310 in the pessimistic case. 1.86 TB of headroom lasts about 6–17 months.

## C. Tool and procedure

**Tool:** the existing rclone crypt lane, `scripts/ops/production_cold_archive_run.ps1`, with operations stage, upload, download and reclaim. Do not use Google Drive for desktop:
- It syncs both ways, so a local delete can spread to Drive.
- Its cache would sit on C:.
- It uploads unencrypted.
- It gives no receipts.

The rclone lane only accesses files it created (`drive.file`) and copies one way: `copyto --immutable --bwlimit 8M --max-transfer --cutoff-mode HARD`. It has no sync and no remote delete.

**Procedure, fitted to the host rules:**
1. Fix the two stale "DISABLED" headers so they match the 09-23 and 09-26 decisions. These are roll-free docs edits:
   - `production-cold-archive-staging.md:15-19`
   - `verified-cold-archive.md:11-12`
2. Select closed days older than 30 days, oldest first, by family. Group with `--chunk-grouping market_day_file_family_v1`: one day and one family per archive, so restores can be partial. Exclude:
   - the last 14 days
   - UTC 09-27..10-30 (exam, plus the 88a hold)
   - the RE-1 root
   - replay_inputs
3. Production, 00:30–09:00, holding the `workload_admission.ps1` lease, serial with 91a (91a runs about 04:30–05:45):
   - `stage` (needs free space above the 50 GiB reserve)
   - `upload`, which encrypts locally first and writes SHA-256 manifests plus four object IDs
   - `download` and re-hash
4. Workstation, daytime and unrestricted: full restore with `workstation_cold_archive_restore`, `cryptcheck`, and a per-member SHA-256 check against the manifest.
5. Owner signs an exact-file reclaim manifest: paths, checksums and reason.
6. Next admitted night, within 24 h of the restore and within 5 minutes of the source review: `reclaim` with the exact files only. Record `Get-Volume` free bytes before and after each batch. Then run `cold_archive_catalog inventory` to refresh `WHERE_DATA_IS.md`, which is stale since 09-13.
7. Monthly drill: restore one random archived day on the workstation and run one replay from it.

**Pace:** in September the lane did 85 batches of 1 GiB in about 2 nights (MEASURED). 175 GiB/month means roughly 6 GiB per night. Making it a recurring scheduled task would need its own owner decision.

## D. Changes so retrains and replays can restore on demand

| # | Change | Why | Effort (ESTIMATED) |
|---|---|---|---|
| 1 | `market_day_labels_finalize` merges into the existing file instead of rewriting it (`settlement_ledger.py:1128,1316-1324,1479`) | Today a missing CSV silently **deletes that day's labels row**. This is the most dangerous gap | M, 1–2 d |
| 2 | Discovery counts marker-registered files as present: `settled_days.py:93`, `price_free_model_learning.py:161`, the replay globs (`replay.py:52`, `replay_backtest.py:353`), `discover_tapes`, `captured_input_parity_evidence` | Archived days otherwise disappear silently | M, 2–3 d |
| 3 | `replay_status_backfill` reuses its existing status instead of re-reading all 1,442 folders (`:78-86`) | Otherwise it raises `ArchivedInputRequired` and the step fails | S–M, 1 d |
| 4 | Hourly and ten-minute scoring report "archived" separately from `missing_tape` (`hourly_model_scoring.py:260`) | Stops the corpus shrinking silently, which can block promotion | S, 0.5 d |
| 5 | A workstation "restore set" command: date range plus families → `locate` → download → restore → publish to `restore_cache`, checked against the event-day manifest SHA | This is the actual "download for retrains" step | M, 2 d |
| 6 | Finish the closed-day Parquet backfill and the event-day manifest backfill (48 of 1,357) | The PIT lane reads hash-checked Parquet first, so raw files can then leave | L, mostly runtime |
| 7 | Extend the lane to nested paths, `mm_runs` and folders with more than 10k files | Unblocks about 85 GiB | M, 2–3 d |

- **Identity:** restoring a byte-identical file to its original path passes the manifest checks (SHA-256 plus size). A file copied by hand into `restore_cache` is refused; the catalog's publish step has to put it there. Signatures bound to file mtime (the closed-day signature and `mm_scoring_projection.py:301`) will re-plan or refuse after a restore. That costs time and is not a failure.
- **No change needed:** the base retrain (WU plus forecast CSVs) stays hot.
- **Roll risk:** items 1–4 change modules imported by the capture loop, so they merge in the 01:00–04:00 quiet window.

## E. Risks

- **Drive outage:** capture is unaffected. Uploads refuse and keep their sources. Readers raise `ArchivedInputRequired` instead of returning empty data. Retrains that need archived days wait, and so does reclaim.
- **Account loss:** after reclaim, Drive holds the **only copy**. The mirror has been frozen since 08-12 and its last verify failed. The recovery keys are stored in the **same Drive remote** (item-325:200). Mitigation: keep a key copy off Drive (printout or password manager). Optionally keep a second copy of the small irreplaceable families (~3.7 GiB) on other media.
- **Uplink saturation:** the 8 MiB/s cap (about 67 Mbit/s) may exceed the home uplink, which is UNVERIFIED. That would delay capture websockets. Measure the uplink first. If it is 20 Mbit/s or less, set `--bwlimit 2M` (about 7 GiB/h, still enough for 6 GiB a night).
- **Public repo:** raw capture can contain URLs, headers and secrets. Encrypting before upload is mandatory and already built in. Never commit receipts that contain object IDs together with tokens. Agents never read the rclone config.
- **Drive limits:** 750 GB/day upload, fine. 5M items, fine (~4 objects per archive).

## F. Owner decisions

1. **Reconcile the DISABLED headers with the 09-23 and 09-26 re-enable.** Recommend: yes, a docs-only change tonight.
2. **Sign the replay_cache delete manifest (32.3 GiB).** Recommend: yes, now.
3. **Sign the order_books_long.csv.gz twin-parity deletes (~29 GiB).** Recommend: yes, once each twin's parity is proven.
4. **Reclaim the 1.55 GiB LOCAL_WITH_CLOUD_COPY files.** Recommend: yes, as the first drill of the procedure.
5. **Fund D1–D5 (~1–1.5 weeks) before offloading variant, explanation or snapshot families.** Recommend: yes, merging in quiet windows after 10-14.
6. **Keep replay_inputs local (decision 11).** Recommend: keep it as is. NTFS already brings it to 28% of its size.
7. **Make the lane a recurring scheduled task.** Recommend: decide by 11-05, after two manual campaigns.
8. **Key custody and a second copy of the irreplaceable families.** Recommend: yes. It is small, and Drive capacity is free.
9. **Measure the uplink and set the bandwidth limit.** Recommend: yes, before the first campaign.

## G. Is this necessary now?

Not for safety yet. Free space is 104 GiB and rising to about 264 GiB by about 10-22 in the central case (ESTIMATED). It becomes necessary once the backlog is spent:
- around late November to mid-December in the central case;
- by **late October** if days like 10-02 repeat (about 23 GiB burned in 24 h despite a 19.86 GiB 91a night; cause UNVERIFIED and worth investigating).

Recommended order:
1. Do the cheap deletes and the doc fixes now.
2. Do the D1–D5 code work and the first Drive campaigns during 10-16 to 11-05. That is the high free-space window, and staging needs at least 50 GiB spare.
3. Treat Drive as a capacity tier running at about 175 GiB/month from then on, not as a backup.

**Files:**
- C:\Users\micha\Desktop\github\weather\docs\operations\production-cold-archive-staging.md
- C:\Users\micha\Desktop\github\weather\docs\operations\cold-archive-locations.md
- C:\Users\micha\Desktop\github\weather\docs\roadmap\audits\storage-value-assessment-2026-09-26.md
- C:\Users\micha\Desktop\github\weather\data\cold_archive\WHERE_DATA_IS.md
- C:\Users\micha\Desktop\github\weather\scripts\ops\production_cold_archive_run.ps1
- C:\Users\micha\Desktop\github\weather\src\weather\backtesting\settlement_ledger.py

## Critic

**Verdict:** The direction is sound, but don't act on it yet. Five points need fixing first: the reclaim window, an unsigned waiver presented as granted, the key copy kept on the same Drive, the missing cost of restoring for a retrain, and hash checks that go only one level deep.

1. **The upload window is narrower than C3 says (MEASURED).** `scripts/ops/production_cold_archive_run.ps1:44` refuses any run from 04:45 to 06:45 ("reserved for scheduled tiering jobs"). STATE_OF_PLAY.md:55-56 reserves 06:41–09:00 for the exam. The 01:00–04:00 quiet-window merges also compete for the one shared lease. That leaves roughly 00:30–04:45 for the archive lane in practice. The 8M cap (`production_cold_archive_transfer_core.py:240`, about 28 GiB/h in theory) is not the risk at night. The risk is a run that overlaps a 01:00 merge or a 00:30 suite. Check that the 6 GiB/night pace fits in about 3 h after lease contention. The pace is UNVERIFIED. No upload should ever run in the 12:00–18:00 window. A daytime workstation restore is fine because it uses a different host.

2. **The replay_cache waiver is presented as granted, but it is not (MEASURED).** `storage-value-assessment-2026-09-26.md:44,67,96` lists it as "NEEDS_OWNER waiver". STATE_OF_PLAY does not mention replay_cache at all. Table A's "DELETABLE (waiver 09-26)" should say "pending F2". The "decision 6" twin-parity basis for order_books_long and "decision 11" for replay_inputs are cited but were not found in canon this pass (UNVERIFIED).

3. **Exam and 88a holds on the "Now" deletions.** Tier B claims to be "exam-safe" but excludes nothing by date. The order_books_long twin deletes and the log and diagnostics purge both need an explicit exclusion of UTC 09-27..10-30. That range covers the exam panel 09-30..10-13 and the 88a hold 10-15..10-30 (STATE_OF_PLAY.md:52,60). They should also exclude the exam roots `scratch\maker-replay-exam-c2` and `maker-replay-panel`, so a "failed stages and worktrees" sweep cannot catch them. Exclude the pinned deployment worktrees (`:48`) too.

4. **After reclaim, Drive holds the only copy, and the keys sit on that same Drive (MEASURED).** item-325 around line 200 puts the recovery keys in "the same Drive remote". The workstation mirror is frozen. The off-Drive key copy (F8) should therefore be a precondition for any reclaim, not a parallel recommendation. AGENTS.md says "Never delete or rewrite tapes, ledgers, or trading evidence casually". A single-copy reclaim of tape families arguably needs the owner to accept, explicitly, that Drive becomes the sole copy.

5. **Hash checks are one level deep.** Drive's MD5 covers the ciphertext only, and rclone crypt exposes no plaintext hash. On production, step 3 "download and re-hash" checks the encrypted object. Only workstation step 4 (`cryptcheck` plus per-member SHA-256) proves the plaintext. The synthesis should say so, and make step 4 mandatory before step 5. The reclaim gate should require a receipt from a workstation restore, not from the production download.

6. **The cost of restoring for a retrain is missing.** Nothing covers downlink time, workstation disk staging, or the D5 command's runtime. For example, restoring 200 GiB at an UNVERIFIED downlink, plus decrypting and checking it, may take hours to days. The "retrains need under 25 GiB" figure is ESTIMATED with no evidence. Replay, parity and the residual corpus (the second retrain lane) read variant_predictions, order_books and explanations, which this plan sends to COLD. Add a restore-time drill (step 7) with a number.

7. **The projection rests on shaky inputs.** The 91a policy expires 10-30 (STATE_OF_PLAY.md:51), and the projection assumes it renews. Free space was about 117 GiB at 02:40 (STATE_OF_PLAY.md:3) and is 103.8 GiB now. That is about 13 GiB lost within the same day, which reinforces the unexplained 10-02 burn. Investigate that burn before trusting the January date.

8. **The order of D1 and the deletions, and the mtime signatures.** Archiving any snapshot or `_long.csv` family before D1 lands risks silently deleting labels rows. Make it a hard block, not "M, 1–2 d". Deleting `_long.csv.gz` twins can also change closed-day mtime signatures (`mm_scoring_projection.py:301`). Confirm those files are outside the signed inputs before signing F3 (UNVERIFIED).
