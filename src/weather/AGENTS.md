# Weather Package Guidance

Scope: canonical Python implementation under `src/weather/`.

## Ownership

- `sources` owns provider fetches, parsing, and source-specific history.
- `model` owns serving-time source assembly, features, distributions, and presentation.
- `calibration` owns training, candidate replay, calibration, and artifact writes.
- `market` owns market configuration, settlement labels, CLOB capture, and trading policy.
- `collection` owns live capture, snapshot persistence, archives, and collection health.
- `backtesting` owns settlement IO, tape scoring, and replay evaluation.
- `reporting` owns reports, scorecards, audits, and promotion summaries.
- `operations` owns scheduled orchestration, supervisors, and operational audits.

Cross-owner helpers belong in a small shared module such as `weather.paths`,
`weather.units`, `weather.io`, `weather.schema_registry`, or `weather.scoring`.
Follow the allowed and transitional edges in
[Package Dependency Boundaries](../../docs/operations/package-boundaries.md).

## Package Rules

- Use canonical `weather.*` imports and `python -m weather...` entrypoints. Flat
  `src/*.py` modules are compatibility wrappers, not implementation owners.
- Use `weather.paths` for repo-owned defaults. Do not derive the repository from
  the current working directory or mutate `sys.path` in package code.
- Preserve stable public modules and CLIs when extracting implementation. Put
  new logic in the documented owner module and keep compatibility facades thin.
- Treat `data/` as ignored local runtime state. Tracked artifacts, configuration,
  and deterministic fixtures belong under `artifacts/`, `config/`, and
  `tests/fixtures/` respectively.
- Register durable schemas through `weather.schema_registry` and update readers,
  writers, migrations, and tests together.

## Verification

Run focused owner tests, then the architecture ratchet when imports, paths,
facades, or module locations change:

```powershell
.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py -q
.\venv\Scripts\python.exe -m compileall -q src\weather
```

See also [Repository Path Policy](../../docs/operations/path-policy.md),
[Large Module Ownership Map](../../docs/operations/module-ownership-map.md), and
[Compatibility Shim Inventory](../../docs/roadmap/compatibility-shim-inventory.md).

## Update this file when

Update when package ownership, shared-module policy, path/import rules, facade
policy, or architecture verification changes.
