# Storage value assessment — 2026-09-26

- **Owns:** the multi-agent read-only assessment of every large data family on the production host (keep / compress / archive to cloud / delete), with skeptic review of every delete and archive recommendation.
- **Read when:** planning any reclaim, archive campaign, retention change or 91a registration.
- **Do not use for:** current free space (`Get-Volume`) or retention rules themselves ([data-retention-policy](../../operations/data-retention-policy.md)).

**Disposition so far:** retired `mm_runs`/`taker_runs` NTFS-compressed 2026-09-26 (51.4 GiB logical, 51.4 → 26.2 GiB on disk, receipt `data/alerts/disk-reclaim-20260926/`). **Owner 2026-09-26: decisions 1-9 approved, 10 keep, 11 no** (DECISION_LOG). Production runs 1, 2, 3 and 8 under exact manifests and lands 91a (4); handoff 110j builds 5, 6, 7 and 9. Exchange-economics baseline re-accepted the same day.


## 1. Verdict

- **This is urgent.** Free space was 52.85 GiB at 00:05 on 09-26, and the disk loses about 5-8 GiB a day. 88a capture stops itself below 50 GiB. The Drive staging lane needs about 50 GiB of spare capture space before it will stage anything. So the Drive route stays mostly blocked until we free space by deleting first.
- **Route (a), delete what can be rebuilt or is duplicated:** about 21-26 GiB. This needs owner-signed exact-path manifests and no code change, so it can be done within days. Adding the replay_cache waiver adds another 32 GiB, for about 53-58 GiB in total. That is the only large, safe and fast win available.
- **Route (c), compress in place with NTFS (mission 91a):** about 170+ GiB on paper. That figure uses assumed compression ratios that were never measured. Nothing is lost, but 91a is not registered yet. Its 64 MiB per-file limit also refuses most of clob_tokens.jsonl, which averages about 81 MiB per file. This is the biggest route, but it takes weeks, not days.
- **Route (b), archive to Drive and then remove the local copy:** about 100-130 GiB of candidates. Most of it is blocked by missing lane support (nested paths, mm_runs paths, over 10k files per event), by event-day manifests that only exist for 48 of 1,357 folders, or by owner approval. Only the top-level price_history files (about 7.9 GiB) can go through the existing lane today.
- **Deleting only buys about a week.** The lasting fix is to cut growth where the data is written: compress clob_tokens when each day closes, stop writing the `*_long.csv` copies twice, and let 91a compress each day as it closes.
- **Answer to "is it useful?"** Much of it is not: paper maker and taker detail, June-era caches and exports, rotated logs, staging copies. The biggest families, though (CLOB tokens and summary, replay inputs, the snapshot tape, variant predictions), are evidence that cannot be rebuilt. Those have to be compressed or archived, not deleted.

## 2. Family table (the skeptic's correction is used wherever the recommendation was not upheld)

