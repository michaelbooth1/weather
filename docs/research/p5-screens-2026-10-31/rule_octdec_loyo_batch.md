# Oct-Dec history LOYO batch: day-specific width (R9) and trajectory items X13 / X18 / X20 (ledger row 95)

Status: DRAFT, pre-declared before any computation (2026-10-31, lane L17, task P5 (b)).

- Evidence class: history-only LOYO SCREEN.
- Under R10, a PASS earns only a forward pre-registration to master. Promotion happens only through a
  forward test, never from this read.
- Nothing dated 2026 is read. No dev, capture, price, panel or settlement row is opened.
- The ledger row text (row 95) was committed before this file, in `ledger_rows_draft.md`.

**Amendment A1 (2026-10-31, pre-run; applies the coordinator's rulings; no outcome, price or label was read
to write it).**

- **Decision: UNDERPOWERED, NOT RUN.** At half the planning δ, power is 0.088 for every arm (0.230 at the full δ). Section (d) carries the MIM §5 rule 6 and checklist (f)
  compliance line. Nothing in this rule runs, and no module is admitted for it, until master rules otherwise
  in a dated Clarification with its own sha256.
- **Ledger number.** Row 95 is PROVISIONAL. L15 assigns the final number in the assembled ledger; rows 82 and
  83 have already collided. A renumber changes only the label, not this rule, and is recorded as a note.
- **Archive.** Owner rule: every ruled-out candidate goes to `C:\archive\ruled-out\<row-folder>` with its
  prereg, script sha256, outputs, receipts and logs. A NOT RUN arm is not ruled out. Its prereg is archived
  under the same folder only when the assembled ledger records its verdict.
