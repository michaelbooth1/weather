# Workstation handoff 2026-09-110x — journal of the owner's manual one-sided orders

Written 2026-09-27 by the production agent; owner approved (2026-09-27) as the cheap live test of the one-sided thesis.
The owner places manual resting orders (for example BUY YES @0.85 and BUY NO @0.90 on MrBeast view markets) that earn
liquidity rewards. We need a durable, read-only journal that measures them honestly. Branch
`codex/manual-order-journal-20260928`, base `origin/master` after the 2026-09-27/28 landing (the wallet reader is on master then).

## Build

`python -m weather.market.order_journal record --out <dir>` (read-only; uses the LAN wallet reader client and public CLOB
reads only; no order paths, no credentials beyond the existing reader client token file):
- Each run appends one hash-chained record: open orders (id, market/condition, side, outcome, price, size, matched), the
  market mid, spread and best levels at that time (public `/book`), reward terms (`/rewards/markets/<condition>`), today's
  reward earnings and current pool percentages (reader `/rewards`), positions and cash (reader `/summary`).
- Fill detection from successive records plus reader `/trades`: for each fill, capture fill time/price/size and schedule
  markouts at +5, +30 minutes and at settlement from public price history (`/prices-history`), filled in by later runs.
- `report`: per order and per market — reward accrued, fills, markouts (5/30/settlement), cash-days tied up, reward-share
  path, and net = rewards + settlement markout; plus the same for a hypothetical two-sided quote at equal distance (reward
  x3 by the Q_min rule, symmetric fill exposure) as the baseline. Mark everything `owner-discretionary` (manual) so it never
  enters automated campaign data.
- A roll-free lease-free PowerShell runner and registrar (every 5 minutes; light; `-WhatIf`; hash pins), and docs.

Fixtures only (recorded reader/CLOB responses). No orders, cancels or signing. Repo-wide audits in focused runs. Push, draft
PR, report `docs/roadmap/agent-report-2026-09-110x-manual-order-journal.md`, verdict first, exact production registration
commands.
