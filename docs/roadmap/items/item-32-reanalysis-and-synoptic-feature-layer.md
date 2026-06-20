# 32. Reanalysis And Synoptic Feature Layer [PARTIAL 2026-06-19 - RICH+PRESSURE REPLAY BLOCKED]

Goal: add physically meaningful, multi-decade-consistent inputs the obs-only set
lacks.

- [x] ERA5 antecedent-day state sidecar, with future soil/cloud/radiation/VPD/ET0
  archive fields wired into the reanalysis fetch plan.
- [x] Pressure-level upper-air source for 850 mb temperature, 500 mb height, and
  thickness. Open-Meteo Historical Weather / ERA5 archive did not populate the
  forecast-style pressure-level fields in the 2026-06-16 probe, so the
  sidecar now uses an explicit cached NOAA PSL NCEP/NCAR daily pressure-level
  NetCDF source for those fields.
- [x] Teleconnection indices (ENSO/PNA), coastal sea-breeze and continentality
  flags per city.
- [x] Add only behind the model harness (item 36); keep broad feature-family
  influence blocked unless settlement-scored gates show out-of-sample skill.
- [ ] Promote or split narrower per-market/subfamily lanes only after the mixed
  market-level reanalysis gates clear. Reanalysis ablation quarantine still
  covers Chicago, Denver, NYC, San Francisco, and Toronto; full replay promotion
  blockers are Austin, Chicago, NYC, San Francisco, and Seattle.

Acceptance: each new feature family earns its place via settlement-scored
validation, not importance charts (extends item 27 to all markets).

## 2026-06-16 update

- Added `reanalysis_synoptic_features_v0.1` as a gated sidecar instead of
  changing the shared historical hourly schema. The feature-store schema is now
  `toronto_feature_store_v1.4`, and live serving receives null defaults unless
  a validated artifact explicitly uses the sidecar.
- Built the Toronto sidecar:
  `data/backtest/item32_reanalysis_synoptic_toronto_summary.json` and
  `data/backtest/item32_reanalysis_synoptic_toronto_report.md`. Coverage:
  9,658 rows from 2000-01-01 through 2026-06-10, with 9,657 antecedent-day
  rows. Existing archives populate antecedent temperature, dewpoint, wind, gust,
  pressure, heat-anomaly, coastal, and continentality fields; newly requested
  soil/cloud/radiation/VPD/ET0 fields will populate after rich reanalysis
  backfills refresh raw archive chunks.
- Ran the settlement-scored Item 27 gate for Toronto:
  `data/wunderground/cyyz/analysis/item27_feature_value_gate.json`. The broad
  `reanalysis_synoptic` family was blocked on 9,100 held-out rows
  (`delta_logloss=-0.0045`, `delta_brier=-0.0021`), so no feature promotion was
  made.
- Remaining work: add a pressure-level reanalysis source, add ENSO/PNA index
  ingestion, rebuild rich raw reanalysis chunks for soil/cloud/radiation fields,
  and rerun settlement-scored gates market-by-market or with a narrower family
  before promotion.

## 2026-06-16 teleconnection/static-context update

- Bumped the gated sidecar to `reanalysis_synoptic_features_v0.2` and the
  shared feature-store schema to `toronto_feature_store_v1.5`.
- Added sidecar columns for static sea/lake-breeze context from the existing
  marine-context registry: sea-breeze context flag, lake-breeze context flag,
  nearest configured water distance, and marine-context station count. The
  existing coastal and continentality fields remain in the same gated family.
- Added local NOAA CPC teleconnection ingestion for ONI and PNA snapshots:
  `data/backtest/item32_teleconnections/oni.ascii.txt` from
  `https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt` and
  `data/backtest/item32_teleconnections/pna.monthly.ascii` from
  `https://www.cpc.ncep.noaa.gov/products/precip/CWlink/pna/norm.pna.monthly.b5001.current.ascii`.
  Serving/training rows use only the latest completed month or season available
  before the target month, so target-month teleconnection values do not leak
  into historical features.
- Rebuilt the Toronto sidecar at
  `data/reanalysis/cyyz/features/reanalysis_synoptic_features.csv` and wrote
  audit artifacts:
  `data/backtest/item32_reanalysis_synoptic_toronto_v02_summary.json` and
  `data/backtest/item32_reanalysis_synoptic_toronto_v02_report.md`. Coverage is
  9,658 rows from 2000-01-01 through 2026-06-10; the new static and
  teleconnection fields are present on all rows.
- Reran the settlement-scored Item 27 gate for Toronto:
  `python -m src.feature_model --market toronto --item27-report-only --item27-folds 5`.
  The broad `reanalysis_synoptic` family remains blocked on held-out scoring
  (`delta_logloss=-0.0118`, `delta_brier=-0.0047`), so no feature promotion was
  made.
- Remaining work: add a pressure-level reanalysis source for 850 mb
  temperature, 500 mb height, and thickness; backfill rich raw reanalysis chunks
  for the still-empty soil/cloud/radiation/VPD/ET0 fields; and test narrower
  subfamilies before any promotion.

## 2026-06-18 audit disposition

The Python audit found no additional code bug to close inside the previously
implemented sidecar, teleconnection, static-context, or gate paths. Follow-up
implementation added a cache-only NOAA PSL NCEP/NCAR daily pressure-level
source: `python -m weather.sources.reanalysis_synoptic --market <market>
download-pressure-level --start YYYY-MM-DD --end YYYY-MM-DD` downloads yearly
`air` and `hgt` NetCDF files, and the normal sidecar build merges previous-day
850 hPa temperature, 500 hPa height, and 1000-500 hPa thickness when cached
files exist. The item remains partial because the new fields still need real
market backfills, sidecar rebuilds, and settlement-scored gates before any
promotion.

## 2026-06-18 all-market sidecar and gate refresh

Rebuilt `reanalysis_synoptic_features.csv` sidecars for all 12 active markets
from the existing `data/reanalysis/<station>/daily/daily_summary.csv` archives.
`weather.reporting.source_family_inventory` now scans those historical sidecar
files directly instead of treating live snapshot `features_long.csv` null
defaults as missing historical rows. The regenerated inventory reports
`reanalysis_synoptic` as lineage `PASS`, train/serve parity `PASS`, 115,896
sidecar rows, and settlement-scored ablation `PRESENT`.

Refreshed the Item 27 feature-value gate for all 12 active markets. Aggregate
reanalysis evidence is positive on the held-out gate (`+0.0113` Brier delta,
76,957 rows; positive means removing reanalysis hurt the model), so the source
family preflight now classifies `reanalysis_synoptic` as
`PROMOTION_CANDIDATE` rather than `BLOCK_PARITY`. The item remains partial
because market-level gates are mixed. Positive deltas below mean reanalysis
helped because removing it worsened held-out Brier.

