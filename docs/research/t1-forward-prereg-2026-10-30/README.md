# T+1 forward test: day-ahead NBM NBP, ECMWF ENS and their blend vs the T+1 market (lane L3)

**Status: DRAFT — not frozen; freezes only on the owner's Q1/Q2 answers.** It also needs the freeze preconditions in
section 8. Drafted 2026-10-30; revised the same day on master's ruling (comparator, accrual, no interim reads, P1). This is a dated research draft, not canonical guidance. No ledger row and no rule sha
exist yet. The freeze commit pins this file's sha256 in a new ledger row, and any later change is a new file and a new
sha.

The test is outcome-blind until its single look. It has zero fitted parameters, because no receipt-dated day-ahead
history exists to fit on (S1 report, 2026-10-30). The one learned quantity is the MR gate's walk-forward pool weight w,
fitted forward on accrued dates only. This draft does not touch `B_FORWARD_TEST_DESIGN.md`, the MG-2 binding package,
any B-bound file, MG-1 or MG-3. It never alters B.

## 1. Question

Is the market weakest at T+1? We define a T+1 snapshot as one whose capture local date D is the day before its target
local date T (T = D + 1). The question: do fixed day-ahead guidance distributions carry information about T's high
that the T+1 market price does not?

## 2. Population

- **Markets:** the built-in highest-temperature markets that are scored under the current label ruling. That is the 10
  US markets other than Denver, plus Toronto. Denver is excluded because from 10-23 it settles on KDEN, is unscored and
  is out of B.
- **Units:** each market is handled in its native unit. Toronto bands are °C integers. The arms are computed in °F and
  mapped exactly by T_C = (T_F − 32)·5/9.
- **Snapshots:** the 24 local top-of-hour times 00:00..23:00 on day D, for target T = D + 1, per market. A
  (market, hour) is a cell.
- **Date rows:** one row per target date T. Each cell weighs equally within its date, and each date weighs equally.
- **Countable date:** a date where at least 8 markets each have at least 12 hours covered by all three arms and the
  comparator. Nothing is imputed.
- **Labels:** the label ruling in force at the look (master 10-25: the venue rule, with WU as fallback). Labels are
  read only at the look.

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
   - **Band probability:** an interior band low..high gets F(high + 0.5) − F(low − 0.5). Open bands take the
     remaining mass.
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
pinned.

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
  |Gamma − mid| per snapshot, plus the Gate 1 and Gate 2 statistics recomputed on the mid where the full ladder of
  mids exists.
- **Why not the book loop or 88a (master checked the host):** `WeatherClobBookLoopSupervisor` runs with
  `date_selection = market_local_date`, so it captures T+0 books only. 88a records the top-ten partial universe
  (`maker_evidence_public.select_universe`). No full horizon-1 ladder was captured anywhere before this recorder.

## 5. Emitter and receipt rule (daily, outcome-blind)

- **Emitter:**
  - Once a day it writes per-snapshot A1, A2 and A3 band pmfs, with provenance, to an append-only emit store with a
    sha256 manifest.
  - It reads only the WS forecast recorders. It never reads a price, label or outcome.
  - The comparator is joined only at the look.
  - Emitter code is frozen at freeze (path and sha in the freeze row).
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
    incomplete.
  - **ECCC GEM** (`C:\t\eccc_gem\forward`) and **GEFS** (`C:\t\gefs_cycles\forward`): context only. They are recorded
    in the emit for description and are never an arm, a gate input or a tiebreak.

## 6. Gate (per arm; w first, then the Brier ratio)

The machinery is the MR gate's w test, unchanged: `docs/research/mr-gate-2026-10-30/rule_mr.md`, sha256 `37cb46be…`,
with `mr_gate.gate_candidate` and `market_blend.pool()`.

- **Pool:** g = m^(1−w)·c^w, renormalised to Σm. Rule-4 impossible bands are zeroed.
- **w fit:** walk-forward on dates ≤ d − 2, grid 0..1, with a pooled Brier objective over all 24 hours.
- **Burn-in:** the first 7 countable dates fit w only and are never scored.
- **Calibration-matched placebo:** L3 sweep rule §5, `docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md`.
  - c_pl(d) = m(d) + (c(d′) − m(d′)), with the donor d′ taken from a within-(market, local hour) derangement over the
    accrued dates.
  - Clip, then renormalise to Σm.
  - J = 20 seeds, 20260921 + j.
  - No outcome is used.
- **Floor-only control:** w → 0+. Here is what it reduces to:
  - At T+1 no target-day observation exists at capture, so rule 4 zeroes nothing.
  - The floor-only blend should therefore equal m exactly.
  - Any non-identity refuses the run, as the w = 0 identity control does.
- **Gate 1 (w), PASS iff all of:**
  - mean w ≥ 0.05;
  - blend R upper bound < 1 (date-clustered);
  - paired blend − placebo Brier upper bound < 0;
  - paired blend − floor-only Brier upper bound < 0.
- **Gate 2 (Brier ratio), PASS iff** blend R = blend Brier / market Brier has a crossed (date × market) 95% upper bound
  < 1. The arm-alone ratio (w = 1) is reported and not gated.
