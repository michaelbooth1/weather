# 39. Data Layer Audit Findings (2026-06-09) [COMPLETE 2026-06-16 - AUDIT FINDINGS RECONCILED]

Full data-layer audit across all 12 markets. Verdict: broad and well-organized
(per-station roots, manifests, raw->hourly->daily tiers, coverage tool), but with
one latent correctness landmine, ~3.6 GB collected-but-unused, ~3.3 GB of
regenerable artifacts in git, and a deep-history asymmetry (Toronto 44 yrs WU vs
US cities 11 yrs). Measured footprint: WU 3.5 GB, GHCNh 2.7 GB, ERA5 961 MB,
snapshots 708 MB. Items below are scoped here and cross-linked to the broader
Track A/B items they sharpen.

Short-term (correctness + cleanup):

- [x] **P0 - `_c` daily columns hold Fahrenheit for the 11 F markets.** Post
  native-unit refactor the daily writer wrote native values into `max_temp_c` /
  `min_temp_c` / `avg_temp_c` / `max_temp_bucket_c` without converting (verified:
  Miami `max_temp_c`=88, LA=71 are degF). Works today only because every consumer
  operates in native unit (e.g. `backtest.py:102` reads `max_temp_bucket_c` and
  native bucket == settlement bucket). **Blocks pooled/canonical-C training
  (item 33 / 35).** Fix = convert F->C properly, or rename columns to `_native`
  and make any pooling convert explicitly. Audit every `_c` consumer.
- [x] **P1 - `data_auditor.py` only validates Toronto.** Hardcoded to CYYZ,
  months 5-6, Celsius bounds (`>45C impossible`) -> flags ~all F rows as
  impossible. 11/12 markets have no working validation. Make it fleet-aware +
  unit-aware (`all_specs()`, native bounds per `display_unit`). Sharpens items
  14 and 31.
- [x] Delete orphaned pre-per-city `_f` model artifacts: `src/feature_model_hgb_f.pkl`
  (7.4 MB), `src/feature_model_coefs_f.json`, `src/late_day_model_coefs_f.json`
  (superseded by per-city `_<city>` artifacts; verified no code loads them).
  Done 2026-06-13: re-confirmed zero static/dynamic references (no market has
  id `f`, so the `_f` artifact suffix is never generated; the pooled `_f_pooled`
  artifacts are separate and still used), then `git rm`'d all three. Per-market
  HGB bundles still load for Toronto/NYC/Miami after removal.
- [x] Backfill `forecast_history` for Atlanta (katl) + Miami (kmia) - currently
  10/12 stations; their forecast-archive features are starving.
  Done 2026-06-13: ran `src.forecast_history --market {atlanta,miami} backfill`.
  Both now hold 333 native-unit (degF) forecast-days, 2018-2026 (the Open-Meteo
  historical-forecast archive starts 2018; 2015-2017 return HTTP 400 and are
  skipped), matching the other 10 markets -> forecast-archive coverage is now
  12/12. Also fixed the cosmetic backfill log that printed degF values with a
  hardcoded " C" label (now uses `spec.display_unit`). The data unblocks a future
  Atlanta/Miami feature-model retrain with non-NaN forecast columns (the retrain
  itself is downstream of this data fix).
- [x] Fix the fleet-wide ERA5 normalize lag: normalized stops at 2026-06-02 while
  raw is fetched to 06-07 (normalize step ~5 days behind fetch).
  Done 2026-06-15: bounded coverage checks now show the original June 1-7
  normalize lag is gone across the fleet, with normalized reanalysis daily rows
  through 2026-06-09 anywhere the raw payloads contain usable temperature
  values. `ReanalysisStore.coverage()` now separates true normalize lag from
  source-availability lag: `raw_only_normalizable_*` counts raw days that have
  non-null `temperature_2m` but no normalized daily row, while
  `raw_only_source_lag_*` counts raw payload days that are all-null and cannot
  normalize yet. The data-layer audit gate now warns only on normalizable
  raw-only days. Validation on 2026-06-08 through 2026-06-14 reported
  `0` normalizable raw-only days and `60` all-null source-lag days across the
  12 markets, so the old rebuild/normalize lag is resolved and the remaining
  raw-only tail is explicit source lag. Focused tests:
  `tests\sources\test_historical_sources.py` and
  `tests\reporting\test_data_layer_audit.py` pass.