| Market | Rows | Delta Brier | Gate |
| :--- | ---: | ---: | :--- |
| Austin | 5,782 | +0.0421 | promote lane candidate |
| Miami | 6,230 | +0.0366 | promote lane candidate |
| Houston | 6,216 | +0.0347 | promote lane candidate |
| Dallas | 6,202 | +0.0336 | promote lane candidate |
| Los Angeles | 6,146 | +0.0180 | promote lane candidate |
| Atlanta | 6,202 | +0.0147 | promote lane candidate |
| Seattle | 6,229 | +0.0015 | promote lane candidate, thin margin |
| San Francisco | 6,216 | -0.0019 | block |
| NYC | 6,202 | -0.0030 | block |
| Chicago | 6,216 | -0.0077 | block |
| Toronto | 9,100 | -0.0091 | block |
| Denver | 6,216 | -0.0121 | block |

Next work is a narrower per-market or subfamily promotion lane rather than a
broad all-market cutover. The positive markets can move into a guarded
candidate/shadow lane now; blocked markets need subfamily diagnostics before
they are allowed to influence a served artifact.

Follow-up implementation in `weather.reporting.source_family_inventory` now
keeps those Item 27 per-market gates in
`data/backtest/source_family_inventory.json` under
`reanalysis_synoptic.ablation.market_details`, plus `positive_markets` and
`blocked_markets`. The regenerated report includes a `Reanalysis Market Gates`
table, so the positive-market lane is no longer tracked only in roadmap prose.

## 2026-06-18 positive-market lane contract

`weather.reporting.source_family_inventory` now emits an explicit
`reanalysis_synoptic.promotion_lane` contract instead of only a broad
`PROMOTION_CANDIDATE` family decision. The regenerated
`data/backtest/source_family_inventory.json` and
`data/backtest/source_family_inventory_report.md` classify the lane as
`PARTIAL_POSITIVE_MARKET_SHADOW_LANE` with policy `positive_markets_only`.

Allowed markets are Atlanta, Austin, Dallas, Houston, Los Angeles, Miami, and
Seattle. Quarantined markets are Chicago, Denver, NYC, San Francisco, and
Toronto. Seattle is flagged as a thin-margin allowed market because its
positive Item 27 Brier delta is only `+0.0015`, below the `0.0030` thin-margin
threshold.

This did not complete Item 32 because no served, full-corpus shadow, or
promotion artifact had consumed the lane. It removed ambiguity from the next
implementation step: train or replay a reanalysis-enabled candidate only for
the allowed markets, keep quarantined markets on the no-reanalysis path, and
require candidate replay to preserve per-market current/market gates before
promotion. The bounded smoke in the following update exercises that plumbing
but is not promotion evidence.

Verification:
`python -m pytest tests\reporting\test_source_family_inventory.py -q` passed
with `9 passed`, and
`python -m weather.reporting.source_family_inventory --snapshots-root data\snapshots --backtest-root data\backtest --ablation-json data\backtest\source_family_ablation.json --candidate-replay-json data\backtest\pooled_candidate_replay_latest.json`
regenerated the inventory and report with status `PASS`.

## 2026-06-18 lane-aware training/replay plumbing update

`weather.calibration.pooled_feature_model` now accepts
`--reanalysis-lane-json`, reads either the source-family inventory or a direct
promotion-lane JSON payload, and masks `reanalysis_synoptic` feature values for
markets outside `promotion_lane.allowed_markets`. Lane metadata is written into
the artifact as `source_family_lanes.reanalysis_synoptic` and
`reanalysis_promotion_lane`. Quarantined markets also receive
`current_blend_market_alpha = 0.0`, so a replayed lane artifact falls back to
the incumbent/current path for Chicago, Denver, NYC, San Francisco, and
Toronto.

`weather.calibration.pooled_candidate_replay` now detects artifacts with
reanalysis feature names or a reanalysis lane contract, loads the matching
market sidecar during replay feature reconstruction, and applies the same lane
mask before scoring. A focused replay-feature smoke against
`data/backtest/item32_reanalysis_positive_market_lane_eval_smoke.pkl` loaded
sidecars for Austin and NYC, preserved Austin reanalysis values
(`reanalysis_synoptic_available=1.0`, `reanalysis_prev_day_max_temp=90.1`),
and masked NYC to `reanalysis_synoptic_available=0.0` with null reanalysis
values.

Smoke training evidence:

- `python -m weather.calibration.pooled_feature_model --objective band --reanalysis-lane-json data\backtest\source_family_inventory.json --max-days-per-market 60 --artifact data\backtest\item32_reanalysis_positive_market_lane_eval_smoke.pkl --out data\backtest\item32_reanalysis_positive_market_lane_eval_smoke_training_report.md --holdout-year 2025`
  wrote a lane-aware F-family band artifact over 9,240 source rows.
- The smoke artifact has 14 hourly models, 222 total feature names, 40
  `reanalysis_` feature names, and the
  `PARTIAL_POSITIVE_MARKET_SHADOW_LANE` metadata embedded.
- The training report shows blocked-validation audit `PASS` for all 14 cutoff
  hours, 165 source-eval rows per hour, and postprocess Brier improving from
  raw in every reported hour. This is only a bounded plumbing smoke, not a
  promotion replay.

Current data coverage is no longer 100% missing for the useful antecedent
surface/static sidecar fields: in the late-2025/2026 sidecar window each active
market has 253 available sidecar rows, and allowed-market training rows carried
21 populated `reanalysis_` columns. The richer columns still need backfill:
pressure-level values, soil temperature/moisture, VPD/ET0,
shortwave-radiation, cloud layers, and teleconnection lag fields remain empty
in the current smoke window.

This bounded smoke did not complete Item 32. The next update records the full
no-cap lane-aware train plus pinned candidate replay, which removes the missing
full-artifact blocker but still fails promotion quality gates.

Verification:

- `python -m pytest tests\calibration\test_pooled_feature_model.py tests\calibration\test_pooled_candidate_replay.py tests\reporting\test_source_family_inventory.py -q`
  passed with `83 passed`.

## 2026-06-18 full lane-aware replay update

The full no-cap lane artifact now exists and has pinned replay evidence. This
removes the previous "full artifact has not completed" blocker, but it does not
complete Item 32 because the replay is still outside market tolerance.

Training:
`python -m weather.calibration.pooled_feature_model --objective band --max-days-per-market 0 --holdout-year 2025 --reanalysis-lane-json data\backtest\source_family_inventory.json --artifact data\backtest\item32_reanalysis_positive_market_lane_full_candidate.pkl --out data\backtest\item32_reanalysis_positive_market_lane_full_training_report.md`
wrote a full F-family lane-aware band artifact over 67,857 source rows. The
artifact has 14 hourly models, schema `pooled_feature_band_hgb_v0.3`, feature
schema `toronto_feature_store_v1.6`, 222 feature names, 40 `reanalysis_`
features, and the embedded `PARTIAL_POSITIVE_MARKET_SHADOW_LANE` contract.
Blocked-validation audit passed with zero leaks for every cutoff hour. The weak
input-family preflight remains `WARN`; sparse pressure-level, soil,
radiation/cloud, VPD/ET0, and teleconnection lag fields still need real
backfill.

