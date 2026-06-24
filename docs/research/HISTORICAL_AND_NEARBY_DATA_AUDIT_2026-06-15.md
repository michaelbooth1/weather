# Historical And Nearby Data Audit - 2026-06-15

## Scope

Fresh audit command:

`.\venv\Scripts\python.exe -m src.data_layer_audit --historical-start 2000-01-01 --historical-end 2026-06-14 --out data\backtest\data_layer_audit_current_after_fill.json --report data\backtest\data_layer_audit_current_after_fill.md`

The generated artifacts are local under `data/backtest/` because `data/` is
ignored. The tracked implementation now recomputes the nearby-station evidence
in `src.weather.reporting.data_quality.data_layer_audit`.

## Added During This Audit

- Backfilled WU settlement history for 2026-06-14 across all 12 registered
  markets. Target-season WU coverage is now 99.2% for Toronto and 99.3% for
  each F-market over 2000-01-01 through 2026-06-14.
- Backfilled METAR/ASOS for 2026-06-14 across all 12 registered markets.
  Target-season METAR coverage is now 100.0% for every market in the same
  audit window.
- Refetched NYC GHCNh 2026 as a source-lag probe. NOAA's 2026 annual file still
  ends at 2026-06-09 locally, so June 10-14 GHCNh is publication lag rather
  than an unfetched local gap.
- Integrated supplemental GHCNh roots into the data-layer audit as
  provenance-labelled nearby history, with composite coverage and bias metrics.

## Remaining Historical Gaps

- Toronto canonical GHCNh remains provider-unavailable for 2000-2012 at
  `CAN06158731`; do not overwrite that canonical root.
- Toronto supplemental GHCNh station `CAN06158733` is already backfilled under
  `data/noaa_ghcnh/cyyz_alt_can06158733` and lifts GHCNh target-season coverage
  from 545/1118 to 1091/1118 days.
- Remaining Toronto GHCNh composite target-season misses are the 2013 handoff
  window plus current NOAA source lag.
- US pre-2015 WU full-year coverage remains about 49.8-49.9%. The latest
  alternate Weather.com ID probe found no available ICAO:9:US candidates, so
  this should be treated as provider-unavailable for full-year training. Target
  season WU is strong enough for high-temperature markets.
- Reanalysis has no normalizable raw-only days after the current refresh; the
  latest missing days are all-null source-lag payloads.

## Nearby-Location Verdict

Nearby historical data is useful when it is handled as supplemental source
evidence, not a silent replacement for the settlement station. Toronto proves
the case: `CAN06158733` is 0.05 km from the market station, adds 546 target-season
days, has 537 target-season overlap days against WU, 0.247 C MAE, and 99.6%
bucket match. Against METAR it has 546 overlap days, 0.235 C MAE, and 99.3%
bucket match.

Recommendation: use validated nearby station roots as source-trust and
redundant-history features, with source id and distance retained. Do not blend
them into canonical settlement history without provenance.

Roadmap follow-up:

- Item 61: supplemental nearby station registry and provenance.
- Item 62: nearby station validation and promotion gates.
- Item 63: nearby station source-trust and redundant-history features.
- Item 64: canonical settlement history provenance guardrails.

## Non-Historical Audit State

The fresh audit reports `WARN`. Required replay status, forecasts, and CLOB
features now pass for the 117 training-ready folders; active 2026-06-15 folders
are not counted as historical/training-ready misses. Remaining warnings are
legacy replay/source-status/features/components coverage, forecast payload
manifests, low-fill ECCC/Gamma fields, and six quarantined raw observations.
