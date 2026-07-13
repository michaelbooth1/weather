# Reporting Guidance

Scope: audits, scorecards, gates, and durable report logic under
`src/weather/reporting/`. Inherits [package-wide guidance](../AGENTS.md).

- Put domain-specific reporting in the existing subpackage: `daily`,
  `data_quality`, `fleet`, `hourly`, `market`, `promotion`, `scorecards`,
  `serving_gates`, `source_gates`, or `validation`. The reporting package root
  is reserved for shared helpers.
- Reporting may read stable domain artifacts and call documented entrypoints;
  it must not become the owner of training, capture, settlement, or operational
  process logic. Prefer stable JSON/schema readers over importing deep
  orchestration internals.
- Compatibility facades such as `promotion.promotion_refresh` keep public
  imports and CLI execution stable. New decisions, readers, rendering, or CLI
  logic belong in their owner modules, which must not import the facade.
- Separate payload assembly from Markdown rendering when a report grows. Keep
  machine-readable output and human-readable output semantically aligned.
- Generated reports normally stay under ignored `data/backtest/`. Commit a
  report under `docs/` only when it is intentionally durable project history;
  do not present dated research findings as current operating state.
- Promotion and serving gates fail closed. Preserve first-blocker ordering,
  exact release/artifact identity, countability rules, and clear next actions.

Run the matching `tests/reporting/` module and the import-architecture ratchet
when moving files or changing cross-package reads. See
[Package Dependency Boundaries](../../../docs/operations/package-boundaries.md)
and [Large Module Ownership Map](../../../docs/operations/module-ownership-map.md).

## Update this file when

Update when reporting subpackage ownership, artifact-reader boundaries, facade
policy, output placement, or fail-closed gate requirements change.