Replay:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item32_reanalysis_positive_market_lane_full_candidate.pkl --out data\backtest\item32_reanalysis_positive_market_lane_full_replay_report.md --json-out data\backtest\item32_reanalysis_positive_market_lane_full_replay.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --disable-candidate-variant-export --skip-microstructure-overlay --disable-long-job-guard`
scored 67,430 F-family rows across 51 market-days, excluded 9,449 non-F rows,
and had zero missing candidate rows. The replay verdict is `BLOCK`,
market-only verdict `PARTIAL_PASS`, and cutover decision `DO_NOT_CUT_OVER`.
Aggregate candidate Brier is `0.042963` versus current `0.043554` and market
`0.037869`, a `-0.000591` delta versus current but `+0.005094` versus market.
Daily-first candidate Brier is `0.042903` versus current `0.043496` and market
`0.037830`, leaving a `+0.005073` market gap.

Per-market action is generated and mixed: Atlanta, Houston, and Los Angeles are
candidate cutover-ready; Dallas, Denver, and Miami continue shadow; Austin,
Chicago, NYC, San Francisco, and Seattle remain blocked by daily-first market
tolerance. Reanalysis sidecars loaded during replay for all F markets, and
quarantined markets stayed on current/no-reanalysis behavior.

Next work is no longer "run the full artifact." The remaining Item 32 unblock
path is to backfill the sparse rich reanalysis fields, diagnose why allowed
markets Austin and Seattle still trail market, keep quarantined markets masked
until their own gates clear, and rerun the full lane replay plus Item
27/source-family gates before any promotion.

## 2026-06-18 rich recent reanalysis refresh update

The sparse-rich-field blocker now has a concrete refresh path and a measured
replay result. `weather.sources.reanalysis_history` gained a guarded
`--refresh-missing-hourly-variables` mode: with `--skip-existing`, the queue now
treats cached raw dates as missing unless they contain non-null values for the
required rich hourly variables. This fixes the stale-cache failure where old
Open-Meteo raw payloads had normalized temperature coverage but all-null soil,
cloud, radiation, VPD, and ET0 variables, so the ordinary missing-date queue
incorrectly skipped them.

Recent rich refresh:
`python -m weather.sources.reanalysis_history --market <market> backfill --start 2026-06-01 --end 2026-06-13 --chunk-days 31 --sleep 0.05 --skip-existing --refresh-missing-hourly-variables`
was run for all 12 active markets. The sidecars were then rebuilt with the
local ONI/PNA snapshots:
`python -m weather.sources.reanalysis_synoptic --market <market> build --oni-path data\backtest\item32_teleconnections\oni.ascii.txt --pna-path data\backtest\item32_teleconnections\pna.monthly.ascii`.
The rich-variable queue is now empty for June 1-13 across all 12 markets, and
sampled sidecars have 12 of 12 June 2-13 rows populated for soil temperature,
soil moisture, VPD, ET0, shortwave radiation, low/mid/high cloud cover, and
lagged ONI/PNA.

Rich-recent lane training:
`python -m weather.calibration.pooled_feature_model --objective band --max-days-per-market 0 --holdout-year 2025 --reanalysis-lane-json data\backtest\source_family_inventory.json --artifact data\backtest\item32_reanalysis_rich_recent_lane_candidate.pkl --out data\backtest\item32_reanalysis_rich_recent_lane_training_report.md`
completed over 67,857 source rows with 14 hourly models and zero blocked-split
leaks. The training stderr still emitted all-missing imputer warnings for the
rich reanalysis fields, which is useful evidence: refreshing only the recent
promotion window makes replay features richer, but it is not yet enough
historical coverage for the full training matrices to learn those fields
reliably.

Pinned replay:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item32_reanalysis_rich_recent_lane_candidate.pkl --out data\backtest\item32_reanalysis_rich_recent_lane_replay_report.md --json-out data\backtest\item32_reanalysis_rich_recent_lane_replay.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --disable-candidate-variant-export --skip-microstructure-overlay --disable-long-job-guard`
scored the same 67,430 F-family rows with zero missing candidate rows and kept
the verdict at `BLOCK`, market-only verdict `PARTIAL_PASS`, and cutover
decision `DO_NOT_CUT_OVER`.

The replay did improve the boundary. Aggregate candidate Brier moved from
`0.042963` to `0.042871` versus current `0.043554` and market `0.037869`.
Daily-first candidate Brier moved from `0.042903` to `0.042810`, shrinking the
daily-first market gap from `+0.005073` to `+0.004981`. Austin moved from
blocked to pass: candidate `0.0391`, current `0.0414`, market `0.0362`, delta
versus market `+0.0029`, within the `0.0030` tolerance. Candidate cutover-ready
markets are now Atlanta, Austin, Houston, and Los Angeles; Dallas, Denver, and
Miami remain shadow; Chicago, NYC, San Francisco, and Seattle remain blocked.

This still does not complete Item 32. The next unblock is a wider historical
rich refresh, not another recent-window-only replay: backfill at least the
2025 holdout and a broader training window for the rich Open-Meteo fields,
rebuild sidecars with ONI/PNA, retrain the lane, and rerun the pinned replay
plus Item 27/source-family gates. Seattle also needs targeted diagnostics
because it improved only slightly and still trails market by `+0.0144`.

## 2026-06-19 rich 2024-2025 reanalysis replay update

The wider rich refresh path was exercised against the training window, not just
the June 2026 replay window. The guarded refresh queue is now empty for all 12
active markets over 2024, 2025, and June 1-13 2026. Rebuilt sidecars have 365
of 365 rows populated for 2024-01-02 through 2024-12-31 for soil temperature,
soil moisture, VPD, ET0, shortwave radiation, low/mid/high cloud cover, and
lagged ONI/PNA. The training stderr no longer lists those rich fields as
all-missing; only the separate pressure-level reanalysis fields remain
all-missing in the current matrices.

Refresh and rebuild commands:
`python -m weather.sources.reanalysis_history --market <market> backfill --start 2024-01-01 --end 2024-12-31 --chunk-days 31 --sleep 0.05 --skip-existing --refresh-missing-hourly-variables`
and
`python -m weather.sources.reanalysis_synoptic --market <market> build --oni-path data\backtest\item32_teleconnections\oni.ascii.txt --pna-path data\backtest\item32_teleconnections\pna.monthly.ascii`
were run for every active market.

Training:
`python -m weather.calibration.pooled_feature_model --objective band --max-days-per-market 0 --holdout-year 2025 --reanalysis-lane-json data\backtest\source_family_inventory.json --artifact data\backtest\item32_reanalysis_rich_2024_2025_lane_candidate.pkl --out data\backtest\item32_reanalysis_rich_2024_2025_lane_training_report.md`
wrote a full F-family lane artifact over 67,857 rows. Blocked-validation audits
passed for all 14 hourly models, and the fitted matrices retained 222 columns.

