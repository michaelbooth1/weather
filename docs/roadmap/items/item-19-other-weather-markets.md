# 19. Other Weather Markets [COMPLETE - EXPLICIT MARKET MAPPINGS]

- [x] Add support for other stations only after Toronto is solid.
- [x] Define each market's resolution source and station mapping explicitly.
- [x] Avoid assuming WU/Weather.com behavior transfers across locations.

Implementation update (2026-06-15): complete. The registry now covers the
temperature-market expansion set with per-market station, timezone, unit,
source-list, leading-observation, and settlement/history mapping. `MarketSpec`
now carries an explicit `resolution_source` field, and
`validate_market_registry()` verifies that the resolution source and leading
observation source are fetched for each market and that the WU/history and ICAO
station identifiers are present. Combined with item 18's JSON registry overlay,
new standard location markets can be added without engine changes while keeping
resolution-source assumptions explicit per market.

Verification:
- `.\venv\Scripts\python.exe -m pytest tests\market\test_market_config.py tests\model\test_market_units.py tests\reporting\test_data_auditor.py -q` -> 21 passed.
- `.\venv\Scripts\python.exe -m compileall src\weather\market\market_registry.py src\market_registry.py`
