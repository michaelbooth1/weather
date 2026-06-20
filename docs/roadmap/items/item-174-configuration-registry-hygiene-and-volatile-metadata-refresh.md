# 174. Configuration Registry Hygiene And Volatile Metadata Refresh [OPEN - STARTED 2026-06-20 - CONFIG INVENTORY AND REGISTRY HYGIENE LIVE]

Goal: make configuration files clearly durable, generated, or deprecated so
runtime behavior does not depend on stale or placeholder registry state.

Source: the 2026-06-20 full repository cleanup audit. `config/locations.json`
was generated from a 2026-06-07 Gamma API snapshot, includes volatile active
event metadata, and lists locations not currently server-rendered.
`config/markets.json` is an empty placeholder. The model variant registry has
active or required entries pointing to ignored `data/backtest` candidate
artifacts.

Why this matters: configuration drift can look like a model or data bug.
Operators need to know which files are authoritative, which are generated, and
which are local shadow state.

## Design

1. Classify each config file as hand-authored, generated, deprecated, or
   local-shadow.
2. Split stable location facts from volatile active market/event metadata.
3. Add a regeneration command and freshness check for generated location
   metadata.
4. Remove, populate, or explicitly deprecate the empty market registry.
5. Enforce variant registry rules for promoted artifacts, shadow candidates,
   and ignored local paths.

- [x] Add a config inventory report covering `locations.json`,
  `markets.json`, `model_variant_registry.json`, supplemental stations, and
  no-market extra locations.
- [ ] Refresh `locations.json` from the current source and record generated-at
  metadata.
- [x] Move volatile active event fields out of durable location facts or mark
  them generated-only.
- [x] Decide whether `markets.json` is removed, populated, or retained as a
  deprecated compatibility shell.
- [x] Add validation that `artifact_required` variants do not point to ignored
  `data/` paths unless they are shadow-only and explicitly allowed.
- [ ] Review diagnostic-only extra locations and either backfill them or
  archive them with a clear reason.

Acceptance: every config file has a documented owner and freshness policy,
generated metadata can be refreshed deterministically, and registry validation
prevents active runtime dependencies on missing local-only artifacts.

## 2026-06-20 progress

Implemented the unlocked config hygiene slice:

- Added `weather.operations.config_inventory`, schema
  `config_inventory_v0.1`, JSON output
  `data/backtest/config_inventory.json`, and Markdown report
  `data/backtest/config_inventory_report.md`.
- Added `docs/operations/config-inventory.md` with owner/freshness policy for
  `locations.json`, `markets.json`, `model_variant_registry.json`,
  `supplemental_stations.json`, and `no_market_extra_locations.json`.
- Marked `config/locations.json` as a `generated_snapshot` and documented
  volatile generated-only fields such as active Polymarket event metadata.
- Retained `config/markets.json` as an explicit
  `deprecated_compatibility_shell`; built-in `MarketSpec` definitions remain
  authoritative unless the external override file is repopulated.
- The item 172 variant-registry validation now blocks active promoted variants
  from depending on ignored `data/` artifact paths, and the config inventory
  reports the same class of issue.

Current generated inventory: `WARN`, with `5` config files and `3` warning
rows. The warning rows are expected until the remaining work is done:
`locations.json` is stale, `markets.json` is intentionally empty/deprecated,
and diagnostic-only no-market extra locations still have no backfilled
evidence.

Verification:

- `python -m weather.operations.config_inventory --out data\backtest\config_inventory.json --report data\backtest\config_inventory_report.md`
  returned `WARN` with 5 configs and 3 warnings.
- `python -m pytest -q tests\operations\test_config_inventory.py tests\market\test_market_config.py tests\operations\test_schema_registry.py tests\operations\test_import_architecture.py tests\operations\test_path_policy.py`
  passed with 31 tests.

Remaining work stays open: refresh `locations.json` from the current source,
split stable location facts from generated active-event metadata, and backfill
or archive diagnostic-only extra locations.
