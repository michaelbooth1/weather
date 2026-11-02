# K112 history-tier test: pre-registration (DRAFT, lane L47, 2026-11-02)

**Status: DRAFT for master's review. Not frozen and not run.** No history-tier label, price or outcome was read
to write it. It uses only:

- L52's row-113 tip `96e9cd9a48fcf8bf42e7c285b7568bdd67307228` (`claude/pm-price-history-20261101`): its
  `rule_3a.md` and `clarification_1.md`;
- the label-free `deciding_population` block of L52's dry-run receipt (`C:\t\l52\3a\dryrun-20261102T151627Z.json`,
  sha256 `a1067a79879985ca47117b91915fc45740604ba43809b8624da854dcd7ac0369`, counts only);
- K112's own dev record (`g2_freeze.md` C1-C4, `results_g2.md`);
- directory and manifest names of local stores, never their rows.

It becomes binding only after master's review and a freeze commit. It **runs only after L52's row-113 run** has
completed and its outputs are sealed.

## 0. Upfront disclosure: the dev gain was September only

The dev result was CONSISTENT under C1.6 (`results_g2.md`): G2 pooled dR -0.00274, with both 95% intervals
straddling 0. The whole gain came from September.

| | Aug (16 dates) | Sep (27 dates) |
| --- | --- | --- |
| G2 point | +0.0019 | -0.0052 |
| G2-P point | +0.0010 | -0.0047 |

August went the wrong way. No month subset is chosen on that basis, now or later (section 4).

## 1. Window and population (frozen)

- **Window:** event dates 2025-12-01..2026-05-26, L52's D window. The end is <= 2026-05-26. The sealed
  2026-05-27..07-30 panel is never opened, and the code refuses any date after 2026-05-26.
- **Markets: US11** (atlanta, austin, chicago, dallas, denver, houston, los-angeles, miami, nyc,
  san-francisco, seattle). These are K112's markets, with b_train in the freeze table.
  - Toronto is in L52's B12 but **out** here: K112 has no b_train or freeze value for it.
  - NYC 2025 and R1/R2 are out.
- **Hours: 07:00 and 10:00 local, pooled.** These are L52's deciding hours, at the price convention in section
  2. 13:00 is out because it is not in L52's deciding set.
  - The freeze table's h07 pick is W=7, lambda=0.5, and its h10 pick is W=14, lambda=0.25.
  - h08, h09, h11 and h12 have no history-tier price, so they are not scored.
- **Deciding population** is L52's outcome-blind, price-complete set restricted to US11.
  - L52 states it as 695 of 1,419 D market-dates, or 1,355 ladder-hours, for B12.
  - Kept by month: 2025-12 79, 2026-01 101, 2026-02 115, 2026-03 139, 2026-04 142, 2026-05 119.
  - The US11 count is taken label-free from the same `deciding_population` build (market-dates kept minus
    Toronto) **before any label read**, and it is recorded in the receipt.
  - The L52 tip and receipt state no per-market kept count, so the US11 N is not known yet. It is at most 695.

## 2. Exact inputs (all fixed by sha before the run)

1. **Market price:** L52's sealed step-2 run `C:\t\l52\history\run-20261102T004422Z`.
   - SHA256SUMS `5073afd8f16ad4a7e9eb21b06df7bbaf78464f12ad4101b27440afc9ed31fe71`.
   - Manifest `fdb984606f3b7e39190383292ca296c411c57034fe94588d0d6f9683f86268a7`.
   - Receipt `a9966d9b7771ce6d203366f1774cb88201df9aa18fe35a13ab09cf0eb7d4be5c`.
   - It is read through L52's own ladder builder, `reliability_3a.py` sha256
     `6e5beb395fbab734dcdb7ad54fe91e440f3b87cb96062c752536c8b62f8fb108`, `build_rows`, imported unchanged.
   - Price convention: book mid on the AFTER side, within 120 s, with m~ = m / sum over the ladder of m. Every
     band must be complete. All of these are L52's convention. The mid caveat in rule_3a section 3 applies
     verbatim.
