# T+1 forward test: day-ahead NBM NBP, ECMWF ENS and their blend vs the T+1 market (lane L3)

**Status: DRAFT — not frozen; freezes only on the owner's Q1/Q2 answers.** It also needs the freeze preconditions in
section 8. Drafted 2026-10-30. This is a dated research draft, not canonical guidance. No ledger row and no rule sha
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

## 4. Comparator m (the T+1 market)

- **Gamma YES where captured.** No capture of Gamma "Yes" prices at T+1 exists today: the snapshot loop records same-day
  events only (S1 report). So **the book rule is the primary comparator**, unless a Gamma T+1 capture is in place
  before freeze. If one is, the freeze row names it.
- **Book rule:**
  - m_b is the YES mid of band b's horizon-1 CLOB book at the capture minute, with both sides present and spread
    ≤ 0.10.
  - If that is not available, use the latest valid mid within the previous 10 minutes. Otherwise the band is missing.
  - **The full ladder is required:** a snapshot with any missing band is uncovered.
  - A snapshot is also uncovered if Σ_b m_b lies outside [0.90, 1.10].
  - The CLOB `last_trade_price` is never used.
- **The 88a recorder does not satisfy the full-ladder rule.** Its universe is the top ten conditions per city, with at
  least three per horizon (`maker_evidence_public.select_universe`). That is about 3–4 bands per T+1 snapshot in the
  cf tape. See precondition P1.

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
  - Under the single-look default (Q1(b)), the stops are applied at the one look to the date-ordered path, and a path
    that would have stopped is recorded FUTILE or HARM.
- The final interval is the date-clustered one, with a block-3 interval reported alongside. If they disagree, the more
  conservative verdict applies.

## 8. Dates, look and freeze preconditions

- **Accrual starts at freeze.** The first target date is the first T whose whole capture day D starts after the freeze
  commit.
- **Look:** a single look, strictly after B's 12-13 look and under the one-date rule (no other forward look on the same
  date). The freeze row fixes the date. If fewer than 52 countable dates have accrued by then, the look waits.
- **Q1 (OWNER): the 88a read scope at look time.** The comparator is the capture-time T+1 market after 09-29, which the
  embargo closes. The owner rules:
  - which 88a (or other book store) horizon-1 rows may be read: stores, date range, events and fields;
  - whether interim futility reads are opened (a), or the stops are applied only at the single look (b, the default);
  - that labels travel at the same look.
- **Q2 (OWNER): the reserved window.** A1 and A3 read NBM station guidance into band probabilities, which makes them
  NBM-guidance-to-band candidates. Those are held out on MG-1's reserved dates (through 11-28, provisional, may move
  later). The owner either:
  - (a) grants a T+1-only exemption, as was done for MG-2 and MG-3; or
  - (b) starts A1 and A3 accrual at the first date after MG-1's recorded last date.

  A2 accrues from freeze in either case.
- **P1 (master confirms before freeze):** the host's CLOB book loop records and keeps horizon-1 YES books for **every
  band** of each in-scope T+1 event, minute-stamped, for the whole accrual. The 88a top-ten universe does not meet this.
- **P2:** the NBM text recorder and the ENS recorder have both been running with closed cycle or run manifests for at
  least 3 consecutive days. ENS was started 2026-10-30 18:34Z and had fetched no run when this draft was written.
- **P3:** the emitter is built and tested on recorder data only, and its sha is pinned.

## 9. Not done under this rule

- No outcome, label or price read after 09-29 before the look.
- No fitting, no tuning and no added arm.
- No change to B, MG-1, MG-2, MG-3, `B_FORWARD_TEST_DESIGN.md` or any B-bound file.
- Nothing prepared for 09-30..10-14 dates.
