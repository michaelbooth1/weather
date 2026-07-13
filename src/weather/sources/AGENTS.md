# Source Adapter Instructions

These instructions apply under `weather.sources`. Inherit
[package guidance](../AGENTS.md).

- Preserve source provenance, timestamps/timezones, native units, parser/schema
  versions, raw-to-normalized lineage, and explicit failure classification.
- Paid weather-provider access is disabled. Do not add credentials or required
  paid-source paths; WU collection uses retained local evidence or the public
  page-backed workflow.
- A source can be expected-unavailable, stale, rate-limited, malformed, or
  missing. Keep those states visible and recoverable; never turn a stale
  last-good cache into fresh evidence.
- Preserve each adapter's source role under the hierarchy in
  [Durable Agent Context](../../../docs/operations/AGENT_CONTEXT.md); adapters
  cannot silently promote supporting data to settlement evidence.
- Unit tests mock network behavior and write temporary stores. Networked
  backfills and refreshes are stateful operator actions, not verification steps.

Run matching `tests/sources` tests and schema/data-quality consumers when a
payload contract changes. See the [history foundation](../../../docs/operations/HISTORY_DATA_DESIGN.md).

## Update this file when

Update when provenance/unit/failure contracts, paid-source policy, WU
collection, caching, or source verification changes.
