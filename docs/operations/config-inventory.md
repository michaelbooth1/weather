# Config Inventory

Last updated: 2026-06-20

Checked-in files under `config/` are classified by owner and freshness policy:

| File | Classification | Policy |
| :--- | :--- | :--- |
| `locations.json` | Generated snapshot | Gamma API active-event metadata; volatile Polymarket fields are generated-only and stale after 7 days. |
| `markets.json` | Deprecated compatibility shell | Empty external override file retained for `weather.market.market_registry`; built-in `MarketSpec` definitions remain authoritative. |
| `model_variant_registry.json` | Hand-authored registry | Validate before promotion; active promoted artifacts must not point at ignored `data/` paths. |
| `supplemental_stations.json` | Hand-authored registry | Review when station provenance changes. |
| `no_market_extra_locations.json` | Local shadow registry | Diagnostic-only entries must be backfilled or archived before training eligibility. |

Generate the current inventory:

```powershell
python -m weather.operations.config_inventory --out data\backtest\config_inventory.json --report data\backtest\config_inventory_report.md
```

`locations.json` still needs a current-source refresh before this roadmap item
can be closed. The inventory intentionally marks that file stale rather than
pretending the 2026-06-07 Gamma snapshot is durable location truth.
