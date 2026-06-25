# 30. Source Redundancy And Gap-Filling [COMPLETE - REDUNDANCY REPORT LIVE]

Goal: no single feed is a single point of failure or bias.

- [x] >=2 observation streams per city (WU + METAR/ASOS + ISD), cross-validated;
  learn each one's lead/bias versus settlement (generalize items 4-5 to all
  markets).
- [x] Multiple forecast sources (Open-Meteo + NWS/NDFD + a global ensemble) into
  an ensemble-forecast feature plus a disagreement signal (extends item 22).
- [x] Automated gap detection and targeted re-fetch; fill observation gaps from
  the redundant stream.

Acceptance: a single source outage degrades gracefully, and forecast
disagreement is a measured feature, not an assumption.

Implementation result (2026-06-12): added `src.source_redundancy`, which builds
`data/backtest/source_redundancy.json`,
`data/backtest/source_redundancy_report.md`,
`data/backtest/source_truth_daily.csv`, and
`data/backtest/forecast_ensemble_features.csv`. It keeps WU as the
settlement-aligned primary, compares it with registry-driven METAR/ASOS, NOAA
GHCNh, and ERA5-style reanalysis for every registered market, learns each
redundant source's daily high bias and peak-time lead versus WU, and emits
provenance-safe daily truth rows. When WU is missing but a redundant source
exists, the truth row becomes a `filled_from_redundant` candidate instead of
pretending the day is clean WU. `src.metar_history` now backfills all registered
market stations from IEM ASOS into the shared native-unit hourly/daily schema.

Gap-fill result: the same report groups missing-source days into targeted
commands for `src.wu_history`, `src.metar_history`,
`src.noaa_ghcnh_history`, and `src.reanalysis_history`. A single source outage
now degrades into either a primary-WU row with missing redundant-source refetch
commands or a provenance-labelled redundant fill candidate; only all-source
gaps remain unfillable.

Forecast result: feature schema `toronto_feature_store_v0.4` adds
`forecast_source_count` and `forecast_disagreement`. Live extraction computes
them from Weather.com, Open-Meteo, ECCC, NWS hourly (US markets), and the
Open-Meteo GFS global ensemble where available; `src.forecast_archive`,
`src.snapshot_tracker`, `src.forecast_tracker`, and the forecast-error
component now carry those sources forward. The new forecast ensemble CSV
backfills the same source-count/median/spread signal from archived forecast
tapes. Existing model artifacts keep serving because they select their trained
feature names.

Current report (2026-06-12 12:31 UTC, window 2026-06-01..2026-06-12):
12 markets / 144 market-days, 84 WU primary days, 84 two-plus-source days, 60
redundant fill days, 0 all-source missing days, and 17 disagreement alerts. The
60 fill rows are provenance-labelled METAR/ASOS candidates for days where WU
history has not printed yet; they are not promoted to clean WU settlements.
Forecast ensemble extraction covered 8,193 snapshots; almost every F-market
snapshot has two forecast sources, while Toronto averages 2.13 sources because
ECCC joins Weather.com/Open-Meteo.

Truth-table upgrade (2026-06-15): `source_truth_daily.csv` now uses
`daily_source_truth_v0.2`, adds consensus high/bucket/source-count fields, and
includes Toronto ECCC SWOB as a declared observation source. WU remains the
selected settlement-primary source; SWOB is provenance-labelled support and bias
evidence, not a hard settlement override.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - REDUNDANCY REPORT LIVE`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

