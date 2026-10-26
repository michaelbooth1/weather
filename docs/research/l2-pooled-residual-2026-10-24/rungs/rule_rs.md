# L2 rung R-S pre-registration: NBM's own spread as a scale-model input (07-12 and 13-16)

Written 2026-10-26, **before any R-S fit**. No R-S row has been fitted, emitted or joined to an outcome, label, price or
market row.

- **Authority:** the coordinator's YES to the item-3 lever on 2026-10-26, under conditions 1-4 (quoted where used).
  - Inventory row 9: "day-specific sharpness information".
  - GEFS member spread is excluded because L15's R-Q covers it.
- **Kill-scope ruling:** master R9 (10-25). Spread information is allowed under its own rule and full ladder. There is
  no global sharpening, and the floor is never weakened.
- **Evidence class:** development evidence only. No edge claim.
- **Data limits:**
  - Nothing dated after 2026-09-29 is read, and dev labels are ≤ 2026-09-29 only.
  - Nothing touches MG-2 or L8's branch.
  - The corpora are read only.

## Why

- **Where the loss is.** About two thirds of the 07-12 excess against the market is day-specific sharpness or shape,
  not centre. After re-centring and tempering, +0.0065 remains (R-I, alternative reading).
- **What the P3d arms lack.** Every P3d arm gets its width from an HGB scale model fitted on out-of-fold |errors| over
  the mean model's features X. X carries the NBM mean (`fh`), but no NBM spread.
  - L6 and MG-1 use v2_stddev only as sigma = max(v2_stddev, 1).
  - HRRR–NBM disagreement already reaches P3d_H's scale model through `k_gap`.
  - NBM's own probabilistic spread is therefore the one spread source missing from every P3d arm.
- **Prior.** The prior evidence is weak but *blind*, not null: the own-information dispersion screen had power of
  about 0.11 (EF §1e).

## The one change (condition 1: SCALE MODEL ONLY)

**Two columns are added to the scale HGB's feature matrix only:**
- `nbm_sd`, the NBM probabilistic-TMAX standard deviation;
- `nbm_qw` = p90 − p10, in °F.

**The mean model is unchanged** (OLS + mean HGB, same X, same seeds). Each arm's mean prediction must therefore equal
its base arm's exactly. That is control C-mean below.

**Sources (point-in-time, matched to the anchor cycle):**

| Half | `nbm_sd` | `nbm_qw` | Source |
| --- | --- | --- | --- |
| Training 2021-25 | `sd` of the L9 row that `nbm_at_cutoff` selects for the anchor `fh` (same cycle, same LastModified rule) | `p90 − p10` of that row | L9 corpus `C:\t\l9\nbm_corpus\nbm_pit_corpus_rows.jsonl`, sha `1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd` |
| Dev / serve | captured `v2_stddev`, on the rows where `usable_v2_mean` is finite (the same usability mask as the anchor) | captured `v2_p90 − v2_p10` | layout `C:\swarm\v3layout` (manifest `4d53fdbdc551…`) |

- **Missing values.** A missing value is NaN, which the HGB handles natively. Nothing is imputed.

**Unchanged, checked in code (condition 4).** The run is refused if any of these differ:

| Item | Pinned value |
| --- | --- |
| `predictive_distribution` source (floor censoring at the observed running max; 2% climatology mix) | sha256 `ae029eda4e4f563dfeaaf21b3d014f19c05116b2697f7d6d4d0dba8a62112fbb` |
| `FLOOR_MIX_CLIM` | 0.02 |
| `MIN_SCALE` | 0.5 |
| `KERNEL_BANDWIDTH` | 0.25 |
| `SCALE_HGB_PARAMS` | max_iter 100, learning_rate 0.05, max_leaf_nodes 7, min_samples_leaf 40, early_stopping False, random_state 42 |
| Dev scorecard code (rule-4 floor mask and served fallback) | sha256 `f69071ac5612f022ade56ada764f813c28da79cd0265848c58041115439005c5`, as R-R |

## Arms (condition 2: one primary per window, declared before any fit)

| Window | PRIMARY (S arm vs its base) | Base | Base inputs, as fitted |
| --- | --- | --- | --- |
| 07-12 | **P3d_H_S − P3d_H**, the P3d half of blend_l6_H | P3d_H (R-R) | R-R: RN-1, the 07-12 HRRR corpus and R-R's emit path |
| 13-16 | **P3d_N_fix_S − P3d_N_fix** | P3d_N_fix (R-H/R-J/R-K base) | NBM only |

**Secondary arms** (reported only; they can never pass or rescue a gate):
- blend_l6_HS, R-R's walk-forward blend with P3d_H_S in place of P3d_H, using the unchanged `blend_weight` and
  BLEND_FIT_FIRST 2026-08-01;
- P3d_N_fix_S at 07-12;
- B arms, unaffected: their scale is constant.

## Gates (in order; per window; each failure stops that window)

### Gate 1: parity, outcome-free (condition 3)

**1a, training.** On the h07-16 training rows that have an anchor `fh`:
- `nbm_sd` and `nbm_qw` must be present on ≥ 0.95 of them;
- the values must be in range (`nbm_sd` in [0, 30] °F; `nbm_qw` in [0, 60] °F).