- **Multiplicity:**
  - Primary p per arm is the one-sided date-clustered bootstrap p for paired blend − market Brier < 0 (B = 10,000,
    seed 20261024).
  - Benjamini-Hochberg at q = 0.10 across the 3 arms.
- **Verdict per arm:** PASS iff BH rejects, Gate 1 passes and Gate 2 passes. Otherwise the verdict is FUTILE, HARM or
  KILL.

  A PASS is a forward SCREEN pass (section 7). It earns a powered confirmation, never a promotion.
- **Per-date rows** (`t1_rows.jsonl`): one row per (arm, date). Each row holds:
  - cell counts;
  - the sufficient sums for blend, market, placebo and floor-only Brier;
  - w_d;
  - the paired differences.

## 7. Size and futility (L8 template, `claude/prereg-power-futility-20261030` @ `9c217b54a`)

- **Estimand:** dR, the daily (blend − market) Brier divided by the date's market Brier.
- **σ source:** no same-pair history exists, so σ is the nearest dev back-out on the dR scale, labelled **dev**. rho is
  therefore unknown, so VIF = 1.11, the maximum measured history VIF.
  - Primary: HRRR R-K σ_d = 0.085.
  - Also reported: R-R 0.069 and L6_G 0.032.
- **N = 45 scored countable dates after the 7 burn-in dates (52 countable dates in all).**
  MDE80(45) = 2.802·σ·√1.11/√45:

  | σ_d | MDE80 at 45 |
  | --- | --- |
  | 0.085 | 0.037 |
  | 0.069 | 0.030 |
  | 0.032 | 0.014 |

- No dev point estimate exists. So the test is declared a **SCREEN** unless the owner states an effect of interest
  ≥ 0.037 dR.
- N80 at an effect of 0.03 dR:

  | σ_d | N80 |
  | --- | --- |
  | 0.085 | 70 |
  | 0.069 | 47 |
  | 0.032 | 10 |

- The empirical-tail power is about 4–7% below nominal (L8).
- **Futility, rule B with the t bound** (z = mean_k/(s_k·√VIF/√k), positive = harm), at 7 / 14 / 21 / 31 scored dates:

  | Scored dates | Stop if |
  | --- | --- |
  | 7 | z > 3.143 (HARM) |
  | 14 | z > +0.5 |
  | 21 | z > 0 |
  | 31 | z > −0.5 |

  - A stop is final for that arm.
  - No interim look can PASS, change N, change the estimand or refit.
  - Each look's ledger row comes before its read.
  - **There are no interim reads** (master ruling 2026-10-30). The stops are applied at the single look, along the
    date-ordered path of scored dates. An arm whose path would have stopped at a look is recorded FUTILE (or HARM at
    look 7). Its later dates are not used for that arm.
- The final interval is the date-clustered one, with a block-3 interval reported alongside. If they disagree, the more
  conservative verdict applies.

## 8. Dates, look and freeze preconditions

- **Accrual depends on the owner's Q2.** In both branches the first target date for an arm is the first T on or after
  its accrual start whose whole capture day D starts after the freeze commit.
  - **Q2 = yes** (a T+1-only exemption from MG-1's reservation): all three arms accrue from freeze.
  - **Q2 = no:** A2 accrues from freeze. A1 and A3 accrue from target date 2026-11-29, or from the day after MG-1's
    recorded last date if that has moved later by then. A1 and A3 then reach their 52 countable dates later than A2.
    The look waits for all three arms, or the freeze row states a per-arm look date under the one-date rule.
- **Look:** a single look, strictly after B's 12-13 look and under the one-date rule (no other forward look on the same
  date). The freeze row fixes the date. If fewer than 52 countable dates have accrued by then, the look waits.
- **Q1 (OWNER): the read scope at look time.** The comparator is the capture-time T+1 market after 09-29, which the
  embargo closes. The owner rules which rows of the WS T+1 price recorder may be read at the look (date range, events
  and fields: Gamma Yes plus the book mid check), and that labels travel at the same look. If 88a rows are wanted as a
  further cross-check, they need their own named scope in the same answer. Interim futility reads are **not** opened
  (master ruling); see section 7.
- **Q2 (OWNER): the reserved window.** A1 and A3 read NBM station guidance into band probabilities, which makes them
  NBM-guidance-to-band candidates. Those are held out on MG-1's reserved dates (through 11-28, provisional, and the end
  may only move later). The owner answers yes, granting a T+1-only exemption as was done for MG-2 and MG-3, or no.
  The accrual bullet above gives both branches.
- **P1:** 3 consecutive days of closed cycle manifests from the WS T+1 price recorder (`C:\t\t1_prices\forward`). It
  must be registered by the coordinator on the owner's yes. A day is counted only if every top-of-hour cycle is marked
  complete for at least 8 in-scope markets.
- **P2:** the NBM text recorder and the ENS recorder have both been running with closed cycle or run manifests for at
  least 3 consecutive days. ENS was started 2026-10-30 18:34Z and had fetched no run when this draft was written.
- **P3:** the emitter is built and tested on recorder data only, and its sha is pinned.

## 9. Not done under this rule

- No outcome, label or price read after 09-29 before the look.
- No fitting, no tuning and no added arm.
- No change to B, MG-1, MG-2, MG-3, `B_FORWARD_TEST_DESIGN.md` or any B-bound file.
- Nothing prepared for 09-30..10-14 dates.
