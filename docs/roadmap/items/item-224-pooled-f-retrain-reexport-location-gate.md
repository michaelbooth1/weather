# 224. Pooled F Retrain/Re-Export Location Gate [PARTIAL 2026-06-23 - V1.15 EVIDENCE REFRESHED, LOCATION BLOCKED]

Goal: re-export the active pooled F artifact under serving-parity and honest
blocked-validation fixes, then make the new artifact pass the location audit
before any broad core-model improvement claim.

Source: `docs/roadmap/audits/location-performance-model-audit-2026-06-22.md`,
plus the early-hour and core-model audits. The early-hour failure matches the
core-model finding that serving applied transforms the tuning objective did not
see, and historical validation was asymmetric between the ML path and baseline.
The active location audit shows bottom markets remain outside tolerance.

Why this matters: even when code-level validation fixes exist, production proof
depends on a regenerated artifact and the exact served distribution passing the
same location and weak-slot gates.

## Design

1. Run the long-job-safe pooled F retrain/re-export path after serving-parity
   and honest blocked-validation fixes.
2. Stamp the artifact with schema, training cutoff, runtime identity, and
   validation provenance.
3. Replay the new artifact against current, item147, and predawn/item147 repair
   on the same market-day corpus.
4. Require hourly, ten-minute, promotion refresh, stage attribution, and
   location split reports to clear market-specific gates before any broad claim.

- [x] Produce a regenerated pooled F artifact with current validation
  provenance.
- [x] Run paired replay against current, item147, and predawn repair.
- [x] Regenerate hourly, ten-minute, promotion refresh, stage attribution, and
  location audit outputs.
- [x] Add an artifact gate that blocks broad claims when the active artifact is
  older than the serving-parity validation fixes.

## Progress 2026-06-22

Added `weather.reporting.pooled_f_retrain_location_gate` with schema
`pooled_f_retrain_location_gate_v0.1`.

Artifacts:

- `data/backtest/pooled_f_retrain_location_gate.json`
- `data/backtest/pooled_f_retrain_location_gate_report.md`

Command:

`python -m weather.reporting.pooled_f_retrain_location_gate --out data\backtest\pooled_f_retrain_location_gate.json --report data\backtest\pooled_f_retrain_location_gate_report.md`

Result: **BLOCK** with 7 blockers. Broad core-model improvement claims remain
disallowed.

Current blockers:

- Active artifact `artifacts\models\hgb\feature_model_hgb_f_pooled_v0_3.pkl`
  was trained at `2026-06-21T21:53:04.962892` with
  `toronto_feature_store_v1.13`, while the active runtime schema is
  `toronto_feature_store_v1.14`.
- Paired candidate replay is `BLOCK`; daily-first blocked validation is
  `BLOCK`; cutover remains `DO_NOT_CUT_OVER`.
- Promotion refresh readiness is `OPEN`; weather-only broad-claim allowance is
  false because aggregate `delta_vs_market` is still positive.
- Hourly/ten-minute weak-slot promotion remains blocked.
- Bottom-location winner-centering remains blocked; first blocker is Seattle
  weak-slot current regression `+0.0307`.
- Exact-band and settlement-distance-0 calibration remains blocked; first
  blocker is exact-band early market gap `+0.0047`.
- Source/missingness location gate remains blocked; first blocker is Miami
  all-fresh market gap `+0.0215`.

The gate passes the validation-provenance check for the current artifact/report,
but it intentionally fails closed until a current-schema retrain/re-export and
all replay, weak-slot, promotion, and location-split reports clear on the same
corpus.

Acceptance: the regenerated pooled F artifact has fresh validation provenance
and clears weak-slot, market-specific, and aggregate promotion gates on the same
corpus before any broad core-model improvement claim is allowed.

Related: items 48, 106, 177, 178, 179, 217, 219.

## 2026-06-22 gate refresh after upstream repairs

