# Model Guidance

Scope: serving-time model code under `src/weather/model/`. Inherits
[package-wide guidance](../AGENTS.md).

- Despite the legacy `TorontoHighTempModel` name, the serving path is
  multi-market. Each market runs in its native unit: Celsius markets in C and
  Fahrenheit markets in F. Use the canonical native-temperature accessors;
  legacy fields ending in `_c` may contain native-unit platform-era values.
- Apply the source-role and hard-floor contract in
  [Durable Agent Context](../../../docs/operations/AGENT_CONTEXT.md) when
  combining observations; a support signal cannot silently change roles.
- Align WU-backed intraday features and floors to the effective WU printed
  cutoff, not wall-clock hour alone. WU publication lag is a modeled behavior.
  When WU is empty, only the admitted station/current rescue captured by model
  emission may establish the effective observed-high floor.
- `historical_target_cache()` defaults to the serving-safe prior-year,
  target-season window. Calibration may request exact PIT coverage dates only
  to make the verified prelocked universe addressable; that does not relax
  per-row cutoff alignment, locked-date exclusion, or prior-as-of boundaries.
- Runtime model code must load calibration through
  `weather.model.calibration_runtime`, not import `weather.calibration`.
- When an active release pointer exists, serving must use its completely
  verified bundle. Do not add fallback reads from global artifact paths.
- A feature change is incomplete until training extraction in
  `weather.calibration.feature_model` and live extraction here agree, artifacts
  are regenerated as required, and replay/backtest evidence is reviewed.

Run focused tests in `tests/model/`, especially unit, feature-skew, distribution,
and release-serving coverage. Package-edge and native-accessor rules are also
enforced by `tests/operations/test_import_architecture.py`.

Canonical architecture details live in
[Package Dependency Boundaries](../../../docs/operations/package-boundaries.md)
and artifact operations in
[Nightly Retrain Runbook](../../../docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md).

## Update this file when

Update when unit/settlement semantics, feature cutoff/parity rules, calibration
boundaries, release serving, or model verification changes.