Pinned replay:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item32_reanalysis_rich_2024_2025_lane_candidate.pkl --out data\backtest\item32_reanalysis_rich_2024_2025_lane_replay_report.md --json-out data\backtest\item32_reanalysis_rich_2024_2025_lane_replay.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --disable-candidate-variant-export --skip-microstructure-overlay --disable-long-job-guard`
still reports `BLOCK`, market-only verdict `PARTIAL_PASS`, and cutover
`DO_NOT_CUT_OVER`.

The wider history did not improve the candidate versus the rich-recent replay.
Aggregate candidate Brier is `0.042932` versus current `0.043554` and market
`0.037869`, leaving a `+0.005063` market gap. Daily-first candidate Brier is
`0.042872` versus current `0.043496` and market `0.037830`, leaving a
`+0.005042` market gap. This is slightly better than the original full lane
(`+0.005073` daily-first market gap), but worse than the rich-recent artifact
(`+0.004981`).

Per-market action is unchanged from the rich-recent replay: Atlanta, Austin,
Houston, and Los Angeles are candidate cutover-ready; Dallas, Denver, and
Miami remain shadow; Chicago, NYC, San Francisco, and Seattle remain blocked.
The material regressions versus rich-recent are Atlanta (`0.0363` versus
`0.0356`) and Seattle (`0.03853` versus `0.03853` rounded, with a slightly
worse market gap). Houston improves slightly.

The source-family gate was rerun two ways. The canonical inventory using
`data\backtest\pooled_candidate_replay_latest.json` remains `PASS` with zero
active model-input blockers. The Item 32 experimental inventory saved at
`data\backtest\item32_reanalysis_rich_2024_2025_source_family_inventory.json`
also reports `PASS` after `weather.reporting.source_family_inventory` was
tightened to count only imputer-retained artifact features. The experimental
artifact declares 222 feature names, but sklearn drops the all-missing
weak/live-only columns; the inventory now reports 156 retained active features,
37 of them from `reanalysis_synoptic`, and zero blocking active families.

Next unblock: keep the rich 2024/2025 data and corrected active-feature
inventory as durable coverage, but stop widening history blindly. The next
candidate should repair the allowed-market blend around Atlanta/Seattle while
preserving Austin/Houston/Los Angeles, or test a narrower reanalysis-only
subset if the broad all-feature lane keeps diluting the rich signal.
Pressure-level fields still require their separate cached NetCDF backfill
before the full synoptic contract is genuinely populated.

## 2026-06-19 pressure-level cache and replay update

The pressure-level contract is now populated for the 2024/2025 training and
holdout windows. `weather.sources.reanalysis_synoptic` can read current NOAA
PSL NetCDF4/HDF5 pressure-level downloads via the optional `netCDF4` reader,
while retaining the existing SciPy NetCDF3 path for classic files. The default
pressure cache now resolves to the shared `data/reanalysis/pressure_level`
directory when no custom data root is supplied, so normal sidecar builds can
reuse the durable yearly `air` and `hgt` files without a per-market cache flag.

Downloaded pressure cache:
`python -m weather.sources.reanalysis_synoptic --market toronto download-pressure-level --start 2024-01-01 --end 2026-12-31 --pressure-level-root data\reanalysis\pressure_level --skip-existing`
cached `air` and `hgt` files for 2024, 2025, and 2026. NOAA's current 2026
file only covers 2026-01-01 through 2026-03-17, so the June 2026 replay window
still cannot receive pressure values from that source yet. For 2024-01-02
through 2024-12-31 and 2025-01-02 through 2025-12-31, all 12 active-market
sidecars have complete 850 hPa temperature, 500 hPa height, and 1000-500 hPa
thickness coverage.

Training:
`python -m weather.calibration.pooled_feature_model --objective band --max-days-per-market 0 --holdout-year 2025 --reanalysis-lane-json data\backtest\source_family_inventory.json --artifact data\backtest\item32_reanalysis_rich_pressure_2024_2025_lane_candidate.pkl --out data\backtest\item32_reanalysis_rich_pressure_2024_2025_lane_training_report.md`
wrote a full F-family lane artifact over 67,779 rows. All 14 blocked-validation
audits passed, and every hourly model retained
`reanalysis_pressure_level_available`,
`reanalysis_prev_day_temperature_850hpa_c`,
`reanalysis_prev_day_geopotential_height_500hpa_m`, and
`reanalysis_prev_day_thickness_1000_500hpa_m`.

Pinned replay:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item32_reanalysis_rich_pressure_2024_2025_lane_candidate.pkl --out data\backtest\item32_reanalysis_rich_pressure_2024_2025_lane_replay_report.md --json-out data\backtest\item32_reanalysis_rich_pressure_2024_2025_lane_replay.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --disable-candidate-variant-export --skip-microstructure-overlay --disable-long-job-guard`
still reports `BLOCK`, market-only verdict `PARTIAL_PASS`, and cutover
`DO_NOT_CUT_OVER`.

The pressure-populated training window did not improve the pinned replay.
Aggregate candidate Brier is `0.042960` versus current `0.043554` and market
`0.037869`, leaving a `+0.005092` market gap. Daily-first candidate Brier is
`0.042899` versus current `0.043496` and market `0.037830`, leaving a
`+0.005070` market gap. This is slightly worse than the rich-only 2024/2025
artifact and worse than the rich-recent artifact, partly because the June replay
window has no pressure values until the NOAA 2026 file advances past March 17.

Per-market action remains mixed: Atlanta, Austin, Houston, and Los Angeles are
candidate cutover-ready; Dallas, Denver, and Miami remain shadow; Chicago, NYC,
San Francisco, and Seattle remain blocked by daily-first market tolerance.

The experimental source-family inventory saved at
`data\backtest\item32_reanalysis_rich_pressure_2024_2025_source_family_inventory.json`
reports `PASS` with zero blockers. `reanalysis_synoptic` is active with 40
retained model features, including the three pressure-level value fields. Item
32 therefore remains partial for empirical replay quality, not for missing
lineage, parity, or pressure-field population in the 2024/2025 training window.

## 2026-06-19 Seattle reanalysis alpha diagnostic

The thin-margin Seattle allowance was tested directly before changing the
positive-market lane. A Seattle-only promotion corpus was pinned at
`data/backtest/item32_seattle_promotion_corpus.json` with 4 settled
market-days, 556 snapshots, and 6,116 band rows. The baseline rich+pressure
artifact was replayed against that corpus at Seattle alpha `0.20`, then a
diagnostic clone,
`data/backtest/item32_reanalysis_rich_pressure_no_seattle_alpha_candidate.pkl`,
was replayed with only Seattle's current-blend alpha changed to `0.00`.

| Artifact | Seattle alpha | Candidate | Current | Market | Delta current | Delta market | Daily-first market gap |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `item32_seattle_rich_pressure_alpha020_replay.json` | 0.20 | 0.038520 | 0.038914 | 0.024133 | -0.000394 | +0.014387 | +0.014423 |
| `item32_seattle_rich_pressure_alpha000_replay.json` | 0.00 | 0.038914 | 0.038914 | 0.024133 | +0.000000 | +0.014781 | +0.014840 |

