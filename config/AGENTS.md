# Configuration Instructions

These instructions apply to `config/`.

- Treat `locations.json` as the durable location, station, settlement, source
  plan, and Polymarket-series registry.
- Do not hand-edit `location_market_events.json`. It is a generated Gamma-event
  snapshot; refresh it with
  `python -m weather.operations.location_config_refresh` and review the diff.
- Keep `markets.json` as the deprecated external-override compatibility shell.
  Built-in `MarketSpec` definitions in
  `src/weather/market/market_registry.py` are authoritative unless
  `WEATHER_MARKET_REGISTRY` explicitly selects another registry for non-live
  workflows; International live candidate/session paths reject that ambient
  override.
- Treat `model_variant_registry.json`, `supplemental_stations.json`, and
  `no_market_extra_locations.json` as reviewed registries. Preserve schema,
  provenance, lifecycle, and archive fields; do not reformat or prune entries
  opportunistically.
- Treat `storage_pressure.json` as an operator activation policy. Its checked-in
  default must preserve current capture; activation is a separately reviewed
  production operation, not part of a code merge.
- Treat `international_live_execution_host.json` as the single-active portable
  executor assignment. Reassignment requires the new public host/principal IDs,
  a reviewed change, and a new production tip; never edit prior receipts.
- Never add credentials, secrets, machine-specific paths, or paid-weather
  provider requirements to checked-in config.

After an intentional config change, run the focused tests for its owner and:

```powershell
.\venv\Scripts\python.exe -m weather.operations.config_inventory --out data\backtest\config_inventory.json --report data\backtest\config_inventory_report.md
```

Update `docs/operations/config-inventory.md` when a file's owner,
classification, generation method, or freshness policy changes. The config
inventory is the canonical policy reference; generated reports under `data/`
are local diagnostics.

## Update this file when

Update when config ownership, generated-versus-hand-authored classification,
refresh commands, or config verification changes.
