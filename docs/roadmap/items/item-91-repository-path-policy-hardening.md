# 91. Repository Path Policy Hardening [COMPLETE 2026-06-16 - REPO-ABSOLUTE DEFAULT PATHS LIVE]

Goal: make runtime, config, artifact, and report paths independent of the
current working directory.

Source: 2026-06-16 architecture review. `weather.paths` already centralizes
repository roots, but many production-facing modules still define defaults with
cwd-relative `Path("data")`, `Path("config")`, or `Path("docs")` expressions.

Why this is missing: scheduled tasks currently set the working directory to the
repo root, so the relative defaults usually work. They remain fragile for
package execution, direct module imports, tests launched from a different cwd,
and future deployment outside this single local checkout.

- [x] Replace module-level cwd-relative defaults with helpers from
  `weather.paths`, such as `data_path()`, `artifacts_path()`, `CONFIG_ROOT`, and
  `DOCS_ROOT`.
- [x] Preserve CLI arguments that accept explicit paths, but normalize defaults
  to repository-absolute paths.
- [x] Add tests for representative commands running from a temporary working
  directory while reading/writing the intended repo paths.
- [x] Document the path policy: repo-owned durable artifacts under `artifacts/`,
  config under `config/`, docs under `docs/`, and runtime/cache/report state
  under `data/`.
- [x] Audit app views and tools for local parent traversal or cwd assumptions
  and move them to the same path helpers.

Acceptance: documented commands, app views, tests, and scheduled-task helpers
resolve default paths correctly regardless of process cwd, and new code has a
single documented path policy to follow.

## Design

Path ownership:

- `weather.paths` remains the single owner for repository roots:
  `REPO_ROOT`, `DATA_ROOT`, `ARTIFACTS_ROOT`, `CONFIG_ROOT`, `DOCS_ROOT`, and
  helper constructors such as `data_path()` and `artifacts_path()`.
- Add `config_path()` and `docs_path()` so callers do not have to compose
  `CONFIG_ROOT / ...` or `DOCS_ROOT / ...` manually.
- Durable repo-owned paths should be absolute at module-default time. Explicit
  CLI arguments may still be relative, but defaults should not depend on the
  process working directory.

Conversion rules:

- Replace module-level `Path("data") / ...` defaults in `src/weather` with
  `data_path() / ...`.
- Replace module-level `Path("config") / ...` defaults with `config_path()` or
  `CONFIG_ROOT / ...`.
- Replace module-level `Path("docs") / ...` defaults with `docs_path()` or
  `DOCS_ROOT / ...`.
- Keep user-provided path arguments as `Path(value)` so explicit relative paths
  continue to mean "relative to the caller's cwd".
- Update app views and tools that discover the repo via parent traversal to use
  `weather.paths` instead.

Guardrails:

- Extend the import architecture tests with a path-policy ratchet over
  production modules, app views, and tools. The guard should reject new
  module-level `Path("data")`, `Path("config")`, or `Path("docs")`
  expressions outside `weather.paths`.
- Add representative cwd-independence tests for scheduled/CLI surfaces and app
  helpers: default paths should still point inside the repository after a test
  changes into a temporary directory.

Documentation:

- Add `docs/operations/path-policy.md` covering the durable path convention:
  artifacts under `artifacts/`, configuration under `config/`, docs under
  `docs/`, and runtime/cache/report state under `data/`.

## Completion

Completed 2026-06-16.

- Added `config_path()` and `docs_path()` to `weather.paths`.
- Replaced production-facing `Path("data")`, `Path("config")`, and
  `Path("docs")` defaults across `src/weather`, app views, and tools with
  repository-absolute `weather.paths` helpers.
- Converted app/tool parent traversal in the Streamlit market-making view and
  market-spec generator to use `weather.paths`.
- Preserved explicit caller-supplied path semantics by continuing to wrap
  function and CLI arguments with `Path(value)`.
- Added `docs/operations/path-policy.md`.
- Added `tests/operations/test_path_policy.py` and extended the architecture
  guard to reject new repo-owned cwd-relative defaults.

Verification:

- `.\venv\Scripts\python.exe -m pytest tests\operations\test_path_policy.py tests\operations\test_import_architecture.py -q` (10 passed)
- Focused regression slice for updated tests: 12 passed.
- `.\venv\Scripts\python.exe -m pytest` (797 passed)

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - REPO-ABSOLUTE DEFAULT PATHS LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

