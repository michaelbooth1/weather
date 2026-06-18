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
- `weather.schema_registry`
- `weather.scoring`
- `weather.time`
- `weather.units`

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
  candidate scoring, and artifact writing.
- `weather.market` owns market configuration, market-microstructure capture,
  market-making policy, paper scoring, and exchange-adapter boundaries.
- `weather.backtesting` owns settlement IO, tape scoring, replay, and replay
  evaluation.
- `weather.collection` owns live snapshot capture, snapshot storage, forecast
  archival, and collection health.
- `weather.reporting` owns durable reports, dashboards, promotion summaries,
  and audit rendering.
- `weather.operations` owns orchestration entrypoints, scheduled jobs,
  supervisors, runtime identity, and long-job guards.

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
- `sources -> model`: forecast-history sources still reuse model feature-store
  and request helper code.

When one of these edges is removed, also remove it from
`TRANSITIONAL_PACKAGE_EDGES` in the architecture test. New transitional edges
must be documented here before they are allowed.

## Facades

Large compatibility facades should remain thin. Public module names can keep
re-exporting stable helpers, but new shared logic should move to owner modules
such as `weather.model.calibration_runtime`, `weather.market.mm_exchange_reports`,
`weather.market.mm_paper_reports`, `weather.reporting.data_layer_audit_report`,
`weather.operations.supervisor`, or the shared utility modules above.
