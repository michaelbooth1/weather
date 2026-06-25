# 89. Explicit Model Build Contract And Source Adapter Boundary [COMPLETE 2026-06-16 - EXPLICIT BUILD CONTRACTS LIVE]

Goal: make model builds explicit data flows instead of a broad mutable facade
that owns fetching, feature extraction, distribution state, presentation rows,
and artifact loading.

Source: 2026-06-16 architecture review. `TorontoHighTempModel` composes several
mixins and still acts as the runtime facade for live source fetching,
distribution estimation, feature vectors, analogs, presentation rows, source
diagnostics, and artifact loading. Distribution and calibration metadata are
currently exposed through `_last_*` attributes after `estimate_distribution()`.

Why this is missing: the mixin split made the model easier to navigate, but the
central object still carries too many responsibilities. Mutable side effects
make replay/debug behavior harder to reason about and make it risky to run
parallel or repeated builds against the same model instance.

- [x] Introduce explicit data contracts such as `SourceBundle`,
  `DistributionResult`, and `ModelBuildResult` for the main build path.
- [x] Return distribution components, calibration context, active model kind,
  and family-secondary gate metadata from distribution calls instead of reading
  `_last_*` attributes.
- [x] Extract live provider adapters out of `weather.model.model_sources` into a
  source-adapter layer that can be tested independently from
  `TorontoHighTempModel`.
- [x] Keep `TorontoHighTempModel` as a compatibility facade while moving the
  orchestration path toward explicit inputs and outputs.
- [x] Add regression tests proving repeated builds on one model instance do not
  leak stale distribution, calibration, source, or gate metadata.

Acceptance: model build outputs are represented by explicit result objects,
source fetching can be exercised without instantiating the full model facade,
and presentation/snapshot code consumes returned metadata rather than mutable
`_last_*` side effects.

## Design

Contract layer:

- Add `weather.model.model_contracts` with frozen dataclasses:
  `SourceBundle`, `DistributionResult`, and `ModelBuildResult`.
- Keep `TorontoHighTempModel.build()` returning the legacy dictionary shape for
  app/snapshot compatibility, but assemble that dictionary from a
  `ModelBuildResult`.
- Add `DistributionMixin.estimate_distribution_result()` as the explicit
  distribution API. `estimate_distribution()` remains as a compatibility method
  returning only the probability distribution.

Metadata flow:

- `DistributionResult` captures the final distribution, distribution-component
  payload, probability-calibration context, active model kind, and
  family-secondary gate at the end of one distribution run.
- `TorontoHighTempModel.build()` passes the returned `DistributionResult` into
  presentation helpers and exposes the plain serialized metadata in the legacy
  build dictionary.
- `SnapshotStore` should read calibration context from the build dictionary
  when recomputing band probabilities, rather than relying on whatever mutable
  `_last_probability_calibration_context` happens to be on the model object.

Source-adapter boundary:

- Add `weather.model.source_adapters` for provider orchestration primitives:
  timing a named source fetch, preserving the `{ok, data, latency_ms,
  fetched_at}` envelope, and collecting named fetchers concurrently.
- Keep provider-specific parsers in `model_sources.py` for this item, but route
  source-group execution through the adapter module so source fetch behavior can
  be tested without constructing `TorontoHighTempModel`.

Compatibility policy:

- Existing callers of `estimate_distribution()` and `build()` continue to work.
- Legacy `_last_*` attributes may be populated for tests/local users during the
  migration, but production build/snapshot code should consume explicit result
  metadata returned by the new contracts.

Verification strategy:

- Add unit tests for `estimate_distribution_result()`, `ModelBuildResult`
  serialization, repeated-build metadata isolation, and source-adapter
  orchestration.
- Run focused model, snapshot, replay, and source-cache tests, then the full
  suite before marking complete.

## Completion

Completed 2026-06-16.

- Added `weather.model.model_contracts` with `SourceBundle`,
  `DistributionResult`, and `ModelBuildResult`.
- Added `DistributionMixin.estimate_distribution_result()` and wired
  `TorontoHighTempModel.build()` to assemble the legacy dictionary from an
  explicit `ModelBuildResult`.
- Routed source-group execution through `weather.model.source_adapters` while
  keeping provider-specific parsing in `model_sources.py`.
- Updated presentation and snapshot persistence to consume returned
  distribution metadata, including probability-calibration context.
- Kept snapshot compatibility for legacy model clients that implement the old
  two-argument `bin_probability` call shape when no calibration context is
  required.
- Extended architecture coverage to include the new model boundary modules.

Verification:

- Focused model/source/snapshot/replay slice: 77 passed.
- `.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py -q` (6 passed)
- `.\venv\Scripts\python.exe -m pytest` (793 passed)

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - EXPLICIT BUILD CONTRACTS LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