- [x] Backfill Toronto may-29 snapshot gap (if recoverable) and re-collect
  Denver (kbkf) WU sparse/missing days (10 calendar-missing + 17 sparse vs ~1/5
  for peers).
  Resolved 2026-06-13: both moot. (1) The may-29 snapshot gap is UNRECOVERABLE --
  there is no `...-toronto-on-may-29-2026` folder at all (tapes jump may-28 ->
  may-30), and live multi-source market/model snapshot state cannot be
  reconstructed after the fact; nothing to backfill. (2) Denver WU is now healthy
  for the high-temp seasonal window: `wu_history --market denver coverage
  2019..2025` reports only 5 missing days, all off-season (2020-11-08,
  2021-01-21..23, 2021-02-20), with raw_days=5016 -- the later wide backfills
  already closed the 2026-06-09 sparsity finding, so there is nothing
  season-relevant to re-collect.

Medium-term (integration + storage hygiene):

- [x] **Decide GHCNh + ERA5: integrate or stop committing.** Original audit
  finding: both were on disk (3.6 GB) without feature/model/climatology wiring
  beyond coverage and backfill tooling. Either use them (settlement cross-check,
  deeper climatology priors, WU-stale redundancy) or stop collecting/committing.
  Decision 2026-06-15: keep and integrate them as non-serving source-reliability
  and redundancy inputs, while keeping same-day settlement truth WU-primary.
  `src.weather.reporting.source_redundancy` joins WU, METAR/ASOS, GHCNh, and
  ERA5-style reanalysis into provenance-safe daily truth rows, source bias stats,
  gap-fill candidates, and disagreement alerts. `pooled_feature_model` consumes
  the same indexes as static source-reliability priors (`source_ghcnh_*` and
  `source_reanalysis_*`) for the pooled v0.3 band candidate, and replay
  reconstruction attaches those priors without same-day final redundant highs.
  The serialized `feature_model_hgb_f_pooled_v0_3.pkl` contains all six
  GHCNh/ERA5 reliability columns for every trained cutoff hour 07-20. Focused
  regression coverage: `tests\calibration\test_pooled_feature_model.py` now
  asserts GHCNh/reanalysis bias/MAE/bucket-match prior generation, and
  `tests\reporting\test_source_redundancy.py` keeps the provenance-safe
  redundancy table live. Item 32 remains gated only for true synoptic/reanalysis
  feature families (upper-air, soil, teleconnections), not for the basic
  GHCNh/ERA5 use-or-drop decision.
- [x] **Stop committing derived hourly partitions (~3.3 GB in git):** WU 1.3 GB /
  GHCNh 1.2 GB / ERA5 0.8 GB ~ 5,376 JSONL files tracked. Raw is gitignored but
  the rebuildable hourly tier is not. Gitignore `data/**/hourly/` (or move to
  LFS/external); keep only `daily_summary.csv` + manifests tracked.
  Reconciled 2026-06-15: the repo now ignores `data/` wholesale, and
  `git ls-files data` returns zero tracked data files, including zero
  `data/**/hourly/` partitions. This is stricter than the original "keep
  daily_summary + manifests tracked" option and satisfies the storage-hygiene
  requirement that multi-GB regenerable data artifacts are no longer carried in
  git.
- [x] Transfer deep US history below 2015 to item 29: GHCNh -> station start,
  ERA5/reanalysis -> older archive depth, and source-limited production window
  policy belong to the historical-record acceptance path, not this audit-cleanup
  item.
  Reconciled 2026-06-16: `data/backtest/item39_data_layer_audit_closure_report.md`
  shows 2000-2026 US GHCNh and reanalysis target-season coverage at about 99.6%
  for the 11 US markets, while pre-2015 Weather.com history remains explicitly
  provider-unavailable and owned by item 29.
- [x] Add historical METAR for the 11 US cities -> per-city settlement-lag models.
  Done 2026-06-16: IEM ASOS/METAR history now covers the 2000-2026 target
  season at 100.0% for all 11 US markets in
  `data/backtest/item39_data_layer_audit_closure_report.md`, and
  per-market settlement-lag artifacts exist under
  `artifacts/calibration/settlement_lag_model_<market>.json` with family
  summary evidence in `data/backtest/f_family_secondary_artifacts_report.md`.
