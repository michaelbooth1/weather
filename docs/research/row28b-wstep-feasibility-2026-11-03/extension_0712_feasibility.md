# Row 28b forward draft: 07-12 extension feasibility (outcome-blind)

Status: **feasibility note only, outcome-blind.** It is not a prereg, does not edit the forward draft
(`claude/row28b-forward-prereg-draft-20261103` @ `1fed1b989`, unfrozen), and reads no price, label, score or loss.
Lane L59, WS, 2026-11-03. Ordered by master after the w-step rulings (`feasibility.md`, "Master rulings").

## Verdict: DON'T ADD (as the draft stands)

A 07-12 B-S arm cannot pass the forward gate honestly today.

- (a) B was never fit at 07-12.
- (b) No same-kind SD or effect size exists, so power cannot be projected under rules 16 + 19.
- (d) Its comparator is PT-1's candidate, on PT-1's dates and hours.

The multiplicity plan (c) is not the obstacle: a fixed sequence works and leaves the 13-16 PASS rule untouched.

An ADD becomes possible only after builds E1-E3 (end of note), and E1 needs a master ruling because it reads history
outcomes.

## (a) B's state covers 13-16 only

- **Row 28 fit B per hour, and only at hours 13-16.**
  - `SCORED_HOURS = (13, 14, 15, 16)` (`scripts/row28_run_v12.py:175`).
  - `arm_training` masks on one `hour` (`:2011-2016`), and the fit loop runs `for hour in SCORED_HOURS` (`:3059`).
  - These paths are on `claude/row28-yearround-history-20261102`, under
    `docs/research/row28-yearround-history-2026-11-02/`.
- **"hours 07-12 vs the L6 stack (section 4.4)" is `not_implemented_descriptive`** (`run/score_result.json:201`).
  - The prereg had pre-registered 07-12 as descriptive-only for every arm, against the served pre-13 comparator: the
    L6 stack over MG-1 (`prereg_row28.md:286`).
  - The runner never built it, so no arm has a 07-12 fit, prediction or score.
  - B at 07-12 is therefore a candidate never tested on history. A forward 07-12 arm would be a new candidate under
    B's spec, not a re-test of a history survivor.
- **The forward draft is 13-16 throughout.**
  - Scope: "The pre-13 half is out of scope, as in row 28 §4.4" (`prereg_row28b_forward.md:46`).
  - The 343b state's field list carries `hours: 13, 14, 15, 16` (`:231`).
- **What a 07-12 fit would need:**
  - **Inputs.** The rows already exist in the build path. The B-bound builder's coverage rule is hours 7-20
    (`prereg_row28.md:63`), and the bound module's own window is `WINDOW_HOURS = (7, 8, 9, 10, 11, 12)`
    (`src/weather/calibration/pooled_residual_model.py:97`, read only). No new data source is needed for history.
  - **Running max.** Before 13, `F` is still defined: it is the max over WU hourly rows up to the cutoff
    (`prereg_row28.md:170`). At 07-12 it is mostly the overnight or early-morning value, so the fit leans on `fh`
    and `current_temp`. No feature needs removing.
    - Serve-time parity changes: serving reads F from captured METAR (`prereg_row28.md:175`), and at 07-12 a METAR
      versus WU-hourly gap is a larger share of a small F. The forward parity control (draft §4, Q6) would need a
      07-12 leg.
  - **The 343b hours field.** 07-12 needs six more per-hour fits (07-12) from the same Dec 17-May 31 training rows.
    That means either a second state, or a 343b state whose hours field lists 7-16.
    - This touches L56's in-progress build and could change the 13-16 state sha. Not touched here; see the question
      to L56 below.
- **Question for L56 (to route).** Can 343b emit per-hour fits for 07-12 from the same training rows without changing
  the 13-16 fits, or the 13-16 state sha?
  - If so, would they be a separate state file (own sha) or the same file with `hours: 7..16`?
  - Does its `train_F_source` / `serve_F_source` pair hold at 07-12?

## (b) Power for a forward 07-12 B-S at N = 45 (rules 16 + 19)

- **No same-kind, same-distance SD exists.** No B-S contrast at 07-12 was ever computed (part (a)).
- **Bound setup.** The 13-16 SD (0.0803, `prereg_row28b_forward.md:123`) is a different distance, so rule 19 treats
  it as a near-twin and forbids it as the source. The formula below takes it only as the base of a stated bound, at
  multiples above the 13-16 gate's 1.5×.
  - The draft's own factors are reused: VIF 1.570, futility inflation ×1.07.
  - The formula is MDE80 = 1.07 × 2.802 × σ × √1.570 / √45 = 0.560 σ.

