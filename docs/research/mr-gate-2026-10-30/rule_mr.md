# MR gate: does a live candidate predict the MARKET's error? (lane L3, DRAFT 2026-10-30)

Status: DRAFT for the coordinator. No dev-window row has been read. This file's sha256 is pinned in the
ledger row before any read; any change after that is a new file and a new sha.

## Population and inputs
- Dev scorecard default folds on `C:\swarm\v3layout` through `weather.calibration.market_blend`
  (not B-bound; imported, unchanged): layout dates 2026-08-01..2026-09-29, burn-in 08-01..08-14,
  scored 08-15..09-29, 11 US markets. Nothing dated after 2026-09-29 is read; no 88a, panel or
  settlement data for 09-30..10-15.
- Market vector m: exactly as the scorecard scores it, **capture-time arm (PRIMARY, master 2026-10-25)**.
- Candidate vector c: the candidate's frozen dev emit (listed below), joined on the scorecard's cells.
  Every candidate input must be dated by receipt at or before the row's capture time; an emit that
  fails this is refused, not repaired in place.
- Realised y: the scorecard's own label for the cell (dates <= 2026-09-29 only).
- Code: harness branch from `claude/loyo-screen-harness-20261030` @ `d9ae63167`; runs from the pinned
  run env (receipt records git HEAD, clean tree required).

## Controls (run first; any miss refuses the whole run, exit 7)
C1 served R all 1.774 / 00-16 1.526 (market_blend's existing control); C2 MG-1 07-12 excess 0.0120;
C3 the w = 0 identity (blend == market, R == 1 exactly).

## P0: market-residual prediction (per candidate, in its own hour block)
Per scored cell (snapshot x band): e = y - m (the market's error), s = c - m (the candidate's
disagreement). Statistic: pooled Pearson rho(s, e) over cells in the block. Interval: date-clustered
bootstrap, 2,000 draws, seed 20261024 (harness default). Placebo: the same statistic with c replaced by
market_blend's date-deranged placebo vector (seed 20260921).
**P0 PASS iff** lower bound of rho > 0 **and** the placebo's interval covers 0.

## w gate (per candidate, only if P0 passes; reported either way)
market_blend's walk-forward log pool, unchanged: g = m^(1-w) c^w, rule-4 impossible bands zeroed,
renormalised to sum(m); w on 0.00..1.00, fitted by date on dates <= d - 2 (burn-in included), pooled
Brier objective, fit block = the candidate's block. Report mean w, blend R = blend Brier / market Brier,
placebo w and R, floor-only R (w -> 0+), each with the date-clustered and crossed intervals.
**w PASS iff all of:** mean w >= 0.05; blend R upper (date-clustered) < 1; paired blend - placebo Brier
upper < 0; paired blend - floor-only Brier upper < 0. A win against MG-1 or served alone does not count.

## Verdict per candidate
PASS = P0 PASS and w PASS. Otherwise KILL (as an edge-over-market candidate on these dates).
Dev wins remain provisional (ledger rules); each candidate is one K row toward the multiplicity count.

## Candidates (one K row each)
1. R-R: P3d_H 07-12 (HRRR hourly extras), frozen state `e9276477…` (ledger row 38); block 07-12.
2. R-K: P3d_H 13-16 (k_max, k_gap, k_tcdc), frozen state `e891d884…` (row 38); block 13-16.
3. GEFS 31-member mean (06Z, sp25, corpus rows `8f512ad9…`): ARM TO BE DEFINED by ruling (see report);
   not run until defined in a new rule file.
4. R-ODC components: NOT TESTABLE under the date rule (see report); no row until ruled.

## Step 3 (conditional, separate row): dev tradability replay of the best PASSing w only
Not run unless a candidate PASSes; its own rule file and ledger row come first.