- [x] Move model artifacts out of `src/` (13 `.pkl` + weight JSONs mixed into the
  code tree) into an `artifacts/` (or `models/`) dir.
  Reconciled 2026-06-15: no `.pkl` or model-weight JSON artifacts are tracked
  under `src/`; tracked model artifacts now live under `artifacts/models/hgb`,
  `artifacts/models/coefs`, `artifacts/calibration`, and `artifacts/manifests`.
  `tests/test_artifacts.py` verifies the read/write path policy, with legacy
  `src/` locations retained only as read fallbacks for old local worktrees.

Long-term (the production data layer):

- [x] Unified per-market daily "truth" table joining WU / METAR / SWOB / GHCNh /
  ERA5 with provenance + a consensus high (today sources are siloed; foundation
  for honest settlement modeling + source-disagreement signal). Extends item 30.
  Done 2026-06-15: `src.weather.reporting.source_redundancy` now writes
  `daily_source_truth_v0.2` rows with `consensus_high`, `consensus_bucket`,
  `consensus_source_count`, and `consensus_sources`, while preserving WU as the
  selected settlement-primary source. Toronto's declared ECCC SWOB source is
  joined into the daily truth table and bias report; US markets do not list SWOB
  as a missing source. The model-facing `FALLBACK_ORDER` stayed unchanged so the
  pooled source-reliability priors are not silently reshaped by this reporting
  upgrade. Evidence artifact:
  `data\backtest\item39_source_truth_daily_v0_2.csv` has 252 fleet rows for
  2026-05-25..2026-06-14, all schema `daily_source_truth_v0.2`; 240 rows have a
  non-empty consensus high, and 3 Toronto rows include SWOB in `source_values`.
  Focused tests: `tests\reporting\test_source_redundancy.py` asserts SWOB join,
  consensus median/bucket fields, SWOB-vs-WU bias, and CSV flattening.
- [x] Automated ingest quality gate in the loop/CI - block writes failing
  range/gap/dup/schema checks; surface in collection-health (closes item 14,
  feeds item 31).
  Done 2026-06-15: `src.weather.operations.daily_refresh` now runs an
  `ingest_quality_gate` step immediately after the reanalysis refresh and writes
  durable `data\backtest\ingest_quality_gate.json` /
  `data\backtest\ingest_quality_gate_report.md` artifacts. The step is visible
  in dry-run plans, daily-refresh reports, and `pipeline_summary`; scheduled/CI
  callers can make the refresh fail closed with `--fail-on-ingest-quality`.
  `src.weather.reporting.data_auditor` now treats daily-summary schema errors as
  corruption alongside duplicate timestamps and impossible values, while missing
  or sparse target-window days remain WARN-level gap evidence. Evidence run
  scoped to 2026 produced `WARN`: 12 market audits ran, 0 missing audit results,
  0 schema-error markets, 0 duplicate-timestamp markets, 0 impossible-value
  markets, and 12 markets with missing target-window days. Focused tests:
  `tests\operations\test_daily_refresh.py` covers the new step, dry-run
  planning, artifact writes, and critical fail-on behavior; `tests\reporting
  \test_data_auditor.py` covers schema errors as corruption.
- [x] Central schema registry + migration tooling (replace scattered
  `schema_version` strings). Part of item 31.
- [x] Parquet + per-source freshness SLAs + a coverage/gap dashboard (extend the
  existing `historical_coverage.py`).
- [x] Evaluate new sources: NWS/NOAA CF6 daily climate reports (official
  daily-max-of-record, settlement-adjacent truth), Meteostat (free long daily
  history), ASOS 1-min/ISD (exact intraday peak timing). Feeds items 29-30.
  Reconciled 2026-06-16: `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md`
  records the free-source audit. Item 77 owns the one-minute ASOS spike/timing
  layer, item 81 owns Meteostat and NASA POWER supplemental fallback policy,
  and item 75 owns US NWS grid/multimodel guidance. CF6 is not adopted as a
  separate current adapter in this slice because the settlement-adjacent truth
  role is already covered by WU primary, METAR/ASOS, GHCNh/reanalysis,
  validated supplemental stations, and the new source-adoption gates; any
  future official-daily replacement should be scoped through items 29/30 rather
  than keeping this audit item open.

Acceptance: the `_c` lie is resolved (pooled training unblocked), every market
has working validation, idle sources are either integrated or dropped, and the
repo no longer carries multi-GB regenerable artifacts.

