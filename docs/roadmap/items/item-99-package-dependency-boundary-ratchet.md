# 99. Package Dependency Boundary Ratchet [COMPLETE 2026-06-16 - PACKAGE EDGE RATCHET LIVE]

Goal: make package dependency direction explicit so shared domain code does not
accidentally live inside CLI/report/orchestration modules.

Source: 2026-06-16 architecture review. The package graph still has cycles such
as model-to-calibration runtime imports, market-to-backtesting settlement
imports, reporting-to-backtesting replay imports, and operations-to-reporting
daily orchestration imports. Some are legitimate today, but they make future
refactors harder to reason about.

Why this is missing: the repo recently moved from a flat module layout to a
package layout. Import guards now protect some known regressions, but there is
not yet a documented dependency-direction policy for the package as a whole.

- [x] Document intended dependency layers for `weather.sources`, `weather.model`,
  `weather.calibration`, `weather.market`, `weather.backtesting`,
  `weather.reporting`, `weather.collection`, `weather.operations`, and shared
  utility packages.
- [x] Classify current cross-package imports as allowed, transitional, or
  forbidden.
- [x] Move reusable settlement, replay, formatting, scoring, and artifact
  runtime helpers out of CLI/report/orchestration modules where needed for this
  ratchet by treating existing owner modules (`settlement_io`, `tape_scoring`,
  `formatting`, `scoring`, `supervisor`, `io`, `time`, and `units`) as the
  documented shared surfaces.
- [x] Extend `tests/operations/test_import_architecture.py` with a package-edge
  ratchet that allows known transitional edges but rejects new broad cycles.
- [x] Add short ownership notes to modules that are intentional facades so
  future helpers are extracted to owner modules instead of being imported from
  the facade.

Acceptance: dependency direction is documented, architecture tests prevent new
high-risk cycles, and shared code lives in owner modules rather than whichever
CLI/report module first needed it.

## Design

Start with a ratchet, not a big-bang import rewrite.

- Keep known edges while documenting their owner and removal condition.
- Forbid new imports from orchestration/CLI modules into lower-level runtime
  packages unless explicitly allowed.
- Prefer small owner modules such as `settlement_io`, `tape_scoring`,
  `formatting`, `scoring`, `supervisor`, and future `units`/`io`/`time`
  helpers over importing from broad facades.

Verification strategy:

- Add an import graph helper in tests that reports package edges.
- Fail only on new forbidden edges at first.
- Tighten transitional allowances as items 93 through 98 land.

## Implementation

- Added `docs/operations/package-boundaries.md` to document owner layers,
  shared utility roots, and transitional package edges.
- Added an AST-based package import graph helper to
  `tests/operations/test_import_architecture.py`.
- Added `ALLOWED_PACKAGE_EDGES` and `TRANSITIONAL_PACKAGE_EDGES` to make the
  current package graph explicit. New cross-package edges fail unless they are
  documented, and removed transitional edges fail until the allowance is
  cleaned up.
- Kept shared utility imports open for `weather.artifacts`, `weather.io`,
  `weather.paths`, `weather.schema_registry`, `weather.scoring`,
  `weather.time`, and `weather.units`.
- Added ownership notes to `weather.market.mm_exchange`,
  `weather.market.mm_paper`, `weather.reporting.data_layer_audit`, and
  `weather.model.toronto_model`.

## Verification

- `.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py -q`
  - 12 passed.
- `.\venv\Scripts\python.exe -m pytest -q`
  - 823 passed, 491 subtests passed.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - PACKAGE EDGE RATCHET LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

