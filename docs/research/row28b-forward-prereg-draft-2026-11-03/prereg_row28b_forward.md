# Row 28b — forward test of row-28 candidate B (season-matched P3d_N refit), DRAFT prereg

Status: **DRAFT, NOT FROZEN.** Nothing in this file binds. Master reviews it; it freezes only after the owner OKs
row-28 prereg §9 item 3 (a named forward embargo line starting 12-17), and a freeze commit records its sha256.
Drafted by lane L59 on the WS (non-capture) on 2026-11-03 from origin/master `621d67f0f`, outcome-blind for the
forward window: no forward date's input, label, price or score was read, and no data dated 2026-09-30 or later was
opened. The only numbers used are row 28's frozen history results (branch
`claude/row28-yearround-history-20261102`, score result sha256
`32932ebc58cfb3db469a3ed373847415ecfc4bca98f98480197c6f2994100f4b` @ `741174e5f`) and the post-hoc D2 diagnostic
(`claude/row28-posthoc-diag-20261103` @ `2a9cfcdf6`), used for sizing only.

**Master rulings on the first draft (2026-11-03), applied here.** Q2 ACCEPTED (the 1.5× planning bound, rule 19).
Q3: the futility looks are dropped for one single look (§6). Q4 ACCEPTED (forward = NBM v5.0, disclosed). Q5
ACCEPTED (venue-rule labels through the R24 frozen copy, mismatch with WU history disclosed). Q1, Q6, Q7 and Q8
stay open. Still DRAFT, NOT FROZEN.

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
| Read rule | no input-derived score, label or price of any forward date is read before (i) the PT-1 look and (ii) the F8-MH look (01-26) have both been taken, and (iii) every earlier-frozen claimant of that date has looked (method §5 rule 9; look order follows freeze time) |
| Hard excluded | everything before D0 for scoring; the sealed panel 2026-05-27..07-30 and 2026-06-01..09-29 are never read, as in row 28 §1 |

- **Claimants to clear before freeze (rule 9, listed by name; to be verified against the CAMPAIGN_LEDGER, the
  DEV_WINDOW_LEDGER and the reserved window at freeze):** PT-1 (12-12..01-25), F8-MH (D0 11-02, look 01-26), row 72
  R-ODC P1 (D0 10-31), MG-1 forward shadow (NBM-derived reads only), MG-2 / Rule B-1 (45th date 12-12), T+1 (not yet
  frozen), L6_G. A claim whose scope cannot be shown not to intersect is treated as intersecting.
- **One look (master ruling on Q3).** The test has a single look, taken after the 45th deciding date (01-30 if
  none drops) is final, that is after its venue-rule label is in the R24 frozen copy. **Earliest read date:
  2027-01-31**, and only once PT-1 and F8-MH (01-26) and every other earlier-frozen claimant have looked; the
  actual read date is recorded in the look receipt.
- **No fail-fast in calendar time.** Every forward read waits for the earlier-frozen claimants' 01-26 looks, so an
  interim look could not be read earlier than the final one; futility looks would save no calendar time.

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
  look-morning R24 frozen copy. **Disclosed mismatch:** row 28's history used WU labels. Denver is excluded, as in
  row 28 §5.3.

## 3. Statistic

d(t) is the mean over the US10 rows at hours 13-16 of [Brier_B − Brier_S] on forward date t (row 28 §6.1); positive
means harm. The point is mean_t d(t). SEs use SD(d)·√κ/√n with κ = max((1+ρ̂)/(1−ρ̂), 1.318), and a block-3
interval (blocks of 3 consecutive dates) is reported beside the date-clustered one.

## 4. Integrity (HALT before any label is joined)

- S dual-implementation check (1e-12), as §2.
- B state and training manifest shas equal the freeze commit.
- Input-availability check: every scored row's NBM inputs were available by the row's cutoff (PIT rule).
- A parity control comparing the built S inputs with the captured MG-2 C5 fallback rows where both exist (Q6).
- The spring-DST day 2027-03-14 is excluded (outside the first 45 dates if none drops).
- A HALT before any score allows a reviewed amendment; after any score exists, no re-run.

## 5. Decision

