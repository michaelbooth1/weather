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
gap is disciplined promotion: the 2026-06-18 backfills repaired the broad
forecast-payload and source-status artifact gaps, while many input families are
still live-only or mostly-null in historical rows until family-specific backfill
and replay gates catch up.

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

Implemented `weather.reporting.source_gates.source_family_inventory` with JSON and Markdown
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
snapshot folders and 12 active markets. The artifact-aware refresh generated
`2026-06-18T17:24:54Z` correctly reports source-family promotion preflight
`PASS`: 0 active model-input families are blocked. The active candidate
artifact exposes 99 trained features; `settlement_observation`,
`forecast_baseline`, `open_meteo_expanded`, and the `clob_microstructure`
overlay are active and have lineage/parity/ablation evidence. The
forecast-payload backfill rebuilt manifests for 105 legacy folders, and the
refreshed data-layer audit shows `forecast_payload_artifact_rate` PASS at
165/165 forecast folders and `snapshot_artifact_source_status` PASS at 153/153
training-ready folders.

The remaining non-active input-family work is lineage/parity cleanup before any
future retrain can use `nws_grid`, `multi_model_guidance`, `mrms_precip`,
`marine_context`, or `eccc_gridded`. Those families now stay out of the active
promotion preflight until they are backfilled, waived, or explicitly added to a
new trained artifact with matching train/serve evidence.

Verification:
`python -m pytest -q tests/backtesting/test_replay_ablation.py tests/reporting/test_source_family_inventory.py tests/reporting/test_daily_learning.py`

## 2026-07-23 Safety Migration

The v0.1 behavior and counts above remain historical evidence. Operational
consumers now require `source_family_ablation_v0.3` and
`source_family_inventory_v0.2`; the retired v0.1 schemas fail closed.
`source_family_ablation_v0.2` is a separate research-only schema and can never
satisfy a promotion preflight.

Loose `weather.backtesting.replay_ablation` runs now default to research-only
v0.2 output and to a distinct research filename. Producing v0.3 requires the
explicit `--operational-evidence` mode. That mode rejects folder or market
subsets and reconstructed inputs, requires a current pinned promotion corpus
plus sorted, disjoint tune and holdout manifests that exactly partition its
dates, recomputes paired/robustness/market inference, and requires a verified
active-release binding. Detached candidate-artifact bindings are research-only
and always block the operational contract, even when their bytes have a stable
receipt. The downstream contract independently recomputes these relationships,
so changing only the schema string or authorization flag cannot make weak
evidence operational.

Inventory v0.2 records the exact source-ablation path, byte count, and SHA-256
read from one stable byte sequence. Promotion readers re-read that path and
block if it has been replaced since inventory publication. Stale, malformed,
research-only, partially populated, or unbound evidence is reported as an
unsafe-artifact blocker rather than as zero blocked families.

The operational schema has one root model binding. The reanalysis publisher
therefore disables both operational candidate evidence and merging: one root
cannot truthfully bind both the base and masked models. The retained research
implementation reads mutable feature, CLOB, and freshness inputs once and
pre-clones both model arms before either scores. Publication is nevertheless
retired earlier: it blocks before `pickle.loads` because a candidate digest
co-supplied by the caller is not an independent trust anchor. A future research
path needs a verified candidate manifest or release graph; a future operational
schema must additionally represent and validate per-variant bindings under one
sealed generation.

The required regeneration order is:

1. Run active-release operational source ablation into a writable staging
   root outside every input or mirrored data root, for example
   `python -m weather.backtesting.replay_ablation --operational-evidence --corpus <promotion-corpus.json> --tune-dates-file <tune-dates.txt> --holdout-dates-file <holdout-dates.txt> --out <writable-root>/source_family_ablation.md --json-out <writable-root>/source_family_ablation.json`.
2. Build inventory v0.2 from that exact JSON into the same writable staging
   root.
3. Build the physical-family ratchet v0.2 from the staged inventory and
   ablation, then consume it through the promotion reader so current path
   digests are revalidated.

This workstation program did not run those stateful regeneration commands:
the mirrored `data/` tree was explicitly read-only. Existing legacy runtime
artifacts therefore remain blocked until an operator performs the sequence in
an authorized writable environment.

The active operational corpus envelope is now `promotion_corpus_v0.2`.
`promotion_corpus_v0.1` and the separate
`ordinal_smoothing_literal_panel_v0.1` envelope are retired, research-only
inputs: default loaders and every operational source contract reject them.
Plain v0.1 corpora remain rejected even with research opt-in. Only a legacy
envelope carrying the explicit ordinal literal-panel materialization contract
may be loaded for sealed replay, and only by a caller that explicitly opts into
research materialization. Generic replay also
resolves manifest folders beneath the supplied snapshots root, verifies the
exact in-memory scoring frame against the corpus pins, and refuses outputs
inside the data/snapshot trees or aliased to corpus/split inputs.

Current `promotion_allowlist_v0.1` and `mm_known_edge_map_v0.2`
artifacts are recommendation/diagnostic schemas, not authorization envelopes.
Readers canonicalize them to shadow/block and ignore stored permission claims;
every emitted root and row now carries
`serving_or_release_authorization=false`. A future authorization schema must
bind the current source chain, candidate/release, policy, economics, unique
market/date scope, and expiry before it may influence serving or trading.
