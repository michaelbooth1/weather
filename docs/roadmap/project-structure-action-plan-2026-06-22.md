# Project Structure Action Plan - 2026-06-22

## Purpose

This is the follow-up work plan from reviewing
`docs/roadmap/project-structure-audit-2026-06-22.md` against the current
worktree. It turns the audit findings into the order of work I would undertake
now.

Scope: repository structure, package boundaries, compatibility shims, generated
state, docs, tests, scripts, artifacts, and local runtime data. This is not a
model-accuracy or trading-policy review.

## Review Verdict

I agree with the main conclusion of the existing audit: the top-level layout is
basically right, and the next improvements should happen inside the existing
package structure rather than through another broad top-level move.

The strongest findings still hold:

- `src/weather` is the canonical source package.
- `artifacts` is the right home for durable model and calibration artifacts.
- `data` should stay ignored local runtime state.
- `docs/roadmap/items` is now a roadmap database and needs generated indexes.
- compatibility shims should be temporary, not a permanent second public API.
- `weather.reporting` is too broad and should split by reporting subdomain.
- module size and package-edge tests are the right long-term ratchets.

The old audit is now stale in several concrete ways:

- tracked file counts grew from `src=330`, `docs=262`, `tests=174`, `app=9` to
  `src=361`, `docs=306`, `tests=206`, `app=10`.
- tracked Python files grew from 542 to 606.
- roadmap items grew from 217 to 253.
- `weather.reporting` grew from 85 files / about 51,900 lines to 114 files /
  about 70,282 lines.
- the current architecture-ratchet failure is no longer the same untracked
  source/test set listed in the old audit. It is now:
  - `tests/market/test_taker_bot_two_sided.py` is untracked in a critical test
    path.
  - README still includes `streamlit run app.py`.
  - `weather.collection.live_variant_predictions` imports
    `weather.calibration`, creating an undocumented `collection -> calibration`
    edge.
- ignored local runtime state grew further: `data/tape_backups` is about
  89,302 MiB and `data/snapshots` is about 84,435 MiB.

## Current Evidence Snapshot

Current dirty worktree summary:

```text
Modified:
  src/weather/market/taker_bot_sizing.py
  src/weather/market/taker_bot_strategy_registry.py

Untracked:
  docs/roadmap/project-structure-action-plan-2026-06-22.md
  tests/market/test_taker_bot_two_sided.py
```

Current architecture ratchet:

```text
python -m pytest tests/operations/test_import_architecture.py -q
14 passed, 3 failed
```

Failures:

1. `test_project_critical_files_are_tracked_or_ignored`
   - offender: `tests/market/test_taker_bot_two_sided.py`
2. `test_first_party_surfaces_do_not_call_compatibility_shims`
   - offender: `README.md`
   - match: `streamlit run app.py`
3. `test_package_dependency_edges_follow_documented_ratchet`
   - offender: `collection->calibration`
   - file: `src/weather/collection/live_variant_predictions.py`

Current package sizes:

| Package | Python files | Lines |
| :--- | ---: | ---: |
| `weather.reporting` | 114 | 70,282 |
| `weather.market` | 37 | 22,101 |
| `weather.operations` | 30 | 15,794 |
| `weather.calibration` | 23 | 15,669 |
| `weather.sources` | 22 | 12,521 |
| `weather.model` | 17 | 10,819 |
| `weather.collection` | 10 | 7,147 |
| `weather.backtesting` | 10 | 4,908 |
| `weather.scoring` | 3 | 242 |

Current largest modules over 2,000 lines:

| Module | Lines |
| :--- | ---: |
| `weather.reporting.daily_learning` | 2,143 |
| `weather.calibration.pooled_candidate_replay` | 2,042 |
| `weather.reporting.data_layer_audit` | 2,020 |

Near-threshold modules:

| Module | Lines |
| :--- | ---: |
| `weather.collection.snapshot_store` | 1,978 |
| `weather.reporting.disagreement_casebook` | 1,892 |
| `weather.model.model_sources` | 1,883 |
| `weather.model.model_features` | 1,849 |
| `weather.operations.tape_backup` | 1,789 |
| `weather.reporting.source_family_inventory` | 1,753 |
| `weather.reporting.multi_variant_shadow` | 1,693 |
| `weather.operations.daily_refresh_steps` | 1,678 |

