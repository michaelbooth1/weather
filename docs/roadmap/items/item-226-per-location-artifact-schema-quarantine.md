# 226. Per-Location Artifact Schema Quarantine [COMPLETE 2026-06-22 - STALE PER-LOCATION ARTIFACTS HISTORICAL-ONLY]

Goal: quarantine or retire old per-location HGB artifacts from promotion
dashboards unless they are retrained under the active feature schema and
registry contract.

Source: `docs/roadmap/audits/location-performance-model-audit-2026-06-22.md`.
Old per-location artifacts use mixed feature store versions (`v0.2`, `v0.3`,
and `v0.4`), while active pooled candidates use `v1.3` or later. The artifact
registry marks many older per-location models as unregistered runtime artifacts,
so comparing them directly with current pooled candidates mixes schema,
training window, and registry status.

Why this matters: location-level analysis needs apples-to-apples artifacts.
Unregistered or stale-schema per-location models can look like useful
alternatives while actually measuring schema drift or old validation policy.

## Design

1. Add a promotion-dashboard filter for artifact registry status and feature
   schema family.
2. Label old per-location HGB artifacts as historical-only unless retrained
   under the active schema.
3. Add a report that lists artifact schema/version mismatches by market.
4. Provide a retrain path for per-location models only if they are needed as a
   controlled comparison against pooled F-family variants.

- [x] Add artifact schema/status filtering to model comparison reports.
- [x] Emit a per-location artifact quarantine report.
- [x] Remove unregistered stale-schema per-location artifacts from promotion
  candidate tables.
- [x] Add a test that stale-schema artifacts cannot appear as active promotion
  candidates.

## Completion Notes

Added `weather.reporting.data_quality.per_location_artifact_quarantine` with JSON and
Markdown outputs. The report scans the model artifact registry, pairs legacy
per-location HGB files with their `feature_model_coefs*` schema metadata, and
marks per-location artifacts as promotable only when they are active registry
variants using the active feature-schema family.

The regenerated `data/backtest/per_location_artifact_quarantine.json` found
`24` per-location HGB/coefs artifacts. All `24` are
`unregistered_runtime_artifact`, all `24` use stale `toronto_feature_store_v0.x`
schemas, all `24` are labeled `historical_only`, and active candidate
violations are `0`.

Promotion refresh now reads this report, shows `Per-location artifact
quarantine` in the operational promotion gates, includes the artifact path in
the refresh artifact table, and adds a `per_location_artifact_quarantine`
readiness blocker if any stale per-location artifact is registered as an active
candidate.

Verification:

- `python -m pytest tests\reporting\test_per_location_artifact_quarantine.py -q`
- `python -m pytest tests\calibration\test_promotion_refresh.py -q`
- `python -m weather.reporting.data_quality.per_location_artifact_quarantine --artifact-registry artifacts\manifests\model_artifact_registry.json --json-out data\backtest\per_location_artifact_quarantine.json --report-out data\backtest\per_location_artifact_quarantine_report.md --fail-on-active-violation`
- `python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\pooled_candidate_replay_latest.json --precomputed-candidate-report data\backtest\pooled_candidate_replay_latest_report.md --candidate-hourly-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_ten_minute_performance.json --skip-serving-gauntlet`

Acceptance: promotion dashboards and model-comparison reports exclude
unregistered or stale-schema per-location HGB artifacts from active candidate
comparisons, or show them only in a historical section with an explicit
non-promotable label.

Related: items 33, 34, 48, 83, 89, 224.
