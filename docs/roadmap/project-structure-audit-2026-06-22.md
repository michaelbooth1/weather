# Project Structure Audit - 2026-06-22

## Scope

This audit covers repository structure, package ownership, generated state,
compatibility shims, documentation layout, tests, scripts, config, and artifacts
in the current worktree. It does not evaluate model skill, trading policy
quality, or provider correctness.

Evidence used:

- `git status --short`
- `git ls-files`
- `rg --files`
- `pyproject.toml`, `pytest.ini`, `.gitignore`, `.gitattributes`
- existing structure docs under `docs/operations/` and `docs/roadmap/`
- line-count and file-count scans for `src/weather`, `tests`, `app`, `tools`,
  `artifacts`, and ignored `data`
- targeted architecture ratchet:
  `python -m pytest tests/operations/test_import_architecture.py -q`

The worktree already had unrelated modified files before this audit. This file
does not depend on reverting them.

## Executive Summary

The project is much better structured than the older flat-layout audit in
`docs/roadmap/codebase-organization-audit.md`: implementation now lives under
`src/weather`, artifacts moved to `artifacts`, app views are split under `app`,
config is centralized, `data` is ignored runtime state, and architecture tests
ratchet import/path rules.

The remaining structure risks are growth-management issues rather than a broken
layout:

1. The compatibility layer is still large: 86 flat `src/*.py` wrappers, root
   helper shims, root `app.py`, and root `scripts/*` shims.
2. `weather.reporting` has become the largest owner package by a wide margin:
   85 Python files and about 51,900 lines.
3. There are still 36 source modules over 1,000 lines, with
   `pooled_candidate_replay.py` and `data_layer_audit.py` just over the current
   2,000-line warning threshold.
4. Several documented cross-package imports are still transitional. They are
   tracked, but they show real coupling between reporting, operations, market,
   collection, calibration, and backtesting.
5. Ignored local runtime state is enormous inside the repo root. That is okay
   for Git hygiene but risky for local operations, backup, and accidental tool
   scans.
6. The current architecture ratchet fails only because critical files are
   untracked in the worktree. The rule is good; the current state needs staging
   or intentional ignore handling.

## Current Top-Level Hierarchy

```text
.
  .github/workflows/          CI automation
  app/                        Streamlit application package and views
  artifacts/                  tracked durable model/calibration artifacts
  config/                     checked-in config and registries
  data/                       ignored local runtime state, tapes, caches, reports
  docs/                       operations, research, and roadmap documents
  scripts/
    launch/                   canonical dashboard launchers
    ops/                      canonical scheduled-task registration scripts
    *.ps1/*.cmd/*.vbs         compatibility shims to launch/ops
  src/
    weather/                  canonical source package
    *.py                      flat compatibility wrappers for old src.* commands
  tests/                      unit and architecture tests
  tools/                      reusable helpers and research CLIs
  weather/__init__.py         repo-root import shim for local Windows workers
  app.py                      Streamlit compatibility shim
  backfill_all.py             helper compatibility shim
  scratch.py                  helper compatibility shim
  train_all_markets.ps1       helper compatibility shim
```

Tracked file counts by top-level area:

| Area | Tracked files | Role |
| :--- | ---: | :--- |
| `src` | 330 | canonical package plus compatibility wrappers |
| `docs` | 262 | operations docs, research notes, roadmap item database |
| `tests` | 174 | unit, architecture, app, and fixture tests |
| `artifacts` | 106 | model pickles, calibration JSON, manifests |
| `tools` | 29 | reusable helpers and research scripts |
| `scripts` | 22 | launcher/ops scripts plus compatibility shims |
| `app` | 9 | Streamlit router and views |
| `config` | 6 | durable and generated config registries |
| root files | 13 | package config, docs, local shims, path/import helpers |

Tracked file counts by extension:

| Extension | Count |
| :--- | ---: |
| `.py` | 542 |
| `.md` | 261 |
| `.json` | 90 |
| `.pkl` | 26 |
| `.ps1` | 19 |
| `.cmd` | 2 |
| `.vbs` | 2 |
| other config/text | 6 |

## Current Worktree State

`git status --short` shows modified roadmap, collection, market, model,
operations, and test files. It also shows untracked work in project-critical
areas:

```text
src/weather/market/snapshot_cadence_quality.py
src/weather/reporting/frozen_baseline_replay_trend.py
tests/model/test_current_day_wu_history_degradation.py
tests/reporting/test_frozen_baseline_replay_trend.py
docs/roadmap/items/item-217-pinned-frozen-baseline-replay-trend.md
```

