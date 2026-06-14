# Codebase Organization Audit

Audited against the current worktree on 2026-06-14.

Implementation note: the refactor recommended here has since been applied in
this worktree. Source now lives under `src/weather/`, model artifacts under
`artifacts/`, app code under `app/`, long-form docs under `docs/`, reusable
helpers under `tools/`, and smoke fixture data under `tests/fixtures/`. The
older `src/*.py`, root helper, and script paths remain as compatibility shims.

## Scope

This audit focuses on file and folder hierarchy, packaging boundaries, generated
artifacts, runtime data, scripts, scratch files, and documentation placement.
It does not evaluate model accuracy or trading logic.

Evidence used:

- `git status --short`
- `git ls-files`
- `rg --files`
- `git check-ignore -v`
- extension and size counts under `src/`
- import/path searches for `sys.path.insert`, `Path("src")`, and workflow
  `git add` patterns

The worktree already has unrelated modified and untracked files. This document
does not depend on reverting those changes.

## Current Shape

Top-level tracked areas:

| Area | Tracked files | Notes |
| --- | ---: | --- |
| `src/` | 152 | Flat mix of Python modules, JSON artifacts, and pickle artifacts. |
| `tests/` | 54 | Unit tests, currently importing via `sys.path.insert`. |
| `scratch/` | 29 | Tracked ad-hoc scripts and smoke data, including `test_*.py` files. |
| root | 15 | App entrypoint, docs, helper scripts, generated inputs, and a log. |
| `scripts/` | 2 tracked, plus untracked launchers | Windows operational launch/supervisor scripts. |
| `.github/` | 1 | Nightly retrain workflow. |

`src/` contents by tracked extension:

| Extension | Tracked files | Interpretation |
| --- | ---: | --- |
| `.json` | 76 | Calibration/model manifests and generated artifacts. |
| `.py` | 61 | Application, model, collection, backtest, and CLI code. |
| `.pkl` | 15 | Pickled sklearn/HGB artifacts. |

Largest tracked model artifacts currently live under `src/`:

| File | Size |
| --- | ---: |
| `src/feature_model_hgb_f_pooled.pkl` | 98.93 MB |
| `src/feature_model_hgb.pkl` | 27.88 MB |
| `src/feature_model_hgb_denver.pkl` | 21.65 MB |
| `src/feature_model_hgb_seattle.pkl` | 18.88 MB |
| `src/feature_model_hgb_chicago.pkl` | 18.80 MB |

`data/` is ignored and untracked, but it is large in the working tree:

| Data area | Files |
| --- | ---: |
| `data/wunderground` | 73910 |
| `data/reanalysis` | 3325 |
| `data/noaa_ghcnh` | 1848 |
| `data/snapshots` | 1241 |
| `data/metar` | 1228 |
| `data/eccc` | 133 |
| `data/backtest` | 116 |
| `data/eccc_swob` | 60 |
| `data/forecast_history` | 24 |
| `data/settlements` | 13 |
| `data/logs` | 2 |

## Main Findings

### 1. `src/` Is Not A Source-Only Directory

`src/` contains executable modules and generated artifacts side by side. This
hurts navigation, makes package boundaries hard to see, and encourages code to
address artifacts as sibling files.

Examples:

- `src/toronto_model.py` loads artifacts from `Path(__file__).parent`.
- `src/feature_model.py` writes `feature_model_coefs*.json`,
  `feature_model_hgb*.pkl`, and `late_day_model_coefs*.json` into `src`.
- `src/intraday_calibration.py` writes `calibrated_weights*.json` into `src`.
- `src/probability_calibration.py`, `src/forecast_error_model.py`,
  `src/settlement_lag_model.py`, and `src/family_secondary_artifacts.py`
  default artifacts to `src/`.
- `src/model_identity.py` and `src/fleet_observability.py` fingerprint artifacts
  from `src/`.

Impact: moving artifacts is not just a file move. It needs a shared artifact
path abstraction so training, serving, identity, provenance, and tests agree.

### 2. Imports Depend On `sys.path.insert`

