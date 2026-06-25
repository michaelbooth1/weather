# 64. Canonical Settlement History Provenance Guardrails [COMPLETE 2026-06-15 - CANONICAL GUARDRAILS LIVE]

Goal: make it impossible to silently blend nearby station data into canonical
settlement history.

Audit source: `docs/research/HISTORICAL_AND_NEARBY_DATA_AUDIT_2026-06-15.md`.
The correct policy is: use validated nearby station roots as source-trust and
redundant-history features, retain source id and distance, and do not blend
them into canonical settlement history without provenance.

Tasks:

- [x] Define canonical versus supplemental source roles in the historical schema
  and audit reports.
- [x] Add reader/writer tests proving canonical daily summaries do not include
  supplemental station rows unless an explicit composite view is requested.
- [x] Add a composite-view helper that exposes canonical + supplemental coverage
  as a separate artifact with lineage columns, never as the canonical CSV.
- [x] Update backfill/rebuild commands so supplemental roots cannot target
  canonical output paths.
- [x] Add a data-layer audit gate that flags any canonical source row whose
  source id/station id does not match the registered canonical station.

Acceptance: canonical settlement history remains a faithful record of the
market's resolution source, while supplemental history is available through
separate provenance-preserving views and features.

Implementation notes:

- Added `weather.sources.canonical_history_guardrails` and the top-level
  `src/canonical_history_guardrails.py` wrapper. The module audits canonical
  daily summaries for non-canonical `source_role`, supplemental lineage columns,
  registered supplemental station ids, and station ids that do not match the
  canonical station metadata.
- Added `build_ghcnh_composite_view(...)` and `write_composite_daily_csv(...)`.
  Composite output uses `ghcnh_composite_daily_view_v0.1` lineage columns such
  as source role, source id, station id, distance, validation status, promotion
  state, root path, and daily path. It writes a separate artifact and never
  mutates the canonical daily CSV.
- Wired `canonical_guardrail_report(...)` into `data_layer_audit`; the new
  `canonical_history_provenance` gate fails on any canonical provenance/station
  violation. The short-window smoke audit reports `0` canonical violations.
- `GHCNHStore` now validates supplemental registry roots during store creation
  when registry context is supplied, and CLI station/backfill/rebuild/coverage
  commands load the registry so bad supplemental roots cannot silently target
  canonical paths.

Verification:

- `.\venv\Scripts\python.exe -m src.canonical_history_guardrails audit --markets toronto --out scratch\item64_canonical_guardrails_smoke.json`
- `.\venv\Scripts\python.exe -m src.canonical_history_guardrails composite-ghcnh --market toronto --start 2000-05-20 --end 2000-05-22 --validation data\backtest\supplemental_station_validation.json --out scratch\item64_ghcnh_composite_smoke.csv`
- `.\venv\Scripts\python.exe -m src.data_layer_audit --historical-start 2000-05-20 --historical-end 2000-05-22 --out scratch\item64_data_layer_audit_smoke.json --report scratch\item64_data_layer_audit_smoke.md`
- `.\venv\Scripts\python.exe -m pytest tests\sources\test_canonical_history_guardrails.py tests\sources\test_supplemental_station_validation.py tests\sources\test_historical_sources.py tests\reporting\test_data_layer_audit.py tests\reporting\test_source_redundancy.py tests\calibration\test_pooled_feature_model.py -q`
- `.\venv\Scripts\python.exe -m compileall src\weather\sources\canonical_history_guardrails.py src\canonical_history_guardrails.py src\weather\sources\supplemental_station_validation.py src\supplemental_station_validation.py src\weather\sources\noaa_ghcnh_history.py src\weather\reporting\data_layer_audit.py src\weather\reporting\source_redundancy.py src\weather\calibration\pooled_feature_model.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-15 - CANONICAL GUARDRAILS LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

