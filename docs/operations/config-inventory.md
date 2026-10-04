# Config Inventory

Status: canonical configuration classification and freshness policy.

Checked-in files under `config/` are classified by owner and freshness policy:

| File | Classification | Policy |
| :--- | :--- | :--- |
| `scheduled_tasks.json` | Hand-authored task lifecycle registry | Reviewed intent, never proof of Scheduler state or permission to re-arm. Owns nightly retired-bot monitoring and the generated task table; update with registrar and status classification changes. |
| `locations.json` | Durable location registry | Hand-authored location, station, settlement, and source-plan facts. Volatile market-event fields are not stored here. |
| `location_market_events.json` | Generated snapshot | Current Gamma API active-event metadata by location; stale after 7 days. |
| `markets.json` | Deprecated compatibility shell | Empty external override file retained for `weather.market.market_registry`; built-in `MarketSpec` definitions remain authoritative. |
| `model_variant_registry.json` | Hand-authored registry | Validate before promotion; active promoted artifacts must not point at ignored `data/` paths. |
| `supplemental_stations.json` | Hand-authored registry | Review when station provenance changes. |
| `no_market_extra_locations.json` | Local shadow registry | Active entries must be backfilled before training eligibility; evidence-free diagnostic entries are retained under `archived_locations`. |
| `storage_pressure.json` | Operator activation policy | **Activated `false` by the owner on 2026-09-19 (item 325).** `capture.write_order_books_long_csv=true` restores the long-CSV projection. Change it only in an operator-approved quiet window after the production dry-run; missing or invalid policy fails safe to writing the projection. |
| `toronto_nbm_blocks.json` | Operator activation policy | Owner decision 2026-10-02. `capture.retain_toronto_nbm_blocks=true` makes the Toronto market store its CYYZ/CYTZ NBM NBP station blocks (from the national bulletin the US markets already download) under the capture-only source `nbm_toronto_station_blocks`, which the feature builder never reads: serving features are unchanged. Checked-in default `false`; missing or invalid policy fails safe to `false`. Read on every Toronto source pass, so a flip applies from the next pass without a code roll. Owner: `weather.sources.toronto_nbm_blocks`. |
| `international_live_execution_host.json` | Hand-authored execution-role registry | Binds one active portable Windows installation and token principal per production tip, separately identifies the dedicated capture host, and is `UNASSIGNED` until a reviewed relocation assigns both public IDs. |

Generate the current inventory:

`config/local/` is ignored owner-local configuration, never part of the tracked
inventory. `local/wallet_reader_client.json` holds the LAN URL and reader bearer
token under the [wallet-reader runbook](wallet-reader.md); never commit or print it.
`examples/portfolio_campaigns.json` is a hand-authored structural template owned by
`maker_core.contracts.portfolio`; update it when the campaign contract changes.
The production agent authors `local/portfolio_campaigns.json` from it using the
owner's actual account and capital records; see [portfolio ledger](portfolio-ledger.md).

```powershell
python -m weather.operations.config_inventory --out data\backtest\config_inventory.json --report data\backtest\config_inventory_report.md
```

Refresh generated market-event metadata:

```powershell
python -m weather.operations.location_config_refresh --locations config\locations.json --event-metadata config\location_market_events.json
```

On the production host, `scripts/ops/refresh_location_config.ps1` follows that
refresh with an independent live target-date validation and reports task
success only when its receipt is readable, dated today, and `PASS`. Keep the
validation after the refresh: the 07:05 paper-maker launch precedes the 09:30
daily chain that otherwise produces this gate.

Event and location counts are volatile. Read the generated JSON or run the
inventory command for current values rather than copying them into prose.

## Update this file when

Update when a checked-in config file is added, removed, reclassified, changes
owner, or changes generation/freshness policy. The agent-doc audit fails when a
checked-in `config/*.json` file is missing from the table above.