| Family | Size GiB | Value (one line) | Recommendation after challenge | Reclaim GiB | Route | Conf. |
|---|---|---|---|---|---|---|
| clob_tokens.jsonl | 60.21 | Gamma series plus join key; no live reader; join key is also inside the book tape | COMPRESS_IN_PLACE (closed days); Drive for days over 30 days old later | ~45 (assumed ratio) | 91a NTFS, but the 64 MiB limit blocks most bytes | med |
| clob_tokens.csv | 40.52 | Live join key for today's MM; a duplicate wherever a jsonl exists | COMPRESS_IN_PLACE; later reclassify it as a projection | ~30 | 91a NTFS | med |
| clob_capture_status.jsonl | 8.44 | Capture-health tape; cannot be rebuilt | COMPRESS_IN_PLACE | ~5 | 91a | med |
| order_books.jsonl.gz | 21.87 | The only full-depth book history | ARCHIVE_SUBSET for days up to 07-30 only; lowest priority | unknown (the ~7 figure is unverified) | Verified cold archive | low |
| order_books.jsonl (open days) | 3.14 | Live book tape | KEEP_HOT | 0 | Tiering at 06:00 already handles it | high |
| order_books_long.csv.gz | 34.72 | Dead weight wherever a jsonl.gz twin exists | DELETE_SUBSET: jsonl.gz twin required, parity proven, no split days, over 14 days old, contract amended | ~29 (unverified) | Extend closed_day_projection_tiering (code change) | med |
| order_books_summary.csv | 44.79 | Midpoint source for markouts; live MM input | COMPRESS_IN_PLACE (closed days older than 14 days) | ~27 | 91a | high |
| market_ws / clob_features | 2.2 | Low | COMPRESS_IN_PLACE | ~1.3 | 91a | high |
| replay_inputs | 77.96 | The only point-in-time input record | COMPRESS_IN_PLACE; move to Drive only if the owner reverses item-325:218 | ~45 | 91a | high |
| variant_predictions / snapshot_explanations | 84.61 | jsonl is the canonical record of what was served; the long CSVs duplicate it | ARCHIVE_SUBSET for days over 30 days old, after re-measuring; NTFS for days 3-30 | ~59 (unverified) | Cold archive, one family per chunk; reader gap must be fixed first | high |
| Snapshot tape JSONL plus CSV projections | 67.01 | Behind nearly every model finding | **Corrected:** COMPRESS_IN_PLACE now; archive only after event-day manifests are backfilled; never delete the CSVs on their own | not estimated (ratio not measured) | 91a | med |
| Legacy per-event forecast_payloads | 36.11 | Only July-September point-in-time forecast bytes; NBM v1/v2 replay | COMPRESS_IN_PLACE; later dedupe into the CAS (~30) | ~14 | 91a (must cover nested paths) | med |
| forecast_payload_cas blobs | 13.1 | The NBM bulletin store; garbage collection is disabled | COMPRESS_IN_PLACE | ~7 | Needs a 91a lane extension | med |
| fetch_fanout receipts | 0.53 logical | Very low; the manifests keep the hashes | Archive monthly tar.gz, then delete; `.claim` files older than 7 days go by TTL | unknown (allocated size not measured) | Registry row first, then cold archive | med |
| forecast_history | 0.22 | The honest point-in-time corpus | KEEP_HOT; reclassify from operator_cache to canonical | 0 | — | high |
| price_history_raw/ | 21.26 (3.46M files) | Low; unread; no finding cites it | Archive only once the lane supports it; never delete | ~21+ | Lane extension needed (nested paths, 256 members per chunk, MAX_FILES 10k) | high |
| price_history.jsonl / raw_manifest / csv | 7.89 | Low; the manifest indexes the raw blobs | ARCHIVE now; the manifest must never be reclaimed before its restore check or ahead of its blobs | ~7.9 | Existing lane with market_day_file_family_v1 | high |
| mm_runs scoring projections | 8.23 | None; rebuildable | DELETE_SUBSET, leaving out the 14 runs Stage A still reads (or pass `--paper-maker-paused`) | ~7-8 | Exact manifest plus cleanup_preflight | high |
| mm_runs quote-intent CSVs | 33.4 | Low (retired paper maker); EF §8bb cites 07-31..08-08 | ARCHIVE the CSVs only (~25.7 plus ~7.44 in quarantine); keep quarantine jsonl and other non-CSV files; keep §8bb dates hot or update the docs | ~32 | Lane extension, or owner-attended tar + rclone cryptcheck | high |
| taker counterfactual detail | 3.21 (6 files) | Very low; past its 14-day retention | DELETE the 6 exact files; gzip them to Drive first (advised) | 3.21 | Owner-signed manifest | high |
| taker remaining run evidence | 5.9 | Low; four historical readers | **Corrected:** KEEP pending an owner decision | 0 now | — | med |
| backtest/replay_cache | 32.28 | Near zero; keys are June-era | NEEDS_OWNER waiver, then delete (or tar to Drive) | ~32 | Owner waiver | high |
| backtest root exports | 10.73 | Low | Delete now: the active_variant_shadow exports and `*_shadow_variants` (~3.5-5.5). Archive the rest. Exclude the pinned baseline CSV, frozen_baseline_manifest, item224 composite rows and any cited pickles or reports | ~3.5-5.5 delete, ~5-7 archive | backtest_artifact_retention manifest, then cold archive | med |
| backtest subdirectories | 1.2 | Low | KEEP_HOT | 0 | — | med |
| Historical source rows | 18.38 | Settlement proxy and training history | KEEP_HOT | 0 | — | high |
| WU atomic-write `.tmp` orphans | 0.47 (16 files) | None | DELETE through a canonical-gate manifest with 4 proofs, including a PID-reuse check | 0.47 | Manifest (precedent 07-21) | high |
| Rotated console logs | 5.56 | Near zero | DELETE the ones stamped before 09-12 (~3.4). Keep the 4 incident files; the 07-13 CLOB console stays byte-identical | ~3.4 | Manifest (operator_cache TTL) | high |
| Rotated diagnostics JSONL | 7.03 | Low | ARCHIVE clob_diagnostics and diagnostics (~5.3-5.8). **Keep observation_triggers (1.22)** until panel B is scored | ~5.5 | Owner gate plus registry fix, then manifest, gzip, Drive | med |
| data/logs, alerts, status tmp | 0.1 | Ops history | KEEP (optionally drop tmp files under 10 MB) | ~0 | — | high |
| Small canonical (88a, execution tape, settlements, wallet) | 3.71 | Highest value per byte on the host | KEEP_HOT | 0 | — | high |
| Staged archive tarballs | 3.44 | Near zero for the failed ones | **Corrected:** DELETE only the 8 FAIL_CLOSED stages; keep the 4 PASS stages (bound to reclaim campaigns) | ~1.97 | Owner lifts the staging-doc clause | high |
| Worktrees (208) | 13.5 | None if clean and merged | DELETE_SUBSET under git-workflow §7 (origin/master ancestry, `--ignored` inventory, indirect task bindings, locked ones excluded) | ~1-3 | Agent run, with receipt | med |
| C:/tmp research dirs, clob_v2_venv | ~0.3-0.5 | Nil, except 2 cited manifests | Delete after moving item40_artifacts and preselect-dryrun (plus clock-receipts?) | ~0.3 | With the worktree receipt | med |
| closed_market_days Parquet | 2.46 | Growing: the local query copy once raw data moves to Drive | KEEP_HOT | 0 | — | med |
| cold_archive catalog and receipts | 0.1 | The map to Drive | KEEP_HOT | 0 | — | high |
| scratch/handoffs | 0.31 | Low | NEEDS_OWNER (the 0.13 rclone.bin) | ~0.14 | — | med |
| .git / .git/lfs | 1.4 | Required | KEEP | 0 | — | high |
| venv / artifacts | 1.11 | Required | KEEP | 0 | — | high |

