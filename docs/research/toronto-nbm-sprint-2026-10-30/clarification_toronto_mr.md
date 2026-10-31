# MR gate 37cb46be: Toronto clarification (lane L8, 2026-10-30)

Base rule: `docs/research/mr-gate-2026-10-30/rule_mr.md`, sha256
`37cb46be8d8ddb272ac69638d71de8d023eddff2384e0a6824e00a18417f34ac`. Its file is on
`claude/ledger-74-76-mr-gate-20261030` and the code is `market_blend` in the run env at `cf381f0f3`.

This clarification was committed with DEV_WINDOW_LEDGER row 77, before any Toronto dev read under the sprint
rule. It applies only to the Toronto NBM sprint, `rule_toronto_nbm.md`. Everything not changed below stays
as in 37cb46be.

## 1. Population

- **Market:** Toronto (CYYZ) only.
- **Snapshots:** dev snapshots captured on target dates 2026-08-01..09-29, local hours 07..16, with
  burn-in 08-01..08-14 and scoring 08-15..09-29.
- **Market vector m:** the capture-time arm, as in 37cb46be.
- **Intervals:** with one market, all are **date-clustered** (2,000 draws, seed 20261024). The crossed
  interval is not reported.

## 2. Calibration-matched placebo (replaces the placebo condition of P0)

Source: the definition from review 2026-10-30, adopted in the L3 sweep rule. L3's sha256 will be added here
by a later clarification once it lands; the definition below stays unchanged.

- **Disagreement:** s(d, h, k) = c(d, h, k) − m(d, h, k) for date d, local hour h and band k.
- **Derangement:** within each hour h, a derangement π of the scored dates (no date maps to itself) gives
  c_pl(d, h, k) = m(d, h, k) + s(π(d), h, k).
- **Band alignment:** bands are aligned by their temperature label. A band of d that has no counterpart in
  π(d) takes s = 0. If π(d) has no snapshot at h, the nearest earlier snapshot of π(d) is used, or s = 0 if
  there is none.
- **Clipping:** c_pl is clipped to [1e-4, 1] per band, then renormalised so that its sum over the
  snapshot's bands equals sum_k m(d, h, k).
- **Seeds:** 20 stated derangement seeds, **20261030 through 20261049**.
- **Placebo statistic:** for each bootstrap draw, rho_pl is the mean over the 20 seeds of
  rho(c_pl − m, y − m) on that draw's dates. The same date-cluster draws are used as for rho_c.

## 3. P0 decision (replaces 37cb46be's "P0 PASS iff")

**P0 PASS iff both:**

1. the lower 95% bound of rho_c = rho(c − m, y − m) is > 0; **and**
2. the lower 95% bound of the paired difference rho_c − rho_pl, computed on the same draws, is > 0.

37cb46be's date-deranged placebo (market_blend's deranged vector, seed 20260921) is still computed. It is
reported only, as a diagnostic, and no longer enters the decision.

## 4. w gate

Unchanged from 37cb46be, with the Toronto population and date-clustered intervals. "Placebo w and R" in
the w gate means the calibration-matched placebo, averaged over the 20 seeds. The date-deranged one is
reported alongside.
