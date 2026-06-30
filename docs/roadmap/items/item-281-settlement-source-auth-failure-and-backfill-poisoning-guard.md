# 281. Settlement-Source Authentication And Transient-Failure Typing And Backfill Poisoning Guard [COMPLETE 2026-06-24 - FAILURE TYPING, RECOVERY, AND FLEET BLOCKERS LANDED]

Goal: stop authentication and transient failures of the canonical
Weather Underground settlement source from being silently recorded as
permanent "unavailable" history, and surface a multi-market settlement-source
auth outage as a fail-closed data-layer blocker instead of per-location noise.

Source: 2026-06-23 system-level roadmap audit of the settlement-truth and
source-provenance theme. `weather.sources.wu_history.WundergroundHistoryStore.write_fetch_error`
stamps every `requests.HTTPError` with `treated_as_source_unavailable: True` and
records the failed date range, and `unavailable_dates()` then feeds
`missing_dates`/`missing_ranges`, which both the `wu_history backfill
--skip-existing` path and `weather.collection.historical_backfill_plan` use to
decide what to re-fetch. There is no failure classification: a `401`/`403`
(disabled legacy paid-provider access), a `429` (rate limit), or a `5xx`/timeout
during a backfill window is treated identically to a true "no data for this
historical date" `400`/`404`. `history_coverage` then reports those days as
legitimate `source_unavailable_days`. The only existing typed handling, item
213, deliberately scopes to current-target-date `400`s as expected degradation
and does not cover historical auth/transient failures.

Why this matters: the WU history source is the canonical settlement
truth for all twelve markets. When the legacy paid-provider path fails during
an unattended backfill, every affected historical day can be permanently
appended to the per-station unavailable set and then skipped forever by
`--skip-existing` backfills and the resumable backfill plan, silently capping
settlement-truth and training-corpus depth with recoverable days that look
"unavailable." A fleet-wide auth failure is also a true single point of failure
that should be a P0 blocker, not 12 per-location failure counts that look like
ordinary current-day 400 noise.

Why it is not already covered: item 213 types only current-date `400`s as
expected and does not touch the backfill error log, `unavailable_dates()`, or
auth/transient classification. Item 100 owns Open-Meteo rate-limit/fallback
resilience, and item 102 owns Toronto ECCC runtime hardening; neither covers the
WU settlement backfill path or the permanent-skip poisoning hazard.
Items 29/30/64/265 own historical depth, redundancy, provenance, and settlement
revision audit, but none own failure-class typing for settlement-source fetch
errors or recovery of poisoned unavailable entries.

## Design

1. Classify WU history fetch failures into an explicit
   `failure_class` in `write_fetch_error`: `permanent_no_data` (true historical
   `400`/`404` with empty observations), `auth_failure` (`401`/`403`),
   `rate_limited` (`429`), and `transient` (`5xx`, timeouts, connection errors).
   Persist `failure_class` alongside the existing `status_code` in the error
   log, and only set `treated_as_source_unavailable: True` for
   `permanent_no_data`.
2. Restrict `unavailable_dates()` (and therefore `missing_dates`,
   `missing_ranges`, and `history_coverage.source_unavailable_days`) to
   `permanent_no_data` rows so auth, rate-limited, and transient failures are
   re-attempted on the next backfill instead of being skipped forever. Keep
   backward compatibility for legacy error-log rows that have no `failure_class`
   by treating an un-typed historical `400`/`404` as `permanent_no_data` and any
   other un-typed status as recoverable.
3. Emit a typed runtime/source-status state `settlement_source_auth_failure`
   distinct from item 213's `expected_current_day_unavailable`, and raise a
   fail-closed P0 settlement-source data-layer blocker when the canonical
   settlement source returns auth failures across two or more markets in the
   same window (likely a rotated/revoked key) so collection does not appear
   healthy while settlement truth is broken fleet-wide.
4. Add a rescan/repair command (for example `wu_history recover-unavailable`)
   that re-reads the per-station error log, clears non-`permanent_no_data`
   unavailable entries, and reports the historical date ranges made re-fetchable,
   so previously poisoned coverage can be recovered without deleting raw data.
5. Surface auth/rate-limited/transient settlement-source failures separately
   from expected current-day degradation in `weather.collection.collection_health`,
   `weather.reporting.data_layer_audit`, and `weather.reporting.fleet_observability`,
   and document legacy paid-provider access as disabled project policy with the
   recovery command in the settlement runbook.

- [x] Add `failure_class` typing to `write_fetch_error` and gate
  `treated_as_source_unavailable` on `permanent_no_data` only.
- [x] Limit `unavailable_dates()`/`missing_ranges`/`history_coverage` to
  permanent-no-data days, with a safe legacy fallback for un-typed rows.
- [x] Add the `settlement_source_auth_failure` source state and a fail-closed
  multi-market P0 settlement-source blocker in the data-layer/health audits.
- [x] Add a `recover-unavailable` rescan/repair command that clears
  non-permanent unavailable entries and reports recovered ranges.
- [x] Add fixtures covering `401`/`403` auth, `429` rate-limit, `5xx`/timeout
  transient, true `400` no-data, and a legacy-poisoned error log that the
  rescan recovers.
- [x] Document disabled legacy paid-provider access and the recovery command in
  the settlement-source operations doc.

Completion note (2026-06-24): `weather.sources.wu_history` now writes
`failure_class`, filters `unavailable_dates()` to permanent no-data rows, and
provides `recover-unavailable`. Live WU auth failures surface as
`settlement_source_auth_failure`; collection health, fleet observability, and
data-layer audit payloads now expose multi-market settlement auth blockers.

Acceptance: a `401`/`403`/`429`/`5xx`/timeout failure on the WU
settlement source during backfill is typed by `failure_class`, is not added to
the permanent `unavailable_dates()` skip set, and is re-attempted on the next
`--skip-existing` backfill and backfill-plan run; auth failures across two or
more markets raise a fail-closed P0 settlement-source data-layer blocker that is
distinct from item 213 expected current-day degradation; and the
`recover-unavailable` rescan recovers historical days previously poisoned by
transient or auth errors, proven by fixtures and a passing focused test run.

Related: items 17, 23, 29, 100, 102, 114, 213, 265.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - FAILURE TYPING, RECOVERY, AND FLEET BLOCKERS LANDED`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

