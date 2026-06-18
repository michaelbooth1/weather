# 94. Internal Compatibility Fallback Retirement [COMPLETE 2026-06-16 - INTERNAL FALLBACKS RETIRED]

Goal: remove package-internal fallback imports now that `weather.*` is the
canonical runtime interface.

Source: 2026-06-16 architecture review. The documented `src/*.py` wrappers are
thin compatibility shims, but several `weather.*` modules still contain
`try/except ImportError` branches for direct source execution or wrapper-era
imports.

Why this is missing: the package migration preserved direct-module execution
while commands, tests, scripts, and app imports were being moved. That was
useful during migration, but leaving fallback imports in package code can hide
real import errors and makes ownership boundaries noisier.

- [x] Confirm README commands, scheduled-task scripts, GitHub Actions, app code,
  tests, and first-party tools all use canonical `python -m weather...` module
  paths for one migration window.
- [x] Keep the flat `src/*.py` wrapper inventory as the only supported legacy
  import/CLI compatibility surface during the retirement window.
- [x] Remove package-internal `except ImportError` fallback import branches from
  `weather.collection`, `weather.market`, `weather.operations`, `weather.reporting`,
  and calibration modules.
- [x] Add an import-architecture guard that rejects new package-internal
  compatibility fallback imports except in explicitly named wrapper modules.
- [x] Run representative canonical CLI smoke checks from a clean working
  directory and from a non-repo current working directory.

Acceptance: package modules use normal package imports only, true import
regressions fail loudly, and legacy compatibility is isolated to the documented
flat wrappers.

## Design

Compatibility should be explicit and easy to delete.

- The only compatibility layer should be the wrapper file that delegates to the
  canonical owner.
- Runtime modules should not try to support being executed by filesystem path.
  Supported execution should be `python -m weather.package.module` or a future
  console script.
- Architecture tests should scan `src/weather`, not just app and tests, for
  fallback comments and `except ImportError` branches used as compatibility
  imports.

Verification strategy:

- `tests/operations/test_import_architecture.py`.
- Canonical CLI smoke checks for collection, market, operations, reporting, and
  calibration entrypoints.
- Full suite after fallback removal.

## Completion

Completed 2026-06-16.

- Removed package-internal compatibility import fallbacks from collection,
  market, calibration, and reporting modules. These modules now import through
  canonical `weather.*` package paths.
- Left true optional dependency handling in place for explicitly allowed
  modules: `weather.market.market_microstructure_capture` handles optional
  `websocket`, and `weather.sources.historical_coverage` handles optional
  parquet support.
- Added an import-architecture guard that scans `src/weather` for wrapper-era
  fallback markers and rejects unapproved `except ImportError` handlers.
- Confirmed active first-party surfaces no longer call `src.*` modules directly;
  the flat `src/*.py` files remain the documented legacy compatibility wrappers.

Verification:

- `rg` scan of `src/weather` shows only the two approved optional dependency
  `except ImportError` handlers.
- `rg` scan of README, GitHub Actions, scripts, tools, app code, and tests found
  no active `python -m src.*`, `from src.*`, or `import src.*` callers.
- Repo-root CLI smokes passed for collection health, snapshot tracker status,
  market microstructure status, daily refresh help, data-layer audit help, and
  pooled candidate replay help.
- Non-repo cwd CLI smokes passed for collection health, market microstructure,
  daily refresh, data-layer audit, and pooled candidate replay package entry
  points.
- `.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py tests\collection\test_collection_robustness.py tests\collection\test_forecast_tracker.py tests\market\test_market_microstructure.py tests\market\test_market_making_run.py tests\market\test_mm_paper.py tests\market\test_mm_exchange.py tests\calibration\test_pooled_candidate_replay.py tests\reporting\test_data_layer_audit.py -q`
  (139 passed)
- `.\venv\Scripts\python.exe -m pytest -q` (806 passed, 491 subtests passed)
