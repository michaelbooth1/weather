# 93. Canonical Temperature Rounding And Unit Helpers [COMPLETE 2026-06-16 - CANONICAL UNITS HELPER LIVE]

Goal: make settlement-relevant rounding and unit conversion a single tested
domain utility instead of duplicated local helpers.

Source: 2026-06-16 architecture review. `round_half_up` is reimplemented across
source, calibration, model, operation, reporting, and backtesting modules. Most
implementations use `floor(x + 0.5)`, but observation-trigger and ASOS one-minute
helpers round negative half values differently.

Why this is missing: the project grew source by source, and small temperature
helpers were copied into local modules before the package had a stable shared
domain layer. That is risky because market settlement and trigger logic depend
on exact bucket behavior.

- [x] Add one canonical helper module for numeric temperature behavior, either
  under `weather.sources.daily_summary` if kept source-specific or a new
  `weather.units` module if used across the whole package.
- [x] Move `round_half_up`, Celsius/Fahrenheit conversion, native-unit bucket
  helpers, and null-safe numeric coercion into that shared layer where
  practical.
- [x] Replace local `round_half_up` definitions in source, calibration,
  operation, model, reporting, and backtesting modules with imports from the
  canonical helper.
- [x] Add regression tests for positive and negative half values, missing
  values, Fahrenheit-native markets, and legacy WU daily-summary columns.
- [x] Add an architecture guard that rejects new local `round_half_up`
  definitions outside the canonical helper and explicit compatibility wrappers.

Acceptance: every runtime path that turns a temperature into a market bucket
uses the same tested helper, negative edge cases are consistent, and new local
rounding definitions fail tests.

## Design

Treat rounding as domain logic, not formatting or math trivia.

- Settlement buckets should continue to match the existing tested project
  expectation unless a separate settlement-policy change explicitly revises it.
- Unit conversion helpers should preserve current schema compatibility: legacy
  `*_c` columns that actually contain native Fahrenheit values must still be
  interpreted intentionally.
- Callers should import semantic helpers such as `native_bucket(...)` or
  `settlement_bucket(...)` where row shape matters, and only use raw
  `round_half_up(...)` for already-normalized numeric values.

Verification strategy:

- Focused unit tests for the helper module.
- Existing source daily-summary, settlement, observation-trigger, ASOS
  one-minute, calibration, and model validation tests.
- Full suite after replacing duplicated helpers.

## Completion

Completed 2026-06-16.

- Added `weather.units` as the canonical nullable temperature helper module for
  `to_float`, `round_half_up`, Celsius/Fahrenheit conversion, and native-unit
  conversion helpers.
- Updated `weather.sources.daily_summary` and `weather.sources.historical_schema`
  to consume and re-export the canonical helpers so existing imports continue to
  work while row-shape interpretation remains local to source/schema modules.
- Replaced local `round_half_up` implementations across sources, calibration,
  collection, operations, reporting, backtesting, and the model facade. The
  model facade keeps a compatibility method, but it delegates to
  `weather.units.round_half_up`.
- Fixed the observed negative-half inconsistency: WU history, observation
  trigger, and ASOS one-minute now all resolve `-1.5` to `-1`.
- Added `tests/model/test_units.py` for canonical rounding, null handling,
  unit conversion, and legacy WU Fahrenheit `*_c` interpretation.
- Extended `tests/operations/test_import_architecture.py` with a guard that
  rejects new local `round_half_up` definitions outside `weather.units` and the
  explicit model-facade compatibility method.

Verification:

- `.\venv\Scripts\python.exe -m pytest tests\model\test_units.py tests\model\test_validation.py tests\operations\test_observation_trigger.py tests\sources\test_asos_one_minute.py tests\operations\test_import_architecture.py -q` (51 passed)
- Negative-rounding smoke check: `weather.units`, WU history, observation
  trigger, and ASOS one-minute all return `-1` for `-1.5`.
- `.\venv\Scripts\python.exe -m pytest -q` (805 passed, 491 subtests passed)
