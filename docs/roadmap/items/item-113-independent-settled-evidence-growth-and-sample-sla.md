# 113. Independent Settled Evidence Growth And Sample SLA [COMPLETE 2026-06-17 - EVIDENCE SLA LIVE]

Goal: make the promotion corpus grow in independent settled observations, not
just in variant rows scored over the same labels.

Source: the June 17 audit found
`data/backtest/model_variant_evidence_growth_report.md` in `ALERT`: scored rows
increased by 269,720 while unique observations, market-days, snapshots, market
count, band count, and settled label count all increased by 0. The same daily
refresh still reported only 44 F-family market-days for 11 F markets and
mostly 4 complete days per F market.

Why this matters: paired variant rows are useful for comparing candidates, but
they do not prove day-by-day model improvement. Broad promotion claims need
fresh independent market-days, especially for the seven shadow markets.

## Design

This item extends item 85. Item 85 makes evidence growth visible; this item
sets the operating SLA and remediation loop that should make evidence actually
grow.

1. Define a daily and rolling 7-day evidence target for each active market:
   new complete settled label, replay-input availability, source-status
   availability, and candidate-scored rows.
2. Split "no new evidence" into expected reasons and failures: market not yet
   settled, event not listed, snapshot loop outage, missing replay inputs,
   failed settlement reconciliation, or candidate replay failure.
3. Add a per-shadow-market sample target before promotion blockers can be
   cleared. Austin, Chicago, Dallas, Miami, NYC, San Francisco, and Seattle
   should not leave shadow only because paired rows multiplied.
4. Feed the target into daily refresh and daily learning: when independent
   evidence does not increase for an active settled day, emit an owner and a
   remediation command.
5. Add a compact trend table to promotion refresh or progress audit showing
   1-day, 7-day, and since-baseline changes in complete labels, market-days,
   snapshots, and unique observations.

- [x] Define the daily evidence-growth SLA and per-shadow-market minimum
  sample target.
- [x] Add no-growth reason classification to the evidence-growth report.
- [x] Emit remediation commands for missing replay inputs, missing settlements,
  and unscored candidate rows.
- [x] Add rolling evidence-growth trend rows to daily refresh/progress audit.
- [x] Block broad promotion claims when the latest run adds variant rows but no
  independent observations.

Acceptance: a daily audit can say whether the project gained independent
settled evidence since the prior run, why not if it did not, and which market
owner/action is required to make tomorrow's corpus larger.

## Implementation Notes

`weather.reporting.candidate_lifecycle.variant_evidence_growth` now emits an independent evidence
SLA with daily, rolling 7-day, and per-shadow-market thresholds, plus
market-delta rows, no-growth classifications, and remediation actions. Daily
refresh carries the SLA, no-growth reasons, and trend rows into the pipeline
summary, and daily learning blocks broad promotion readiness when the evidence
SLA says paired variant-row growth did not add independent settled evidence.

## Verification

`.\venv\Scripts\python.exe -m pytest -q tests\reporting\test_variant_evidence_growth.py tests\operations\test_daily_refresh.py::TestDailyRefresh::test_model_variant_evidence_growth_step_runs_from_daily_refresh_inputs tests\reporting\test_daily_learning.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-17 - EVIDENCE SLA LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