Regenerated the broad-claim gate after refreshing the predawn sweep,
bottom-location, exact-band, and current-max trust evidence:

- `data/backtest/pooled_f_retrain_location_gate.json`
- `data/backtest/pooled_f_retrain_location_gate_report.md`

The refreshed gate remains `BLOCK` with `7` blockers and keeps broad pooled-F
core-model improvement claims disallowed.

Current blockers:

- `artifact_runtime_schema`: active artifact
  `artifacts\models\hgb\feature_model_hgb_f_pooled_v0_3.pkl` is still stamped
  with `toronto_feature_store_v1.13`, while the active runtime feature schema is
  `toronto_feature_store_v1.14`.
- `paired_candidate_replay`: paired candidate replay remains `BLOCK`, daily-
  first blocked validation remains `BLOCK`, and cutover remains
  `DO_NOT_CUT_OVER`.
- `promotion_refresh_broad_claim`: aggregate/daily-first promotion evidence
  still does not allow the weather-only broad claim.
- `hourly_ten_minute_weak_slot_gate`: the hourly/ten-minute weak-slot promotion
  gate is not clear.
- `bottom_location_gate`: bottom-location winner-centering remains blocked;
  first blocker is current Brier regression `+0.0307`.
- `exact_band_distance_zero_gate`: exact-band/distance-zero calibration remains
  blocked; first blocker is market gap `+0.0047` against the `+0.0030`
  tolerance.
- `source_missingness_location_gate`: source/missingness location gate remains
  blocked; first blocker is Miami all-fresh market gap `+0.0215`.

The gate still passes training validation provenance for the existing artifact
and report, but no schema-current retrain/re-export was produced here. The item
therefore remains partial with an up-to-date fail-closed gate and explicit
blocking evidence.

## 2026-06-22 proof packet mapping

Proof-packet blocker: `weather_only_model_proof_packet.gates.active_artifact_identity`.
Retrain/re-export work must first make the active artifact identity proof-grade
in the packet before downstream broad-claim or per-market dispositions can
advance.

## 2026-06-22 full retrain attempt

Attempted the canonical active-artifact retrain:

```powershell
python -m weather.calibration.pooled_feature_model --objective band --family-unit F --min-artifact-free-bytes 0
```

The foreground run exceeded a 15-minute timeout before writing outputs. A
hidden background retry was then launched with stdout/stderr redirected to:

- `data/backtest/pooled_f_retrain_20260622_stdout.log`
- `data/backtest/pooled_f_retrain_20260622_stderr.log`

That retry remained active after sustained CPU use, emitted only sklearn
all-missing-column imputer warnings, produced no success stdout, and had not
modified `artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl`. It was
stopped to avoid leaving an unbounded training process running.

This full-corpus attempt was superseded by the sharded-hour re-export below.

## 2026-06-22 sharded-hour re-export

Used the mergeable pooled-band shard path to train hours `7` through `20`
individually with merge payloads, then merged the 14 validated shards into the
active artifact:

```powershell
python -m weather.calibration.pooled_feature_model --objective band --family-unit F --hours 7,8,9,10,11,12,13,14,15,16,17,18,19,20 --merge-band-shards data\backtest\pooled_f_retrain_hour07.pkl data\backtest\pooled_f_retrain_hour08.pkl data\backtest\pooled_f_retrain_hour09.pkl data\backtest\pooled_f_retrain_hour10.pkl data\backtest\pooled_f_retrain_hour11.pkl data\backtest\pooled_f_retrain_hour12.pkl data\backtest\pooled_f_retrain_hour13.pkl data\backtest\pooled_f_retrain_hour14.pkl data\backtest\pooled_f_retrain_hour15.pkl data\backtest\pooled_f_retrain_hour16.pkl data\backtest\pooled_f_retrain_hour17.pkl data\backtest\pooled_f_retrain_hour18.pkl data\backtest\pooled_f_retrain_hour19.pkl data\backtest\pooled_f_retrain_hour20.pkl --artifact artifacts\models\hgb\feature_model_hgb_f_pooled_v0_3.pkl --out data\backtest\f_family_pooled_band_model_v0_3_report.md --min-artifact-free-bytes 0
```

