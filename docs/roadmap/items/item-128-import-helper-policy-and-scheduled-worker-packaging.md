# 128. Import Helper Policy And Scheduled Worker Packaging [COMPLETE 2026-06-18 - IMPORT POLICY DOCUMENTED]

Goal: decide whether repo-root import helpers are supported runtime
infrastructure or temporary local scaffolding, then make the import model
consistent for scheduled workers.

Source: 2026-06-18 repository hierarchy review. `sitecustomize.py` and the
repo-root `weather/__init__.py` alter import/path behavior outside the normal
editable-install path. They may be useful for Windows Task Scheduler workers,
but they also bypass the cleaner `pip install -e .` plus canonical
`weather.*` model if they remain undocumented or untracked.

Why this matters: import helpers are high-leverage files. If required, they
must be tracked, tested, and documented because scheduled workers depend on
them. If not required, they should be removed so all entrypoints use the same
package installation contract.

## Design

1. Identify every production and scheduled-worker scenario that imports
   `weather.*` without an editable install or without `src` on `PYTHONPATH`.
2. Decide one supported model:
   tracked repo-root helpers for local Windows workers, or no repo-root helpers
   and a strict editable-install requirement.
3. If helpers remain, document their purpose, allowed behavior, and tests.
4. If helpers are removed, update scheduled-task registration and runbooks to
   enforce package installation before launch.
5. Add regression coverage for the chosen import behavior from a clean
   subprocess and from a non-repo current working directory.

- [x] Audit scheduled tasks, launchers, CI, and manual runbooks for import
  assumptions.
- [x] Choose and document the supported import helper policy.
- [x] Track and test required helpers, or remove local-only helpers and rely on
  editable install.
- [x] Verify `python -m weather...` works from a non-repo current working
  directory in the supported operator setup.
- [x] Ensure the runtime identity/stale-code guard matches the chosen import
  model.

Acceptance: the repo has one documented import model for app code, tests,
manual commands, CI, and Windows scheduled workers. Any helper that mutates
import behavior is tracked, justified, and tested, or it is absent.

## Completion

Completed 2026-06-18.

Supported import model:

- Primary contract: install the source-layout package in the repo venv with
  `python -m pip install -e .`, then run canonical `python -m weather...`
  commands.
- Non-repo current working directories are supported when the package is
  available through the editable install or an explicit package path such as
  `PYTHONPATH=<repo>\src`.
- `sitecustomize.py` and repo-root `weather/__init__.py` remain tracked
  Windows scheduled-worker safeguards for processes started from the repository
  root by Task Scheduler.
- The helpers are not a replacement for setup and should not be treated as a
  second public import surface.

Documentation:

- Added the policy to `docs/operations/path-policy.md`.
- Confirmed scheduled-task scripts use the repo venv's `pythonw.exe` and set
  `-WorkingDirectory $RepoRoot`.
- README and active operations docs use canonical `weather.*` module commands.

Implementation:

- Added runtime tests that verify `sitecustomize.py` and `weather/__init__.py`
  are tracked.
- Added subprocess coverage for repo-root helper imports with `PYTHONPATH`
  removed.
- Added subprocess coverage for non-repo imports with the explicit package
  path set.
- Added `sitecustomize.py` and `weather/**/*.py` to the runtime identity source
  fingerprint so stale-code detection includes the import helpers.

Verification:

- `python -m pytest tests\operations\test_runtime_utilities.py tests\operations\test_runtime_identity.py tests\operations\test_import_architecture.py tests\operations\test_path_policy.py -q`
  passed.
- From `C:\Users\micha\AppData\Local\Temp`,
  `C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe -c "import weather.paths; print(weather.paths.REPO_ROOT)"`
  printed `C:\Users\micha\Desktop\github\weather`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - IMPORT POLICY DOCUMENTED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

