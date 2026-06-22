# 213. Current-Date WU History Expected-Degradation Handling [COMPLETE 2026-06-22 - CURRENT-DAY WU 400S ARE TYPED EXPECTED DEGRADATION]

Goal: handle current-date `wu_history` requests as an expected unavailable or
degraded path when the provider returns 400s, while preserving useful current
max and settlement-high evidence from supported sources.

Source: the 2026-06-21 log review found `73` `wu_history` 400 failures across
the 12 active market locations. These were not blocking source-status proof, but
they repeated throughout the target day and appeared as source failures in
per-location logs.

Why this matters: current-day WU history often behaves differently from settled
or previous-day history. Repeated 400s create noisy failure counts, hide real
provider outages, and can confuse current-high trust logic. The model should
know when this is an expected current-date limitation and degrade cleanly to
`wu_current`, METAR, official observations, or cached settlement ledger context.

## Design

1. Detect current-target-date `wu_history` calls before issuing or after the
   first 400 response, and classify them as expected current-date unavailable
   rather than generic provider failure.
2. Emit a distinct source status such as `expected_current_day_unavailable`
   with provider response detail, TTL, and fallback source selected.
3. Ensure reliability scoring treats this state differently from true stale,
   rate-limited, or failed historical data.
4. Add a daily summary counter that separates expected current-date WU history
   degradation from unexpected source failures.

- [x] Add current-date WU history classification and fallback state.
- [x] Update source-status reporting and fleet observability to separate this
  state from true failures.
- [x] Make current-high trust logic consume the cleaner fallback state.
- [x] Add fixtures covering current-date 400s for US and Toronto-style station
  IDs.
- [x] Backfill or annotate June 21 source-failure reports so the pattern is
  traceable.

## Completion Notes

Added typed expected-unavailable source metadata for current-target-date
`wu_history` 400s. `fetch_wu_history` now converts current-day Weather.com/WU
history 400 responses into `expected_current_day_unavailable` with
`http_status=400`, `cache_status=expected_unavailable`, and
`fallback_source=wu_current,metar,eccc_swob,current_high_ledger`.

Source-status rows now persist `fallback_source`, and source family/fleet
observability summaries expose `expected_unavailable_source_count` separately
from `failed_source_count`. Expected current-day WU history unavailability no
longer increments true failed-source counts or blocks source-status proof by
itself, while reliability/source freshness still records the explicit
`expected_unavailable:wu_history` state for downstream consumers.

Regression fixtures cover both Toronto-style (`CYYZ:9:CA`) and US-style
(`KATL:9:US`) WU history IDs, and a source-status proof fixture matching the
June 21 repeated-400 pattern.

Verification:

- `python -m pytest tests\model\test_current_day_wu_history_degradation.py tests\collection\test_collection_robustness.py tests\collection\test_live_variant_predictions.py tests\reporting\test_fleet_observability.py -q`

Acceptance: current-target-date WU history 400s no longer appear as repeated
generic failures; they produce a typed degradation state with a known fallback,
and source-status proof can distinguish expected current-day unavailability
from real provider failures.

Related: items 17, 23, 136, 153, 193, 212.