## Action Order

I would do this in small, reviewable batches. The key principle is to restore
the structure ratchet first, then make the audit reproducible, then split large
modules behind stable public facades.

## Phase 0 - Preserve User Work And Establish Baseline

### Step 0.1 - Confirm dirty worktree ownership

Actions:

1. Run `git status --short`.
2. Treat all pre-existing modified and untracked files as user-owned.
3. Avoid formatting or moving files not directly involved in the current
   structural task.

Acceptance:

- No unrelated file is reverted or rewritten.
- The action PR/diff contains only structure-audit or targeted ratchet changes.

### Step 0.2 - Capture the current structure baseline

Actions:

1. Run the architecture ratchet:
   `python -m pytest tests/operations/test_import_architecture.py -q`.
2. Capture top-level tracked file counts.
3. Capture package line counts.
4. Capture modules over 1,000 and 2,000 lines.
5. Capture ignored `data` size by immediate child directory.

Acceptance:

- A single markdown or JSON artifact records the current baseline.
- The baseline names exact command outputs and dates.

## Phase 1 - Restore The Architecture Ratchet

### Step 1.0 - Classify the untracked critical test file

Problem:

`tests/market/test_taker_bot_two_sided.py` is untracked under a critical test
path, so the architecture ratchet fails before it can be treated as a clean
structural baseline.

Actions:

1. Review the test file to confirm whether it belongs to the current taker-bot
   two-sided/no-side work.
2. If it is valid project work, keep it under `tests/market` and stage it with
   the related taker-bot changes.
3. If it is scratch or abandoned work, move it out of `tests` or add an
   explicit ignore/classification only after confirming it should not be part
   of the suite.
4. Run:
   `python -m pytest tests/operations/test_import_architecture.py::test_project_critical_files_are_tracked_or_ignored -q`.

Acceptance:

- No untracked files remain under project-critical source/test/app/ops/tool
  paths.
- The tracked-or-ignored architecture check passes.

### Step 1.1 - Remove the README compatibility-shim command

Problem:

`README.md` currently contains both the canonical dashboard command and the
legacy shim command:

```powershell
.\venv\Scripts\python.exe -m streamlit run app/streamlit_app.py
.\venv\Scripts\python.exe -m streamlit run app.py
```

The second command violates the first-party shim caller rule.

Actions:

1. Keep `app/streamlit_app.py` as the documented command.
2. Remove the `streamlit run app.py` example from active README instructions,
   or move it to a clearly historical compatibility note outside active command
   surfaces if the test permits that wording.
3. Run:
   `python -m pytest tests/operations/test_import_architecture.py::test_first_party_surfaces_do_not_call_compatibility_shims -q`.

Acceptance:

- The targeted shim-caller test passes.
- README active instructions only use canonical `weather.*`,
  `app/streamlit_app.py`, `scripts/ops`, `scripts/launch`, and `tools/*`
  surfaces.

### Step 1.2 - Resolve `collection -> calibration` in live variant predictions

Problem:

`src/weather/collection/live_variant_predictions.py` imports runtime prediction
helpers from calibration modules:

- `weather.calibration.pooled_feature_model.band_prediction_record`
- `weather.calibration.pooled_feature_model.apply_band_postprocessing`
- `weather.calibration.pooled_feature_model.predict_band_rows_for_bundle`
- `weather.calibration.pooled_candidate_replay.apply_continuous_density_calibration`
- `weather.calibration.pooled_candidate_replay.density_band_probability_from_distribution`
- `weather.calibration.pooled_candidate_replay.microstructure_feature_frame`

That creates an undocumented `collection -> calibration` edge. I would not
simply bless this as a stable edge because collection is a live capture/runtime
owner, while calibration owns training/replay/promotion artifact generation.

Preferred actions:

1. Create a serving/runtime owner module, likely one of:
   - `weather.model.variant_prediction_runtime`
   - `weather.model.pooled_candidate_runtime`
2. Move only serving-safe pure prediction helpers into that module.
3. Update `weather.collection.live_variant_predictions` to import from the new
   runtime module.
4. Update calibration modules to import those extracted helpers instead of
   defining runtime behavior themselves.
5. Keep CLI, replay, training, artifact writing, and report generation in
   `weather.calibration`.
