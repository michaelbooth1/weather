# Row 28b — forward test of row-28 candidate B (season-matched P3d_N refit), DRAFT prereg

**This prereg's verdict is B − S and claims MODEL IMPROVEMENT ONLY** (master ruling on Q1, 2026-11-03). Under
MODEL_IMPROVEMENT_METHOD §5 rule 4 (MIM:160-161), "A dev win against served or MG-1 is not edge progress", and a
candidate earns a market test only if its walk-forward w beats the placebo and the floor-only control. A PASS here
is not an edge claim and not an adoption.

Status: **DRAFT, NOT FROZEN.** Nothing in this file binds. Master reviews it; it freezes only after the owner OKs
row-28 prereg §9 item 3 (a named forward embargo line starting 12-17), and a freeze commit records its sha256.
Drafted by lane L59 on the WS (non-capture) on 2026-11-03 from origin/master `621d67f0f`, outcome-blind for the
forward window: no forward date's input, label, price or score was read, and no data dated 2026-09-30 or later was
opened. The only numbers used are row 28's frozen history results (branch
`claude/row28-yearround-history-20261102`, score result sha256
`32932ebc58cfb3db469a3ed373847415ecfc4bca98f98480197c6f2994100f4b` @ `741174e5f`) and the post-hoc D2 diagnostic
(`claude/row28-posthoc-diag-20261103` @ `2a9cfcdf6`), used for sizing only.

**Master rulings (2026-11-03), applied here; all of Q1-Q9 are answered.**

- Q1 ANSWERED, (c) two stages: the verdict here is B − S, model improvement only. The rule-4 w step is its own
  later prereg (§7a).
- Q2 ACCEPTED: the 1.5× planning bound (rule 19).
- Q3 SUPERSEDED by Q9.
- Q4 ACCEPTED: forward = NBM v5.0, disclosed.
- Q5 ACCEPTED: venue-rule labels through the R24 frozen copy; the mismatch with WU history is disclosed.
- Q6 ANSWERED, (a): MG-2's fallback log from the WS daily pull, counts and sha only (§4).
- Q7 ANSWERED, (c): a master ruling, recorded verbatim in (c).
- Q8 ANSWERED, (a): ledger rows are a pre-D0 requirement (§1a).
- Q9 ANSWERED, (a): the Rule B looks are restored and applied in date order at the single read, with the 4-7% MDE
  inflation. No checker change and no rule change. Master's note: MIM rule 7 already covers this case ("A look
  reads a date only when rule 9 allows it").