## 3. Do-now plan, in order

Two rules apply throughout. Run every data-touching step inside 00:30-09:00 under the `workload_admission.ps1` lease, and never during 12:00-18:00 or 00:00-00:15. Take a free-bytes reading before and after each step.

**(a) Delete derived, regenerable or duplicate data (lowest risk)**
1. **backtest/replay_cache, 32.28 GiB.** First: the owner waives the reachability-manifest rule, because artifacts/releases does not exist on this host so the rule can never be met. Then delete the whole directory, or tar it to Drive if the owner wants a copy. Write a receipt.
2. **mm_runs scoring projections, ~7-8 GiB.** Build an exact-path manifest with SHA-256 values, naming the quote-intent tape as the rebuild source. Run `python -m weather.operations.cleanup_preflight --manifest`, then get owner sign-off. First: either add `--paper-maker-paused` to the Stage-A task or leave out the latest 14 runs. For each run, the sibling quote-intent tapes must be present and must match the size and mtime in its projection manifest. Do this before any gzip of the mm_runs tapes.
3. **Rotated console logs, ~3.4 GiB.** Exact manifest: rotated files stamped before 09-12, plus `observation_trigger_console.log.malformed.bak`. Exclude the 4 incident files and the live consoles.
4. **backtest root shadow exports, ~3.5-5.5 GiB.** Run `python -m weather.reporting.data_quality.backtest_artifact_retention`, then cleanup_preflight. Before it runs, hand-exclude `model_variant_evidence_baseline_active_shadow_long.csv` and its manifest, `frozen_baseline_manifest.json` and `item224_active_source_route_composite_rows.csv`.
5. **taker counterfactual detail, 3.21 GiB.** Manifest covering the 6 named files. Gzip them to Drive first (advised). In the same change, correct the class error in taker-paused-and-pruned-2026-08-07.md.
6. **Failed staging tarballs, ~1.97 GiB.** Covers 8 attempts: e10d1/e10d2/e10d5/e10r6 and p11b-e. First the owner lifts production-cold-archive-staging.md:17-19 and supersedes the p11b checkpoint note. Keep every receipt JSON.
7. **Worktrees plus C:/tmp, ~1.3-3.5 GiB.** Follow the git-workflow §7 procedure and write a receipt. Delete no branches.
8. **WU `.tmp` orphans, 0.47 GiB.** Canonical-gate manifest using the 4 proofs, with the PID check comparing process start time against the file's mtime.

