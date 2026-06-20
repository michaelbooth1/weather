# 150. Extra-Location Compatibility Registry [COMPLETE 2026-06-18 - COMPATIBILITY GATE LIVE]

Goal: add a registry and admission gate for non-Polymarket locations so only
settlement-compatible, provenance-clean, forecast-covered locations are allowed
into extra-location shadow training.

Source: the no-market transfer audit found that naive pooling is harmful, and
the external postprocessing literature emphasizes supervised
forecast-observation pairs plus station/location information. Extra locations
should therefore be admitted for label quality and compatibility, not merely
because they are easy to backfill.

Why this matters: a location without a market can still be useful if it has the
same target definition and high-quality forecast/observation history. It can be
noise if the daily-high definition, station siting, timezone cutoff, source
latency, or forecast feature coverage differs from the target markets.

## Design

1. Define an extra-location registry separate from Polymarket market specs. The
   registry should include station id, source ids, timezone, unit, coordinates,
   elevation, coastal flag, target definition, and provenance notes.
2. Grade every candidate location on:
   - settlement-label compatibility,
   - forecast-history coverage,
   - observation/source-state coverage,
   - station stability and revision risk,
   - unit/timezone/cutoff compatibility,
   - climate/domain similarity to target markets.
3. Block training use unless the location has enough independent labeled days
   and all required provenance fields.
4. Distinguish diagnostic-only locations from training-eligible extra
   locations.
5. Feed registry status into the transfer harness and evidence-growth reports.

- [x] Add a registry schema for no-market extra locations.
- [x] Add a compatibility grading report with PASS, SHADOW_ONLY, and BLOCKED
  states.
- [x] Add tests that reject missing station provenance, ambiguous target
  definition, missing timezone, and insufficient forecast-history coverage.
- [x] Add evidence counters for independent location-days and target-season
  coverage.
- [x] Document the minimum requirements for adding a new no-market location.

Acceptance: no-market locations cannot enter shadow training until they pass a
machine-readable compatibility gate, and every blocked or shadow-only location
has a concrete reason instead of silently becoming pooled training data.

## 2026-06-18 implementation update

Added `config/no_market_extra_locations.json` and
`weather.reporting.extra_location_registry`, with schemas
`no_market_extra_location_registry_v0.1` and
`extra_location_compatibility_report_v0.1`.

The registry requires station id, source ids, timezone, unit, coordinates,
elevation, coastal flag, cutoff policy, target definition, station stability,
climate class, provenance notes, forecast-history days, observation days, and
independent labeled days. The grader emits `PASS`, `SHADOW_ONLY`, or
`BLOCKED`, plus concrete reasons and evidence counters.

The current starter registry entries are diagnostic-only and generated a
`SHADOW_ONLY` report because they have no backfilled forecast/observation
history yet:

- `data/backtest/no_market_extra_location_compatibility.json`
- `data/backtest/no_market_extra_location_compatibility_report.md`

Minimum requirements for adding a training-eligible no-market location:
settlement-compatible daily-high labels, explicit station/source provenance,
timezone/unit/cutoff compatibility, stable station status, explicit climate
similarity class, at least 60 independent labeled days, at least 45 forecast
history days, and at least 60 observation days.
