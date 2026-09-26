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

NBP guidance must satisfy the [target-period and parser-provenance
contract](nbm-target-period-contract.md). Future guidance admission requires
recorded maximum-period provenance; unversioned history remains legacy replay
only. The quarantined shadow crosses an explicit input-regime boundary, with
no fitting, retirement, re-scoring or pooling across that boundary.

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

## Glossary

Terms are shorthand for the linked owner's contract, not additional authority.

| Term | Meaning | Owner |
| --- | --- | --- |
| B / C strata | Separate in-season / out-of-season pre-boundary evaluation panels; never pool them or cross the provenance boundary. | [Findings digest](FINDINGS_DIGEST.md) |
| Mission id | A correspondence sequence label, not a calendar date; reports reuse their handoff's id. | [Roadmap guide](../roadmap/AGENTS.md) |
| Roll-sensitive / roll-free | Whether adopting changed source can restart a capture worker through its loaded import closure; obtain the script's verdict. | [Delegation contract §3](DELEGATION_CONTRACT.md#3-roll-sensitivity--how-to-decide-it) |
| `promotion_countable` | The evidence-admission flag required for promotion counting; a complete quality grade alone is insufficient. | [Evidence and model claims](#evidence-and-model-claims) |
| pUSD | The International venue's dollar-denominated collateral unit; balances and caps retain their explicit unit. | [Live pilot](INTERNATIONAL_MM_LIVE_PILOT.md) |
| T+1 / T+2 | Target market-local settlement dates one / two days after the reference market-local date. | [Reward pre-registration](../research/liquidity-reward-epoch-preregistration-2026-09-20.md) |
| `P_many` / `P_single` | Reward predictions integrated over observed two-sided minutes under the many-maker / single-maker share assumptions. | [Reward pre-registration](../research/liquidity-reward-epoch-preregistration-2026-09-20.md) |
| `k_accrued` | Venue-reported reward accrual divided by `P_many`; accrual is not proof of payment. | [Reward addendum](../research/liquidity-reward-epoch-addendum-2026-09-23.md) |
| EF / RF / HW | Established findings / retracted claims and false leads / how we get things wrong. | [Digest routing](FINDINGS_DIGEST.md) |
| Lease | Exclusive workload admission held through complete child-tree cleanup; not trading authority. | [Host load policy](HOST_LOAD_POLICY.md) |
| Quiet window | The bounded integration window for a roll-sensitive change, subject to the guarded merge checks. | [Delegation contract §3](DELEGATION_CONTRACT.md#3-roll-sensitivity--how-to-decide-it) |
| Attempt / session | A launch attempt can fail before a live session begins; retain and report both counts independently. | [RE-1 findings](ESTABLISHED_FINDINGS.md) |

## Update this file when

Update when durable domain, settlement, unit, evidence, storage, release, or
execution-safety invariants change. Do not add transient audit results, current
metrics, model/schema version strings, local worktree notes, or priorities.
