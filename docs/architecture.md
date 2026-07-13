# Architecture

Status: canonical durable guide.

The platform collects weather and market evidence for daily high-temperature
markets, produces native-unit probability distributions, compares them with
market prices and settlement outcomes, and promotes only artifacts that pass
the evidence and release gates.

## Owner boundaries

| Owner | Responsibility |
| --- | --- |
| `app/` | Thin Streamlit routing and presentation views |
| `weather.sources` | Provider fetch/parsing, historical stores, source schemas |
| `weather.model` | Serving-time source assembly, features, distributions, calibration application |
| `weather.calibration` | Training, candidate replay/scoring, calibration, artifact production |
| `weather.market` | Market registry, Polymarket/CLOB access, settlement labeling, maker/taker policy |
| `weather.collection` | Snapshot/forecast capture, persistence, health, and backfill |
| `weather.backtesting` | Settlement ledger IO, frozen-tape scoring, replay, evaluation |
| `weather.reporting` | Audits, reports, scorecards, promotion and serving gates |
| `weather.operations` | Supervisors, scheduled pipelines, releases, and operational audits |
| Shared `weather.*` modules | Paths, units, IO, schemas, artifacts, scoring, identity, and release contracts |

[Package boundaries](operations/package-boundaries.md) are the detailed
dependency contract. [The module ownership map](operations/module-ownership-map.md)
identifies large compatibility facades and their extraction owners.

## Data and decision flow

```text
market registry + location/event config
  -> Polymarket event and weather/source adapters
  -> TorontoHighTempModel (legacy name; multi-market implementation)
  -> SourceBundle -> DistributionResult -> ModelBuildResult
  -> SnapshotStore local append-only tapes
  -> settlement ledger and market-day finalization
  -> frozen-tape backtest and captured-input replay
  -> reporting, promotion, and production-readiness gates
  -> candidate artifact -> immutable verified release
  -> process-bound serving bundle
```

The CLOB capture loop is intentionally separate from the slower weather/model
snapshot loop. The observation-trigger loop can request recomputation when
low-cost live observations change. See the
[operations topology](operations/OPERATIONS_DESIGN.md).

The paper taker writes `orders_long.csv` and its counterfactual tape by append.
`incremental_state.sqlite3` is a rebuildable intent index and cumulative
checkpoint, not canonical evidence: ordinary ticks use it to materialize only
new rows and the bounded filled-position set, while explicit maintenance
recovery may stream the canonical tapes. Per-tick memory, tape-I/O, duration,
and post-warmup slope diagnostics are advisory observability and do not change
daily-roll liveness classification.

## Sources of truth

- Runtime market behavior: built-in `MarketSpec` values in
  `weather.market.market_registry`, optionally overlaid by the configured
  external registry.
- Broader location/source planning: `config/locations.json`. It is not the same
  set as the built-in live market registry.
- Volatile Gamma event metadata: generated
  `config/location_market_events.json`; refresh it rather than hand-editing it.
- Supervised settlement labels: per-market ledgers under local
  `data/settlements/`; folder settlement files are derived copies.
- Schemas: `weather.schema_registry` and producer/consumer tests.
- Serving state: the verified active-release pointer and complete immutable
  release graph. Candidate artifacts are never active merely because they exist.
- Active work: numbered roadmap items and the generated active backlog.

## Invariants that cross owners

- Markets operate in their native settlement unit. Convert only at explicit
  source or display boundaries; do not infer units from legacy `_c` field names.
- Apply the settlement/source hierarchy defined in
  [Durable Agent Context](operations/AGENT_CONTEXT.md) consistently across
  source, model, label, replay, and reporting owners.
- Intraday features align to the effective WU printed cutoff, not blindly to
  wall-clock time.
- Training extraction and live feature extraction change together. Captured
  input replay is the preferred proof against train/serve skew.
- Snapshot, forecast, order-book, settlement, and trading tapes are local
  evidence. Writes must stay atomic/single-writer and schema changes must remain
  replayable.
- Active serving binds a complete verified release. Do not fall back to global
  artifacts when a release pointer exists but verification fails.
- Public facade names and compatibility shims can remain stable, but new logic
  belongs to the documented owner module and must not import back through its
  facade.

## Update this file when

Update when owner boundaries, the end-to-end data flow, authoritative stores,
release binding, or repository-wide model/evidence invariants change. Update
package edges and facade details in their operations documents instead of
duplicating them here.
