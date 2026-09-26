# Architecture

Status: canonical durable guide.

- **Owns:** which package owns which responsibility, the end-to-end data flow, the authoritative store for each
  kind of fact, and invariants that cross owners.
- **Read when:** deciding where new code belongs, or tracing a value from capture to settlement to release.
- **Do not use for:** allowed import edges ([package boundaries](operations/package-boundaries.md)), facade split
  status ([module ownership map](operations/module-ownership-map.md)), scheduled tasks
  ([operations design](operations/OPERATIONS_DESIGN.md)), or anything about today
  ([STATE_OF_PLAY](operations/STATE_OF_PLAY.md)).
- **Verify with:** `ls src/weather/` for the owner packages; `PACKAGE_ROOTS`, `SHARED_PACKAGE_ROOTS` and
  `ALLOWED_PACKAGE_EDGES` in `tests/operations/test_import_architecture.py` for the enforced layering.

The platform collects weather and market evidence for daily high-temperature
markets, produces native-unit probability distributions, compares them with
market prices and settlement outcomes, and promotes only artifacts that pass
the evidence and release gates.

## Owner boundaries

| Owner | Responsibility |
| --- | --- |
| `app/` | Thin Streamlit routing and presentation views |
| `maker_core` | Domain-neutral plugin contracts, pure quote proposals and hash-chained offline evidence; [contract](operations/maker-core-contracts.md) |
| `weather.sources` | Provider fetch/parsing, historical stores, source schemas |
| `weather.model` | Serving-time source assembly, features, distributions, calibration application |
| `weather.calibration` | Training, candidate replay/scoring, calibration, artifact production |
| `weather.market` | Market registry, Polymarket/CLOB access, settlement labeling, maker/taker policy |
| `weather.collection` | Snapshot/forecast capture, persistence, health, and backfill |
| `weather.backtesting` | Settlement ledger IO, frozen-tape scoring, replay, evaluation |
| `weather.reporting` | Audits, reports, scorecards, promotion and serving gates |
| `weather.operations` | Supervisors, scheduled pipelines, releases, and operational audits |
| Shared `weather.*` modules | Paths, units, IO, schemas, artifacts, scoring, identity, and release contracts |

The shared row covers two different things. Ten roots are declared importable by every owner
(`SHARED_PACKAGE_ROOTS`; `weather.scoring` is a package, the rest are flat modules). The remaining flat modules
directly under `src/weather/` (release, point-in-time, experiment, execution-host and payload contracts) are not
classified by the import ratchet at all: neither imports of them nor imports made by them are checked. Some already
import owner packages (`weather.residual_distribution_release` imports calibration, model, operations and
reporting; the shared `weather.variant_registry` re-exports `weather.reporting.candidate_lifecycle.variant_registry`),
so an import of a root module can carry an owner-package dependency the ratchet does not see. Check with
`git grep -nE "^\s*(from|import) weather\.(backtesting|calibration|collection|market|model|operations|reporting|sources)" -- ":(glob)src/weather/*.py"`
and do not add new ones.

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

The Streamlit Operator Control Room is a read-only projection of persisted
reporting and operations evidence. `weather.reporting.market.operator_control_room`
owns its exact-target-date reduction and fail-closed `HOLD` decision; the
`app/views/control_room.py` view only renders that result. Even a complete
software pass stops at `READY FOR EXPLICIT APPROVAL`. The dashboard does not
grant trading authority or expose order, cancel, credential, promotion, or
risk-setting actions. The frontend intentionally contains only this Control
Room and the active Roadmap; retired market, history, overview, and operations
views are not hidden routes or retained application code.

The taker track is paused by owner decision (maker focus); read
[STATE_OF_PLAY](operations/STATE_OF_PLAY.md) for whether it is running. Its storage contract still binds the code
and the evidence already on disk. The paper taker writes `orders_long.csv` and its counterfactual tape by append.
Real order evidence is permanent. Counterfactual replay detail has a specific
date-bounded policy: daily-roll startup removes only hash-bound allowlisted raw
and settled detail CSVs after both their target date and mtime exceed the
configured retention, without waiting for settlement. Compact P&L, strategy,
report, plan, and apply receipts remain.
`incremental_state.sqlite3` is a rebuildable intent index and cumulative
checkpoint, not canonical evidence: ordinary ticks use it to materialize only
new rows and the bounded filled-position set, while explicit maintenance
recovery may stream the canonical tapes. Per-tick memory, tape-I/O, duration,
and post-warmup slope diagnostics are advisory observability and do not change
daily-roll liveness classification.

## Sources of truth

- Runtime market behavior: built-in `MarketSpec` values in
  `weather.market.market_registry`, optionally overlaid by the configured
  external registry. ID lookup defaults only for an absent (`None`) ID;
  explicit unknown, blank, padded or non-string IDs are errors. Market configs
  retain the resolved ID alongside its native unit, local-date timezone and
  canonical event slug. An explicit event slug must identify one registered
  market/date; conflicting slug fields and capture identity overrides fail
  before token rows are built. Absent-event date fallback remains available
  to legacy config callers; it does not repair an explicit invalid slug.
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