This rejects removing Seattle from the allowed reanalysis lane as the next
unblock. The existing `0.20` alpha is weakly useful versus current, but the
market gap remains far outside tolerance. Seattle needs direct market-gap
repair, not current fallback. The first paired replay attempt also hit the
artifact disk guard because local free space was below the 1 GB reserve; the
small diagnostic was rerun with `--min-artifact-free-bytes 0`. Subsequent Item
154 cleanup (`data/backtest/backtest_artifact_cleanup_manifest_4.json`) restored
the local backtest artifact-retention report to `PASS` with the 1 GB reserve
met for that diagnostic pass, while Item 146 still owns external backup-root
durability for irreplaceable and high-volume data.

A later retention check after the CLOB raw-artifact audit temporarily reversed
the local headroom status:
`data/backtest/backtest_artifact_retention_after_clob_raw_gate_report.md` was
`BLOCK` with `371.6 MB` free, a `105.3 MB` shortfall against the 500 MB reserve,
and zero automatic cleanup candidates. Follow-up retention work classified
source-state ablation CSVs as rebuildable row exports, then applied cleanup
manifests
`data/backtest/backtest_artifact_cleanup_manifest_after_source_ablation_cleanup.json`
and `data/backtest/backtest_artifact_cleanup_manifest_after_row_export_cleanup.json`.
Together they deleted 19 rebuildable row/shadow exports totaling `156.9 MB`
while retaining paired replay reports/manifests. The final no-cleanup report
`data/backtest/backtest_artifact_retention_after_row_export_cleanup_final_report.md`
is `PASS` with `490.0 MB` free and `0 B` shortfall against the 500 MB reserve.

Next unblock: stop broad feature accretion and run narrower ablations or
market-specific repairs. The leading targets are Seattle, NYC, San Francisco,
and Chicago market-tolerance gaps while preserving Atlanta/Austin/Houston/Los
Angeles. Refresh the 2026 pressure cache only after NOAA publishes dates that
cover the active replay window, then rerun the same pinned replay and inventory.

## 2026-06-19 no-pressure lane and training guard

The first narrower reanalysis subfamily path is now encoded as
`data/backtest/item32_reanalysis_rich_no_pressure_lane.json`. It keeps the
current positive-market reanalysis mask (`atlanta`, `austin`, `dallas`,
`houston`, `los-angeles`, `miami`, `seattle`) and quarantines the same five
markets (`chicago`, `denver`, `nyc`, `san-francisco`, `toronto`), but blocks
only the pressure-level reanalysis fields:
`reanalysis_pressure_level_available`,
`reanalysis_prev_day_temperature_850hpa_c`,
`reanalysis_prev_day_geopotential_height_500hpa_m`, and
`reanalysis_prev_day_thickness_1000_500hpa_m`.

`pooled_feature_model` now supports `blocked_feature_columns` and
`blocked_feature_prefixes` in reanalysis lane JSON. That makes pressure-only
or other subfamily ablations reproducible without editing sidecars or removing
the useful non-pressure reanalysis features.

The full no-pressure training command was attempted twice:
`python -m weather.calibration.pooled_feature_model --objective band --max-days-per-market 0 --holdout-year 2025 --reanalysis-lane-json data\backtest\item32_reanalysis_rich_no_pressure_lane.json --artifact data\backtest\item32_reanalysis_rich_no_pressure_lane_candidate.pkl --out data\backtest\item32_reanalysis_rich_no_pressure_lane_training_report.md`.
The first run passed 20 minutes and was stopped with no artifact/report. After
storage cleanup and CLOB tiering restored local headroom, the same full command
again exceeded a 30-minute timeout and was stopped with no artifact/report.
This is now a throughput problem, not a disk-preflight blocker.

To prevent low-disk repeats, `pooled_feature_model` now has
`--min-artifact-free-bytes`, defaulting to the shared artifact reserve, and
preflights planned model/report outputs before dataset assembly or fitting.
The disk guard was exercised while local free space was low, then cleared after
`tape_backup_unmanifested_cleanup_applied.json` and
`clob_order_book_tiering_apply_batch1.json`; the latest local retention check
`data/backtest/backtest_artifact_retention_after_backup_cleanup_and_tiering_report.md`
is `PASS`.

A bounded no-pressure diagnostic was completed with
`--max-days-per-market 120`:
`data/backtest/item32_reanalysis_rich_no_pressure_recent120_candidate.pkl`
trained over 18,480 rows, and
`data/backtest/item32_reanalysis_rich_no_pressure_recent120_replay.json`
replayed against the pinned promotion corpus. The replay still reports
`BLOCK / DO_NOT_CUT_OVER`, though it improves current: aggregate candidate
Brier `0.042781` versus current `0.043554` and market `0.037869`
(`+0.004913` market gap); daily-first candidate `0.042723` versus current
`0.043496` and market `0.037830` (`+0.004893` market gap). Per-market, Atlanta,
Houston, and Los Angeles pass; Dallas, Denver, and Miami remain shadow; Austin
now blocks narrowly at daily-first market gap `+0.003098`; Chicago, NYC, San
Francisco, and Seattle remain blocked (`+0.009212`, `+0.022290`,
`+0.005107`, and `+0.014554` daily-first market gaps).

Conclusion: removing pressure fields is not enough. The next Item 32 work
should focus on direct market-gap repairs for NYC, Seattle, San Francisco,
Chicago, and the now-thin Austin edge while preserving Atlanta/Houston/Los
Angeles. Full no-pressure training also needs a runtime reduction or
checkpointed/market-sharded training path before it can produce final evidence.

Verification:
`python -m pytest tests\calibration\test_pooled_feature_model.py -q` passed
with `41 passed`.

## 2026-06-19 checkpointed no-pressure training path

The full no-pressure lane now has a checkpointed training path instead of a
single monolithic command. `weather.calibration.pooled_feature_model` can write
merge payloads with `--write-merge-payload` and merge compatible hour shards
with `--merge-band-shards`, requiring the requested `--hours` set before it
writes a replayable artifact. The merge refits artifact-level adjacent and
market-bias postprocess from the concatenated holdout band rows, updates every
hour bundle with the merged postprocess, records `training_shards` metadata,
and strips the temporary merge payload from the final artifact.

Real Item 32 evidence:

- Full-history no-pressure shards for hours `07` through `20` completed. The
  first parallel batch exposed an important operational constraint: hour `09`
  hit a sklearn `MemoryError` when three shard trainings ran concurrently, then
  succeeded when retried alone. The practical command policy is therefore
  sequential or memory-capped shard training, not broad parallel fan-out.
- `python -m weather.calibration.pooled_feature_model --merge-band-shards ... --hours 7,8,9,10,11,12,13,14,15,16,17,18,19,20 --artifact data\backtest\item32_reanalysis_rich_no_pressure_full_merged_candidate.pkl --out data\backtest\item32_reanalysis_rich_no_pressure_full_merged_report.md`
  wrote the replayable 14-hour artifact. The merge report shows 14 shards,
  217,126 postprocess fit rows, 262 adjacent-calibration contexts, 220
  market-bias contexts, and `training_shards` metadata. The final artifact
  strips the temporary `band_postprocess_merge_payload`.
