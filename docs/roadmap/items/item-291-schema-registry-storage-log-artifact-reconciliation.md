# 291. Schema Registry Reconciliation For Storage And Log Artifacts [COMPLETE 2026-06-24 - STRICT AUDIT CLEAN WITH EXPLICIT NON-SCHEMA EXCLUSIONS]

Goal: register or intentionally exclude every durable storage/log artifact
schema-like version so schema drift is visible and intentional, not discovered
only during audits.

Source: the 2026-06-23 data-layer audit ran `weather.schema_registry audit
--paths src --strict` and found 47 unregistered schema-like versions. Several
are durable storage or log artifacts, including snapshot explanation/backfill
schemas, CLOB order-book tiering, daily progress/refresh disk artifacts,
market-making/taker policy and bakeoff artifacts, and storage/retention repair
outputs. Some strings are strategy IDs or policy IDs rather than artifact
schemas, but the registry has no explicit allowlist to distinguish those from
missed durable schemas.

Why this matters: the project is adding many long-lived JSON/JSONL/CSV/Parquet
artifacts. If schema versions are not registered or intentionally classified as
non-artifact IDs, readers cannot reliably migrate them, retention tooling cannot
tell which files are safe to rebuild, and future audits produce noisy failures
that hide real drift. A clean schema registry is part of making the data layer
durable without becoming brittle.

## Design

1. Review every current unregistered schema-like literal and classify it as one
   of: durable artifact schema to register, transient/internal report schema to
   register, policy/strategy identifier to exclude, or legacy/deprecated schema
   to record as legacy.
2. Add registry entries for durable storage and log artifacts, including owner,
   status, supersedes/migration notes where applicable, and description.
3. Add a code-backed exclusion mechanism for non-schema identifiers such as
   strategy IDs, sizing policy IDs, and pricing model IDs so strict audits can
   remain useful without forcing every identifier into the schema registry.
4. Update producers that hard-code schema strings to use `schema_version(...)`
   where they are public artifacts, preserving compatibility for existing
   files.
5. Wire strict schema-registry audit into the roadmap/data-layer validation
   path for storage-owned packages after the current 47 items are resolved.

- [x] Produce a reviewed classification table for the 47 currently
  unregistered schema-like versions.
- [x] Register durable storage/log/report schemas with owners, status, and
  migration notes.
- [x] Add an explicit exclusion/allowlist for non-schema policy and strategy
  identifiers.
- [x] Replace hard-coded durable artifact schema strings with registry lookups
  where appropriate.
- [x] Add tests proving strict schema audit passes for storage/log packages and
  still catches a new unregistered durable schema.

Acceptance: `python -m weather.schema_registry audit --paths src --strict`
passes or reports only explicitly allowed non-schema identifiers; every durable
storage/log artifact has a registered owner and migration status; and adding a
new unregistered durable artifact schema fails a focused schema-registry test.

## Completion Notes

Completed on 2026-06-24. The authoritative source audit found 50 schema-like
literals, not the 47 in the original item snapshot. Forty-five durable storage,
log, report, sidecar, repair, or verification artifacts are now registered in
`weather.schema_registry` with owners and active status. The five remaining
literals are code-backed exclusions for non-serialized policy/model identifiers:
`flat_notional_v1`, `maker_default_v0`, `polymarket_symmetric_price_v1`,
`top_of_book_only_v1`, and `top_of_book_plus_1pct_depth_v1`.

Producers for public storage/log artifacts now use `schema_version(...)` for
the newly registered registry entries where appropriate, including retention
cleanup, CLOB order-book tiering, daily progress/freshness reports, daily
refresh preflight/repair reports, runtime identity evidence, snapshot
evaluation, taker edge permission maps, and trading evidence summaries.

Reviewed classification table:
`docs/operations/schema-registry-storage-log-reconciliation.md`.

Validation:

- `python -m weather.schema_registry audit --paths src --strict`:
  `registered=343 discovered=567 unregistered_versions=0 excluded_versions=5`
- `python -m pytest tests/operations/test_schema_registry.py tests/operations/test_clob_order_book_tiering.py tests/operations/test_daily_refresh.py tests/reporting/test_backtest_artifact_retention.py tests/reporting/test_daily_progress_ledger.py tests/reporting/test_runtime_identity_evidence.py tests/reporting/test_snapshot_evaluation.py tests/reporting/test_trading_evidence.py -q`:
  84 passed

Related: items 31, 60, 97, 112, 132, 175, 204, 286, 287.
