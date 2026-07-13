# Market and Trading Instructions

These instructions apply under `weather.market`. Inherit
[package guidance](../AGENTS.md).

- `market_registry.py` owns built-in runtime market specs; all markets use their
  native settlement unit. Coordinate registry changes with config, README,
  source/model coverage, and both C/F tests.
- Apply the settlement hierarchy in
  [Durable Agent Context](../../../docs/operations/AGENT_CONTEXT.md).
  Settlement ledgers are authoritative local labels; folder settlement files
  and reports are derived views.
- Keep fast CLOB capture separate from slower weather/model capture. Preserve
  token mapping, raw/summary tape lineage, freshness, and audit fail-closed
  behavior.
- Maker/taker policy, paper fills, scoring, and live exchange adapters must stay
  distinguishable. Ordinary tests and development use fixtures, read-only,
  shadow, or paper modes.
- Do not add direct secrets to config, logs, docs, or process arguments. Live
  actions require explicit user authorization plus existing readiness, release,
  credential-reference, risk, and confirmation gates.

Run matching `tests/market` tests and operations/reporting gate tests for shared
evidence contracts. See [Durable Agent Context](../../../docs/operations/AGENT_CONTEXT.md).

## Update this file when

Update when registry/settlement ownership, CLOB capture boundaries, trading
mode safety, credential handling, or market verification changes.
