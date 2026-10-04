# Workstation handoff 2026-09-111i — cold-snapshot nightly stops on the first tiny file

Written 2026-09-30 by the production agent. Disk relief, so it may merge during the exam period. Base `origin/master`;
branch `codex/cold-snapshot-tiny-files-20260930`.

## What production measured (2026-09-30 00:40, source `b0032a907`)

- Dry run (`-Nightly`, 32 GiB policy): PASS; 1,233 closed folders inventoried, the 32 GiB budget filled with 4,851
  eligible files in 221 batches, so the eligible backlog is at least 32 GiB
  (`scratch/cold_snapshot_compression/nightly-20260930-dry-a1/`).
- Low-budget apply (1 GiB policy): the first seven files compressed and verified with equal hashes, allocation ratios
  about 3-4:1 (for example `clob_features.jsonl` 634,880 -> 159,744 bytes). The eighth,
  `replay_input_status.json` (385 bytes, allocation 392: NTFS keeps it resident in the MFT record), reclaimed 0 bytes,
  and `cold_snapshot_compression.py:220-221` raised "no positive allocated-byte savings; stop before expanding". The
  whole night stopped with 0.65 MiB saved (`.../nightly-20260930-apply-lowbudget-a1/`, status FAILED_RETAIN_AND_INSPECT).
- Nearly every closed folder holds files this small, so the nightly as written stops almost immediately every night.

## Work

1. Exclude, at selection time, files that cannot shrink: logical size below one allocation unit (4 KiB) or allocation
   not larger than one cluster. They are skipped with a recorded reason, never compressed, never counted.
2. Keep the stop rule for files that should shrink: a non-positive result on a selected file still stops the batch
   (that rule protects against real failures). Do not weaken hash, identity or admission checks.
3. Say exactly how production resolves the retained failed attempt `nightly-20260930-apply-lowbudget-a1` under the
   retained-file verification contract (docs/operations/cold-snapshot-compression.md), so the interlock that blocks
   later automatic runs is cleared honestly; all eight of its files are VERIFIED with equal hashes.
4. Report the expected per-night reclaim from the dry-run selection and the measured 3-4:1 allocation ratios, labelled
   as projected.

## Deliverables

Fixture tests (a resident 385-byte file is skipped with a reason; a 4 KiB+ file with zero savings still stops the
batch), the repo-wide audits, green CI, roll verdict inputs. Report
`docs/roadmap/agent-report-2026-09-111i-cold-snapshot-tiny-files.md` with the exact production steps: resolve the failed
attempt, rerun the dry run and a low-budget apply on the fixed tip, then register `WeatherColdSnapshotNightly`.
