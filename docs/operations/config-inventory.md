# Config Inventory

Last updated: 2026-06-20

Checked-in files under `config/` are classified by owner and freshness policy:

| File | Classification | Policy |
| :--- | :--- | :--- |
| `locations.json` | Durable location registry | Hand-authored location, station, settlement, and source-plan facts. Volatile market-event fields are not stored here. |
| `location_market_events.json` | Generated snapshot | Current Gamma API active-event metadata by location; stale after 7 days. |
| `markets.json` | Deprecated compatibility shell | Empty external override file retained for `weather.market.market_registry`; built-in `MarketSpec` definitions remain authoritative. |
| `model_variant_registry.json` | Hand-authored registry | Validate before promotion; active promoted artifacts must not point at ignored `data/` paths. |
| `supplemental_stations.json` | Hand-authored registry | Review when station provenance changes. |
| `no_market_extra_locations.json` | Local shadow registry | Active entries must be backfilled before training eligibility; evidence-free diagnostic entries are retained under `archived_locations`. |

Generate the current inventory:

```powershell
python -m weather.operations.config_inventory --out data\backtest\config_inventory.json --report data\backtest\config_inventory_report.md
```

Refresh generated market-event metadata:

```powershell
python -m weather.operations.location_config_refresh --locations config\locations.json --event-metadata config\location_market_events.json
```

The 2026-06-20 refresh wrote `location_market_events_v0.1` with 115 active
Gamma events across 51 configured locations. The generated config inventory is
`PASS` with 6 config files and 0 warnings.