**1b, dev (before any dev fit is scored).** For each dev snapshot at h07-16 whose captured v2 is usable, the captured
`v2_stddev`, `v2_p10` and `v2_p90` are compared with the dev NBP corpus row for the same (market, target date, cycle =
the captured `v2_cycle_key` cycle). The dev corpus is `C:\t\l3\analogue\nbm2026\corpus\nbm_pit_corpus_rows.jsonl`,
sha `85746b7a560116f632436b24f268938a0a4ec47bf6d748aacba6e0abef257727`.
- **Match:** |Δ| ≤ 1e-6 °F. The values are integer °F in both sources.
- **PASS:** match share ≥ **0.98** for each of the three variables, in each window separately.
- **Stop rule:** below the threshold, the rung stops as "parity failed". This is not a kill.

Labels are not read in gate 1.

### Guard G-s (no global sharpening; before gate 2 is read)

- On each window's training OOF rows, compute s_new/s_old: the scale model with the two columns over the scale model
  without them, on the same rows and the same OOF errors.
- **The median must lie in [0.95, 1.05].** Outside that, the rung stops for that window as "global width shift". This
  is not a kill, and no rescaled variant follows.
- The mean ratio and the p10/p90 of the ratio are reported.

### Control C-mean (refused otherwise)

The S arm's mean predictions equal its base arm's (max |Δ| = 0) on every LOYO row and every dev row.

### Gate 2: LOYO 2021-25 (Aug-Sep), S beats base

- **Statistic:** pooled window mean of Brier(S) − Brier(base) per row, with a date-clustered bootstrap (2,000 draws,
  seed 20261024), on rows both arms cover.
- **PASS** if the upper 95% bound is below 0.
- **Control (refused otherwise):** the base arm's LOYO rows reproduce exactly:
  - 07-12: R-R's `C:\t\l2\rungr\loyo\loyo_rows.jsonl`, sha `170c61e36d0b4559a91389e01138d622bbccdc00d2091b8a80a21b8eaf7e383e`
    (P3d_H rows);
  - 13-16: R-K's `C:\t\l2\rungk\loyo\loyo_rows.jsonl`, sha `bb0bf4943b7105b3f0ded1ec327c80bbdc54d9cbcc657cd10bf50d49eb761ee3`
    (P3d_N_fix rows).
- **Reported:** each hour, and each market.

### Gate 3: dev 2026-08-01..09-29, S beats base

- **Statistic:** dR = R(S) − R(base), ALL markets, the window's hours, on snapshots covered by both arms, with
  date-clustered 95% intervals (2,000 draws, seed 20260921). Dev scored dates are 08-15..09-29, as in R-R.
- **PASS** if the upper bound is below 0.
- **Controls (refused otherwise):**
  - The base dev files are byte-identical:
    - 07-12 P3d_H `a2dc30e2b0790ad4cf4ed167c329c00a6c87d4245fb1d6a55d0f80ffdfc14f3d`;
    - 13-16 P3d_N_fix `abc4350724fe42a5d2423dcf5dd3f1c1b06dcea4799cb0d297bd6de465096109`.
  - The MG-1 07-12 control is 0.012.
  - C-mean holds.

### Gate 4: against the incumbent (read only after gate 3 passes; it drafts, never applies)

- **07-12:** blend_l6_HS − L6 on gate 3's statistic, read as WIN, HARM or NULL exactly as R-R's gate 4. Also reported:
  blend_l6_HS − blend_l6_H (the spread increment inside MG-3's 07-12 arm).
- **13-16:** P3d_N_fix_S against MG-2's as-of-capture post-13 arm, on R-K's gate-4 statistic.
- **On a WIN:** L2 drafts, but does not apply, a Clarification and a parity addendum. The forward serve path needs the
  captured v2 quantiles in MG-2's bundle, plus the §b.0 neutral-module prerequisite.

### Reported only (never a gate)

- Per hour and per market.
- Calibration: PIT and coverage of the 50/80/90% central bands, S vs base.
- Sharpness: the mean predictive SD.
- The share of rows where `nbm_sd` < 1 °F (the MG-1 floor region).
- The G-s ratio distribution.

## PRE-REGISTERED KILL

If gate 2 or gate 3 fails in a window, **NBM's own spread (`nbm_sd`, p90 − p10) is closed as a scale-model input for
that window's NBM-anchored P3d arms.**
- No other transform, column, bandwidth or scale-model variant of NBM spread is run there under any rung name.
- The kill is recorded in RETRACTED_AND_FALSE_LEADS and the dev-window ledger.
- A mean-model variant is a separate, later rule (condition 1). It is not a rescue.

A gate 1 failure, a G-s stop, a refused control or a missing corpus stops the window without a kill.

**NBS TXNSD is not opened** unless R-S passes in a window, and a reason it is not redundant with NBP `sd` (the same
NBM) is named first.

## Outputs

- `C:\t\l2\rungs\loyo\`, `C:\t\l2\rungs\emit\` and `C:\t\l2\rungs\score\rs_score.json`.
- This rule, its `.sha256` sidecar and the summary go in `docs/research/l2-pooled-residual-2026-10-24/rungs/`.
- The code records this rule's sha256 (`RS_RULE_SHA256`) before any R-S row exists.
- Heavy steps go through `workstation_heavy.ps1` (-Queue, OMP 10), after items 1-2 on the queue.