The architecture ratchet run produced:

```text
16 passed, 1 failed
```

The one failure was
`test_project_critical_files_are_tracked_or_ignored`, caused by the four
untracked critical source/test files. Structurally, this is the right failure:
new implementation/test files should be either tracked or explicitly classified
before the architecture scan goes green.

## Root File Map

| Path | Current role | Structure note |
| :--- | :--- | :--- |
| `.gitattributes` | line-ending policy and Git LFS rule for HGB pickles | keep; this protects artifact bytes |
| `.gitignore` | ignores venv/cache/raw runtime state and `data/` | good policy; data remains local runtime state |
| `README.md` | primary operator setup and command guide | current commands use `weather.*` modules |
| `pyproject.toml` | source-layout package metadata | canonical package is found under `src` |
| `requirements.txt` | pinned runtime dependency list | duplicates dependency list in `pyproject.toml` |
| `pytest.ini` | testpaths and `pythonpath = src` | keeps tests off ignored scratch/live probes |
| `sitecustomize.py` | local Windows scheduled-worker defaults and `src` path insert | useful local safeguard, but should stay narrowly scoped |
| `app.py` | compatibility shim for `streamlit run app.py` | remove after shim expiration window if no external dependency |
| `backfill_all.py` | compatibility shim to `tools/backfill_all.py` | remove after shim expiration window |
| `scratch.py` | compatibility shim to `tools/generate_market_specs_from_locations.py` | name is misleading; retire after shim window |
| `train_all_markets.ps1` | compatibility shim to `tools/train_all_markets.ps1` | remove after shim expiration window |
| `weather/__init__.py` | repo-root import shim that extends path to `src/weather` | keep only while Windows worker path safety needs it |
| `.github/workflows/retrain.yml` | nightly retrain/backfill/artifact audit workflow | uses canonical `weather.*` commands |

## Canonical Package Map

| Package | Files | Lines | Ownership | Main growth pressure |
| :--- | ---: | ---: | :--- | :--- |
| `weather.reporting` | 85 | 51,909 | durable reports, audit rendering, promotion summaries, dashboard support | package is becoming too broad |
| `weather.market` | 37 | 19,751 | market config, CLOB capture, MM/taker policy, paper/live exchange boundaries | market operations and strategy code share one package |
| `weather.calibration` | 23 | 15,593 | training, candidate replay/scoring, calibration artifacts | replay/scoring modules remain large |
| `weather.operations` | 29 | 13,816 | scheduled jobs, supervisors, repairs, runtime identity | orchestration imports reporting and market heavily |
| `weather.sources` | 22 | 12,483 | raw provider fetch, parsing, historical stores | source modules still reuse model helpers in one edge |
| `weather.model` | 17 | 10,059 | serving-time feature extraction, distributions, source adapters | `model_sources` and feature/distribution modules are large |
| `weather.collection` | 10 | 6,738 | live snapshot capture/storage/archive/health | `snapshot_store` is near 2,000 lines |
| `weather.backtesting` | 10 | 4,908 | replay, settlement IO, tape scoring, analytics | manageable but coupled to collection/reporting |
| `weather.scoring` | 3 | 242 | shared scoring math | good shared utility package |

Shared root modules under `src/weather`:

| Module | Role |
| :--- | :--- |
| `artifacts.py` | artifact path policy, registry, size/preflight audit |
| `paths.py` | canonical repo/data/artifact/config/docs paths |
| `io.py` | shared IO helpers |
| `schema_registry.py` | central schema-version registry and migration audit |
| `time.py` | shared time helpers |
| `units.py` | canonical nullable temperature and bucket helpers |
| `variant_registry.py` | shared model-variant registry helpers |

## Large Module Watchlist

Modules over 1,000 lines:

