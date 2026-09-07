# Durable Agent Context

Status: canonical domain-invariant guide.

This project is a research, evidence-collection, model-validation, and
operations platform for Polymarket daily high-temperature markets. It serves
multiple Celsius and Fahrenheit markets and evaluates whether weather-only or
market-aware probability estimates outperform live market prices after proper
settlement scoring.

This file intentionally contains no current performance metrics, worktree
state, model/schema versions, event counts, or backlog priorities. Read the
[generated active backlog](../roadmap/active-backlog.md), code/config, and local
generated reports for dynamic state.

## Settlement and units

- Each market operates end-to-end in its configured native settlement unit.
  Toronto is the canonical Celsius market; the built-in U.S. markets use
  Fahrenheit. Legacy identifiers ending in `_c` may predate this contract and
  must be interpreted through their schema/producer, not their name alone.
- The modeled settlement source is the highest whole-degree value printed by
  the configured Weather Underground history source for the market's local
  target date. Rounding and band parsing use the canonical unit helpers.
- WU history is the settlement proxy and may establish a hard observed floor.
  When the WU observation path is empty, the serving contract also promotes
  the effective observed high already admitted by feature extraction: a
  target-date, cutoff-aligned current station observation or its captured
  max-since-07:00 summary. This exception never admits forecast, climatology,
  post-cutoff, unit-implausible, or missing evidence.
- A supporting observation can lead or disagree with the WU print. Model that
  uncertainty; outside the explicit empty-WU rescue contract, do not silently
  turn a non-resolution source into a hard floor.
- Intraday features align to the effective WU printed cutoff. Wall-clock time
  can advance before WU history prints a row. Any station rescue used as a
  floor must be captured by the build and must not use an observation after
  the model-emission time.

Paid weather-provider access is unsupported. Do not add credentials, required
environment variables, operator commands, or roadmap dependencies for paid
weather data. WU labels come from retained local artifacts, the public
page-backed collector, or an explicit reviewed manual-override policy.

## Evidence and model claims

The north-star claim is not “the forecast looks reasonable.” Evidence should
compare model probabilities with captured market yes-prices and realized
settlement using proper scoring such as Brier score/log loss, calibration,
protected slices, and after-cost trading evidence where applicable.

- Frozen-tape or captured-input replay is preferred over reconstructing inputs
  from current code or future data.
- Snapshot coverage and settlement-label quality determine whether a market-day
  is countable. Partial, stale, reconstructed, or release-unbound rows must not
  be silently upgraded.
- The admission bar is `promotion_countable`, not `quality_grade == "complete"`.
  The settlement authority is `data/settlements/<market>/ledger.jsonl`, not
  `market_day_labels.csv`; the CSV is a projection and can disagree.
- Uncertainty on any model-versus-market claim uses crossed date x market
  clustering. Exchangeable market-day resampling produces intervals that are too
  narrow and has already retracted published results. Report the effective date
  and market cluster counts with every estimate, and say explicitly when a delta
  is not distinguishable from zero.
- Artifact regime boundaries are provenance, not target-date age. Do not pool
  evidence across them.
- Market-informed features require leakage-safe evaluation. Keep weather-only
  and market-aware claims distinguishable.
- Training feature extraction and live feature extraction must change together.
  Update schemas, regenerate candidates, and prove train/serve parity.
- Calibration can reduce probability error; it does not manufacture predictive
  edge. Always retain a market benchmark.
- Candidate existence is not promotion. Promotion and production-readiness
  gates must fail closed when evidence is missing, stale, inconsistent, or
  bound to a different release.

## Runtime and storage

- Canonical source is the installed `src/weather` package and canonical CLIs
  use `python -m weather...`.
- Repository-owned default paths come from `weather.paths`; normal runtime code
  must not depend on the process working directory.
- All `data/` content is ignored local state. Tapes, ledgers, raw payloads,
  status files, and reports can be operationally durable without being tracked
  by Git. A clean checkout has none of them.
- Snapshot, forecast, CLOB, settlement, maker, and taker evidence is append-only
  or explicitly migrated. Cleanup requires the storage/retention contracts and
  a reviewed exact-path manifest.
- Durable qualified model state belongs under `artifacts/`; mutable candidate
  training output belongs under ignored `artifacts/candidates/`; small
  deterministic test inputs belong under `tests/fixtures/`.
- Long-running collectors use single-writer locks, atomic status updates,
  bounded child processes, and runtime identity. Restart affected processes
  after code, target-date, registry, or serving-pointer changes.

See [path policy](path-policy.md),
[data storage classes](data-storage-class-contract.md),
[retention policy](data-retention-policy.md), and
[artifact policy](artifact-storage-policy.md).

## Release and execution safety