Artifacts:

- `artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl`
- `data/backtest/f_family_pooled_band_model_v0_3_report.md`
- `data/backtest/pooled_f_retrain_merged_candidate.pkl`
- `data/backtest/pooled_f_retrain_merged_candidate_report.md`
- `data/backtest/pooled_f_retrain_hour07.pkl` through
  `data/backtest/pooled_f_retrain_hour20.pkl`

Result: the active artifact is now stamped with
`toronto_feature_store_v1.14`, includes models for hours `7` through `20`, and
records `14` training shards. The merged report used `210306` postprocess fit
rows.

Reran:

```powershell
python -m weather.reporting.pooled_f_retrain_location_gate --out data\backtest\pooled_f_retrain_location_gate.json --report data\backtest\pooled_f_retrain_location_gate_report.md
python -m weather.reporting.weather_only_model_proof_packet
```

Gate result: still `BLOCK` with `7` blockers. The stale active-artifact schema
blocker is resolved, and
`weather_only_model_proof_packet.gates.active_artifact_identity` now passes.
Remaining blockers:

- `training_validation_provenance`: missing artifact/report blocked-validation
  provenance.
- `paired_candidate_replay`: candidate replay remains `BLOCK`; blocked
  validation remains `BLOCK`; cutover remains `DO_NOT_CUT_OVER`.
- `promotion_refresh_broad_claim`: aggregate candidate still trails market
  Brier by `+0.0087`.
- `hourly_ten_minute_weak_slot_gate`: current hourly gate remains `BLOCK`.
- `bottom_location_gate`: candidate does not improve current Brier, `+0.0307`.
- `exact_band_distance_zero_gate`: target Brier trails market by `+0.0047`,
  above the `+0.0030` tolerance.
- `source_missingness_location_gate`: Miami all-fresh candidate trails market by
  `+0.0215`.

Item 224 therefore remains `PARTIAL`: schema-current re-export is complete, but
the regenerated artifact is not yet proof-grade for broad promotion or
location-clearance claims.

## 2026-06-23 v1.15 re-export and gate refresh

Re-exported the active pooled F artifact from the v1.15 current-max trust
candidate and preserved the previous active artifact at:

- `data/backtest/item224_feature_model_hgb_f_pooled_v0_3_pre_v15_reexport_backup.pkl`

Updated artifacts:

- `artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl`
- `data/backtest/f_family_pooled_band_model_v0_3_report.md`
- `data/backtest/pooled_candidate_replay_latest.json`
- `data/backtest/pooled_candidate_replay_latest_report.md`
- `data/backtest/item224_pooled_f_retrain_location_gate.json`
- `data/backtest/item224_pooled_f_retrain_location_gate_report.md`

The active artifact is now stamped with
`toronto_feature_store_v1.15`, matches the active runtime schema, and carries
blocked-validation provenance. The item 224 gate now passes both:

- `artifact_runtime_schema`
- `training_validation_provenance`

Fresh paired replay result:

- Replay verdict: `BLOCK`
- Cutover decision: `DO_NOT_CUT_OVER`
- Blocked validation: `BLOCK`
- Aggregate delta vs current: `-0.0030`
- Aggregate delta vs market: `+0.0067`
- Daily-first delta vs current: `-0.0026`
- Daily-first delta vs market: `+0.0066`
- Candidate market verdict: `PARTIAL_PASS`

Reran:

```powershell
python -m weather.reporting.pooled_f_retrain_location_gate --out data\backtest\item224_pooled_f_retrain_location_gate.json --report data\backtest\item224_pooled_f_retrain_location_gate_report.md
```

Gate result: `BLOCK` with `6` blockers. Broad pooled-F core-model improvement
claims remain disallowed.

Remaining blockers:

