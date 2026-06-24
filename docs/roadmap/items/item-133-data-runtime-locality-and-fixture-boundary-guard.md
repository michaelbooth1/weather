# 133. Data Runtime Locality And Fixture Boundary Guard [COMPLETE 2026-06-18 - DATA BOUNDARY GUARD LIVE]

Goal: keep `data/` ignored and local while making durable artifacts and test
fixtures explicit, small, and reproducible.

Source: 2026-06-18 repository hierarchy review. The current policy is healthy:
runtime tapes, caches, reports, and provider payloads live under ignored
`data/`; durable model artifacts live under `artifacts/`; deterministic smoke
fixtures live under `tests/fixtures/`. Local `data/` is very large, so the
boundary needs active protection.

Why this matters: local runtime data is necessary for this project, but it
should not become implicit source of truth. Durable model state, reproducible
fixtures, and local tapes have different lifecycles and should not drift into
each other's directories.

## Design

1. Ratify the data policy in README and operations docs:
   `data/` is local runtime state, `artifacts/` is durable model state, and
   `tests/fixtures/` is small deterministic test data.
2. Add checks that prevent new tests from depending on local `data/` paths
   unless the test explicitly constructs a temporary fixture.
3. Keep generated reports under `data/backtest` local unless promoted to
   `docs/` or `artifacts/` by an explicit decision.
4. Ensure `.gitignore`, CI, nightly retrain, and artifact publishing all align
   with the same policy.
5. Document when a local runtime output should graduate into an artifact,
   fixture, or docs report.

- [x] Confirm `.gitignore`, README, CI, and runbooks all state the same data
  policy.
- [x] Add or extend tests that prevent accidental direct dependence on local
  `data/` in unit tests.
- [x] Document promotion rules for runtime outputs.
- [x] Keep deterministic fixtures under `tests/fixtures/` and small enough for
  normal Git review.
- [x] Ensure nightly retrain commits artifacts, not local data caches.

Acceptance: `data/` remains ignored local runtime state, tests use explicit
fixtures or temporary directories, durable model outputs are promoted through
`artifacts/`, and current docs/CI do not imply that local data is required for
a clean checkout.

## Completion

Completed 2026-06-18.

Implementation:

- Updated `.gitignore` comments to use canonical `weather.*` commands while
  preserving the existing ignored `data/` and `scratch/` policy.
- Extended `docs/operations/path-policy.md` with runtime-output promotion
  rules:
  - durable trained model state and provenance move to `artifacts/`;
  - small deterministic test inputs move to `tests/fixtures/`;
  - historical human-readable reports move to `docs/`;
  - caches, provider payloads, live tapes, loop status, diagnostics, and
    regenerated reports stay under ignored `data/`.
- Added `test_tests_do_not_depend_on_repo_root_data_tree`, which flags direct
  `Path("data/...")` or `open("data/...")` usage in tests unless the test file
  clearly constructs a temporary fixture.
- Confirmed the GitHub retrain workflow commits `artifacts/` only after model
  training and artifact audits; it does not add local `data/` caches.

Verification:

- `python -m pytest tests\operations\test_import_architecture.py::test_tests_do_not_depend_on_repo_root_data_tree tests\operations\test_path_policy.py -q`
  passed.
- `git check-ignore -v data data\snapshots\demo.jsonl scratch\demo.txt`
  confirmed `data/` and `scratch/` are ignored.
- `git ls-files data` returned 0 tracked files.
- `git ls-files tests/fixtures` returned 5 tracked fixture files.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - DATA BOUNDARY GUARD LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

