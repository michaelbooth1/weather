# 2026-06-21 WU History Current-Day Degradation

The 2026-06-21 log review found repeated `wu_history` HTTP 400 responses
across the active market locations. This pattern is now classified as
`expected_current_day_unavailable` when it occurs for the current target date,
instead of as a generic provider failure.

Expected source-status fields:

- `source=wu_history`
- `status=expected_current_day_unavailable`
- `http_status=400`
- `degradation_state=expected_current_day_unavailable`
- `cache_status=expected_unavailable`
- `fallback_source=wu_current,metar,eccc_swob,current_high_ledger`

Operational interpretation: current-day WU history 400s should be counted under
`expected_unavailable_source_count`, not `failed_source_count`. They should be
reviewed with current-high fallback evidence from `wu_current`, METAR/ASOS,
official observations, and the current-high ledger rather than paging as a
settled-history outage.