- **Run bases (ruling 4), recorded and not cut.** The planned base for a run branch is `9ee8a243f55efe314ad5a1b1b33dd0cf0816508e` (row 92's tip). These would be merged read-only into it: `claude/stack-l9-20261025` @ `8167b89a898699c2103cd6be136cc09ee9702c85` (X13) and `claude/rung0712-20261025` @ `6488c7a31623c859631099a882ffee2fd065a925` (X18/X20 via `pooled_residual_model`, imported only). The rule branch is `claude/p5-screens-20261031`, based on `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de`.

**Amendment A2 (2026-10-31, pre-run; applies master's edge-size power ruling; no outcome, price or label was
read to write it). A2 supersedes A1's Decision bullet and section (d)'s rule 6 compliance decision. Every
other A1 bullet stands.**

- **Master ruling (relayed by the coordinator, 2026-10-31).** Checklist (f)'s half-dev-effect sizing does
  NOT bind kill-only dev or history reads; it is for forward tests. A kill-only read states its power AT
  EDGE SIZE, the effect a B-style PASS needs (about a 5% Brier gain against the market, R ≤ 0.95
  equivalent), and it runs only if that power is ≥ 0.5.
- **Verdict vocabulary.** The verdict is "KILL at edge size" or "SCREEN" only. Neither is a promotion, an
  edge claim, or an information claim below edge size. UNTESTABLE (coverage) and VOID (a control failed)
  stay as non-verdicts. The labels TESTED-UNDERPOWERED, SURVIVE and PASS in this file are read as
  "SCREEN" (survivor or pass) and "KILL at edge size" (anything else), and no line may claim or deny
  information below edge size.
- **Units (L15).** `claude/research-docs-batch-20261031` @ `f2ed2fa9108c98ad362a315b6ee666fa95ef34f9`,
  `EXHAUSTION_REGISTER` and `DEV_WINDOW_LEDGER`: the SYN bar is 5% of the served−market gap, i.e.
  0.05×(R_served−1) in R units (about −0.024 at 07-12 and −0.043 at 13-16); B's PASS is 5% of the
  market's Brier; a market-residual P0 needs ρ ≥ √0.05 = 0.2236 for a 5% gain.
- **Power formula.** power = Φ(δ/SE − 1.96). The working is `edge_power_working.py` and its output, in the
  R13 archive folders `C:\archive\ruled-out\_p5-ens`, `_p5-subbar` and `_p5-loyo` (listed in
  `SHA256SUMS_A2`).
- **Final row number: 95** (coordinator, 2026-10-31). A1's PROVISIONAL label is closed.
- **Scale for this arm: bucket Brier against the incumbent, converted relatively.** No Oct-Dec market
  exists, so edge size is translated through the incumbent's dev R against the market. This relative
  scaling is an approximation, disclosed here.
  - Incumbent bucket Brier on these rows: 0.8480287548671755 (`C:\t\l3\sml6\loyo.json`, sha256
    `07ef7810d81e434c93e08e552d3ca2df0ec195790a52b6431e578ab3ce515919`, `season_matched_loyo` oct_dec
    pooled `brier_part`).
  - Proxy R_L6 at 07-12 on dev = 1 + 0.0081/0.05301 = 1.1528 (L6's 07-12 excess +0.0081, section (c); the
    market Brier from atlas `046aa7a9…`).
  - **B-style (R ≤ 0.95):** a relative cut of (1.1528 − 0.95)/1.1528 = 17.59%, δ = 0.1759·0.84803 = 0.1492.
  - **SYN bar (binding, the smaller):** 0.05×(1.1528 − 1)/1.1528 = 0.663%, δ = 0.00663·0.84803 = 0.00562.
  - **SE** = 0.00833·√1.78/√375 = 0.000574 (section (d)). For d_net, where each draw subtracts one
    placebo, a conservative √2 gives SE 0.000812.
  - **Power at the SYN bar:** Φ(0.00562/0.000574 − 1.96) = 1.00; with the √2 SE, 1.00. At the B-style δ,
    1.00.
  - Shown only to fix the scale: the dev per-band SYN figure 0.0012 taken unconverted would give 0.55
    (0.32 with √2). That reading mixes per-band Brier with integer-bucket Brier and is not used.
- **Decision: W1, X13, X18 and X20 RUN (power ≥ 0.5 at edge size).** The verdict per arm is "SCREEN" (a
  section 4 PASS, which earns only a forward pre-registration to master under R10) or "KILL at edge size"
  (anything else). UNTESTABLE and VOID keep their meaning.
- **Disclosed construction for X20 (S1, section 3).** The 13-14 rows are built by a local copy of the
  `cool_season_audit.l6_rows` pattern with hours (13, 14) in place of `HOURS_0712`, inside the new module.
  `cool_season_audit` is not edited.
- **Disclosed X13 adapter.** `ols_floor_ladder.overnight_lows` reads WU record rows (`minute_of_day`,
  temperature). The module feeds it the same pinned upstream obs that `l6.load` reads (market station,
  non-corrected rows, local minute of day), converted in memory; no other source is opened.
- **Entry point and admission.** `python -m weather.calibration.octdec_loyo_batch`, writing only under
  `--out`, which must sit below `C:/t/l17/octdec/` and must not exist. The module diff and shas go to the
  coordinator before any run, and the run is never self-admitted. The 15 HGB fits are heavy and run only
  through `scripts\ops\workstation_heavy.ps1 -Queue` after admission.

## 0. Why this batch exists (scope rulings)

- **R9** (EF §10af, master 2026-10-25) scopes the R-I kill. It covers only fitted temperature or scale
  maps on NBM-anchored arms. Spread information, meaning day-specific predictors of spread, is a separate
  open family. That family needs its own rule and the full ladder, with no global sharpening and a floor
  that is never weakened.
- **R10** scopes the R-G (X18) and R-J (X20) kills to Aug-Sep dev. An Oct-Dec rung needs a fresh rule plus
  LOYO on Oct-Dec 2021-25, and it promotes only through a forward test.
- **X13's reopen line** reads "overnight low and dewpoint help in Oct-Dec: an Oct-Dec rung under R10".
- **Row 92's batch note** (`permarket-octdec-2026-10-30/batch_note.md`) closed X13 "by family" and X18/X20
  "ruled out by family, not run". The review (`acaf441b…`, takeaway 5 and appendix B) calls those by-rule
  closures premature. This batch runs them instead of extending the family kill.

## 1. Machinery (row 92, unchanged except where stated)

**Rule and code.** Row 92's rule `docs/research/permarket-octdec-2026-10-30/rule_rm_octdec.md` (sha256
`9e494ff9bcd71160e3c2bc8cf1a2d2f767cf675103493c846e4809b95e44b9b8`) and its code
`weather.calibration.permarket_octdec` on `claude/rm-octdec-run-20261030` @
`9ee8a243f55efe314ad5a1b1b33dd0cf0816508e` (module sha256 `236970ee…`).

