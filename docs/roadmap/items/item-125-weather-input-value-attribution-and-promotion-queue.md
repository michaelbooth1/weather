# 125. Weather Input Value Attribution And Promotion Queue [COMPLETE 2026-06-18 - SOURCE-FAMILY PREFLIGHT LIVE]

Goal: turn the now-broad weather-input surface into a controlled promotion
queue where each source family is either proven useful, explicitly live-only,
or kept out of model influence until train/serve parity and settlement-scored
lift are available.

Source: the 2026-06-18 data-layer audit found that the project is not mainly
blocked by lack of candidate inputs. The registry and feature code already
wire Open-Meteo expanded fields, official NWS grid guidance, multi-model
guidance, MRMS precipitation context, coastal/marine context, ECCC gridded
Toronto context, reanalysis/synoptic features, and market microstructure
features. Official public sources also support useful future lanes, including
Open-Meteo forecast and historical APIs, NWS gridpoint data, NOAA NBM, HRRR,
MRMS, CO-OPS, IEM ASOS one-minute data, and ECCC HRDPS/GeoMet. The remaining
gap is disciplined promotion: only 60 of 165 forecast folders had raw forecast
payload manifests, only 159 of 165 snapshot folders had source-status
artifacts, and many input families are live-only or mostly-null in historical
rows until backfill and replay gates catch up.

Why this matters: adding more adapters can make the model look richer while
silently widening train/serve mismatch. The useful work now is to measure which
source families improve settled performance by market, cutoff, and weather
regime, then promote only the families with durable lift and recoverable
lineage.

Reference source docs checked during the audit:

- Open-Meteo Forecast API: https://open-meteo.com/en/docs
- Open-Meteo historical forecast API: https://open-meteo.com/en/docs/historical-forecast-api
- NWS API and gridpoint docs: https://www.weather.gov/documentation/services-web-api and https://weather-gov.github.io/api/gridpoints
- NOAA NBM, HRRR, and MRMS public datasets: https://registry.opendata.aws/noaa-nbm/ , https://registry.opendata.aws/noaa-hrrr-pds/ , https://registry.opendata.aws/noaa-mrms-pds/
- NOAA CO-OPS API: https://api.tidesandcurrents.noaa.gov/api/prod/
- IEM ASOS download and one-minute archive: https://mesonet.agron.iastate.edu/request/download.phtml and https://mesonet.agron.iastate.edu/request/asos/1min.phtml
- ECCC GeoMet and HRDPS docs: https://api.weather.gc.ca/ and https://eccc-msc.github.io/open-data/msc-data/nwp_hrdps/readme_hrdps_en/

## Design

1. Build a source-family inventory with fields for source, feature columns,
   live availability, historical archive availability, raw payload lineage,
   missingness, model artifact usage, ablation status, and promotion owner.
2. Backfill or explicitly waive missing forecast-payload and source-status
   artifacts before a source family is allowed to claim train/serve parity.
3. Run settlement-scored ablations by source family, including at least:
   Open-Meteo expanded environment, NWS grid, multi-model guidance, MRMS,
   marine/coastal context, ECCC gridded Toronto context, reanalysis/synoptic,
   nearby-station redundancy, and CLOB microstructure.
4. Report lift and harm by market, cutoff hour, missingness regime, source-age
   regime, and warm/cool-side bucket pressure.
5. Promote useful families through candidate artifacts with explicit feature
   manifests and fallback behavior; keep non-proven live-only fields as
   diagnostics until they have evidence or a written live-only policy.
6. Before broadening beyond the 12 active markets, score candidate locations
   from `config/locations.json` for settlement station quality, official
   observation history, forecast-source coverage, timezone/calendar handling,
   and adapter readiness.

- [x] Generate `data/backtest/source_family_inventory.json` and a readable
  report.
- [x] Add a source-family ablation runner or extend the existing ablation gate
  so each broad input family has a comparable lift/harm result.
- [x] Add artifact-lineage checks for forecast payloads and source-status rows
  to the promotion preflight.
- [x] Add a `live_only` promotion policy field for features that are useful
  only in serving but cannot be represented in historical training.
- [x] Add per-market and per-cutoff missingness reports for all candidate
  source families.
- [x] Add a market-expansion source scorecard before enabling additional
  locations from `config/locations.json`.

Acceptance: every weather-input family that influences a production or
candidate model has a source-family inventory row, train/serve parity status,
lineage status, settlement-scored ablation result, and promotion decision.
Future source or market additions must pass the same scorecard instead of
being added because the external API exists.

## Completion Notes

Implemented `weather.reporting.source_family_inventory` with JSON and Markdown
outputs, schema registration, source-family specs, source-status and raw
forecast-payload lineage checks, feature-column missingness by market and
cutoff hour, `live_only` policy fields, CLOB/source-state replay evidence
ingest, and a market-expansion scorecard for `config/locations.json`. Daily
learning now reads `source_family_inventory.json` and turns a failed promotion
preflight into a P0 blocker before training or promotion readiness can pass.

Extended `weather.backtesting.replay_ablation` with broader source-family
variants and `source_family_ablation_v0.1` JSON output. The runner normalizes
archived `NaN` band bounds before scoring and writes variant-level lift/harm
evidence with the same sign convention as the report: positive delta means the
ablated family was helping.

Current production evidence (2026-06-18):
`data/backtest/source_family_inventory.json` covers 11 families across 165
snapshot folders and 12 active markets. It correctly reports `BLOCK`: 10
model-influencing families are blocked by lineage or train/serve parity, while
targeted Atlanta knockout replay supplied evidence for forecast, Open-Meteo,
NWS, multi-model, and MRMS variants, and candidate replay supplied source-state
and CLOB overlay evidence. The generated preflight command preserves the longer
all-market ablation as an explicit evidence job instead of silently promoting
live-only inputs.

Verification:
`python -m pytest -q tests/backtesting/test_replay_ablation.py tests/reporting/test_source_family_inventory.py tests/reporting/test_daily_learning.py`