6. Run focused tests:
   - `python -m pytest tests/collection/test_live_variant_predictions.py -q`
   - `python -m pytest tests/calibration/test_pooled_candidate_replay.py -q`
   - `python -m pytest tests/operations/test_import_architecture.py -q`

Fallback if extraction is too large for one pass:

1. Add `collection -> calibration` as a documented transitional edge in
   `docs/operations/package-boundaries.md`.
2. Add the same pair to `TRANSITIONAL_PACKAGE_EDGES` in
   `tests/operations/test_import_architecture.py`.
3. Create a follow-up roadmap item to extract runtime prediction helpers.

Acceptance:

- Full architecture ratchet passes.
- Either no `collection -> calibration` edge remains, or it is explicitly
  transitional with an owner and removal target.

## Phase 2 - Make The Audit Reproducible

### Step 2.1 - Add `weather.operations.structure_inventory`

Problem:

The current audit requires many ad hoc shell scans. That makes future audits
slow and easy to stale.

Actions:

1. Add `src/weather/operations/structure_inventory.py`.
2. Emit JSON by default under `data/backtest/structure_inventory.json`.
3. Optionally emit markdown under
   `data/backtest/structure_inventory_report.md`.
4. Include:
   - top-level tracked file counts
   - extension counts
   - source package line counts
   - modules over configurable line thresholds
   - test package line counts
   - app view line counts
   - compatibility shim count
   - artifact count and size summary
   - ignored `data` size summary
   - architecture ratchet status, optionally skipped by flag
5. Add tests under `tests/operations/test_structure_inventory.py` with temporary
   fixture trees so tests do not depend on local `data`.

Acceptance:

- One command regenerates the high-signal tables from this action plan.
- Tests avoid scanning the developer's local runtime data.

### Step 2.2 - Wire structure inventory into documentation workflow

Actions:

1. Add a README or operations-doc command:
   `python -m weather.operations.structure_inventory --report`.
2. Reference it from `docs/operations/module-ownership-map.md`.
3. Keep generated reports under ignored `data/backtest` unless explicitly
   promoted to docs.

Acceptance:

- Future structure audits can cite a command rather than hand-counted evidence.

## Phase 3 - Split Current 2,000-Line Modules

### Step 3.1 - Split `weather.reporting.daily_learning`

Why first:

It is now the largest module at 2,143 lines, and it belongs to the already
overgrown reporting package.

Actions:

1. Identify current responsibilities: log readers, evidence extraction,
   synthesis/decision model, markdown rendering, CLI.
2. Extract pure readers to `weather.reporting.daily_learning_readers`.
3. Extract synthesis/summary model to `weather.reporting.daily_learning_summary`.
4. Extract markdown rendering to `weather.reporting.daily_learning_render`.
5. Keep `weather.reporting.daily_learning` as the compatibility facade and CLI
   entrypoint.
6. Add an architecture test rule that extracted modules do not import the
   facade.
7. Run `python -m pytest tests/reporting/test_daily_learning.py -q`.

Acceptance:

- `daily_learning.py` drops below 1,500 lines.
- Existing command/import surface remains stable.

### Step 3.2 - Split `weather.reporting.data_layer_audit`

Actions:

1. Preserve `weather.reporting.data_layer_audit` as public facade/CLI.
2. Move source probes and row collection to
   `weather.reporting.data_layer_audit_collectors`.
3. Move gate/status classification to
   `weather.reporting.data_layer_audit_gates`.
4. Move report rendering to the already existing report-oriented module if
   practical, or a new `data_layer_audit_render`.
5. Keep remediation manifest logic separate from report rendering.
6. Run:
   - `python -m pytest tests/reporting/test_data_layer_audit.py -q`
   - `python -m pytest tests/operations/test_import_architecture.py -q`

Acceptance:

- `data_layer_audit.py` drops below 1,500 lines.
- Extracted modules do not import the facade.

### Step 3.3 - Split `weather.calibration.pooled_candidate_replay`

Actions:

1. Separate runtime-safe prediction helpers first if not already done in Phase
   1.
2. Move readers and row normalization to a reader module.
3. Move scoring/math to a scoring module.
4. Move markdown/report output to a report module.
5. Keep replay orchestration and CLI in the facade.
6. Run:
   - `python -m pytest tests/calibration/test_pooled_candidate_replay.py -q`
   - `python -m pytest tests/reporting/test_multi_variant_shadow.py -q`
   - `python -m pytest tests/operations/test_import_architecture.py -q`

