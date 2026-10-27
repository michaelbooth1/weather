# R-V clarification RV-C1a: the Aug-Sep reported key set and a determinism control (history only, one look)

Lane L2, 2026-10-27. This amends RV-C1 `db11d8d2e1443143816302cbe16b1f065401ca4b8aa3d8ca61122ba1aaef3ba5`
(`clarification_rv_c1.md`), which amends R-V `b0cf2a03224d2581f96c77b801dd5244353ca1f2025ab0802940dcf65e88e818`
(`rule_rv.md`).

This clarification is hashed and pushed before the RV-C1a run. Dev-window ledger row 54
(`claude/l2-dev-ledger-rows-20261026`) is written PENDING before the run, and the run waits for master's confirmation.

**Authority.** Master's ruling of 2026-10-27, relayed by the coordinator: Option 1, RV-C1a on row 54, ACCEPTED.
- Control 2 for the reported Aug-Sep set uses gate 1's keys minus the rows with a non-finite F or current_temp.
  It must disclose exactly 1 such row, miami 2024-08-31 h13. Any other count is VOID.
- The PRIMARY and (b) controls and the decision rule are unchanged.
- A new determinism control: c1a's three row files must have the same sha256 as c1's. Only hashes are compared,
  no score is read, and a mismatch is VOID.
- The c1 outputs stay unread permanently, with their shas recorded in row 53.

## 1. Why RV-C1 was VOID (ledger row 53)

- RV-C1's control 2 required each scored set's keys to equal its reference file exactly.
- The reported-only Aug-Sep set had 13,107 keys, against R-V gate 1's 13,108 (`2a91bb80…`).
  - The missing key is (h13, 2024, miami, 2024-08-31).
- **Cause.** That row has a non-finite high_so_far or current_temp.
  - R-V gate 1 scored it through `rung_loyo`, which keeps such rows (the gap is `nan_to_num`ed).
  - RV-C1's read (a) serves through the served state. It needs finite inputs, so it drops the row, as C10 and
    SM-H do.
  - No served-path scorer could match gate 1's file. The defect was in RV-C1 §3 and control 2 as written (ruling
    D2), not in the data.
- **What was seen.** The run stopped before any score was summarised. Every number it printed is in row 53:
  - Oct-Dec gates 1a and 1b passed, with coverage 1.0.
  - Check 1 passed, with 103,609 forward rows and HRRR parity.
  - The PRIMARY keys (16,496) and the (b) keys (12,372) were identical to their references.
  - Tier-2, V-off (a), C10 fwd_rows reproduction and V-off (b) were all 0.0.
- **c1's row files stay unopened permanently.** They are not summarised, moved or deleted. Their shas:

| File | sha256 |
| --- | --- |
| `rows_a_octdec.jsonl` | `8f629f08326462f81190ff84d959d70b613919f39e0227ff82ed44771b9ec398` |
| `rows_a_augsep.jsonl` | `5265da71a5cf8966936c44f1caf6ab29043cdf400f55310921b7dfe57d786570` |
| `rows_b.jsonl` | `98959cf2bd48c42441152c4de1c7f7c65b7c35b7c0a1d9f22ad414ecfcb69372` |

## 2. What changes

1. **Control 2, the reported-only Aug-Sep set.**
   - The reference is R-V gate 1's `loyo_rows.jsonl` keys (`2a91bb80…`) minus the declared non-finite set
     {(13, 2024, miami, 2024-08-31)}.
   - The run recomputes the keys it drops on the Aug-Sep frame for a non-finite F or current_temp. That list must
     equal the declared set exactly: one row, the one named. A count of 0, a count of 2 or more, or a different
     row is VOID.
   - The read (a) exclusion count on that set must equal the length of the list.
   - The declared key must be in gate 1's file. No row may be missing or extra against the reduced reference.
   - The PRIMARY Oct-Dec set and the (b) set keep RV-C1's exact-equality control unchanged.
2. **Control 7, determinism (new).**
   - Each of c1a's `rows_a_octdec.jsonl`, `rows_a_augsep.jsonl` and `rows_b.jsonl` must have the sha256 listed in
     §1.
   - Only hashes are compared, and no score is read. A mismatch is VOID.
   - The control runs with the others, before any summary.
3. **The Oct-Dec manifest is bound** at `3c6cca736b72503efcdcdf00769143340b779091464a2b8be384f00c386cac97`. It
   is the fetch RV-C1 used: 165 files, 0 merge conflicts.

Nothing else changes from RV-C1. That covers:
- the arms, frames, folds, fetch window and inputs;
- gates 1a and 1b, which STOP;
- controls 1 and 3-6 and their tolerances;
- the decision rule: (a) is an adopt-candidate iff UB < 0 on the PRIMARY keys, (b) iff UB < 0, and the Aug-Sep
  read is reported only;
- §5 of RV-C1 (what follows).

## 3. What byte reproducibility rests on (fixed in code before this hash)

- **Row content.** The seeded fits are fixed:
  - HGB uses `random_state=42` and `early_stopping=False`.
  - The folds, row order and arm order are fixed: years sorted, then markets sorted, and the scored sets in a
    fixed order.
- **Serialisation.** Rows are written with `json.dumps(sort_keys=True)`, one per line, in text mode on the same
  host.
  - They carry no timestamp, path, pid or random id.
  - The audit file carries paths and environment, and it is not under control 7.
- **Thread count.** This was the one unpinned input.
  - RV-C1 ran with `OMP_NUM_THREADS`, `MKL_NUM_THREADS` and `OPENBLAS_NUM_THREADS` = 10, inherited from the
    lane's launcher. The wrapper does not set them.
  - A different count can change the order of floating-point reductions.
  - RV-C1a therefore refuses to start unless all three equal 10, and it records them in the audit
    (`rv_c1a_threads`).
- **Same interpreter and libraries.** The run uses the same venv and the same host as RV-C1. The module's sha is
  recorded in the audit, as before.
- **Evidence it holds.** In RV-C1, controls 5 and 6 reproduced rows from two earlier, separate runs (C10's and
  SM-H's) with a maximum difference of 0.0. This is value equality, not byte equality. Control 7 is the byte test.

## 4. The run

- One queued run of `rv-c1a` through `workstation_heavy.ps1 -Queue`, write-once, into the new empty directory
  `C:\t\l2\rv\c1a\`. It runs only after master confirms the tip, shas and row 54.
- Its inputs are RV-C1's, with the Oct-Dec manifest bound as in §2.
- Any failed control is VOID, and every number seen is disclosed.

## 5. Outputs

In `C:\t\l2\rv\c1a\`:
- `rvc1a_audit.json`
- `rows_a_octdec.jsonl`, `rows_a_augsep.jsonl`, `rows_b.jsonl`