**Readers.** `cool_season_audit.l6_rows` and `season_matched_l6.training_rows/fit_state/stack_brier`.

**Pinned inputs:**

| input | sha256 |
| --- | --- |
| obs | `37d97195828d9f58d510f078e3029d53ed051fe471c4a94333bb0cc51f6d28f2` |
| selection | `a23f4cba11c0ec1666e7069cc89c93f699e5573546c048be4e398070cc1fb199` |
| NBM corpus | `1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd` |
| MG-2 coefficients | `4bc51e031ce10862d44ffdc57a6a6ca92bd46d98412bfc0e087b681a01b0c398` |
| C1 receipt `C:\t\l3succ\c1\c1.json` | `c881a5bba59c36f6dd409b055910ee2ba83a36833735ca679bd8475c053dbe14` |

**Rows.** Months 10-12 of 2021-25, local 07-12, 11 US markets: 24,381 scored rows on 375 dates.

**Incumbent A0** is the SM-L6 OWN HGB fitted on Oct-Dec of the other four years, plus the MG-2 l6_stack
with frozen coefficients:

- mu = v + a_h + b_h·(n − v);
- σ = max(s, 1);
- Gaussian integer-bucket Brier, floored at the observed running max R (`rz_hrrr_spread.bucket_brier`).

**Strict nesting** (`permarket_octdec.run`, unchanged):

- for held-out year Y, the outer fit is on the four years ≠ Y;
- the inner predictions for year X ≠ Y come from fits outside {X, Y}: 10 inner fits plus 5 outer fits;
- every lever parameter for year Y is fitted only on inner predictions of the years X ≠ Y.

The HGB fits are shared by all arms and computed once.

**The statistic** replaces row 92's R2 with the MR-P0 bootstrap conventions:

- per-row d = Brier(arm) − Brier(A0) on identical rows;
- date-cluster bootstrap with B = 10,000 and seed 20261024 (`upstream_obs_screen.cluster_ci` with
  draws = 10,000 and seed = 20261024);
