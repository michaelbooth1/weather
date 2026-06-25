# 198. Settled-Day Root-Cause Attribution Report [COMPLETE 2026-06-21 - CANONICAL REPORT AND DAILY-REFRESH STEP LIVE]

Goal: turn the manual June 20 forensic workflow into a repeatable settled-day
report that explains why a model/trading day was good or bad.

Source: the June 20 investigation required several ad hoc joins: final-winner
probability at taker fill snapshots, component Brier by regime, model top versus
market top versus final band, current-max anomaly checks, forecast-source
outlier checks, and startup feature plausibility checks. These joins produced
actionable findings that the existing hourly and 10-minute reports do not
surface directly.

Why this matters: scorecards identify weak slots, but they do not automatically
explain whether the cause is data quality, forecast inputs, post-processing,
component blending, market/trading policy, or serving runtime gaps. Without a
canonical root-cause report, each bad day requires slow manual analysis and
important patterns can be missed.

## Design

1. Add a `settled_day_root_cause` reporting module with JSON, Markdown, and CSV
   outputs.
2. Include sections for model-vs-market winner rank, component attribution,
   forecast-source outliers, current-max anomalies, startup plausibility,
   taker fill-time final-winner joins, and market-making preflight causes.
3. Assign each detected flaw to an existing roadmap item or propose a new item
   candidate.
4. Run the report after settled-day freshness, hourly performance, 10-minute
   performance, taker finalization, and market-making roll reports.
5. Add tests using June 20 fixtures for warm-tail taker loss, WU max anomaly,
   and F-market startup sentinel rows.

- [x] Implement the canonical settled-day root-cause report.
- [x] Add June 20 fixtures for the manual diagnostics from this audit.
- [x] Wire the report into daily refresh after settlement labels are available.
- [x] Emit a roadmap-mapping section with existing item links and suggested new
  item titles.
- [x] Require the report before making broad model-improvement or regression
  claims for a settled day.

Acceptance: a single command can explain the main failure modes for a settled
day, reproduce the June 20 findings, and route each actionable flaw to a
roadmap item or explicit no-action rationale.

Completion note 2026-06-21: `weather.reporting.settled_day_root_cause` now
emits JSON, Markdown, and issue CSV outputs and scans model-vs-market winner
rank, WU current-max anomalies, forecast warm outliers, startup plausibility,
taker fill losses, MM preflight blocks, and weak performance slots. The daily
refresh pipeline runs the report after distribution-stage attribution, and the
June 20 artifacts were generated at `data/backtest/settled_day_root_cause_2026-06-20.*`.
Focused reporting and daily-refresh tests cover the report and orchestration.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - CANONICAL REPORT AND DAILY-REFRESH STEP LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

