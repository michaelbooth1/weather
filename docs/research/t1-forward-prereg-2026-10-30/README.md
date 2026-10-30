# T+1 forward test: day-ahead NBM NBP, ECMWF ENS and their blend vs the T+1 market (lane L3)

**Status: DRAFT, not frozen.** It freezes at **P1**: the WS T+1 price recorder has 3 consecutive closed UTC days
(expected after UTC day 2026-11-02 closes). The freeze commit pins this file's sha256 in a new ledger row, which is
written before the freeze. After that, any change is a dated Clarification with its own sha. The freeze happens only
after the coordinator has been told; the lane never freezes on its own.

**History:**
- Rev 1 was drafted 2026-10-30.
- Rev 2 (`8772336e0`) followed master's ruling the same day: the comparator, accrual, no interim reads, and P1.
- Rev 3 (`a8c9d559d`) follows the owner's iterate-faster decisions of 2026-10-30 (`MODEL_IMPROVEMENT_METHOD.md` §5 on
  `claude/docs-owner-20261030` @ `e759a55d1`). It adds:
  - the intake reason;
  - the P0 stage, with w ahead of R;
  - standing blind accrual (rule 8), which replaces the owner Q2 exemption;
  - the one date rule (rule 9), which answers Q1;
  - sizing from the test's own numbers (rule 6), with the futility block written as a new pre-registration (rule 7).

- Rev 4 (this file) folds in master's rulings Q-a, Q-b and Q-c of 2026-10-30 (sections 0, 2, 7 and 8).

This is a dated research draft, not canonical guidance.

The test is outcome-blind until its single look. Its arms have zero fitted parameters, because no receipt-dated
day-ahead history exists to fit on (S1 report, 2026-10-30). The one learned quantity is the MR gate's walk-forward pool
weight w, which is fitted forward on accrued dates only. This draft does not touch `B_FORWARD_TEST_DESIGN.md`, the MG-2
binding package, any B-bound file, MG-1 or MG-3. It never alters B.

## 0. Intake (method §5 rule 2) and S1

**Why the market might lack this information.** Nothing about T+1 forecasting has been measured: the exhaustion
register's row 28 and lead L8 say "never measured". This is a new horizon, not a new source on an exhausted family.

- At T+1 no target-day observation exists. The T+1 price is therefore formed from guidance alone, and the venue's T+1
  books are thinner than T+0. The L3 survey of 2026-10-30 found that the lowest-temperature family is barely quoted,
  and the highest-temperature T+1 ladders have a median inner spread of about 3 cents.
- Two published day-ahead distributions may be under-used by a market that prices the T+1 ladder before the day's
  observations arrive:
  - the NBM percentile spread;
  - the ECMWF ENS member spread.

**Exhaustion check** (`EXHAUSTION_REGISTER.md` §6):
- **ENS:** the ENS *mean* was killed at T+0 (X5, a null over MG-1 at 00-12 and over t3-r3 at 13-16). Its reopen
  condition is "ENS spread as spread information". A2 uses the dressed member distribution, which is that spread, and
  it is used at a new horizon.
- **NBM debias and extra daily-max NWP:** these are exhausted at T+0. A1 is neither a debias nor a T+0 lever. It is the
  raw percentile distribution at T+1, where no T+0 result applies.
- **Master ruling 2026-10-30 (Q-a): NOT exhausted. A1 and A2 stay, labelled SCREEN.**
  - X5 and the T+0 kills closed spread as a width or scale modulator on our own T+0 model, where same-day
    observations dominate.
  - A1 and A2 are zero-parameter full pmfs. They are scored against a different market, at a horizon with no
    observations (register row 28). The new mechanism is the horizon.
- **If T+1 shows nothing** (no arm passes P0), X5's reopen line ("ENS spread as spread information") also closes for
  T+1. The result's register row says so.

**S1, outcome-free (done, 2026-10-30).** No receipt-dated day-ahead history exists, so there is no LOYO and no dev
stage.
- The arms read only forward recorders.
- Coverage and receipt dating are checked by P2 and the emitter tests (P3).
- The comparator exists only from the T+1 price recorder (P1).

So rule 2's "history, dev" tiers are empty by construction. Without them this is a **forward SCREEN**: it can kill, and
a PASS earns only a confirmation (section 7).

## 1. Question

Is the market weakest at T+1? A T+1 snapshot is one whose capture local date D is the day before its target local
date T (T = D + 1). The question: do fixed day-ahead guidance distributions predict the T+1 market's error, and carry
information about T's high that the T+1 market price does not?

