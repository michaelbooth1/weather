# P3d_N vs P3d_N_fix diagnostic (lane L2), 2026-10-25

**No MG-2 gate flips under the fix.** This covers clause (d), the pick's eligibility conditions, G1 and G2 (all
read on dev). The dev evidence for picking P3d_N over A_N survives.

This is descriptive only: no arm and no rule. It uses dev rows up to 2026-09-29 only, and every number is selection
evidence. Code: `pooled_residual_model p3dn-diag-emit` and `p3dn-diag-score`. Output shas are at the end.

- **P3d_N** is `721ae2cd…`: the last replay snapshot captured in [h:00, h+1:00), with raw METAR °F.
- **P3d_N_fix** is the latest snapshot captured at or before the row's own capture, converted to WU whole °F
  (half-up).
- **Both use the same fitted model.**
  - Re-emitted with the same fits on the old inputs, the result equals `721ae2cd…` on all 18,573 rows at h13-16
    (max |dp| 0.0).
  - On the fixed inputs it equals R-H's `abc43507…` (max |dp| 0.0).
  - So the whole gap comes from the inputs.

## 1. Input diff (h13-14: 9,332 rows; h15-16: 9,241 rows)

- **Only three feature columns differ:** `F`, `x_high_so_far` and `x_current_temp`. `F` and `x_high_so_far` are
  the same value; `F` is also the floor. `fh`, the day-of-year terms, lat/lon/elev, `market_code` and `hour` are
  identical on every row.

| h13-14 | Rows |
| --- | --- |
| Any differing column | 8,418 (90%) |
| `F` / `x_high_so_far` differ | 8,260 |
| `x_current_temp` differs | 8,257 |
| Differ because of the snapshot chosen (not the rounding) | 147 (high), 172 (current) |
| P3d_N's snapshot captured **after** the row's capture | 8,077 (median 27.6 min, p90 51 min, max 59.9 min) |
| P3d_N used a METAR row received after capture (more rows, newer latest observation) | 180 |
| Any observation used that was observed after capture | **0** (every observation is at or before h:00, which is at or before capture) |

- **Magnitude:**
  - The typical difference is rounding: the median |diff| is 0.06 °F (p90 0.08 °F), between T-group tenths and
    WU whole °F.
  - The rows that differ because of the snapshot chosen carry the large differences, up to 17.9 °F (high) and
    19.9 °F (current).
- **Hours:**
  - h13: 4,006 high / 3,998 current differ, 3,938 snapshots after capture.
  - h14: 4,254 / 4,259 differ, 4,139 after capture.
  - h15-16 shows the same pattern.
- **This is look-ahead on receipt, not on observation.** No value is observed after the snapshot's capture time,
  but about 2% of rows use a report first received after capture.

## 2. Attribution of the +0.0107 (dR, date-clustered, 7,000 identical covered snapshots at 13-14)

The gap is P3d_N_fix − P3d_N = **+0.0107 [+0.0016, +0.0210]** (crossed [−0.0085, +0.0365]), reproduced exactly.

Method:
- Each variant's inputs are taken from the non-fix side as named, with the rest held at the fix.
- The share of the gap is (fix − variant) / (fix − P3d_N), with the denominator's sign kept on every draw.

| Variant | fix − variant (dR) | Share of gap [95%] |
| --- | --- | --- |
| **Column group high_so_far (F, x_high_so_far)** | +0.0084 [+0.0008, +0.0166] | **0.79 [0.23, 1.44]** |
| Column group current_temp | +0.0029 [−0.0007, +0.0067] | 0.27 [−0.13, 0.98] |
| Interaction | | −0.06 [−0.90, 0.36] |
| **Mechanism: snapshot selection only** (P3d_N's snapshot, WU rounding) | +0.0103 [+0.0065, +0.0149] | **0.97 [0.44, 4.11]** |
| Mechanism: rounding only (as-of snapshot, raw °F) | +0.0001 [−0.0083, +0.0093] | 0.01 [−3.08, 0.52] |

Note: 22 of the 2,000 draws have a denominator ≤ 0, which is why some share intervals are wide.

- **13-16:** the gap is +0.0139 [+0.0033, +0.0253]. high_so_far explains 0.95 [0.66, 1.59] and selection 1.35
  [0.76, 4.33]. Rounding slightly favours the fix (−0.0044).
- **Reading:** the gap is P3d_N's receipt look-ahead, which acts mostly through high_so_far (both the feature and
  the floor). The WU rounding costs nothing.