Acceptance:

- `pooled_candidate_replay.py` drops below 1,500 lines.
- Runtime prediction logic is not owned by calibration unless explicitly
  training/replay-only.

## Phase 4 - Contain Reporting Package Growth

### Step 4.1 - Add reporting subpackage conventions

Actions:

1. Add subpackages gradually:
   - `weather.reporting.observability`
   - `weather.reporting.promotion`
   - `weather.reporting.validation`
   - `weather.reporting.roadmap`
   - `weather.reporting.trading`
2. Start only with modules already split behind facades.
3. Keep public compatibility facades in `weather.reporting.*` until callers are
   migrated.
4. Update `docs/operations/package-boundaries.md` with subpackage guidance.

Acceptance:

- New reporting work has a target subdomain.
- No large bulk move happens without tests.

### Step 4.2 - Move one low-risk reporting family as a pilot

Recommended pilot:

`promotion_refresh_*` is already split into readers, decisions, gap analysis,
orchestration, report, and CLI modules.

Actions:

1. Create `weather.reporting.promotion`.
2. Move promotion-refresh implementation slices into that subpackage.
3. Leave `weather.reporting.promotion_refresh` as public facade.
4. Update imports and tests.
5. Run `python -m pytest tests/calibration/test_promotion_refresh.py -q`.

Acceptance:

- A reporting subpackage exists with one proven migrated family.
- Facade remains stable.

## Phase 5 - Reduce Transitional Package Edges

### Step 5.1 - Make an edge burn-down table

Actions:

1. Use `structure_inventory` or a small AST scanner to list observed edges.
2. Compare with `ALLOWED_PACKAGE_EDGES` and `TRANSITIONAL_PACKAGE_EDGES`.
3. Add a table to `docs/operations/package-boundaries.md`:
   - edge
   - current files
   - owner
   - planned removal approach
   - target date or blocking condition

Acceptance:

- Every transitional edge has a named removal route.

### Step 5.2 - Burn down `sources -> model`

Why:

This is already documented as transitional, and it indicates provider/source
code is still using serving model helpers.

Actions:

1. Identify the exact import in source modules.
2. Move shared schema or feature helpers to a shared module if they are pure.
3. Keep provider fetch/parsing in `weather.sources`.
4. Keep serving assembly in `weather.model`.
5. Remove `sources -> model` from the transitional edge list after tests pass.

Acceptance:

- `sources -> model` no longer appears in observed package edges.

### Step 5.3 - Burn down one reporting edge

Recommended first target:

`reporting -> operations` or `reporting -> calibration`, whichever has the
smallest number of callers after Phase 3/4.

Actions:

1. Extract shared status dataclasses or report rows to `weather.reporting` or
   shared utilities.
2. Avoid importing orchestration modules from report builders.
3. Update package-boundary docs and tests.

Acceptance:

- At least one transitional edge is removed from both code and docs.

## Phase 6 - Add Smaller Hygiene Ratchets

### Step 6.1 - Add dependency drift check

Problem:

Dependencies are duplicated in `requirements.txt` and `pyproject.toml`.

Actions:

1. Add a small test or operations audit that parses both files.
2. Compare package names and pinned versions.
3. Fail if one file changes without the other.

Acceptance:

- Dependency drift fails locally before it reaches CI.

### Step 6.2 - Normalize retired research scripts

Problem:

`tools/research` contains retired probes named `test_*.py`, which are not
collected by pytest but still look like tests.

Actions:

1. Create `tools/research/retired`.
2. Move retired probes there or rename them away from `test_*.py`.
3. Keep `research_harness.py` available for historical/ad hoc runs.
4. Add a simple architecture test that `tools/research/test_*.py` is empty
   unless a file is explicitly allowed.

Acceptance:

- Research helpers no longer resemble unit tests.

### Step 6.3 - Add roadmap item metadata guard

Problem:

There are now 253 roadmap item files. They are a database in practice.

Actions:

1. Add optional front matter or a generated manifest that records:
   - item id
   - title
   - status
   - date
   - disposition
   - owner/package
2. Keep `active-backlog.md` generated from that source.
3. Extend roadmap lint to detect duplicate ids, missing statuses, and stale
   ROADMAP rows.

