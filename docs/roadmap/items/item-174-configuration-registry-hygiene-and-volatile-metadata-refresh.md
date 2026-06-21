# 174. Configuration Registry Hygiene And Volatile Metadata Refresh [COMPLETE 2026-06-20 - DURABLE CONFIGS AND FRESH GENERATED EVENTS]

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
- [x] Refresh `locations.json` from the current source and record generated-at
  metadata.
- [x] Move volatile active event fields out of durable location facts or mark
  them generated-only.
- [x] Decide whether `markets.json` is removed, populated, or retained as a
  deprecated compatibility shell.
- [x] Add validation that `artifact_required` variants do not point to ignored
  `data/` paths unless they are shadow-only and explicitly allowed.
- [x] Review diagnostic-only extra locations and either backfill them or
  archive them with a clear reason.

Acceptance: every config file has a documented owner and freshness policy,
generated metadata can be refreshed deterministically, and registry validation
prevents active runtime dependencies on missing local-only artifacts.

## 2026-06-20 completion

Implemented and verified the config hygiene slice:

- Added `weather.operations.config_inventory`, schema
  `config_inventory_v0.1`, JSON output
  `data/backtest/config_inventory.json`, and Markdown report
  `data/backtest/config_inventory_report.md`.
- Added `weather.operations.location_config_refresh`, schema
  `location_market_events_v0.1`, and generated
  `config/location_market_events.json` from the live Gamma API.
- Added `docs/operations/config-inventory.md` with owner/freshness policy for
  `locations.json`, `location_market_events.json`, `markets.json`,
  `model_variant_registry.json`, `supplemental_stations.json`, and
  `no_market_extra_locations.json`.
- Converted `config/locations.json` to durable location/station/source-plan
  facts (`location_registry_v0.1`) and moved active Polymarket event metadata
  to `config/location_market_events.json`.
- Refreshed the generated market-event metadata on 2026-06-20. The refresh
  fetched `115` active Gamma events across all `51` configured locations with
  no configured locations missing from the API and no API locations missing
  from the file.
- Retained `config/markets.json` as an explicit
  `deprecated_compatibility_shell`; built-in `MarketSpec` definitions remain
  authoritative unless the external override file is repopulated.
- Archived the evidence-free no-market diagnostic locations under
  `archived_locations` with explicit archive reasons, leaving the active
  `locations` list empty until a backfill produces eligibility evidence.
- The item 172 variant-registry validation now blocks active promoted variants
  from depending on ignored `data/` artifact paths, and the config inventory
  reports the same class of issue.

Current generated inventory: `PASS`, with `6` config files and `0` warning
rows.

Verification:

- `python -m weather.operations.config_inventory --out data\backtest\config_inventory.json --report data\backtest\config_inventory_report.md`
  returned `PASS` with 6 configs and 0 warnings.
- `python -m pytest -q tests\operations\test_config_inventory.py tests\operations\test_location_config_refresh.py tests\reporting\test_source_family_inventory.py tests\market\test_market_config.py tests\operations\test_schema_registry.py tests\operations\test_import_architecture.py tests\operations\test_path_policy.py`
  passed.
