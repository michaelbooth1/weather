# Weather Model System

Status: canonical durable guide.

This document answers three questions: what produces a served weather
distribution, what the supported training lanes actually change, and what
evidence is required before a model claim or promotion. It deliberately omits
current scores, artifact versions, and active work status. Read
[established findings](ESTABLISHED_FINDINGS.md) for measured results,
[state of play](STATE_OF_PLAY.md) for current priorities, and the generated
[active backlog](../roadmap/active-backlog.md) for unfinished work.

## Role In The Product

The weather model produces a native-settlement-unit probability distribution.
For the International maker experiment it is a quote-centre and inventory-risk
input. It has not demonstrated an edge over market prices. Market prices may be
used as a benchmark or diagnostic, but never as evidence that a price-free
weather candidate learned independent skill.

Model promotion is separate from proving the bounded maker lifecycle. A live
plumbing test must retain its own permission and risk gates; completing a
retrain does not grant trading authority.

## Served Graph

`TorontoHighTempModel` is a legacy public name for the multi-market serving
implementation. Conceptually, a build follows this graph:

```text
market specification + target date + effective cutoff
  -> point-in-time weather and forecast SourceBundle
  -> live feature extraction
  -> per-market base estimator + target-date prior
  -> ordered distribution transforms and constraints
  -> exact-bin calibration and boundary handling
  -> normalized DistributionResult / ModelBuildResult
```

The exact transform order belongs to `weather.model.model_distribution` and its
recorded pipeline snapshots, not to this prose. The graph includes base/prior
blending, bucket transitions, live-observation signals, support floors,
forecast shaping where eligible, tail controls, intraday residual centering,
current-maximum constraints, continuation/lock-in logic, and final calibration.
These are statistically distinct stages even though serving exposes one final
distribution.

### Input families

| Input family | Serving role | Authority and caveat |
| --- | --- | --- |
| Market specification | Native unit, bands, station, timezone, and contract interpretation | Built-in `MarketSpec` plus reviewed registry overlay |
| WU history/current-day evidence | Settlement-proxy history and effective observed high | Configured Weather Underground history is the settlement proxy; fallbacks are supporting evidence unless the contract says otherwise |
| Station observations | Cutoff-safe current conditions, current maximum, and intraday feature history | Parsed source rows must be available by the effective cutoff; never backfill a live feature with later knowledge |
| Forecast guidance | Forecast high and source-state features | Free sources only; training must use issue-qualified point-in-time rows rather than a stitched best-later value |
| Historical target prior | Target-date-aligned base support | Must be bounded by market/date and use native settlement units |
| Model artifacts | Estimators, calibration, and downstream transform state | A verified release graph is authoritative; a file existing under the global artifact tree does not make it active |
| Market prices | Benchmark, disagreement, quote, and trading policy | Not a weather-model training input and not valid evidence of independent weather skill |

### Two forecast-ensemble contexts

The serving implementation currently constructs forecast summaries in two
different contexts:

- live feature extraction includes the configured Open-Meteo global-model
  payload when building forecast features;
- the distribution-stage forecast context does not pass that payload to the
  same ensemble helper.

This can be intentional only if it remains explicit and tested. The feature
row and the later forecast transform must not be described as the same
consensus. A candidate must either preserve the distinction in its feature and
release contract or unify it with replay evidence.

### Artifact feature semantics

The estimator's stored feature order, not the current extractor schema, decides
which live values an existing artifact consumes. A newer extractor may safely
emit more fields while an older artifact selects a compatible subset, but that
is compatibility rather than adoption of the new information.

