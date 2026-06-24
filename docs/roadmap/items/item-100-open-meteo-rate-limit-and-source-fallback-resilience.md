# 100. Open-Meteo Rate Limit And Source Fallback Resilience [COMPLETE 2026-06-18 - DEGRADED SOURCE PROVENANCE LIVE]

Goal: prevent a single provider rate limit from degrading all active-market
model rows during a live trading day.

Source: `docs/research/MODEL_LIVE_REVIEW_2026-06-16.md`. The June 16 live
review found `open_meteo` and `open_meteo_multimodel` failed across the US
markets in the latest source-status rows. Toronto also had an Open-Meteo
failure. The model still produced rows, but one source family failed fleet-wide
while several model-market disagreements depended on late-day forecast
redundancy.

Why this is missing: item 74 expanded Open-Meteo feature coverage, but live
serving still needs fleet-level request budgeting, cache reuse, backoff, and
fallback semantics that avoid synchronized provider failures.

## Design

Keep model math unchanged. Treat Open-Meteo resilience as a source-fetch,
provenance, and gating problem so today's rows remain comparable to prior
snapshots while degraded evidence is visible.

1. Classify Open-Meteo-backed sources as one source family:
   `open_meteo`, `open_meteo_multimodel`, `global_ensemble`, and `eccc_gem`.
   Their successful rows carry `source_family=open_meteo`.
2. Before a family fetch hits the provider, reuse a same-target-date
   last-good payload younger than a short fresh-reuse window. This is the
   fleet request budget: snapshot, replay, forecast, and observation loops can
   call the same model path without duplicating equivalent Open-Meteo requests
   inside that window.
3. Retry HTTP 429 responses with capped exponential backoff and any
   `Retry-After` hint. If attempts are exhausted, record
   `status=rate_limited`, `http_status=429`, and `retry_after_seconds`.
4. If a rate-limited fetch has a valid last-good payload inside the source TTL,
   serve it as `status=rate_limited_cache`, not plain `stale_cache`, while
   preserving the payload, hash, original `fetched_at`, cache age, TTL, and
   provider error.
5. Widen source-status and forecast-payload artifacts with degradation fields:
   `source_family`, `http_status`, `retry_after_seconds`,
   `degradation_state`, and `cache_status`. Existing CSVs are widened by the
   snapshot store.
6. Fleet collection health reads the latest per-market source-status rows and
   reports source-family degradation counts. Model-only review remains allowed
   when rows have explicit provenance; trading/live-forward evidence is blocked
   when a family has failed, stale, or rate-limited fallback rows.

- [x] Add a fleet-level request budget for Open-Meteo and Open-Meteo
  multimodel calls so snapshot, forecast, replay, and observation loops do not
  duplicate equivalent requests inside the same TTL window.
- [x] Add exponential backoff and retry-after handling for HTTP 429 responses,
  with source-status rows that distinguish rate limited, failed, stale-cache
  fallback, and fresh-cache reuse.
- [x] Reuse valid cached forecast payloads across active markets when the
  provider is rate-limited, while preserving payload hash, fetched-at time, and
  age in source-status and forecast payload artifacts.
- [x] Add source-family degradation metrics to fleet observability: affected
  market count, failed source count, fallback source count, and whether model
  rows are still allowed to count for model-only review versus trading evidence.
- [x] Add tests that simulate provider 429s across multiple markets and prove
  the model writes explicit degraded-source rows instead of silently losing
  source redundancy.

Acceptance: an active-day run with Open-Meteo 429s still writes current model
rows with explicit degraded-source provenance, does not hammer the provider,
and clearly gates trading/live-forward evidence when source redundancy is below
policy.

Verification:

- `python -m pytest tests/model/test_source_adapters.py tests/model/test_source_cache_ttl.py tests/operations/test_observation_trigger.py::ObservationTriggerTests::test_snapshot_store_persists_source_degradation_metadata tests/reporting/test_fleet_observability.py::TestFleetObservability::test_fleet_collection_health_returns_one_row_per_registered_market`
- `python -m pytest tests/operations/test_observation_trigger.py tests/reporting/test_fleet_observability.py`
- `python -m pytest tests/market/test_mm_policy.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - DEGRADED SOURCE PROVENANCE LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

