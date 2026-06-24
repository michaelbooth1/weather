# 18. Multi-Day Market Support [COMPLETE - CONFIG REGISTRY OVERLAY]

- [x] Parameterize target date, event slug, station, and data root.
- [x] Allow creating a new market config without code edits.
- [x] Reuse the same history and snapshot machinery for future Toronto markets.

Implementation update (2026-06-15): complete. Target date, event slug, market
id, station identifiers, timezone, unit, source list, and data root are already
driven by `MarketSpec` / `MarketConfig`. `src.weather.market.market_registry`
now also loads an optional external JSON overlay from `config/markets.json` (or
`WEATHER_MARKET_REGISTRY`) using schema `market_registry_v0.1`, so standard
markets can be added or overridden without Python code edits. Missing config is
a no-op, and invalid schema versions fail fast.

Verification:
- `.\venv\Scripts\python.exe -m pytest tests\market\test_market_config.py tests\model\test_market_units.py tests\sources\test_metar_history.py tests\sources\test_historical_sources.py -q` -> 38 passed.
- `.\venv\Scripts\python.exe -m compileall src\weather\market\market_registry.py src\market_registry.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - CONFIG REGISTRY OVERLAY`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

