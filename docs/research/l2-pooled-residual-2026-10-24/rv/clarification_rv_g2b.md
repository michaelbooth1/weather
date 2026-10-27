# R-V clarification RV-G2b: gate 2 for read (b), SM_HV vs the served SM-H at 13-15

- **Status: In force: master accepted 2026-10-27, with the edits recorded here.** Lane L2, 2026-10-27. Nothing
  runs from it until the coordinator confirms the dev MOS fetch.
- **Amends** R-V gate 2 (`rule_rv.md`, `b0cf2a03224d2581f96c77b801dd5244353ca1f2025ab0802940dcf65e88e818`) for
  read (b) only, as RV-C1 §5 (`db11d8d2e1443143816302cbe16b1f065401ca4b8aa3d8ca61122ba1aaef3ba5`) requires.
  RV-C1a (`739c6a462e77f1a25d3ad47cceafa77a1b7200046f8761cbad5d27aa09343f32`) is unchanged.
- **Hashed before any dev row is read.** The sha256 of the accepted text is recorded in code and in the ledger row
  before the dev fetch or any dev emission.

## 0. What a result here can and cannot do (pre-declared)

- **A gate-2 PASS is evidence for a CAPTURE PROPOSAL only.** It is never a binding change to MG-2 or Rule B-1.
  B binds without MOS on 2026-10-29, whatever this read gives.
- **MG-3.** MG-3 binds SM-H `b6bc242a…` at 13-15 (MG3-DC-1). Any MG-3 adoption of SM_HV needs, before MG-3's D0:
  - a dated MG3-DC-1 clarification that names it; and
  - forward MOS/NBE capture live and parity-tested (rule_rv.md "Forward parity").
  If either cannot be in place by D0, R-V moves to the next model after MG-3. No MG-3 file changes on this read.
- **A (b) PASS alone cannot justify MG-3 adoption unless (a) also passes, OR the MG-3 clarification gives its own
  reason** (master, 2026-10-27; (b) is out of season, §2).
- **A gate-2 FAIL** closes MOS/NBE day-max as a 13-15 input on SM-H (rule_rv.md "PRE-REGISTERED KILL", RV-C1 §5).
  The dev input checks (§3) STOP rather than kill.
- Dev evidence is selection evidence, not an edge claim.

## 1. Disclosure (what is known before this read)

- **RV-C1a (ledger row 54), history only.** (b) `SM_HV − SM_H | 13-15 | brier`, Oct-Dec 2021-25: −0.00197
  [−0.00384, −0.00017], 12,372 rows, 375 dates; adopt-candidate.
- **SMH-1:** SM_H − P3d_N_fwd 13-15 −0.01273 [−0.01625, −0.00936] (history).
- **Not seen by L2:** any 2026 MOS/NBE value, any 2026 `v_gap`, any SM_HV dev distribution or score. L2 has not
  scored SM-H `b6bc242a` on the 2026 dev window in any run of its own.
- **Other lanes' 2026 dev contact (master's host log, 2026-10-27; nothing else is logged):**
  - L8's rehearsals `rh0928b` and `rh0928c` ran the MG-2 serve path, `c6cc39f7` included, on 2026-09-28 as a
    reproducibility check. No score was read.
  - The B control receipts `b_control.json` `2ce8f4a7…`, `c67ba81a…` and `17b293a7…` compute B-1's positive
    control on the 2026-07-31..09-29 dev layout. They may contain MG-2-vs-market dev scores that use `c6cc39f7`.
    L2 has not read them and does not open them before the gate-2 run.

## 2. Out-of-season limitation (stated now)

- SM-H and SM_HV are both fitted on Oct-Dec 2021-25 only (season-matched). The only 2026 dev rows allowed are
  Aug-Sep (nothing after 2026-09-29), so this read scores both arms **out of season**.
- It tests whether `v_gap` helps the SM-H fit on 2026 out-of-sample rows, not MG-3's in-season gain. A PASS is
  weaker evidence than read (a)'s; a FAIL still closes as §0 says.