- one-sided p = (1 + #{mean* ≥ 0})/(B + 1);
- BH at q = 0.10 over K = 4.

**The placebo is calibration-matched.** For each arm, its signal is deranged across dates within
(market, hour), with J = 20 seeds 20260921 + j (`market_blend.placebo_vector`'s derangement), and the arm
is refitted through the identical nested procedure. Then:

- d_net = d_arm − mean_j d_pl,j;
- draw b uses j = b mod 20.

The placebo has the same flexibility, the same fit and the same floor, so any gain from fitting freedom
alone cancels.

**Daily statistics** come from `successor_odc_low.daily_stats`. Year, month, hour and market cells come
from `permarket_octdec.gate`.

## 2. Arms (K = 4; fixed)

| id | family | lever (one ingredient on A0) | parameters (nested) | block |
| --- | --- | --- | --- | --- |
| W1 | R9 spread information | day-specific width: σ' = max(1, max(s, 1)·exp(γ_h·(z − z̄_m,h))) with z = ln max(\|n − v\|, 0.25) | γ_h on the grid 0.00..1.00 step 0.05 (ties to 0) per hour; z̄_m,h = training-years mean per market and hour | 07-12 |
| X13 | overnight low (L9 ladder, X13) | centre: mu' = mu + β_h·(low_so_far − mu) + β′_h·(low_prev_evening − mu), centred on training means | per-hour OLS of the inner residual (dmax − mu_inner) on the two centred columns | 07-12 |
| X18 | R-G trajectory (X18) | centre: mu' = mu + Σ_j β_h,j·(x_j − x̄_j) over `RG_FEATURES` = t_trend3, t_trend3_miss, t_amp, t_path_gap | per-hour OLS on the inner residual; `rg_diurnal_fraction` re-estimated on the fit's own Oct-Dec training years | 07-12 |
| X20 | R-J trajectory (X20) | as X18, at cutoffs 13 and 14 | as X18 | 13-14 (conditional, section 3) |

**Construction notes.**

- W1 is spread *information*: it is driven by the day's disagreement between the obs-driven HGB nowcast
  and the NBM centre.
  - It is not a fitted global temperature or scale map. The anomaly is centred per market and hour on
    the training years.
  - No global sharpening: if the mean log multiplier on the training rows has |·| > 0.02 (R-Z's
    `LOGMULT_MAX`), γ_h = 0 for that fold.
  - The floor is never weakened: σ' ≥ 1 °F, and the observed running-max floor R is applied unchanged.
  - W1 first faces R-Z's P0 screen (rule `36fa7726…`): nested-LOYO Spearman ρ(z − z̄, |dmax − mu|) ≥ 0.05
    pooled, with at most 1 opposite-sign year. Below that it is CLOSED at P0 (p = 1, still in K).
  - **R15 applied (coordinator ruling 2, 2026-10-31): W1 STAYS (K = 4).** R-I's measured width input was
    not |n − v| or any monotone transform of it.
    - `C:\t\l2\rungi\rule_ri.md` (sha256
      `b8a3d79ca13111db2bd667dc16e7a8418ddfe27bfaecbfaea23b099037341730`) defines R-I at lines 48-54: "a
      per-hour temperature τ_h, applied as q_b ∝ p_b^τ_h". There is one τ per local hour h07-h12, pooled
      over all markets, chosen on the grid 0.50..3.00.
    - That is a constant per hour, with no day-specific input.
    - R-I's kill text at lines 113-115 closes another "temperature grid, hour grouping, scale-parameter
      variant, per-market map, conditional trigger or isotonic form" on NBM-anchored arms.
    - W1 is none of those. It is a day-specific width driven by a measured disagreement (R9 spread
      information), with its global log multiplier capped at 0.02 so that it cannot act as a re-fitted
      temperature.
    - No substitute width signal is added.
  - HRRR 3x3 spread is not used: X38/X39 closed it at all hours (Aug-Sep). The ENS spread has no Oct-Dec
    history locally (row 93, section 0).
- **X13 columns** are the L9 constructs `ols_floor_ladder.overnight_lows` (`claude/stack-l9-20261025` @
  `8167b89a898699c2103cd6be136cc09ee9702c85`): `low_so_far`, the minimum since local midnight up to the
  cutoff, and `low_prev_evening`, imported read-only.
  - The dewpoint is not added because `td` is already an L6 OWN column. Hour-pooled slopes are not
    re-tested because SM-L6 is per-hour by construction.
- **X18/X20 columns** come from `pooled_residual_model.trajectory_features`, `rg_columns` and
  `rg_diurnal_fraction` (`claude/rung0712-20261025` @ `6488c7a31623c859631099a882ffee2fd065a925`, rule
  `rule_rg.md` `a8cf65640625605acdd0acad391bb267357957a5fd0bd9bd7e6e7a62dafe9b29`). They are imported
  read-only, because `pooled_residual_model.py` is B-bound.
  - `tend3` is already an OWN column, so t_trend3 measures residual trajectory beyond it.
- **The centre arms** (X13, X18, X20) fit linear corrections to the stack residual, not new HGB columns.
  One ingredient, one rung, and no extra HGB refit, so the fits stay comparable with row 92's.

## 3. S1, outcome-free coverage (before any Brier or residual is read)

- **07-12 columns.** Report the coverage of every column on the 24,381 rows. An arm with coverage < 0.90
  is UNTESTABLE (p = 1, still in K). Rows where a column is missing keep A0 (the lever is 0 there), and
  that count is reported.
- **The 13-14 block (X20).** It requires `upstream_obs_screen.build_history` Oct-Dec rows at cutoffs 13
  and 14, with ≥ 10,000 rows on ≥ 300 dates and NBM `s` finite on ≥ 0.90 of them.
  - **Its incumbent A0′** is the SM-L6 OWN nowcast n with σ = max(s, 1). There is no stack, because the
    MG-2 stack coefficients exist only for 07-12. The same Brier and floor apply.
  - If S1 fails, X20 is UNTESTABLE (p = 1, still in K). It is recorded as "BLOCKED on a 13-14 Oct-Dec
    history incumbent", not as killed.
  - **Disclosed:** A0′ is a weaker incumbent than the 13-16 serving arm (P3d_N), so a 13-14 pass is
    bounded context only.

## 4. Decision

An arm PASSES iff all of the following hold:

1. it is testable, and W1 has passed its P0;
2. BH (q 0.10, K = 4) rejects;
3. the date-clustered Δ upper bound is < 0;
4. the placebo-net d_net upper bound is < 0;
5. no year or month cell has a CI lower bound > 0 (row 92's `ci_worse_cells`).

A PASS earns only a forward pre-registration to master (R10). Anything else is a KILL, or UNTESTABLE.

## (a) Positive control

Any failure → VOID, and no arm is reported.

- **C-a, reproduction.** The incumbent A0 against the MG-1 analogue reproduces C1's
  −0.005245663923351247 on 24,381 rows, to 1e-12 (row 92: |diff| 0).
- **C-b, identity.** γ = 0 and β = 0 reproduce A0's per-row Brier: max |diff| 0.0, for every arm.
- **C-c, planted signal and its negation** (A4 form, seed 20261031, built in memory and never written as
  a feature):
  - **Centre arms:** planted column p = 0.5·(dmax − mu_inner) + ε, with sd(ε) = sd(dmax − mu_inner).
    - +p must PASS (BH reject with upper < 0).
    - −p must fit β of the opposite sign in all 5 folds, and d must be identical to 1e-9. That is the
      sign invariance of the OLS.
  - **W1:** planted z = ln|dmax − mu_inner| + ε.
    - It must pass the P0 and must PASS.
    - The negation −z must fit γ_h = 0 in ≥ 4 of 5 folds per hour, with a d upper bound ≥ 0. One-sidedness
      means no help is possible from the wrong sign.
  - These read the outcome deliberately as planted controls. They are never candidates and never in K.
  - **Ruling 3 (coordinator, 2026-10-31): confirmed as CONTROLS, not an oracle.** Every planted column and
    its negation are built in memory only and are never written as a candidate vector or column. Every
    output field that carries one is labelled `CONTROL`. A run that lacks either the planted control or its
    negation is VOID.
  - The ruling's "dev outcomes ≤ 09-29" condition holds trivially here: this batch reads only Oct-Dec
    2021-25 history, and no 2026 date.
- **C-d, training score.** In every fold the fitted lever is not worse than lever = 0 on its own training
  rows (row 92's check).

## (b) Comparator fairness

- **Same floor.** The arm and A0 share the same rows, the same HGB fits and the same observed running-max
  floor R inside `bucket_brier`.
- **Same calibration.** They share the frozen MG-2 stack calibration, and every arm changes exactly one
  ingredient.
- **Placebo.** The placebo arm gets the same fitting freedom on deranged signals.
- **A0′ at 13-14** is the same OWN nowcast with the same floor and the same width calibration
  max(s, 1).

## (c) Targeted loss slice

- **Oct-Dec rows.** The incumbent's gain over the MG-1 analogue is −0.00525 on 24,381 rows (C1, row 85).
  Row 92's σ_d is 0.00833.
- **Dev slices, cited only as motivation.** No dev row is read here.
  - Sharpness carries about two thirds of the 07-12 excess on dev (R-H atlas `ff7ee23179be2bec…`, X27):
    W1's target.
  - The centre carries the rest (L5's Shapley centre share at 07-12 is 76.5% against served): the X13/X18
    target.
- **Expected size:** about 0.0005-0.0007 per arm, from R-I's LOYO −0.00045 and R-Q's LOYO −0.00067.

## (d) MDE and clusters

These are the checklist (f) fields, from row 92's own run on these rows.

| field | value |
| --- | --- |
| N | 375 date clusters (Oct-Dec 2021-25) |
| sigma_d | 0.00833 (row 92) |
| rho | +0.128 (lag-1, row 92) |
| block3 ratio | 1.028 (block-3 SE 0.000442 / iid SE 0.000430) |
| VIF | 1.78: the floor applies, since max(1, 1.294, 1.056) < 1.78 |
| MDE80 | 0.0016 (= 2.802 · 0.00833 · √1.78 / √375) |
| delta (planning) | 0.0007 |
| power at delta | about 0.23 |
| N80 at delta | about 2,000 dates (more than the corpus holds) |
| class | SCREEN |
| intervals | date-clustered, plus block-3 (MIM §5 rule 7) |

Consequences:

- MIM §5 rule 6 (power ≥ 0.5) is not met at the planning δ. It is met only for δ ≥ 0.0011.
- A KILL here is "KILL at edge size" (TESTED-UNDERPOWERED when the CI includes −0.0016), and it keeps each
  item's reopen line (review takeaway 3).
- Futility look: none. One look only.

### MIM §5 rule 6 and checklist (f) compliance (coordinator instruction, 2026-10-31)

**What (f) requires below power 0.5.**

- Power must be ≥ 0.5 at delta, and delta is taken at half the dev point. The checklist says: "State the
  power at the dev point and at half of it, and use half for class".
- A test that cannot show this "is a SCREEN or does not launch". That is PREREGISTRATION_CHECKLIST (f),
  `claude/s5-power-futility-gate-20261030` @ `9206b56a083cb9ca7cb63b0fafddb8c7a98a0d8d`, lines 49-79.
- MIM §5 rule 6 (`claude/docs-owner-20261030` @ `e759a55d10e31dd48559ef99b9d2959c41271fd3`, lines
  161-162) says "no screen launched below power 0.5".
- As written, (f) binds pre-registrations that spend forward dates (checklist line 51). Rule 6's sentence
  carries no such limit, and the coordinator applies it to these screens.

**Numbers.**

- SE = 0.00833·√1.78/√375 = 0.000574.
- Power at the planning δ 0.0007 is 0.230. At half (0.00035) it is 0.088.
- The corpus holds 375 dates, and N80 at δ is about 2,000.

**Why it is not argued admissible.** A KILL here closes each item's Oct-Dec estimand (section 5) on a read
that misses a planning-size effect about 91% of the time, and the corpus cannot grow to N80.

**Decision.** W1, X13, X18 and X20 are all UNDERPOWERED, NOT RUN. K stays 4, and an arm that is not run
carries p = 1. Their reopen lines and R10 status are unchanged by this rule.

**Reopening.** A run needs one of the following, as a dated Clarification with its own sha256 before any
module:

- a master ruling that rule 6 does not bind kill-only history reads; or
- a δ ≥ 0.0011, which is where power at half reaches 0.5, measured on these rows by an earlier read.

## (e) Dev-window reuse

DEV_WINDOW_LEDGER: this is row 95. It is history only, so its dev-window reuse count is 0: no date in
2026-07-31..09-29 is read. The Oct-Dec 2021-25 rows have been read by rows 85, 86 and 92 (and by SM-L6's
row 41 LOYO). This batch is their 5th read.

## 5. Kill and reopen line (written now)

**W1.** A KILL closes the |n − v| disagreement anomaly as day-specific width on SM-L6 for Oct-Dec 07-12.
R9's spread-information family stays open for external spread sources.

**X13, X18 and X20.** A KILL closes that item's columns as a linear residual correction on the SM-L6
incumbent for Oct-Dec. It reopens only with an HGB-column variant under a new rule written before any read,
and the Aug-Sep kills stand unchanged.

No other grid, hour block, shrinkage, column subset, objective or window runs under any name.

## 6. Outputs and test plan (before any run; the coordinator admits the module)

**Outputs.**

- They are written once, under `C:/t/l17/octdec/` only:
  - a receipt JSON with the per-arm d, d_net, p, BH q, cells and fitted γ/β per fold;
  - the S1 coverage JSON.
- A ruled-out arm keeps its prereg, script sha, outputs, receipts and logs under
  `C:\archive\ruled-out\<row-95 folder>`.

**The module.**

- A new research module, `weather.calibration.octdec_loyo_batch`, on a run branch off
  `9ee8a243f55efe314ad5a1b1b33dd0cf0816508e`. It merges the L9 and rung0712 commits above read-only, and
  that merge is listed in the diff sent to the coordinator.
- It does no network I/O, and refuses any date outside 2021-01-01..2025-12-31.
- It reuses `permarket_octdec.stack_mu`, `brier` and `gate` by import, and does not edit them.

**Unit tests (synthetic frames only).**

- The nested-fit index sets (no inner fit sees X or Y).
- The W1 σ' floor and the LOGMULT guard.
- The C-b identity.
- C-c signs on a toy frame.
- The derangement (no fixed points, within (market, hour)).
- Pytest runs with `--basetemp` under `C:\t\l17\pytest-octdec`, which is deleted afterwards.

**The run.** One run, after admission, via `scripts\ops\workstation_heavy.ps1 -Queue -Kind weather_heavy`,
with OMP/MKL/OPENBLAS set to 10, `-MinAvailableMemoryGB 3` and a write-once out dir.