The app, many source modules, and nearly every test add `src` to `sys.path` and
then import bare module names. The repository has no `pyproject.toml`, no
`setup.cfg`, no `setup.py`, and no `src/__init__.py`.

Impact: subpackages will be noisy and risky until import mechanics are made
explicit. The current flat layout is partly a consequence of the import model.

### 3. `data/` Policy Contradicts Documentation And CI

`.gitignore` ignores all of `data/`, and `git ls-files data` returns zero.
However:

- `README.md` says raw provider payloads are ignored while normalized hourly and
  daily artifacts are tracked.
- `.github/workflows/retrain.yml` runs `git add ... data/wunderground/*`.
- `git check-ignore -v` confirms normalized-looking paths such as
  `data/wunderground/cyyz/daily/daily_summary.csv` are ignored by `data/`.

Impact: the repo has an unclear source-of-truth policy. CI may regenerate files
it cannot commit without force-add behavior or ignore exceptions.

### 4. `scratch/` Is Tracked As Normal Project Content

`scratch/` contains 29 tracked files, including ad-hoc scripts, live tests, and
smoke data. `pytest.ini` explicitly avoids collecting scratch tests:

```ini
testpaths = tests
```

Impact: `scratch/` is being used as semi-permanent research history, local
workspace, and fixture storage at the same time.

### 5. Root Directory Mixes Too Many Roles

The root currently contains:

- app entrypoint: `app.py`
- operational helpers: `backfill_all.py`, `train_all_markets.ps1`
- docs: `README.md`, `ROADMAP.md`, `AGENT_CONTEXT.md`,
  `MARKET_MAKING_PLAN.md`, `HISTORY_DATA_DESIGN.md`,
  `OPERATIONS_DESIGN.md`
- generated/research inputs: `locations.json`, `scratch.py`
- log output: `atlanta.log`

Impact: important entrypoints are hard to distinguish from generated material,
long-form planning docs, and disposable files.

### 6. `app.py` Is A Large Streamlit Surface

`app.py` is roughly 35 KB and combines app setup, operations controls,
dashboard rendering, cached data access, formatting helpers, and live views.

Impact: moving the app into an `app/` package should be paired with splitting
view code, not just renaming the file.

## Recommended Target Hierarchy

Target structure:

```text
weather/
  app/
    streamlit_app.py
    views/
      dashboard.py
      operations.py
      overview.py
  src/
    weather/
      __init__.py
      paths.py
      artifacts.py
      model/
      market/
      sources/
      collection/
      calibration/
      backtesting/
      reporting/
      operations/
  artifacts/
    models/
      hgb/
      coefs/
    calibration/
    manifests/
  data/
    runtime-and-local-data-only
  docs/
    operations/
    research/
    roadmap/
  scripts/
    ops/
    launch/
  tools/
    backfill_all.py
    train_all_markets.ps1
  tests/
    model/
    market/
    sources/
    collection/
    backtesting/
    fixtures/
  scratch/
    local-only-and-ignored
```

This is the durable end state. The migration should be staged so currently
documented commands keep working during the transition.

## Proposed Package Map

Use existing filename prefixes as the first package boundary. That keeps the
move understandable and reduces arbitrary taxonomy decisions.

| Target package | Current files |
| --- | --- |
| `weather.model` | `toronto_model.py`, `model_base.py`, `model_climatology.py`, `model_constants.py`, `model_distribution.py`, `model_features.py`, `model_presentation.py`, `model_sources.py`, `model_identity.py`, `feature_store.py` |
| `weather.calibration` | `feature_model.py`, `intraday_calibration.py`, `pooled_feature_model.py`, `pooled_candidate_replay.py`, `probability_calibration.py`, `forecast_error_model.py`, `settlement_lag_model.py`, `family_secondary_artifacts.py`, `model_ensemble.py` |
| `weather.market` | `market_config.py`, `market_registry.py`, `market_day_labels.py`, `market_microstructure.py`, `polymarket_client.py` |
| `weather.sources` | `wu_history.py`, `eccc_history.py`, `eccc_swob_history.py`, `metar_history.py`, `noaa_ghcnh_history.py`, `reanalysis_history.py`, `forecast_history.py`, `daily_summary.py`, `historical_schema.py`, `historical_coverage.py` |
| `weather.collection` | `snapshot_tracker.py`, `forecast_tracker.py`, `collection_health.py`, `data_ingestion.py`, `historical_backfill_plan.py`, `historical_backfill_runner.py` |
| `weather.backtesting` | `backtest.py`, `replay.py`, `replay_ablation.py`, `replay_backtest.py`, `snapshot_analytics.py`, `settled_days.py`, `settlement_ledger.py` |
| `weather.reporting` | `data_auditor.py`, `data_layer_audit.py`, `source_redundancy.py`, `location_trust.py`, `fleet_observability.py`, `progress_audit.py`, `disagreement_casebook.py`, `promotion_corpus.py`, `promotion_gauntlet.py`, `promotion_refresh.py`, `overview_helpers.py` |
| `weather.operations` | `ops_monitor.py`, `runtime_identity.py` |