## 3. Data and dev input checks (inputs only; STOP, not a kill)

- **Dev MOS/NBE fetch:** shared with RV-G2a §2 (`C:\t\l2\rv\mos_dev2026\`, runtimes 2026-07-31 00:00Z ..
  2026-09-29 23:59Z, manifest sha recorded). The column and the NBE deviation are rule_rv.md's; the dev anchor is
  the captured `usable_v2_mean`.
- **Dev HRRR:** L13's `C:\t\l13\hrrr_2026dev`, with the SM-H point rule (nearest) and `rk_columns`, as R-K's dev
  emit; shas of its manifest, selections and stations recorded.
- **Dev rows:** R-K's dev population at h13-15 (layout `C:\swarm\v3layout`, replay `replay-inputs-le0929`, folds
  2026-08-01..09-29, scored 08-15..09-29), snapshots covered by both arms.
- **Checks:**
  - `mos_x` finite on ≥ 0.95 of the dev rows h13-15;
  - |mean dev `v_gap` − mean SM-H-frame training `v_gap`| ≤ 1.5 °F;
  - the dev HRRR parity gate of R-K (`rk_parity_training` on dev stats) passes.

## 4. Arms

- **Comparator: SM-H served** = `b6bc242a…`, loaded only by `sm_h_load_state`, served by
  `mg3_state_distribution`, unchanged.
- **Candidate: SM_HV frozen.** One fit with SM-H's freeze path (`sm_h_build_state` on the SM-H frame: Oct-Dec
  2021-25, 13-15, L9 NBM, L13 HRRR with `sm_h_day_filter`), with `extra_hgb = (k_max, k_gap, k_tcdc, v_gap)`,
  v_gap last, `v_gap` from the Oct-Dec corpus `3c6cca73…`. Its sha256 is recorded before the dev emission.
- **San Francisco is OUT of the decision** (master, 2026-10-27): MG-3 serves SF from MG-2's arm at 13-15
  (MG3-DC-1 §2.1). SF is scored and reported separately only. This departs from RV-C1 (b), which kept SF in.

## 5. Statistic and decision

- **Statistic (rule_rv.md gate 2, hours changed to 13-15):** dR = mean_cell(Brier_SM_HV − Brier_SM_H) /
  mean_cell(Brier_market), all markets except san-francisco, h13-15 pooled, date-clustered 95% interval, 2,000
  draws, seed 20260921.
- **PASS iff the upper bound is below 0.** Nothing else enters the decision.
- **Reported only:** the raw Brier difference; each hour; per market (SF separately); log loss; each arm's R vs
  market.

## 6. Controls (any failure is VOID; no score is summarised)

1. **Inputs.** `b6bc242a` (via `sm_h_load_state`), the NBM corpus, the HRRR train and dev files, the Oct-Dec MOS
   manifest `3c6cca73…`, the dev manifest (recorded), the layout and replay root all match.
2. **V off.** SM_HV's builder without `v_gap` (`extra_hgb = (k_max, k_gap, k_tcdc)`), on the same frame, equals
   `b6bc242a`'s served distribution on every dev row to 1e-9 (RV-C1 control 6 on dev).
3. **Pipeline (rule_rv.md gate 2, unchanged):** P3d_N_fix at 13-16 on the same harness is byte-identical to R-H's
   (`abc43507…`), and MG-1's 07-12 control gives 0.012.
4. **Key identity.** Both arms' scored keys are identical; counts are reported by hour and market, with SF's
   rows counted apart from the decision set.
5. **Determinism.** OMP/MKL/OPENBLAS pinned at 10 and recorded, as RV-C1a.

## 7. Mechanics

- Code on branch `claude/rv-c1-20261027`; the constant holding this file's sha is added before any dev row exists.
- Shares RV-G2a's dev fetch and its one queued run if both are accepted (separate decisions). Outputs write-once in
  `C:\t\l2\rv\g2\`.
- Ledger row: allocated by the coordinator, written PENDING with this file's sha before the fetch.