- `paired_candidate_replay`: candidate replay remains `BLOCK`; blocked
  validation remains `BLOCK`; cutover remains `DO_NOT_CUT_OVER`.
- `promotion_refresh_broad_claim`: core candidate still needs aggregate
  `delta_vs_market <= 0` and daily-first clearance.
- `hourly_ten_minute_weak_slot_gate`: current hourly gate remains `BLOCK`; the
  candidate hourly gate must pass with matching variant, corpus hash, and fresh
  generation time.
- `bottom_location_gate`: candidate does not improve current Brier, `+0.0307`.
- `exact_band_distance_zero_gate`: target Brier trails market by `+0.0047`,
  above the `+0.0030` tolerance.
- `source_missingness_location_gate`: Miami all-fresh candidate trails market by
  `+0.0215`.

The unblocked work is complete for schema/provenance. The remaining unblocking
work is model-quality repair on hard location and weak-slot slices; another
artifact copy or replay refresh will not clear the item unless the candidate
beats the market tolerance on aggregate, daily-first, and the blocked
location-specific gates.

## 2026-06-23 v1.15 downstream evidence refresh

Fixed the extracted `weather.reporting.promotion_refresh` CLI long-job guard
imports, then refreshed promotion and location evidence against the active
v1.15 current-max candidate artifacts from Item 232:

- `data/backtest/current_max_trust_candidate_replay.json`
- `data/backtest/current_max_trust_candidate_replay_report.md`
- `data/backtest/current_max_trust_variant_rows.csv`
- `data/backtest/current_max_trust_hourly_candidate_performance.json`
- `data/backtest/current_max_trust_ten_minute_performance.json`
- `data/backtest/f_family_promotion_refresh.json`
- `data/backtest/f_family_promotion_refresh_report.md`
- `data/backtest/bottom_location_winner_centering.json`
- `data/backtest/bottom_location_winner_centering_report.md`
- `data/backtest/exact_band_distance_zero_calibration.json`
- `data/backtest/exact_band_distance_zero_calibration_report.md`
- `data/backtest/item224_pooled_f_retrain_location_gate.json`
- `data/backtest/item224_pooled_f_retrain_location_gate_report.md`

The refreshed promotion run now uses a candidate shadow export with source and
missingness context:

- candidate shadow export: `data/backtest/current_max_trust_variant_rows.csv`.
- candidate id: `current_max_trust_retrain_v0_1`.
- artifact hash: `95a1298ec744299a5dfab7aa0ab861816bf6f877a50555dfe5cd616942683934`.
- feature schema: `toronto_feature_store_v1.15`.

Commands:

```powershell
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\current_max_trust_candidate_replay.json --precomputed-candidate-report data\backtest\current_max_trust_candidate_replay_report.md --candidate-hourly-performance-report data\backtest\current_max_trust_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\current_max_trust_ten_minute_performance.json --skip-serving-gauntlet --disable-long-job-guard --min-artifact-free-bytes 0 --out data\backtest\f_family_promotion_refresh.json --report data\backtest\f_family_promotion_refresh_report.md --incomplete-manifest data\backtest\f_family_promotion_refresh_incomplete.json
python -m weather.reporting.bottom_location_winner_centering --variant-rows data\backtest\current_max_trust_variant_rows.csv --ten-minute-report data\backtest\current_max_trust_ten_minute_performance.json --out data\backtest\bottom_location_winner_centering.json --report data\backtest\bottom_location_winner_centering_report.md
python -m weather.reporting.exact_band_distance_zero_calibration --variant-rows data\backtest\current_max_trust_variant_rows.csv --out data\backtest\exact_band_distance_zero_calibration.json --report data\backtest\exact_band_distance_zero_calibration_report.md
python -m weather.reporting.pooled_f_retrain_location_gate --candidate-replay data\backtest\current_max_trust_candidate_replay.json --out data\backtest\item224_pooled_f_retrain_location_gate.json --report data\backtest\item224_pooled_f_retrain_location_gate_report.md
```

