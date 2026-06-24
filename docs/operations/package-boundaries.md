# Package Dependency Boundaries

Status: live ratchet as of 2026-06-16.

The `weather` package is moving from historical flat modules toward explicit
ownership boundaries. The current rule is a ratchet: every cross-package import
must either use a shared utility package, match a stable package edge, or be
listed as a transitional edge in `tests/operations/test_import_architecture.py`.

## Shared Utilities

These packages are intentionally importable by any owner package:

- `weather.artifacts`
- `weather.io`
- `weather.paths`
- `weather.runtime_identity`
- `weather.schema_registry`
- `weather.scoring`
- `weather.time`
- `weather.units`
- `weather.variant_registry`

New helpers that are reused across package owners should land in one of these
shared modules or in a new small owner module, not in the first CLI or report
module that needed them.

## Owner Layers

- `weather.sources` owns raw provider fetch, parsing, daily summaries, and
  source-specific historical stores.
- `weather.model` owns serving-time model assembly, feature extraction,
  distribution estimation, presentation, and runtime calibration artifact
  application.
- `weather.calibration` owns training, replay-driven calibration, promotion
  candidate scoring, source-state feature transforms for calibration artifacts,
  and artifact writing.
- `weather.market` owns market configuration, market-microstructure capture,
  market-making policy, paper scoring, and exchange-adapter boundaries.
- `weather.backtesting` owns settlement IO, tape scoring, replay, and replay
  evaluation.
- `weather.collection` owns live snapshot capture, snapshot storage, forecast
  archival, and collection health.
- `weather.reporting` owns durable reports, dashboards, promotion summaries,
  and audit rendering.
- `weather.operations` owns orchestration entrypoints, scheduled jobs,
  supervisors, long-job guards, and architecture/ownership audits that are
  operational rather than domain-specific.

## Transitional Edges

These package edges are allowed by the ratchet because they already exist and
have not yet been split into cleaner owner modules:

- `backtesting -> collection`: settlement ledgers still reuse collection
  coverage helpers.
- `backtesting -> operations`: replay backtests still use the long-job guard.
- `backtesting -> reporting`: replay/backtest CLIs still reuse report
  formatting and promotion-corpus helpers.
- `calibration -> operations`: long-running calibration jobs still use the
  operations long-job guard.
- `calibration -> reporting`: calibration still uses report formatting,
  location trust, promotion-corpus, and source-redundancy helpers.
- `collection -> backtesting`: forecast tracking still reuses settlement and
  tape-scoring helpers.
- `market -> backtesting`: market-day labels and paper scoring still reuse
  settlement helpers.
- `market -> collection`: market-microstructure features still locate latest
  collection folders directly.
- `market -> model`: market clients still reuse model-source request helpers.
- `operations -> reporting`: daily refresh still orchestrates reporting modules
  directly.
- `reporting -> calibration`: promotion refresh still imports calibration
  candidate and pooled-model helpers.
- `reporting -> operations`: observability reports still read operational
  status and job-guard helpers directly.

When one of these edges is removed, also remove it from
`TRANSITIONAL_PACKAGE_EDGES` in the architecture test. New transitional edges
must be documented here before they are allowed.

## Transitional Edge Burn-Down

Generate current edge counts with:

```powershell
python -m weather.operations.structure_inventory --report data\backtest\structure_inventory_report.md
```

Current removal routes:

| Edge | Current pressure | Owner route |
| :--- | :--- | :--- |
| `backtesting -> collection` | Low | Move coverage lookup used by settlement/replay into `weather.backtesting` or a shared read-only inventory helper. |
| `backtesting -> operations` | Low | Keep only pure long-job guard helpers in operations; if replay needs them permanently, extract a shared runtime guard module. |
| `backtesting -> reporting` | Medium | Move report formatting/promotion-corpus read helpers used by replay CLIs into shared reporting-neutral helpers. |
| `calibration -> operations` | Low | Extract long-job guard usage behind an owner-neutral runtime utility if more calibration jobs need it. |
| `calibration -> reporting` | Medium | Move formatting, location trust, promotion corpus, and source-redundancy primitives that calibration needs into shared owner modules. |
| `collection -> backtesting` | Low | Move settlement/tape-scoring read contracts used by live collection into shared backtesting-neutral IO helpers. |
| `market -> backtesting` | Medium | Extract settlement label/tape-scoring contracts used by market-day labels and paper scoring into shared settlement IO helpers. |
| `market -> collection` | Medium | Stop locating latest snapshot folders from market features directly; consume a collection inventory/manifest contract instead. |
| `market -> model` | Medium | Move request/source helper reuse out of model serving modules into a shared provider-request utility. |
| `operations -> reporting` | High | Split daily-refresh orchestration from report construction; operations should call reporting entrypoints, not import deep report internals. |
| `reporting -> calibration` | High | Keep calibration-owned scoring/training in calibration and move report-readable candidate result contracts into shared schemas or reporting readers. |
| `reporting -> operations` | Medium | Read operational status artifacts through stable JSON/status contracts instead of importing operations helpers. |

Burn-down rule: remove at least one transitional edge whenever a related large
module is split, and update this table plus `TRANSITIONAL_PACKAGE_EDGES` in
`tests/operations/test_import_architecture.py` in the same change.

## Facades

Large compatibility facades should remain thin. Public module names can keep
re-exporting stable helpers, but new shared logic should move to owner modules
such as `weather.model.calibration_runtime`, `weather.market.mm_exchange_reports`,
`weather.market.mm_paper_reports`, `weather.reporting.data_quality.data_layer_audit_report`,
`weather.operations.supervisor`,
`weather.calibration.pooled_feature_source_state`, or the shared utility modules
above.