## 2. Population

- **Markets:** the built-in highest-temperature markets that are scored under the current label ruling. That is the 10
  US markets other than Denver, plus Toronto. Denver is excluded because from 10-23 it settles on KDEN, is unscored and
  is out of B.
- **Units:** each market is handled in its native unit. Toronto bands are °C integers. The arms are computed in °F and
  mapped exactly by T_C = (T_F − 32)·5/9.
- **Snapshots:** the 24 local top-of-hour times 00:00..23:00 on day D, for target T = D + 1, per market. A
  (market, hour) is a cell.
- **Date rows:** one row per target date T. Each cell weighs equally within its date, and each date weighs equally.
- **Countable date:** at least 8 markets each have at least 12 hours covered by all three arms and the comparator.
  Nothing is imputed.
- **Labels:** venue-rule labels from 10-23 (METAR, with WU as fallback; master 10-25). KDEN is out with Denver. Labels
  arrive by one host label transfer at the look (section 8) and are never read before it.

## 3. Arms (fixed; no fitting)

An arm value is **covered** at a snapshot only if its source product passes the receipt rule in section 5.

1. **A1, NBM NBP.**
   - Source: the TXN percentile rows of the latest NBP cycle that passes the receipt rule, with cycle age at most
     13 h at capture. NBP is not issued every hour.
   - Rows used: TXNP1, TXNP2, TXNP5, TXNP7, TXNP9, the 10th, 25th, 50th, 75th and 90th percentiles, in integer °F.
   - Column: the TXN column valid at 00 UTC on T + 1. This is the daytime maximum ending in the evening of local day T
     at all 11 stations (UTC−4..−8).
   - Each integer percentile v stands for the continuous interval [v − 0.5, v + 0.5).
   - **Interpolation:** the CDF is piecewise linear through the knots (P10, 0.10), (P25, 0.25), (P50, 0.50),
     (P75, 0.75), (P90, 0.90).
     - Tied knots spread the mass between their levels uniformly over [v − 0.5, v + 0.5).
     - Lower tail: mass 0.10, uniform over [P10 − 1.5·max(P25 − P10, 1), P10].
     - Upper tail: mass 0.10, uniform over [P90, P90 + 1.5·max(P90 − P75, 1)].
   - **Band probability:** an interior band low..high gets F(high + 0.5) − F(low − 0.5). Open bands take the remaining
     mass.
   - Known limitation, not corrected: NBM's daytime-max period is not the calendar-day maximum.
2. **A2, ECMWF ENS.**
   - Source: the latest 00/12 UTC run that passes the receipt rule, with run age at most 24 h at capture.
   - Members: every ensemble member present. The open data carries 50 perturbed members; a control row counts if one
     appears. A run with fewer than 45 members is uncovered.
   - Member high: the maximum of the member's bilinear `mx2t3` over the windows wholly inside local day T. This is the
     containment rule of `tools/research/ecmwf_ens_daily.py`. Edge windows are excluded, and the value is converted
     from K to °F.
   - **Kernel dressing (fixed):** each member is dressed with a Gaussian of σ_k = 2.0 °F, and the members are equally
     weighted. Band probabilities use the same continuity rule as A1.
   - Known limitations, not corrected: no station bias correction, and the grid is 0.25°.
3. **A3, the equal-weight blend:** 0.5·A1 + 0.5·A2, band by band. A3 is covered only where both A1 and A2 are.

Every arm is floored at `market_blend.EPS` and renormalised before the pool. Nothing is tuned after this file's sha is
pinned. The three arms are one frozen batch (method §5 rule 5): one rule, one ledger row, one look.

## 4. Comparator m (the T+1 market; master ruling 2026-10-30)

- **Primary: Gamma Yes.** m_b is band b's Gamma `outcomePrices` entry labelled "Yes". This is the same price
  definition as the T+0 layout's `p_market_yes`. It comes from the WS T+1 price recorder (section 5) at the snapshot's
  top-of-hour cycle.
  - **The full ladder is required:** a snapshot with any band missing or non-finite is uncovered.
  - A snapshot is also uncovered if Σ_b m_b lies outside [0.90, 1.10].
  - A cycle row counts only if its receipt time is within 10 minutes after the top of the hour. That receipt time is
    the snapshot's capture time for the receipt rule.
  - The CLOB `last_trade_price` is never used.
