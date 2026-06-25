# 318. Post-Threshold Large Module Decomposition Refresh [COMPLETE 2026-06-25 - MODULE-SIZE WARNING SET CLEARED]

Goal: bring the module-size audit back under the 2,000-line warning threshold
with owner-scoped splits, updated ownership docs, and matching test fixture
extraction where needed.

Source: 2026-06-25 Python structure refactor audit. The current
`python -m weather.operations.module_size_audit` run reports eight warnings:
`weather.operations.tape_backup` (3,741 lines),
`weather.reporting.daily.daily_learning` (3,078),
`weather.operations.daily_refresh_steps` (2,827),
`weather.market.mm_paper` (2,475), `weather.schema_registry` (2,200),
`weather.collection.snapshot_store` (2,164),
`weather.market.taker_bot_bakeoff` (2,162), and
`weather.reporting.source_family_inventory` (2,038). Prior decomposition items
90, 98, 130, 173, and 205 are complete and do not own this refreshed warning
set.

Why this matters: the repo intentionally uses a module-size ratchet because
large operational, market, reporting, collection, and shared-registry modules
mix too many responsibilities and make package-boundary burn-down harder. The
largest tests mirror the same pressure: `test_taker_bot.py`,
`test_daily_refresh.py`, `test_daily_learning.py`, and
`test_pooled_candidate_replay.py` all exceed 2,000 lines. Without a new owner,
the warning threshold becomes advisory noise instead of an active maintenance
gate.

## Design

1. Update `docs/operations/module-ownership-map.md` with current warning
   modules, a concrete owner, and a next split target for each warning.
2. Split modules by existing owner boundaries and stable public surfaces:
   - `tape_backup`: separate manifest/status, retention/pruning, restore drill,
     and CLI orchestration.
   - `daily_learning`: separate readers, synthesis/decision model, report
     rendering, and CLI wiring inside `weather.reporting.daily`.
   - `daily_refresh_steps`: split step registry, adapters, status aggregation,
     and daily-refresh report contracts without importing the facade.
   - `mm_paper`: separate tape ingestion, accounting/scoring, report rendering,
     evidence export, and CLI orchestration.
   - `schema_registry`: separate registry data, audit/check logic, and CLI
     rendering without weakening schema ownership.
   - `snapshot_store`: separate schema constants, readers, writers, sidecar
     backfill/migration helpers, and repair CLI behavior.
   - `taker_bot_bakeoff`: separate artifact readers, scoring, profitability
     verification, report rendering, and CLI.
   - `source_family_inventory`: separate input readers, family/gate
     classification, report rendering, and CLI.
3. Keep compatibility facades and public CLIs stable unless an existing
   roadmap item explicitly authorizes removing them.
4. Remove package-boundary transitional edges opportunistically when a split
   naturally creates owner-neutral contracts; do not perform a broad import
   rewrite as part of this item.
5. Split oversized tests only with their production owner changes, extracting
   reusable fixtures/builders when they make the source split reviewable.

- [x] Refresh `docs/operations/module-ownership-map.md` with the eight current
  warnings and planned splits.
- [x] Reduce `weather.operations.tape_backup` below the warning threshold.
- [x] Reduce `weather.reporting.daily.daily_learning` below the warning
  threshold.
- [x] Reduce `weather.operations.daily_refresh_steps` below the warning
  threshold.
- [x] Reduce `weather.market.mm_paper` below the warning threshold.
- [x] Reduce or explicitly exempt `weather.schema_registry` with documented
  registry/audit ownership.
- [x] Reduce `weather.collection.snapshot_store` below the warning threshold.
- [x] Reduce `weather.market.taker_bot_bakeoff` below the warning threshold.
- [x] Reduce `weather.reporting.source_family_inventory` below the warning
  threshold.
- [x] Split matching large test fixtures/builders where needed for the source
  splits.
- [x] Rerun module-size audit and architecture ratchet after each split batch.

2026-06-25 daily-refresh slice: split step order/resume filtering to
`weather.operations.daily_refresh_registry`, settled-day barrier contracts to
`weather.operations.daily_refresh_settled_day`, and execution/status aggregation
to `weather.operations.daily_refresh_status`. `weather.operations.daily_refresh_steps`
is now a step-adapter compatibility surface at 1,994 lines. The regenerated
module-size audit reports `7` warnings; the remaining over-threshold modules
have owner and next-split metadata in both the ownership map and audit notes.

