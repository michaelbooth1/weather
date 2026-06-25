# 317. Marine Water-Contrast Source/Model Boundary Ratchet [COMPLETE 2026-06-25 - SOURCE-LOCAL CUTOFF CONTRACT RESTORES RATCHET]

Goal: restore the package dependency ratchet by removing the current
`weather.sources -> weather.model` import introduced by the marine
water-contrast historical sidecar.

Source: 2026-06-25 Python structure refactor audit. The architecture ratchet
fails with one undocumented package edge:
`sources->model` from `src/weather/sources/marine_water_contrast.py`, caused by
importing `weather.model.model_constants.INTRADAY_CUTOFF_HOURS`.

Why this matters: `weather.sources` owns provider fetch, parsing, daily
summaries, and source-specific historical stores. `weather.model` owns
serving-time model assembly and feature extraction. A source adapter importing a
model constant weakens that boundary and makes historical source code depend on
serving internals. Item 191 owns the marine contrast feature and promotion
blockers, but it does not own this architecture ratchet failure. Item 99
completed the ratchet; this item restores it after the new edge appeared.

## Design

1. Replace the `weather.model.model_constants.INTRADAY_CUTOFF_HOURS` import in
   `weather.sources.marine_water_contrast` with a source-local default, an
   explicit caller-provided cutoff tuple, or a shared owner-neutral cutoff
   contract.
2. Preserve item 191 behavior: station-history rows remain cutoff-aware, feature
   rows still use the same cutoff hours as serving/replay, and GLSEA/OISST
   sidecar behavior remains unchanged.
3. Prefer removing the edge over documenting it as transitional. Only add a
   temporary transitional edge if the extraction needs a larger caller-contract
   change, and include a dated removal checklist.
4. Update package-boundary docs only if a new shared cutoff owner is introduced
   or a temporary transition is unavoidable.
5. Add or adjust focused tests so the cutoff default is covered without
   importing model internals from sources.

- [x] Remove the `weather.sources -> weather.model` edge from
  `marine_water_contrast.py`.
- [x] Keep marine water-contrast feature rows and cutoff defaults behaviorally
  equivalent.
- [x] Add or update source tests for default cutoff-hour behavior.
- [x] Rerun the architecture ratchet and confirm no undocumented package edges
  remain.
- [x] Update `docs/operations/package-boundaries.md` only if a new shared owner
  or temporary transition is introduced.

Acceptance: `python -m pytest tests\operations\test_import_architecture.py -q`
passes with no `sources->model` edge, and focused marine contrast/source tests
prove the cutoff-aware sidecar behavior remains intact.

Related: items 99, 191, 89, 97, 254.

## Completion Notes

Removed the `weather.model.model_constants.INTRADAY_CUTOFF_HOURS` import from
`weather.sources.marine_water_contrast` and replaced it with the source-local
`DEFAULT_INTRADAY_CUTOFF_HOURS` contract. The default remains the serving/replay
cutoff grid `(7, 8, ..., 20)`, and callers can still override cutoff hours
explicitly through the existing builder/store/backfill/CLI surfaces.

Added focused source tests proving the default cutoff grid produces cutoff-aware
feature rows and that the source module does not import `weather.model`. The
full architecture ratchet now passes without the undocumented `sources->model`
edge. No package-boundary doc update was needed because no new shared owner or
temporary transitional edge was introduced.
