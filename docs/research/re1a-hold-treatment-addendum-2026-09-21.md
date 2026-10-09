# RE-1A place-and-hold treatment addendum — 2026-09-21

**PROPOSED — owner ratifies before the first order. No live authority.** This
dated addendum corrects only RE-1A's treatment duration and aggregation unit,
as required by mission 09-80b. The frozen source is
[liquidity-reward-epoch preregistration at a14ce80dc](https://github.com/michaelbooth1/weather/blob/a14ce80dc/docs/research/liquidity-reward-epoch-preregistration-2026-09-20.md).

Assess the 180 visible two-sided minute floor and `P_many >= 2.0` cumulatively
on **one band within one UTC reward day**, summing place-and-hold sessions.
Each session has a 120-minute ceiling. Permit at most four sessions per UTC
day and three reward days for RE-1A; report every day and every attempted
session, including failures and inconclusive outcomes. The immutable
`stage2_hold_v1` profile encodes these ceilings. Cleanup must fit within the
same UTC reward day. Missed, invisible or unobserved intervals count as zero.

The prediction remains the sum of per-minute reward shares. Retain `P_many`
and `P_single` and freeze each session's prediction and journal hash before
opening any earnings observation. Daily SDK accrual is not proof of payment;
the next-day verdict needs complete, independently reconciled payment evidence
for that maker, condition and UTC reward day.

**Unchanged:** RE-1M; the configured tomorrow-market selection rule and tie
order; outward-snapped twenty-share quote prices; prediction formula; owner
veto of the entire selection rather than substitution; and verdict thresholds.
For adequate evidence, `k = paid / P_many`: `k >= 0.5` is `PAID_AS_MODELLED`,
`0.1 <= k < 0.5` is `PAID_DILUTED`, and zero paid with observed scoring and
`P_many >= 2` is `NOT_PAID`. All other cases are `INCONCLUSIVE`; fewer than 180
visible minutes, changed reward settings or incomplete evidence are always
inconclusive. None of these outcomes is a profitability or deployment claim.

Owner ratification: **not supplied**. The
[owner decision draft](../operations/stage2-hold-owner-authorization-draft.md)
owns the proposed grants and residual cancellation exposure.
