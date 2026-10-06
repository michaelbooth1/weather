# Agent report 2026-09-111i — cold-snapshot nightly: skip tiny files, two-day selection

Handoff: [workstation-handoff-2026-09-111i-cold-snapshot-tiny-files.md](workstation-handoff-2026-09-111i-cold-snapshot-tiny-files.md).
Owner decision: [DECISION_LOG](../operations/DECISION_LOG.md) row 2026-09-30 (two days instead of fourteen).
Branch `codex/cold-snapshot-tiny-files-20260930`. Workstation (Claude Code), fixtures only. Open questions served: none.

**Verdict: FIXED on fixtures; expected ROLL-FREE (production to confirm with `roll_verdict.ps1`).** Files that cannot
shrink (logical size below 4 KiB, or allocation not above one 4 KiB cluster) are skipped at selection with a recorded
reason and never opened, compressed or counted; a selected file that reclaims nothing still stops its batch. The nightly
now selects closed built-in market-days at least two local days old whose files are unchanged for two days. The failed
attempt `nightly-20260930-apply-lowbudget-a1` had **no honest way to be cleared** on master (see §3); this branch adds one.

## 1. What changed

| File | Change |
| --- | --- |
| `src/weather/operations/cold_snapshot_nightly.py` | `unshrinkable()` reasons; `plan_batches(..., skipped=)`; per-folder `skipped-NNNN.json` (inventory-hash bound, inside the 64 MiB evidence bound); receipt field `files_skipped_unshrinkable`; `HOT_WINDOW_DAYS = 1`, `UNCHANGED_SECONDS = 2 days` |
| `src/weather/operations/storage_recovery_inventory.py` | `validate_folders` hot windows are now {1, 30}: the nightly-only 14 is replaced by 1; the attended 30-day contract is unchanged |
| `src/weather/operations/cold_snapshot_nightly_resolution.py` | New read-only-over-receipts CLI that writes one create-only resolution for a failed nightly attempt (§3) |
| `scripts/ops/cold_snapshot_nightly_run.ps1` | A non-PASS prior attempt is accepted only with a resolution whose `wrapper_result_sha256` equals the prior's `wrapper-result.json` hash; the attempt still consumes its date |
| `docs/operations/cold-snapshot-compression.md`, `storage-recovery-inventory.md` | Two-day rule, tiny-file skip, resolution procedure |
| tests | `test_cold_snapshot_nightly.py` (2-day boundaries, 385/392-byte resident file skipped with reason, 8 KiB zero-savings file still stops the batch and never touches the next file), new `test_cold_snapshot_nightly_resolution.py` |

Unchanged: `compress_candidate` (stop rule at `cold_snapshot_compression.py:220-221`), every hash, identity,
writer-exclusion, lease, admission, window, budget and reservation check, the attended lane's 30-day/64 MiB contract.

**Age semantics, stated exactly.** "At least two local days old" is implemented literally: at Toronto date D+2 the
market-day D is selectable and D+1 is not (event strictly older than a one-day hot window). With the 00:30 start and the
separate 48 h unchanged-file rule, files last written late on D are usually picked up at D+3. If the owner meant "strictly
older than two days" (the old "strictly older than 14" shape), set `HOT_WINDOW_DAYS = 2` and allow 2 in
`storage_recovery_inventory.HOT_WINDOW_WORDS`.

## 2. Tiny-file rule

Skip reasons: `logical_size_below_one_cluster` (size < 4096) and `allocation_not_above_one_cluster` (allocation <= 4096).
The measured failure (`replay_input_status.json`, 385 bytes, allocation 392, MFT-resident) is skipped by the first. The
cluster is the documented 4 KiB NTFS default (`CLUSTER_BYTES`), not queried; on a larger-cluster volume a file between
4 KiB and one cluster would be selected and stop its batch, which is the safe direction. Skipped files consume no byte or
file budget.

## 3. Resolving `nightly-20260930-apply-lowbudget-a1`

Finding: on master the runner refused any prior nightly attempt whose wrapper was not PASS, with no clearing input, and
the doc's "resolve through the retained-file verification contract" could not work: `-VerifyRetained` requires the
preimage directly under one attempt directory (nightly journals sit in `batch-NNNN/`), a `cold_snapshot_compression_receipt`
envelope (nightly journals have none) and an attended `cold_snapshot_compression_request` predecessor (nightly has a
policy). So the interlock would have blocked forever or tempted a rename.

`python -m weather.operations.cold_snapshot_nightly_resolution` refuses unless: wrapper `FAILED`, `teardown_proved`, no
hard stop, `deleted_files 0`; child `result.json` is the bound `FAILED_RETAIN_AND_INSPECT` (same source and request
hash); every batch's journals form a contiguous prefix of its `selection.json`; every started file has both journals,
the after-journal is `VERIFIED` with the preimage SHA-256, LZNT1 format, unchanged identity fields and consistent
`reclaimed_bytes`. It reads no source payload, writes only
`scratch/cold_snapshot_compression/resolved-nightly/<attempt>.json` (create-only) and never touches the attempt. Its
`verified_reclaimed_bytes` is reconciliation only and never enters a nightly total; the eight files are now compressed
(0x800) and are excluded from every later selection. An attempt with a before-journal lacking its after-journal is
refused and stays blocking; extending `-VerifyRetained` to nightly journals is **not done** and is reported as a
requirement if that case ever occurs.

