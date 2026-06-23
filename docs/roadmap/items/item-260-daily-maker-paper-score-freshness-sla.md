# 260. Daily Maker Paper-Score Freshness SLA [OPEN 2026-06-23 - MM PAPER REPORT STALE UNTIL MANUAL JUNE 19-22 REFRESH]

Goal: run `weather.market.mm_paper` daily against the latest completed active
maker run folders and mark maker evidence stale when `mm_paper_report.md` does
not cover the latest completed active day.

Source:
`docs/roadmap/audits/trading-stack-performance-strategy-audit-2026-06-23.md`.
The audit found the standard maker paper report stale until a manual narrow
refresh wrote `data/backtest/mm_paper_june19_22.md` and
`data/backtest/mm_paper_june19_22.json`. That refresh found `33` conservative
fills and `+1.6556` USDC net after estimated fees/incentives, but the gate
remained `OPEN` with zero live-forward paper days.

Why this matters: maker paper scoring is only useful if it stays current. A
stale report can make the system appear to have fresh maker evidence while the
latest active days are blocked, degraded, or non-countable.

## Design

1. Add a daily refresh step that discovers the latest completed active maker
   run folders under `data/mm_runs`.
2. Run `weather.market.mm_paper` over the latest eligible folders and write the
   standard `mm_paper_report.md` and JSON status artifacts.
3. Record latest-covered active day, latest-completed active day, live-forward
   day count, conservative fills, and gate status in machine-readable output.
4. Surface maker paper-score freshness in daily refresh status and the
   market-making dashboard or report.
5. Block maker live-forward profitability evidence when the report is stale.

- [ ] Add latest-maker-run discovery to daily refresh.
- [ ] Regenerate the standard maker paper report daily from latest eligible
  run folders.
- [ ] Add freshness fields to the report and status JSON.
- [ ] Make stale maker paper-score status block maker evidence countability.

Acceptance: `mm_paper_report.md` and its JSON sidecar cover the latest
completed active maker day, daily refresh reports the paper-score freshness
status, and maker evidence is marked stale when the standard report does not
cover that latest completed active day.

Related: items 44, 57, 210, 211.