| Module | Lines | Suggested owner split |
| :--- | ---: | :--- |
| `weather.calibration.pooled_candidate_replay` | 2,021 | CLI/orchestration, readers, scoring, rendering, persistence |
| `weather.reporting.data_layer_audit` | 2,020 | source probes, gates, remediation model, rendering |
| `weather.reporting.daily_learning` | 1,966 | parsers, extractors, synthesis, report writer |
| `weather.collection.snapshot_store` | 1,955 | schema constants, readers, writers, cadence metadata, migrations |
| `weather.reporting.disagreement_casebook` | 1,892 | input loading, case classification, report rendering |
| `weather.model.model_sources` | 1,869 | provider fetch clients vs serving adapter logic |
| `weather.operations.tape_backup` | 1,789 | manifest, retention, backup, restore drill CLI |
| `weather.calibration.feature_model` | 1,617 | training pipeline, artifact IO, CLI, reports |
| `weather.reporting.candidate_lifecycle.multi_variant_shadow` | 1,610 | row normalization, scoring, governance report, CLI |
| `weather.model.model_features` | 1,583 | feature extraction groups and source-state features |
| `weather.market.mm_paper` | 1,575 | tape ingestion, scoring, accounting, report/CLI |
| `weather.operations.observation_trigger` | 1,548 | watcher loop, trigger classification, replay, CLI |
| `weather.reporting.ten_minute_model_performance` | 1,521 | scoring, slots, gates, rendering, CLI |
| `weather.reporting.source_gates.source_family_inventory` | 1,497 | source inventory, promotion gates, report |
| `weather.sources.reanalysis_synoptic` | 1,430 | retrieval, sidecars, feature transforms, audit |
| `weather.market.mm_policy` | 1,427 | pure policy, risk overlays, quote intent formatting |
| `weather.model.model_distribution` | 1,417 | distribution construction, calibration, explanations |
| `weather.market.market_microstructure` | 1,385 | facade/orchestration around capture/features/audit |
| `weather.model.feature_store` | 1,380 | schema, transforms, validation, export helpers |
| `weather.operations.daily_refresh_steps` | 1,362 | registry, adapters, status aggregation |
| `weather.reporting.source_gates.source_redundancy` | 1,356 | daily truth, redundancy metrics, report |
| `weather.calibration.pooled_candidate_scoring` | 1,347 | row-level scoring and shadow policy helpers |
| `weather.reporting.progress_audit` | 1,299 | data loading, gate model, doc/report output |
| `weather.reporting.settled_day_root_cause` | 1,268 | data joins, classification, rendering |
| `weather.market.market_making_run_support` | 1,236 | support helpers for run orchestrator |
| `weather.schema_registry` | 1,208 | registry entries plus audit/check logic |
| `weather.collection.collection_health` | 1,179 | coverage checks, degradation, CLI/report |
| `weather.sources.eccc_swob_history` | 1,120 | fetch/parse/store/report for SWOB |
| `weather.market.market_making_run` | 1,111 | date/budget MM orchestrator |
| `weather.market.mm_exchange` | 1,101 | keyless exchange adapter and reports boundary |
| `weather.calibration.pooled_density_training` | 1,088 | density training pipeline |
| `weather.reporting.variant_basket_selection_validation` | 1,087 | validation harness and reports |
| `weather.reporting.location_analysis.no_market_location_transfer` | 1,077 | no-market transfer validation |
| `weather.reporting.candidate_lifecycle.price_free_model_learning` | 1,067 | inactive-market diagnostics |
| `weather.calibration.pooled_feature_assembly` | 1,053 | pooled feature matrix assembly |
| `weather.operations.nightly_retrain` | 1,009 | retrain orchestration |

The current warning threshold in `docs/operations/module-ownership-map.md` is
2,000 lines. Two modules now exceed it by line count, and several others are
close enough that new work will keep pushing them over.

## Test Map

| Test area | Python files | Lines | Notes |
| :--- | ---: | ---: | :--- |
| `tests/reporting` | 58 | 14,477 | mirrors largest production package |
| `tests/market` | 16 | 6,594 | MM/taker/CLOB tests |
| `tests/model` | 24 | 6,348 | feature, distribution, source-adapter tests |
| `tests/calibration` | 13 | 6,233 | pooled/replay/calibration tests |
| `tests/operations` | 23 | 5,830 | architecture, scheduler, daily refresh tests |
| `tests/sources` | 15 | 3,356 | provider/source tests |
| `tests/backtesting` | 8 | 1,385 | replay/backtest tests |
| `tests/collection` | 7 | 1,356 | snapshot/collection tests |
| `tests/app` | 5 | 428 | app smoke/view tests |

Large test files track large modules. That is useful coverage, but it is also a
signal to split fixtures/builders from assertions:

- `tests/calibration/test_pooled_candidate_replay.py`: 1,805 lines
- `tests/reporting/test_fleet_observability.py`: 1,367 lines
- `tests/calibration/test_pooled_feature_model.py`: 1,312 lines
- `tests/market/test_market_making_run.py`: 1,303 lines
- `tests/market/test_taker_bot.py`: 1,278 lines
- `tests/reporting/test_daily_learning.py`: 1,232 lines
- `tests/operations/test_daily_refresh.py`: 1,229 lines