Result: the umbrella gate remains `BLOCK` with `6` blockers:

- `paired_candidate_replay`: replay `BLOCK`, blocked validation `BLOCK`,
  cutover `DO_NOT_CUT_OVER`; aggregate delta vs market `+0.0067`,
  daily-first delta vs market `+0.0066`.
- `promotion_refresh_broad_claim`: broad claim remains false because aggregate
  `delta_vs_market` is positive and daily-first clearance failed.
- `hourly_ten_minute_weak_slot_gate`: candidate hourly gate remains `BLOCK`;
  early-hour candidate Brier trails market by `+0.0069`, and candidate
  10-minute weak-slot Brier trails market by `+0.0132`.
- `bottom_location_gate`: refreshed v1.15 row export still blocks; first
  blocker is candidate not improving current Brier by `+0.0266`.
- `exact_band_distance_zero_gate`: refreshed v1.15 row export still blocks;
  target Brier trails market by `+0.0111`, above the `+0.0030` tolerance.
- `source_missingness_location_gate`: now uses the v1.15 candidate shadow export
  and still blocks on real slice performance; first blocker is Seattle all-fresh
  candidate trailing market by `+0.0197`.

This removes the stale/missing evidence blocker class for Item 224. The
remaining unblock is a new model/location repair that improves the hard bottom
markets, exact-band early slices, and source/missingness slices versus the
market benchmark; the current v1.15 artifact is not promotable as-is.

## 2026-06-23 forecast-radiation broad-unblock diagnostic

Tested the Item 187 forecast-radiation candidate as a possible broad unblock
for Item 224 because its isolated lane gate passes on positive-market cities.
The diagnostic artifacts are:

- `data/backtest/item224_item187_forecast_radiation_hourly_candidate_performance.json`
- `data/backtest/item224_item187_forecast_radiation_hourly_candidate_performance_report.md`
- `data/backtest/item224_item187_forecast_radiation_ten_minute_performance.json`
- `data/backtest/item224_item187_forecast_radiation_ten_minute_performance_report.md`
- `data/backtest/item224_item187_forecast_radiation_promotion_refresh.json`
- `data/backtest/item224_item187_forecast_radiation_promotion_refresh_report.md`
- `data/backtest/item224_item187_forecast_radiation_bottom_location_winner_centering.json`
- `data/backtest/item224_item187_forecast_radiation_bottom_location_winner_centering_report.md`
- `data/backtest/item224_item187_forecast_radiation_exact_band_distance_zero_calibration.json`
- `data/backtest/item224_item187_forecast_radiation_exact_band_distance_zero_calibration_report.md`

Result: the candidate is not a broad Item 224 unblock.

- Candidate-hourly gate: `BLOCK`; early-hour Brier trails market by `+0.0052`.
- Candidate 10-minute gate: `BLOCK`; weak-slot Brier trails market by
  `+0.0120`.
- Promotion refresh: `3` promote (`dallas`, `denver`, `houston`), `2` shadow
  (`atlanta`, `austin`), and `6` blocked (`chicago`, `los-angeles`, `miami`,
  `nyc`, `san-francisco`, `seattle`).
- Bottom-location gate: `BLOCK`; first blocker is Seattle weak-slot not
  improving current, and the required bottom markets still trail market in
  early/midday slices.
- Exact-band distance-zero gate: `BLOCK`; exact-band early trails market by
  `+0.0065`, and settlement-distance-0 early trails market by `+0.0961`.
- Source/missingness gate: `BLOCK`; bottom all-fresh slices trail market for
  Miami (`+0.0186`), Seattle (`+0.0182`), and NYC (`+0.0143`).

The useful unblocking direction is a composite or retrained no-market repair
that preserves the Item 187 positive-market gains while directly fixing the
bottom-market all-fresh/two-source slices and the exact-band
settlement-distance-0 early rows. The existing predawn repair remains useful
for weak slots, but its row-export surrogate still trails market broadly and
cannot satisfy the active replay/export contract by itself.