Per the handoff, all eight files of the 09-30 attempt have VERIFIED equal-hash journals, so the resolution applies; the
production agent should confirm that from the receipts rather than from this report.

Schema note: the resolution record uses the existing `cold_snapshot_nightly_receipt` version with
`record: "failed_attempt_resolution"` instead of a new registry entry, deliberately, so the branch stays out of the
`schema_registry*` family (which is in all four capture closures) during the exam period. A dedicated schema can follow
after 10-13 if wanted.

## 4. Projected per-night reclaim (PROJECTED, not measured)

Inputs from production (handoff): the 32 GiB dry run filled its budget with 4,851 files (mean ~6.8 MiB, so large files
dominate the bytes and the tiny-file skip removes almost none of them); seven files compressed at allocation ratios of
about 3-4:1 (e.g. 634,880 -> 159,744 bytes, 3.97:1). Projection while the backlog lasts: reclaim = budget x (1 - 1/r) =
**~21 GiB (r = 3) to ~24 GiB (r = 4) per night at the 32 GiB budget**, and ~0.67-0.75 GiB per 1 GiB low-budget apply.
Hashing is twice per file at 16 MiB/s, so 32 GiB needs ~68 minutes of hashing plus unmeasured compression time inside
the 00:30-04:45 window. The two-day rule adds roughly twelve more closed days to the eligible backlog (size not measured
here). Steady state after the backlog is bounded by one day's closed snapshot growth x 0.67-0.75; that growth is not
measured on the workstation. Seven files are a thin basis for r; the first low-budget apply on the fixed tip is the
measurement.

## 5. Roll verdict inputs (per file)

| File | Closures |
| --- | --- |
| `cold_snapshot_nightly.py`, `cold_snapshot_nightly_resolution.py`, `storage_recovery_inventory.py` | None expected: imported only by operations CLIs (cold snapshot, storage recovery, cold archive); no capture loop imports them |
| `cold_snapshot_nightly_run.ps1` | None (`.ps1`) |
| docs, tests | None |

No `schema_registry*` file changed. Production must re-derive with `scripts\ops\roll_verdict.ps1 -Branch
codex/cold-snapshot-tiny-files-20260930`; the workstation has no capture status files.

## 6. Verification on the workstation

- Focused + audits under `scripts\ops\workstation_heavy.ps1`: cold-snapshot nightly/resolution/compression/wrapper/
  verification, storage-recovery inventory/batch plan, schema registry, import architecture, agent docs, path policy,
  module size, release import boundary, app architecture: 270 passed, 1 skipped (native NTFS fixtures ran).
- `python -m weather.operations.agent_docs_audit`: PASS. `compileall -q app src tests`: exit 0.
- Runner interlock smoke (scratch copy of its prior-attempt block against fixture attempts): resolved -> cleared; no
  resolution -> "requires review"; wrapper receipt changed after resolution -> "requires review"; resolved attempt on
  the same local date -> "already consumed this local date".

## 7. Not done

No registration, no production write, no restart, no merge, no production data read, no Scheduler change. The attempt
was not resolved (production does that). `docs/operations/storage-plan-2026-09-23.md` (dated plan) still says 14 days;
left as history. STATE_OF_PLAY not rewritten (production owns it).

## 8. Production steps (in order, all paths absolute on production)

1. Merge per the roll verdict (expected roll-free, so any night under the exam-period policy as disk relief).
2. Inspect `scratch\cold_snapshot_compression\nightly-20260930-apply-lowbudget-a1` receipts, then from the adopted tip:

   ```powershell
   .\venv\Scripts\python.exe -m weather.operations.cold_snapshot_nightly_resolution `
     --production-repo-root $productionRepo --attempt nightly-20260930-apply-lowbudget-a1 `
     --approved-by "<reviewer>"
   ```

   Expect `RESOLVED`, `files_verified` 8. Any refusal: stop and report its message.
   `nightly-20260930-dry-a1` is PASS and needs nothing.
3. In 00:30-04:45 under the lease, a fresh dry run: `scripts\ops\cold_snapshot_compression_run.ps1 -Nightly` with a new
   `-OutputRoot` under `scratch\cold_snapshot_compression`, the approved policy and the adopted tip. Review
   `files_skipped_unshrinkable`, the `skipped-*.json` reasons and that selections include days 3-14 old.
4. One low-budget apply (1 GiB policy) the same way with `-Apply`; expect PASS with positive `reclaimed_bytes` on every
   selected file. This measures r.
5. Register `WeatherColdSnapshotNightly` with `register_cold_snapshot_nightly.ps1 ... -Apply` bound to the adopted tip
   and the approved 32 GiB policy (runbook: [cold-snapshot-compression.md](../operations/cold-snapshot-compression.md)).
   Manual attempts named `nightly-<date>-*` consume that local date for the scheduled runner, so the first scheduled
   run is the following night.

Reproduce the tests on production (bounded suite rules apply there):

```powershell
.\venv\Scripts\python.exe -m pytest -q tests/operations/test_cold_snapshot_nightly.py tests/operations/test_cold_snapshot_nightly_resolution.py
```
