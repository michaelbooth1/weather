# Row 28 — year-round P3d_N refit, HISTORY-ONLY kill-only prereg (DRAFT r2)

Status: **DRAFT, NOT FROZEN.** Nothing in this file binds until master reviews
it and a freeze commit records its sha256. Drafted by lane L59 on the WS
(non-capture) on 2026-11-02 from origin/master `52d97f75b`, outcome-blind: no
row-28 label, outcome, settlement value or model score was read to write it.
Only metadata was read: row counts, dates, S3 listings, manifests, rule text and
code (one exception disclosed in §11). r2 folds the MAJORs of one fresh review
(§14).

This is a **history-only, kill-only** step. It can kill arms or let them survive
history. It cannot adopt, serve, promote or bind anything. A surviving arm only
earns the right to *ask* for a forward test (§9).

## 0. Question and scope

MG-2 serves P3d_N (bound state `c6cc39f7…a9c780`) on the post-13 half only
inside its training coverage 08-01..12-16 (`mg2_p3d_n.TRAINING_COVERAGE`).
Outside that coverage MG-2 rule clarification C5 falls the post-13 half back
to MG-1 and logs each row in `mg2_post_coverage_fallback.jsonl`. Row 28 asks:

> Does a P3d_N_fix-spec refit that covers Dec 17 – May 31 beat **what MG-2
> actually serves on those dates**, at the post-13 hours, on V4-era history?

Out of scope: any change to MG-2, `release-binding.json`, any B-bound file,
`B_FORWARD_TEST_DESIGN.md`, `docs/research/mg2-composite-binding-2026-10-25/`,
or PT-1. The pre-13 half (L6 stack over MG-1) is not a candidate here (§4.4).

## 1. Dates (binding)

| Tier | Dates | Role |
| --- | --- | --- |
| Deciding | 12-17..05-31 of 2021–2025, plus 2026-01-01..**2026-05-05** | Scores decide |
| V5 sliver (descriptive) | 2026-05-06..2026-05-26 | Scored descriptively only; never training; §7 gate inputs |
| Training-only | All other dates of 2021–2025 (arms A, C, D; §4) | Fit rows, never scored as deciding |
| Hard excluded | 2026-05-27..2026-07-30 (sealed panel); 2026-06-01..09-29 unused; everything ≥ 2026-09-30 | Never read |

- The coordinator's deciding range ends 2026-05-26. **r2 deviation, for master
  to rule on:** 2026-05-06..05-26 are NBM V5.0 dates. Keeping them would break the
  "history scoped to V4" requirement (§7), so they move to a descriptive V5
  sliver. If master prefers the original range, they rejoin fold 2026 and the
  V4-scope claim is dropped.
- Deciding calendar size: 977 dates under the coordinator range
  (`scripts/cap_counts_v2.py`), and **956** after the V5 sliver moves out. Before
  §5's drops, the folds hold 151 / 166 / 166 / 167 / 166 / 140 dates (2021..2026).
  2021 starts on 2021-01-01 because 2020-12 is not in the corpus.
- Jun–Jul 2021–25 may be training rows. They are never a deciding tier.
- Date rule (method §5 rule 9): one date rule for every arm. A date enters the
  deciding tier only through §5's integrity rules, which are applied before any
  score. Other claimants of these dates: PT-1 (12-12..01-25, forward 2026–27
  only), the F8-MH look, K112 G0/G2 (2026 Jan–May), row 113 step 2 (counts),
  and the P3F/PIT Jan–Jul corpora (§11). None of them is a forward claim on a
  history date.

## 2. Comparator (binding) — what would actually serve

The comparator was established outcome-blind from four sources:

- `rule.md` C5 (lines 377–391);
- the release-binding (`release-binding.json`, rule_sha256
  `e761cc4eef097b80ae95fa03245871e8689a50125f4ad11ad00286218b17cdec`);
- `mg2_p3d_n.py`;
- `mg2_composite.py`.

- **S (deciding comparator): MG-1 at hours 13–16, Dec 17–May 31.**
  - MG-1 is the zero-parameter NBM read: mu = v2_mean, sigma = max(v2_stddev, 1), with the rule-4 floor.
  - It is the C5 post-coverage fallback. MG-2 serves it on every deciding date, because every deciding date lies outside 08-01..12-16.
  - The reference implementation is `weather.reporting.scorecards.free_source_candidates.mg1`, the module that `mg2_composite` imports. Its file sha256 is recorded at freeze.
  - The scorer must assert that S equals that function's output on (a) 50 fixed synthetic rows and (b) every scored row. A mismatch triggers HALT.