- **Secondary check (reported, never a verdict):** the CLOB book YES mid, (best bid + best ask)/2, recorded in the same
  cycle. It is used only where both sides are present and the spread is ≤ 0.10. The report shows Σ mid and
  |Gamma − mid| per snapshot. P0 and Gates 1 and 2 are recomputed on the mid where the full ladder of mids exists.
- **Why not the book loop or 88a (master checked the host):** `WeatherClobBookLoopSupervisor` runs with
  `date_selection = market_local_date`, so it captures T+0 books only. 88a records the top-ten partial universe
  (`maker_evidence_public.select_universe`). No full horizon-1 ladder was captured anywhere before this recorder.

## 5. Emitter and receipt rule (daily, outcome-blind; method §5 rule 8)

- **Emitter:**
  - Once a day it writes per-snapshot A1, A2 and A3 band pmfs, with provenance, to an append-only emit store with a
    sha256 manifest.
  - It reads only the WS forecast recorders. It never reads a price, label or outcome.
  - The comparator is joined only at the look.
  - Emitter code is frozen at freeze (path and sha in the freeze row).
  - Accrual is blind and standing: the emitter runs from the freeze with no per-candidate exemption.
  - Parity checks run alongside it. A failed parity check VOIDs that date before the look and is recorded in the emit
    manifest, never silently dropped.
- **Receipt rule:** a forecast counts for a snapshot only if its receipt time is ≤ the snapshot's capture time. Receipt
  time is the later of these two:
  - the publication time the store records;
  - our own fetch time.

  So a product the recorder did not yet hold never counts.
- **Stores:**
  - **NBM text recorder** `C:\t\nbm_text\forward` (`<YYYYMMDD>/<HH>/nbm_text.jsonl`).
    - Publication time: the S3 `LastModified` on the `product` row (`last_modified_utc`; block rows carry it as
      `available_utc`).
    - Fetch time: `fetched_utc`.
    - Block rows are used only when they are followed by an ok `product` row with the same `file_sha256`.
  - **ECMWF ENS recorder** `C:\t\ecmwf_ens\forward`.
    - Publication time: the message `Last-Modified` on `points.jsonl`.
    - Fetch time: our fetch time.
    - Runs are used only once their manifest is closed.
  - **WS T+1 price recorder** (comparator only; joined at the look and never read by the emitter):
    `C:\t\t1_prices\forward`, recorder `tools/research/t1_price_forward_recorder.py`. Each row carries its receipt
    time, event and condition ids, and the cycle's full-ladder sum check. Cycle manifests are marked complete or
    incomplete. Before the look the lane reads only the manifests' completeness flags, for P1 and for countable-date
    coverage, and never a price.
  - **ECCC GEM** (`C:\t\eccc_gem\forward`) and **GEFS** (`C:\t\gefs_cycles\forward`): context only. They are recorded
    in the emit for description and are never an arm, a gate input or a tiebreak.

## 6. Gate (per arm, in order: P0, then w, then the Brier ratio; method §5 rules 3 and 4)

The stages run in order, and an arm that fails a stage stops there. Every stage's statistics are reported for every
arm, so the report shows each arm's full row.

### 6.1 P0, market-residual prediction (rule 3)

The form is the L3 MR sweep rule §5 (`docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md` at `93031af5d`, sha256
`85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`), on this test's population (all 24 hours,
burn-in dates excluded).

- **Per scored entry (snapshot × band):** e = y − m, the market's error. s = c − m, the arm's disagreement.
- **Statistic:** ρ_c, the pooled Pearson ρ(s, e).
- **Calibration-matched placebo:**
  - c_pl(d) = m(d) + (c(d′) − m(d′)). The donor date d′ comes from a within-(market, local hour) derangement over the
    accrued dates.
  - Clip, then renormalise to Σm.
  - J = 20 seeds, 20260921 + j. No outcome enters the placebo.
