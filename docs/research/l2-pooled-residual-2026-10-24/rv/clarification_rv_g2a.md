# R-V clarification RV-G2a: gate 2 for read (a), P3d_V_fwd vs the served c6cc39f7 at 13-16 (DRAFT for master)

- **Status: DRAFT for master's review.** Lane L2, 2026-10-27. Not in force; nothing runs from it until master
  accepts it and the coordinator allocates its dev-window ledger row.
- **Amends** R-V gate 2 (`rule_rv.md`, `b0cf2a03224d2581f96c77b801dd5244353ca1f2025ab0802940dcf65e88e818`) for
  read (a) only, as RV-C1 §5 (`db11d8d2e1443143816302cbe16b1f065401ca4b8aa3d8ca61122ba1aaef3ba5`) requires.
  RV-C1a (`739c6a462e77f1a25d3ad47cceafa77a1b7200046f8761cbad5d27aa09343f32`) is unchanged.
- **Hashed before any dev row is read.** The sha256 of the accepted text is recorded in code and in the ledger row
  before the dev fetch or any dev emission.

## 0. What a result here can and cannot do (pre-declared)

- **A gate-2 PASS is evidence for a CAPTURE PROPOSAL only.** It is never a binding change to MG-2 or Rule B-1.
  B binds without MOS on 2026-10-29, whatever this read gives.
- **MG-3.** Any MG-3 adoption of a MOS/NBE column needs, before MG-3's D0:
  - a dated MG3-DC-1 clarification that names it; and
  - forward MOS/NBE capture live and parity-tested (rule_rv.md "Forward parity").
  If either cannot be in place by D0, R-V moves to the next model after MG-3. No MG-3 file changes on this read.
- **A gate-2 FAIL** closes MOS/NBE day-max as a 13-16 input on the served P3d_N arm (rule_rv.md "PRE-REGISTERED
  KILL", RV-C1 §5). The dev input checks (§3) STOP rather than kill.
- Dev evidence is selection evidence, not an edge claim.

## 1. Disclosure (what is known before this read)

- **RV-C1a (ledger row 54), history only.** (a) PRIMARY `P3d_V_fwd − P3d_N_fwd | 13-16 | brier`, Oct-Dec
  2021-25: −0.00338 [−0.00509, −0.00164], 16,496 rows, 375 dates; adopt-candidate. The Aug-Sep 2021-25
  reported-only read: −0.00572 [−0.00791, −0.00357].
- **R-V gate 1 (row 43):** `P3d_V − P3d_N_fix` 13-16 −0.00447 [−0.00651, −0.00255] (see RV-C1 §1).
- **Not seen by L2:** any 2026 MOS/NBE value (the A-IEM-2 copy at `C:\swarm\data\iem\mos` is not read), any 2026
  `v_gap`, and any P3d_V_fwd dev distribution or score. L2 has not scored `c6cc39f7` on the 2026 dev window in
  any run of its own. Master or the coordinator confirms from the ledger whether any other lane has, and that
  result is listed here before hashing.

## 2. Data

- **Dev MOS/NBE fetch.** `rv_fetch` unchanged, with `rv_fetch_windows([2026])`: runtimes 2026-07-31 00:00Z ..
  2026-09-29 23:59Z (nothing later; a later year refuses). Models GFS, NAM and NBE; the 11 R0 stations; one
  connection, ≥ 8 s spacing. Output `C:\t\l2\rv\mos_dev2026\` with its own manifest; the manifest sha256 is
  recorded in the audit before any dev emission.
- **The column** is rule_rv.md's exactly, including the stated NBE deviation (the 2026 archive's 00Z run). On dev
  the anchor is the captured `usable_v2_mean`, as rule_rv.md and R-K's `k_gap`. Training keeps L9's `fh`.
- **Dev rows.** R-K's dev population at h13-16: the scorecard layout `C:\swarm\v3layout`, replay inputs
  `replay-inputs-le0929`, folds 2026-08-01..09-29, scored 08-15..09-29, as `rung_k_score`. Both arms are scored on
  the same snapshots (covered by both arms).

## 3. Dev input checks (inputs only; STOP, not a kill)

- `mos_x` finite on ≥ 0.95 of the dev rows h13-16;
- |mean dev `v_gap` − mean training `v_gap`| ≤ 1.5 °F, the training mean taken on the forward frame of §4;
- reported per source: the share of dev rows whose selected run exists and carries the D-max field.

## 4. Arms

- **Comparator: P3d_N_served** = the served state `c6cc39f7…` (`C:\t\l2\forward\state\p3d_n_state.pkl`, loaded
  only after its sha matches), served by `state_distribution`, unchanged. It is trained on 2021-25 only, so the
  2026 dev window is out of sample for it.
- **Candidate: P3d_V_fwd frozen.** One all-years fit, frozen before any dev emission:
  - training frame: RV-C1's (a) frame, `forward_training_frame(C:\t\l2\records)`, all 9 FORWARD_CENTRES, Aug-Dec
    2021-25, hours 13-16, L9 NBM, `v_gap` from the merged Aug-Sep (`1e6e6b3d…`) and Oct-Dec (`3c6cca73…`)
    corpora;
  - the same builder as RV-C1 (`rv_c1_v_entry`, `rv_c1_v_shell`, `extra_hgb = ("v_gap",)`), served by
    `mg3_state_distribution` through the `c6cc39f7` shell;
  - its frozen file's sha256 is recorded in the audit before the dev emission.
- Nothing else is fitted on 2026 rows. No dev fold refit.

## 5. Statistic and decision

- **Statistic (rule_rv.md gate 2, unchanged):** dR = mean_cell(Brier_P3d_V_fwd − Brier_P3d_N_served) /
  mean_cell(Brier_market), ALL markets, h13-16 pooled, date-clustered 95% interval, 2,000 draws, seed 20260921.
- **PASS iff the upper bound is below 0.** Nothing else enters the decision.
- **Reported only:** the raw Brier difference; each hour, 13-14 and 15-16; per market; log loss; each arm's R vs
  market.

## 6. Controls (any failure is VOID; no score is summarised)

1. **Inputs.** `c6cc39f7`, the NBM corpus `1ae4bf52…`, both history MOS manifests, the dev manifest (recorded),
   the layout and replay root all match; no merge conflict between corpora.
2. **V off.** The P3d_V_fwd builder with `extra_hgb = ()`, refit on the same frame and served through the shell
   by `mg3_state_distribution`, equals `c6cc39f7`'s `state_distribution` on every dev row to 1e-9 (RV-C1 control
   4 on dev).
3. **Pipeline (rule_rv.md gate 2, unchanged):** P3d_N_fix at 13-16 on the same harness is byte-identical to R-H's
   (`abc43507…`), and MG-1's 07-12 control gives 0.012.
4. **Key identity.** Both arms' scored keys are identical; counts are reported by hour and market.
5. **Determinism.** OMP/MKL/OPENBLAS pinned at 10 and recorded, as RV-C1a.

## 7. Mechanics

- Code on branch `claude/rv-c1-20261027`; the constant holding this file's sha is added before any dev row exists.
- One dev fetch (network, inputs only), then one queued run through `workstation_heavy.ps1 -Queue`, shared with
  RV-G2b if both are accepted (shared fetch and population; separate decisions). Outputs write-once in
  `C:\t\l2\rv\g2\`.
- Ledger row: allocated by the coordinator, written PENDING with this file's sha before the fetch.
