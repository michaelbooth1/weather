# 318. Post-Threshold Large Module Decomposition Refresh [OPEN 2026-06-25 - SEVEN MODULES REMAIN AFTER DAILY REFRESH SLICE]

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
- [ ] Reduce `weather.operations.tape_backup` below the warning threshold.
- [ ] Reduce `weather.reporting.daily.daily_learning` below the warning
  threshold.
- [x] Reduce `weather.operations.daily_refresh_steps` below the warning
  threshold.
- [ ] Reduce `weather.market.mm_paper` below the warning threshold.
- [ ] Reduce or explicitly exempt `weather.schema_registry` with documented
  registry/audit ownership.
- [ ] Reduce `weather.collection.snapshot_store` below the warning threshold.
- [ ] Reduce `weather.market.taker_bot_bakeoff` below the warning threshold.
- [ ] Reduce `weather.reporting.source_family_inventory` below the warning
  threshold.
- [ ] Split matching large test fixtures/builders where needed for the source
  splits.
- [ ] Rerun module-size audit and architecture ratchet after each split batch.

2026-06-25 daily-refresh slice: split step order/resume filtering to
`weather.operations.daily_refresh_registry`, settled-day barrier contracts to
`weather.operations.daily_refresh_settled_day`, and execution/status aggregation
to `weather.operations.daily_refresh_status`. `weather.operations.daily_refresh_steps`
is now a step-adapter compatibility surface at 1,994 lines. The regenerated
module-size audit reports `7` warnings; the remaining over-threshold modules
have owner and next-split metadata in both the ownership map and audit notes.

Acceptance: `python -m weather.operations.module_size_audit --out data\backtest\module_size_audit.json --report data\backtest\module_size_audit_report.md`
reports zero warnings, or any remaining over-threshold module has an explicit
documented exception with owner, reason, and next review date; focused owner
tests and `tests/operations/test_import_architecture.py` pass after each split
batch.

Related: items 90, 98, 130, 173, 205, 270, 99, 176.