- **S_bound (descriptive only): the bound P3d_N state `c6cc39f7`, applied out of season** to the same rows.
  - It loads only with the sha in `release-binding.json`.
  - Out of season it inherits the bound centre set and the non-wrapping `nearest_centre`: Jan–May dates map to the 08-08 centre ("aug_sep") and Dec 17–31 maps to 12-09. That artefact is part of what S_bound measures, and is stated as such.
  - S_bound never decides and is never counted in the multiplicity correction.
- **Forbidden comparators:** any dev, refit or convenient state that was never bound. This is the retracted X40 lesson: X40's comparator `dff5d797` was never bound.

## 3. Shared model spec, rows and folds

3.1 **Recipe.** Every arm uses the P3d_N_fix spec as bound:

- the B-bound `fit_pooled(train, market_id=False, doy=True, raw_columns=False, bias_by="season")`, imported read-only;
- the NBP mean anchor and the same features;
- the same band/Brier scoring, with `b_scorer.HOURS` restricted to 13–16;
- HGB `random_state` values pinned exactly as in the bound builder.

Only the training rows differ by arm.

3.2 **Feature map frozen for Dec–May** (the bound state only knows the Aug–Dec centres):

- Arms A, C and D use the centre set `FORWARD_CENTRES + JAN_JUL_CENTRES + ("2026-12-24",)` (24 centres, 15-day spacing).
- Arm B uses `JAN_JUL_CENTRES[:10] + ("2026-12-24",)`, that is 01-08..05-23 plus 12-24.
- `season` is `pooled_residual_model.season_of(centre)` unchanged:
  - Dec 17–31 rows get centre 12-24 and season "oct_dec";
  - Jan–May rows get a "jan_jul" centre.
- `nearest_centre` is used unchanged, without wrap. With 12-24 and 01-08 both present, wrapping cannot change any pick: the furthest dates, Dec 31 and Jan 1, are each 7 days from their own centre and at least 8 days from the other one.
- The scorer asserts the wrap-free and wrap-aware picks are identical for every deciding date. A mismatch triggers HALT.

3.3 **Rows: one built row per (market, date, hour) feeds S and every arm.**

