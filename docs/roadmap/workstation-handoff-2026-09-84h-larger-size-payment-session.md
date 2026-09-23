# Workstation handoff 2026-09-84h — a larger-size RE-1 payment session

Written 2026-09-23 by the production agent. **Owner decision 2026-09-23:** payment tests may use **any band and any size**
within the dedicated testing wallet, **100 pUSD total, all of it for testing**; the RE-1 cap (three sessions, none after
2026-09-30) stays ([forward plan](../operations/forward-plan-2026-09-23.md), decision 4). Branch: `codex/re1-public-reads-ua-20260922`
(PR 85), stacked on `c771cbb42`. **Session 2 (2026-09-23 evening) stays on `c771cbb42` at 20 shares; this is for session 3.**

## 1. Why

At session 1's competition a full six-hour 20-share session accrues about 0.64, below the venue's 1-dollar daily minimum,
so the payment path (payout, asset, linking) can never be tested at 20 shares. Share rises with size: at session 1's final
competition, 50 shares gives roughly 11% and about 1.4 per six hours on a 53/day band. Session 3 must cross 1 dollar.

## 2. Change (money controls — smallest possible)

1. **Size becomes a per-session parameter** chosen before the confirmation phrase: the largest of {20, 30, 50, 75} whose
   two-sided reserve `size × (yes_buy + no_buy)` is at most **min(available_collateral − 10, 75)** pUSD at selection time.
   The chosen size, reserve and wallet reading are printed in the confirmation block and bound into the confirmation phrase
   digest. No CLI flag can exceed 75 shares or 75 pUSD reserve.
2. **Selection:** every configured band whose event date is local today, T+1 or T+2 and whose reward minimum size is at most
   the chosen size is eligible (not only UTC-tomorrow). The frozen ranking and the `predicted_360_minutes >= 2.0` rule stay,
   computed at the chosen size with the canonical estimator. The owner may still refuse any shown band at the phrase.
3. Everything else unchanged: ±1.5 c distance, requote rules, fill ends the session (84g handling), heartbeat, 6-hour fixed
   session, UTC-day rule, capital and open-order caps scaled to the chosen size only.
4. **New dated pre-registration addendum** `docs/research/liquidity-reward-epoch-addendum-2026-09-23b-size.md` written by
   this mission before any code: the treatment change (size rule, selection scope), that it follows session 1's data, the
   verdict rules (unchanged: frozen table and the 2026-09-23 addendum side by side), and the per-session worst case
   (the full reserve).

## 3. Tests

Size selection at wallet readings 97, 60, 40, 25 (25 gives 20 shares or refuses), reserve binding in the phrase digest, no
path above 75 shares/75 pUSD, eligibility of T+0/T+1/T+2 with reward minimums 20/100, prediction at the chosen size equals the
canonical estimator, all existing RE-1 suites green, the parity audit updated only where the size parameter enters. Full
suite through `workstation_heavy.ps1` with a short `--basetemp`, finished before 19:00 ET and never during a live session.

## 4. Boundaries and report

No `preflight`/`live`/`cancel-only`/`collect-*` by the agent; no `.env`; never touch the session worktree or campaign root.
Append a dated 84h section to `docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md`: verdict
first, the size rule with examples, test counts, the tip. Hand back the tip as soon as focused tests pass; the owner then
preflights it for session 3 (by 2026-09-29).