- **Primary:** Δ = ρ_c − mean_j ρ_pl,j.
  - Date-clustered bootstrap, B = 2,000, seed 20261024.
  - One-sided p = (1 + #{Δ*_b ≤ 0}) / (B + 1).
- **Multiplicity:** Benjamini-Hochberg at q = 0.10 across the 3 arms.
- **P0 PASS iff** BH rejects and the lower 95% bound of Δ > 0.
- Reported alongside: Δ per block (00-05, 06-09, 10-12, 13-16, 17-23) and per market. These are descriptive only.

### 6.2 Gate 1, w (rule 4; only an arm that passed P0 can PASS)

The machinery is the MR gate's w test, unchanged: `docs/research/mr-gate-2026-10-30/rule_mr.md`, sha256 `37cb46be…`,
with `mr_gate.gate_candidate` and `market_blend.pool()`.

- **Pool:** g = m^(1−w)·c^w, renormalised to Σm. Rule-4 impossible bands are zeroed.
- **w fit:** walk-forward on dates ≤ d − 2, grid 0..1, with a pooled Brier objective over all 24 hours.
- **Burn-in:** the first 7 countable dates fit w only and are never scored.
- **Placebo:** the calibration-matched placebo of 6.1, put through the same pool and w fit.
- **Floor-only control:** w → 0+. Here is what it reduces to:
  - At T+1 no target-day observation exists at capture, so rule 4 zeroes nothing.
  - The floor-only blend should therefore equal m exactly.
  - Any non-identity refuses the run (exit 7), as the w = 0 identity control does.
- **Gate 1 PASS iff all of:**
  - mean w ≥ 0.05;
  - blend R upper bound < 1 (date-clustered);
  - paired blend − placebo Brier upper bound < 0;
  - paired blend − floor-only Brier upper bound < 0.

### 6.3 Gate 2, the Brier ratio (only after Gate 1)

- **Gate 2 PASS iff** blend R = blend Brier / market Brier has a crossed (date × market) 95% upper bound < 1.
- The arm-alone ratio (w = 1) is reported and not gated.

### 6.4 Verdict and rows

- **Verdict per arm:** PASS iff P0, Gate 1 and Gate 2 all pass, the futility path of section 7 did not stop the arm,
  and the sanity controls held. Otherwise the verdict is KILL, FUTILE or HARM, whichever applies.
- **What a PASS means:** it is a forward SCREEN pass. These dates are B's dates (rule 8), so a PASS is never an edge
  claim and never a promotion. It earns two things:
  1. A dev tradability replay on these dates, once they have joined dev under rule 9 (rule 4).
  2. A powered confirmation on fresh dates disjoint from B's.
- **Per-date rows** (`t1_rows.jsonl`), written beside the result: one row per (arm, date). Each row holds:
  - cell counts;
  - the P0 sufficient sums (Σs, Σe, Σs², Σe², Σse, n) for the arm and each placebo seed;
  - the sufficient sums for blend, market, placebo and floor-only Brier;
  - w_d;
  - the paired differences.

## 7. Size and futility (method §5 rules 6 and 7; L8 template `claude/prereg-power-futility-20261030` @ `9c217b54a`)

- **Estimand:** dR, the daily (blend − market) Brier divided by the date's market Brier.
- **σ source (rule 6):** no measured sigma exists for this pair, because there is no T+1 history. σ is therefore the
  nearest dev back-out on the dR scale, labelled **dev**. rho is unknown, so VIF = 1.11, the maximum measured history
  VIF.
  - Primary: HRRR R-K σ_d = 0.085.
  - Also reported: R-R 0.069 and L6_G 0.032.
- **Effect (rule 6):** no dev effect exists, so "half the dev effect" cannot be formed. The declared screening effect
  is δ_s = 0.030 dR (master ruling 2026-10-30, Q-c: it stands under §5, and no owner restatement is needed). This is about half of the T+0 morning gap's guidance read (exhaustion register row 13: −0.012 to
  −0.015 Brier on a market Brier of about 0.2–0.25).
  - δ_s is never shrunk.
  - If any freeze check moves the power below 0.5, the lane STOPS and tells the coordinator. Such checks include a
    measured σ or VIF, or a coverage change in the countable-date rule.
- **N, from these numbers (rule 6: no screen below power 0.5, at least 20 dates before any PASS).**
  - Power at δ_s is Φ(δ_s·√N/(σ·√VIF·k) − 1.96), with the MDE inflated by k = 1.07 (rule 7, the upper end of 4–7%).
  - The smallest N with power ≥ 0.5 at the primary σ is **N = 40 scored countable dates**, so 47 countable dates in
    all with the 7 burn-in dates.
  - N = 40 ≥ 20, so a PASS is allowed.

  | σ_d | Power at δ_s, N = 40 (k = 1.07) | MDE80 at 40 (k = 1.07) | N80 at δ_s (k = 1.07) |
  | --- | --- | --- | --- |
  | 0.085 (primary) | 0.50 | 0.042 | 81 |
  | 0.069 | 0.68 | 0.035 | 53 |
  | 0.032 | 1.00 | 0.016 | 12 |

  - At the primary σ the test is underpowered for 80%, so it stays a SCREEN. That holds whatever the dates.