## 3. MG-2 composite vs MG-1 (Brier, MG-2's scorer; date-clustered `w_date`, crossed beside)

- **The composite:** the L6 stack before 13 (part `07a67425…`), then P3d_N or P3d_N_fix at 13-16, with MG-1
  wherever the post-13 vector is unusable.
- **Controls:**
  - The composite rebuilt from its parts equals MG-2's own `control_v3/mg2_vectors.parquet` (`8f3e5895…`) at 00-16,
    with max abs 1.1e-16.
  - The arm-A composite reproduces `dev_composite.json` at 13-16: −0.010371 against −0.01037.
- **Rows:** P3d_N_fix is used on 13,970 snapshots at 13-16 and MG-1 on 14 (2 more than with P3d_N).

| Block | Original (P3d_N) | With the fix (P3d_N_fix) | Fix − original |
| --- | --- | --- | --- |
| 00-16 (G1, margin +0.0010) | −0.0049 [−0.0065, −0.0034] | −0.0048 [−0.0065, −0.0033] | +0.0001 [+0.0000, +0.0002] |
| 00-12 | −0.0018 [−0.0027, −0.0008] | identical | 0 |
| 07-12 | −0.0038 [−0.0058, −0.0018] | identical | 0 |
| **13-16 (G2)** | −0.0155 [−0.0195, −0.0117] | **−0.0151 [−0.0192, −0.0113]** | +0.0004 [+0.0001, +0.0007] |
| 13-14 | −0.0083 [−0.0116, −0.0051] | −0.0079 [−0.0112, −0.0048] | +0.0004 [+0.0001, +0.0008] |
| 15-16 | −0.0225 [−0.0274, −0.0181] | −0.0222 [−0.0272, −0.0176] | +0.0003 [−0.0001, +0.0008] |
| h13 / h14 | −0.0065 / −0.0099 | −0.0061 [−0.0093, −0.0029] / −0.0096 [−0.0133, −0.0062] | |
| h15 / h16 | −0.0177 / −0.0274 | −0.0175 / −0.0270 | |

- **Crossed intervals with the fix:** 00-16 [−0.0069, −0.0028]; 13-16 [−0.0201, −0.0100].
- **Dev reading:**
  - G1 and G2 both pass in both versions, and the dev stop condition (13-16 upper bound ≥ 0) is not met.
  - The fix costs 0.0004 Brier at 13-16, which is about 3% of the composite's 13-16 gain.
  - Unlike arm A, P3d_N has a dev gain at h13 in both versions.

## 4. The MG-2 serve path (L8 `claude/mg2-composite-binding-v2-20261025`)

**Ancestry.** The serve path at 1a3a3864f is the parent of L8's tip 710f0c672 (= origin). The tip changes only
`rule.md` (ledger row numbers), so the code is the same in both.

**MG-2 is never served live.** It is a captured-input replay:
- Rule §1 says nothing in serving, capture, release or Scheduler imports it.
- `mg2_composite.py:102` (`_refuse_production_import`) enforces that.

**The forward gate path is not capture-time.** It is `last_in_hour`:
- `mg2_composite.py:845`: `emit` calls `post_records(state, snaps, replay_root, first, last)`, whose default
  `inputs="last_in_hour"` is at `:782`.
- `mg2_p3d_n.py:416` (`emit_rows`, default `last_in_hour`) leads to `:449` (`scan_replay`).
- `:381-383`: `chosen[local.hour] = ...` keeps the last snapshot captured in [h:00, h+1:00).
- `:478` gives every row of that hour this one record.
- `:355-366` (`_observations`): only rows observed at or before h:00 are used, so there is no observation
  look-ahead.
- `mg2_composite.py:852` writes these vectors as `mg2_vectors.parquet`.
- `:935` makes `score` refuse any other file, and `:956` scores it against MG-1.
- The bound forward state (frozen record, `late_report.rule: last_in_hour`) is the same rule. Rule §8 C3-binding
  and C4 say so explicitly.

**The as-of-capture path is capture-time by construction**, but it is not the gate:
- `mg2_p3d_n.py:486` (`as_of_capture(indexes[...], at_local)`) reads the latest snapshot captured at or before
  the row's capture.
- `mg2_composite.py:862` computes it only on forward rows, and `:435` refuses dev rows.
- C4 makes it PRIMARY for market comparisons and DESCRIPTIVE for the MG-1 gate.