- The trading product uses International Polymarket (`polymarket_global`) only.
  Polymarket US implementation, tests, and historical records may remain for
  compatibility, but must not be selected for a new probe, credential setup,
  live-readiness decision, or exchange mutation.
- A configured active release must bind the complete verified release graph.
  Missing, mismatched, or corrupt components block serving; do not fall back to
  ambient global artifacts.
- Candidate construction is inactive. Promotion and rollback are reviewed,
  boundary-aware operations; long-running processes must reload/restart after a
  pointer change.
- Ordinary development stays in research, shadow, dry-run, read-only, or paper
  modes. Live exchange actions require explicit user authorization plus current
  readiness, credentials-by-reference, risk, evidence, and release gates.
- Background capture is more valuable than opportunistic heavy work on the
  dedicated host. Follow the host-load and operations topology policies before
  running backfills, corpus builds, replays, or training.

## Gate design and operating rules

Challenge inherited operating rules before imposing their cost on the operator.
Identify the concrete failure each rule prevents, its authority or evidence,
and whether the consuming stage already checks that risk directly. Keep rules
with a justified purpose; remove redundant ceremony or replace unsupported
proxies with checks of the actual condition. Record the reasoning in the owning
contract and test the failure boundary. This applies to procedural rules as
well as numeric thresholds; familiarity alone is not a justification.

For the bounded attended International Stage 0/1 sequence, the operator's
invocation of the reviewed local command carries authorization and the stated
eligibility/no-circumvention attestation. Do not add repeated confirmation
prompts. Follow the [owning authorization contract](INTERNATIONAL_MM_LIVE_PILOT.md#reviewed-command-authorization)
for scope, attendance and the independent runtime gates.

A gate must protect the stage that consumes it. Do not make a read-only or
no-order stage depend on a later stage's profitability, quote-quality, or
research heuristic merely because one artifact is convenient to reuse.

Every numeric hard block must identify, in its owning code or canonical
contract:

- its owner and exact stage;
- whether it is a protocol/operational safety invariant, a current external
  rule, an explicit owner-approved risk envelope, or an experimental
  heuristic;
- the source and date, rationale, supporting evidence, units, and boundary
  semantics; and
- the failure consequence plus the condition that triggers remeasurement or
  review.

Protocol/operational safety invariants and current external rules fail closed
within their documented scope. External limits must come from current bound
evidence rather than a copied constant when the venue can change them. An
owner-approved loss, exposure, or resource envelope may also fail closed, but
must be described as a chosen risk bound rather than an empirical optimum and
must identify what new authority or evidence permits review. An experimental
heuristic without measured support is a preference, ranking feature, warning,
or explicit experiment parameter—not an immutable hard block. It must not be
described as "optimal" or "safe," and it must not block an unrelated stage.

When an unexplained threshold blocks work, first trace its history and causal
path, then state why it exists and the risks of tightening, relaxing, or
removing it. Do not mechanically raise the value to make a run pass; decouple
the stages or replace the heuristic with a measured decision rule. Preserve
the underlying safety controls while that work is reviewed.

## Architectural routing

- `weather.sources`: provider adapters and source history.
- `weather.model`: serving assembly, features, distributions, and calibration
  application. `TorontoHighTempModel` is a historical name for a multi-market
  implementation.
- `weather.calibration`: training, candidate replay, and artifact construction.
- `weather.market`: registry, exchange data, settlement labels, and trading
  policy/evidence.
- `weather.collection`: capture, persistence, archive, and collection health.
- `weather.backtesting`: settlement IO, tape scoring, and replay evaluation.
- `weather.reporting`: audits, scorecards, promotion, and serving gates.
- `weather.operations`: supervision, scheduled pipelines, host safety, and
  release lifecycle.

The detailed owner/import contract is
[package-boundaries.md](package-boundaries.md); large facade ownership is in
[module-ownership-map.md](module-ownership-map.md); the end-to-end flow is in
[architecture.md](../architecture.md).

## Development expectations

- Preserve settlement hierarchy, native units, cutoff alignment, schema
  provenance, probability mass, and fail-closed gates.
- Add focused deterministic tests in the matching owner directory. Tests use
  temporary local data layouts and never assume the developer's `data/` tree.
- For model changes, include replay/backtest evidence appropriate to the claim,
  not only model-only validation.
- For operational changes, verify status/dry-run paths, output contracts,
  process restart behavior, and Windows scheduled-worker constraints.
- Keep dated evidence historical. Put changing work status in roadmap items and
  regenerate the active backlog.

Use [development.md](../development.md) for the verification matrix and
[the root agent instructions](../../AGENTS.md) for task workflow.

## Update this file when

Update when durable domain, settlement, unit, evidence, storage, release, or
execution-safety invariants change. Do not add transient audit results, current
metrics, model/schema version strings, local worktree notes, or priorities.