## 2026-06-23 bottom-market basket no-go diagnostic

The full all-variant basket validation was too large for a foreground pass, so
the same candidate families were filtered to the hard bottom markets
(`miami`, `nyc`, `seattle`) and rerun as an item-specific diagnostic.

Filtered row inputs are under:

- `data/backtest/item224_basket_inputs/`

Generated diagnostics:

- `data/backtest/item224_bottom_variant_basket_selection_validation.json`
- `data/backtest/item224_bottom_variant_basket_selection_validation_report.md`
- `data/backtest/item224_bottom_variant_basket_no_go.json`
- `data/backtest/item224_bottom_blocked_market_repair_diagnostics.json`
- `data/backtest/item224_bottom_blocked_market_repair_diagnostics_report.md`

Basket result: `blocked`.

- Selected bottom-market basket delta vs market: `+0.0207`, above the
  `+0.0030` tolerance.
- Miami selected `item147_time_split_alpha` and passed later-date eval
  (`delta_vs_market -0.0033`).
- NYC selected `current_max_trust_retrain_v0_1` and blocked
  (`delta_vs_market +0.0287`); even the diagnostic oracle only reached
  `+0.0141`.
- Seattle selected the predawn-repair branch and blocked
  (`delta_vs_market +0.0368`); even the diagnostic oracle only reached
  `+0.0165`.
- Slice-level basket policies also blocked; the best settlement-distance
  oracle was still `+0.0054` versus market.

Repair diagnostic classification:

- Miami: `market_gap_without_clear_winner_signal`; top repair slice is
  `bin_type=eq`, with all-fresh and settlement-distance-0 also contributing.
- NYC: `winner_underpricing_vs_market`; top repair is winner probability mass
  on `settlement_distance_bucket=0` and EQ rows.
- Seattle: `winner_underpricing_vs_market`; top repair is winner probability
  mass on EQ and `settlement_distance_bucket=0` rows.

This rules out a promotion-safe basket of existing no-market branches for the
hard bottom markets. The next aligned unblock is a new retrained or calibrated
candidate that specifically adds winner mass for NYC/Seattle exact-band
settlement-distance-0 rows and repairs Miami EQ/all-fresh market-gap slices,
then replays through the active candidate export contract.

## 2026-06-23 bottom-market winner-mass logistic repair diagnostic

Built a no-market logistic winner-mass repair diagnostic over the hard bottom
markets (`miami`, `nyc`, `seattle`) using only model probabilities and
inference-available slice fields from the aligned current-max, Item 187,
Item 147, Item 32, and predawn candidate rows. The diagnostic trained on
`2026-06-07` and `2026-06-08`, evaluated on `2026-06-12` and `2026-06-13`,
and wrote:

- `data/backtest/item224_bottom_winner_mass_logistic_repair_rows.csv`
- `data/backtest/item224_bottom_winner_mass_logistic_repair.json`
- `data/backtest/item224_bottom_winner_mass_logistic_repair_report.md`
- `data/backtest/item224_bottom_winner_mass_logistic_bottom_location.json`
- `data/backtest/item224_bottom_winner_mass_logistic_bottom_location_report.md`
- `data/backtest/item224_bottom_winner_mass_logistic_exact_band_distance_zero.json`
- `data/backtest/item224_bottom_winner_mass_logistic_exact_band_distance_zero_report.md`

Result: useful lift versus current, but still not a gate-clearing unblock.

- Eval candidate Brier `0.0303` versus current `0.0551`, improving current by
  `-0.0248`.
- Eval candidate still trails market `0.0188` by `+0.0115`.
- Miami eval nearly clears the market tolerance (`+0.0022`), but NYC
  (`+0.0164`) and Seattle (`+0.0181`) remain blocked.
