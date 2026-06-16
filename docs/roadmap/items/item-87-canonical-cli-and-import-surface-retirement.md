# 87. Canonical CLI And Import Surface Retirement [COMPLETE 2026-06-16 - CANONICAL PACKAGE SURFACE LIVE]

Goal: make `weather.*` the durable public runtime interface while keeping the
old `src.*` wrappers only as temporary compatibility shims.

Source: 2026-06-16 architecture review. The packaged source now lives under
`src/weather`, but the dashboard, tests, README, GitHub workflow, scheduled-task
scripts, and tools still depend on `python -m src.*`, root-level wrappers, or
manual `sys.path` mutation.

Why this is missing: the package migration successfully moved production code
under `weather.*`, but the compatibility layer remains part of normal runtime
and development. That makes the migration hard to complete, hides import
regressions from package-install scenarios, and leaves `pyproject.toml` out of
sync with documented commands.

- [x] Add canonical command entry points for the supported operator and research
  commands, either through `weather.*` module execution or `pyproject.toml`
  console scripts.
- [x] Update README, scheduled-task scripts, GitHub Actions, launchers, and
  reusable tools to call the canonical interface while preserving root
  compatibility wrappers for one migration window.
- [x] Move Streamlit app imports from top-level wrappers to `weather.*` package
  imports and remove app-level `sys.path.insert`.
- [x] Move tests to canonical package imports and replace per-file `sys.path`
  mutation with the existing pytest path configuration.
- [x] Extend the import architecture ratchet so app code and tests cannot
  reintroduce root-level internal imports or manual path mutation.
- [x] Add a deprecation inventory for remaining `src/*.py` wrappers, with owner,
  current caller, and removal condition.

Acceptance: a clean checkout can run documented commands through the canonical
package interface, app and tests do not mutate `sys.path`, and `src.*` wrappers
are documented as compatibility-only rather than the active public API.

## Design

Canonical runtime surface:

- The durable module-execution form is `python -m weather.<package>.<module>`.
  This uses the package that `pyproject.toml` actually installs from
  `src/weather`.
- The existing flat `src/*.py` files remain as wrappers for one migration
  window. They should not be used by app code, tests, documentation, scheduled
  tasks, or first-party tools after this item closes.
- No new behavior should be introduced while moving imports. This item is a
  boundary cleanup, not a model, trading, or data-path change.

Import policy:

- Production package code imports internal modules through `weather.*`.
- Streamlit app code imports domain logic through `weather.*`; the only
  non-package imports in app code should be standard-library, third-party, or
  `app.*` view imports.
- Tests rely on `pytest.ini` / editable install path configuration and import
  package modules directly. Per-file `sys.path.insert` is not allowed.
- First-party tools that still need repo-local execution use package imports
  and canonical module commands.

Compatibility wrapper policy:

- The wrapper owner is the target `weather.*` module.
- Current allowed callers are external/local legacy commands only.
- Removal condition is: README, scripts, CI, app, tests, and first-party tools
  all use the canonical interface for at least one clean migration window.
- The current wrapper inventory is tracked in
  `docs/roadmap/compatibility-shim-inventory.md`.

Verification strategy:

- Architecture tests scan `app/` and `tests/` for manual path mutation and
  legacy top-level internal imports.
- CLI smoke checks prove representative canonical commands import and expose
  help/status behavior.
- Focused app and import-architecture tests run before the item is marked
  complete.

## Completion

Completed 2026-06-16.

- README commands, scheduled-task scripts, GitHub Actions, reusable tools,
  Streamlit app imports, and tests now use the canonical `weather.*` package
  surface.
- The README and GitHub workflow install the package with `pip install -e .`
  so module execution matches the packaged source layout.
- `tests/operations/test_import_architecture.py` now guards `app/` and
  `tests/` against manual `sys.path` mutation and legacy top-level internal
  imports.
- `docs/roadmap/compatibility-shim-inventory.md` records the remaining flat
  wrappers as compatibility-only shims with owner and removal conditions.

Verification:

- `.\venv\Scripts\python.exe -m pip install -e .`
- `.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py -q`
- `.\venv\Scripts\python.exe -m pytest tests\app tests\operations\test_market_making_daily_roll.py tests\operations\test_nightly_retrain.py tests\market\test_market_microstructure.py -q`
- `.\venv\Scripts\python.exe -m pytest -q` (789 passed)
- Canonical CLI smoke checks for `weather.schema_registry`,
  `weather.market.market_microstructure`,
  `weather.operations.market_making_daily_roll`, and
  `weather.operations.nightly_retrain`.
