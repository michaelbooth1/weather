# 39. Data Layer Audit Findings (2026-06-09) [NEW - OPEN]

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
- [ ] Fix the fleet-wide ERA5 normalize lag: normalized stops at 2026-06-02 while
  raw is fetched to 06-07 (normalize step ~5 days behind fetch).
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

- [ ] **Decide GHCNh + ERA5: integrate or stop committing.** Both are on disk
  (3.6 GB) but wired into NO feature/model/climatology code - only the coverage
  /backfill tooling references them. Either use them (settlement cross-check,
  deeper climatology priors, WU-stale redundancy) or stop collecting/committing.
  Resolves the "gated" status of item 32; model history is effectively WU-only.
- [ ] **Stop committing derived hourly partitions (~3.3 GB in git):** WU 1.3 GB /
  GHCNh 1.2 GB / ERA5 0.8 GB ~ 5,376 JSONL files tracked. Raw is gitignored but
  the rebuildable hourly tier is not. Gitignore `data/**/hourly/` (or move to
  LFS/external); keep only `daily_summary.csv` + manifests tracked.
- [ ] Deepen US history below 2015: GHCNh -> station start, ERA5 -> 1940; gives
  the 11 US cities Toronto-class priors (same adapters, no new integration).
  Extends item 29.
- [ ] Add historical METAR for the 11 US cities -> per-city settlement-lag models
  (today only Toronto has one via SWOB). Extends items 5 and 30.
- [ ] Move model artifacts out of `src/` (13 `.pkl` + weight JSONs mixed into the
  code tree) into an `artifacts/` (or `models/`) dir.

Long-term (the production data layer):

- [ ] Unified per-market daily "truth" table joining WU / METAR / SWOB / GHCNh /
  ERA5 with provenance + a consensus high (today sources are siloed; foundation
  for honest settlement modeling + source-disagreement signal). Extends item 30.
- [ ] Automated ingest quality gate in the loop/CI - block writes failing
  range/gap/dup/schema checks; surface in collection-health (closes item 14,
  feeds item 31).
- [ ] Central schema registry + migration tooling (replace scattered
  `schema_version` strings). Part of item 31.
- [ ] Parquet + per-source freshness SLAs + a coverage/gap dashboard (extend the
  existing `historical_coverage.py`).
- [ ] Evaluate new sources: NWS/NOAA CF6 daily climate reports (official
  daily-max-of-record, settlement-adjacent truth), Meteostat (free long daily
  history), ASOS 1-min/ISD (exact intraday peak timing). Feeds items 29-30.

Acceptance: the `_c` lie is resolved (pooled training unblocked), every market
has working validation, idle sources are either integrated or dropped, and the
repo no longer carries multi-GB regenerable artifacts.

Artifact-path guard update (2026-06-15 UTC): `weather.artifacts` now has focused
unit coverage proving model artifacts route to `artifacts/models/hgb`,
`artifacts/models/coefs`, `artifacts/calibration`, or `artifacts/manifests`
rather than the source tree, with legacy `src/` paths retained only as read
fallback candidates. The `artifact_candidates()` annotation now reflects that
absolute/explicit paths return a variable-length tuple. This does not close the
remaining storage-hygiene decisions: GHCNh/ERA5 integration, derived hourly
partition policy, full model-artifact migration, central schema registry, and CI
ingest gates remain open.

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