| σ bound (stated) | MDE80 at N = 45 |
| --- | --- |
| 1.5 × 0.0803 = 0.1205 (the 13-16 gate's bound) | 0.0675 |
| 2 × 0.0803 = 0.1606 | 0.0899 |
| 3 × 0.0803 = 0.2409 | 0.1349 |

- **No effect size exists either.** Rule 6 sets delta at half the history point (draft §6), and there is no 07-12
  history point.
  - The 13-16 delta 0.0684 is a different-distance near-twin. Borrowing it would break rule 19's intent, so it is
    not used.
  - At the edge-size floor (G 0.0057, draft §5), power is about 0.04-0.10 at any N ≤ 166, as the draft already says
    for 13-16.
- **Result.** Power cannot be projected, so the arm fails prereg_check (f), which needs power ≥ 0.5 at a sourced
  delta. The arm is unpowered as specified.
- **Recorded 07-12 candidate-vs-MG-1 dev contrasts are not usable.** L5 A1/A2 have MDE80 0.0062/0.0068 at 43 dev
  dates (`ESTABLISHED_FINDINGS.md:4536-4538`). They are another candidate and another season, on crossed date × market
  intervals rather than date-clustered ones, and possibly in a different Brier unit (row 28 uses the multi-band Brier,
  base ≈ 0.85).
- **Master's 40-50 dates for power 0.5** is the later 07-12 w step against the market (`feasibility.md` §5, row 82's
  bound). It is not this B-S arm, and it would still need a B-S 07-12 PASS first (MIM rule 4, `:160-161`).

## (c) Multiplicity: fixed sequence, 13-16 first; Holm is not allowed

- **Fixed sequence (allowed).**
  - Test 13-16 first under its PASS rule exactly as drafted (§5: point ≤ −0.0057, 95% upper bound < 0 on both the
    date-clustered and block-3 intervals).
  - Only if 13-16 PASSES is 07-12 tested, under the same rule at the same α.
  - FWER stays ≤ α, and the 13-16 rule is unchanged in every outcome. A 13-16 FAIL ends the family, and 07-12 is
    reported as not tested.
- **Holm (rejected).** It would test the smaller p at α/2. If 07-12 came first and failed, Holm would stop before
  13-16, so a 13-16 result passing at α would not pass. Either way the 13-16 PASS rule is weakened.
- **No added look.** 07-12 is read at the draft's single read (after the 45th date, earliest 2027-01-31). It gets no
  look of its own and no interim PASS; the (g) Rule B stops stay 13-16-only.
- **A 07-12 PASS** would claim model improvement at 07-12 only. Its own 07-12 w step would come next (master ruling 1;
  `feasibility.md`).

## (d) Rule 9 scope: the 07-12 arm would intersect

- **PT-1** (12-12..01-25) is a 07-12 test (`COOL_SEASON_PAPER_TEST_PREREG.md:38`).
  - Its candidate C-PT is the pre-13 half of the MG-2 composite: MG-1 plus L6's own-observations stack
    (`COOL_SEASON_PAPER_TEST_PREREG.md:44-46`). That is the same served pre-13 comparator a fair 07-12 S would use
    (`prereg_row28.md:286`).
  - The 07-12 arm's deciding dates 12-17..01-25 lie inside PT-1's dates, at PT-1's hours, with PT-1's candidate as S.
    This is an intersection.
  - The draft's read rule already defers every read until after PT-1's look (`prereg_row28b_forward.md:54`). The rule
    must name the 07-12 intersection explicitly.
- **L6_G** is a 07-12 forward screen (`src/weather/calibration/l6g_forward_look.py:37`). It runs N = 45 from a D0
  capped at 11-02 (`DECISION_LOG.md:282`), so with drops its later dates can reach past 12-16.
  - By the draft's own rule ("a claim whose scope cannot be shown not to intersect is treated as intersecting",
    `:60`), the read must also follow L6_G's look.
- **F8-MH, row 72, MG-1 shadow, MG-2 Rule B-1, T+1:** these are already listed (`:58-60`), and the 07-12 hours
  change nothing for them beyond what the draft already states.
- **The reserved window** (MG-1, 10-15..11-28; `reserved-confirmation-window.md:3-4`) does not reach 12-17.
- **Shared inputs (one more disclosure).** A 07-12 S reads the captured METAR and L6 inputs that PT-1 and L6_G
  also read. Sharing inputs is not a date claim, but the prereg must say so.

## Builds that would make an ADD possible (all outcome-blind except E1)

- **E1. Build row 28's pre-registered 07-12 descriptive output** (prereg §4.4): B fit at hours 07-12 on 2021-25,
  scored against the L6 stack.
  - It is POST-HOC, because the row-28 verdict is out. It reads history outcomes, so it needs a master ruling.
  - It is the only same-kind source for σ_d and delta (rules 6 + 19). Without it, (b) stays unprojectable.
- **E2. L56 answer** (part (a)), then the 07-12 fits as a separate state (own sha) that leaves the 13-16 state sha
  unchanged.
- **E3. Draft amendments (only after E1 and E2).** In the forward draft:
  - a 07-12 S definition (the served L6 stack, with its bound coefficients and state);
  - a 07-12 leg in the parity control;
  - the fixed sequence of (c);
  - the PT-1 and L6_G read-order lines of (d);
  - a prereg_check (f) block for 07-12 from E1's σ and delta.
