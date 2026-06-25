# 260. Daily Maker Paper-Score Freshness SLA [COMPLETE 2026-06-23 - STANDARD MM PAPER SCORE FRESHNESS GATED]

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

- [x] Add latest-maker-run discovery to daily refresh.
- [x] Regenerate the standard maker paper report daily from latest eligible
  run folders.
- [x] Add freshness fields to the report and status JSON.
- [x] Make stale maker paper-score status block maker evidence countability.

Acceptance: `mm_paper_report.md` and its JSON sidecar cover the latest
completed active maker day, daily refresh reports the paper-score freshness
status, and maker evidence is marked stale when the standard report does not
cover that latest completed active day.

Completion note 2026-06-23: added maker paper-score freshness tracking to the
standard `mm_paper_report.json`/Markdown output, with latest completed active
day versus latest covered active day, live-forward day count, and stale
countability blocking. Daily refresh now runs `maker_paper_score` before
`trading_evidence`, writes the standard report/fill/known-edge artifacts, and
surfaces freshness in `daily_refresh_status.json` and the daily Markdown
report. Trading evidence recomputes freshness from `data/mm_runs` and blocks
maker countability when the standard report is stale. Verification:
`python -m pytest tests\market\test_taker_bot.py tests\market\test_mm_paper.py tests\reporting\test_trading_evidence.py tests\operations\test_daily_refresh.py tests\operations\test_schema_registry.py -q`.

Related: items 44, 57, 210, 211.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - STANDARD MM PAPER SCORE FRESHNESS GATED`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