- **Training coverage (rule 6):** the arms fit nothing. The walk-forward w uses only accrued dates ≤ d − 2, so its
  coverage reaches the last forward date by construction.
- **Futility (rule 7, Rule B with the t bound).** The statistic is z = mean_k/(s_k·√VIF/√k), and positive means harm.
  It is applied at 7 / 14 / 21 / 31 scored dates:

  | Scored dates | Stop if |
  | --- | --- |
  | 7 | z > 3.143 (HARM) |
  | 14 | z > +0.5 |
  | 21 | z > 0 |
  | 31 | z > −0.5 |

  - A stop is final for that arm.
  - No look can PASS early, change N, change the estimand or refit.
  - **A look reads a date only when rule 9 allows it.** Every accrued date is also claimed by B (and A1/A3's dates by
    MG-1), so no date can be read before those tests have looked. The stops are therefore applied once, at the single
    look, along the date-ordered path of scored dates (master ruling 2026-10-30: no interim reads).
  - An arm whose path would have stopped is recorded FUTILE (or HARM at 7). Its later dates are not used for that arm.
  - Each look's ledger row comes before its read.
- **Intervals:** the final interval is the date-clustered one, with a block-3 interval reported alongside. If they
  disagree, the more conservative verdict applies.

## 8. Dates, look and freeze

- **Accrual (rule 8, standing blind accrual).** All three arms accrue outcome-blind from the freeze, with no
  per-candidate owner exemption. The owner's former Q2 (a T+1-only exemption from MG-1's reservation) is withdrawn as
  moot.
  - The first target date is the first T whose whole capture day D starts after the freeze commit.
  - A1 and A3 read NBM station guidance into band probabilities, so their dates inside MG-1's reserved window are also
    claimed by MG-1. That changes when they may be read, not whether they accrue.
- **Look (rules 8 and 9).** There is a single look. It comes strictly after the last look of every test that claims any
  of its dates:
  - B (look 12-13);
  - MG-1 for A1 and A3;
  - any other test in the look chain (L6_G, MG-3, PT-1) whose claimed dates intersect ours.

  The freeze row lists those tests by name and fixes the look as the later of two dates: the day after the last of
  their recorded looks, and the date by which 47 countable dates have accrued. If a claiming test's look moves later,
  this look moves with it. It is never earlier.
- **Q1 (read scope at the look): answered by rule 9 (owner 2026-10-30); confirmed by master 2026-10-30 (Q-b).** After
  the last claiming look, the accrued dates join dev, prices included. At the look the scorer reads only the following,
  for the accrued countable target dates only.
  - **Labels:** ONE host label transfer at the look, in the MG-2 §9.6 style.
    - Fields: the settlement bucket and promotion-countable.
    - Labels are venue-rule labels from 10-23 (METAR, WU fallback). KDEN is out per section 2.
    - Never via the daily channel, and no second transfer.
  - **Prices:** ONLY the WS T+1 recorder's Gamma Yes (primary) and book mid (secondary), as captured.
    - No 88a rows.
    - No backfill, and no other price source.
- **Freeze (the coordinator is told first; the lane never freezes on its own):**
  - **P1, the freeze point:** 3 consecutive closed UTC days of cycle manifests from the WS T+1 price recorder
    (`C:\t\t1_prices\forward`, task `L3 T+1 price forward recorder (logon)`, running since 2026-10-30 21:48Z).
    - A day counts only if every top-of-hour cycle is marked complete for at least 8 in-scope markets.
    - Only the completeness flags are read.
    - With full days 10-31, 11-01 and 11-02, P1 is met once UTC 11-02 closes.
  - **P2, checked in the same freeze row:** the NBM text recorder and the ENS recorder have both had closed cycle or run
    manifests for at least 3 consecutive days. ENS forward runs start 2026-10-31 00Z.
  - **P3, checked in the same freeze row:** the emitter is built and tested on recorder data only, and its sha is
    pinned.
  - If P2 or P3 is not met at P1, the lane reports that and waits. It does not freeze a partial batch.
  - The freeze row carries this file's sha256, the emitter sha, the recorder blobs, the claiming-test list and the
    look rule. It is written as `pending` before the freeze commit.

## 9. Not done under this rule

- No outcome, label or price read after 09-29 before the look.
- No fitting, no tuning and no added arm.
- No change to B, MG-1, MG-2, MG-3, `B_FORWARD_TEST_DESIGN.md` or any B-bound file.
- Nothing prepared for 09-30..10-14 dates.