## App Map

| Path | Lines | Role |
| :--- | ---: | :--- |
| `app/streamlit_app.py` | 80 | page routing and query param sync |
| `app/views/single_market.py` | 697 | main per-market dashboard |
| `app/views/market_making.py` | 448 | market-making dashboard |
| `app/views/operations.py` | 156 | local worker/operator page |
| `app/views/history.py` | 109 | history page |
| `app/views/overview.py` | 69 | overview page |
| `app/table_utils.py` | 51 | shared table helpers |

The app split is healthy. The next app refactor should target
`single_market.py` and `market_making.py` by separating data loading,
view-model assembly, and rendering helpers.

## Config Map

| Path | Role | Structure note |
| :--- | :--- | :--- |
| `config/locations.json` | durable location/station/source-plan registry | large hand-authored registry |
| `config/location_market_events.json` | generated active-event metadata | volatile config tracked in Git; consider `config/generated/` |
| `config/markets.json` | deprecated compatibility shell | keep only while `market_registry` still documents it |
| `config/model_variant_registry.json` | model variant lifecycle and artifact contract registry | important promotion input |
| `config/no_market_extra_locations.json` | no-market shadow registry | should stay near location registry but with clear promotion state |
| `config/supplemental_stations.json` | nearby station provenance registry | durable config |

`docs/operations/config-inventory.md` already documents classifications. The
remaining structure issue is that durable hand-authored config and generated
volatile config share one flat directory.

## Artifact Map

| Area | Files | MiB | Notes |
| :--- | ---: | ---: | :--- |
| `artifacts/models` | 50 | 365.82 | HGB pickles and model-adjacent files |
| `artifacts/calibration` | 51 | 1.61 | JSON calibration artifacts |
| `artifacts/manifests` | 5 | 0.16 | registry, size audit, promotion preflight |

Largest working-tree artifacts:

| Path | MiB |
| :--- | ---: |
| `artifacts/models/hgb/feature_model_hgb_f_pooled.pkl` | 98.93 |
| `artifacts/models/hgb/feature_model_hgb.pkl` | 27.88 |
| `artifacts/models/hgb/feature_model_hgb_denver.pkl` | 21.65 |
| `artifacts/models/hgb/feature_model_hgb_miami.pkl` | 19.78 |
| `artifacts/models/hgb/feature_model_hgb_seattle.pkl` | 18.88 |

`.gitattributes` correctly puts `artifacts/models/hgb/*.pkl` under Git LFS.
The first pooled model is close to the 100 MiB failure threshold documented in
`docs/operations/artifact-storage-policy.md`.

## Ignored Local Data Map

`data/` is ignored and untracked, but it is operationally very large:

| Area | Files | MiB |
| :--- | ---: | ---: |
| `data/tape_backups` | 3,845 | 76,859.94 |
| `data/snapshots` | 122,607 | 72,513.77 |
| `data/noaa_ghcnh` | 4,187 | 6,321.24 |
| `data/wunderground` | 74,052 | 3,885.07 |
| `data/reanalysis` | 8,071 | 3,328.50 |
| `data/metar` | 4,753 | 3,060.00 |
| `data/backtest` | 1,131 | 2,744.57 |
| `data/mm_runs` | 225 | 910.32 |
| `data/taker_runs` | 40 | 312.96 |
| `data/ops` | 14 | 127.12 |

Keeping this out of Git is correct. The structure risk is local operational:
repo-wide scans, backups, and disk pressure can become dominated by ignored
state unless tooling consistently scopes itself to tracked/source directories.

## Scripts And Tools Map

Canonical script locations:

| Area | Files | Role |
| :--- | ---: | :--- |
| `scripts/launch` | 3 | dashboard launchers |
| `scripts/ops` | 10 | scheduled-task registration |
| root `scripts/*` | 10 | compatibility shims to `launch/` and `ops/` |

Reusable tools:

| Path | Lines | Role |
| :--- | ---: | :--- |
| `tools/backfill_all.py` | 140 | backfill helper |
| `tools/generate_market_specs_from_locations.py` | 45 | market spec generator |
| `tools/train_all_markets.ps1` | n/a | training helper |
| `tools/research/input_variable_significance.py` | 1,303 | substantial research CLI |
| `tools/research/research_harness.py` | 260 | retired/live research script harness |

