# 85. Independent Market-Day Evidence Expansion For Variant Evaluation [COMPLETE 2026-06-16 - EVIDENCE GROWTH MONITOR LIVE]

Goal: increase the number of independent settled observations available for
variant decisions, not just the number of variant probabilities scored over the
same observations.

Source: `docs/research/MODEL_VARIANT_AUDIT_2026-06-16.md`. The audit found
that most current F-family variants share the same 44 market-days, 6,130
snapshots, and 11 markets; the inspected item 35 density export was the only
variant export that expanded independent coverage to 51 market-days and 12
markets.

Why this is missing: multi-variant testing improves paired comparison speed,
but the bottleneck for stronger promotion claims is still daily settled
market-day collection and broader replay coverage.

- [x] Add an evidence-growth report tracking unique market-days, snapshots,
  bands, settled labels, markets, and source families separately from scored
  variant rows.
- [x] Define the minimum independent evidence increment required before making
  a new broad promotion claim, such as a required number of new settled
  market-days or per-shadow-market labels.
- [x] Wire the daily settled market-day refresh to update the evidence-growth
  report so weekly/monthly reviews can prove whether the corpus actually grew.
- [x] Alert when variant rows increase but unique observation count does not.
- [x] Prioritize additional labels for the current F-family shadow markets:
  Austin, Chicago, Dallas, Miami, NYC, San Francisco, and Seattle.

Acceptance: variant reviews can show exactly how independent evidence changed
since the prior review and which markets gained new settled labels.

Completion update 2026-06-16:

- Added `weather.reporting.candidate_lifecycle.variant_evidence_growth` and the compatibility CLI
  `src.variant_evidence_growth`.
- The report tracks scored rows, unique market/date/snapshot/band observations,
  snapshots, market-days, markets, bands, settled labels, source-family counts,
  row multiplier, per-market coverage, priority shadow-market flags, and delta
  versus a baseline run.
- The default minimum increment for a new broad promotion claim is explicit in
  the report and CLI: at least `1` new unique observation and `1` new
  market-day versus the chosen baseline, configurable by
  `--min-unique-observation-increment` / `--min-market-day-increment` and the
  daily-refresh passthrough flags.
- Wired the report into `weather.operations.daily_refresh` as
  `model_variant_evidence_growth`, with `--variant-evidence-current`,
  `--variant-evidence-baseline`, and `--skip-model-variant-evidence-growth`
  controls. Missing current inputs skip the step rather than failing the whole
  daily refresh.
- Generated `data/backtest/model_variant_evidence_growth_report.md` comparing
  item 86 against item 70/71. It correctly returns `ALERT`: scored rows grew by
  269,720 while unique observations changed by 0. Current coverage remains
  67,430 unique observations, 6,130 snapshots, 44 market-days, and 11 markets.
- Priority shadow markets are explicitly flagged in the generated per-market
  table: Austin, Chicago, Dallas, Miami, NYC, San Francisco, and Seattle.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - EVIDENCE GROWTH MONITOR LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