Artifact-path guard update (2026-06-15 UTC): `weather.artifacts` now has focused
unit coverage proving model artifacts route to `artifacts/models/hgb`,
`artifacts/models/coefs`, `artifacts/calibration`, or `artifacts/manifests`
rather than the source tree, with legacy `src/` paths retained only as read
fallback candidates. The `artifact_candidates()` annotation now reflects that
absolute/explicit paths return a variable-length tuple.

Schema-registry update (2026-06-15 UTC): `weather.schema_registry` now owns a
central inventory for public artifact schema versions and exposes migration
audit tooling via `python -m src.schema_registry`. High-traffic producers now
consume registry constants directly (`feature_store`, `historical_coverage`,
`market_registry`, WU daily summaries, `daily_refresh`, `observation_trigger`,
and settlement ledgers). The registry also inventories legacy/current schema
versions discovered across `src`; strict audit writes
`data/backtest/schema_registry_audit.json` and passes with `65` registered
schemas, `124` discovered literals, and `0` unregistered schema versions.
Focused tests: `tests\operations\test_schema_registry.py`,
`tests\sources\test_historical_sources.py`, `tests\market\test_market_config.py`,
`tests\model\test_feature_store.py`, `tests\market\test_market_day_labels.py`,
and `tests\operations\test_daily_refresh.py` pass.

Historical coverage dashboard update (2026-06-15 UTC):
`src.historical_coverage dashboard` now produces a normalized per-market/source
dashboard with coverage status, gap counts, artifact presence, per-source
freshness SLA status, Markdown, JSON, CSV, and Parquet outputs. The dashboard
schema is registered as `historical_coverage_dashboard_v0.1`; default artifacts
write to `data/backtest/historical_coverage_dashboard.{json,md,csv,parquet}`.
Focused coverage in `tests\sources\test_historical_sources.py` verifies stale
and missing-source classification plus JSON/Markdown/CSV/Parquet rendering.
Smoke command:
`.\venv\Scripts\python.exe -m src.historical_coverage dashboard --markets nyc
--start 2026-06-01 --end 2026-06-02 --as-of 2026-06-15` passed.

P0 unit-contract fix (2026-06-11): `src.daily_summary` now centralizes
native-vs-Celsius daily-summary reads, `src.wu_history` writes
`wu_daily_native_v2` with explicit `*_native` columns and true Celsius `*_c`
columns, and all 12 WU normalized stores were rebuilt from local raw payloads.
Spot check: NYC June 7 is native `81 F` with `max_temp_c=27.2222`; Toronto June
7 remains `24 C`. Native settlement/model readers now prefer
`max_temp_bucket_native` / `max_temp`, while the storage layer is safe for
canonical-C pooling. The pooled trainer also filters implausible native buckets
(found and excluded Miami 2005-06-11 at impossible `171 F`).

P1 fleet-aware auditor fix (2026-06-11): `src.data_auditor` now uses
`all_specs()`, per-market `data_root`, daily-summary native/C helpers, and
native temperature bounds (`F` and `C`) instead of hardcoded CYYZ/Celsius
assumptions. It exposes `--fleet --json --strict` for automation and feeds the
fleet observability report. Spot checks cleared the false NYC/Denver F-market
pressure/temperature alerts while preserving the true Miami 2005-06-11
`171 F` critical. Follow-up on 2026-06-14 quarantined that impossible raw WU row
during normalization; Miami 2005-06-11 now rebuilds to `86 F`, and fleet strict
audits report zero impossible values.

Completion update (2026-06-16 UTC): the original audit findings have either
been fixed or moved to their durable roadmap owners. Unit correctness, fleet
validation, source-redundancy integration, storage hygiene, artifact-path
policy, schema registry, freshness/dashboard reporting, ingest gates, and
source evaluation are no longer open Item39 work. The closure audit
`data/backtest/item39_data_layer_audit_closure_report.md` still has gate status
`FAIL`, but its blockers are operational/live-tape follow-ups already routed to
item 36 (legacy replay inputs), items 3/22/30 (forecast payload issue metadata),
items 17/37 (source-status latency rows), and item 29 (remaining source-depth
policy). Item39 is therefore closed as an audit-reconciliation item, not as a
claim that every downstream data-system improvement is finished.