Running steps 1-8 gives about 53-58 GiB and brings free space back above the staging and 88a thresholds.

**(b) Archive to Drive, then remove originals through the verified cold archive** (production_cold_archive_run.ps1 stage/upload/transfer, then an independent workstation restore within 24 h, then `-Operation reclaim`, with owner approval for each campaign)

9. **price_history.jsonl, raw_manifest and csv, ~7.9 GiB.** The existing lane accepts these. The raw blobs stay local.
10. **Rotated clob_diagnostics and diagnostics, ~5.5 GiB.** First: correct the registry (roll-sensitive, so the quiet window) or get an owner canonical-gate sign-off.
11. **variant_predictions and explanations older than 30 days, ~59 GiB unverified.** First: re-measure; make `discover_tapes` and `captured_input_parity_evidence` archive-aware; confirm whether an event-day manifest is required. Run small batches oldest first and reclaim each batch before staging the next.
12. **mm_runs quote-intent CSVs, ~32 GiB.** First: extend the lane to mm_runs paths, or run an owner-attended tar + rclone cryptcheck with a restore test. Decide how to handle the EF §8bb dates.
13. **price_history_raw, ~21 GiB.** First: a reviewed lane extension that makes one tar per event subtree.
14. **backtest root remainder (~5-7 GiB), fetch_fanout receipts, and order_books.jsonl.gz up to 07-30.** These come last.

**(c) Compress in place**
15. Register and bound mission 91a. Raise or chunk the 64 MiB limit for clob_tokens.jsonl. Extend it to nested forecast_payloads paths and CAS `.blob` files.
16. Order of work: clob_tokens.jsonl and csv, then replay_inputs, then order_books_summary, then snapshot JSONL and CSVs, then legacy forecast_payloads, then capture_status and CAS. Closed days only, older than the current day plus the previous 14 days.
17. Source-side slope fixes, all roll-sensitive and in the quiet window: compress clob_tokens.jsonl when each day closes; stop writing the `*_long.csv` copies (after migrating their readers); write rotated sidecars as gzip; gzip-tier order_books_long by extending closed_day_projection_tiering.

**(d) Keep:** everything listed in section 5.

## 4. Owner decisions needed

1. **replay_cache waiver** (32.28 GiB). Recommend deleting it. It is a rebuildable cache keyed to June models, so a Drive upload is not worth the time it takes.
2. **Sign the step (a) delete manifests** (~21-26 GiB). Recommend yes, and add `--paper-maker-paused` to Stage A.
3. **Lift the staging retention clause** for the 8 failed stages only (1.97 GiB). Recommend yes.
4. **Register 91a and allow raising the 64 MiB limit** (~170+ GiB, assumed). Recommend yes. This is the single biggest lever.
5. **Resume Drive campaigns** for variant predictions, top-level price_history, rotated diagnostics and mm_runs quote intents (~100+ GiB). Recommend yes, sequenced after decision 1 so staging has room.
6. **Accept the rebuild-parity argument for order_books_long** and amend data-storage-class-contract.md:21 and data-retention-policy.md:270-272 (~29 GiB, unverified). Recommend yes, limited to days with a jsonl.gz twin.
7. **Registry corrections:** clob_diagnostics and rotated diagnostics become operator logs; add fetch_fanout rows; exclude WU `.tmp` files; reclassify forecast_history as canonical; add a maker_evidence retention row. These are enablers, not direct reclaim. Recommend yes, in the quiet window.
8. **EF §8e incident logs:** does gzip-and-retain count as retaining them? (~1.4 GiB). Recommend yes, except the 07-13 file, which stays untouched.
9. **Source-side write stops** (roughly 1-2 GiB a day of growth). Recommend compress-on-close first and the long-CSV write stop second.
10. **Remaining taker evidence** (5.9 GiB). Recommend keeping it for now and archiving later as low priority.
11. **Reverse item-325:218 so replay_inputs can move to Drive.** Recommend no, unless the disk is still short after 91a.

