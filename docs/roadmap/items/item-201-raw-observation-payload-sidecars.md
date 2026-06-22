# 201. Raw Observation Payload Sidecars [COMPLETE 2026-06-21 - OBSERVATION RAW PAYLOADS HAVE DURABLE SIDECARS]

Goal: capture raw observation payload sidecars for live observation sources,
matching the forecast raw-payload retention pattern.

Source: the June 21 log audit found raw forecast payload manifests are present
for current folders, but replay inputs intentionally strip raw payloads and the
same raw/hash/path/bytes metadata is not captured for WU history/current, METAR,
ECCC SWOB, and similar observation feeds.

Why this matters: several high-value model gaps are observation-driven:
`wu_lag_catchup_miss`, stale-source cases, current-max anomalies, and startup
live-observation null/unit failures. Persisted normalized values are enough to
score the miss, but raw provider payloads are needed to determine whether the
cause was provider lag, parser behavior, source revision, unit normalization,
or cache fallback.

## Design

1. Extend snapshot persistence with `observation_payloads_long.csv`,
   `observation_payloads.jsonl`, and raw payload files under
   `observation_payloads/`.
2. Capture source, source family, provider timestamps, fetch time, status,
   stale/cache state, payload hash, payload bytes, row count, source URL, and
   raw payload path.
3. Include WU history/current, METAR, ECCC SWOB, and other settlement-relevant
   observation feeds when a raw payload exists.
4. Add privacy/storage guardrails: hashes and manifests are required; raw body
   retention may be tiered by source and age.
5. Wire observation payload coverage into data-layer audit and daily learning.

- [x] Add observation raw payload sidecar writers.
- [x] Update source adapters to expose raw payloads where available.
- [x] Add storage-budget accounting and retention policy hooks.
- [x] Add provider/parser autopsy sections for WU lag and current-max anomalies.
- [x] Backfill manifests where raw payloads can be reconstructed from existing
  local source caches.

Acceptance: any future `wu_lag_catchup_miss`, stale observation, or current-max
anomaly case has the raw provider payload evidence needed to classify provider
lag versus parser/cache/model behavior.

Completion note 2026-06-21: `SnapshotStore` now writes
`observation_payloads_long.csv`, `observation_payloads.jsonl`, and raw files
under `observation_payloads/` for observation sources such as WU
history/current, METAR, and ECCC SWOB when their source payload exposes
`raw_payload`. Rows include source family, fetch/cache state, provider observed
time/station/update fields, payload hash, byte count, row count, URL, and raw
path. `python -m weather.collection.snapshot_store backfill-observation-payloads
<folder>` idempotently promotes observation-source rows from legacy
`forecast_payloads_long.csv` manifests. The data-layer audit inventories
`observation_payloads`, recommends missing observation payload sidecars, and the
snapshot tests prove raw payloads are retained while replay inputs stay stripped.