- Archive path `C:\archive\row28b-forward-state\<fit_id>\` and equivalence (c) in STATE-SHA mode: OK (master).
- Still DRAFT, NOT FROZEN until the owner OKs the 12-17 embargo line.

**Re-test from zero.** Row 28 prereg §8.3: "The forward test re-tests the candidate from zero, and the history point
is not carried as evidence." The history point (B − S −0.1368) sizes this test; it never enters its verdict.

## 0. Question and scope

> On forward dates from 2026-12-17, does arm B (a P3d_N_fix-spec refit trained on Dec 17 – May 31 rows only) beat
> **what MG-2 serves on those dates** (S: MG-1, the C5 post-coverage fallback) at hours 13-16?

- A PASS here is a model-vs-served result. It is **not an edge claim and not an adoption** (method §5 rule 4: a win
  against served or MG-1 is not edge progress). The market read in §7 is descriptive and decides nothing.
- Out of scope: any change to MG-2, `release-binding.json`, any B-bound file, `B_FORWARD_TEST_DESIGN.md`,
  `docs/research/mg2-composite-binding-2026-10-25/`, or PT-1. Nothing here serves, promotes or binds.
- The pre-13 half is out of scope, as in row 28 §4.4.

## 1. Dates

| Item | Value |
| --- | --- |
| D0 | 2026-12-17 (not earlier; row 28 §9 item 3), and not before this file's freeze commit |
| Deciding dates | the first **N = 45** forward dates from D0 that pass §4's integrity rules, in date order (12-17..01-30 if none drops) |
| Read rule | no input-derived score, label or price of any forward date is read before (i) the F8-MH look (01-26) has been taken and (ii) every earlier-frozen or bound claimant of that date has looked (method §5 rule 9; look order follows freeze time). PT-1 is NOT RUNNABLE (R21) and claims no date; its R21 receipt stands where a PT-1 look would |
| Hard excluded | everything before D0 for scoring; the sealed panel 2026-05-27..07-30 and 2026-06-01..09-29 are never read, as in row 28 §1 |

- **Claimants to clear before freeze (rule 9, listed by name; to be verified against the CAMPAIGN_LEDGER, the
  DEV_WINDOW_LEDGER and the reserved window at freeze):** PT-1 (NOT RUNNABLE (R21), claims no date; receipt `docs/research/pt1-not-runnable-2026-11-03/receipt.md` sha256 `8c45c8d99dabf1e38b21ad3ebd6e1b015a723b54054dd73d72e2373686cf7c35`), F8-MH (D0 11-02, look 01-26), row 72
  R-ODC P1 (D0 10-31), MG-1 forward shadow (NBM-derived reads only), MG-2 / Rule B-1 (45th date 12-12), T+1 (not yet
  frozen), L6_G. A claim whose scope cannot be shown not to intersect is treated as intersecting.
- **Single read (master ruling on Q9).** All reads happen at one read, taken after the 45th deciding date (01-30 if
  none drops) is final, that is after its venue-rule label is in the R24 frozen copy. **Earliest read date:
  2027-01-31**, and only once F8-MH (01-26) and every other earlier-frozen or bound claimant have looked (PT-1 claims no date: NOT RUNNABLE, R21). The actual
  read date is recorded in the look receipt. At that read, the Rule B looks of (g) are applied in date order
  (k = 7, 14, 21, 31) before the final test; a look reads a date only when rule 9 allows it (MIM §5 rule 7).
- **No early stop in calendar time.** Every forward read waits for the earlier-frozen claimants' 01-26 looks, so
  the looks give no early stop in calendar time. A HARM or FUTILE stop is still final for this prereg.

1a. **Pre-D0 requirement (master ruling on Q8).** A DEV_WINDOW_LEDGER K row for B on forward dates, as the freeze
branch's first commit and before D0 (as F8-MH did, ledger row 104), plus a C row if a control stage is kept, each
with verdict pending. No ledger row is added while this file is a draft.

## 2. Candidate and comparator

- **B (frozen before D0).** The row-28 arm B recipe (row 28 §3.1, §3.2, §4): the B-bound
  `fit_pooled(train, market_id=False, doy=True, raw_columns=False, bias_by="season")` imported read-only, the NBP
  mean anchor and the same features, HGB `random_state` pinned as in the bound builder, trained on the Dec 17 – May 31
  rows of all five 2021-2025 season-years (no held-out fold). One state; its sha256 and the training-row manifest
  sha256 are recorded in the freeze commit. The fit runs under `scripts\ops\workstation_heavy.ps1`.
- **S.** MG-1 at hours 13-16: mu = v2_mean, sigma = max(v2_stddev, 1), the rule-4 floor, via
  `weather.reporting.scorecards.free_source_candidates.mg1.predict`, checked against
  `weather.model.mg_serve_core.mg1_band_probs` to 1e-12 on every scored row (row 28 §2). S reads only the 07Z
  v2_mean, as serving does.
- **Inputs.** Both arms read the same rows, built by the row-28 build function from the free official NBM archive
  with the history's point-in-time availability rule, inputs only and blind.
- **NBM v5.0 (disclosed; master ruling on Q4).** Every forward date is NBM v5.0. Row 28's history survival was
  V4-scoped, and its §7 gate (PASS on 21 V5.0 dates) means "no gross shift seen", not equivalence; this is why
  the forward test re-tests B from zero.
- **Labels (master ruling on Q5).** Forward dates fall after 2026-10-23, so labels are the venue-rule labels
  (routine METAR, WU fallback), read only through `read_venue_labels` inside the registered entry point from the
  look-morning R24 frozen copy. **Disclosed mismatch:** row 28's history used WU labels. Denver is excluded from
  scoring and emission, as in row 28 §5.3; it stays in B's training, as in v12 (master ruling 11-03).

## 3. Statistic

d(t) is the mean over the US10 rows at hours 13-16 of [Brier_B − Brier_S] on forward date t (row 28 §6.1); positive
means harm. The point is mean_t d(t). SEs use SD(d)·√κ/√n with κ = max((1+ρ̂)/(1−ρ̂), 1.318), and a block-3
interval (blocks of 3 consecutive dates) is reported beside the date-clustered one.

## 4. Integrity (HALT before any label is joined)

- S dual-implementation check (1e-12), as §2.
- B state and training manifest shas equal the freeze commit.
- Input-availability check: every scored row's NBM inputs were available by the row's cutoff (PIT rule).
- **Parity control (master ruling on Q6, option (a)).** The built S inputs are compared with MG-2's own C5
  fallback log (`mg2_post_coverage_fallback.jsonl`) from the WS daily pull, counts and sha only. This needs an
  outcome-blind check first that the pull runs past 12-17. If it does not, option (b) applies: a host bounded extract,
  counts only. S's dual-implementation check is kept either way.
- The spring-DST day 2027-03-14 is excluded (outside the first 45 dates if none drops).
- A HALT before any score allows a reviewed amendment; after any score exists, no re-run.

## 5. Decision

- **PASS** iff all N = 45 dates are scored, no (g) look stopped the test, the point is ≤ −0.0057 (row 28's G floor),
  and the 95% upper bound is < 0 on **both** the date-clustered and the block-3 interval (the more conservative verdict
  holds).
- **FAIL** otherwise, including a (g) HARM or FUTILE stop. **HALTED** if §4 fires.
- A PASS ends this prereg and claims model improvement only. It earns no market test by itself; the rule-4 w step
  (§7a) comes first.

## 6. Power and futility (method §5 rules 6-7, rule 16, rule 19)

- **SD source (rule 19).** Same contrast, same hours, same season: the row-28 history B − S per-date SD 0.0803 over
  657 dates (ρ 0.222, κ_AR 1.570, κ_block3 1.419). Rule 19 also asks for the realised/projected SD ratio after the
  look; it is reported.
- **Planning bound (master ruling on Q2, accepted).** The forward season is one NBM v5.0 season with venue-rule
  labels, so the gate below uses a stated conservative bound of **1.5 × 0.0803 = 0.1205**.
- **Futility inflation restored (Q9).** The MDE uses the 4-7% futility-look inflation at its upper end (×1.07,
  method §5 rule 7). Futility and harm stops cost power; no interim look produces a PASS.
- **Effect.** delta = half the history point (0.1368 / 2 = 0.0684), method §5 rule 6. Power at the edge size 0.0057 is
  about 0.04-0.10 at any N ≤ 166 and is stated, not claimed: this test can only confirm a large B − S effect.

| SD basis | N | MDE80 (×1.07) | Power at delta | Power at the history point |
| --- | --- | --- | --- | --- |
| realised 0.0803 | 45 | 0.0450 | 0.99 | 1.00 |
| bound 1.5× (gate) | 45 | 0.0675 | 0.81 | 1.00 |
| 2× | 45 | 0.0900 | 0.57 | 0.99 |
| bound 1.5× | 20 | 0.1012 | 0.47 | 0.97 |
| bound 1.5× | 166 | 0.0351 | 1.00 | 1.00 |

## (a) Positive control

S's dual-implementation agreement 1e-12 on every scored row and on 50 fixed synthetic rows, and the frozen B state
reproducing its own training-time predictions on 50 fixed rows to 1e-12 (max abs diff 0.0). The dev-window
served-vs-market R 1.774 / 1.526 does not apply: no dev date is read.

## (b) Comparator fairness

S gets the same rule-4 floor and the same calibration (none beyond the shared band/Brier scorer) as B, on identical
rows: paired per (market, date, hour), the same build function, the same label copy.

## (c) Targeted loss slice

Master ruling on Q7, verbatim: "The (c) slice is the scored population itself (h13-16, US10, the scored window).
No Dec-May loss atlas exists (the atlas is dev-scoped), and row-28's POST-HOC D1 shows the history gain is broad
across every month and fold for A, B and C. No sub-slice is claimed. (Master, 2026-11-03.)"

History size, for sizing only: B − S −0.1368 per-row Brier (row-28 score result
`32932ebc58cfb3db469a3ed373847415ecfc4bca98f98480197c6f2994100f4b`).

## (d) MDE and clusters

MDE80 0.0675 at the planning bound (0.0450 at the realised SD), ×1.07 inflated, at 45 date clusters and 10 market
clusters.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md: reuse count 212 (2026-11-03) plus one for this row; this test reads no 07-31..09-29 date.

## (f) Power gate
- sigma_d: 0.1205 (history, 1.5 x the row-28 B - S per-date SD 0.0803 over 657 dates, 2021-2025 Dec 17-May 31, score_result.json sha256 32932ebc58cfb3db469a3ed373847415ecfc4bca98f98480197c6f2994100f4b; conservative bound per method rule 19)
- rho: +0.222
- block3 ratio: 1.191
- VIF: 1.570
- delta: 0.0684 (half the history point; power at the history point 1.00)
- N: 45
- MDE80: 0.0675 (2.802 x sigma_d x sqrt(VIF) / sqrt(N), inflated 7%)
- power: 0.81
- class: POWERED
- intervals: date-clustered (verdict) and block-3 (reported beside it; the more conservative verdict holds)

## (g) Futility
- look 7: HARM if t > 3.143
- look 14: FUTILE if z > +0.5
- look 21: FUTILE if z > 0
- look 31: FUTILE if z > -0.5
- final N: 45
- interim PASS: never

z_k = mean_k / (s_k × √VIF / √k) on the first k deciding dates, positive meaning harm. The looks are applied in date
order at the single read (§1); they give no early stop in calendar time. A stop is final for this prereg. No look
produces a PASS, changes N or the estimand, or starts a refit.

## 7. Descriptive only (decides nothing)

- B and S against the market at hours 13-16: R and the walk-forward log-pool weight w (method §3 rung 4), with the
  floor-only control. Prices are read only under the §1 read rule.
- Per-market d, per-month d, and the realised/projected SD ratio (rule 19).

## 7a. The rule-4 w step (pointer only; not drafted here)

The rule-4 w step (walk-forward w against the placebo and the floor-only control, MIM §3 rung 4 and §5 rule 4) is
its OWN later prereg, run before any forward market test, as a history-tier screen on the L52 public price history.
Its data scope follows STATE_OF_PLAY line 50 as recorded; if that needs an owner yes, it goes to master first.

## 8. Questions (all answered by master, 2026-11-03)

1. Q1 — ANSWERED (c): two stages; B − S here, model improvement only; the w step per §7a.
2. Q2 — ACCEPTED: the 1.5× planning bound.
3. Q3 — SUPERSEDED by Q9.
4. Q4 — ACCEPTED: forward = NBM v5.0, disclosed.
5. Q5 — ACCEPTED: venue-rule labels via the R24 frozen copy, mismatch disclosed.
6. Q6 — ANSWERED (a): MG-2's fallback log, counts and sha, after the outcome-blind pull check; else (b) (§4).
7. Q7 — ANSWERED (c): master's ruling, recorded verbatim in (c).
8. Q8 — ANSWERED (a): the pre-D0 ledger requirement (§1a).
9. Q9 — ANSWERED (a): the Rule B looks are restored, applied in date order at the single read, with the ×1.07
   inflation; no checker change, no rule change.

## 8a. Freeze record fields (L56's accepted prereg field names; PLACEHOLDER = unknown until freeze)

- candidate_id: PLACEHOLDER
- module: PLACEHOLDER
- module_source_sha256: PLACEHOLDER
- fit_manifest_sha256: PLACEHOLDER
- state_sha256: PLACEHOLDER
- state_sidecar_sha256: PLACEHOLDER
- state_schema: mg2_p3d_n_state/1
- arm: B (season-matched, Dec 17 - May 31 rows of 2021-2025)
- centres: PLACEHOLDER
- season_of: PLACEHOLDER
- hours: 13, 14, 15, 16
- training_window: Dec 17 - May 31 of season-years 2021-2025
- training_rows_sha256: PLACEHOLDER
- bucket_space_sha256: PLACEHOLDER
- upstream_sha256: {pooled_residual_model: PLACEHOLDER, mg2_p3d_n: PLACEHOLDER, mg_serve_core: PLACEHOLDER, feature_model: PLACEHOLDER, ols_floor_ladder: PLACEHOLDER, r0_ols_floor_devfit: PLACEHOLDER}
- sklearn_version: PLACEHOLDER
- conversion: PLACEHOLDER
- late_report: PLACEHOLDER
- train_F_source: PLACEHOLDER
- serve_F_source: PLACEHOLDER
- shadow_first: 2026-12-17
- shadow_last: PLACEHOLDER
- coverage_window: PLACEHOLDER
- input_modes: as_of_capture
- forward_receipt_sha256: PLACEHOLDER
- shadow_rows_sha256: PLACEHOLDER
- emit_receipt_sha256: PLACEHOLDER
- equivalence_report_sha256: PLACEHOLDER
- frozen_before_utc: PLACEHOLDER (before 2026-12-17)
- markets: training: 11 R0 markets incl. Denver (as v12); scored/emitted: US10
- scored_window: 2026-12-17..2027-01-30 (the N = 45 deciding dates)
- emission_window: 2026-12-17..2027-05-31 (emission only; named separately from the scored window)
- fit_kind: forward
- state_archive_path: `C:\archive\row28b-forward-state\<fit_id>\`

**Master's Q-W commitment trail.**

- The B state is frozen before 2026-12-17.
- Emission runs in WEEKLY batches from 2026-12-21, from as_of_capture inputs only.
- Each batch's shadow_rows_sha256 and emit receipt go to master the same day and are logged with a host timestamp.
- Emission reads no outcomes.

## 9. Related

Row 28 prereg §8.3, §9 (`claude/row28-yearround-history-20261102`); EF §10aw; method §5 rules 4, 6, 7, 9, 16, 19;
[pre-registration checklist](../../operations/PREREGISTRATION_CHECKLIST.md).
