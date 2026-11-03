# Row 28 — year-round P3d_N refit, HISTORY-ONLY kill-only prereg (DRAFT r4)

Status: **DRAFT, NOT FROZEN.** Nothing in this file binds until master reviews
it and a freeze commit records its sha256. Drafted by lane L59 on the WS
(non-capture) on 2026-11-02 from origin/master `52d97f75b`, outcome-blind: no
row-28 label, outcome, settlement value or model score was read to write it.
Only metadata was read: row counts, dates, S3 listings, manifests, rule text and
code (one exception disclosed in §11). r2 folds the MAJORs of one fresh review
(§14). r3 applies master's 11-02 rulings (1)–(3) on r2 (§14). r4 folds the second
independent review of r3 (3 MAJOR, 9 MINOR) and master's rulings on paired
evaluation, arm C's training gap and uniform market NBM (§14). r4-final applies
master's 2026-11-02 rulings on r4 (A–C and the rule-16 labelling, §8.4) and records the
arm C gap option (§4.1a).

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
| Deciding | The 12-17..05-31 seasons ending 2021, 2022, 2023, 2024, 2025 (2021 from 01-01) | Scores decide |
| Descriptive V4 (fold 2026) | 2025-12-17..2026-05-05 | Scored descriptively for every arm; decides nothing; never training |
| Descriptive V5.0 sliver | 2026-05-06..2026-05-26 | Labelled V5.0; decides nothing; never training; context for the §7 gate |
| Training-only | All other dates of 2021–2025 (arms A, C, D; §4) | Fit rows, never scored as deciding |
| Hard excluded | 2026-05-27..2026-07-30 (sealed panel); 2026-06-01..09-29 unused; everything ≥ 2026-09-30 | Never read, never requested |

- **Master ruling (3), 11-02:** the whole 2026 season is descriptive only, for
  every arm. Deciding = the five 2021–25 folds.
  - **2025-12-17..12-31 is NOT deciding.** Under the season-year layout (§3.4)
    it opens season-year 2026 (fold 2026), not a 2021–25 fold, so it is
    descriptive with the rest of fold 2026.
  - Master ruling (1): the V4 scope stands. 2026-01-01..05-05 is descriptive V4;
    05-06..05-26 is descriptive V5.0 and decides nothing.
- Deciding calendar size: **816 dates**
  (`scripts/cap_counts_v3.py`), folds 151 / 166 / 166 / 167 / 166 (2021..2025),
  and 811 after the 5 spring-DST dates (§5.1). 2021 starts on 2021-01-01 because
  2020-12 is not in the corpus. (r2's 977/956 and r3's "≈ 950" are superseded.)
- **r4: the final deciding set is n = 660 dates**, fixed outcome-blind and
  listed in `deciding_dates_r4.txt` (held locally at `C:\t\L59\row28\r4_deciding_dates.txt`; it is exactly the 811-date set minus the drops tabled in §1.1). Every arm and S are scored on exactly
  this set (paired, master ruling (a)1).

1.1 **Outcome-blind drops from 811 to 660 (r4).** All three causes are
structural, decided from metadata only, and apply to every arm:

| Cause | Dates | Count |
| --- | --- | --- |
| No PIT-corpus record window. The single builder (§3.3) only builds a (centre, year) window that `covered_years` finds complete for all 11 markets at hours 7–20 in the PIT forecast corpora (status rows of `coverage.jsonl` only) | 2021-01-01..03-13, 2021-03-15..03-31, 2023-12-17..2024-01-30, 2024-03-01 (leap day: no centre window reaches it), 2024-12-17..12-31 | 150 (includes 2021-01-22) |
| No 07Z bulletin posted by any 13–16 cutoff (§3.3, review m7) | 2022-01-06 (07Z posted 2022-01-07 02:47Z) | 1 |
| 07Z object absent (also in the row above) | 2021-01-22 | (0 extra) |

- Folds after the drops: 2021: 61, 2022: 164, 2023: 165, 2024: 120,
  2025: 150 (season-years).
- Of the 150 uncovered dates, 44 are complete for US10 at hours 13–16 alone; they
  are still dropped, because the bound builder's coverage rule is all markets ×
  hours 7–20 per window and is not relaxed here.
- `deciding_dates_r4.txt` sha256
  `6913484a6abb1c7f0f2083eef919699cb2f05670c52306b2ab96998e0d84bcfb` (CRLF line ends).
- **Computed by code, outcome-blind (r4-final, master ruling A).** The list is produced by
  `scripts/row28_deciding_dates_r4.py`, which reads only PIT-corpus manifests and
  `coverage.jsonl` status rows (through the bound `covered_years` and `window_days`, imported
  read-only), the 07Z NBP listing `nbp07_listing_decmay.tsv` (sha256 `a39073ad…`) and market
  timezones from `config/locations.json`. It asserts that no candidate falls in the hard
  exclusions, that record windows never overlap, and that its output hashes to `6913484a…`
  (`--expect-sha`); the r4-final run passed. The same 660 dates are committed with LF line
  ends as `deciding_dates_r4.txt` next to this file (sha256
  `a2f601baef06dc662bedb710f53392f29da826c0eaede83182311768b3105b29`; the repository's
  `eol=lf` rule normalises line ends). Both commits precede any label join. The late-07Z
  drop is computed, not listed: a date is dropped if its 07Z object is absent or its
  LastModified is after any US10 13–16 local cutoff instant. This yields 2021-01-22 (absent,
  already uncovered) and 2022-01-06 only.
- **2024-02-29 stays in the deciding set.** The deciding comparator S and every arm are
  computable on it: S is date-free, and the arms' only Feb 29 failure (the bound
  `nearest_centre`) is handled by the fixed Rule L of §3.2. Only the descriptive S_bound is not
  computable there (§3.2). No paired drop applies, and n = 660, the folds, the look and the
  §6.3/§8.4 thresholds are unchanged.