2. **Labels (WU daily highs, native F):** only the output of L52's bounded extractor `extract_bounded_v1.py`,
   sha256 `65ce60f34a06f35488747cb60603701ab9aeb46a03d036bd973c457a9f6d945a`.
   - That extractor runs once, emits rows dated <= 2026-05-26 with a per-file SHA256SUMS, and has its
     manifest checked.
   - That output goes live only after row 113 has run. This test consumes the same sealed extract and does
     not re-extract.
   - The label is the settlement bucket, under L52's ruling L1. Partial and missing WU days are excluded and
     counted (L52 rulings L2/L3). The same label feeds both the scoring y and the 2026 d series.
3. **2026 d series for b_recent:** d(m, u) = NBP 07Z mean - WU high, the same definition as G2.
   - It needs an NBP 07Z corpus for target dates about 2025-11-17..2026-05-25.
   - **None is held:** L9's corpus covers 135 dates per year for 2021-25, and `nbm2026` covers 07-30..09-29
     (`nbm2026_dates.txt`, 62 lines). This is open item O-H1.
4. **Model inputs for the two arms** at 07:00 and 10:00: see open item O-H2.

## 3. Candidate and reference (frozen, no re-fit)

- **Candidate P3d_T:** K112 exactly as pinned.
  - Module `x36_trailing_g2.py` sha256 `022565ccceba52eed4b617ca031425a81f40dd9d373b08a64ee751dae9e55679`.
  - Freeze table sha256 `eb73fc04ab20d7b0410633e3d159b069aa14ab4a8f36c5b76db0750fac79fc37`.
  - mu' = mu - lambda_h * clip(b_recent - b_train, +/-3).
  - b_train is the frozen `b_train_2026` (Aug 1..Sep 29 means, 2021-25 WU era), with **no** seasonal re-fit
    and no new W or lambda.
  - b_recent is `x36_trailing_g1.b_recent` unchanged: the W latest dates strictly before t **in the same
    year**.
- **Reference P3d_N_fix:** the base distribution the candidate shifts. It is the same arm as G2's reference,
  emitted on the same rows.
- **Statistic:** dR = R(P3d_T) - R(P3d_N_fix), with R = Brier_model / Brier_market. The market is the L52 mid
  ladder m~. It is pooled over US11, 07:00 and 10:00, and every deciding market-date, on rows where both arms
  are covered.
- **Rows with fewer than W prior same-year dates** get shift 0 and are counted, as in G2. Expected cases:
  - January 1-7 at h07 and January 1-14 at h10, from the same-year rule;
  - any span where the label or corpus gaps leave fewer than W dates.
- **Pinned consequences, disclosed and not fixed:**
  - **b_train is a summer level** applied to Dec-May. Any seasonal level difference in d enters
    clip(b_recent - b_train) as a systematic shift. That is part of the candidate as pinned. Changing it
    would be a new family (C3.3), not a K112 variant.
  - **The year boundary** zeroes early-January shifts.

## 4. Decision rule (frozen)

- **Decider: the pooled dR only.** It uses two intervals: the date-clustered 95% interval (2000 draws, seed
  20261024, as G2) and the circular moving-block 95% interval (block L = 7 dates, 2000 draws, seed 20261024,
  as C1.5).