- Bottom-location gate remains `BLOCK` with `6` blockers; Seattle weak-slot,
  early, and midday trail market, NYC weak-slot has no candidate rows, and
  NYC/Miami midday still trail market.
- Exact-band/distance-0 gate remains `BLOCK` with `3` aggregate blockers:
  exact-band early `+0.0059` vs market, settlement-distance-0 early `+0.0642`
  vs market, and one-above early current regression `+0.0278`.

This narrows the next unblock: a winner-mass repair is directionally correct,
but it needs market-competitive NYC/Seattle exact-band settlement-distance-0
performance and a one-above guardrail fix before the active pooled-F export can
clear Item 224.

## 2026-06-23 bottom-market residual manifest and composite no-go

Ran the reusable market residual repair program over the item-specific bottom
market candidate exports and the existing basket no-go registry:

- `data/backtest/item224_bottom_market_residual_repair_program.json`
- `data/backtest/item224_bottom_market_residual_repair_program_report.md`
- `data/backtest/item224_bottom_market_residual_rejected_registry.json`
- `data/backtest/item224_bottom_market_residual_manifests/item231_miami_early_residual_v0_1.json`
- `data/backtest/item224_bottom_market_residual_manifests/item231_nyc_early_residual_v0_1.json`
- `data/backtest/item224_bottom_market_residual_manifests/item231_seattle_early_residual_v0_1.json`

Result: `BLOCK`.

- manifests: `3`.
- passing manifests: `1`.
- blocked manifests: `2`.
- shadow/keep candidate: Miami with `item147_time_split_alpha`
  (`delta_vs_market -0.0059`).
- blocked candidates: NYC with `item147_time_split_alpha`
  (`delta_vs_market +0.0035`, blocker `+0.0037 > +0.0030` on target
  Brier) and Seattle with the predawn/current-fallback repair
  (`delta_vs_market +0.0020`, blocker current regression `+0.0016`).
- rejected registry entries: `23`, including the existing variant basket no-go
  and all current bottom-market candidate families for at least one hard
  market.

Also tested a market-scoped composite export:

- `data/backtest/item224_bottom_market_residual_composite_rows.csv`
- `data/backtest/item224_bottom_market_residual_composite_bottom_location.json`
- `data/backtest/item224_bottom_market_residual_composite_bottom_location_report.md`
- `data/backtest/item224_bottom_market_residual_composite_exact_band_distance_zero.json`
- `data/backtest/item224_bottom_market_residual_composite_exact_band_distance_zero_report.md`

Composite policy: Item 147 for Miami/NYC plus a current-holdout candidate for
Seattle. Result: still `BLOCK`.

- bottom-location gate: `7` blockers. Seattle weak/early/midday still trails
  market by `+0.0104`, `+0.0375`, and `+0.0360`; NYC weak/early/midday trails
  by `+0.0073`, `+0.0033`, and `+0.0068`; Miami midday trails by `+0.0138`.
- exact-band/distance-0 gate: `5` blockers. Aggregate exact-band early trails
  market by `+0.0150`, settlement-distance-0 early trails by `+0.1218`, and
  adjacent guardrails regress current.

This rules out market-scoped routing across the existing no-market candidates.
The remaining Item 224 unblock is a genuinely new NYC/Seattle winner-mass and
midday repair that is competitive with market on exact-band,
settlement-distance-0, weak-slot, early, and midday slices while preserving
Miami's Item 147 gains.

## 2026-06-23 no-market ranked winner repair diagnostic

Built a new bottom-market no-market ranked winner-mass repair using the existing
bottom-market candidate exports as inputs. The diagnostic trained only on
`2026-06-07` and `2026-06-08`, evaluated on `2026-06-12` and `2026-06-13`,
and excluded label-derived and market-derived features from the training
features (`outcome`, `market_yes`, and `settlement_distance_bucket`). It used
candidate probability, rank, modal-band distance, source state, forecast-count,
forecast-disagreement, pressure, cutoff, bin type, and market fields.

Artifacts:

