# Config Inventory

Status: canonical configuration classification and freshness policy.

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

Event and location counts are volatile. Read the generated JSON or run the
inventory command for current values rather than copying them into prose.

## Update this file when

Update when a checked-in config file is added, removed, reclassified, changes
owner, or changes generation/freshness policy. The agent-doc audit fails when a
checked-in `config/*.json` file is missing from the table above.
