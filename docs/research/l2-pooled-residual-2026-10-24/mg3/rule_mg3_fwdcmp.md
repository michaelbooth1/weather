# Rule FWD-CMP (ledger row 67): an Oct-Dec-only P3d_H against the rebuilt Aug-Dec P3d_H, inside MG-3's bound 07-12 blend (item 341)

Lane L3, 2026-10-27. Master ruled on 2026-10-27, relayed by the coordinator. R-ODC (row 65, L8) runs as declared,
labelled "vs the Aug-Sep-centred frozen blend (item 341)". The re-scoped comparison from proposal
`9bde9b0de6f2096451cba3ad673143bc98f5e94e6a0d7f6f94a0ac6b5dccc3bf` §6 becomes this new pre-registered row, inside
item 341's shared LOYO.

This rule is written and pushed before any fit. Row 67 is written PENDING before the run.

This is history-only development evidence with no edge claim:

- No 2026 row is trained on or scored.
- Nothing dated after 2026-09-29 is read.
- A pass promotes nothing on its own. It earns only a separately pre-registered forward test (ruling R10).

## 1. Question

At Oct-Dec 07-12, inside the blend MG-3 would actually serve (SM-L6 plus RF-2 weights), does a P3d_H fitted on Oct-Dec
rows only beat the P3d_H fitted on Aug-Dec rows (FORWARD_CENTRES, FWD-1)?

Prior evidence points both ways:

| Row | Comparison | Result | Outcome |
| --- | --- | --- | --- |
| 50 (C10-sel, MG-2 13-16) | forward Aug-Dec P3d_N vs season-only | +0.00356 [+0.00185, +0.00523] | forward kept |
| 51 (SMH-1, MG-3 13-15) | Oct-Dec-only P3d_H vs forward | −0.01273 [−0.01625, −0.00936] | season-only won |

## 2. Arms (identical rows, folds and support)

- **COMP′.** This is FWD-1 §5 exactly:
  - the rebuilt Aug-Dec specification (`rule_mg3_p3dh_state_fwd1.md` §1);
  - blocked LOYO over 2021-25 on all nine FORWARD_CENTRES' rows;
  - the three-corpus HRRR union under the per-(season, year) coverage gate.
  - Its P3d_H fold distributions are the ones FWD-1 §5 produces, reused and not refitted.
- **G1′.** The same specification and code path:
  - `RK_ARMS["P3d_H"]`, `_rung_entry`, `MEAN_HGB_PARAMS`, `bias_by` season;
  - conversion disabled, RN-1, NBM `1ae4bf52…`.
  The **only** change is the training rows: the five Oct-Dec centres (10-10, 10-25, 11-09, 11-24, 12-09), blocked
  LOYO over 2021-25. This is R-ODC's G1 fit specification. The fits are made here, and nothing is read from R-ODC's
  outputs.
- **Blend for both arms.**
  - Blend = w_h · P3d_H + (1 − w_h) · SM-L6, bucket by bucket, with the MG-1 fallback and rule-4 floor (FWD-1 §5).
  - SM-L6 is the held-out-year vector from row 46 `loyo_vectors.parquet` `0fde7553…`.
  - w_h are the RF-2 weights (FWD-1 §4). They were fitted for the Aug-Dec state, and G1′ uses them unchanged (a
    disclosed asymmetry, because no weight is refitted for G1′).
- **Support.**
  - Both arms are scored on FWD-1 §5's per-fold Oct-Dec support: `fold_support` over the four training years'
    Oct-Dec labels, hours 07-12.
  - Edges are open (`open_edges` / `edge_brier`, R-ODC env `701b7bb5d…`).
  - The run refuses if the two arms' supports differ in any fold.
- **No-cycle keys** keep NaN extras on both arms. Counts are reported, along with the statistic recomputed with
  them dropped. That recomputation is never a gate.

## 3. One gate

- **Statistic.** dR = mean_cell(Brier_G1′ − Brier_COMP′) / mean_cell(Brier_COMP′).
  - Cells are (local_date, market), pooled over h07-12, Oct-Dec 2021-25 held-out rows, and the 11 R0 markets.
  - Brier is the multi-bucket Brier (Σ p_k² − 2 p_y + 1).
  - The interval is date-clustered (`dev_scorecard.ratio_interval` with `_date_weights`), 2,000 draws, seed
    20261027.
  - This is R-ODC's gate-1 construction with COMP′ in place of COMP, so the two readings sit on one scale.
- **PASS** if the upper 95% bound of dR is below 0.
- **Reported, never gating:**
  - the 10 MG3-DC-1 markets;
  - the 5 primary markets;
  - each hour, each held-out year and each month;
  - the absolute Brier difference;
  - the no-cycle-dropped sensitivity;
  - support edge counts.
- **Effect.**
  - **Within MG3-DC-1: none.** MG-3's candidate is fixed by FWD-1 and the amended §2.2a before MG3_D0. This row
    neither re-selects nor rebinds it.
  - **On a PASS:** history evidence for a season-only 07-12 P3d_H. It may be proposed for a separately
    pre-registered forward test after MG3-DC-1's look.
  - **On a FAIL:** the verdict reads "Oct-Dec-only P3d_H does not beat the Aug-Dec forward P3d_H inside the bound
    blend at Oct-Dec 07-12".

## 4. Power (stated up front)

- **Design.** 11 markets × about 75 dates × 5 years × 6 hours ≈ 24,750 rows, in 375 date clusters.
- **Estimate.** MDE80 ≈ 0.0067 on the dR scale. This is R-ODC's estimate, extrapolated from X41's blend interval.
- **Caveat.** That interval was measured on the Aug-Sep-centred blend. Two arms that share a blend partner and
  weights should differ less, so the paired SE is expected to be smaller. This is not assumed.
- **After the run.** The realised SE and MDE80 are reported.
- **A null** is reported as a null at this power, never as evidence of no effect.

## 5. Selection and dependence (disclosed)

- **Shared folds.** COMP′ and the §2.2a drop check (`clarification_mg3_dc1_fwd1.md` §1) use the same LOYO folds.
  This row is read only after the drop check has been computed and recorded. It cannot change the drop check.
- **Fresh data.** The Oct-Dec 2021-25 rows are not fresh, for three reasons:
  - they were read by X13;
  - they were read by row 46;
  - R-ODC reads them concurrently.
  No column, centre or hyperparameter is chosen on them here.
- **Multiplicity.** This is a candidate row (type K), and it counts toward the edge-test multiplicity denominator.

## 6. Order, mechanics, limits

- **Order.** These must all be done before this row runs:
  - FWD-1 pushed and reviewed by master;
  - the 2021-23 seal;
  - FWD-1 §3.1-§3.3 and §4 (RF-2 exists);
  - FWD-1 §5 and the drop check recorded.
  Then G1′'s folds run, then this gate.
- **How it runs.** Once, serially, through `workstation_heavy.ps1 -Queue`.
- **Outputs.** `C:\t\l3\mg3fwd\fwdcmp\`, write-once:
  - rows;
  - support per fold;
  - the summary and the gate verdict.
- **Limits.**
  - Data ≤ 2026-09-29.
  - No paid data and no new dependency.
  - No change to MG-2, B, R-ODC or L8's branch.