- **PASS:** the pooled upper bound is < 0 under **both** bootstraps, AND the pooled point is < 0.
- **KILL:** anything else.
  - There is no CONSISTENT tier at the history tier.
  - A KILL routes K112 to `C:\archive\ruled-out\` with its INDEX line.
  - A PASS is selection evidence only. It is never an edge claim or a serving claim, and it is never dev
    evidence.
- **Per-month results** (6 calendar months, both bootstraps) and per-hour results (07, 10) are **diagnostic
  only**.
  - No month or hour subset is a decider, before or after reading.
  - Any month-specific claim needs a new pre-registration on new data.
- **Controls** (STOP on failure, before any verdict):
  1. L52's price integrity: SHA256SUMS re-verified.
  2. L52's label-extract manifest and script sha.
  3. Arm parity: on rows where the candidate's shift is exactly 0, P3d_T must equal P3d_N_fix to 1e-12.
  4. A dev-reproduction check: the same emit code, run on the 2026-08-15..09-29 layout rows, must reproduce
     G2's `dev_P3d_N_fix.jsonl` sha `06bc2faa...` and `dev_P3d_T.jsonl` sha `96d80204...`. This re-reads no new
     dev outcome, only the already-scored files.

## 5. MDE80 before reading (counts only)

**Method.** The history-tier standard error is projected from G2's realised dev bootstrap, scaled by the ratio
of independent market-days.

- G2 dev: MDE80 0.010747 at 473 market-days (43 dates).
- MDE80 is about 2.8 * SE, from `dev_scorecard.mde80`'s centred bootstrap (critical |error| at 95% plus the 80%
  shift). So SE_dev = 0.003838.
- SE_hist = SE_dev * sqrt(473 / N_hist), and MDE80_hist = 2.8 * SE_hist.

| N_hist (US11 market-dates) | MDE80 | Power at the dev point (-0.00274) | Power at -0.0075 |
| --- | --- | --- | --- |
| 695 (upper bound: all B12 kept) | 0.0089 | 0.14 | 0.66 |
| 600 | 0.0095 | 0.12 | 0.60 |
| 550 | 0.0100 | 0.12 | 0.56 |
| 695, hour penalty (dev ~6 hourly ladders per market-day vs history 1.95; hour noise taken as independent) | 0.0156 | 0.07 | 0.27 |

- The frozen projection is the market-day row at the label-free US11 N. It is recomputed by this formula at run
  start, before any label read, and written into the receipt.
- The realised MDE80 from the history bootstrap is reported next to it.
- **Disclosed now:** at the dev effect size, power is at most about 0.14. A KILL at the history tier would
  therefore not show the dev effect is absent. A PASS would need an effect several times larger than the dev
  point.

## 6. Order and gating

1. L52's row-113 run completes. Its sealed label extract and receipts exist.
2. Master resolves the open items below.
3. A freeze commit replaces this DRAFT header with FROZEN and pins:
   - the run module's sha (a new module; `x36_trailing_g2.py` is untouched);
   - the NBP corpus sha;
   - the input shas.
4. Pytest via `-Queue` on synthetic data.
5. The coordinator's go.
6. A single run via `-Queue`. The verdict goes to the coordinator first.

## 7. Open items for master (not resolved here)

- **O-H1, NBP 07Z corpus for 2025-11-17..2026-05-25.** None is held on the WS. Options:
  - a bounded NOAA open-data fetch (free, official) with receipts, cut off at 2026-05-25;
  - or name an existing corpus.
  - Without it there is no d series, and every row has shift 0.
- **O-H2, model inputs for P3d_N_fix at 07:00 and 10:00 for Dec-May.** Dev used captured-input replay
  (`replay-inputs-le0929`, <= 09-29 only). For Dec-May, the WS holds `C:\t\l2\records` (file names show 2026
  dates, contents not opened). Master to rule:
  - which input path (records-based training frame vs captured replay, if any exists);
  - whether the base model's training years include any D date (in-sample disclosure).
  - Train/serve parity differs from dev in either case and will be disclosed.
- **O-H3, the summer b_train applied to winter and spring** (section 3). Test as pinned (this draft), or rule
  the history tier uninformative for K112 as pinned.
- **O-H4, power** (section 5). Whether a run at about 0.14 power at the dev effect is worth spending, given that
  a KILL cannot rule the effect out.