Acceptance:

- Roadmap parsing is not dependent only on heading text conventions.

## Phase 7 - Control Ignored Runtime State

### Step 7.1 - Add ignored-data disk budget reporting

Problem:

Ignored local runtime state is very large:

| Area | Files | MiB |
| :--- | ---: | ---: |
| `data/tape_backups` | 4,195 | 89,301.61 |
| `data/snapshots` | 140,742 | 84,434.81 |
| `data/noaa_ghcnh` | 4,187 | 6,321.24 |
| `data/wunderground` | 74,052 | 3,885.01 |
| `data/backtest` | 1,290 | 3,286.61 |
| `data/metar` | 4,753 | 3,060.00 |

Actions:

1. Extend existing retention/tape backup tooling or the new
   `structure_inventory` command to report ignored data sizes.
2. Add warning thresholds by area.
3. Recommend moving backup roots outside the repo when size exceeds threshold.
4. Keep generated reports under `data/backtest`.

Acceptance:

- Operators can see disk pressure before daily refresh or snapshot loops fail.
- Routine structure scans do not traverse `data` unless explicitly requested.

## Phase 8 - Revisit Compatibility Shims On Schedule

### Step 8.1 - Prepare but do not prematurely delete shims

Problem:

The audit correctly identifies 86 flat `src/*.py` wrappers plus root helper,
app, and script shims. The documented expiration date is 2026-07-18.

Actions now:

1. Keep first-party docs and scripts off shim paths.
2. Keep the architecture test enforcing no first-party shim calls.
3. Add a dated checklist for the 2026-07-18 review.

Actions on or after 2026-07-18:

1. Re-run the caller scan.
2. Check known scheduled tasks and operator paths.
3. Delete shim batches with no dependency.
4. Document any retained shim with owner, dependency, and next review date.

Acceptance:

- No shim remains solely because the cleanup date was missed.

## Proposed Work Batches

### Batch 1 - Ratchet repair

Files likely touched:

- `tests/market/test_taker_bot_two_sided.py`, if it is valid project work and
  should be staged with the current taker-bot changes
- `README.md`
- `src/weather/collection/live_variant_predictions.py`
- new runtime helper module, if extracting
- affected calibration modules, if extracting
- `docs/operations/package-boundaries.md`, only if a transitional edge is
  intentionally documented
- `tests/operations/test_import_architecture.py`, only if a transitional edge
  is intentionally documented

Verification:

```powershell
.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py -q
.\venv\Scripts\python.exe -m pytest tests\collection\test_live_variant_predictions.py -q
```

### Batch 2 - Structure inventory

Files likely touched:

- `src/weather/operations/structure_inventory.py`
- `tests/operations/test_structure_inventory.py`
- `docs/operations/module-ownership-map.md`

Verification:

```powershell
.\venv\Scripts\python.exe -m pytest tests\operations\test_structure_inventory.py -q
.\venv\Scripts\python.exe -m weather.operations.structure_inventory --report
```

### Batch 3 - First large-module split

Start with:

- `src/weather/reporting/daily_learning.py`

Verification:

```powershell
.\venv\Scripts\python.exe -m pytest tests\reporting\test_daily_learning.py -q
.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py -q
```

### Batch 4 - Reporting subpackage pilot

Start with:

- promotion-refresh implementation slices

Verification:

```powershell
.\venv\Scripts\python.exe -m pytest tests\calibration\test_promotion_refresh.py -q
.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py -q
```

## Tasks I Would Not Start With

I would not start with these:

1. Bulk-moving all reporting files into subpackages.
2. Deleting root shims before the 2026-07-18 compatibility window.
3. Moving `data` into Git or tracking generated reports by default.
4. Splitting model/calibration modules before the architecture ratchet is green.
5. Rewriting roadmap item history instead of adding metadata/indexing around
   it.

## Definition Of Done For This Structure Push

The first structure push is complete when:

1. `tests/operations/test_import_architecture.py` passes.
2. `README.md` has no active shim command examples.
3. `collection -> calibration` is either removed or explicitly transitional
   with a removal plan.
4. `weather.operations.structure_inventory` can regenerate current structure
   metrics.
5. At least one over-2,000-line module is split behind a stable facade.
6. The action plan and package-boundary docs name the next edge/module to burn
   down.