## 5. What NOT to touch, and why

- **88a data/maker_evidence, execution_tape, settlements, market_day_labels, wallet_ledger, observation_payloads.** These are the informed maker's replay inputs, the ground truth and the RE-1 accounting. They cannot be re-fetched.
- **order_books.jsonl(.gz) from 07-31 onward.** Owner guidance from 09-09, the execution-tape join from 08-10, frozen 89a panel A (08-15..09-23) and panel B (09-25..10-08) all depend on these days.
- **observation_triggers rotations.** They are the E2 source for panel B. The desk-study tool reads only the unrotated file, which is a latent defect the owner should hear about.
- **CAS blobs and legacy forecast payloads:** no deletion or GC. Garbage collection is disabled, and NBM layers 2/3 need them.
- **Snapshot JSONL, replay_inputs, variant jsonl:** no deletion of any kind. `snapshots_long.csv` and `features_long.csv` must not be removed on their own either, because labels, settled_days, the admissibility clock and freshness readers treat a folder without them as a day that does not exist.
- **Historical source rows and WU history.** WU is the settlement proxy.
- **Folders with no raw JSONL** (~93): there, order_books_long.csv.gz is the only full-depth record.
- **clob_loop_console.20260713T145512118267Z.log** (the spent archive attempt) and the three 0814 incident files, except as owner decision 8 allows.
- **PASS-stage tarballs** p11j00016s1, p11j00025s1, p11m00003s1 and p17a00003s1. They are bound to pending reclaim campaigns.
- **Pinned files in backtest:** the frozen baseline CSV and its manifest, frozen_baseline_manifest.json, the item224 composite input rows, and the pickles and reports that roadmap items cite.
- **Worktrees that are locked, bound to a task (directly or through an ops script), used for boot recovery, or not merged**, and any whose ignored `data/` is not trivial.
- **.git/lfs, venv, artifacts, the cold_archive catalog, closed_market_days Parquet, current-day and last-14-day files, and the RE-1 campaign root.**

## 6. Unknowns to measure first (cheapest read-only method)

1. **Real LZNT1 ratio per family.** Run `compact /q` over the Aug 6-12 folders, which are already NTFS-compressed; it reports logical versus allocated size per file. This turns the ~170 GiB estimate into a real number.
2. **Age split per family** (how much is over 14 or 30 days old). The snapshot_age_buckets field came out empty. Re-run `weather.operations.storage_recovery_inventory` in the lease window, or fix the bucket bug in the scratch script.
3. **Originals already uploaded to Drive and restore-verified but still on disk** (LOCAL_WITH_CLOUD_COPY, for example e10d00001). Read data/cold_archive/WHERE_DATA_IS.md and the catalog. This is the cheapest reclaim of all and its size is unknown.
4. **Whether the production staging lane requires a current event_day_manifest** (only 48 of 1,357 folders have one). Read the selection checks in production_cold_archive_stage.py.
5. **How many order_books_long days have a jsonl.gz twin, plus the split and post-09-19 days.** A one-level stat of names per event folder, or a dry-run plan from closed_day_projection_tiering.
6. **variant_predictions bytes older than 30 days,** since the 81-vs-59 GiB figures conflict. Answered by the same inventory as item 2.
7. **Allocated size of fetch_fanout** (650k files). Run `compact /q /s` or a bounded allocated-size inventory in the lease window.
8. **Sizes of C:/tmp, scratch/w and the 165 sibling worktrees.** Measure each one with a timeout, not a single du over everything.
9. **Which family the Stage-A daily persistence (~5-6 GiB/day) and the +3-3.7 GiB steps come from.** Diff two consecutive name-level inventories.
10. **Growth since the 09-24 inventory,** about 2 days unmeasured. Read the volume's free bytes now.
11. **Size of the pre-07-31 order_books.jsonl.gz subset.** Read data/backtest/clob_raw_tape_tiering_report.md.
12. **System Restore shadow storage after the cap, and pagefile/hiberfil sizes.** Run `vssadmin list shadowstorage` and check the file attributes.