Do not infer learned use from a feature name. The currently inspected base
artifact treats forecast-source count primarily as an availability branch and
does not split on forecast disagreement; calling those inputs "forecast
consensus" overstates what the fitted estimator learned. Structural details
and the dated evidence are in
[established findings](ESTABLISHED_FINDINGS.md#8r-core-model-structure-and-lineage-audit--2026-08-15).

## Artifact And Runtime Identity

A countable serving identity must bind all of the following:

1. the release manifest and complete artifact graph;
2. the code and constants actually loaded by the process;
3. the estimator and postprocessor bytes actually deserialized by the process;
4. the feature contract, dependency/runtime contract, and source/cutoff
   semantics used to build the distribution.

Hashing files from disk at snapshot time is insufficient: a long-lived process
may still hold older code or deserialized objects. Hashing raw Python code
objects is also insufficient unless path-bearing fields such as
`code.co_filename` are normalized recursively. Identity schema v0.3 binds the
normalized loaded code, nested behavior constants, loaded artifact state, and
runtime dependency versions; import-time and current-disk hashes are diagnostic
only. Historical v0.1/v0.2 identities are not comparable to v0.3. Never merge
the superseded v0.2 implementation as built. Roadmap item 330 owns adoption and
the remaining model bill of materials.

Historical served replay is impossible when the exact served bytes and inputs
were not retained. In that case, label evidence honestly as a paired comparison
inside one rebuilt environment; do not relabel it as reproduction of historical
production output.

## Training Lanes

### Free point-in-time forecast surface

The training-only Previous Runs contract keeps all 21 schema-known forecast
fields explicit, but the free PIT endpoint has proved complete only for twelve:
surface temperature, total cloud, shortwave/direct/diffuse radiation, wind and
gusts, CAPE, precipitation and its probability, vapour-pressure deficit, and
ET0 evapotranspiration. Cloud layers, visibility, surface soil temperature and
moisture, both pressure-level temperatures, and 500 hPa geopotential height are
all-null or rejected on the PIT endpoint.

The immutable corpus plan therefore requests only the proved twelve-field
surface. Profile features that require one of the nine unavailable fields are
explicitly excluded with reasons. They must never be populated from the
stitched settled archive, because that would trade coverage for target-time
lookahead. The schema-known superset remains documented so a future genuine PIT
source can expand the contract through a reviewed change rather than a silent
alias.

### Legacy global trainers

Legacy feature-model and calibration CLIs may read ambient global artifacts or
the stitched daily forecast file and may write global artifact paths. They are
useful for controlled research and for understanding the incumbent, but they
are not the production-candidate path. Never promote their output by copying it
into a release.

### Supported all-market base retrain

`weather.operations.base_retrain` and
`weather.calibration.base_model_candidate` own the supported candidate lane.
The [nightly retrain runbook](NIGHTLY_RETRAIN_RUNBOOK.md) is the executable
contract. Its important properties are:

- an explicit, code-owned market/date/cutoff population;
- an immutable, issue-qualified PIT forecast corpus and hash-bound feature
  records;
- field-level train/serve parity for values, units, categories, missingness,
  and cutoff behavior;
- fold-local imputation, blocked year groups, out-of-fold tuning, and an
  untouched later qualification surface;
- candidate-only output outside the repository, protected-state inventories,
  fleet-atomic release construction, and no active-pointer mutation.

This lane is the correct first refit for repairing seasonal population and PIT
lineage. It intentionally freezes the parent's feature order and estimator
capacity. It refits each market's base estimators and exact-distribution
calibration, then copies the other verified parent components unchanged.

That makes it a **correctness baseline, not an information-gain candidate**. It
does not test newly staged Previous Runs fields, and copied downstream
postprocessors may remain statistically coupled to the old base distribution.
Every inherited stage still needs matched outer-date attribution before it is
kept in a promoted child.

### Challengers

Pooled, density, source-bias, and residual-model experiments remain research
challengers until they use the same PIT population, labels, serving feature
contract, and qualification design as the supported base lane. The next useful
challenger is deliberately simple: a regularized, market-identity-aware NWP
residual or ordinal model that tests genuinely new issue-qualified information
against the refitted incumbent. Market identity and native-unit semantics are
allowed; market prices are not model features. Complexity is not a substitute
for an independent signal.

## Evaluation Contract

For every candidate:

1. Freeze the population, code, dependencies, features, artifacts, labels, and
   source/request hashes before reading the result.
2. Preserve native settlement units and effective WU print cutoff semantics.
3. Compare against a simple market/date prior, the incumbent full stack, and
   the market benchmark. A benchmark-consuming control is not a weather
   candidate.
4. Tune only inside the training folds. Score a fitted mapping on its own
   training data as a basic objective sanity check, then use untouched outer
   dates for the claim.
5. Attribute both the complete served stack and stage removals on identical
   rows. Copied postprocessors receive no grandfathered credit.
6. Use crossed date-by-market clustering, report intervals and power/MDE, and
   keep artifact-regime boundaries separate.
7. Require captured-input replay or an explicitly labeled rebuilt-environment
   comparison, then immutable shadow evidence before promotion.
8. Fail closed on missing mass, lineage, identity, label quality, coverage, or
   release verification. Never weaken the serving floor to make a candidate
   pass.

## Decision Order

The shortest credible path is:

1. qualify the twelve-field PIT corpus contract and its provider-response export;
2. run the supported base retrain as a correctness and seasonal-baseline test;
3. build a generated model bill of materials and adopt loaded-process identity;
4. qualify the full candidate and its inherited stages on the same untouched
   PIT surface, retiring stages that do not pay their way;
5. fit the simple new-information challenger using the staged Previous Runs
   fields;
6. freeze a winning graph and collect immutable shadow evidence;
7. consider promotion only through the existing release and evidence gates.

See [roadmap item 330](../roadmap/items/item-330-model-bom-loaded-identity-and-pit-challenger.md)
for acceptance criteria. Item 321 remains the parent production-readiness and
release program.

## Update This File When

Update when the served graph, authoritative input family, supported training
lane, artifact/runtime identity contract, or model-evaluation contract changes.
Put scores and dated structural findings in `ESTABLISHED_FINDINGS.md`, current
priority in `STATE_OF_PLAY.md`, and implementation status in the owning roadmap
item.
