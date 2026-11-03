# Row 28b — forward test of row-28 candidate B (season-matched P3d_N refit), DRAFT prereg

Status: **DRAFT, NOT FROZEN.** Nothing in this file binds. Master reviews it; it freezes only after the owner OKs
row-28 prereg §9 item 3 (a named forward embargo line starting 12-17), and a freeze commit records its sha256.
Drafted by lane L59 on the WS (non-capture) on 2026-11-03 from origin/master `621d67f0f`, outcome-blind for the
forward window: no forward date's input, label, price or score was read, and no data dated 2026-09-30 or later was
opened. The only numbers used are row 28's frozen history results (branch
`claude/row28-yearround-history-20261102`, score result sha256
`32932ebc58cfb3db469a3ed373847415ecfc4bca98f98480197c6f2994100f4b` @ `741174e5f`) and the post-hoc D2 diagnostic
(`claude/row28-posthoc-diag-20261103` @ `2a9cfcdf6`), used for sizing only.

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
- The 45th date is about 01-30, so all N dates have accrued before the first allowed read; the §6 looks are applied
  in order at that single read (open question Q3).

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
  with the history's point-in-time availability rule, inputs only and blind. Every forward date is NBM v5.0; row 28
  was V4-scoped and its §7 gate (PASS on 21 V5.0 dates) means "no gross shift seen", not equivalence (Q4).
- **Labels.** Forward dates fall after 2026-10-23, so labels are the venue-rule labels (routine METAR, WU fallback),
  read only through `read_venue_labels` from the look-morning frozen copy (R24 ruling). Row 28 used WU history
  labels (Q5). Denver is excluded, as in row 28 §5.3.

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

- **PASS** iff all N = 45 dates are scored, no §6 look stopped the test, the point is ≤ −0.0057 (row 28's G floor),
  and the 95% upper bound is < 0 on **both** the date-clustered and the block-3 interval (the more conservative verdict
  holds).
- **FAIL** otherwise (including a §6 HARM or FUTILE stop). **HALTED** if §4 fires.
- A PASS ends this prereg. It earns a market-facing test request only (method §5 rule 4), never adoption.

## 6. Power and futility (method §5 rules 6-7, rule 16, rule 19)

- **SD source (rule 19).** Same contrast, same hours, same season: the row-28 history B − S per-date SD 0.0803 over
  657 dates (ρ 0.222, κ_AR 1.570, κ_block3 1.419). Rule 19 also asks for the realised/projected SD ratio after the
  look; it is reported.
- **Planning bound.** The forward season is one NBM v5.0 season with venue-rule labels, so the gate below uses a
  stated conservative bound of **1.5 × 0.0803 = 0.1205**.
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

The post-13 (hours 13-16) Dec 17 – May 31 slice that MG-2 serves with the MG-1 fallback; history size of the gap
B closes: −0.1368 per-row Brier (row-28 score result `32932ebc58cfb3db469a3ed373847415ecfc4bca98f98480197c6f2994100f4b`).
No loss atlas exists for this season; the history score result stands in for it (Q7).

## (d) MDE and clusters

MDE80 0.0675 at the planning bound (0.0450 at the realised SD), at 45 date clusters and 10 market clusters.

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

z_k = mean_k / (s_k × √VIF / √k) on the first k deciding dates, positive meaning harm. A stop is final for this
prereg. No look produces a PASS, changes N or the estimand, or starts a refit.

## 7. Descriptive only (decides nothing)

- B and S against the market at hours 13-16: R and the walk-forward log-pool weight w (method §3 rung 4), with the
  floor-only control. Prices are read only under the §1 read rule.
- Per-market d, per-month d, and the realised/projected SD ratio (rule 19).

## 8. Open questions for master (draft only)

1. Q1 — Estimand: keep B − S primary (row 28's question), or make the market w read primary under rule 4?
2. Q2 — The planning bound 1.5× is the drafter's choice; master may set it.
3. Q3 — With a single read after 01-26, the looks are applied retroactively; keep N = 45, or lengthen N so that
   later looks read sequentially?
4. Q4 — V5.0 throughout the forward window versus a V4-scoped history: is an extra outcome-blind input check needed?
5. Q5 — Venue-rule labels forward vs WU labels in history: acceptable, or score both?
6. Q6 — Which captured MG-2 fallback rows exist from 12-17 for the §4 parity control (a host read, counts only)?
7. Q7 — Does the checker's (c) accept the history score result in place of an atlas?
8. Q8 — Ledger: one K row for B on forward dates, written before D0.

## 9. Related

Row 28 prereg §8.3, §9 (`claude/row28-yearround-history-20261102`); EF §10aw; method §5 rules 4, 6, 7, 9, 16, 19;
[pre-registration checklist](../../operations/PREREGISTRATION_CHECKLIST.md).