- `python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item32_reanalysis_rich_no_pressure_full_merged_candidate.pkl --out data\backtest\item32_reanalysis_rich_no_pressure_full_merged_replay_report.md --json-out data\backtest\item32_reanalysis_rich_no_pressure_full_merged_replay.json --replay-report= --candidate-variant-out= --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --disable-candidate-variant-export --skip-microstructure-overlay --disable-long-job-guard`
  scored 67,430 F-family rows with zero missing candidate rows. The replay is
  still `BLOCK / DO_NOT_CUT_OVER`: aggregate candidate Brier `0.0431` versus
  current `0.0435` and market `0.0379`, and daily-first candidate Brier
  `0.0430` versus current `0.0434` and market `0.0378`. The daily-first market
  gap is `+0.0052`, worse than the no-pressure recent-120 diagnostic
  (`+0.004893`), so the full no-pressure lane is now a scored dead end rather
  than an untested blocker.
- Per-market action is mixed: Houston and Los Angeles pass; Atlanta, Dallas,
  Denver, and Miami remain shadow; Austin, Chicago, NYC, San Francisco, and
  Seattle block. High-disagreement guardrails still block Chicago (`+0.0067`),
  Denver (`+0.0062`), NYC (`+0.0188`), San Francisco (`+0.0045`), and Seattle
  (`+0.0147`) versus market.
- The merged replay source-family inventory
  `data\backtest\item32_reanalysis_rich_no_pressure_full_merged_source_family_inventory_report.md`
  is `PASS` with zero blocking active families. `reanalysis_synoptic` has
  lineage `PASS`, parity `PASS`, ablation `PRESENT`, and 36 retained active
  features in this no-pressure lane.

This still does not complete Item 32. The tooling and full no-pressure scoring
blockers are resolved, but the model-quality blocker remains. The next unblock is
direct market-gap repair for Austin, Chicago, NYC, San Francisco, and Seattle
while preserving Houston and Los Angeles, not more broad reanalysis feature
accretion or another full no-pressure rerun.

Verification:
`python -m pytest tests\calibration\test_pooled_feature_model.py tests\calibration\test_pooled_candidate_replay.py tests\operations\test_schema_registry.py -q`
passed with `88 passed`, and
`python -m weather.schema_registry audit --paths src\weather\calibration\pooled_feature_model.py --strict`
reported zero unregistered versions.

## 2026-06-19 pressure-cache freshness status

The 2026 pressure-level blocker is now repeatably checkable instead of relying
on a manual file-size note. `weather.sources.reanalysis_synoptic` gained a
`pressure-level-status` command that reports local NOAA PSL pressure-level file
presence, optional remote HEAD metadata, and requested-date metric coverage.

Current replay-window status:
`python -m weather.sources.reanalysis_synoptic --market toronto pressure-level-status --start 2026-06-01 --end 2026-06-13 --pressure-level-root data\reanalysis\pressure_level --check-remote --json-out data\backtest\item32_pressure_level_cache_status_2026_replay_window.json --report-out data\backtest\item32_pressure_level_cache_status_2026_replay_window_report.md`.

The report is `CACHE_CURRENT`, not stale-local-cache. Local `air.2026.nc` and
`hgt.2026.nc` match the remote NOAA sizes exactly (`22,917,693` and
`17,838,727` bytes), and the remote `Last-Modified` headers are still
`Thu, 19 Mar 2026 14:27:58 GMT` / `14:27:59 GMT`. Metric coverage for
2026-06-01 through 2026-06-13 is `0/13` complete, with latest cached metric
date `2026-03-17`.

This does not unblock Item 32, but it removes ambiguity from the pressure
refresh instruction: rerunning the pressure download now cannot add June replay
coverage. Refresh only after the remote NOAA files grow or their modified
timestamps advance beyond the March file, then rebuild sidecars and rerun the
pinned Item 32 replay.

Verification:
`python -m pytest tests\sources\test_reanalysis_synoptic.py tests\operations\test_schema_registry.py -q`
passed with `11 passed`, and
`python -m weather.schema_registry audit --paths src\weather\sources\reanalysis_synoptic.py --strict`
reported zero unregistered versions.

## 2026-06-19 no-pressure replay repair-action export

The full no-pressure replay now has row-level repair evidence, not only the
aggregate `BLOCK / DO_NOT_CUT_OVER` report. I reran the existing artifact with
only the candidate shadow-variant export enabled:
`python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\item32_reanalysis_rich_no_pressure_full_merged_candidate.pkl --out data\backtest\item32_reanalysis_rich_no_pressure_full_merged_repair_export_replay_report.md --json-out data\backtest\item32_reanalysis_rich_no_pressure_full_merged_repair_export_replay.json --candidate-variant-out data\backtest\item32_reanalysis_rich_no_pressure_full_merged_variant_rows.csv --candidate-variant-id item32_reanalysis_rich_no_pressure_full_merged --candidate-variant-family item32_reanalysis_synoptic_no_pressure --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --skip-microstructure-overlay --disable-long-job-guard`.

The replay still blocks, but the export is complete: `67,430` F-family rows,
zero missing candidate rows, candidate Brier `0.0431` versus current `0.0435`
and market `0.0379`, and daily-first gap `+0.0052` versus market.

I then ran the repair-action diagnostic:
`python -m weather.reporting.blocked_market_repair_diagnostics data\backtest\item32_reanalysis_rich_no_pressure_full_merged_variant_rows.csv --out data\backtest\item32_reanalysis_rich_no_pressure_full_merged_repair_actions.json --report data\backtest\item32_reanalysis_rich_no_pressure_full_merged_repair_actions_report.md --min-slice-rows 200 --top-slices 6`.

The remaining Item 32 blockers are now market-specific:

- Austin blocks narrowly with `repair_largest_market_gap_slice`; the top slice
  is settlement-distance-0 with weighted market gap `25.1277`.
- Chicago, NYC, and San Francisco are `current_fallback_trails_market` with
  full `1.0000` current-fallback share, so more reanalysis feature accretion is
  not sufficient unless it creates non-current skill in those markets.
- Seattle is `winner_underpricing_vs_market`; the next useful repair is winner
  probability mass on EQ / settlement-distance-0 rows, not another broad
  no-pressure rerun.
- No blocked market regresses current in this export, so a current-regression
  guard is available but not the Item 32 failure mode.

This does not complete Item 32. It narrows the model-quality blocker after the
lineage/parity/ablation/tooling blockers were cleared: preserve Houston and Los
Angeles, then repair Austin slices, Chicago/NYC/SF non-current signal, and
Seattle winner mass before rerunning the pinned replay.