- **Descriptive fold 2026 and the V5.0 sliver cannot be built** by the single
  builder: the PIT corpora end in 2025 and the 12-24 window is covered only for
  2021 and 2022. They are reported as "not built", not scored. The §7 gate is
  unaffected (inputs only).
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
  - The reference implementation is `weather.reporting.scorecards.free_source_candidates.mg1.predict`, the module that `mg2_composite` imports. Its file sha256 is recorded at freeze.
  - **Independent check (r4, review m8).** S is computed twice: once by `free_source_candidates.mg1.predict` and once, independently, by `weather.model.mg_serve_core.mg1_band_probs` on the same (mu, sigma, band) inputs. The two must agree to 1e-12 on 50 fixed synthetic rows and on every scored row. A mismatch triggers HALT.
  - S reads only the 07Z v2_mean, as serving does (`mg2_composite.py` 87–90); rows with no 07Z by the cutoff are not scored (§3.3).
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
- **Centre per row (r4, review M1).** Each row's `centre` (and so `season`) is recomputed as `nearest_centre(target_date, <that arm's centre set>)`. The payload centre of the record file that carried the row is ignored. Example: a May 31 row arrives in the 06-07 record file; arms A, C, D keep centre 06-07, arm B maps it to 05-23.
- **Leap-day rule (fixed, pre-stated; r4-final, outcome-blind code finding).** 2024-02-29 is a deciding date (inside the covered 2024 02-22 window). The bound `nearest_centre` (`pooled_residual_model` and its `mg_serve_core` copy) builds `date(2001, month, day)` and raises `ValueError` on Feb 29.
  - **Rule L (binding for every arm, every row, training and scored):** wherever row-28 code needs a centre for a target_date of Feb 29, it calls `nearest_centre` with the same year's Feb 28 instead. Only the centre lookup is substituted; every other field (target_date, doy, fold, cutoffs, inputs, labels) keeps the real date. In every arm's centre set Feb 28 and Feb 29 both map to 02-22 (6 and 7 days from 02-22; ≥ 9 days from 03-09), so Rule L cannot change any pick. The §3.2 wrap assertion applies Rule L the same way. The scorer asserts that Rule L's pick for 2024-02-29 is 02-22 in each arm; a mismatch → HALT.
  - **The deciding comparator S is computable on 2024-02-29.** S is MG-1 C5 (§2): mu = v2_mean, sigma = max(v2_stddev, 1), the rule-4 floor and the bucket space. `mg_serve_core.mg1_band_probs` and `mg1.predict` take no date, centre or day-of-year input. The 07Z bulletin for 2024-02-29 was posted at 08:26Z, before every 13–16 cutoff. So S needs no substitution.
  - **Every arm's serve-time inputs are computable on 2024-02-29.** The market NBM, F, current_temp and the bucket space are date-free, and doy uses `tm_yday`, which is valid on Feb 29. The only Feb 29 failure in the arm path is the centre lookup, which Rule L fixes in advance. The paired rule therefore drops nothing, and n stays 660.
  - **Only the descriptive S_bound is not computable on 2024-02-29.** It runs the bound state through the bound `state_features`, which has the same Feb 29 failure and is not substituted. It is reported "not computable" on that date and never decides. Bound code is not edited.

3.3 **Rows (r4, review M1): one build function, one row per (market, date, hour), feeding S and every arm.**

- **The one build function** for every market row, scored or training, is the B-bound `pooled_residual_model.extract_market(market, centre, manifests, out_root, training_years=covered_years(centre, manifests))`, imported read-only, then `pooled_frame` and `attach_training_nbm`. It writes to a new row-28 records root, never to `C:\t\l2\records`. The 12-24 centre is built by the same call; there is no second, "direct" builder. No held cache is rebuilt (the SoP hold on the forecast_history, open_meteo_archives and reanalysis caches until a399941e lands is respected); the builder only reads the existing PIT corpora.
- **Inputs, from that one path:**

| Input | Source |
| --- | --- |
| Label `y` | `rec["final_bucket"]` (WU daily high), as the bound trainer |
| `F` (high so far) | `rec["high_so_far"]`: the max over WU hourly rows up to the cutoff (`feature_model.py` 1111–1117), exactly as the bound training builder (`pooled_residual_model.py` 430). r3's "METAR-only running max" was wrong for history and is withdrawn. No METAR history source is used. |
| `current_temp` | `rec["current_temp"]`, same WU-hourly path |
| `fh` (anchor) | NBP TXN mean from the NBM tables of §3.3b |
| `v2_stddev` (S only) | NBP TXNSD of the 07Z bulletin |

- Disclosure: serving (rule C1, `rule.md` 393–402) reads F from captured METAR. History uses the trainer's WU-hourly F for every arm and for S alike, so the comparison stays paired; the forward test is where METAR-F parity is confirmed.
- **Exactly one row per (market, target_date, hour).** Rows are keyed by target_date. A duplicate key across record windows triggers HALT (with the 15-day centre spacing and ±7-day windows none is expected).
- **NBM for scored rows (r4, review m7; dated narrowing of master's availability ruling (2): master ruling 2026-11-02 (WS relay 21:36 report)):** a scored row needs the 07Z bulletin posted (LastModified) at or before its own cutoff instant, because served MG-1 reads only 07Z. The 01Z/00Z fallback of `nbm_at_cutoff` is used for training rows only. Under this rule the only structural drop is 2022-01-06 (§1.1). Ruling (2) as first given said "newest of 07/01/00" for scored rows. Master accepted the narrowing for scored rows on 2026-11-02, applied identically to every arm and S. Training rows keep ruling (2) unchanged.
- **Training rows** use `attach_training_nbm` with `nbm_at_cutoff` (07Z, then 01Z, then 00Z, by LastModified ≤ the row's cutoff), and fill-from-forecast (L9 IMPUTE "fc") only where no cycle was posted by the cutoff (§3.3b).
- **All filters act on each row's `target_date`** (r4, review m5): fold hold-outs, arm B's Dec 17–May 31 selection, the hard exclusions and §1.1's drops. Record windows and payload centres never decide membership (the 05-23 window reaches June and the 01-08 window reaches December).

3.3b **Market-station NBM source per training month (r4, master FLAG 2: identical for arms A, B, C and D).**

| Training dates (2021–2025, inside covered windows) | Market-row NBM source | Fill-from-forecast? |
| --- | --- | --- |
| Jan 1 – May 31 | This fetch, 07Z (`nbp_station_blocks_c07.jsonl`) + the 01Z/00Z add-on | Only rows with no cycle posted by the cutoff |
| Jun 1 – Jul 29 | Gap fetch, 07Z (`nbp_station_blocks_gap_c07.jsonl`) | Only rows with no 07Z posted by the cutoff |
| Jul 30 – Jul 31, Sep 30 – Oct 2 | No centre window reaches these dates, so no rows exist | n/a |
| Aug 1 – Sep 29, Oct 3 – Dec 16 | L9 corpus `1ae4bf52` (07Z), as bound | As bound |
| Dec 17 – Dec 31 (2021, 2022 only: the only covered 12-24 windows) | This fetch, 07Z | Only rows with no cycle posted by the cutoff |

- One NBM table is built with `ols_floor_ladder nbm-corpus` from the L9 blocks plus the new blocks, with the gap blocks restricted to Jun 1 – Jul 31 so that no (market, date, cycle) appears twice.
- **Control C-0c:** on the overlapping dates Oct 3 – Dec 16, the gap fetch's market blocks must equal L9's blocks byte for byte (`block_sha256`). Mismatch → HALT.
- **Imputation cap (r4, review M2):** if more than 5% of any arm's training rows in any calendar month are fill-from-forecast, the whole run HALTs (the base inputs are shared, so the breach is not arm-specific). No month is planned to be on fill-from-forecast; any imputed rows are counted per month and reported before any score.
- The comparator stays MG-1 at hours 13–16 as served, untouched by this ruling (S never uses training rows).

3.4 **Folds: LOYO by season-year, five deciding folds (2021..2025) plus one
descriptive fold (2026).**

- Fold Y holds out the whole season-year Dec 17 (Y−1) .. Dec 16 (Y).
- No row dated inside that interval enters fold Y's training set. That covers market rows, Denver rows and pool-station rows (arm C). It also covers rows outside the deciding tier, so Jun–Dec 16 of Y is never training for fold Y.
- Fold 2026 (descriptive) holds out 2025-12-17..2026-05-26 and trains on every permitted row outside that interval: 2021-01-01..2025-12-16, minus the hard exclusions.
- No 2026-dated row is a training row for any fold.
- Training rows adjacent to the held-out season (Dec 16 of Y−1 and before) are allowed. The within-year lag-1 ρ is 0.137, so the edge leakage is negligible, and the AR(1)-inflated SE (§6) already absorbs that serial correlation.

3.5 **Control C-0 (HALT if it fails).** The builder, run on the R-A corpus definition exactly as its manifest records it (FORWARD_CENTRES records, bound years, bound seeds), must reproduce two things to 1e-9 before any deciding row is scored:

- the R-A training rows (19,657);
- the R-A per-row predictions.

**Control C-0b (r4, review M1; HALT if it fails).** The 12-24 window is new. Before any Dec 17–31 row is used, the same build call, run for the 12-09 and 01-08 centres into the new records root, must reproduce the existing `C:\t\l2\records` rows for those centres (`y`, `F`, `current_temp`, `fh`, every `x_*`) to 1e-9.

3.6 **Bucket space per arm (r4, review m6).** `buckets[market]` for an arm and fold is frozen as the union of `bucket_space` over the record payloads that contribute training rows to that arm and fold, plus every integer in [min, max] of that fold's training labels for the market. It feeds `p_clim` (the 2% mix). It never uses held-out labels.

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
- Pool stations come from the frozen classes file. Their rows are extended to all months (§10), and pool rows inside the held-out season-year are excluded (§3.4), by target_date.
- **Pool rows use exactly arm A's training dates** (the covered windows of §1.1/§3.3, by target_date), so C's training dates equal A's and only the station set differs.
- **Serve-time inputs (master ruling (a)1).** At scoring, arm C needs the same market inputs as arm A (the class is a fixed property of each market station); pool rows are training-only. No deciding date lacks an input C needs, so C is scored on the same 660 dates as every arm and S, and no extra drop applies.
- **Training gap (master ruling (a)2/(a)3) — option: [FINALISED AT GAP-MANIFEST TIME, see §4.1a].**

4.1a **Arm C training-gap option.** [placeholder: finalised when the IEM gap manifest lands, deadline 11-03 06:00]
- R-P2's controls run first: C-0 (reproduce R-A to 1e-9) and C-b (empty-pool check).
- C must also pass R-P2's screen against A (C−A). KILL if any of:
  - the point is ≥ −0.0005;
  - the *wide* 95% upper bound (§6.1) is ≥ 0;
  - any market's 95% lower bound is > 0 (per-market CI, §6.1);
  - more than 1 of the 5 deciding folds has d > 0 (R-P2's rule as frozen).
- Disclosure: the frozen class rule and the pool corpus `a57e10a6…` are Aug–Sep only. The extension to other months is new data, not a re-read.

4.2 **Arm D** applies the frozen K112 formula on top of arm A's mu: mu' = mu − λ·clip(b_recent − b_train, ±3°F), where d = NBP07 mean − WU high.

- Frozen rule: `rule_x36_trailing_final.md`, sha256 `032c8dc3bf33fd7dc549a5a9e93ed04d86809678a087fc43766e272b99f077f2`, on `origin/claude/x36-v5-reopen-20261101` under `docs/research/x36-v5-reopen-2026-11-01/`.
- **(W, λ) is fixed now, with no search on the deciding tier.**
  - K112's freeze table (`g2_freeze_table.json`, same folder, sha256 `383e4a6a1b8f4449e09f046dcff6bef90903df311115623d31b16974cf8ca449`) froze picks only for h07–h12. It has none for 13–16.
  - Pre-declared "nearest frozen hour" rule: hours 13–16 all use the h12 pick, **W = 14, λ = 0.25**.
- b_recent is the mean d over the W most recent *available* dates strictly earlier than the target, drawn from the previous 2W calendar days. If fewer than W such dates exist (for example early January 2021, which has no Dec 2020 data), no correction is applied (mu' = mu).
- b_train keeps the frozen K112 definition: the per-market mean d over Aug 1..Sep 29, recomputed inside each fold from that fold's training years only.
- **Sources for d (r4, review m4).** d uses the **07Z** NBP mean only (K112's frozen definition), not `nbm_at_cutoff`. 07Z market values: Dec 1–16 from the L9 corpus `1ae4bf52` (covers Oct 3 – Dec 16), Dec 17 – May 31 from this fetch. WU high: the WU daily summary high of each prior date. A prior date with no 07Z or no complete WU day is simply not "available" for b_recent.
- Prior-day WU highs and 07Z values from dates inside the held-out season are allowed in b_recent: they are real-time information at the target date's cutoff (the trailing window looks only strictly earlier). They are never training rows.
- Disclosures:
  1. K112's only measured gain is in season, Aug 15–Sep 29: G1 pooled −0.00226 [−0.00378, −0.00079], and the h12 interval spans 0.
  2. On 2026 Jan–May only 24 of 60 market-months improved in G0, and May over-corrected. K112's (W, λ) were selected on 2026-01-15..05-26. Under master ruling (3) every arm, D included, decides on folds 2021–2025 only, so no D-specific exclusion remains.
  3. X30: an intercept win may be a bias correction, not information.
- D must also beat A (D−A) under the same four kill conditions as C−A, on the same five deciding folds.

4.3 **Multiplicity.**

- The primary family is four contrasts, A−S, B−S, C−S and D−S, corrected by **Holm over 4 at two-sided family-wise α = 0.05**. The most stringent step is α = 0.0125, z = 2.498.
- The family is fixed at 4: a FUTILE or HALTED arm keeps its slot with p := 1.
- C−A and D−A are gatekeeping conditions inside C and D, not extra family members. C or D survives only if its X−S passes Holm *and* its X−A passes the kill screen.
- **Arm A is always scored on all folds**, even when A is itself FUTILE, because it is the reference for C−A and D−A.
- **If A is HALTED, C and D are HALTED too (r4, review M3)**: they have no valid reference, so they get no verdict and keep their slots with p := 1.
- S_bound contrasts are descriptive and uncounted.

4.4 **Hours.** The deciding hours are 13, 14, 15 and 16: the post-13 half within `b_scorer.HOURS` 07–16. Hours 07–12 are scored descriptively against the served pre-13 comparator and never decide. That comparator is the L6 stack over MG-1, with bound coefficients `07a67425…ee17e9` and state `800072c7…2ee2db`. Replacing the pre-13 half is a different question and would need its own prereg.

## 5. Integrity: cap, spring-DST rule, Denver

The r3 counts come from `scripts/cap_counts_v3.py` (v2 with the r3 deciding tier; v2 is kept for the r2 range). Both read only three inputs:

- `local_date` and `row_count` from the WU `daily_summary.csv`;
- the NBP listing;
- the L47b count.json counts.

Its output, `cap_counts_v3.json` (sha256 `0b53932a8054a10c8f8ee102726e374d6da2a2f7523c9881c3a92e3c973b0b89`, held locally at `C:\t\L59\row28\r3\`), covers the 816 deciding dates. A day counts as partial if its WU `row_count < 18` (`settlement_ledger.COMPLETE_DAY_MIN_ROWS`). The v2 output (`803b5416…41036e7`) covered r2's 977-date range and is superseded.

5.1 **Spring-DST rule (pre-declared).** The US spring-forward day (second Sunday of March) is excluded from the deciding tier for every market and year.

- It is structurally partial: every US10 market has exactly 4 partial DST days among the 5 deciding years, which accounts for 40 of the 47 US10 partial+missing market-dates. (r2 said "5 in 2021–2025"; that count included 2026-03-08 and is corrected here.)
- Five DST dates are dropped (2021–2025), whether or not each is partial in a given market. 2026-03-08 is in the descriptive fold and is dropped there by the same rule.
- Fall-back days are not in the deciding tier.
- The script keeps a *missing* DST-day value in the numerator while removing DST days from the denominator. This is conservative and moot here: US10 has 0 missing days in the deciding range.

5.2 **Pooled integrity cap.**

- **Baseline (pre-freeze):** after 5.1, US10 partial+missing is 7 of 8,110 market-dates, **0.086%** (non-DST partials: austin 2, houston 2, dallas 1, seattle 1, san-francisco 1; 0 missing). **On the r4 set of 660 dates it is 0 of 6,600** (all seven fall in dates §1.1 already drops; Denver, descriptive, has 4). Partial and missing market-dates are dropped from the deciding tier for every arm and S (paired) and never imputed.
- **What counts toward the cap at run time.** Every deciding US10 market-hour of the 660-date set that cannot be scored, for any reason:
  - WU partial or missing;
  - no 07Z at the cutoff (§3.3);
  - a missing `F` or `current_temp` in the built row;
  - for arm C, an empty pool.
- Any such row is dropped from every arm's and S's comparison (paired, master ruling (a)1); the date list and n are restated in the pre-score integrity report.
- **HALT before any arm score is computed** if any of these holds:
  - the pooled dropped share exceeds **1.0%**;
  - any single market exceeds **3.0%**;
  - any single fold loses more than **2.0%**.
- **HALT scope (r4, review M3, consistent with §8.2):** an empty-pool breach HALTs arm C only (so D and A proceed). Every other cap breach, the §3.3b imputation cap, and C-0 / C-0b / C-0c / §2 / §3.2 / duplicate-key assertion failures HALT the whole run (all four arms).
- **NBP availability** is per row (§3.3), not a fixed clock. The listing (`nbp07_listing_decmay.tsv`, sha256 `a39073ad0793dd7d8f0a3010ebd3cb1213bf70a799e37f68faa681af31443e17`) shows:
  - 2021-01-22 has no 07Z object;
  - 7 objects were posted at or after 12Z (2021-02-11, 2022-01-06 [posted the next day], 2023-01-20, 2023-05-24, 2024-04-16, 2024-04-21, 2024-05-15).
- For those 8 dates the 01Z and 00Z text was fetched (used for training rows only, §3.3). For scored rows only 07Z counts; applied to the 13–16 cutoffs, the only date dropped is 2022-01-06 (2021-01-22 has no bulletin at any cycle). Both are in §1.1.
- **2026 (descriptive):** NBP is present on 146/146 dates in every market (L47b counts).

5.3 **Denver.** Denver is excluded from the deciding tier and may contribute training rows. Both reasons are outcome-blind:

- **Integrity.** 17 of 816 Denver deciding dates are partial or missing (2.1%); after 5.1 it is 13 of 811 (1.6%), about 19 times the US10 rate. Non-DST partials: 5 in 2021, 2 in 2022, 2 in 2025; plus 4 missing dates in 2021. The descriptive 2026 season adds 13 more non-DST partials, so the KBKF series is deteriorating.
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

- **Wide CI.** Uses κ_wide = max(κ, κ_block3). **κ_block3 = SE²(block-3) / SE²(iid)** (r4, review m9): the kept dates of each season-year, in date order, are cut into consecutive blocks of 3 that never cross a season-year (fold) boundary; a trailing block of 1–2 dates is kept as a shorter block. SE²(block-3) is the variance of the block means of d, weighted by block size, divided by the number of blocks; SE²(iid) = SD²(d)/n. Both CIs are reported.
- **Per-market CI.** The same construction on that market's per-date series (hours 13–16), unadjusted for multiplicity.

6.2 **Variance basis (stated, outcome-blind).** The row-109 receipt is `C:\t\l48\rp2_power_v1.json`, sha256 `2380229d6f430a4dcddcc7ff64745fcd1df8fee0383b68f7c523dae477f46306`. It gives:

- per-date SD 0.016304 over 300 Aug–Sep dates, at 65.5 rows/date;
- lag-1 ρ 0.137;
- AR(1) inflation 1.318 (block-3: 1.193).

From this, σ_eff = 0.016304·√1.318 = **0.01872**.

- **Row-count inflation for this design.** Hours 13–16 × 10 markets is about 40 rows/date against 65.5, so σ is scaled by √(65.5/40) = 1.28 to give **σ_dec = 0.0240**. This is an upper bound for that factor, because it assumes independent rows.
- **Larger caveat.** Row-109 is a near-twin contrast. X−S against the zero-parameter MG-1 out of season is likely wider, so the table below runs to 4×σ_eff.

6.3 **MDE80 per arm (r4, all arms and S paired on the same n = 660, √n = 25.69).** The Holm worst step is z = 2.498, so MDE80 = 3.340·SE. **Basis (r4, review m10):** both the MDE and the power columns use the inflated SE = 1.07·σ/√660 (method rule 7's 4–7% futility-look inflation at its upper end). Power is P(z > 2.498) at a true −0.0057. The futility column uses the §8.1 look at n = 390 with the uninflated SE σ/√390 (that look is the source of the inflation).

| σ basis | MDE80 (×1.07) | Power at −0.0057 (×1.07) | Futility false-stop at −0.0057 |
| --- | --- | --- | --- |
| σ_eff 0.0187 | 0.0026 | ≈ 1.00 | ≈ 0.001 |
| σ_dec 0.0240 | 0.0033 | ≈ 1.00 | ≈ 0.010 |
| 2×σ_eff 0.0374 | 0.0052 | ≈ 0.88 | ≈ 0.07 |
| 3×σ_eff 0.0562 | 0.0078 | ≈ 0.48 | ≈ 0.16 |
| 4×σ_eff 0.0749 | 0.0104 | ≈ 0.25 | ≈ 0.23 |

- History of this table: r2 (n ≈ 950, no ×1.07 on power), r3 (n = 811; the second review's inflated power was 0.94 / 0.58 / 0.32 at 2× / 3× / 4×). r4's drop from 811 to 660 (§1.1) raises every MDE by √(811/660) − 1 ≈ 11%.
- Per-fold MDE80 (≈ 130 dates, σ_dec, unadjusted) is ≈ 0.0059, so per-fold signs are reported but not tested.
- Method rule 16 (power ≥ 0.5 at edge size) is met up to 2×σ_eff and fails from ≈ 2.9×σ_eff (3×: 0.48). Master accepted n = 660 with this loss (2026-11-02). The labelling of a non-passing arm on an underpowered run is pre-stated in §8.4 (r4-final): it is INCONCLUSIVE-UNDERPOWERED, not KILL. r4's "KILL (underpowered)" label is withdrawn.
- **Pre-declared:** the realised power of §8.4 is reported with every result.
- The realised population counts, i.e. scored rows per hour and arm after §5 drops including C's non-empty pools, are computed before any score from inputs only and committed with the pre-score integrity report.

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

- **When.** After folds 2021, 2022 and 2023 are scored: **390 of the 660** deciding dates (61 + 164 + 165), 59.1%, for every arm. A fold-aligned look cannot land closer to 50% (two folds would be 34%); the 59% placement is declared as is. (r3's "≈ 479"/"480" were the 811-date counts with and without 2021-01-22; both are superseded.)
- **No peeking past the look (r4, review m11).** Held-out rows of folds 2024 and 2025 are not joined to their labels until the look's result file (per-arm point, SE, FUTILE flags) is written and committed to the branch with its sha256. The commit sha is cited in the final report. (Fold-2024/2025 labels used as *training* rows of folds 2021–2023 are not held-out rows and are not affected.)
- **Rule.** Each arm whose point is > **−0.00285** (a fixed number, half of −0.0057, not half of the data-dependent G) is stopped as FUTILE.
- **Failure rates.** See the table in §6.3.
- **After the look.** There is no efficacy stopping, and survivors continue to all folds. A FUTILE arm keeps its Holm slot with p := 1 (§4.3). Arm A is scored to completion regardless.
- **Reporting.** Both the date-clustered and block-3 intervals are reported at the look.

8.2 **Final outcome per arm** (exactly one, checked in this order):

1. **HALTED.** A HALT condition fired, with the scope of §5.2 (r4, review M3):
   - **whole run (all four arms):** C-0, C-0b, C-0c, §2's S assertions, §3.2's wrap assertion, the duplicate-key check, the §3.3b imputation cap, or any §5.2 cap breach other than an empty pool;
   - **arm C only:** C-b (empty-pool check) or an empty-pool cap breach;
   - **arms C and D:** whenever arm A is HALTED (§4.3).
   - **Order (r4, review m8):** every HALT assertion runs on predictions and inputs **before any label is joined**, so a HALT can never fire after a score exists.
   - The arm has no verdict.
   - A repair needs a written, reviewed amendment made before any arm score has been read.
   - Once any arm score exists, no re-run is allowed: the arm stays HALTED and the row reports it.
2. **FUTILE.** Stopped at §8.1.
3. **KILL** (a true kill). Any one of the *crossing* conditions, at any power:
   - the X−S point is > −0.00285 (it crosses the §8.1 futility line; this includes a point ≥ 0);
   - any single market's per-market 95% CI for X−S lies entirely above 0;
   - (C, D only) the X−A point is ≥ −0.0005, or any market's X−A 95% lower bound is > 0 (§4.1).

   Or any one of the *failure-to-show* conditions, **only when the contrast that failed is adequately powered (§8.4)**:
   - X−S fails Holm;
   - more than 2 of the 5 deciding folds have X−S d > 0;
   - (C, D only) X−A's wide 95% upper bound is ≥ 0, or more than 1 of the 5 deciding folds has X−A d > 0.
4. **INCONCLUSIVE-UNDERPOWERED** (r4-final, master ruling 2026-11-02). No crossing condition holds, at least one failure-to-show condition holds, and the contrast that failed is not adequately powered (§8.4). §8.4 states the consequences.
5. **SURVIVES-history.** Everything else. Survival is V4-scoped and is not an adoption.

8.3 **Selection.** For each survivor, compute its own G (§9.1). The forward candidate is chosen as follows:

- It is the survivor with the most negative point *among survivors whose point is ≤ their G*.
- If the best survivor fails its G but another survivor passes, the one that passes is the candidate.
- If none passes, there is no forward test.
- The selection is disclosed. The forward test re-tests the candidate from zero, and the history point is not carried as evidence.

8.4 **Underpowered labelling and "adequate power" (r4-final, master ruling 2026-11-02; method rule 16).**

- **Master's rule.** A non-passing result on an underpowered run is INCONCLUSIVE-UNDERPOWERED, not KILL. A true KILL needs adequate power at the observed κ, or a point estimate crossing the futility line (point > −0.00285, §8.1). This section is the pre-stated labelling that §6.3 refers to.
- **Adequate power, defined numerically.** For a contrast with per-date differences d over the n scored dates, let κ_wide = max(κ, κ_block3) (§6.1, with κ ≥ 1.318) and SE_wide = 1.07 · SD(d) · √κ_wide / √n (the ×1.07 basis of §6.3). The realised power is:
  - X−S (Holm worst step): P = Φ(0.0057 / SE_wide − 2.498);
  - X−A gate (C, D; unadjusted two-sided 95%): P = Φ(0.0057 / SE_wide − 1.960).

  The contrast is **adequately powered iff P ≥ 0.80**. For X−S this is SE_wide ≤ 0.0057 / 3.340 = **0.001707**; at n = 660 that is a realised σ̂ = SD(d)·√κ_wide ≤ **0.0410 ≈ 2.19×σ_eff**. For X−A it is SE_wide ≤ 0.0057 / 2.802 = 0.002034 (σ̂ ≤ 0.0489 ≈ 2.61×σ_eff at n = 660).
- **Bands of the realised σ̂ (X−S, n = 660), pre-stated:**

  | Realised σ̂ = SD(d)·√κ_wide | Power at −0.0057 (×1.07) | Rule 16 | A failure-to-show condition gives |
  | --- | --- | --- | --- |
  | ≤ 2.19×σ_eff (≤ 0.0410) | ≥ 0.80 | met | KILL |
  | 2.19–2.93×σ_eff | 0.50–0.80 | met | INCONCLUSIVE-UNDERPOWERED |
  | ≥ 2.93×σ_eff (≥ 0.0548; the "≈ 2.9" of §6.3) | < 0.50 | fails | INCONCLUSIVE-UNDERPOWERED, rule-16 failure flagged |

  A crossing condition gives KILL in every band.
- **When it is computed.** κ_block3, κ and SD(d) need scored differences, so the realised power cannot exist before the label join. It is computed mechanically from (SD(d), κ_wide, n) alone by the formula above, with no other input or judgement, and is written into the same result file as the point and SE before the verdict is assigned. Everything else is fixed before any label join: the formula, the 0.80 threshold, the edge −0.0057, the ×1.07 factor, the z values, n = 660 and the thresholds 0.001707 and 0.002034. At the §8.1 look the same quantity is reported (n = 390, uninflated SE) for information only; FUTILE is decided by the point alone.
- **Consequences of INCONCLUSIVE-UNDERPOWERED.**
  - The arm is not a survivor. It does not enter §8.3 and cannot ask for a forward test from this row.
  - It does not count as evidence against the lever. The K ledger row is recorded **open**, not killed, with its realised power and point.
  - It keeps its Holm p as computed (only FUTILE sets p := 1).
  - **Reopen trigger.** The lever may be reopened under a new prereg by either (a) more deciding seasons becoming buildable (for example PIT corpora extended past 2025, or the 150 uncovered dates of §1.1 gaining record windows) such that this section's formula, at this run's observed SD(d) and κ_wide and the new n, gives power ≥ 0.80; or (b) an owner-opened forward lane for the arm. Neither changes this row's history verdict.
- **Reporting.** Every arm reports: outcome (§8.2), point, SE_wide, κ, κ_block3, κ_wide, realised power and band.

## 9. Forward gate (binding)

Forward dates are used only if **all** of the following hold:

1. **History point.** The candidate's history point is ≤ **G**.
   - Formula: G = min(−0.0057, −2·1.96·σ̂/√166), where σ̂ = that arm's per-date SD on the deciding tier × √κ, with the κ floor of 1.318 applied.
   - Derivation: the forward window 2026-12-17..2027-05-31 is 166 dates. Method rule 6 sizes from half the effect with power ≥ 0.5, i.e. effect/2 ≥ 1.96·σ/√166.
   - At σ_eff 0.01872 this gives 2·0.002848 = **0.0057**. At σ_dec it gives 0.0073.
   - G is never looser than −0.0057.
   - r3 recompute: the √n inside G is the *forward* count (√166 = 12.88) and does not change with the history tier. What r3 changes is σ̂, now estimated on the 811 deciding dates (2021–25 folds only), and the history-side check: at −0.0057 with σ_eff the history z is 0.0057/(0.01872/√811) = 8.7 (σ_dec 6.8; 2× 4.3), so a true gate-sized effect clears Holm with ample room on the new count.
   - The 2026 descriptive fold never enters σ̂ or the history point.
   - r4: σ̂ is estimated on the 660 paired deciding dates. The history z at −0.0057 becomes 0.0057/(0.01872/√660) = 7.8 (σ_dec 6.1; 2× 3.9). G itself is unchanged.
2. **V5 gate.** The §7 gate did not FLAG, or master ruled the FLAG through.
3. **Embargo.** The owner OKs a named forward embargo line starting 12-17.
   - No forward date is read before both the PT-1 look and the F8-MH look (01-26) have been taken.
   - The forward look order follows freeze time (method rule 9).

The forward test is a separate prereg. Nothing here touches MG-2, `release-binding.json`, the B-bound files or PT-1.

PT-1's §5.4 retrain-window date drop does not apply here, because P3d_N is not retrain-family (B design §0(c)). This row does not change that.

## 10. Data (approved free official; inputs only before freeze)

| Input | Volume | Source | Notes |
| --- | --- | --- | --- |
| Input (fetched 11-02/03, done) | Requests | Downloaded / kept | Manifest |
| --- | --- | --- | --- |
| NBM 07Z NBP whole bulletins, 2021-01-01..2025-12-31 Dec 17–May 31 | 831 | 26.06 GB streamed and discarded; 0.92 GB of blocks (11 markets + 300 pool) | `manifest_nbp.json` `2948b718…259b6f5f` |
| NBM 01Z/00Z add-on, 8 dates | 16 | 0.32 GB; 0.01 GB blocks (2021-01-22 absent at every cycle) | same |
| R-P2 IEM extension, Dec 16 – Jun 1 windows 2021–25 | 3,110 | 0.87 GB kept | `manifest_iem.json` `17aca6d1…699ad61f` |
| Gap NBM 07Z (master ruling (a)3), Jun 1 – Jul 31 and Oct 1 – Dec 16, 2021–25 | 690 | [finalised at gap-manifest time] | [§4.1a] |
| Gap IEM, May 31 – Dec 17 windows 2021–25 | 3,110 | [finalised at gap-manifest time] | [§4.1a] |
| 2026 Jan–May 26 NBP 07Z | already local (L47b, 146 dates) | — | V4.3 / V5.0 (§7 gate only) |

- **IEM estimate miss (master ruling (a)4):** the IEM extension was estimated at ≈ 50 GB but came to 0.87 GB, because L48's Aug–Sep IEM for the 300 pool stations had been 0.29 GB; the ≈ 50 GB figure conflated it with the whole-bulletin NBM stream (≈ 26 GB).
- Fetcher: `scripts/row28_fetch_v1.py` (Dec–May, add-on, IEM) and `scripts/row28_fetch_v2.py` (gap mode), reusing the sha-pinned L48 helpers `station_pool_fetch_v2.py` `98ddd33e…`.

- Heavy steps run only through `scripts\ops\workstation_heavy.ps1 -Queue`. Fetches run as network-bound light work (master 11-01 ruling) or via `-Queue`.
- The request list is generated so that 2026-05-27..07-30 and every date ≥ 2026-09-30 are excluded at generation time, and the fetcher asserts it before the first request; nothing in those ranges is requested, even into a discard stream.
- Before freeze, only integrity counts are inspected (dates, row counts, posted times); no temperature or obs value. Each fetch writes a run receipt with URLs, byte totals and shas.
- C: free space stays ≥ 40 GiB at all times. Fetches check free bytes before each request and stop below 45 GiB. NBM bulletins are discarded after block extraction; IEM CSVs are small and kept.
- All fetches are inputs only: no label, settlement or observation value was opened, and nothing is fitted or scored before freeze.

## 11. Data reuse disclosure

- **2026 Jan–May was read before.**
  - K112 G0 read it (descriptive scores) and K112 selected (W, λ) on 2026-01-15..05-26.
  - Row 113 step 2 read counts only.
- **Drafting exception.** While drafting, L59 opened K112's `g2_freeze_table.json` to read the frozen (W, λ).
  - The file also holds K112's aggregate dev Brier sums for 2026 Jan–May at h07–h12.
  - Those are K112's already-published dev numbers, at pre-13 hours, and are not row-28 scores. No design choice used them.
- **Earlier use of Dec 17–May 31 2021–2025 labels.** They were used by earlier full-year and Jan–Jul work: the P3F arm and the PIT corpora `3a7034d2`, `672a1f57` and `ece9d1c2`. No row-28 arm has been scored on them. This is why the result is history-only and needs a forward confirmation.
- **Never opened.** `C:\t\l2\p2` and all panel stores are never opened (names only).
- **Master ruling (3), 11-02, on this disclosure.** The 2026 season (2025-12-17..2026-05-26) is DESCRIPTIVE-ONLY FOR EVERY ARM; deciding = the 2021–25 folds only. Reasons as ruled: K112's published dev Brier sums for 2026 were seen; 2026 Jan–May was already spent as K112 dev data; the power cost is ≈ 8–10% (§6.3: ≈ 8%). 2025-12-17..12-31 falls in fold 2026 under §3.4 and is therefore descriptive too.

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

**r3 (master rulings on r2, 11-02):**

1. V4 scope kept. 2026-01-01..05-05 is descriptive V4; 05-06..05-26 is descriptive, labelled V5.0, decides nothing, and is context for the §7 gate (§1, §7).
2. The NBM availability rule is accepted as drafted: scored rows take the newest of 07Z/01Z/00Z posted by the cutoff with no imputation; training rows use fill-from-forecast (§3.3). The 8-date 01Z/00Z add-on fetch is approved.
3. 2026 is descriptive for every arm; deciding = 2021–25 folds; 2025-12-17..12-31 is in fold 2026 and descriptive (§1, §3.4, §4.1, §4.2, §8.2, §11). Cap counts recomputed with `cap_counts_v3.py` (§5); MDE80 recomputed on n = 811 for all variance multiples (§6.3); the forward-gate √n note added (§9.1); futility look re-placed at 59% (§8.1). r2's "5 DST partials per market in 2021–2025" is corrected to 4 (§5.1).
4. Noted; no change.

**r4 (second independent review of r3 `3fe952fa…`, verdict READY-AFTER-MAJORS, 0 BLOCKER / 3 MAJOR / 9 MINOR; plus master's rulings (a)1–4 and FLAG 1–2):**

| Finding | Resolution in r4 |
| --- | --- |
| M1 scored-row build path | One builder `extract_market` for every row (§3.3); F/current_temp from the trainer's WU-hourly path, r3's METAR claim withdrawn; one row per key, centre = `nearest_centre` per arm (§3.2); control C-0b (§3.5) |
| M2 Jun–Jul anchor | Market NBM frozen per month, identical A–D (§3.3b, FLAG 2); 5%-per-arm-month imputation cap → whole-run HALT; no month planned on fill-from-forecast |
| M3 A HALTED | A HALTED ⇒ C, D HALTED (§4.3); empty-pool breach HALTs C only, all else the whole run (§5.2 = §8.2) |
| m4 D window | 07Z only; Dec 1–16 from L9 `1ae4bf52`; held-out prior-day highs allowed as real-time info (§4.2) |
| m5 target_date filters | All filters by target_date (§3.3, §4.1) |
| m6 bucket space | Frozen per arm and fold (§3.6) |
| m7 S on late 07Z | Scored rows need 07Z by the cutoff; 2022-01-06 dropped for all (§1.1, §3.3); narrows ruling (2) for scored rows — flagged |
| m8 S check | Independent `mg_serve_core.mg1_band_probs` vs `mg1.predict` (§2); all HALT checks before labels are joined (§8.2) |
| m9 κ_block3 | Defined as SE²(block-3)/SE²(iid), fold-bounded blocks (§6.1) |
| m10 ×1.07 basis | Applied to MDE and power; recomputed at n = 660 (§6.3) |
| m11 peek guard | Look result committed with sha before held-out 2024–25 labels are joined (§8.1) |
| m12 counts | 977/956/≈950/479/480 superseded and explained (§1, §6.3, §8.1); this review cited here |
| Ruling (a)1 paired | Every arm and S on the same 660 dates; C needs no extra serve-time input (§1, §4.1) |
| Ruling (a)2/3 arm C gap | §4.1a |
| Ruling (a)4 IEM miss | One line in §10 |
| FLAG 2 market NBM | §3.3b |

**New outcome-blind finding in r4 (flagged to master):** the B-bound builder's PIT-corpus coverage rule leaves 150 of the 811 dates without a record window (Jan–Mar 2021, Dec 17 2023 – Jan 30 2024, Dec 17–31 2024, and the 2024 leap day), so the paired deciding set is 660 and rule-16 power falls below 0.5 from ≈ 2.9×σ_eff (§1.1, §6.3). The descriptive 2026 fold and V5.0 sliver cannot be built (§1.1).

**r4-final (master's rulings on r4 `09bd09b9…` @ `ead57fe7c`, 2026-11-02):**

| Ruling | Resolution in r4-final |
| --- | --- |
| A. n = 660 under the strict bound coverage rule; drop list by code, outcome-blind, committed before any label join | `scripts/row28_deciding_dates_r4.py` reproduces `6913484a…`; the list is committed (§1.1). Folds 61/164/165/120/150 and the look at 390/660 are unchanged |
| B. m7 accepted as a dated narrowing of ruling (2) for scored rows | Recorded as "master ruling 2026-11-02 (WS relay 21:36 report)" (§3.3) |
| C. Descriptive 2026 fold and V5.0 sliver unbuildable | Already stated (§1.1); §7 gate unaffected |
| Rule 16: underpowered labelling; adequate power defined | §8.4 (new); §8.2 KILL split into crossing vs failure-to-show conditions; INCONCLUSIVE-UNDERPOWERED added; §6.3's "KILL (underpowered)" withdrawn |
| New code finding: leap day | The bound `nearest_centre` raises on Feb 29. Fixed Rule L (§3.2): Feb 28's centre is used for a Feb 29 target_date, which gives the same pick (02-22) in every arm. The deciding S (MG-1 C5) and all arm serve-time inputs are computable on 2024-02-29, so there is no paired drop and n stays 660 (§1.1). Only the descriptive S_bound is "not computable" there. The bound `state_features` failure is outside row 28's scope; the coordinator is raising it separately |
