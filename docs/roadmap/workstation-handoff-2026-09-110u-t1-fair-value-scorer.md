# Workstation handoff 2026-09-110u — T+1/T+2 fair-value reliability scorer

Written 2026-09-27 by the production agent (owner-approved). The informed-maker design requires a T+1 fair-value reliability
table before live; the frozen `docs/research/t1-fair-value-preregistration-2026-09-25.md` (on the weather-plugin branch)
defines it but no scorer exists. Owner approved running the scored read on the replay scoring day (2026-10-15) from the same
sealed bundles, disclosed in the replay execution manifest. Branch `codex/t1-fair-value-scorer-20260927`, base
`origin/codex/maker-replay-harness-20260926`.

## Build

`weather.market.maker_plugin.fair_value_score` implementing the pre-registration exactly (read its text; do not change any
frozen choice): first complete minute per UTC hour, paired Brier versus the captured mid, hourly to market-day averaging,
fixed reliability bins, the crossed bootstrap with the registered seed and replicate count, the UNDERPOWERED rule, NBP versus
fallback and lead 1 versus lead 2 reported separately. Read sealed replay bundles (110s shape, including the additive
`release_calibration_method` field). Deterministic JSON and Markdown; refuse to run before the registered earliest date.

## Deliverables

Fixtures only. Repo-wide audits in focused runs. Push, draft PR, report
`docs/roadmap/agent-report-2026-09-110u-t1-fair-value-scorer.md`, verdict first.
