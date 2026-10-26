# L14 rung R-P pre-registration: NBH remaining-hours maximum as a 13-16 centre shift

Written 2026-10-25 (about 21:00 EDT), before any NBH row has been read.

- **What has not been read:** no NBH row, manifest row or block from L12's `C:\t\l12\nbs_nbh\` or
  `C:\t\l12\nbs_nbh_2026dev\`. Only L12's plan (`C:\t\l12\fetch_plan.md`, sha `22283889…`), its date list and its
  progress log lines were read.
- **What has been seen:** L2's R-H dev distributions were seen as file metadata only (keys of one row), not scored.
- **Authority:** the coordinator's L14 F9 assignment (lever inventory row 7 / flag F9, `C:\t\inv\lever_inventory.md`).
- **Name:** rung R-P. R-N and R-O are not reused.
- **Evidence class:** development evidence only; no edge claim.
- **Data limits:**
  - Nothing dated after 2026-09-29 is read.
  - Nothing touches MG-2, L8's branch or L2's rungs.
  - L12's corpora are read only, and only after L12 reports done with `SHA256SUMS`. The finalised shas are recorded
    in the audit before any row is read.

## Coordination with L2 (R-K, R-L)

**What L2's rules say** (on `claude/rung0712-20261025` @ bdc1ef0f8, read before writing this rule):
- `rungk/rule_rk.md`, sha `21b5dfe1…`: HRRR 13-16, with clarification RK-1.
- `rungl/rule_rl.md`: NBS TXN 07-12.
- R-L's kill states that NBH is not reopened or covered by it.
- R-K's kill covers HRRR only.

**How R-P differs:**
- **Source:** the NBM hourly blend (NBH), not HRRR.
- **Hours:** 13-16, not 07-12.
- **Form:** R-P is a different model form. R-K and R-L add OLS and HGB features. R-P is a two-parameter
  translation of the incumbent arm's own predictive distribution, with the spread unchanged and no per-market
  terms.

**Overlap with R-K:**
- R-P shares R-K's cell (13-16 centre). Lever inventory row 7 says to run the two "in sequence".
- R-P's incumbent is P3d_N_fix and MG-2's post-13 arm, as registered today, whatever R-K finds.
- A combined HRRR+NBH arm is outside this rule.

**Shared machinery:** R-P re-uses L2's R-A arms (B_N, P3d_N_fix) through L2's code, imported and unchanged.

## Precondition: production never captured NBH (disclosed)

- `docs/operations/DATA_LAYER_V2_PLAN.md` item 11: backfillable sources (NBH/NBS/MOS among them) "are not captured
  live".
- NBH was declined for capture on 2026-10-04 (EXHAUSTION_REGISTER S3; DL 10-04).
- Captured snapshots hold only the NBM v2 NBP-derived `usable_v2_mean`.

**Consequences:**
1. **The dev NBH input is not what the capture saw.** It is L12's archive read: the S3 object for the cycle, with
   S3 `LastModified` as the availability instant (L12 plan, PIT caveat). The 10-minute margin below is the only
   latency allowance.
2. **No R-P result can establish train/serve parity, captured-input replay or release binding.** Even a gate 4 WIN
   gives only a drafted proposal. Before any promotion, a forward NBH recorder is needed (the parity plan under
   gate 1), and that is a production capture change (roll-sensitive).
3. **The cycle-coverage ceiling.** L12 fetched cycles 04Z-19Z (fetch plan, Scope). At 13-16 local:
   - Eastern rows run 17Z-20Z, Central 18Z-21Z, Mountain 19Z-22Z and Pacific 20Z-23Z.
   - Cycles land about HH+0:35-1:15.
   - So for later hours the newest *existing* cycle (20Z-22Z) is not in the corpus, and R-P selects 19Z or older.
   - This makes R-P's NBH staler than a live reader's. That biases against R-P and is not a leak.
   - It is reported per market and hour (cycle age), and not repaired here. A 20Z-23Z supplement would need the
     coordinator's word and a new rule.

## Rows, anchor and floor

- **Markets:** R-A's 11 US markets (Toronto is out).
- **Cutoff hours:** h ∈ {13, 14, 15, 16}.
- **Training:** L2's R-A training frame. `dev_training_frame` on `C:\t\l2\records`, with L9's `nbm_at_cutoff`
  attached from `C:\t\l9\nbm_corpus\nbm_pit_corpus_rows.jsonl`, Aug-Sep 2021-25, h13-16. These are exactly R-J's
  and R-K's LOYO rows.
- **Dev:** L2's R-H dev emit `C:\t\l2\rungh\emit1316\`. Its files must match by sha:
  - `dev_B_N.jsonl` `bab9cac728a5b363888278ad66b12e73807b5e0ae0849bcb13f12f5e8139f186`;
  - `dev_P3d_N_fix.jsonl` `abc4350724fe42a5d2423dcf5dd3f1c1b06dcea4799cb0d297bd6de465096109`.
  - Otherwise the run is refused.
- **Anchor A:**
  - in training: the row's L9 `nbm_at_cutoff` mean;
  - on dev: the snapshot's captured `usable_v2_mean`;
  - in both cases, the same value P3d_N_fix consumed.
- **Floor F:** the arm's own high-so-far input (WU whole °F, as of capture).
- **Dev control for A and F:** R-P re-derives A and F per dev snapshot through L2's `rung_inputs`. With those
  inputs, P3d_N_fix's distribution must reproduce R-H's file to within 1e-12 on every snapshot. Otherwise the run
  is refused.

## The feature (pre-committed, exactly one)

**For a row:** market m (station from the registry), local date d, cutoff hour h; t = h:00 local on d. Dev uses
the same t; every scored snapshot is captured at or after h:00.

**Cycle selection:**
- **Candidates:** L12's `nbh` manifest rows for UTC dates d−1, d and d+1 where:
  - the station block `status` is `ok`;
  - the block bytes' sha256 equals the manifest `sha256`;
  - `last_modified` + 10 min ≤ t.
- **Choice:** the newest issue time among the candidates.
- **Missing:** if the newest is older than t − 12 h, the row is missing.

**Parsing:**
- The block bytes are parsed as delivered by `parse_block` from `tools/research/nbm_nbs_nbh_fetch.py` @ 186c42ad4:
  per-column `valid_utc` from the `UTC` row, resolved forward from the header issue time, and `rows["TMP"]` in
  whole °F.
- If the block's issue time disagrees with the manifest cycle, the row is missing.

**Remaining-hours maximum:**
- `f_rem` = max TMP over columns whose valid time, converted to local time on d, lies in [t, 23:00 local on d].
- The row is missing if any hour in that window has no column or a non-numeric TMP.

**Feature:**
- **x = max(f_rem, F) − A**: the NBH-implied day maximum given what has already been observed, measured from the
  NBM anchor.
- Using max(f_rem, F) rather than f_rem alone is fixed here, before data. After the peak, f_rem alone would say
  "cooler" about a day whose high is already in.
- **Missing rows:** the arm is unchanged (δ = 0, whatever (a, b)). They add a constant to the fit criterion and do
  not move the fit.

**Constraints:** no other NBH element (DPT, SKY, WSP, …), window, cycle rule, margin, transform or block statistic
is used.

## Arms

**The shift:**
- **B_P** = B_N translated by δ = a_B,h + b_B,h · x.
- **P3d_P** = P3d_N_fix translated by δ = a_P,h + b_P,h · x.
- There is one (a, b) per arm per cutoff hour: four pairs per arm, pooled over all markets, with no per-market
  term.

**Translation (spread unchanged):**
- **Span:** the market's R-A bucket space (`buckets[market]` from `dev_training_frame`, the observed-label set) is
  not contiguous. The translation therefore works on the contiguous integer span J = [min space, max space], with
  zero mass on integers in J that the arm does not list. Training and dev use the same `buckets[market]`. On dev,
  keys absent from R-H's sparse dictionaries are zero.
- The arm's mass p(k) on integer k is read as uniform on [k − 0.5, k + 0.5).
- **Shift:** p'(j) = Σ_k p(k) · |[k − 0.5 + δ, k + 0.5 + δ) ∩ [j − 0.5, j + 0.5)| for j ∈ J.
- **Edges:** mass beyond either end of J goes to that end integer.
- **Floor:** mass on integers below F moves onto F. If F lies outside J, onto the nearest end of J.
- **Scoring:** the result is a dictionary over J. `brier_score` and `log_loss` sum over its keys. Every label lies
  in the space, so it lies in J.
- **Revision note (v2, pre-data):** this paragraph replaces version 1's "a non-contiguous space is refused" (rule sha `97d2d6bd…`,
  never reported). Version 1 would have refused every row. The change was made before any NBH row was read, after
  the bucket space was inspected in one R-A training record (atlanta, centre 2026-09-07).

**Fit:**
- **Grid:** b ∈ {0, 0.05, …, 1.00} (21 values), a ∈ {−3.0, −2.9, …, +3.0} °F (61 values).
- **Criterion:** minimise the mean summed bucket Brier (`feature_model.brier_score`) of the translated, floored
  arm.
- **Ties:** smallest b, then smallest |a|, then a < 0 before a > 0.
- (a, b) = (0, 0) is the arm itself, so the fit can always return the incumbent.
- **Fit rows:** out-of-sample arm distributions only (nested; next section).

## Gates (in order; each stops the rung if it fails)

### Gate 1: parity and inputs (inputs only, two halves, as RK-1)

- **1a (training rows, before gate 2):**
  - the L12 2021-25 corpus `SHA256SUMS` exists and every used block verifies;
  - NBH coverage (x not missing) ≥ 0.95 of the h13-16 rows;
  - TMP within [−40, 130] °F;
  - zero selections failing LM + 10 min ≤ t;
  - median |max(f_rem, F) − A| ≤ 3 °F (two forecasts of one day's high; proves the slot is read).
- **1b (dev, before gate 3):** the same checks on the 2026 corpus and the dev rows, plus the R-H sha checks and the
  A/F reproduction control above.
- **Outcomes:**
  - If either half fails, R-P stops as "parity failed" (not a kill).
  - If no finalised 2026 corpus is delivered, R-P stops after gate 2 as DEV UNTESTABLE (not a kill).
- **Forward parity (required before any promotion; not available now):**
  - one owned NBH block parser and cycle selector, imported by the research reader and a forward recorder;
  - recorder blocks byte-identical to the archive on the same cycles;
  - recorded retrieval − `LastModified` under the 10 min margin on almost all rows (otherwise widen the margin and
    re-fit);
  - a snapshot payload stamping the NBH cycle and block sha256 for captured-input replay and release binding.

### Gate 2: nested LOYO 2021-25, B_P beats B_N at 13-16

- **Outer folds:** for each held-out year Y ∈ 2021..2025 and each hour h:
  - fit the arm (R-A's `_rung_entry`, unchanged) on years ≠ Y;
  - predict Y.
- **Inner folds:** for each inner year Z ≠ Y:
  - fit the arm on years ∉ {Y, Z};
  - predict Z;
  - (a, b) for (arm, h, Y) is the grid minimiser over the pooled inner predictions of all Z ≠ Y.
  - Year Y's outcomes never enter Y's (a, b).
- **Statistic:** mean per row of Brier(B_P) − Brier(B_N), pooled over h13-16, with a date-clustered bootstrap
  (2,000 draws, seed 20261024).
- **PASS** if the upper 95% bound is below 0.
- **Control (refusal, not a gate):** the outer-fold B_N and P3d_N_fix rows must reproduce R-J's
  `C:\t\l2\rungj\emit\loyo_rows.jsonl`: identical (hour, year, market, date) keys, and every Brier and log loss
  within 1e-12.
- **Reported:** each hour; P3d_P − P3d_N_fix; the fitted (a, b) per (arm, h, Y); and the share of folds with b = 0.

### Gate 3: dev, P3d_P beats P3d_N_fix at 13-16

- **Dev (a, b):** per arm and hour, the grid minimiser over all 2021-25 outer-fold LOYO predictions (each year out
  of sample). No dev row enters the fit.
- **Population:** as R-F and R-J. Scorecard folds 2026-08-01..09-29, scored 08-15..09-29, layout `C:\swarm\v3layout`.
- **Statistic:** dR = mean_cell(Brier_P3d_P − Brier_P3d_N_fix) / mean_cell(Brier_market), ALL markets, h13-16
  pooled, date-clustered 95% (2,000 draws, seed 20260921).
- **Scope:** snapshots covered by B_N, B_P, P3d_N_fix, P3d_P and the composite.
- **PASS** if the upper bound is below 0.
- **Control:** MG-1's 07-12 excess must give 0.012, as R-J. Otherwise refused.

### Gate 4: against MG-2's post-13 arm (R-F reading)

- **Comparator:** composite_post13, exactly R-J's construction in `rung_j_score`. That is MG-2's post-13 dev arm
  P3d_N (`C:\t\l2\p3d_n_dev\dev_P3d_N.jsonl`, sha
  `721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec`, refused otherwise) where the scorecard covers
  it, else MG-1. Gate 3's comparator is P3d_N_fix, the arm R-P translates; gate 4's is MG-2 as bound.
- **Candidate:** P3d_P with the same MG-1 fallback.
- **Statistic:** gate 3's statistic on gate 3's scope.
- **Reading:**
  - **WIN** if the 13-16 upper bound is below 0 and no hour h13..h16 has a lower bound above 0.
  - **HARM** if the lower bound is above 0.
  - **NULL** otherwise.
- **If WIN:** L14 drafts, but does not apply, a dated MG-2 post-13 Clarification and the forward NBH capture and
  parity plan. Nothing else.

### Reported only (never a gate)

- R (Brier ÷ market Brier) for every arm.
- Each arm vs the market, with date-clustered intervals.
- Each hour, h13-14 and h15-16, and per market.
- B_P − B_N on dev.
- Missing rates.
- The selected-cycle age per market and hour, and the 19Z-ceiling share.
- MDE80 = 2.8 · se.

## Power, stated before scoring

- **Dev:** 43 scored dates and 473 market-days.
- **Interval width:** R-J's P3d_G − P3d_N_fix 13-14 dev interval was [−0.0207, +0.0158] dR. So gate 3's MDE80 is
  about 0.025 dR.
- **Expected effect:** lever inventory row 7 expects about −0.0005 Brier at 13-16, which is far below that MDE.
  Gate 3 is a refutation gate.
- **LOYO:** 305 dates × 11 markets per hour. This is the only gate with power for small effects.

## PRE-REGISTERED KILL

If gate 2 or gate 3 fails, the NBH remaining-hours path is closed as a 13-16 centre input.

Concretely, no other NBH TMP window, transform, cycle rule, margin, shift or fit form, and no NBH TMP feature added
to an OLS or HGB, is run as a centre input at 13-16 on B_N, P3d_N_fix or any NBM-anchored arm under any rung name.

**Scope of the kill:**
- It stands even though gate 3 is underpowered. It is a decision-rule closure, recorded with its MDE, not a claim
  of no effect.
- It does not cover:
  - NBH at other hours;
  - other NBH elements;
  - HRRR (R-K's own rule);
  - a 20Z-23Z cycle supplement. Re-opening because of the 19Z ceiling needs an owner ruling, because the ceiling is
    disclosed here.
- A gate 1 failure, or no 2026 corpus, stops R-P without a kill.

## Multiplicity

- B_P and P3d_P are the two candidates: two K rows in the dev-window ledger. They are proposed as pending via the
  docs head before scoring.
- The dev window is reused, as R-F to R-K were.

## Code and outputs

- **Code:**
  - Branch `claude/nbh-centre-1316-20261026` from `origin/claude/rung0712-20261025` @ bdc1ef0f8. It imports L2's
    `pooled_residual_model` unchanged.
  - New module `weather.calibration.nbh_centre_shift`. It records this rule's sha256 as `RP_RULE_SHA256` before any
    R-P row exists.
  - The module is allowlisted on that branch with an admission test.
- **Outputs:**
  - `C:\t\l14\rp\loyo\`: gate 1a and gate 2 (`rp_loyo_audit.json`, `loyo_rows.jsonl`, `ab_fits.json`).
  - `C:\t\l14\rp\emit\`: gate 1b and the dev distributions `dev_B_P.jsonl`, `dev_P3d_P.jsonl`.
  - `C:\t\l14\rp\score\rp_score.json`.

## Revision record (all before any NBH row was read)

- **v1** `97d2d6bd…`: never reported.
- **v2** replaced the translation span (above).
- **v3** (this text) makes two corrections:
  - gate 4's comparator is R-J's MG-2 post-13 arm P3d_N, not P3d_N_fix;
  - missing rows are left unchanged (δ = 0) rather than set to x = 0, which would have applied the intercept a.