- `data/backtest/item224_bottom_no_market_stacked_winner_repair.json`
- `data/backtest/item224_bottom_no_market_stacked_winner_repair_rows.csv`
- `data/backtest/item224_bottom_no_market_stacked_winner_bottom_location.json`
- `data/backtest/item224_bottom_no_market_stacked_winner_bottom_location_report.md`
- `data/backtest/item224_bottom_no_market_stacked_winner_exact_band_distance_zero.json`
- `data/backtest/item224_bottom_no_market_stacked_winner_exact_band_distance_zero_report.md`
- `data/backtest/item224_bottom_no_market_ranked_winner_repair.json`
- `data/backtest/item224_bottom_no_market_ranked_winner_repair_rows.csv`
- `data/backtest/item224_bottom_no_market_ranked_winner_repair_report.md`
- `data/backtest/item224_bottom_no_market_ranked_winner_bottom_location.json`
- `data/backtest/item224_bottom_no_market_ranked_winner_bottom_location_report.md`
- `data/backtest/item224_bottom_no_market_ranked_winner_exact_band_distance_zero.json`
- `data/backtest/item224_bottom_no_market_ranked_winner_exact_band_distance_zero_report.md`
- `data/backtest/item224_bottom_no_market_ranked_winner_residual_program.json`
- `data/backtest/item224_bottom_no_market_ranked_winner_residual_program_report.md`
- `data/backtest/item224_bottom_market_residual_repair_program_with_ranked.json`
- `data/backtest/item224_bottom_market_residual_repair_program_with_ranked_report.md`

Reproducible command:

`python -m weather.reporting.item224_no_market_ranked_winner_repair --out-rows data\backtest\item224_bottom_no_market_ranked_winner_repair_rows.csv --out-json data\backtest\item224_bottom_no_market_ranked_winner_repair.json --report data\backtest\item224_bottom_no_market_ranked_winner_repair_report.md`

Ranked repair held-out result:

- eval rows: `9251`.
- aggregate eval delta vs current: `-0.0191`.
- aggregate eval delta vs market: `+0.0134`.
- Miami eval delta vs market: `+0.0020`, inside the `+0.0030` market
  tolerance.
- NYC eval delta vs market: `+0.0186`.
- Seattle eval delta vs market: `+0.0194`.

Official gates:

- bottom-location gate: `BLOCK` with `5` blockers, down from `6` for the
  simpler stack. Miami and NYC early/weak slices clear, but Seattle weak
  (`+0.0077` vs current), Seattle early (`+0.0005` vs current), Seattle midday
  (`+0.0221` vs market), NYC midday (`+0.0099` vs market), and Miami midday
  (`+0.0168` vs market) still block.
- exact-band/distance-0 gate: `BLOCK` with `4` blockers. Aggregate exact-band
  early still trails market by `+0.0061`, settlement-distance-0 early trails
  market by `+0.0081`, one-above early regresses current by `+0.0304`, and
  adjacent early regresses current by `+0.0074`.
- market residual repair program: `BLOCK`; Miami passes on
  `item147_time_split_alpha`, but NYC selects the ranked repair and blocks on
  one-above guardrail current regression `+0.0198`, while Seattle selects the
  predawn/current-fallback repair and blocks because target Brier still does not
  improve current (`+0.0016`) despite market delta `+0.0020`.
- combined residual program with all existing bottom-market candidates plus
  the ranked repair: `BLOCK`, with Miami passing on `item147_time_split_alpha`,
  NYC selecting the ranked repair but blocking on one-above guardrail current
  regression `+0.0198`, and Seattle selecting the predawn/current-fallback
  repair but blocking because target Brier still does not improve current
  (`+0.0016`) despite market delta `+0.0020`.

This is progress but not a promotion unblock. The next aligned repair should
add a Seattle-specific early/weak-slot signal and a midday calibration guard
that preserves the ranked repair's Miami/NYC early gains without pushing mass
into one-above/adjacent loser bins.