Several `tools/research/test_*.py` files are retired live probes. They are not
collected by pytest because `pytest.ini` restricts collection to `tests`, but
their names still look like tests to humans and simple tooling.

## Documentation Map

| Area | Role | Structure note |
| :--- | :--- | :--- |
| `docs/operations` | durable runbooks, policies, package maps | strong owner documentation |
| `docs/research` | dated research audits and plans | useful history, mixed freshness |
| `docs/roadmap` | roadmap index, generated active backlog, tracks, items | now a semi-structured planning database |
| `docs/roadmap/items` | 217 numbered item files | should keep generated index/backlog as source-of-navigation |

`docs/roadmap/active-backlog.md` reports 217 items, 35 active, 7 open, 28
partial, and 182 complete. The roadmap item set is large enough that generated
indexes and linting should remain mandatory.

## Import Boundary Map

The package-boundary ratchet is documented in
`docs/operations/package-boundaries.md` and enforced by
`tests/operations/test_import_architecture.py`.

Observed cross-owner import edges include:

| Edge | Files |
| :--- | ---: |
| `reporting -> backtesting` | 15 |
| `reporting -> market` | 15 |
| `operations -> market` | 10 |
| `operations -> reporting` | 9 |
| `sources -> market` | 9 |
| `backtesting -> market` | 8 |
| `calibration -> model` | 8 |
| `collection -> market` | 8 |
| `calibration -> market` | 7 |
| `model -> sources` | 6 |
| `calibration -> backtesting` | 6 |
| `calibration -> reporting` | 5 |
| `operations -> backtesting` | 5 |

Some of these are allowed stable edges; some are explicitly transitional. The
ratchet is valuable because it prevents new accidental edges, but the current
edge counts show where the next extractions should happen.

## What Is Already Working Well

- The canonical `src/weather` package exists and is used by README, CI,
  launchers, scheduled-task scripts, and tests.
- `weather.paths` and `weather.artifacts` centralize path policy and artifact
  lookup.
- `data/` is ignored, while deterministic test fixtures live under
  `tests/fixtures`.
- Binary model artifacts are under `artifacts/models/hgb` and covered by Git
  LFS attributes.
- The app is no longer a single root `app.py`; it has a router and view modules.
- Architecture tests enforce import hygiene, shim caller policy, path policy,
  tracked critical files, package edges, model/calibration separation, and
  compatibility-facade direction.
- `docs/operations` has useful living policy docs for paths, artifacts,
  configs, package boundaries, and module ownership.

## Suggested Refactor Items

### P0 - Keep The Structure Ratchet Green

1. **Track or intentionally classify current critical untracked files.**
   - Evidence: the targeted architecture test fails only on untracked
     source/test files.
   - First move: stage or explicitly ignore/classify
     `snapshot_cadence_quality.py`, `frozen_baseline_replay_trend.py`, and
     their tests once their current work is ready.
   - Acceptance: `python -m pytest tests/operations/test_import_architecture.py
     -q` passes.

2. **Assign the July 18 compatibility-shim removal owner now.**
   - Evidence: item 206 is open; 86 flat `src/*.py` wrappers plus root helper,
     app, and script shims still exist.
   - First move: create the post-2026-07-18 removal checklist as an active
     owner task, with batches by shim class.
   - Acceptance: after 2026-07-18, every shim class is either removed or
     retained with a concrete external dependency and next review date.

3. **Add a generated structure inventory command.**
   - Evidence: this audit required multiple ad hoc file/line/count scans.
   - First move: extend `weather.operations.module_size_audit` or add
     `weather.operations.structure_inventory` to emit package/file counts,
     line counts, large modules, shim counts, artifact sizes, and data sizes.
   - Acceptance: one command regenerates the high-signal tables in this audit.

### P1 - Reduce Growth Pressure In Source Packages

4. **Split modules over the 2,000-line warning threshold first.**
   - Targets: `weather.calibration.pooled_candidate_replay` and
     `weather.reporting.data_layer_audit`.
   - First move: extract CLI/rendering/persistence slices behind existing
     public module facades.
   - Acceptance: each target drops below 1,500 lines and extracted modules do
     not import the facade.

5. **Create subpackages inside `weather.reporting`.**
   - Evidence: `weather.reporting` has 85 files and about 51,900 lines.
   - Suggested split:
     - `weather.reporting.observability`
     - `weather.reporting.validation`
     - `weather.reporting.promotion`
     - `weather.reporting.roadmap`
     - `weather.reporting.trading`
   - Acceptance: imports still expose stable public facades, but new modules
     land under a reporting subdomain instead of the flat reporting directory.