I also tested the simplest row-level winner-mass repair on the same export:
`python -m weather.reporting.winner_boost_validation data\backtest\item32_reanalysis_rich_no_pressure_full_merged_variant_rows.csv --out data\backtest\item32_reanalysis_rich_no_pressure_full_merged_winner_boost_validation.json --report data\backtest\item32_reanalysis_rich_no_pressure_full_merged_winner_boost_validation_report.md`.
The chronological validation is `BLOCK`: selected daily-first Brier is
`0.0463` versus current `0.0456` and market `0.0385`, worse than the baseline
candidate `0.0447`. Austin and San Francisco pass under simple EQ/off-forecast
boosts, but Chicago, NYC, Seattle, and several shadow/monitor markets still
block. This rules out a generic exact-winner multiplier as the Item 32 unblock;
the next repair needs market-specific non-current signal for Chicago/NYC/SF and
a richer Seattle winner-mass policy that does not damage the aggregate holdout.

The chronological current-blend validation also blocks:
`python -m weather.reporting.current_blend_validation --rows data\backtest\item32_reanalysis_rich_no_pressure_full_merged_variant_rows.csv --base-replay data\backtest\item32_reanalysis_rich_no_pressure_full_merged_repair_export_replay.json --out data\backtest\item32_reanalysis_rich_no_pressure_full_merged_current_blend_validation.json --report data\backtest\item32_reanalysis_rich_no_pressure_full_merged_current_blend_validation_report.md`.
The selected holdout score is candidate Brier `0.0451` versus current `0.0456`
and market `0.0385`, leaving a `+0.0065` market gap and worsening the baseline
candidate's `+0.0061` holdout market gap. The report now surfaces selection
reason and raw-row availability: Chicago, NYC, and San Francisco have
`baseline_artifact_full_current_fallback_no_raw_candidate` with `0` raw eval
rows, so this row export cannot validate raw non-current skill for those
markets. Austin selects alpha `0.10` but still blocks at `+0.0061` versus
market, and Seattle keeps alpha `0.20` while still blocking at `+0.0164`.
This makes the next Item 32 step explicit: produce a candidate/export that
actually exposes non-current probabilities for Chicago/NYC/San Francisco, while
separately repairing Austin slices and Seattle winner mass.

I produced that diagnostic candidate by cloning the full no-pressure artifact
and setting `current_blend_market_alpha = 1.0` for Chicago, NYC, and San
Francisco only:
`data/backtest/item32_reanalysis_rich_no_pressure_full_merged_raw_alpha_chicago_nyc_sf_candidate.pkl`.
The pinned replay is still `BLOCK / DO_NOT_CUT_OVER`, but it answers the raw
skill question. Aggregate candidate Brier improves from the baseline export's
`0.0431` to `0.0423` versus current `0.0435`, while the market gap only narrows
from `+0.0052` to `+0.0044`; daily-first still leaves a `+0.0044` market gap.
The blocked markets remain Austin, Chicago, NYC, San Francisco, and Seattle.

Market-level conclusion:

- Chicago raw alpha helps versus current (`0.0405` candidate vs `0.0453`
  current), but still trails market by `+0.0042`.
- NYC raw alpha helps materially versus current (`0.0462` candidate vs
  `0.0589` current), but still trails market by `+0.0101`.
- San Francisco raw alpha is unsafe: candidate Brier `0.0548` regresses current
  `0.0463` by `+0.0085` and trails market by `+0.0135`.
- Austin and Seattle remain separate blockers: Austin trails market by
  `+0.0032`, and Seattle trails market by `+0.0144`.

This rules out blindly opening the current fallback for all quarantined
markets. The next promotable repair has to be guarded per market: keep San
Francisco current-guarded until a new signal clears current, continue Chicago
and NYC only with additional market-gap repair, and handle Austin/Seattle via
their slice and winner-mass repairs before rerunning the pinned full replay.

## 2026-06-19 reanalysis branch basket check

The reanalysis-rich no-pressure branch was added to the existing blocked-market
variant basket check so Item 32 could be evaluated against the stronger Item
147/134/135 branches rather than only in isolation:
`data\backtest\item147_blocked_markets_variant_basket_with_item32_validation_report.md`.
The selector chooses variants on June 7/8 and evaluates June 12/13 for Austin,
Los Angeles, NYC, San Francisco, and Seattle.

The basket remains `blocked`: selected later-date daily-first Brier is
`0.0465` versus current `0.0505` and market `0.0359`, leaving the same
`+0.0106` market gap and all five markets blocked. Adding Item 32 improves the
diagnostic eval oracle from `+0.0092` to `+0.0085`, but still does not clear
market tolerance.

The useful Item 32 signal is narrow and not split-stable yet. Austin's eval
oracle would pick `item32_reanalysis_rich_no_pressure_full_merged` with a
`+0.0005` market gap, but the earlier-date selector picks current because the
branch does not win on the train split. Los Angeles and Seattle also select
Item 32 only in eval-oracle mode and still miss market tolerance; NYC remains
best under Item 147; San Francisco remains safest under current/or prior
forecast-profile branches. This keeps Item 32 `PARTIAL`: reanalysis can be a
candidate ingredient, especially for Austin, but it is not promotable without
more split-stable market-specific evidence.

I extended the basket validator with a leave-one-market-day stability section
and regenerated the same report. This makes the Austin boundary more precise:
Item 32 is selected in 3 of 4 held-out Austin day cuts and the eval oracle also
picks it in 3 of 4, but the selected aggregate still blocks at `+0.0054` versus
market and slightly regresses current. The oracle aggregate would pass market
at `-0.0002`, which means the signal is real but not yet policy-stable. June 7
and June 13 are the weak Austin days: Item 32 misses market by `+0.0092` on
June 7, and the selector falls back to current on June 13 while the oracle
would have used Item 32. The next Item 32 repair should therefore focus on an
Austin-specific guard/selector that keeps the June 8/12 lift without the June
7/13 failures, then rerun the full pinned replay.

The same report now includes guarded branch policies that blend a variant back
to current serving by inference-time source/cutoff/forecast-side rules. For
Austin, the fixed Item 32 guard `all_fresh_midday_late` passes the local market
tolerance with candidate Brier `0.0386` versus market `0.0362`
(`+0.0024`) and improves current by `-0.0024`. The stricter train-selected
leave-one-day guard still blocks at `+0.0034`, selecting `all_fresh` once and
`all_fresh_midday_late` three times. This is a better next candidate shape
than broad reanalysis promotion: predeclare/test an Austin
all-fresh-midday/late reanalysis guard, then rerun the full pinned replay and
verify it does not damage the other markets.

## 2026-06-19 Austin guarded replay

The Austin guard is now replayable instead of only a row-export diagnostic.
`weather.calibration.pooled_candidate_replay` supports artifact-level
`current_blend_context_alpha` rules, and the diagnostic artifact
`data/backtest/item32_reanalysis_austin_all_fresh_midday_late_guard_candidate.pkl`
sets Austin to current by default, then opens the Item 32 branch only when
`source_freshness_state=all_fresh` and cutoff regime is `midday` or `late`.
The replay report now renders that context rule explicitly.

The full pinned replay
`data/backtest/item32_reanalysis_austin_guard_replay_report.md` still returns
`BLOCK / DO_NOT_CUT_OVER`, but it clears the Austin market blocker:

- Aggregate candidate Brier improves from the unguarded no-pressure replay
  `0.04310` to `0.04302`, and the market gap narrows from `+0.00523` to
  `+0.00515`.
