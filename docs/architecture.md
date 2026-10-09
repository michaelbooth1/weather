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
| `weather.market` | Market registry, Polymarket/CLOB access, settlement labeling, live maker adapters and policy |
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

The Streamlit Control Room projects project context, host diagnostics and
persisted trading evidence. `weather.reporting.market.operator_control_room`
owns the general pilot checklist; `operator_evidence`, `operator_session` and
`operator_trading` own bounded observation readers, while
`weather.reporting.roadmap.project_overview` reads the canonical project note
and workstream ledger. `app/monitor_data.py` shares caches across browser
sessions. The host collector runs at most one bounded diagnostic at a time,
independently of fast session refreshes. Views expose no trading, credential,
promotion or risk-setting actions. The portable launcher's action-time gates
remain authoritative. See [the monitor contract](operations/OPERATOR_MONITOR.md)
for freshness, input bounds and accounting semantics. The default page is the Owner
Cockpit: `weather.reporting.market.cockpit_snapshot` reads money, work, health
and exam sources (each optional, with an explicit unavailable reason) and
`app/views/cockpit.py` renders it without controls, failing closed. The
frontend contains the Cockpit, Control Room, Roadmap, and the offline [Reward Simulator](operations/liquidity-reward-simulator.md).
The simulator delegates to the canonical maker calculator, uses hypothetical
inputs, and exposes no account or order actions. Retired page modules remain removed.

The paper taker and the paper maker were retired and their runtime code deleted on
2026-09-29 (110o part 3), except the paper-run tool `weather.market.market_making_run`,
retained only for the International live-pilot Stage 0/1 paper proof. Their run folders under `data/taker_runs` and `data/mm_runs`
remain append-only evidence: real order evidence is permanent, and the taker's
bounded counterfactual detail is governed by the
[storage class contract](operations/data-storage-class-contract.md). The retained
`trading_evidence` report reads them through the read-only
`weather.reporting.market.retired_trading_evidence` module.

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
  Refresh fails if pagination ends on a full final page without proving complete
  discovery. Event and market resolution descriptions retain their exact text
  and UTF-8 SHA-256 plus separate source URLs; those bytes do not establish
  settlement-source equivalence or economic readiness. The metadata envelope
  atomically binds exact registry bytes and event metadata; paired readers,
  candidate freezing and release verification use
  `weather.market.location_config`. The separate registry projection may lag
  after interruption; inventory reports drift. Legacy pairs are explicitly
  unbound, and invalid declared generations fail closed.
  `--metadata-only` preserves original registry bytes. See the
  [configuration generation contract](operations/config-inventory.md#location-configuration-generations).
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
- Station observation rows are keyed on the observation instant
  (`metar-parser-v4` keys AWC rows on `obsTime`, never the nominal
  `reportTime`; [durable domain context](operations/AGENT_CONTEXT.md)). Captured
  v3 rows are not rewritten; `python -m weather.backtesting.metar_keying_replay`
  re-derives both keyings from the retained raw payloads for closed dates up to
  2026-09-29 and reports the per-snapshot difference. It is read-only.
- Training extraction and live feature extraction change together. Captured
  input replay is the preferred proof against train/serve skew.
- Snapshot, forecast, order-book, settlement, and trading tapes are local
  evidence. Writes must stay atomic/single-writer and schema changes must remain
  replayable.
- Active serving binds a complete verified release. Do not fall back to global
  artifacts when a release pointer exists but verification fails.
- Afternoon residual centering is controlled by `component.enabled` in
  `artifacts/misc/afternoon_residual_centering.json` (or the verified release's
  copy). Disabled means the serving stage returns `artifact_disabled` without
  shifting or spreading probabilities. The loader reads it at model construction;
  changing the global artifact requires recreating existing model instances.
  Source fingerprints exclude artifacts, so a source-roll verdict alone does not
  prove activation. Preserve fitted contexts when toggling the switch; never
  refit against this stage's own output. See [the decision and evidence](operations/ESTABLISHED_FINDINGS.md#2-the-cool-bias-is-real-and-is-not-correctable-at-serve).
- The late-day lock-in stages (heuristic, learned, high-has-stood, expanded,
  standing-high partial, late-day continuation) read one anchor built by
  `late_day_lockin_anchor` in `weather.model.model_distribution`
  (`LATE_DAY_LOCKIN_ANCHOR_VERSION`, model `v0.5.11`; the pre-lock-in floor
  of `lockin-anchor-v4` is model `v0.5.12`). With WU printed history
  present it is that history, unchanged. With WU history empty it is the
  observed same-day station high: point-in-time METAR rows keyed by observation
  time (AWC `obsTime`, else the raw `DDHHMMZ` group), never by the nominal
  `reportTime`, so a D-1 23:5x report carried into D as a "00:00" row is
  excluded. It is never higher than `guidance_physical_floor`, which still
  carries that report. Once a late-day stage acts, mass below the anchor
  bucket moves onto it and the calibration floor follows. Before lock-in
  (`lockin-anchor-v4`) the same move applies at the same-day METAR high bucket,
  because the hard floor otherwise reads only the current reading and the max
  since 07:00; SWOB rows keep their hedge until lock-in. Implausible readings
  never anchor. The calibration taper reads the resulting strength.
  `python -m weather.backtesting.lockin_anchor_replay` replays closed dates up
  to 2026-09-29, comparing the old and new anchors. It is read-only and exits 3
  when any row puts more mass below the anchor than before.
- Public facade names and compatibility shims can remain stable, but new logic
  belongs to the documented owner module and must not import back through its
  facade.

## Update this file when

Update when owner boundaries, the end-to-end data flow, authoritative stores,
release binding, or repository-wide model/evidence invariants change. Update
package edges and facade details in their operations documents instead of
duplicating them here.