2026-06-25 source-family slice: split Markdown rendering to
`weather.reporting.source_family_inventory_report` while keeping
`weather.reporting.source_family_inventory.write_report` as a compatibility
export. `weather.reporting.source_family_inventory` is now 1,826 lines. The
regenerated module-size audit reports `6` warnings; the remaining
over-threshold modules keep owner and next-split metadata in both the ownership
map and audit notes.

2026-06-25 snapshot-store slice: split sidecar/cadence backfill helpers and
snapshot-store utility CLI wiring to `weather.collection.snapshot_store_backfill`
while keeping `weather.collection.snapshot_store` compatibility exports stable.
`weather.collection.snapshot_store` is now 1,972 lines. The regenerated
module-size audit reports `5` warnings; the remaining over-threshold modules
keep owner and next-split metadata in both the ownership map and audit notes.

2026-06-25 taker-bakeoff slice: split replay input normalization, current
replay profitability verification, and model-variant row expansion to
`weather.market.taker_bot_bakeoff_scoring` while keeping
`weather.market.taker_bot_bakeoff` compatibility exports stable.
`weather.market.taker_bot_bakeoff` is now 1,861 lines. The regenerated
module-size audit reports `4` warnings; the remaining over-threshold modules
keep owner and next-split metadata in both the ownership map and audit notes.

2026-06-25 schema-registry slice: split static schema registry records to
`weather.schema_registry_data`, recent runtime/snapshot/taker records to
`weather.schema_registry_recent_data`, and registry dataclasses to
`weather.schema_registry_types` while keeping `weather.schema_registry`
compatibility exports stable. `weather.schema_registry` is now 181 lines and
the largest registry data shard is 1,946 lines. The regenerated module-size
audit reports `3` warnings; the remaining over-threshold modules keep owner
and next-split metadata in both the ownership map and audit notes.

2026-06-25 mm-paper slice: split active-day freshness, tape readers,
conservative fill accounting, queue companion scoring, and P&L summaries to
`weather.market.mm_paper_scoring` while keeping `weather.market.mm_paper`
compatibility exports stable. `weather.market.mm_paper` is now 1,366 lines and
`weather.market.mm_paper_scoring` is 1,187 lines. The regenerated module-size
audit reports `2` warnings; the remaining over-threshold modules keep owner
and next-split metadata in both the ownership map and audit notes.

2026-06-25 daily-learning slice: split artifact readers, input
freshness/coverage/consistency gates, experiment queue item builders, label
countability, calibration monitoring, and scorecard assembly to
`weather.reporting.daily.daily_learning_scorecard` while keeping
`weather.reporting.daily.daily_learning` compatibility exports stable.
`weather.reporting.daily.daily_learning` is now 1,783 lines and
`weather.reporting.daily.daily_learning_scorecard` is 1,381 lines. The
regenerated module-size audit reports `1` warning; the remaining
over-threshold module keeps owner and next-split metadata in both the ownership
map and audit notes.

2026-06-25 tape-backup slice: split retention policy, manifest building,
capacity checks, validation, restore-drill SLA, backup status, and alerts to
`weather.operations.tape_backup_manifest`; deduplicated repository preflight,
restic command execution, backup/status/restore drill, and dedup job helpers to
`weather.operations.tape_backup_dedup`; and unmanifested cleanup planning,
durable restore proof verification, cleanup apply gates, and cleanup report
rendering to `weather.operations.tape_backup_cleanup`. `weather.operations.tape_backup`
is now 913 lines, `weather.operations.tape_backup_manifest` is 1,138 lines,
`weather.operations.tape_backup_dedup` is 842 lines, and
`weather.operations.tape_backup_cleanup` is 1,038 lines. The regenerated
module-size audit reports `0` warnings.

Acceptance: `python -m weather.operations.module_size_audit --out data\backtest\module_size_audit.json --report data\backtest\module_size_audit_report.md`
reports zero warnings, or any remaining over-threshold module has an explicit
documented exception with owner, reason, and next review date; focused owner
tests and `tests/operations/test_import_architecture.py` pass after each split
batch.

Related: items 90, 98, 130, 173, 205, 270, 99, 176.
