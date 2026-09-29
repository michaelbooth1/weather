# Workstation handoff 2026-09-111c — storage classifications for 5g, and expected-disabled maker tasks

Written 2026-09-29 by the production agent. The owner approved 5g on 2026-09-29 on the condition that the classification
lands first. The 2026-09-29 cleanup preflight (`data/alerts/storage-decisions-20260929/` on production) blocked all 282
mm_runs scoring-projection files and `backtest/active_variant_shadow_attribution.jsonl` as `unclassified`. The watchdog
adopted from 110n (2026-09-29) flags two tasks that are disabled on purpose. Base `origin/master`; branch
`codex/storage-class-5g-20260929`. This is disk relief, so it may merge during the exam period.

## Work

1. In `src/weather/operations/storage_classes.py`, add reviewed classifications so `cleanup_preflight` classifies:
   - `mm_runs/*/*/mm_scoring_projection.csv` and `mm_runs/*/*/model_variant_mm_scoring_projection.csv`: a rebuildable
     projection whose rebuild source is the sibling `quote_intents_long.csv` / `model_variant_quote_intents_long.csv`,
     bound by size and mtime in `mm_scoring_projection_manifest.json`. The projection manifests stay retained.
   - `backtest/active_variant_shadow_attribution.jsonl`: the same class and family as its sibling
     `active_variant_shadow_long.csv` (`backtest_row_exports`).
2. In `scripts/ops/health_watchdog.ps1`, declare `WeatherMarketMakingDailyRoll` and
   `WeatherMarketMakingDailyRollSupervisor` expected-disabled, with the reason "live and paper maker paused by owner
   2026-09-25". Use a reviewed, named list, never a blanket silence: any other unexpectedly disabled task must still
   alert.

## What would falsify this mission

A classification whose rebuild source cannot actually rebuild the projection, or which also matches files that are not
rebuildable, is wrong. Say so rather than widening the pattern.

## Deliverables

Fixture tests: `cleanup_preflight` classifies all three path shapes and still blocks a projection whose quote-intent
source is missing; the watchdog stays silent on those two tasks and still alerts on another disabled task. Include the
repo-wide audits. Report `docs/roadmap/agent-report-2026-09-111c-storage-class-5g.md`, with the per-file roll verdict,
the new `health_watchdog.ps1` and `status.ps1` SHA-256 values, and the exact production re-registration command in the
110n report's form.
