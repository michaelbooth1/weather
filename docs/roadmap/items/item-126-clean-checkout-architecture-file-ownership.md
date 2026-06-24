# 126. Clean-Checkout Architecture File Ownership [COMPLETE 2026-06-20 - CLEAN-CHECKOUT AND PACKAGE RATCHET PASS]

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
- [x] Verify a clean checkout can run the architecture and path-policy tests
  without hidden local files.
- [x] Track, move, or ignore the current project-critical untracked source,
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

## 2026-06-20 closure

The current clean-checkout guard has no untracked project-critical offenders.
The earlier untracked taker/reporting source files are tracked, and the new
shared `weather.variant_registry` module is staged as tracked source so
collection callers no longer depend directly on `weather.reporting`.

The remaining architecture drift found by the focused guard was also repaired:

- `weather.model.model_sources` now uses shared writer-lock helpers from
  `weather.io` instead of importing `weather.operations.supervisor`.
- `weather.collection.collection_health` and
  `weather.collection.live_variant_predictions` use shared variant-registry
  helpers.
- Package-boundary documentation and the ratchet include
  `weather.variant_registry` as a shared utility surface.
- Optional dependency checks in
  `winner_band_signal_validation` and `reanalysis_synoptic` now catch the
  narrower `ModuleNotFoundError`, avoiding broad internal compatibility
  fallback handlers.

Verification:

- `git ls-files --others --exclude-standard -- src/weather tests app scripts/ops docs/operations tools`
  returned no rows.
- `git ls-files --stage src/weather/variant_registry.py` returned the staged
  source blob for the new shared module.
- `python -m pytest -q tests\operations\test_import_architecture.py tests\operations\test_path_policy.py tests\model\test_source_cache_ttl.py tests\collection\test_live_variant_predictions.py`
  passed with 49 tests.
- `python -m pytest -q tests\operations\test_runtime_utilities.py tests\collection\test_collection_robustness.py tests\reporting\test_fleet_observability.py`
  passed with 60 tests.
- `python -m pytest -q tests\market\test_market_microstructure.py tests\operations\test_observation_trigger.py tests\operations\test_loop_jsonl_repair.py`
  passed with 56 tests.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - CLEAN-CHECKOUT AND PACKAGE RATCHET PASS`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

