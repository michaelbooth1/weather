# RE-1 session 3 size and selection addendum — 2026-09-23

Status: pre-registered before mission 84h code changes. Owns the session 3
treatment change authorized by the owner on 2026-09-23. Session 2 remains on
`c771cbb42` at 20 shares. This document does not authorize a live run.

This change follows session 1's data: the handoff reports about 0.64 dollars
for six hours at 20 shares under its observed competition, below the venue's
1-dollar daily payout minimum. It is a response to those observations, not an
outcome-blind treatment. No new session or payout evidence was read for this
mission. The dedicated testing wallet contains at most 100 pUSD, all for testing.

For each eligible band's two backed BUY prices, choose the largest size in
`{20, 30, 50, 75}` for which `size × (yes_buy + no_buy)` is at most
`min(available_collateral − 10, 75)` pUSD at selection time. Refuse if none fits.
Print the chosen size, full two-sided reserve, and wallet reading before the
owner's phrase; bind all three into its digest. No CLI option can raise either
the 75-share ceiling or the 75-pUSD reserve ceiling.

The selection universe is every configured band whose event date is local
today, T+1 or T+2, and whose reward minimum is at most its chosen size. Keep
the frozen ranking, other filters and `predicted_360_minutes >= 2.0`, using
the canonical estimator at the chosen size. The owner can refuse the shown
band at confirmation. Do not select a different band by discretion.

Keep the ±1.5-cent target distance, requote rules, heartbeat, fixed six-hour
duration, single UTC-day rule, and fill-ends-session handling from 84g. Scale
only the capital and open-order size caps to the chosen size. The conservative
per-session worst case is loss of the full two-sided reserve, at most 75 pUSD;
do not substitute expected losses or assume the two fills offset one another.

Verdict rules are unchanged: report the frozen 2026-09-20 table and the
owner-approved 2026-09-23 interpretation addendum side by side, including
adequacy, SHORT, payout-minimum and asset rules. Their authoritative sources
are on `codex/reward-test-attended-handoff-20260921` at `cc028cda` in
`docs/research/liquidity-reward-epoch-preregistration-2026-09-20.md` and
`docs/research/liquidity-reward-epoch-addendum-2026-09-23.md`.
The three-session cap, no session after 2026-09-30, hurdle and RE-2 conditions
remain unchanged. This treatment tests payment feasibility, not profitability.

Validate wallet readings 97, 60, 40 and 25, confirmation binding, absolute
ceilings, local-date eligibility and reward minimums, estimator parity, and
all RE-1 regression suites. The owner must preflight the new reviewed tip for
session 3. The implementing agent runs no live or collection commands.