| Input | Source |
| --- | --- |
| Label | WU daily high |
| `F` (high so far) and `current_temp` | METAR-only running max and latest obs at the cutoff (rule C1, `rule.md` 393–402), as in the bound builder |
| `fh` | NBP TXN mean |
| `v2_stddev` (S's sigma and rule-4 floor input) | NBP TXNSD |

- The NBM cycle is chosen by the bound `ols_floor_ladder.nbm_at_cutoff`: the newest of 07Z, 01Z, 00Z whose LastModified is at or before that row's own local cutoff instant.
- **Scored rows:** a row with no NBM value at its cutoff is dropped for S and every arm alike, with no imputation.
- **Training rows** keep the bound builder's behaviour (`attach_training_nbm`, L9 IMPUTE "fc", which reads the existing forecast_history cache; nothing is rebuilt) so that training parity with `c6cc39f7` holds. The imputed count is reported.
- Scoring uses only rows where S and the arm are both defined.
- The 12-24 centre records are absent from `C:\t\l2\records`, so Dec rows are built directly by the same builder. No held cache is rebuilt: the SoP hold on the forecast_history, open_meteo_archives and reanalysis caches until a399941e lands is respected.

3.4 **Folds: LOYO by season-year, six folds (2021..2026).**

- Fold Y holds out the whole season-year Dec 17 (Y−1) .. Dec 16 (Y).
- No row dated inside that interval enters fold Y's training set. That covers market rows, Denver rows and pool-station rows (arm C). It also covers rows outside the deciding tier, so Jun–Dec 16 of Y is never training for fold Y.
- Fold 2026 holds out 2025-12-17..2026-05-05 and trains on every permitted row outside that interval: 2021-01-01..2025-12-16, minus the hard exclusions.
- Training rows adjacent to the held-out season (Dec 16 of Y−1 and before) are allowed. The within-year lag-1 ρ is 0.137, so the edge leakage is negligible, and the AR(1)-inflated SE (§6) already absorbs that serial correlation.

3.5 **Control C-0 (HALT if it fails).** The builder, run on the R-A corpus definition exactly as its manifest records it (FORWARD_CENTRES records, bound years, bound seeds), must reproduce two things to 1e-9 before any deciding row is scored:

- the R-A training rows (19,657);
- the R-A per-row predictions.

## 4. Arms (pre-registered; each arm is one K ledger row)

| Arm | Training rows (outside the held-out season-year) | Notes |
| --- | --- | --- |
| **A** | Year-round pooled: all months of 2021–2025 | Plain P3d_N_fix-spec refit; `doy` and `season` carry the season |
| **B** | Season-matched: Dec 17–May 31 rows only | X40 found season-matching lost in Oct–Dec; tested here with no prior either way |
| **C** | A + R-P2 class-matched pooling | See 4.1 |
| **D** | A + K112 trailing correction | See 4.2 |

4.1 **Arm C** uses the R-P2 arm `P3d_N_cls` exactly: two fits per (hour, fold), one per class.

- Frozen R-P2 rule `prereg_rp2.md`, sha256 `2a438306214ece68e6e58d6f288765dc8addace7d21b89a02a22141e9c2d3e70`, on `origin/claude/station-pooled-corpus-s0-20261101` under `docs/research/climate-similar-pooling-rp2-2026-11-02/`.
- Classes file sha256 `35d0090dddf7b082c5ce0d777cf488c09bbcf6baead14c786e68c39fbafe1689`, held locally at `C:\t\rp2\out\rp2_classes.json`. Its git blob differs only by line endings.
- Class rule: marine if coast_km ≤ 25 to the Natural Earth 10m coastline, else continental.
- Pool stations come from the frozen classes file. Their rows are extended to all months (§10), and pool rows inside the held-out season-year are excluded (§3.4).
- R-P2's controls run first: C-0 (reproduce R-A to 1e-9) and C-b (empty-pool check).
- C must also pass R-P2's screen against A (C−A). KILL if any of:
  - the point is ≥ −0.0005;
  - the *wide* 95% upper bound (§6.1) is ≥ 0;
  - any market's 95% lower bound is > 0 (per-market CI, §6.1);
  - more than 1 of the 6 folds has d > 0 (R-P2's "1 of 5 years", adapted to six folds).
- Disclosure: the frozen class rule and the pool corpus `a57e10a6…` are Aug–Sep only. The extension to other months is new data, not a re-read.

4.2 **Arm D** applies the frozen K112 formula on top of arm A's mu: mu' = mu − λ·clip(b_recent − b_train, ±3°F), where d = NBP07 mean − WU high.

- Frozen rule: `rule_x36_trailing_final.md`, sha256 `032c8dc3bf33fd7dc549a5a9e93ed04d86809678a087fc43766e272b99f077f2`, on `origin/claude/x36-v5-reopen-20261101` under `docs/research/x36-v5-reopen-2026-11-01/`.
- **(W, λ) is fixed now, with no search on the deciding tier.**
  - K112's freeze table (`g2_freeze_table.json`, same folder, sha256 `383e4a6a1b8f4449e09f046dcff6bef90903df311115623d31b16974cf8ca449`) froze picks only for h07–h12. It has none for 13–16.
  - Pre-declared "nearest frozen hour" rule: hours 13–16 all use the h12 pick, **W = 14, λ = 0.25**.
- b_recent is the mean d over the W most recent *available* dates strictly earlier than the target, drawn from the previous 2W calendar days. If fewer than W such dates exist (for example early January 2021, which has no Dec 2020 data), no correction is applied (mu' = mu).
- b_train keeps the frozen K112 definition: the per-market mean d over Aug 1..Sep 29, recomputed inside each fold from that fold's training years only.
- Disclosures:
  1. K112's only measured gain is in season, Aug 15–Sep 29: G1 pooled −0.00226 [−0.00378, −0.00079], and the h12 interval spans 0.
  2. On 2026 Jan–May only 24 of 60 market-months improved in G0, and May over-corrected. K112's (W, λ) were selected on 2026-01-15..05-26. **D's deciding statistic therefore uses folds 2021–2025 only.** D's fold-2026 score is descriptive.
  3. X30: an intercept win may be a bias correction, not information.
- D must also beat A (D−A) under the same four kill conditions as C−A, computed on the same five folds, with "more than 1 of 5 folds".

4.3 **Multiplicity.**

- The primary family is four contrasts, A−S, B−S, C−S and D−S, corrected by **Holm over 4 at two-sided family-wise α = 0.05**. The most stringent step is α = 0.0125, z = 2.498.
- The family is fixed at 4: a FUTILE or HALTED arm keeps its slot with p := 1.
- C−A and D−A are gatekeeping conditions inside C and D, not extra family members. C or D survives only if its X−S passes Holm *and* its X−A passes the kill screen.
- **Arm A is always scored on all folds**, even when A is itself FUTILE, because it is the reference for C−A and D−A.
- S_bound contrasts are descriptive and uncounted.

4.4 **Hours.** The deciding hours are 13, 14, 15 and 16: the post-13 half within `b_scorer.HOURS` 07–16. Hours 07–12 are scored descriptively against the served pre-13 comparator and never decide. That comparator is the L6 stack over MG-1, with bound coefficients `07a67425…ee17e9` and state `800072c7…2ee2db`. Replacing the pre-13 half is a different question and would need its own prereg.

## 5. Integrity: cap, spring-DST rule, Denver

The counts come from `scripts/cap_counts_v2.py`, which reads only three inputs:

- `local_date` and `row_count` from the WU `daily_summary.csv`;
- the NBP listing;
- the L47b count.json counts.

Its output, `cap_counts_v2.json` (sha256 `803b5416ce2eb2c2cd921dfbc714835cccf08f90c84a949fa76ea92a041036e7`, held locally at `C:\t\L59\row28\`), was computed over the coordinator range ending 05-26. A day counts as partial if its WU `row_count < 18` (`settlement_ledger.COMPLETE_DAY_MIN_ROWS`).

5.1 **Spring-DST rule (pre-declared).** The US spring-forward day (second Sunday of March) is excluded from the deciding tier for every market and year.

- It is structurally partial: every US10 market has exactly 5 partial DST days in 2021–2025, which accounts for 50 of the 78 US10 partial+missing market-dates.
- Six DST dates are dropped (2021–2026). 2026-03-08 is dropped by the same rule whether or not it is partial in a given market.
- Fall-back days are not in the deciding tier.
- The script keeps a *missing* DST-day value in the numerator while removing DST days from the denominator. This is conservative and moot here: US10 has 0 missing days in the deciding range.

5.2 **Pooled integrity cap.**

- **Baseline (pre-freeze):** after 5.1, US10 partial+missing is 28 of 9,710 market-dates, **0.288%**. Partial and missing market-dates are dropped from the deciding tier and never imputed.
- **What counts toward the cap at run time.** Every deciding US10 market-hour dropped for any reason other than 5.1:
  - WU partial or missing;
  - no NBM at cutoff (§3.3);
  - a missing METAR input;
  - for arm C, an empty pool.
- **HALT before any arm score is computed** if any of these holds:
  - the pooled dropped share exceeds **1.0%**;
  - any single market exceeds **3.0%**;
  - any single fold loses more than **2.0%**.
- **NBP availability** is per row (§3.3), not a fixed clock. The listing (`nbp07_listing_decmay.tsv`, sha256 `a39073ad0793dd7d8f0a3010ebd3cb1213bf70a799e37f68faa681af31443e17`) shows:
  - 2021-01-22 has no 07Z object;
  - 7 objects were posted at or after 12Z (2021-02-11, 2022-01-06 [posted the next day], 2023-01-20, 2023-05-24, 2024-04-16, 2024-04-21, 2024-05-15).
- For those 8 dates the 01Z and 00Z text is fetched (an input only). Which rows are then dropped is decided mechanically by `nbm_at_cutoff`, and the list is fixed before any score.
- **2026:** NBP is present on 146/146 dates in every market (L47b counts).

5.3 **Denver.** Denver is excluded from the deciding tier and may contribute training rows. Both reasons are outcome-blind:

- **Integrity.** 31 of 977 Denver deciding dates are partial or missing (3.2%), which breaks the per-market cap. Non-DST partials: 5 in 2021, 2 in 2022, 2 in 2025, 13 in 2026; plus 4 missing dates in 2021.
- **Transfer.** From 10-23 Denver settles on KDEN, which is outside MG-2/B (SoP), so a KBKF history result would not transfer.

Denver per-market scores are reported descriptively.

## 6. Statistic, power, MDE

6.1 **Statistic.** For arm X and deciding date t:

- d_X(t) is the mean over the US10 rows at hours 13–16 of [Brier_X − Brier_S], using the per-row multi-band Brier (the R-A/K112 LOYO unit; base Brier ≈ 0.85).
- The point estimate is mean_t d_X(t).

The SE uses SD(d_X) × √κ / √n:

- ρ̂ is the lag-1 autocorrelation of d_X over consecutive kept dates within each season-year, pooled.
- Pairs that straddle a dropped date or a fold boundary are skipped.
- κ_AR = (1+ρ̂)/(1−ρ̂), and κ = max(κ_AR, 1.318).

The two-sided p-value comes from z. Two CIs are used:

- **Wide CI.** Uses κ_wide = max(κ, κ_block3), where κ_block3 is the variance ratio of block-3 date-means to the date-clustered SE (method rule 7). Both CIs are reported.
- **Per-market CI.** The same construction on that market's per-date series (hours 13–16), unadjusted for multiplicity.

6.2 **Variance basis (stated, outcome-blind).** The row-109 receipt is `C:\t\l48\rp2_power_v1.json`, sha256 `2380229d6f430a4dcddcc7ff64745fcd1df8fee0383b68f7c523dae477f46306`. It gives:

- per-date SD 0.016304 over 300 Aug–Sep dates, at 65.5 rows/date;
- lag-1 ρ 0.137;
- AR(1) inflation 1.318 (block-3: 1.193).

From this, σ_eff = 0.016304·√1.318 = **0.01872**.

- **Row-count inflation for this design.** Hours 13–16 × 10 markets is about 40 rows/date against 65.5, so σ is scaled by √(65.5/40) = 1.28 to give **σ_dec = 0.0240**. This is an upper bound for that factor, because it assumes independent rows.
- **Larger caveat.** Row-109 is a near-twin contrast. X−S against the zero-parameter MG-1 out of season is likely wider, so the table below runs to 4×σ_eff.

6.3 **MDE80 per arm.** n ≈ 956 − 6 DST ≈ 950 (D: ≈ 810). The Holm worst step is z = 2.498, so MDE80 = 3.340·σ/√n. Method rule 7's 4–7% futility-look inflation is applied as ×1.07.

| σ basis | MDE80 (A–C, ×1.07) | Power at −0.0057 | Futility false-stop at −0.0057 |
| --- | --- | --- | --- |
| σ_eff 0.0187 | 0.0022 | ≈ 1.00 | < 0.001 |
| σ_dec 0.0240 | 0.0028 | ≈ 1.00 | ≈ 0.004 |
| 2×σ_eff 0.0374 | 0.0043 | ≈ 0.98 | ≈ 0.05 |
| 3×σ_eff 0.0562 | 0.0065 | ≈ 0.73 | ≈ 0.12 |
| 4×σ_eff 0.0749 | 0.0087 | ≈ 0.44 | ≈ 0.20 |

- Arm D, at n ≈ 810, has an MDE about 8% larger.
- Per-fold MDE80 (about 160 dates, σ_dec, unadjusted) is about 0.0053, so per-fold signs are reported but not tested.
- Method rule 16 (power ≥ 0.5 at edge size) is met up to 3×σ_eff and fails at about 4×σ_eff.
- **Pre-declared:** the realised power (power at −0.0057 using that arm's own σ̂) is reported with every result. A KILL through a Holm failure with realised power below 0.5 is labelled "KILL (underpowered)". It is still a kill for this row, but it does not count as evidence against the lever family.
- The realised population counts, i.e. scored rows per hour and arm after §5 drops including C's non-empty pools, are computed before freeze from inputs only and appended to the freeze commit.

## 7. V4→V5 outcome-blind gate

**NBM versions.**

| Version | History and serving dates |
| --- | --- |
| V4.0 | to 2023-01-17 |
| V4.1 | from 2023-01-18 |
| V4.2 | from about 2024-05 |
| V4.3 | from mid-2025 through 2026-05-05 |
| V5.0 (serving) | 07Z from 2026-05-06 |

Training and deciding rows are all V4.x (§1). **The history result is scoped to V4, and the forward test is the V5 confirmation.** The following gate must pass before the forward gate can open.

**Inputs only (no labels, no outcomes).** For each US10 market, two distributions are compared:

- (NBP07 TXN mean − WU observed temperature at 07 local);
- TXNSD.

They are compared between the V5.0 dates 2026-05-06..05-26 and the same calendar window in V4.x years 2023–2025. The V4.3 dates of 2026 Jan–May 05 are a within-year reference.

**FLAG** if any of these holds:

- the pooled |SMD| on the TXN-minus-obs feature is > 0.25;
- the pooled TXNSD median ratio V5/V4 is outside [0.8, 1.25];
- more than 3 of 10 markets individually exceed |SMD| > 0.5.

**Handling.**

- A FLAG closes the forward gate pending a master ruling.
- The gate is computed and reported before any arm score, and its result cannot be revised after scores are seen.
- It rests on 21 V5.0 dates, so it is low-powered: a PASS means "no gross shift seen", not equivalence.
- The V5 sliver's arm scores (§1) are descriptive and are reported after the gate.

## 8. Futility and decision

8.1 **50% futility look (method rule 7).**

- **When.** After folds 2021, 2022 and 2023 are scored: 483 of 956 calendar dates, about 50%. For D, which uses 2021–2025, this is about 59% of its dates. Declared as is.
- **Rule.** Each arm whose point is > **−0.00285** (a fixed number, half of −0.0057, not half of the data-dependent G) is stopped as FUTILE.
- **Failure rates.** See the table in §6.3.
- **After the look.** There is no efficacy stopping, and survivors continue to all folds. A FUTILE arm keeps its Holm slot with p := 1 (§4.3). Arm A is scored to completion regardless.
- **Reporting.** Both the date-clustered and block-3 intervals are reported at the look.

8.2 **Final outcome per arm** (exactly one, checked in this order):

1. **HALTED.** Any HALT condition fired: C-0, C-b, §2's assertions, §3.2's assertion, or §5.2's cap.
   - The arm has no verdict.
   - A repair needs a written, reviewed amendment made before any arm score has been read.
   - Once any arm score exists, no re-run is allowed: the arm stays HALTED and the row reports it.
2. **FUTILE.** Stopped at §8.1.
3. **KILL.** Any one of:
   - X−S fails Holm;
   - the point is ≥ 0;
   - (C, D only) X−A fails its kill screen;
   - any single market's per-market 95% CI lies entirely above 0;
   - more than 2 of 6 folds have d > 0 (D: more than 2 of 5).
   - Tagged "(underpowered)" as defined in §6.3.
4. **SURVIVES-history.** Everything else. Survival is V4-scoped and is not an adoption.

8.3 **Selection.** For each survivor, compute its own G (§9.1). The forward candidate is chosen as follows:

- It is the survivor with the most negative point *among survivors whose point is ≤ their G*.
- If the best survivor fails its G but another survivor passes, the one that passes is the candidate.
- If none passes, there is no forward test.
- The selection is disclosed. The forward test re-tests the candidate from zero, and the history point is not carried as evidence.

## 9. Forward gate (binding)

Forward dates are used only if **all** of the following hold:

1. **History point.** The candidate's history point is ≤ **G**.
   - Formula: G = min(−0.0057, −2·1.96·σ̂/√166), where σ̂ = that arm's per-date SD on the deciding tier × √κ, with the κ floor of 1.318 applied.
   - Derivation: the forward window 2026-12-17..2027-05-31 is 166 dates. Method rule 6 sizes from half the effect with power ≥ 0.5, i.e. effect/2 ≥ 1.96·σ/√166.
   - At σ_eff 0.01872 this gives 2·0.002848 = **0.0057**. At σ_dec it gives 0.0073.
   - G is never looser than −0.0057.
2. **V5 gate.** The §7 gate did not FLAG, or master ruled the FLAG through.
3. **Embargo.** The owner OKs a named forward embargo line starting 12-17.
   - No forward date is read before both the PT-1 look and the F8-MH look (01-26) have been taken.
   - The forward look order follows freeze time (method rule 9).

The forward test is a separate prereg. Nothing here touches MG-2, `release-binding.json`, the B-bound files or PT-1.

PT-1's §5.4 retrain-window date drop does not apply here, because P3d_N is not retrain-family (B design §0(c)). This row does not change that.

## 10. Data (approved free official; inputs only before freeze)

| Input | Volume | Source | Notes |
| --- | --- | --- | --- |
| NBM 07Z NBP text, Dec 17–May 31 2021–25 | 830 dates, ≈ 1.2 GB | NOAA AWS open data | 2021-01-22 has no 07Z (disclosed) |
| NBM 01Z/00Z NBP text, 8 absent/late dates | ≈ 0.02 GB | NOAA AWS | §5.2 |
| NBM 07Z NBP text, Jun–Jul 2021–25 | ≈ 305 dates, ≈ 0.43 GB | NOAA AWS | Training rows for arms A, C, D |
| R-P2 IEM pool extension, all non-Aug–Sep months | ≈ 50 GB streamed | IEM ASOS, serial with 5 s spacing as in L48 | Stream-and-discard to station blocks |
| 2026 Jan–May 26 NBP 07Z | Already local (L47b, 146 dates) | — | V4.3 / V5.0 |

- Heavy steps run only through `scripts\ops\workstation_heavy.ps1 -Queue`.
- C: free space stays ≥ 40 GiB at all times. Fetches check free bytes before each batch and stop below 45 GiB. Raw IEM pages are discarded after block extraction.
- Fetches may start once this draft has been sent to the coordinator. They are inputs only: no label is read, and nothing is fitted or scored before freeze.

## 11. Data reuse disclosure

- **2026 Jan–May was read before.**
  - K112 G0 read it (descriptive scores) and K112 selected (W, λ) on 2026-01-15..05-26, so D's deciding statistic excludes fold 2026 (§4.2).
  - Row 113 step 2 read counts only.
- **Drafting exception.** While drafting, L59 opened K112's `g2_freeze_table.json` to read the frozen (W, λ).
  - The file also holds K112's aggregate dev Brier sums for 2026 Jan–May at h07–h12.
  - Those are K112's already-published dev numbers, at pre-13 hours, and are not row-28 scores. No design choice used them.
- **Earlier use of Dec 17–May 31 2021–2025 labels.** They were used by earlier full-year and Jan–Jul work: the P3F arm and the PIT corpora `3a7034d2`, `672a1f57` and `ece9d1c2`. No row-28 arm has been scored on them. This is why the result is history-only and needs a forward confirmation.
- **Never opened.** `C:\t\l2\p2` and all panel stores are never opened (names only).

## 12. Timeline

1. Draft 11-02.
2. Fresh review.
3. Coordinator.
4. Master.
5. Freeze.

Input fetches start when the draft is sent. Fits and scores happen only after freeze. Target: a history result by about 11-20, so that a 12-17 forward start stays possible.

## 13. Related lever statuses (no action here)

- **22a AIFS:** needs an owner-opened named test (recorder dates after 09-29).
- **Row 23:** waits on this row's base.
- **Rows 19 and 26:** stay parked.

## 14. Review log

r1 had one fresh Opus 5.5 review, given the draft and the script only. Verdict: READY-AFTER-MAJORS. It raised 9 MAJOR, 9 MINOR and 4 NIT findings.

All 9 MAJORs are folded into r2:

1. Dec–May feature map frozen (§3.2).
2. The bound builder's per-row NBM availability adopted; no imputation on scored rows (§3.3, §5.2).
3. The fold-2026 leak closed by season-year folds (§3.4).
4. Pool-station rows on held-out dates excluded (§3.4, §4.1).
5. V5.0 dates moved out of the deciding tier (§1), flagged for master.
6. Futility × Holm made explicit (§4.3, §8.1).
7. D's fold counts fixed (§4.2, §8.2).
8. Wide and per-market CIs defined (§6.1).
9. HALTED added as an outcome (§8.2).

MINORs folded:

- named row sources and the MG-1 reference (§2, §3.3);
- C-0 defined on the R-A corpus definition with seeds (§3.5);
- 3× and 4× σ rows plus the underpowered label (§6.3);
- rule-7 inflation and the block-3 interval (§6.3, §8.1);
- corrected futility fraction (§8.1);
- survivor and G tie (§8.3);
- the AR(1) estimator (§6.1);
- D's window start (§4.2);
- branch paths for the frozen inputs (§4).

NITs folded:

- what counts toward the cap (§5.2);
- the DST numerator note (§5.1);
- the S_bound centre artefact (§2);
- the boundary-buffer justification (§3.4).
