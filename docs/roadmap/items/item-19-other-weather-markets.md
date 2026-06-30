# 19. Other Weather Markets [COMPLETE - EXPLICIT MARKET MAPPINGS]

- [x] Add support for other stations only after Toronto is solid.
- [x] Define each market's resolution source and station mapping explicitly.
- [x] Avoid assuming WU behavior transfers across locations.

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

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - EXPLICIT MARKET MAPPINGS`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

