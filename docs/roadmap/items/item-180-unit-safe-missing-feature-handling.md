# 180. Unit-Safe Missing-Feature Handling [COMPLETE 2026-06-21 - MISSINGNESS ROUTES THROUGH IMPUTER]

Goal: stop hard-coded Celsius fallback constants from pre-empting the per-market
imputer and corrupting Fahrenheit-market features.

Source: `docs/roadmap/core-model-audit-2026-06-20.md` finding M1 (also the
2026-06-09 audit finding #6). `extract_live_features` substitutes literal
constants when a field is missing — `current_temp`/`high_so_far`/`temp_7am`
`= 17.0`, `dewpoint = 10.0`, `humidity = 60.0`, `wind_speed = 15.0`
([model_features.py:378-443](../../../src/weather/model/model_features.py#L378)).

Why this matters: the constants are Celsius-flavoured and unit-blind — on a
Fahrenheit market `17.0` is read as 17 °F (~ −8 °C), a wild value. Worse, by
filling a number the code bypasses the `SimpleImputer(strategy="median")` the
model was trained with, so a missing field serves a different value than training
imputed for it. Both are train/serve skew that scales with the fleet.

## Design

1. Return `None` for missing numeric features on the non-strict serving path, and
   let the HGB native-NaN columns and the LR `imputer_median` handle missingness
   exactly as in training.
2. Audit each fallback site; keep a literal only where a non-model consumer truly
   needs a value, and make any retained fallback unit-aware via
   `spec.c_to_native(...)`.
3. Add a test on a Fahrenheit market proving a missing field serves the trained
   imputer median, not a Celsius literal.

- [x] Replace the serving-path literals with explicit missingness.
- [x] Make any genuinely required fallback unit-aware.
- [x] Add the F-market missing-feature parity test.

Acceptance: no Celsius literal reaches a feature value on any market, missing
inputs route through the trained imputer, and the F-market parity test passes.

Completion note 2026-06-21: `extract_live_features` now keeps missing
non-strict numeric live fields as `None` instead of filling
`17.0`/`10.0`/`60.0`/`15.0`. Derived deltas that depend on those missing fields
also stay missing, while the strict analog path remains fail-closed. The
Fahrenheit-market serving test proves missing live fields reach the HGB
imputer and the model receives the trained median row rather than a Celsius
literal.

Related: items 178, 179; `[[model-audit-2026-06-09]]`, `[[multi-market-platform]]`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - MISSINGNESS ROUTES THROUGH IMPUTER`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