Some files can move twice: first into a broad package, then later split by
responsibility after imports and tests are stable.

## Migration Plan

### Phase 0: Freeze The Current Contract

Before moving files, record the public commands and paths that must keep
working:

- `python -m src.snapshot_tracker`
- `python -m src.market_microstructure`
- `python -m src.feature_model --all`
- `python src/feature_model.py`
- `python src/data_auditor.py`
- `streamlit run app.py`
- Windows scheduled task scripts under `scripts/`
- GitHub Action retrain commands

Add focused smoke tests for the command entrypoints or document intentional
breakage before changing them.

### Phase 1: Add Central Path Helpers

Add one source module for repository paths and one for artifact paths before
moving files.

Suggested modules:

- `src/paths.py` or `src/weather/paths.py`
- `src/artifact_paths.py` or `src/weather/artifacts.py`

Responsibilities:

- repository root
- data root
- artifacts root
- per-market artifact suffix handling
- backwards-compatible lookup from old `src/` artifact paths while migration is
  in progress

Update these current hard-coded artifact readers/writers first:

- `src/toronto_model.py`
- `src/feature_model.py`
- `src/intraday_calibration.py`
- `src/probability_calibration.py`
- `src/forecast_error_model.py`
- `src/settlement_lag_model.py`
- `src/family_secondary_artifacts.py`
- `src/model_identity.py`
- `src/fleet_observability.py`
- `.github/workflows/retrain.yml`
- `README.md`

### Phase 2: Move Artifacts Out Of `src/`

Move generated model artifacts into `artifacts/` after path helpers are in use.

Suggested layout:

```text
artifacts/
  models/
    hgb/
      feature_model_hgb*.pkl
    coefs/
      feature_model_coefs*.json
      late_day_model_coefs*.json
  calibration/
    calibrated_weights*.json
    probability_calibration*.json
    forecast_error_model*.json
    settlement_lag_model*.json
  manifests/
    f_family_secondary_artifacts.json
```

Keep a compatibility read path for one release cycle:

1. Prefer `artifacts/...`.
2. Fall back to the old `src/...` path.
3. Emit provenance using the actual loaded path.
4. Remove fallback after CI and scheduled tasks are updated.

### Phase 3: Resolve `data/` Ownership

Choose one policy and make `.gitignore`, README, and CI match it.

Recommended policy:

- `data/` is local runtime/cache/output data and remains ignored.
- Small deterministic fixtures live under `tests/fixtures/`.
- Durable generated model artifacts live under `artifacts/`.
- Backtest/report outputs are either ignored runtime outputs or promoted to
  explicit docs/reports, not implicitly tracked under `data/backtest`.

If normalized weather data must be tracked, replace blanket `data/` ignore with
specific ignore rules such as:

```gitignore
data/**/raw/
data/**/loop_*.log
data/**/diagnostics*.jsonl
```

and add explicit allow rules for the exact normalized files. Do not keep the
current mixed policy.

### Phase 4: Package The Code

Add package metadata and move modules in batches.

Minimum package setup:

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "weather-market"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Preferred import direction:

- application and tests import `weather.*`
- modules use explicit package imports
- command wrappers keep old `python -m src.<module>` entrypoints working until
  documentation and scheduled tasks are migrated