- **PASS** iff all N = 45 dates are scored, the point is ≤ −0.0057 (row 28's G floor),
  and the 95% upper bound is < 0 on **both** the date-clustered and the block-3 interval (the more conservative verdict
  holds).
- **FAIL** otherwise. **HALTED** if §4 fires.
- A PASS ends this prereg. It earns a market-facing test request only (method §5 rule 4), never adoption.

## 6. Power, single look (method §5 rule 6, rule 16, rule 19)

- **SD source (rule 19).** Same contrast, same hours, same season: the row-28 history B − S per-date SD 0.0803 over
  657 dates (ρ 0.222, κ_AR 1.570, κ_block3 1.419). Rule 19 also asks for the realised/projected SD ratio after the
  look; it is reported.
- **Planning bound (master ruling on Q2, accepted).** The forward season is one NBM v5.0 season with venue-rule
  labels, so the gate below uses a stated conservative bound of **1.5 × 0.0803 = 0.1205**.
- **Single look, no inflation.** With no interim look, the futility-look SE inflation (method §5 rule 7, ×1.07) is
  not applied. Alpha: one final test, two-sided 95% (one-sided 2.5%) on each of the date-clustered and block-3
  intervals, and a PASS needs both, so the false-PASS rate is at most 2.5%.
- **Effect.** delta = half the history point (0.1368 / 2 = 0.0684), method §5 rule 6. Power at the edge size 0.0057 is
  about 0.04-0.10 at any N ≤ 166 and is stated, not claimed: this test can only confirm a large B − S effect.

| SD basis | N | MDE80 | Power at delta | Power at the history point |
| --- | --- | --- | --- | --- |
| realised 0.0803 | 45 | 0.0420 | 0.995 | 1.00 |
| bound 1.5× (gate) | 45 | 0.0630 | 0.86 | 1.00 |
| 2× | 45 | 0.0841 | 0.63 | 0.995 |
| bound 1.5× | 20 | 0.0946 | 0.53 | 0.98 |
| bound 1.5× | 166 | 0.0328 | 1.00 | 1.00 |

## (a) Positive control

S's dual-implementation agreement 1e-12 on every scored row and on 50 fixed synthetic rows, and the frozen B state
reproducing its own training-time predictions on 50 fixed rows to 1e-12 (max abs diff 0.0). The dev-window
served-vs-market R 1.774 / 1.526 does not apply: no dev date is read.

## (b) Comparator fairness

S gets the same rule-4 floor and the same calibration (none beyond the shared band/Brier scorer) as B, on identical
rows: paired per (market, date, hour), the same build function, the same label copy.

## (c) Targeted loss slice

The post-13 (hours 13-16) Dec 17 – May 31 slice that MG-2 serves with the MG-1 fallback; history size of the gap
B closes: −0.1368 per-row Brier (row-28 score result `32932ebc58cfb3db469a3ed373847415ecfc4bca98f98480197c6f2994100f4b`).
No loss atlas exists for this season; the history score result stands in for it (Q7).

## (d) MDE and clusters

MDE80 0.0630 at the planning bound (0.0420 at the realised SD), at 45 date clusters and 10 market clusters.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md: reuse count 212 (2026-11-03) plus one for this row; this test reads no 07-31..09-29 date.

## (f) Power gate
- sigma_d: 0.1205 (history, 1.5 x the row-28 B - S per-date SD 0.0803 over 657 dates, 2021-2025 Dec 17-May 31, score_result.json sha256 32932ebc58cfb3db469a3ed373847415ecfc4bca98f98480197c6f2994100f4b; conservative bound per method rule 19)
- rho: +0.222
- block3 ratio: 1.191
- VIF: 1.570
- delta: 0.0684 (half the history point; power at the history point 1.00)
- N: 45
- MDE80: 0.0630 (2.802 x sigma_d x sqrt(VIF) / sqrt(N); single look, no futility inflation)
- power: 0.86
- class: POWERED
- intervals: date-clustered (verdict) and block-3 (reported beside it; the more conservative verdict holds)

## (g) Futility
- final N: 45
- interim PASS: never

No futility look (master ruling on Q3): one single look after the 45th date is final; see §1 for the
earliest read date and why fail-fast in calendar time is unavailable.

## 7. Descriptive only (decides nothing)

- B and S against the market at hours 13-16: R and the walk-forward log-pool weight w (method §3 rung 4), with the
  floor-only control. Prices are read only under the §1 read rule.
- Per-market d, per-month d, and the realised/projected SD ratio (rule 19).

## 8. Open questions for master (draft only)

1. Q1 — Estimand: keep B − S primary (row 28's question), or make the market w read primary under rule 4?
2. Q2 — CLOSED: the 1.5× planning bound is accepted (master 2026-11-03).
3. Q3 — CLOSED: a single look, no futility looks (master 2026-11-03).
4. Q4 — CLOSED: forward = NBM v5.0, disclosed (master 2026-11-03).
5. Q5 — CLOSED: venue-rule labels via the R24 frozen copy, mismatch disclosed (master 2026-11-03).
6. Q6 — Which captured MG-2 fallback rows exist from 12-17 for the §4 parity control (a host read, counts only)?
7. Q7 — Does the checker's (c) accept the history score result in place of an atlas?
8. Q8 — Ledger: one K row for B on forward dates, written before D0.
9. Q9 — CHECKER CONFLICT (new, for master): `prereg_check --forward` REFUSES this single-look design, because
   `check_futility` requires every Rule B look before final N (`src/weather/reporting/scorecards/prereg_check.py`
   lines 76 and 171-182; MIM §5 rule 7). Options: a ruling that restores the four looks (applied in order at the
   single read), a reviewed checker change that admits a declared single-look design, or a recorded exemption.
   This draft must pass the checker before it can freeze.

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
- markets: US10 (atlanta, austin, chicago, dallas, houston, los-angeles, miami, nyc, san-francisco, seattle); Denver out
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

Row 28 prereg §8.3, §9 (`claude/row28-yearround-history-20261102`); EF §10aw; method §5 rules 4, 6, 9, 16, 19;
[pre-registration checklist](../../operations/PREREGISTRATION_CHECKLIST.md).
