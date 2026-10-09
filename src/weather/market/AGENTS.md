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
- `reward_quote` owns pure reward-aware quote proposals; `mm_live_envelope`
  owns immutable profile definitions. Neither creates an exchange capability.
  Profile integration follows the [pilot runbook](../../../docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md#stage-2-one-band-maker-quote)
  and must preserve all Stage 1 controls and numeric ratchets.
- `mm_stage2_hold` owns the bounded two-capability controller and chained
  prediction journal; `mm_stage2_selection` owns frozen public ranking;
  `mm_stage2_rewards` separates accrual from paid evidence. The closed
  `mm_stage2_rehearsal` exchange never grants live authority. Sealed live wiring
  and terminal market-evidence validation belong to `mm_stage2_entrypoint`,
  with exact two-token stream evidence.
- Do not add direct secrets to config, logs, docs, or process arguments. Live
  actions require explicit user authorization plus existing readiness, release,
  credential-reference, risk, and confirmation gates.
- The portable live SDK bundle is public substrate only. Keep its export/import
  separate from credential transfer, preserve current-user-only runtime
  activation, and retain exact host/principal-bound installation provenance on
  each execution PC. Normal retries use the vault and current signer/account
  authentication checks; independent backup comparison is an explicit setup or
  recovery operation, not an expiring session prerequisite. See the
  [credential lifecycle contract](../../../docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md#credential-provisioning-and-fresh-comparison).

Run matching `tests/market` tests and operations/reporting gate tests for shared
evidence contracts. See [Durable Agent Context](../../../docs/operations/AGENT_CONTEXT.md).

## Update this file when

Update when registry/settlement ownership, CLOB capture boundaries, trading
mode safety, credential handling, or market verification changes.