Avoid a single giant import rewrite. Move one package group at a time and run
tests after each group.

### Phase 5: Split The Streamlit App

Move `app.py` into `app/streamlit_app.py` only after command wrappers are ready.

Suggested split:

- `app/streamlit_app.py`: Streamlit setup and page selection
- `app/views/operations.py`: current operations page code
- `app/views/dashboard.py`: live market dashboard
- `app/views/overview.py`: overview page
- `app/formatting.py`: UI formatting helpers if they are not domain logic

Maintain a root `app.py` shim temporarily:

```python
from app.streamlit_app import main

main()
```

This preserves `streamlit run app.py` while the README and launcher scripts are
updated.

### Phase 6: Clean Root, Scripts, Docs, And Scratch

Root target:

- keep `README.md`, `requirements.txt`, packaging config, `.gitignore`,
  `.gitattributes`, and minimal shims only
- move operational docs to `docs/operations/`
- move research docs to `docs/research/`
- move roadmap/history docs to `docs/roadmap/`
- move reusable helper CLIs to `tools/`
- move Windows launch/supervisor scripts under `scripts/launch/` and
  `scripts/ops/`
- remove `atlanta.log` from Git and add `*.log` or a narrower log ignore rule
- classify `locations.json` as either `config/locations.json`,
  `tests/fixtures/locations.json`, or generated ignored data
- delete or ignore `scratch.py`
- convert useful `scratch/` scripts into `tools/` or tests; ignore the rest

## Suggested First Pull Requests

1. **PR 1: Path policy only**
   - Add path/artifact helper modules.
   - Update artifact readers and writers to use helpers while preserving old
     paths.
   - Add tests for artifact path resolution.

2. **PR 2: Move artifacts**
   - Move `.json` and `.pkl` artifacts from `src/` to `artifacts/`.
   - Update README, requirements comment, workflow `git add`, model identity,
     and fleet observability.
   - Run model load tests and provenance tests.

3. **PR 3: Data policy**
   - Make `.gitignore`, README, and workflow agree.
   - Move committed smoke data from `scratch/` to `tests/fixtures/` if needed.

4. **PR 4: Packaging foundation**
   - Add `pyproject.toml`.
   - Add package imports or compatibility wrappers.
   - Remove repeated test-level `sys.path.insert` through pytest config.

5. **PR 5: Docs and root cleanup**
   - Move long-form docs under `docs/`.
   - Move helper scripts under `tools/` or `scripts/`.
   - Leave root shims for documented commands.

6. **PR 6+: Module package moves**
   - Move one group at a time: `model`, `market`, `sources`, `collection`,
     `calibration`, `backtesting`, `reporting`.
   - Keep compatibility wrappers until scheduled tasks, README, and workflow are
     fully migrated.

## Verification Checklist

Run these after each structural PR:

```powershell
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall src tests
.\venv\Scripts\python.exe -m src.snapshot_tracker --status
.\venv\Scripts\python.exe -m src.market_microstructure status
.\venv\Scripts\python.exe -m src.fleet_observability report --strict
```

For artifact moves, also verify:

```powershell
@'
import sys
sys.path.insert(0, "src")
from toronto_model import TorontoHighTempModel
from market_registry import all_specs
for spec in all_specs():
    model = TorontoHighTempModel(market_id=spec.id)
    print(spec.id, bool(model.calibrated_weights), model.get_model_version_string())
'@ | .\venv\Scripts\python.exe -
```

For the Streamlit move, verify:

```powershell
.\venv\Scripts\python.exe -m streamlit run app.py
```

## Do Not Start With These Moves

Avoid these as first steps:

- bulk-moving all `src/*.py` into subpackages before path helpers exist
- moving `.pkl` files without updating model identity and provenance
- changing `.gitignore data/` without deciding whether normalized data is source
  of truth
- deleting `scratch/` before classifying which files are useful tools or
  fixtures
- removing root `app.py` before launcher scripts and README are updated

The safest first change is to centralize paths, then move artifacts. That
unblocks most of the hierarchy cleanup while preserving current runtime
behavior.
