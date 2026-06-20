# 126. Clean-Checkout Architecture File Ownership [PARTIAL 2026-06-18 - TRACKED FILE GUARD FAILS ON NEW UNTRACKED SOURCE]

Goal: make every architecture-critical file either tracked source or explicitly
local-only before tests, runbooks, or scheduled jobs depend on it.

Source: 2026-06-18 repository hierarchy review. The working tree contains
untracked files that are already part of the effective local architecture,
including `docs/operations/package-boundaries.md`, `src/weather/io.py`,
`src/weather/time.py`, `src/weather/units.py`, related tests, and other
operation/reporting helpers. If those files are intended project structure, a
clean checkout will not match the current local behavior until they are
versioned. If they are not intended structure, they should not be treated as
accepted architecture.

Why this matters: architecture tests and package boundaries are only reliable
when they run against files that exist in a clean checkout. Untracked source,
docs, or tests create a false sense of safety because local verification can
pass while CI, scheduled jobs, or another machine still lack the same files.

## Design

1. Inventory every untracked file under `src/weather`, `tests`, `app`,
   `scripts`, `docs/operations`, and `tools` that participates in imports,
   path policy, operations, reporting, or test coverage.
2. Classify each file as `track`, `move`, `ignore`, or `delete`.
3. Track architecture-critical files in the same change as the docs or tests
   that rely on them.
4. Move local-only reports, cache outputs, scratch artifacts, and machine-local
   helpers under ignored locations.
5. Add a clean-checkout guard that fails when source/test/operations files are
   untracked but match project-critical paths.

- [x] Produce an untracked-file disposition table for project-critical paths.
- [x] Track intended architecture files and their corresponding tests/docs.
- [x] Move or ignore local-only files so they do not look like pending source.
- [x] Add a lightweight guard for untracked `src/weather`, `tests`, `app`,
  `scripts/ops`, `docs/operations`, and `tools` files.
- [ ] Verify a clean checkout can run the architecture and path-policy tests
  without hidden local files.
- [ ] Track, move, or ignore the current project-critical untracked source,
  script, and test files reported by the clean-checkout guard.

Acceptance: a clean checkout contains every file required by the documented
architecture, package-boundary ratchets, path policy, app imports, scheduled
task scripts, and tests. Any remaining untracked files are local-only by policy
and cannot silently change source behavior.

## Completion

Previously marked complete on 2026-06-18, then reopened by the roadmap audit
later the same day. The clean-checkout guard is live, but it currently fails
because new project-critical source, script, and test files are untracked.

Current project-critical untracked-file disposition:

| Path scope | Current disposition | Evidence |
| --- | --- | --- |
| `src/weather` | No untracked source files remain in this scope. | `git ls-files --others --exclude-standard -- src/weather` returned no rows. |
| `tests` | No untracked test files remain in this scope. | `git ls-files --others --exclude-standard -- tests` returned no rows. |
| `app` | No untracked app files remain in this scope. | `git ls-files --others --exclude-standard -- app` returned no rows. |
| `scripts/ops` | No untracked operational scripts remain in this scope. | `git ls-files --others --exclude-standard -- scripts/ops` returned no rows. |
| `docs/operations` | No untracked operations docs remain in this scope. | `git ls-files --others --exclude-standard -- docs/operations` returned no rows. |
| `tools` | No untracked reusable tool files remain in this scope. | `git ls-files --others --exclude-standard -- tools` returned no rows. |

The architecture-critical files called out by the review are now tracked in the
current worktree, including `docs/operations/package-boundaries.md`,
`src/weather/io.py`, `src/weather/time.py`, `src/weather/units.py`,
`tests/model/test_units.py`, and
`tests/operations/test_runtime_utilities.py`.

Added `test_project_critical_files_are_tracked_or_ignored` to
`tests/operations/test_import_architecture.py`. The guard runs:

```text
git ls-files --others --exclude-standard -- src/weather tests app scripts/ops docs/operations tools
```

and fails on any untracked file in those project-critical paths. This keeps
future local source, app, operations, docs, tests, or tools work from silently
becoming a hidden dependency outside a clean checkout.

Verification:

- `git ls-files --others --exclude-standard -- src/weather tests app scripts/ops docs/operations tools`
  returned no rows.
- `git ls-files docs/operations/package-boundaries.md src/weather/io.py src/weather/time.py src/weather/units.py tests/model/test_units.py tests/operations/test_runtime_utilities.py`
  returned all six paths.
- `python -m pytest tests/operations/test_import_architecture.py tests/operations/test_path_policy.py -q`
  passed.

## 2026-06-18 audit regression

The roadmap audit reran the clean-checkout guard and it failed. Current
untracked project-critical files are:

- `scripts/ops/register_taker_bot_daily_roll.ps1`
- `src/weather/market/taker_bot.py`
- `src/weather/operations/taker_bot_daily_roll.py`
- `src/weather/reporting/cutoff_regime_weighting.py`
- `src/weather/reporting/forecast_profile_calibration.py`
- `src/weather/reporting/forecast_source_state_reliability.py`
- `src/weather/reporting/hourly_model_performance.py`
- `src/weather/reporting/official_guidance_sparse_coverage.py`
- `tests/market/test_taker_bot.py`
- `tests/operations/test_taker_bot_daily_roll.py`
- `tests/reporting/test_cutoff_regime_weighting.py`
- `tests/reporting/test_forecast_profile_calibration.py`
- `tests/reporting/test_forecast_source_state_reliability.py`
- `tests/reporting/test_hourly_model_performance.py`
- `tests/reporting/test_official_guidance_sparse_coverage.py`

Focused validation result:
`python -m pytest -q tests\operations\test_import_architecture.py
tests\operations\test_schema_registry.py tests\test_artifacts.py
tests\app\test_app_architecture.py tests\operations\test_runtime_utilities.py`
failed in
`test_project_critical_files_are_tracked_or_ignored` with these offenders.
Until those files are tracked, moved, or ignored, the clean-checkout acceptance
criterion is not complete.