6. **Reduce transitional package edges by extracting shared contracts.**
   - Targets:
     - `reporting -> market`
     - `reporting -> backtesting`
     - `operations -> reporting`
     - `collection -> market`
     - `sources -> model`
   - First move: move pure dataclasses, row schemas, scoring primitives, and
     report table helpers into owner-neutral shared modules only when they are
     actually shared.
   - Acceptance: remove at least three transitional edges from
     `TRANSITIONAL_PACKAGE_EDGES` and the package-boundary doc.

7. **Separate provider clients from serving source adaptation.**
   - Evidence: `weather.model.model_sources` is 1,869 lines and `sources ->
     model` remains a transitional edge.
   - First move: move raw provider fetch/parsing clients to `weather.sources`;
     keep serving-time blend/adaptation logic in `weather.model`.
   - Acceptance: `weather.sources` no longer imports `weather.model`.

8. **Split app views by data loading and rendering.**
   - Targets: `app/views/single_market.py` and `app/views/market_making.py`.
   - First move: create local view-model helpers or `app/data_loaders.py` for
     cached data access, keeping Streamlit calls in view modules.
   - Acceptance: view files shrink and tests can cover view-model assembly
     without starting Streamlit.

### P2 - Improve Operational And Documentation Structure

9. **Separate durable config from generated config.**
   - Evidence: `config/location_market_events.json` is generated/stale after 7
     days but lives beside hand-authored durable registries.
   - First move: move generated config snapshots under `config/generated/` or
     document a stricter naming convention.
   - Acceptance: `config_inventory` reports durable vs generated config without
     relying only on prose.

10. **Move very large ignored runtime stores out of the repo root or add a
    stronger local retention command.**
    - Evidence: ignored `data/tape_backups` and `data/snapshots` together are
      about 149 GiB.
    - First move: make the existing retention/tiering tools report total
      ignored-state size by area and recommend external roots for backups.
    - Acceptance: routine source scans avoid `data/`, and local disk-budget
      warnings trigger before operational runs fail.

11. **Normalize `tools/research`.**
    - Evidence: many retired live probes are named `test_*.py`; one research
      CLI is 1,303 lines.
    - First move: rename retired live probes away from `test_*.py` or place
      them under `tools/research/retired/`; split
      `input_variable_significance.py` if it remains active.
    - Acceptance: no research helper looks like a pytest test unless it belongs
      under `tests`.

12. **Choose one dependency source of truth.**
    - Evidence: dependency pins are duplicated in `requirements.txt` and
      `pyproject.toml`.
    - First move: add a small check that compares both lists, or move pins into
      one file and generate/derive the other.
    - Acceptance: dependency drift fails a focused test or audit command.

13. **Add roadmap item front matter or a generated item index artifact.**
    - Evidence: 217 item files act like a database, and `active-backlog.md` is
      generated.
    - First move: standardize machine-readable fields for item id, status,
      date, owner, and disposition.
    - Acceptance: roadmap lint can parse status without relying on fragile
      heading conventions.

14. **Refresh stale module docstrings after extraction.**
    - Evidence: several split modules still carry inherited or generic
      "Implementation slice extracted..." docstrings.
    - First move: update docstrings as modules are touched for real work.
    - Acceptance: package inventory output can use docstrings as reliable
      one-line file summaries.

15. **Keep the repo-root import shim on a retirement watchlist.**
    - Evidence: `weather/__init__.py` and `sitecustomize.py` are local Windows
      safeguards, but they are also alternate import mechanics.
    - First move: document the exact scheduled-worker condition that still
      needs them.
    - Acceptance: if editable installs and Task Scheduler working directories
      make them redundant, retire them after a scheduled-worker smoke check.

## Suggested Target Shape As The Project Grows

The current top-level layout is basically right. The next target should be a
deeper source package, not another top-level move:

```text
src/weather/
  artifacts.py
  paths.py
  schema_registry.py
  scoring/
  sources/
  model/
  calibration/
  collection/
  backtesting/
  market/
  operations/
  reporting/
    observability/
    validation/
    promotion/
    roadmap/
    trading/
```

Keep root compatibility shims only through the documented migration window.
Keep `data/` ignored. Keep model binaries in `artifacts/` with LFS or an
external artifact manifest. Let `docs/roadmap/items` remain the durable roadmap
history, but keep generated indexes/lints as the primary navigation surface.