- Austin improves from candidate `0.03939` versus current `0.04099` and market
  `0.03620` (`+0.00318` market gap) to candidate `0.03849`
  (`-0.00251` versus current, `+0.00228` versus market). Austin is now
  `PASS`.
- Houston and Los Angeles also pass. Atlanta, Dallas, Denver, and Miami remain
  shadow. Chicago, NYC, San Francisco, and Seattle remain blocked.

This is real Item 32 progress but not completion. The next reanalysis-side
work should preserve the Austin guarded policy while repairing Chicago/NYC/SF
current-fallback gaps and Seattle winner mass before another full replay can
clear the item.

## 2026-06-20 UTC Austin guard plus Chicago/NYC raw-alpha replay

I cloned the replayable Austin guard artifact into
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_candidate.pkl`
and opened only Chicago and NYC to raw Item 32 candidate alpha. Austin keeps
the `all_fresh` midpoint/late context rule, and San Francisco stays on current
fallback because the previous raw-alpha diagnostic regressed current there.

The full pinned replay
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_replay_report.md`
still reports `BLOCK / DO_NOT_CUT_OVER`, but it materially narrows the Item 32
model gap. Aggregate candidate Brier is `0.04141` versus current `0.04349`
and market `0.03787`; daily-first candidate Brier is `0.04136` versus current
`0.04344` and market `0.03783`, leaving a `+0.00353` daily-first market gap.

Market-level result:

- Austin remains `PASS`: candidate `0.03849`, current `0.04099`, market
  `0.03620`, gap `+0.00228`.
- Chicago now beats current (`0.04049` vs `0.04533`) but still trails market by
  `+0.00418`.
- NYC now beats current (`0.04619` vs `0.05895`) but still trails market by
  `+0.01013`.
- San Francisco is protected from the unsafe raw-alpha branch and remains a
  current-fallback block at `+0.00503` versus market.
- Seattle remains a winner-mass block at `+0.01440` versus market.

The refreshed repair diagnostic
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_repair_actions_report.md`
classifies the remaining blockers as: Chicago
`market_gap_without_clear_winner_signal`, NYC and Seattle
`winner_underpricing_vs_market`, and San Francisco
`current_fallback_trails_market`. The next Item 32 work should keep this
combined guard as the baseline, then add a Chicago slice repair, richer
NYC/Seattle winner-mass signal, and a non-current San Francisco signal before
another full replay.

I also corrected `weather.reporting.current_blend_validation` so row-level
alpha reconstruction honors `current_blend_context_alpha` rules. The regenerated
time-split alpha report
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_current_blend_validation_report.md`
still blocks. It now counts Austin context raw rows correctly (`1,859` train /
`1,804` eval), but selected alpha over earlier market-days does not generalize:
selected eval daily-first gap is `+0.00527` versus market, worse than the
combined replay baseline's `+0.00491`. The selected alphas keep Chicago and
NYC at `1.0`, Seattle at `0.2`, and choose Austin `0.2`, but Austin, Chicago,
Los Angeles, NYC, San Francisco, and Seattle all remain holdout blocks. This
rejects another broad alpha-schedule pass as an Item 32 unblock.

I then ran a stricter context-guard scan over inference-time keys only
(`source_freshness_state`, `cutoff_regime`, forecast disagreement/pressure,
forecast source count, and `bin_type`):
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_context_guard_validation_report.md`.
It also blocks. Selected context policies worsen daily-first holdout market gap
to `+0.00509` versus the combined replay baseline's `+0.00491`. The useful
clues are negative: Chicago's best train-selected/eval-oracle guard
(`current_on_forecast_disagreement_bucket=low_disagreement`) improves the
later-date candidate but still misses market by `+0.00461`; NYC's best oracle
still misses by `+0.01972`; Seattle's best oracle still misses by `+0.01525`;
and San Francisco has no raw candidate rows under this guarded artifact. The
next Item 32 repair therefore needs new signal/features, not another
inference-slice raw/current guard over the same probabilities.

## 2026-06-20 UTC artifact-lane source-family inventory

I reran the source-family inventory against the current combined Item 32 replay:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_source_family_inventory_report.md`.
The report is `PASS` with zero blocking family rows and now points its
preflight command at
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_replay.json`.

I also tightened `weather.reporting.source_family_inventory` so it extracts the
artifact-declared `reanalysis_promotion_lane`, reports it separately from the
gate-derived lane, and blocks preflight if an active reanalysis artifact allows
markets that the settlement-scored Item 27 gates quarantine. The regenerated
report proves the combined artifact is using 36 active reanalysis features and
that its no-pressure artifact lane is consistent with the market gates:
allowed markets are Atlanta, Austin, Dallas, Houston, Los Angeles, Miami, and
Seattle; quarantined markets are Chicago, Denver, NYC, San Francisco, and
Toronto; pressure-level fields remain explicitly blocked. This strengthens the
Item 32 data-layer evidence, but the item remains `PARTIAL` because the replay
and market-gap gates still block Chicago, NYC, San Francisco, and Seattle.

## 2026-06-20 UTC reproducible context-guard rejection and pressure refresh

I formalized the prior ad hoc context-guard scan as
`weather.reporting.context_guard_validation`, registered
`context_guard_validation_v0.1`, and regenerated the combined Item 32 report:
`data/backtest/item32_reanalysis_austin_guard_chicago_nyc_raw_context_guard_validation_report.md`.
The validator selects candidate/current guards on earlier market-days and
evaluates later market-days using only inference-time fields; this run also
tests two-condition policies with at least 200 train rows.

The result is still `BLOCK` and is weaker than the observed combined replay
baseline. Selected daily-first Brier is `0.0439` versus market `0.0385`, a
`+0.0054` market gap; the observed baseline on the same eval rows is `0.0434`,
gap `+0.0049`. Seven markets block under train-selected guards: Austin,
Chicago, Houston, Los Angeles, NYC, San Francisco, and Seattle. The eval oracle
also confirms the remaining blocker shape: Chicago's best guard still misses
market by `+0.0047`, NYC by `+0.0195`, San Francisco has no non-current rows
and stays at `+0.0056`, and Seattle remains `+0.0161`.

I also refreshed the 2026 replay-window pressure-level cache status with remote
headers:
`data/backtest/item32_pressure_level_cache_status_2026_replay_window_refresh_report.md`.
The local `air.2026.nc` and `hgt.2026.nc` files still match NOAA's remote
sizes and the remote modified timestamps remain March 19, 2026. Metric coverage
for June 1-13 is still `0/13`, with latest cached metric date `2026-03-17`.
That makes this a source-lag boundary, not a local rebuild miss.

Focused validation:
`python -m pytest tests\reporting\test_context_guard_validation.py tests\reporting\test_current_blend_validation.py tests\reporting\test_variant_basket_selection_validation.py tests\operations\test_schema_registry.py -q`
passed with 18 tests. The strict schema audit for the new report and registry
entry reported `registered=193 discovered=204 unregistered_versions=0`.
