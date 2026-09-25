# Workstation handoff 2026-09-100e — wallet reader P&L split

Written 2026-09-25 by the production agent. Finding: [afternoon audit](audits/afternoon-audit-2026-09-25.md) row 4. On
`codex/wallet-public-reader-20260925` @ `4ac157185`, `/summary`'s `unrealized_pnl_pusd` read **−9,703**: `portfolio_summary`
sums `[*positions, *resolved]` (`src/weather/market/wallet_reader.py:56-64`), so lifetime cost basis of ~103 long-resolved lots
(old MrBeast and May-July temperature markets) swamps the one live lot (Chicago, −12.38).

## Build (same branch)

- `unrealized_pnl_pusd` and `marked_positions_pusd` cover **live positions only**.
- New `resolved_pnl_vs_cost_pusd` and `resolved_count` for the resolved list (informational; never mixed into live or campaign).
- `campaign_pnl_pusd = cash + live marked value − campaign_net_contributions` when `--campaign-capital` is given (unchanged
  meaning; document that the owner should pass equity at the 2026-09-22 campaign start so historical dust cancels).
- `BLEED_LIMIT` uses only cash and campaign P&L (unchanged thresholds: cash < 60 or campaign < −40).

## Tests and deliverables

Fixtures: 1 live + 103 resolved gives live-only unrealized; resolved figure separate; campaign arithmetic with and without
capital. All 100a safety properties unchanged; fixtures only, no `.env`, no real account. Report: append to
`docs/roadmap/agent-report-2026-09-100d-wallet-reader-fixes.md` as "100e". Push is authorized; the owner restarts `serve`.