**The forward state converts to WU whole °F** (`mg2_p3d_n.py:283-284`; record `conversion:
wu_whole_f_tgroup:half_up`). So the forward gate arm corresponds to this diagnostic's "selection only" variant:
P3d_N's snapshot with WU rounding. On dev that variant is the one that captures the whole look-ahead gain.

**The gate is symmetric in rows but not in inputs.** MG-1 is capture-time. The look-ahead's dev size against MG-1 is
the +0.0004 Brier in section 3. P3d_N's forward state is a different fit (Aug-Dec), which this diagnostic did not
score.

**The pick re-scored** (`dev_pick` logic, rows = A_N ∩ P3d_N at 13-16, seed 20261025):
- **Controls:**
  - 13,958 rows (13,956 also covered by the fix).
  - P3d_N − A_N = −0.155099, the same as the pick.
  - A_N − MG-1 = −0.391544, the same as the pick.

| dR vs A_N | P3d_N (pick) | P3d_N_fix |
| --- | --- | --- |
| Pooled, date-clustered | −0.1551 [−0.2175, −0.0980] | **−0.1413 [−0.2043, −0.0824]** |
| Pooled, crossed | −0.1551 [−0.3296, −0.0305] | −0.1413 [−0.3226, −0.0154] |
| h13 / h14 | −0.1092 / −0.1498 | −0.0991 [−0.1519, −0.0528] / −0.1402 [−0.2177, −0.0695] |
| h15 / h16 | −0.1971 / −0.2804 | −0.1916 [−0.3099, −0.0889] / −0.2450 [−0.4329, −0.0781] |
| Primary 5 (point) | −0.1075 | −0.0878 (date-clustered [−0.1794, +0.0012]) |
| vs MG-1 | −0.5466 | −0.5331 [−0.7093, −0.3842] |
| Conditions 2, 3 and 4, and the tie rule | all hold | **all hold** |

- **The pick survives the fix.**
- **A_N was not fixed.** L3's reader `r0_ols_floor_challenger.py:596-629` (`scan_replay_observations`, the last
  snapshot in the hour) gives A_N the same receipt look-ahead. This comparison is therefore conservative for
  P3d_N_fix.
- **Clause (d)** (A_N − MG-1 upper bound < 0) does not involve P3d_N. It still holds at −0.3915, upper bound
  −0.2488. A capture-time A_N was not built, because that would be a new arm.

## Files

| File | sha256 |
| --- | --- |
| `C:\t\l2\diag\emit\diag_emit_audit.json` | `8323b5d6ef6ee5988037d4f7768d10ed5ae84edc75b4b561245d3fce5d106ee2` |
| `C:\t\l2\diag\emit\diag_inputs.jsonl` (per-row diff) | `51a08c2d531c7f230ca25a947a8545ebb1d4195e4841deed95d192ca1b75b987` |
| `dev_fix` / `dev_orig` | `abc43507…` (= R-H) / `871a0ea4…` |
| `dev_swap_high` / `dev_swap_current` | `bd588782…` / `99fec64f…` |
| `dev_mech_selection` / `dev_mech_rounding` | `fd05faa1…` / `d3ae4383…` |
| `C:\t\l2\diag\score\diag_score.json` | `ceb4b3ac3c37f67a65b281a9ac6f5b1d5900d238e98d63d4b9567ef66da0f19d` |

## Disclosures

1. **The A_N vectors were opened.** `C:\t\l3\dev_n2\dev_nbm_n2_ols_floor.jsonl` (sha256 `066ac73b…`) was read by
   `p3dn-diag-score` for the pick re-score in section 4. The lane's standing rule forbids opening A_N vectors, but
   the coordinator's diagnostic GO asked for this re-score, and master accepted the opening as within that GO.
   `C:\t\mg2\control_refit_armA.json` was not opened.
2. **Two corrupt replay lines were skipped.** The first emit run stopped on a corrupt replay line, and its partial
   output was deleted. The re-run skips such lines, as `dev_emit_rung` does, and counts them as
   `corrupt_replay_line_fix: 2` (both on the fix side). Those 2 rows are absent from every variant.
3. **A 2-test pytest ran directly.** It used `-k "p3dn_diag or rung_j"` with `--basetemp C:\t\l2\pt`, which was
   deleted afterwards. It ran on the workstation, not the capture host, and outside the heavy wrapper. Both tests
   passed. Every emit and score run went through `workstation_heavy.ps1`.
