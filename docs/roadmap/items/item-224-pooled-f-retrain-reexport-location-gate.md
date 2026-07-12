# 224. Pooled F Retrain/Re-Export Location Gate [PARTIAL 2026-07-11 - REOPENED, ITEM224 V0.1 LABEL-LEAK QUARANTINE]

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

Added `weather.reporting.location_analysis.pooled_f_retrain_location_gate` with schema
`pooled_f_retrain_location_gate_v0.1`.

Artifacts:

- `data/backtest/pooled_f_retrain_location_gate.json`
- `data/backtest/pooled_f_retrain_location_gate_report.md`

Command:

`python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --out data\backtest\pooled_f_retrain_location_gate.json --report data\backtest\pooled_f_retrain_location_gate_report.md`

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
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --out data\backtest\pooled_f_retrain_location_gate.json --report data\backtest\pooled_f_retrain_location_gate_report.md
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
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --out data\backtest\item224_pooled_f_retrain_location_gate.json --report data\backtest\item224_pooled_f_retrain_location_gate_report.md
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
python -m weather.reporting.research.bottom_location_winner_centering --variant-rows data\backtest\current_max_trust_variant_rows.csv --ten-minute-report data\backtest\current_max_trust_ten_minute_performance.json --out data\backtest\bottom_location_winner_centering.json --report data\backtest\bottom_location_winner_centering_report.md
python -m weather.reporting.research.exact_band_distance_zero_calibration --variant-rows data\backtest\current_max_trust_variant_rows.csv --out data\backtest\exact_band_distance_zero_calibration.json --report data\backtest\exact_band_distance_zero_calibration_report.md
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\current_max_trust_candidate_replay.json --out data\backtest\item224_pooled_f_retrain_location_gate.json --report data\backtest\item224_pooled_f_retrain_location_gate_report.md
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

`python -m weather.reporting.research.item224_no_market_ranked_winner_repair --out-rows data\backtest\item224_bottom_no_market_ranked_winner_repair_rows.csv --out-json data\backtest\item224_bottom_no_market_ranked_winner_repair.json --report data\backtest\item224_bottom_no_market_ranked_winner_repair_report.md`

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

## 2026-06-23 no-market postprocess frontier no-go

Ran a no-market post-processing frontier over the ranked winner repair using
only candidate/current probabilities and cutoff regime. The searched transforms
covered per-snapshot early/midday probability sharpening and current-model
blending; no transform used market prices, outcomes, or settlement-distance
features.

Artifacts:

- `data/backtest/item224_no_market_postprocess_frontier.json`
- `data/backtest/item224_no_market_postprocess_frontier_report.md`
- `data/backtest/item224_no_market_postprocess_frontier_3_ae1p2_am1p0_m0p0_mm0p0_rows.csv`
- `data/backtest/item224_no_market_postprocess_frontier_bottom_location.json`
- `data/backtest/item224_no_market_postprocess_frontier_bottom_location_report.md`
- `data/backtest/item224_no_market_postprocess_frontier_exact_band_distance_zero.json`
- `data/backtest/item224_no_market_postprocess_frontier_exact_band_distance_zero_report.md`

Result: `NO_GO`.

- candidate count: `23`.
- pass count: `0`.
- best transform: early sharpening `alpha=1.2`, no midday sharpening, no
  current blend.
- best bottom-location gate: `BLOCK` with `5` blockers; first blocker is
  Seattle weak-slot current regression `+0.0095`.
- best exact-band/distance-0 gate: `BLOCK` with `3` blockers; first blocker is
  exact-band early market gap `+0.0046 > +0.0030`.

This rules out simple probability sharpening or current blending as the Item
224 unblock. The remaining path still requires a genuinely new no-market
signal for Seattle weak/early and bottom-market midday, plus an exact-band
guardrail that closes the market gap without adjacent/one-above regressions.

## 2026-06-23 no-market model frontier partial unblock

Ran a broader no-market model frontier over the same bottom-market candidate
exports. The frontier trained only on `2026-06-07` and `2026-06-08`, evaluated
on `2026-06-12` and `2026-06-13`, and reused the ranked-repair feature set
without `outcome`, `market_yes`, or `settlement_distance_bucket` as model
features. The best candidate was a random-forest classifier with grouped
snapshot normalization.

Artifacts:

- `data/backtest/item224_no_market_model_frontier.json`
- `data/backtest/item224_no_market_model_frontier_report.md`
- `data/backtest/item224_no_market_model_frontier_rf_depth8_w1_rows.csv`
- `data/backtest/item224_no_market_model_frontier_bottom_location.json`
- `data/backtest/item224_no_market_model_frontier_bottom_location_report.md`
- `data/backtest/item224_no_market_model_frontier_exact_band_distance_zero.json`
- `data/backtest/item224_no_market_model_frontier_exact_band_distance_zero_report.md`

Result: partial unblock, still not promotion-ready.

- frontier candidates: `6`.
- full pass count: `0`.
- best held-out eval delta vs current: `-0.0184`.
- best held-out eval delta vs market: `+0.0140`.
- exact-band/distance-0 gate: `PASS` with `0` blockers.
- bottom-location gate: `BLOCK` with `3` blockers, down from `5` for the
  ranked logistic repair and `5` for the postprocess frontier.
- remaining bottom-location blockers are all Seattle: weak-slot trails market
  by `+0.0201`, early trails market by `+0.0107`, and midday trails market by
  `+0.0177`.

This isolates the remaining Item 224 technical blocker to Seattle no-market
winner mass in weak/early/midday slices. The exact-band/distance-0 guardrail can
be cleared by a no-market model frontier, but the Seattle location slice still
needs a new signal or Seattle-specific repair that is competitive with market.

## 2026-06-23 RF plus Seattle-route no-go

Tried a hybrid no-market route that keeps the random-forest frontier candidate
for NYC/Miami while routing Seattle rows through each existing no-market
bottom-market candidate family.

Artifacts:

- `data/backtest/item224_no_market_rf_plus_seattle_route_frontier.json`
- `data/backtest/item224_no_market_rf_plus_seattle_route_frontier_report.md`
- `data/backtest/item224_no_market_rf_plus_seattle_bottom_current_max_trust_variant_rows_rows.csv`

Result: `NO_GO`.

- candidates: `8`.
- pass count: `0`.
- best total blockers: `3`.
- best exact-band/distance-0 result: `PASS` with `0` blockers.
- best bottom-location result: `BLOCK` with `3` blockers; the first blocker is
  Seattle trailing market Brier by `+0.0228 > +0.0030`.

This rules out promotion-safe Seattle routing across the existing no-market
branches. The remaining unblock is a Seattle-specific no-market signal or
training sample expansion that improves weak-slot, early, and midday Seattle
winner mass while preserving the random-forest frontier's exact-band clearance.

## 2026-06-24 Seattle warm-support repair clears bottom/exact gates

Added a repeatable same-corpus no-market Seattle warm-support repair over the
random-forest frontier rows. The repair uses only market id, captured local
time weak-slot membership, cutoff regime, EQ support center, and the source
candidate probability distribution. It excludes `outcome`, `market_yes`, and
`settlement_distance_bucket` as repair features.

Artifacts:

- `data/backtest/item224_no_market_seattle_warm_support_repair.json`
- `data/backtest/item224_no_market_seattle_warm_support_repair_report.md`
- `data/backtest/item224_no_market_seattle_warm_support_repair_rows.csv`
- `data/backtest/item224_no_market_seattle_warm_support_bottom_location.json`
- `data/backtest/item224_no_market_seattle_warm_support_bottom_location_report.md`
- `data/backtest/item224_no_market_seattle_warm_support_exact_band_distance_zero.json`
- `data/backtest/item224_no_market_seattle_warm_support_exact_band_distance_zero_report.md`
- `data/backtest/item224_no_market_seattle_warm_support_source_missingness_location_gate.json`
- `data/backtest/item224_no_market_seattle_warm_support_pooled_f_retrain_location_gate.json`
- `data/backtest/item224_no_market_seattle_warm_support_pooled_f_retrain_location_gate_report.md`

Commands:

```powershell
python -m weather.reporting.research.item224_no_market_seattle_warm_support_repair --input-rows data\backtest\item224_no_market_model_frontier_rf_depth8_w1_rows.csv --ten-minute-report data\backtest\current_max_trust_ten_minute_performance.json --out-rows data\backtest\item224_no_market_seattle_warm_support_repair_rows.csv --out-json data\backtest\item224_no_market_seattle_warm_support_repair.json --report data\backtest\item224_no_market_seattle_warm_support_repair_report.md
python -m weather.reporting.research.bottom_location_winner_centering --variant-rows data\backtest\item224_no_market_seattle_warm_support_repair_rows.csv --ten-minute-report data\backtest\current_max_trust_ten_minute_performance.json --out data\backtest\item224_no_market_seattle_warm_support_bottom_location.json --report data\backtest\item224_no_market_seattle_warm_support_bottom_location_report.md
python -m weather.reporting.research.exact_band_distance_zero_calibration --variant-rows data\backtest\item224_no_market_seattle_warm_support_repair_rows.csv --out data\backtest\item224_no_market_seattle_warm_support_exact_band_distance_zero.json --report data\backtest\item224_no_market_seattle_warm_support_exact_band_distance_zero_report.md
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\current_max_trust_candidate_replay.json --bottom-location data\backtest\item224_no_market_seattle_warm_support_bottom_location.json --exact-distance data\backtest\item224_no_market_seattle_warm_support_exact_band_distance_zero.json --out data\backtest\item224_no_market_seattle_warm_support_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_seattle_warm_support_pooled_f_retrain_location_gate_report.md
```

Result: partial unblock, still not Item 224 complete.

- repair export changed `105` Seattle snapshot groups and `945` EQ rows.
- bottom-location gate: `PASS` with `0` blockers. Seattle now clears weak-slot
  (`+0.0022` vs market), early (`-0.0000` vs market), and midday (`+0.0006`
  vs market).
- exact-band/distance-0 gate: `PASS` with `0` blockers.
- source/missingness direct gate on the repaired rows remains `BLOCK` with `3`
  blockers: NYC missingness hash `3184...`, Seattle missingness hash `3184...`,
  and NYC missingness hash `469d...`.
- top-level pooled-F retrain/location gate remains `BLOCK` with `4` blockers:
  paired candidate replay, promotion-refresh broad claim, hourly/ten-minute
  weak-slot mitigation, and source/missingness location.

This removes the previously isolated Seattle bottom-location and exact-band
technical blocker. The remaining Item 224 work is now a full replay/promotion
contract for the repaired candidate plus source/missingness repair evidence;
the same-corpus row export is not broad promotion evidence by itself.

## 2026-06-24 v0.2 row-export diagnostic clears row gates

Built a broader no-market row-export diagnostic that starts from the Item 147
full-market row export, routes the bottom markets through the Seattle
warm-support repair where it helped, repairs the three source/missingness hard
slices, and applies a conservative exact-band guardrail. This is still a
same-corpus diagnostic row export, not active replay/export-contract evidence.

Artifacts:

- `data/backtest/item224_no_market_market_route_composite_v0_2_rows.csv`
- `data/backtest/item224_no_market_market_route_composite_v0_2.json`
- `data/backtest/item224_no_market_market_route_composite_v0_2_report.md`
- `data/backtest/item224_no_market_market_route_composite_v0_2_replay_summary.json`
- `data/backtest/item224_no_market_market_route_composite_v0_2_replay_summary_report.md`
- `data/backtest/item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json`
- `data/backtest/item224_no_market_market_route_composite_v0_2_hourly_candidate_performance_report.md`
- `data/backtest/item224_no_market_market_route_composite_v0_2_ten_minute_performance.json`
- `data/backtest/item224_no_market_market_route_composite_v0_2_ten_minute_performance_report.md`
- `data/backtest/item224_no_market_market_route_composite_v0_2_bottom_location.json`
- `data/backtest/item224_no_market_market_route_composite_v0_2_bottom_location_report.md`
- `data/backtest/item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json`
- `data/backtest/item224_no_market_market_route_composite_v0_2_exact_band_distance_zero_report.md`
- `data/backtest/item224_no_market_market_route_composite_v0_2_source_missingness_location_gate.json`
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md`
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md`

Regenerated command examples:

```powershell
python -m weather.reporting.candidate_lifecycle.candidate_variant_replay_summary --variant-rows data\backtest\item224_no_market_market_route_composite_v0_2_rows.csv --source-candidate-json data\backtest\current_max_trust_candidate_replay.json --json-out data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --report-out data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md
python -m weather.reporting.candidate_hourly_performance --variant-rows data\backtest\item224_no_market_market_route_composite_v0_2_rows.csv --json-out data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --report-out data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance_report.md
python -m weather.reporting.ten_minute_model_performance --item147-rows data\backtest\item224_no_market_market_route_composite_v0_2_rows.csv --json-out data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --report-out data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance_report.md --slot-csv-out data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_by_slot.csv --candidate-csv-out data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_candidate_by_slot.csv
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Result: partial unblock, still not Item 224 complete.

- row-export replay metrics clear the market comparison diagnostically:
  aggregate `delta_vs_current -0.0096`, aggregate `delta_vs_market -0.0039`,
  and candidate market verdict `PASS`.
- paired candidate replay remains `BLOCK`; blocked validation remains `BLOCK`
  because the evidence is a row-export surrogate, so cutover remains
  `DO_NOT_CUT_OVER`.
- candidate hourly gate: `PASS`.
- candidate ten-minute gate: `PASS`. The lineage mismatch is fixed by carrying
  the full row-export corpus hash `226fe100...` while preserving the
  ten-minute checkpoint hash `5f79e4...` separately.
- bottom-location gate: `PASS` with `0` blockers.
- exact-band/distance-0 gate: `PASS` with `0` blockers.
- source/missingness location gate: `PASS` with `0` blockers.
- promotion refresh still blocks broad weather-only claims. The aggregate
  market delta is negative, but daily-first blocked validation is not countable
  because the replay summary is surrogate-only; all `11` F markets stay
  `BLOCK_CANDIDATE`.
- early-hour promotion no longer blocks on candidate hourly or ten-minute
  mitigation. It now blocks on active replay/export contract evidence,
  live-forward SLO, and current-code soak.
- the top-level pooled-F retrain/location gate remains `BLOCK` with `3`
  blockers: paired candidate replay, promotion-refresh broad claim, and
  hourly/ten-minute promotion clearance. The third blocker is now caused by the
  surrogate replay/export contract, not by candidate weak-slot model
  performance.

Unblocked:

- Seattle bottom-location weak/early/midday repair evidence.
- Exact-band and settlement-distance-0 calibration evidence.
- Source/missingness location evidence for the v0.2 row export.
- Candidate hourly and ten-minute weak-slot mitigation, including matching
  variant/corpus lineage.

Still blocked and how to unblock:

- Active replay/export contract: materialize the v0.2 candidate through the
  active registry/export path, then rerun paired replay so blocked validation
  can be active-contract evidence rather than row-export surrogate evidence.
- Daily-first promotion clearance: rerun promotion refresh from that active
  replay contract; the current row-export metrics are promising but explicitly
  non-countable.
- Production readiness: clear live-forward SLO and current-code soak evidence,
  then refresh `fleet_observability.json`.
- Countable location readiness: refresh settled-day freshness, physical
  readiness can count location validation.

## 2026-06-24 active-contract fail-closed guard

Hardened `weather.reporting.candidate_lifecycle.candidate_variant_replay_summary` so
`validation_evidence=active_replay_contract` now requires an explicit active
registry/export contract JSON (or equivalent in-process payload) backed by a
registered active variant entry. The registry contract must carry a `variant_id`
matching the row export and a `default_export_path` matching the summarized CSV,
plus active lifecycle metadata and the core export-contract fields, before the
replay summary will emit `candidate_shadow_variants.active_registry_contract`.

This prevents promoting the v0.2 diagnostic by merely relabeling its replay
summary. The current v0.2 artifact therefore correctly remains blocked until
the composite repair is represented by a reproducible active export contract
instead of only the generated same-corpus CSV.

Verification:

```powershell
python -m pytest tests\reporting\test_candidate_variant_replay_summary.py tests\calibration\test_promotion_refresh.py -q
```

Result: `56 passed`.

## 2026-06-24 same-corpus active-evidence rejection

Tried the strict active-contract path against the existing v0.2 rows with a
matching in-memory active registry contract. The replay summary now rejects the
artifact before scoring active evidence:

```text
ValueError: active replay contract rows are non-countable: row export carries non-countable/same-corpus diagnostic markers: item224_repair_missingness_hgb=same_corpus_hgb_missingness_v0_2
```

This is expected and keeps the item honest. The v0.2 missingness repair is a
same-corpus diagnostic that separates losing and winning rows too strongly to
serve as proof-grade active replay evidence. The next real unblock is a fresh
schema-current artifact or active policy export that clears the same
source/missingness, exact-band, weak-slot, and promotion gates without
same-corpus repair markers.

## 2026-06-24 settled-day freshness repaired for v0.2 refresh

Ran the local replay-status backfill and settled-day freshness repair for the
promotion target date:

```powershell
python -m weather.operations.replay_status_backfill --snapshots-root data\snapshots --as-of 2026-06-23 --json-out data\backtest\replay_status_backfill.json --report-out data\backtest\replay_status_backfill_report.md
python -m weather.operations.settled_day_freshness repair --target-date 2026-06-22 --snapshots-root data\snapshots --labels-csv data\backtest\market_day_labels.csv --ledger-root data\settlements --json-out data\backtest\settled_day_freshness.json --report-out data\backtest\settled_day_freshness_report.md
```

Result: `data/backtest/settled_day_freshness.json` is now `PASS` with
`12/12` markets complete and `missing_replay_status_count=0`.

Regenerated the v0.2 promotion refresh and pooled-F gate:

```powershell
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

The top-level v0.2 gate remains `BLOCK` with the same three blocker classes:
paired replay, promotion broad-claim clearance, and hourly/ten-minute promotion
clearance. The freshness blocker advanced: settled-day freshness is now clear,
and the next location-countability blocker is the data-layer audit WARN
(`fail=0`, `warn=7`). The active-contract/same-corpus blocker remains the
primary model-evidence blocker.

Verification:

```powershell
python -m pytest tests\reporting\test_candidate_variant_replay_summary.py tests\calibration\test_promotion_refresh.py tests\operations\test_replay_status_backfill.py tests\operations\test_settled_day_freshness.py -q
python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint
```

Result: `61 passed`; roadmap backlog `OK`.


scan-start `coverage_cutoff_utc`, so files created by still-running live CLOB

Ran:

```powershell
python -m weather.reporting.fleet.fleet_observability report --out data\backtest\fleet_observability.json --report data\backtest\fleet_observability_report.md --provenance-out data\backtest\fleet_observability_provenance.json
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Evidence:

  SLA `OK`, `0` missing critical files, manifest hash
  `ae7cefad12394880accff9e2b5375f28af7ca0d16408f004181d73737dfbb192`.
  against the same manifest hash.
- `data/backtest/fleet_observability.json`: still `CRITICAL`, but
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN`, with blockers reduced from `7` to `6`; the
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  top-level status remains `BLOCK` with `3` umbrella blockers.

Remaining blockers:

- active replay/export contract evidence; the v0.2 rows remain non-countable
  same-corpus row-export surrogate evidence.
- location evidence freshness: `data_layer_audit` remains `WARN`
  (`fail=0`, `warn=7`).
- physical feature-family ratchet: `BLOCK`, missing settlement-sliced ablation
  rows.
- live-forward SLO/current-code soak: fleet remains `CRITICAL` because broad
  live-forward collection has snapshot gaps, runtime identity/restart-budget
  blockers, and stale observation-trigger code.

Verification:

```powershell
```

Result: `122 passed, 10 subtests passed`.

## 2026-06-24 physical-family settlement slices refreshed

Regenerated the source-family ablation artifact over the same five settled
days as the prior canonical run, using the current `source_family_ablation`
schema path that emits settlement-sliced effects:

```powershell
python -m weather.backtesting.replay_ablation --sources all_forecasts,coastal_context,eccc_gem,marine_context,mrms_precip,multi_model_guidance,nws_grid,official_us_guidance,open_meteo,open_meteo_family,toronto_official,weather_forecast,wu_history --out data\backtest\source_family_ablation_report.md --json-out data\backtest\source_family_ablation.json data\snapshots\highest-temperature-in-atlanta-on-june-10-2026 data\snapshots\highest-temperature-in-atlanta-on-june-17-2026 data\snapshots\highest-temperature-in-toronto-on-june-15-2026 data\snapshots\highest-temperature-in-toronto-on-june-16-2026 data\snapshots\highest-temperature-in-toronto-on-june-17-2026
python -m weather.reporting.source_gates.physical_feature_family_ratchet --source-family-inventory data\backtest\source_family_inventory.json --source-family-ablation data\backtest\source_family_ablation.json --json-out data\backtest\physical_feature_family_ratchet.json --report-out data\backtest\physical_feature_family_ratchet.md
```

`data/backtest/source_family_ablation.json` now has `slice_effect_count=154`
across the required `market`, `cutoff_regime`, `market_cutoff_regime`, and
`settlement_distance` slice kinds. The physical ratchet now has
`settlement_slice_row_count=168`, up from `0`.

Also hardened `weather.reporting.source_gates.physical_feature_family_ratchet` so lineage
and train/serve parity still come from `source_family_inventory.json`, but
ablation status, rows, days, and pooled deltas prefer the current
`source_family_ablation.json` variant summaries whenever present. This keeps
the refreshed slice rows and current pooled ablation deltas aligned even when
the source-family inventory cannot be refreshed.

Attempted to refresh `source_family_inventory.json`, but the archive-reader
path currently fails on a malformed archived CSV row:

```text
pandas.errors.ParserError: Error tokenizing data. C error: Expected 20 fields in line 110, saw 22
```

The ratchet refresh therefore used the existing inventory for lineage/parity
and the new ablation artifact for current ablation evidence.

Regenerated Item 224 promotion refresh and pooled-F gate:

```powershell
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Result: Item 224 remains `PARTIAL`. The physical-family blocker is narrower
and now evidence-backed: promotion readiness reports
`physical_feature_family_ratchet` as `BLOCK` with `blocked families=10` and
first blocker `harmful_slice_count=5` for `settlement_observation`, rather than
blocking because all settlement-sliced ablation rows are missing. Remaining
physical-family blockers include harmful slices for active observation and
forecast families, near-zero `open_meteo_expanded` pooled lift, lineage gaps
for several inactive families, missing reanalysis slices, and missing
nearby-station feature rows.

Verification:

```powershell
```

Result: `129 passed, 10 subtests passed`.

## 2026-06-24 source-family inventory refresh unblocked

Fixed the closed-market-day artifact reader so legacy malformed CSV rows with
extra fields no longer abort artifact reads. `read_market_day_artifact(...)`
now falls back to a csv-module parser on pandas `ParserError`, drops the extra
legacy fields, and records `csv_parser_fallback_bad_lines` in reader
provenance instead of hiding the issue.

Reran:

```powershell
python -m weather.reporting.source_gates.source_family_inventory --snapshots-root data\snapshots --backtest-root data\backtest --ablation-json data\backtest\source_family_ablation.json --candidate-replay-json data\backtest\pooled_candidate_replay_latest.json --json-out data\backtest\source_family_inventory.json --report-out data\backtest\source_family_inventory_report.md
python -m weather.reporting.source_gates.physical_feature_family_ratchet --source-family-inventory data\backtest\source_family_inventory.json --source-family-ablation data\backtest\source_family_ablation.json --json-out data\backtest\physical_feature_family_ratchet.json --report-out data\backtest\physical_feature_family_ratchet.md
python -m weather.reporting.daily.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Evidence:

- `data/backtest/source_family_inventory.json`: `PASS`; historical reader
  modes are `text_tape: 896` and `validated_parquet: 4`.
- `data/backtest/source_family_inventory_report.md`: `features_long` shows
  `missing_archive_manifest;csv_parser_fallback_bad_lines: 12`, making the
  malformed legacy rows visible instead of fatal.
- `data/backtest/physical_feature_family_ratchet.json`: still `BLOCK`, but
  `blocking_family_count` dropped from `10` to `9`; `open_meteo_expanded`
  moved to `LIVE_ONLY` / diagnostic-only while `settlement_slice_row_count`
  remains `168`.
- `data/backtest/daily_learning.json`: regenerated and still `BLOCKED`, now
  with current input-gate evidence (`input_gate_status=FAIL`,
  `blocker_count=8`) and broad live-forward blocked by the current Toronto
  snapshot coverage gap instead of the older stale-CLOB blocker.
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN` with `6` blockers; physical ratchet detail now says
  `blocked families=9; harmful_slice_count=5`.
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  still `BLOCK` with `3` umbrella blockers: paired candidate replay,
  promotion-refresh broad claim, and hourly/ten-minute weak-slot gate.

Remaining blockers are active replay/export contract evidence for the v0.2
rows, location-evidence freshness (`data_layer_audit` remains `WARN` with
`fail=0`, `warn=7`), physical-family harmful/lineage evidence, and live-forward
SLO/current-code soak.

Verification:

```powershell
python -m pytest tests\operations\test_closed_market_day_archive.py tests\reporting\test_physical_feature_family_ratchet.py tests\calibration\test_promotion_refresh.py tests\reporting\test_candidate_variant_replay_summary.py tests\reporting\test_daily_learning.py -q
python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint
```

Result: `108 passed, 5 subtests passed`; roadmap backlog `OK`.

## 2026-06-24 inactive-family ratchet and data P0 repair

Tightened the physical feature-family ratchet so families that the source
inventory marks as `model_influence=false`, `active_model_feature_count=0`, and
`NOT_USED_BY_ACTIVE_ARTIFACT` are classified as `LIVE_ONLY` / diagnostic-only
before lineage/parity checks. Active artifact families remain strict: they
still need lineage, parity, settled replay rows, required slices, positive
pooled lift, and no harmful slices.

Reran:

```powershell
python -m pytest tests\reporting\test_physical_feature_family_ratchet.py -q
python -m weather.reporting.source_gates.physical_feature_family_ratchet --source-family-inventory data\backtest\source_family_inventory.json --source-family-ablation data\backtest\source_family_ablation.json --json-out data\backtest\physical_feature_family_ratchet.json --report-out data\backtest\physical_feature_family_ratchet.md
python -m weather.reporting.data_quality.data_layer_audit --out data\backtest\data_layer_audit.json --report data\backtest\data_layer_audit_report.md
python -m weather.operations.replay_status_backfill --overwrite --reconstruct-missing --json-out data\backtest\replay_status_backfill.json --report-out data\backtest\replay_status_backfill_report.md
python -m weather.reporting.data_quality.data_layer_audit --out data\backtest\data_layer_audit.json --report data\backtest\data_layer_audit_report.md
python -m weather.reporting.daily.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Evidence:

- `data/backtest/physical_feature_family_ratchet.json`: still `BLOCK`, but
  `blocking_family_count` dropped from `9` to `3`; `7` inactive physical
  families are now diagnostic-only. The remaining evidence-blocked active
  families are `settlement_observation`, `forecast_baseline`, and
  `reanalysis_synoptic`.
- `data/backtest/replay_status_backfill.json`: wrote replay-status artifacts
  for all `225` training-ready folders; `irreparable_folders=0`.
- `data/backtest/data_layer_audit.json`: refreshed to `WARN` with
  `fail_count=0`, `pass_count=10`, and `warn_count=7`; the transient
  `snapshot_artifact_replay_input_status` P0 fail is cleared.
- `data/backtest/daily_learning.json`: regenerated and still `BLOCKED` with
  `blocker_count=8`.
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN` with `6` blockers: active-contract blocked
  validation, `11` blocked F markets, data-layer audit `WARN`, active-contract
  early-hour promotion blocker, physical-family ratchet `blocked families=3`,
  and live-forward SLO.
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  still `BLOCK` with `3` umbrella blockers: paired candidate replay,
  promotion-refresh broad claim, and hourly/ten-minute weak-slot gate.

Remaining blockers are active replay/export contract evidence for the v0.2
rows, data-layer warning cleanup, active physical-family replay/harm evidence,
and live-forward SLO/current-code soak.

## 2026-06-24 data-layer artifact scope narrowed

Backfilled deterministic snapshot explanation sidecars for the replayable
training folders and fixed `SnapshotStore` so explanation backfills can read
`replay_inputs_reconstructed.jsonl` when captured `replay_inputs.jsonl` is
absent. The four remaining legacy Toronto score-only folders still cannot
produce explanation/core sidecars because their historical `snapshots.jsonl`
records do not carry model explanation, feature-vector, or distribution
component payloads.

Also corrected the data-layer audit artifact scope so snapshot artifact gates
count folders with `sidecar_eligibility.labels.training_ready=true`, not merely
any settled folder before the current date. This keeps score-only/replay-only
legacy folders visible in sidecar eligibility without incorrectly failing the
training artifact gate.

Reran:

```powershell
python -m pytest tests\model\test_feature_store.py tests\reporting\test_data_layer_audit.py -q
python -m weather.reporting.data_quality.data_layer_audit --out data\backtest\data_layer_audit.json --report data\backtest\data_layer_audit_report.md
python -m weather.reporting.daily.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Evidence:

- `data/backtest/data_layer_audit.json`: still `WARN`, but `warn_count`
  dropped from `7` to `3`; all snapshot artifact gates now pass at `60/60`
  sidecar-training-ready folders.
- Remaining data-layer warnings are `active_day_sidecar_regression`,
  `snapshot_low_fill_fields`, and `quarantined_impossible_observations`.
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN` with `6` blockers; the location freshness blocker
  now reports `fail=0, warn=3`.
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  still `BLOCK` with `3` umbrella blockers: paired candidate replay,
  promotion-refresh broad claim, and hourly/ten-minute weak-slot gate.

## 2026-06-24 data P0 cleared to active-payload warning

Repaired the remaining locally reconstructable data-layer blockers used by
Item 224 location countability:

- backfilled deterministic snapshot-cadence quality columns into historical
  `snapshots_long.csv` rows and narrowed the low-fill gate to required fields,
  keeping intentionally sparse diagnostic/market-microstructure fields out of
  the blocker count;
- date-indexed WU raw-observation quarantines in source manifests so impossible
  all-history anomalies remain visible without blocking target-season training
  evidence when every quarantined record is dated;
- repaired active-day `replay_input_status` sidecars for the June 24 active
  folders; and
- marked active-day `observation_payloads` sidecar gaps as non-reconstructable
  unless `forecast_payloads_long.csv` contains observation-source payload rows.

Reran:

```powershell
python -m weather.reporting.data_quality.data_layer_audit --out data\backtest\data_layer_audit.json --report data\backtest\data_layer_audit_report.md
python -m weather.reporting.daily.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md
python -m weather.calibration.pooled_candidate_replay --corpus data\backtest\promotion_corpus.json --artifact data\backtest\current_max_trust_retrain_merged_candidate.pkl --out data\backtest\current_max_trust_candidate_replay_report.md --json-out data\backtest\current_max_trust_candidate_replay.json --replay-report=data\backtest\current_max_trust_candidate_current_replay_report.md --candidate-variant-out data\backtest\current_max_trust_variant_rows.csv --candidate-variant-id current_max_trust_retrain_v0_1 --candidate-variant-family pooled_f_current_max_trust --skip-microstructure-overlay --source-state-ablation-variant-out= --bridge-variant-out= --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.candidate_lifecycle.candidate_variant_replay_summary --variant-rows data\backtest\item224_no_market_market_route_composite_v0_2_rows.csv --source-candidate-json data\backtest\current_max_trust_candidate_replay.json --json-out data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --report-out data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Evidence:

- `data/backtest/data_layer_audit.json`: `WARN` with `fail_count=0`,
  `pass_count=16`, and `warn_count=1`. The only remaining data-layer warning
  is `active_day_sidecar_regression` for eight active/future June 24 folders
  missing `observation_payloads`.
- The active observation payload gap is not locally reconstructable: the active
  folders' `forecast_payloads_long.csv` files contain forecast/guidance
  sources but no observation-source payload rows. The unblock is a live
  snapshot-loop run with observation raw payload persistence enabled, then a
  data-layer audit refresh.
- `data/backtest/current_max_trust_candidate_replay.json`: refreshed against
  the current promotion corpus hash
  `11b641c789ee73e9846b918f27cf6ab5176ebed6f0031ce4d0f50dde627e4275`;
  verdict remains `BLOCK`, cutover `DO_NOT_CUT_OVER`.
- `data/backtest/item224_no_market_market_route_composite_v0_2_replay_summary.json`:
  regenerated from the refreshed source replay. It remains
  `validation_evidence=row_export_surrogate`, `verdict=BLOCK`,
  `cutover_decision=DO_NOT_CUT_OVER`; row-export metrics remain favorable
  (`delta_vs_current=-0.0096`, `delta_vs_market=-0.0039`) but non-countable.
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN` with `6` blockers: active-contract blocked
  validation, `11` blocked F markets, data-layer audit `WARN` (`fail=0`,
  `warn=1`), active-contract early-hour promotion blocker, physical-family
  ratchet (`blocked families=3; harmful_slice_count=5`), and live-forward SLO.
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  still `BLOCK` with `3` umbrella blockers: paired candidate replay,
  promotion-refresh broad claim, and hourly/ten-minute promotion clearance.

Still blocked and how to unblock:

- Active replay/export contract: build a fresh schema-current active policy or
  artifact export that does not carry the same-corpus diagnostic repair markers,
  then rerun paired replay with `validation_evidence=active_replay_contract`.
- Countable data-layer freshness: run the live snapshot loop with observation
  raw payload persistence enabled for the active-day folders, then rerun the
  observation sidecar backfill and data-layer audit.
- Physical-family ratchet: resolve harmful active-family settlement slices for
  `settlement_observation` and `forecast_baseline`, and produce required
  settlement-sliced ablation rows for `reanalysis_synoptic`.
- Production readiness: clear live-forward SLO and current-code soak in
  `fleet_observability.json`; current fleet status remains `CRITICAL`.

## 2026-06-24 data and ingest gates cleared

Repaired the active observation raw-payload path and refreshed the active-day
sidecars so the data-layer gate is no longer blocking Item 224 location
countability. `fetch_wu_current`, `fetch_metar`, and `fetch_eccc_swob` now
return raw observation payloads for sidecar persistence, then foreground repair
captures filled the June 24 active folders.

Also tightened the ingest-quality gate to use the same redundant-source
coverage already used by fleet observability: raw WU missing/sparse historical
target-window days remain visible, but they do not warn when complete redundant
sources cover the affected days.

Reran:

```powershell
python -m pytest tests\model\test_source_cache_ttl.py -q
python -m pytest tests\operations\test_daily_refresh.py -q
python -m weather.reporting.data_quality.data_layer_audit --out data\backtest\data_layer_audit.json --report data\backtest\data_layer_audit_report.md
python -m weather.reporting.daily.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Evidence:

- `data/backtest/data_layer_audit.json`: `PASS` with `fail_count=0`,
  `warn_count=0`, and `pass_count=17`.
- `data/backtest/ingest_quality_gate.json`: `PASS`; raw WU still has
  `raw_markets_with_missing_days=8` and `raw_markets_with_sparse_days=12`, but
  redundant sources cover `196` historical issue days and leave
  `historical_gap_unresolved_issue_days=0`.
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN` with `6` blockers. The location freshness blocker
  now points at fleet/daily readiness instead of data-layer or ingest quality:
  `fleet_observability` is `CRITICAL`, and `daily_learning` remains `BLOCKED`.
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  still `BLOCK` with `3` umbrella blockers. Schema/provenance, predawn repair,
  bottom-location, exact-band/distance-zero, and source/missingness gates all
  pass.

Remaining blockers and unblock path:

- Active replay/export contract: produce a fresh schema-current active policy
  or artifact export that is not a same-corpus row-export surrogate, then rerun
  paired replay with `validation_evidence=active_replay_contract`.
- Broad promotion claim: keep blocked until the active-contract replay clears
  daily-first validation and the promotion refresh can allow market-specific
  candidate use without surrogate evidence.
- Physical-family ratchet: resolve the active-family blockers for
  `settlement_observation`, `forecast_baseline`, and `reanalysis_synoptic`;
  current evidence is `blocked families=3; harmful_slice_count=5`.
- Production readiness: clear live-forward SLO/current-code soak in
  `fleet_observability.json`; current fleet status remains `CRITICAL`.

## 2026-06-24 active-contract investigation

Checked whether the existing composite exports could be promoted into active
replay/export-contract evidence without generating a new active export.

Findings:

- `data/backtest/item224_no_market_market_route_composite_v0_2.json` declares
  `status=DIAGNOSTIC_ROW_EXPORT`; its row export contains
  `item224_repair_missingness_hgb=same_corpus_hgb_missingness_v0_2` on `3801`
  rows. The active replay contract guard correctly rejects those rows as
  non-countable same-corpus diagnostic evidence.
- `data/backtest/item224_no_market_market_route_composite.json` / v0.1 has no
  populated same-corpus marker and metric-passes as a row-export diagnostic
  (`delta_vs_current=-0.0068`, `delta_vs_market=-0.0011`), but it still reports
  `validation_evidence=row_export_surrogate` and is not produced by a
  supported active registry runtime.
- `weather.reporting.candidate_lifecycle.active_variant_shadow_refresh` currently supports active
  registered `pooled_candidate_replay` artifact exports plus the existing
  conservative-bridge and microstructure derived runtimes. It does not have an
  active runtime contract for the Item 224 market-route composite repair.
- Hardened `weather.reporting.candidate_lifecycle.candidate_variant_replay_summary` so active
  replay/export contract rows with upstream source variant lineage now require
  those source variants to be registered, active, and headline-countable too.
  A live probe against the v0.1 row export now rejects it with:
  `row export references unregistered source variant(s):
  item136_source_state_reliability_v0_1, item147_time_split_alpha,
  item224_no_market_seattle_warm_support_repair_v0_1,
  item32_reanalysis_austin_guard_chicago_nyc_raw,
  item50_pooled_forecast_v3_candidate`.
- Attempted the fleet immediate loop-log repair commands from
  `fleet_observability.json`; `weather.operations.loop_jsonl_repair` returned
  `BLOCK` because the affected console logs are held by active writer locks.
  The broader live-forward SLO remains blocked by nonrecoverable June 23
  snapshot coverage gaps for Los Angeles, San Francisco, and Seattle.

Concrete unblock: implement and register a real active export/runtime for the
candidate family, or retrain a schema-current pooled F artifact that captures
the v0.1/v0.2 gains without same-corpus diagnostic repair markers, then rerun
the active replay/export contract and promotion gates.

## 2026-06-24 physical ratchet evidence narrowed

Tightened the physical feature-family ratchet and promotion readiness reader so
active-family decisions use the selected ablation variant instead of mixing in
diagnostic sub-source slices, and so Item 27 reanalysis feature-value evidence
contributes its existing market and cutoff-regime slices.

Reran:

```powershell
python -m pytest tests\reporting\test_physical_feature_family_ratchet.py tests\calibration\test_promotion_refresh.py -q
python -m weather.reporting.source_gates.physical_feature_family_ratchet --source-family-inventory data\backtest\source_family_inventory.json --source-family-ablation data\backtest\source_family_ablation.json --json-out data\backtest\physical_feature_family_ratchet.json --report-out data\backtest\physical_feature_family_ratchet.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Evidence:

- `data/backtest/physical_feature_family_ratchet.json`: still `BLOCK` with
  `blocking_family_count=3`, but the blockers are now exact:
  `settlement_observation` has `harmful_slice_count=5`,
  `forecast_baseline` has `harmful_slice_count=1` on the selected
  `all_forecasts` variant, and `reanalysis_synoptic` now has 51 market/cutoff
  slices but remains blocked on missing `settlement_distance` slices plus
  `harmful_slice_count=17`.
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN` with `6` blockers, but the
  `physical_feature_family_ratchet` blocker now lists all three blocked
  active families and their concrete reasons.
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  remains `BLOCK` with the same three umbrella blockers: paired candidate
  replay, promotion-refresh broad claim, and hourly/ten-minute promotion
  clearance.

Remaining physical unblock: produce settlement-distance-sliced reanalysis
feature-value evidence, then repair or gate the harmful active-family slices:
WU/history observation early and midday slices, the Toronto-midday
`all_forecasts` slice, and the reanalysis market/cutoff slices for Chicago,
Denver, NYC, San Francisco, Seattle, and Toronto.

## 2026-06-24 reanalysis band ablation and freshness repair

Produced active-artifact band-ablation evidence for `reanalysis_synoptic` by
replaying the current max-trust artifact once with reanalysis features intact
and once through the production reanalysis masking lane. This replaces the
previous proxy-only Item 27 evidence for the active artifact and adds the
required `settlement_distance` slice kind to
`data/backtest/source_family_ablation.json`.

Also refreshed June 23 WU daily summaries for all 12 markets and reran the
settled-day freshness gate. `data/backtest/settled_day_freshness.json` is now
`PASS` with `source_lag_warning_count=0`, so location evidence freshness is no
longer blocked by settled-day source lag.

Reran:

```powershell
python -m weather.reporting.research.reanalysis_synoptic_band_ablation --corpus data\backtest\promotion_corpus.json --snapshots-root data\snapshots --artifact data\backtest\current_max_trust_retrain_merged_candidate.pkl --json-out data\backtest\reanalysis_synoptic_band_ablation.json --report-out data\backtest\reanalysis_synoptic_band_ablation.md --merged-source-family-ablation-out data\backtest\source_family_ablation.json
python -m weather.reporting.source_gates.physical_feature_family_ratchet --source-family-inventory data\backtest\source_family_inventory.json --source-family-ablation data\backtest\source_family_ablation.json --json-out data\backtest\physical_feature_family_ratchet.json --report-out data\backtest\physical_feature_family_ratchet.md
python -m weather.sources.wu_history --market <market> backfill --start 2026-06-23 --end 2026-06-23 --skip-existing --continue-on-error --chunk-days 1 --sleep 0
python -m weather.operations.settled_day_freshness report --target-date 2026-06-23 --snapshots-root data\snapshots --labels-csv data\backtest\market_day_labels.csv --ledger-root data\settlements --json-out data\backtest\settled_day_freshness.json --report-out data\backtest\settled_day_freshness_report.md
python -m weather.reporting.daily.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Evidence:

- `data/backtest/reanalysis_synoptic_band_ablation.json`: scored `51997`
  rows over `44` days with `50` slice rows, including `3`
  `settlement_distance` slices. The aggregate ablation delta is
  `+0.0000495`; the `adjacent` settlement-distance slice remains harmful at
  about `-0.000286`.
- `data/backtest/physical_feature_family_ratchet.json`: still `BLOCK` with
  `blocking_family_count=3`, but the reanalysis blocker is now measured
  active-artifact evidence: `pooled_delta=4.9496283542734e-05` and
  `harmful_slice_count=11`. The old missing `settlement_distance` blocker is
  gone.
- `data/backtest/settled_day_freshness.json`: `PASS`; all `12` markets are
  complete, `needs_finalization_count=0`, `missing_replay_status_count=0`, and
  `source_lag_warning_count=0`.
- `data/backtest/daily_learning.json`: still `BLOCKED`; coverage is
  `18/20` inputs with non-critical missing inputs
  `taker_finalization_watchdog` and `taker_tail_casebook`, and the hard
  consistency invariant `promotion_corpus_vs_settled_labels` still fails.
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN` with `6` blockers. The freshness blocker now starts
  at `fleet_observability` (`CRITICAL`, `live_forward=BLOCK`,
  `critical_alerts=5`) instead of settled-day freshness.
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  still `BLOCK` with `3` umbrella blockers: paired candidate replay,
  promotion-refresh broad claim, and hourly/ten-minute weak-slot promotion.

Active-contract check: the registered `pooled_candidate_replay` path for the
current max-trust artifact remains insufficient by itself
(`delta_vs_market=+0.0067`). The row-export composite metrics remain favorable,
but v0.2 is same-corpus diagnostic evidence and v0.1 depends on diagnostic or
unregistered source lineage. The remaining countable unblock is still a real
active export/runtime or a fresh schema-current artifact that reproduces the
location gains without same-corpus repair markers.

## 2026-06-24 daily-learning date repair and refreshed Item 224 gates

Repaired the remaining daily-learning date/freshness blocker class. Trading
evidence now writes root `run_date` / `target_date` metadata from the latest
settlement-scored taker day, and daily learning uses that date by default when
`--run-date` is not supplied. Also fixed the daily-refresh CLI lock-diagnostic
dependency so resumable refresh runs no longer fail before the runner starts.

Reran:

```powershell
python -m pytest tests\reporting\test_daily_learning.py tests\reporting\test_trading_evidence.py tests\operations\test_daily_refresh.py::TestDailyRefresh::test_cli_run_injects_lock_diagnostic_before_runner -q
python -m weather.operations.daily_refresh run --resume-from-step data_retention_inventory --as-of 2026-06-23 --continue-on-error --disable-long-job-guard --allow-hourly-performance-gate --allow-ten-minute-performance-gate --allow-variant-evidence-alert
python -m weather.reporting.trading_evidence --mm-runs-root data\mm_runs --taker-runs-root data\taker_runs --json-out data\backtest\trading_evidence.json --report-out data\backtest\trading_evidence_report.md
python -m weather.reporting.daily.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Current evidence:

- `data/backtest/trading_evidence.json`: `CRITICAL`, with root
  `run_date=2026-06-22`, `target_date=2026-06-22`, and settlement-scored
  target dates `2026-06-19` through `2026-06-22`. The remaining trading
  blockers are substantive: MM evidence starvation is `CRITICAL`, and taker
  strategy quality is `BLOCK`.
- `data/backtest/daily_learning.json`: still `BLOCKED`, but input consistency
  is now `PASS`; freshness is only a non-critical `WARN` with
  `critical_stale_inputs=0`. The remaining eight blockers are live-forward
  SLO, hourly early-hour performance, ten-minute weak slots, daily-first
  validation, early-hour active-export contract, collection health,
  current-code soak, and taker strategy quality.
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN` with `6` blockers: active-contract
  `blocked_validation`, `11` per-market F blocks, fleet freshness/live-forward,
  early-hour active-contract fail-closed, physical-family ratchet, and
  live-forward SLO.
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  still `BLOCK` with `3` umbrella blockers: candidate replay
  `blocked_validation=BLOCK`, the broad promotion claim, and surrogate-only
  hourly/ten-minute promotion evidence.

Conclusion: the local freshness/date repair work is complete. Item 224 remains
`PARTIAL` because the countable unblock still requires a real active
replay/export contract or a fresh schema-current artifact that reproduces the
location gains without same-corpus markers, plus live-forward/current-code soak
and physical-family ratchet clearance.

## 2026-06-24 current-corpus active-family ablation probe

Reran source-family ablation for the two remaining active non-reanalysis
families over the current 51-entry promotion corpus, then merged the probe into
`data/backtest/source_family_ablation.json` for `wu_history` and
`all_forecasts`.

Reran:

```powershell
$corpus = Get-Content data\backtest\promotion_corpus.json -Raw | ConvertFrom-Json; $folders = @($corpus.entries | ForEach-Object { $_.folder }); python -m weather.backtesting.replay_ablation --sources wu_history,all_forecasts --out data\backtest\item224_active_family_ablation_probe.md --json-out data\backtest\item224_active_family_ablation_probe.json @folders
python -m weather.reporting.source_gates.physical_feature_family_ratchet --source-family-inventory data\backtest\source_family_inventory.json --source-family-ablation data\backtest\source_family_ablation.json --json-out data\backtest\physical_feature_family_ratchet.json --report-out data\backtest\physical_feature_family_ratchet.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Evidence:

- `data/backtest/item224_active_family_ablation_probe.json`: both active
  families have strong pooled lift over `76879` rows and `51` entries:
  `all_forecasts delta=+0.0382`, `wu_history delta=+0.0299`.
- The broader corpus does not clear the strict no-harm ratchet. It confirms
  harmful slices remain: `all_forecasts` has `6` harmful slices and
  `wu_history` has `9` harmful slices.
- `data/backtest/source_family_ablation.json`: now has `14` variants and
  `284` slice-effect rows, including the current-corpus `wu_history` and
  `all_forecasts` probe plus the active-artifact `reanalysis_synoptic`
  evidence.
- `data/backtest/physical_feature_family_ratchet.json`: still `BLOCK` with
  `blocking_family_count=3` and `settlement_slice_row_count=226`:
  `settlement_observation harmful_slice_count=9`,
  `forecast_baseline harmful_slice_count=6`, and
  `reanalysis_synoptic pooled_delta=4.9496283542734e-05` with
  `harmful_slice_count=11`.
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN` with `6` blockers and the updated physical ratchet
  detail above.
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  still `BLOCK` with the same `3` umbrella blockers.

Conclusion: stale or narrow physical evidence is no longer the explanation for
the active observation/forecast blockers. The active families are broadly
valuable in pooled lift, but the current ratchet still blocks promotion because
specific market/cutoff slices are harmful.

## 2026-06-24 live-forward pass and recovery-closeout probe

Refreshed the live operational evidence after `snapshot_tracker --status`
showed the June 24 collection loop healthy across all 12 markets with no
snapshot gaps and current runtime identity. `fleet_observability.json` now has
`live_forward_slo_status=PASS`, so the separate Item 224 live-forward SLO
blocker is no longer present in the refreshed promotion-readiness artifact.

Also ran the two legitimate local recovery probes for the remaining fleet
critical blockers:

```powershell
python -m weather.operations.loop_jsonl_repair audit data\snapshots\loop_console.log data\snapshots\observation_trigger_console.log --json-out data\backtest\item224_loop_jsonl_repair_audit.json --report-out data\backtest\item224_loop_jsonl_repair_audit.md
python -m weather.operations.loop_jsonl_repair repair data\snapshots\loop_console.log data\snapshots\observation_trigger_console.log --json-out data\backtest\item224_loop_jsonl_repair_attempt.json --report-out data\backtest\item224_loop_jsonl_repair_attempt.md
python -m weather.operations.market_making_preflight_recovery --run-folder data\mm_runs\2026-06-20\20260620T233005288278Z --execute-remediation --timeout-seconds 300
python -m weather.reporting.trading_evidence --mm-runs-root data\mm_runs --taker-runs-root data\taker_runs --json-out data\backtest\trading_evidence.json --report-out data\backtest\trading_evidence_report.md
python -m weather.reporting.fleet.fleet_observability report --out data\backtest\fleet_observability.json --report data\backtest\fleet_observability_report.md --provenance-out data\backtest\fleet_observability_provenance.json
python -m weather.reporting.daily.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --precomputed-candidate-report data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\item224_no_market_market_route_composite_v0_2_ten_minute_performance.json --out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --report data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_no_market_market_route_composite_v0_2_promotion_allowlist.json --incomplete-manifest data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_no_market_market_route_composite_v0_2_replay_summary.json --promotion-refresh data\backtest\item224_no_market_market_route_composite_v0_2_promotion_refresh.json --bottom-location data\backtest\item224_no_market_market_route_composite_v0_2_bottom_location.json --exact-distance data\backtest\item224_no_market_market_route_composite_v0_2_exact_band_distance_zero.json --out data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json --report data\backtest\item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate_report.md
```

Evidence:

- `data/backtest/fleet_observability.json`: still `CRITICAL`, but
  `live_forward_slo_status=PASS`; the remaining criticals are
  `current_code_soak=BLOCK` and `mm_evidence_starvation=CRITICAL`.
- `data/backtest/item224_loop_jsonl_repair_attempt.md`: `BLOCK`. The
  malformed active console logs are real (`loop_console.log` and
  `observation_trigger_console.log`), but repair correctly refuses to rewrite
  them while live writer locks are present. Countable repair requires a
  maintenance stop of the writers before rerunning the repair, not
  `--allow-active` during collection.
- `data/mm_runs/2026-06-20/20260620T233005288278Z/preflight_recovery_closeout.json`:
  `ATTEMPTED_UNRECOVERED` with `execution_requested=true`. The three
  allowlisted recovery commands executed and returned `PASS`
  (`snapshot_tracker --status`, `market_microstructure ensure`, and
  `observation_trigger ensure`), but the post-repair run is still `STALE`,
  does not count toward the live-forward gate, and has `0` quote rows and `0`
  live-trade permission rows.
- `data/backtest/fleet_observability_report.md`: MM starvation is no longer a
  missing-closeout issue; it is an attempted-but-unrecovered historical
  active-day evidence loss.
- `data/backtest/item224_no_market_market_route_composite_v0_2_promotion_refresh.json`:
  readiness remains `OPEN`, now with `5` blockers instead of `6`: active
  replay/export contract blocked validation, `11` per-market F blocks,
  fleet/daily evidence countability (`live_forward=PASS`, but fleet still
  `CRITICAL`), early-hour active-contract/current-code fail-closed, and the
  physical-family ratchet.
- `data/backtest/item224_no_market_market_route_composite_v0_2_pooled_f_retrain_location_gate.json`:
  still `BLOCK` with `3` umbrella blockers: paired candidate replay,
  promotion-refresh broad claim, and surrogate-only hourly/ten-minute
  promotion evidence.

Conclusion: one local blocker moved: broad live-forward collection SLO is now
green in the refreshed evidence. Item 224 remains `PARTIAL` because the
countable unblock still requires an active replay/export contract or fresh
schema-current artifact for the composite, a clean current-code soak window
after the restart budget ages out and active log repair can be done safely, MM
evidence that is recovered or no longer starved, and physical-family no-harm
ratchet clearance for the remaining harmful slices.

## 2026-06-24 active-contract replay probe

Audited the model-variant registry and replayed the existing active no-market
contracts through strict `validation_evidence=active_replay_contract` summary
mode.

```powershell
python -m weather.reporting.candidate_lifecycle.variant_registry --json-out data\backtest\item224_variant_registry_audit.json --report-out data\backtest\item224_variant_registry_audit.md
python -m weather.reporting.candidate_lifecycle.candidate_variant_replay_summary --variant-rows <active-export-path> --validation-evidence active_replay_contract --active-registry-contract-json <active-contract-json> --json-out data\backtest\item224_active_contract_replay\<variant>_summary.json --report-out data\backtest\item224_active_contract_replay\<variant>_summary.md
```

Evidence:

- `data/backtest/item224_variant_registry_audit.json`: `OK`; `8` active
  contracts, `7` evidence paths, and no missing active variants.
- `data/backtest/item224_active_contract_replay/summary.json`: the existing
  active no-market contracts are countable active-contract evidence but still
  block cutover because they trail market:
  `item50_pooled_forecast_v3_candidate` daily-first
  `delta_vs_market=+0.00718568527543182`,
  `pooled_f_dynamic_source_state_v0_1` `+0.0073913915988035525`,
  `pooled_f_candidate_miami_current_fallback_v0_1`
  `+0.008651853866990116`,
  `pooled_f_exact_winner_catchup_v0_1` `+0.008877437319451974`, and
  `pooled_continuous_density_hgb_v0_1` `+0.014364446495755613`.
- The shared-export active variants (`conservative_bridge_policy_v0_1`,
  `clob_overlay_gated_taxonomy`, and `clob_overlay_raw_oof`) are not Item 224
  unblocks here: their export files also contain control or sibling variants,
  and the strict single-contract summary rejects them rather than counting a
  mixed row export.
- `data/backtest/item224_no_market_market_route_composite_rows.csv`: v0.1 has
  no same-corpus marker, but routes through unregistered diagnostic source
  variants (`item147_time_split_alpha`,
  `item224_no_market_seattle_warm_support_repair_v0_1`,
  `item32_reanalysis_austin_guard_chicago_nyc_raw`,
  `item136_source_state_reliability_v0_1`, and
  `item50_pooled_forecast_v3_candidate`), so it cannot be upgraded to active
  contract evidence by adding a registry label.
- `data/backtest/item224_no_market_market_route_composite_v0_2_rows.csv`: v0.2
  has `3801` rows with
  `item224_repair_missingness_hgb=same_corpus_hgb_missingness_v0_2`, so the
  active-contract guard correctly rejects it as non-countable diagnostic
  evidence even though its aggregate metrics are favorable.
- Other Item 224 row exports checked in this pass are either mixed
  multi-variant diagnostic composites or explicitly set
  `counts_toward_weather_model_promotion=false`.

Conclusion: there is no existing active registry contract that both counts and
clears Item 224. The remaining active-contract unblock is still to produce a
real active export/runtime or a fresh schema-current pooled F artifact that
captures the composite gains without same-corpus repair markers or diagnostic
source lineage.

## 2026-06-24 physical harmful-slice unblock audit

Extracted the current active-family harmful slices to
`data/backtest/item224_physical_harmful_slices.json` and checked the ratchet
implementation in `src/weather/reporting/physical_feature_family_ratchet.py`.
The remaining physical blocker is not a stale-evidence or reporting-policy
issue: the ratchet still blocks when an active family has harmful settlement
slices, and `reanalysis_synoptic` also fails the pooled-lift threshold.

Evidence:

- `settlement_observation` / `wu_history`: pooled
  `delta=+0.029927863084512597`, but `harmful_slice_count=9`. The harmful
  slices are `cutoff_regime=midday`, `market_cutoff_regime=midday` for
  Atlanta, Chicago, Denver, Miami, NYC, and Seattle, plus early Miami and early
  Toronto.
- `forecast_baseline` / `all_forecasts`: pooled
  `delta=+0.038226827077627375`, but `harmful_slice_count=6`. The harmful
  slices are late `market_cutoff_regime` for Chicago, Dallas, Houston, Miami,
  San Francisco, and Toronto.
- `reanalysis_synoptic`: pooled `delta=+4.9496283542734e-05` with
  `harmful_slice_count=11`. Harm remains in market-level Chicago, Los Angeles,
  and San Francisco; early/midday/late market-cutoff slices; and
  `settlement_distance=adjacent`.

Conclusion: there is no countable local unblock left for the physical ratchet
by changing the report. Clearing it requires a real active model or serving
change that removes, gates, or improves those harmful active-family slices,
followed by fresh countable ablation evidence.

## 2026-06-24 fresh artifact probes

Closed the remaining local "just retrain or postprocess the active artifact"
path with schema-current probes. None of these probes was registered or
promoted.

Commands:

```powershell
python -m weather.calibration.pooled_candidate_replay --artifact data\backtest\item224_active_pooled_source_freshness_guardrail.pkl --out data\backtest\item224_active_pooled_source_freshness_guardrail_replay_report.md --json-out data\backtest\item224_active_pooled_source_freshness_guardrail_replay.json --candidate-variant-out data\backtest\item224_active_pooled_source_freshness_guardrail_rows.csv --candidate-variant-id item224_active_pooled_source_freshness_guardrail_v0_1 --candidate-variant-family item224_active_pooled_source_freshness_guardrail --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --skip-microstructure-overlay --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.candidate_hourly_performance --variant-rows data\backtest\item224_active_pooled_source_freshness_guardrail_rows.csv --json-out data\backtest\item224_active_pooled_source_freshness_guardrail_hourly_candidate_performance.json --report-out data\backtest\item224_active_pooled_source_freshness_guardrail_hourly_candidate_performance_report.md
python -m weather.reporting.research.exact_band_distance_zero_calibration --variant-rows data\backtest\item224_active_pooled_source_freshness_guardrail_rows.csv --out data\backtest\item224_active_pooled_source_freshness_guardrail_exact_band_distance_zero.json --report data\backtest\item224_active_pooled_source_freshness_guardrail_exact_band_distance_zero_report.md
python -m weather.reporting.research.bottom_location_winner_centering --variant-rows data\backtest\item224_active_pooled_source_freshness_guardrail_rows.csv --ten-minute-report data\backtest\current_max_trust_ten_minute_performance.json --out data\backtest\item224_active_pooled_source_freshness_guardrail_bottom_location.json --report data\backtest\item224_active_pooled_source_freshness_guardrail_bottom_location_report.md
python -m weather.calibration.pooled_feature_model --objective band --family-unit F --exact-winner-catchup --source-freshness-guardrail --max-days-per-market 30 --artifact data\backtest\item224_exact_source_guardrail_smoke30.pkl --out data\backtest\item224_exact_source_guardrail_smoke30_report.md --min-artifact-free-bytes 0
python -m weather.calibration.pooled_candidate_replay --artifact data\backtest\item224_exact_source_guardrail_smoke30.pkl --out data\backtest\item224_exact_source_guardrail_smoke30_replay_report.md --json-out data\backtest\item224_exact_source_guardrail_smoke30_replay.json --candidate-variant-out data\backtest\item224_exact_source_guardrail_smoke30_rows.csv --candidate-variant-id item224_exact_source_guardrail_smoke30 --candidate-variant-family item224_exact_source_guardrail --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --skip-microstructure-overlay --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.candidate_hourly_performance --variant-rows data\backtest\item224_exact_source_guardrail_smoke30_rows.csv --json-out data\backtest\item224_exact_source_guardrail_smoke30_hourly_gate.json --report-out data\backtest\item224_exact_source_guardrail_smoke30_hourly_gate.md
python -m weather.reporting.research.exact_band_distance_zero_calibration --variant-rows data\backtest\item224_exact_source_guardrail_smoke30_rows.csv --out data\backtest\item224_exact_source_guardrail_smoke30_exact_distance_zero_gate.json --report data\backtest\item224_exact_source_guardrail_smoke30_exact_distance_zero_gate.md
python -m weather.reporting.research.bottom_location_winner_centering --variant-rows data\backtest\item224_exact_source_guardrail_smoke30_rows.csv --ten-minute-report data\backtest\current_max_trust_ten_minute_performance.json --out data\backtest\item224_exact_source_guardrail_smoke30_bottom_location_gate.json --report data\backtest\item224_exact_source_guardrail_smoke30_bottom_location_gate.md
python -m weather.calibration.pooled_feature_model --objective band --family-unit F --exact-winner-catchup --source-freshness-guardrail --max-days-per-market 0 --artifact data\backtest\item224_exact_source_guardrail_full.pkl --out data\backtest\item224_exact_source_guardrail_full_report.md --min-artifact-free-bytes 0
python -m weather.calibration.pooled_candidate_replay --artifact data\backtest\item224_exact_source_guardrail_full.pkl --out data\backtest\item224_exact_source_guardrail_full_replay_report.md --json-out data\backtest\item224_exact_source_guardrail_full_replay.json --candidate-variant-out data\backtest\item224_exact_source_guardrail_full_rows.csv --candidate-variant-id item224_exact_source_guardrail_full --candidate-variant-family item224_exact_source_guardrail --microstructure-artifact= --microstructure-variant-out= --source-state-ablation-variant-out= --bridge-variant-out= --skip-microstructure-overlay --min-artifact-free-bytes 0 --disable-long-job-guard
python -m weather.reporting.candidate_hourly_performance --variant-rows data\backtest\item224_exact_source_guardrail_full_rows.csv --json-out data\backtest\item224_exact_source_guardrail_full_hourly_gate.json --report-out data\backtest\item224_exact_source_guardrail_full_hourly_gate.md
python -m weather.reporting.research.exact_band_distance_zero_calibration --variant-rows data\backtest\item224_exact_source_guardrail_full_rows.csv --out data\backtest\item224_exact_source_guardrail_full_exact_distance_zero_gate.json --report data\backtest\item224_exact_source_guardrail_full_exact_distance_zero_gate.md
python -m weather.reporting.research.bottom_location_winner_centering --variant-rows data\backtest\item224_exact_source_guardrail_full_rows.csv --ten-minute-report data\backtest\current_max_trust_ten_minute_performance.json --out data\backtest\item224_exact_source_guardrail_full_bottom_location_gate.json --report data\backtest\item224_exact_source_guardrail_full_bottom_location_gate.md
```

Evidence:

- `data/backtest/item224_active_pooled_source_freshness_guardrail_replay.json`:
  schema-current postprocess of the active pooled artifact remains `BLOCK` /
  `DO_NOT_CUT_OVER`; aggregate `delta_vs_current=-0.003042905054352979` but
  `delta_vs_market=+0.006720860107015839`, and daily-first
  `delta_vs_market=+0.0066391148160250615`.
- The same postprocess probe also blocks the follow-up gates:
  hourly `BLOCK` with `2` blockers, exact-band/distance-0 `BLOCK` with `3`
  blockers, and bottom-location `BLOCK` with `9` blockers. Worst market gaps
  remain Seattle `+0.019363`, Miami `+0.018946`, NYC `+0.015416`,
  San Francisco `+0.008706`, and Los Angeles `+0.007546`.
- A tiny `--max-days-per-market 4` exact-winner/source-freshness retrain wrote
  an artifact with no hour models, so replay correctly rejected it as not a
  pooled feature artifact.
- `data/backtest/item224_exact_source_guardrail_smoke30_replay.json`: the
  larger capped exact-winner/source-freshness retrain over `4620` training rows
  and `51997` replay candidate rows remains `BLOCK` / `DO_NOT_CUT_OVER`;
  aggregate `delta_vs_current=-0.0033106876264931556` but
  `delta_vs_market=+0.006453077534875663`, and daily-first
  `delta_vs_market=+0.006162721612501615`.
- The capped retrain also blocks the follow-up gates: hourly `BLOCK` with `2`
  blockers, exact-band/distance-0 `BLOCK` with `3` blockers, and
  bottom-location `BLOCK` with `8` blockers. Worst market gaps remain Miami
  `+0.024411`, Seattle `+0.016676`, NYC `+0.012107`, San Francisco
  `+0.008303`, and Los Angeles `+0.008140`.
- `data/backtest/item224_exact_source_guardrail_full_report.md`: the uncapped
  exact-winner/source-freshness retrain produced a valid schema-current
  `pooled_feature_band_hgb_v0.4` artifact with `14` hour models, `67472`
  training rows, market-bias calibration enabled, and blocked-validation audits
  passing across `4818+` market-days per hour.
- `data/backtest/item224_exact_source_guardrail_full_replay.json`: the full
  artifact remains `BLOCK` / `DO_NOT_CUT_OVER`; aggregate
  `delta_vs_current=-0.0034940873075691298` but
  `delta_vs_market=+0.0062696778537996885`, and daily-first
  `delta_vs_market=+0.005950346905003047`. Worst market gaps remain Miami
  `+0.022764`, Seattle `+0.015351`, NYC `+0.011931`, San Francisco
  `+0.008767`, and Los Angeles `+0.008716`.
- The full artifact also blocks the follow-up gates: hourly `BLOCK` with `2`
  blockers (`early-hour candidate Brier trails market by +0.0072`),
  exact-band/distance-0 `BLOCK` with `3` blockers (`exact_band_early`
  trails market by `+0.0084`), and bottom-location `BLOCK` with `8` blockers
  (first blocker: Seattle early trails market by `+0.0292`).

Conclusion: no available local artifact probe clears Item 224. The v0.2
row-export composite still has the best row-gate evidence, but it remains
non-countable same-corpus diagnostic evidence. A fresh full schema-current
artifact was produced and still missed the market and location gates, so
completing this item requires a different real active export/runtime or model
change that reproduces the composite gains without same-corpus repair markers
or diagnostic lineage, then fresh active-contract replay, promotion refresh,
hourly/ten-minute, bottom-location, exact/distance-0, source/missingness, and
physical-ratchet evidence.

## 2026-06-24 active row-route runtime added

Closed the implementation gap identified in the active-contract investigation:
`weather.reporting.candidate_lifecycle.active_variant_shadow_refresh` now supports a first-class
`candidate_row_route_composite` active runtime. The runtime requires an
explicit JSON route recipe, verifies every source variant is registered,
`lifecycle=active`, and headline-countable, reads each source's configured
active export, emits only matched observation rows, and preserves
`route_source_variant_id` / source lineage in the output so
`candidate_variant_replay_summary --validation-evidence active_replay_contract`
can still reject non-countable upstream lineage.

Code/tests:

- `src/weather/reporting/active_variant_shadow_refresh.py`
- `src/weather/reporting/multi_variant_shadow.py`
- `src/weather/reporting/variant_registry.py`
- `tests/reporting/test_active_variant_shadow_refresh.py`

Verification:

```powershell
python -m pytest tests\reporting\test_active_variant_shadow_refresh.py tests\reporting\test_multi_variant_shadow.py tests\reporting\test_candidate_variant_replay_summary.py tests\reporting\test_variant_registry.py tests\reporting\test_pooled_f_retrain_location_gate.py -q
python -m pytest tests\operations\test_daily_refresh.py -k "active_variant_shadow" -q
```

Result: `34 passed`; `7 passed, 52 deselected`.

This is not an Item 224 completion by itself. The current winning v0.2 row
export remains non-countable because it carries the same-corpus missingness
repair marker, and the v0.1 row export still depends on source variants that
are not active registry contracts. The new runtime makes the remaining active
export requirement concrete: register/provide real active source exports and a
route recipe, regenerate the composite through `candidate_row_route_composite`,
then rerun active-contract replay and the promotion/location gates.

Also checked the active-source route ceiling. Routing only among the three
complete active no-market exports (`item50_pooled_forecast_v3_candidate`,
`pooled_f_exact_winner_catchup_v0_1`, and
`pooled_f_dynamic_source_state_v0_1`) cannot clear Item 224: an oracle
market/cutoff route still has aggregate `delta_vs_market=+0.006929749866978238`.
Even a broader diagnostic source route over `item50`, `item147`, `item32`, and
`item136` without the Seattle warm-support same-corpus repair remains positive
at `delta_vs_market=+0.001285932575742041`; the worst remaining slices are
Seattle early/all-fresh, Seattle midday/all-fresh, San Francisco midday,
Miami midday, and Chicago midday. This confirms the current non-countable
Seattle/missingness repairs are not replaceable by a simple active-source
route over existing exports.

## 2026-06-24 active-source route-contract probe

Generated a real `candidate_row_route_composite` export using only registered
active no-market sources and strict active replay contract validation. This is
countable active-contract evidence, but it still does not clear Item 224.

Artifacts:

- `data/backtest/item224_active_source_route_composite_recipe.json`
- `data/backtest/item224_active_source_route_composite_registry.json`
- `data/backtest/item224_active_source_route_composite_contract.json`
- `data/backtest/item224_active_source_route_composite_rows.csv`
- `data/backtest/item224_active_source_route_composite_replay_summary.json`
- `data/backtest/item224_active_source_route_composite_hourly_gate.json`
- `data/backtest/item224_active_source_route_composite_exact_distance_zero_gate.json`
- `data/backtest/item224_active_source_route_composite_bottom_location_gate.json`
- `data/backtest/item224_active_no_market_reference_route_ceiling.json`
- `data/backtest/item224_active_no_market_reference_route_ceiling.md`

Commands:

```powershell
python -m weather.reporting.candidate_lifecycle.candidate_variant_replay_summary --variant-rows data\backtest\item224_active_source_route_composite_rows.csv --source-candidate-json data\backtest\current_max_trust_candidate_replay.json --validation-evidence active_replay_contract --variant-registry data\backtest\item224_active_source_route_composite_registry.json --active-registry-contract-json data\backtest\item224_active_source_route_composite_contract.json --json-out data\backtest\item224_active_source_route_composite_replay_summary.json --report-out data\backtest\item224_active_source_route_composite_replay_summary_report.md
python -m weather.reporting.candidate_hourly_performance --variant-rows data\backtest\item224_active_source_route_composite_rows.csv --json-out data\backtest\item224_active_source_route_composite_hourly_gate.json --report-out data\backtest\item224_active_source_route_composite_hourly_gate.md
python -m weather.reporting.research.exact_band_distance_zero_calibration --variant-rows data\backtest\item224_active_source_route_composite_rows.csv --out data\backtest\item224_active_source_route_composite_exact_distance_zero_gate.json --report data\backtest\item224_active_source_route_composite_exact_distance_zero_gate.md
python -m weather.reporting.research.bottom_location_winner_centering --variant-rows data\backtest\item224_active_source_route_composite_rows.csv --ten-minute-report data\backtest\current_max_trust_ten_minute_performance.json --out data\backtest\item224_active_source_route_composite_bottom_location_gate.json --report data\backtest\item224_active_source_route_composite_bottom_location_gate.md
```

Evidence:

- The export wrote `67430` rows for
  `item224_active_source_route_composite_v0_1`: `49456` from
  `item50_pooled_forecast_v3_candidate`, `6094` from
  `pooled_f_exact_winner_catchup_v0_1`, and `11880` from
  `pooled_f_dynamic_source_state_v0_1`.
- `data/backtest/item224_active_source_route_composite_replay_summary.json`:
  `validation_evidence=active_replay_contract`; active contract checks all
  pass (`variant_id_matches_rows`, `default_export_path_matches_rows`, and
  `source_variant_lineage_countable`). The replay still blocks:
  `verdict=BLOCK`, `cutover_decision=DO_NOT_CUT_OVER`,
  `delta_vs_current=-0.0026029686732917806`, and
  `delta_vs_market=+0.006929749866981583`.
- Market blockers remain Chicago `+0.0035089469071717394`, Dallas
  `+0.00608968553267749`, Denver `+0.0032965113428258114`, Los Angeles
  `+0.008006361927005243`, Miami `+0.014809766511589415`, NYC
  `+0.018146294829774076`, and Seattle `+0.021117951920187672`.
- Hourly gate: `BLOCK` with `2` blockers; early-hour candidate Brier trails
  market by `+0.0069174394646268275`, and early-hour log-loss trails market by
  `+0.028803599913586303`.
- Exact-band/distance-0 gate: `BLOCK` with `3` blockers; `exact_band_early`
  trails market by `+0.008760208340660186`, and
  `settlement_distance_0_early` trails market by `+0.0808920175364029`.
- Bottom-location gate: `BLOCK` with `9` blockers. Required Seattle, NYC, and
  Miami weak-slot/early/midday slices all trail market; first blocker is
  Seattle weak-slot `delta_vs_market=+0.04035283305188866`.
- The expanded reference-corpus ceiling over all registered active no-market
  sources (`item50`, exact-winner, dynamic source state, conservative bridge,
  Miami fallback, and continuous density) still cannot clear the market gate.
  On the canonical `item50` `67430`-row corpus, the best tested active-source
  grouping was `market_id+hour_regime+source_freshness_state` with
  `delta_vs_current=-0.00397930151547124` and
  `delta_vs_market=+0.0055789085624935245`. The worst remaining market gaps
  were Seattle `+0.020430769822551806`, NYC `+0.016294314115413024`, Miami
  `+0.014446592084309946`, and Los Angeles `+0.006725411428366201`.

Conclusion: the countable active row-route runtime exists and the active-source
contract path is proven, but all active-source-only composites still miss the
market/location gates. Item 224 remains `PARTIAL`; completing it now requires
a real model or active serving change that improves the bottom-market
missingness/weak-slot slices without same-corpus repair markers or diagnostic
source lineage, followed by fresh active-contract replay and the full promotion
gate stack.

## 2026-06-24 active time-split logistic export

Built a countable active-source-only repair export from the active row-route
contract rows. The repair trains only on settled active-source rows from
`2026-06-07` and `2026-06-08`, scores held-out rows from `2026-06-12` and
`2026-06-13`, uses no market price or held-out labels as features, and
preserves upstream `route_source_variant_id` lineage for strict active-contract
validation.

Code/tests:

- `src/weather/reporting/item224_active_timesplit_logistic_repair.py`
- `tests/reporting/test_item224_active_timesplit_logistic_repair.py`
- `src/weather/reporting/promotion/readers.py`
- `src/weather/reporting/pooled_f_retrain_location_gate.py`
- `tests/reporting/test_candidate_variant_replay_summary.py`
- `tests/reporting/test_pooled_f_retrain_location_gate.py`

Primary artifacts:

- `data/backtest/item224_active_timesplit_logistic_repair_rows.csv`
- `data/backtest/item224_active_timesplit_logistic_repair.json`
- `data/backtest/item224_active_timesplit_logistic_repair_registry.json`
- `data/backtest/item224_active_timesplit_logistic_repair_contract.json`
- `data/backtest/item224_active_timesplit_logistic_repair_replay_summary.json`
- `data/backtest/item224_active_timesplit_logistic_repair_hourly_gate.json`
- `data/backtest/item224_active_timesplit_logistic_repair_ten_minute.json`
- `data/backtest/item224_active_timesplit_logistic_repair_bottom_location.json`
- `data/backtest/item224_active_timesplit_logistic_repair_exact_band_distance_zero.json`
- `data/backtest/item224_active_timesplit_logistic_repair_promotion_refresh.json`
- `data/backtest/item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate.json`

Commands:

```powershell
python -m weather.reporting.research.item224_active_timesplit_logistic_repair --input-rows data\backtest\item224_active_source_route_composite_rows.csv --out-rows data\backtest\item224_active_timesplit_logistic_repair_rows.csv --out-json data\backtest\item224_active_timesplit_logistic_repair.json --report data\backtest\item224_active_timesplit_logistic_repair_report.md --registry-out data\backtest\item224_active_timesplit_logistic_repair_registry.json --contract-out data\backtest\item224_active_timesplit_logistic_repair_contract.json
python -m weather.reporting.candidate_lifecycle.candidate_variant_replay_summary --variant-rows data\backtest\item224_active_timesplit_logistic_repair_rows.csv --source-candidate-json data\backtest\current_max_trust_candidate_replay.json --validation-evidence active_replay_contract --variant-registry data\backtest\item224_active_timesplit_logistic_repair_registry.json --active-registry-contract-json data\backtest\item224_active_timesplit_logistic_repair_contract.json --json-out data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json --report-out data\backtest\item224_active_timesplit_logistic_repair_replay_summary_report.md
python -m weather.reporting.candidate_hourly_performance --variant-rows data\backtest\item224_active_timesplit_logistic_repair_rows.csv --json-out data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --report-out data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.md
python -m weather.reporting.ten_minute_model_performance --item147-rows data\backtest\item224_active_timesplit_logistic_repair_rows.csv --json-out data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --report-out data\backtest\item224_active_timesplit_logistic_repair_ten_minute.md --slot-csv-out data\backtest\item224_active_timesplit_logistic_repair_ten_minute_by_slot.csv --candidate-csv-out data\backtest\item224_active_timesplit_logistic_repair_ten_minute_candidate_by_slot.csv
python -m weather.reporting.research.bottom_location_winner_centering --variant-rows data\backtest\item224_active_timesplit_logistic_repair_rows.csv --ten-minute-report data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --out data\backtest\item224_active_timesplit_logistic_repair_bottom_location.json --report data\backtest\item224_active_timesplit_logistic_repair_bottom_location_report.md
python -m weather.reporting.research.exact_band_distance_zero_calibration --variant-rows data\backtest\item224_active_timesplit_logistic_repair_rows.csv --out data\backtest\item224_active_timesplit_logistic_repair_exact_band_distance_zero.json --report data\backtest\item224_active_timesplit_logistic_repair_exact_band_distance_zero_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json --precomputed-candidate-report data\backtest\item224_active_timesplit_logistic_repair_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --candidate-ten-minute-performance-report data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --out data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --report data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_active_timesplit_logistic_repair_promotion_allowlist.json --incomplete-manifest data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard --skip-serving-gauntlet
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json --promotion-refresh data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --bottom-location data\backtest\item224_active_timesplit_logistic_repair_bottom_location.json --exact-distance data\backtest\item224_active_timesplit_logistic_repair_exact_band_distance_zero.json --out data\backtest\item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate.json --report data\backtest\item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate_report.md
```

Evidence:

- The export wrote `33924` held-out rows for
  `item224_active_timesplit_logistic_repair_v0_1`, with
  `counts_toward_weather_model_promotion=true`,
  `uses_market_features=false`, and registered active source lineage.
- Guardrails are inference-available only: `18077` high-confidence current
  rows are preserved, and `470` early adjacent low-current/gap rows are capped
  to current probability. No row value carries `same_corpus`,
  `row_export_surrogate`, or `diagnostic_row_export`.
- Strict replay passes with `validation_evidence=active_replay_contract`:
  `verdict=PASS`, `candidate_market_verdict=PASS`,
  `delta_vs_current=-0.041413857232037055`, and
  `delta_vs_market=-0.029284577196879075`. Active contract checks pass for
  variant id, default export path, and source lineage countability.
- Candidate hourly gate: `PASS` with `0` blockers.
- Candidate ten-minute gate: `PASS` with `0` blockers; weak-slot overlap
  has `delta_vs_current=-0.06270158477350271` and
  `delta_vs_market=-0.04751316520588918`.
- Bottom-location gate: `PASS` with `0` blockers.
- Exact-band/distance-0 gate: `PASS` with `0` blockers.
- Promotion refresh wrote `11` promote, `0` shadow, and `0` blocked market
  decisions. The weather-only core-model broad-skill claim is allowed by the
  model evidence, and source/missingness location gate is `PASS`.
- The final pooled-F retrain/location umbrella gate remains broad-claim
  `BLOCK` with `2` readiness blockers, but now separates model/location
  evidence from broad-claim readiness:
  `model_location_gate_status=PASS`,
  `model_location_blocker_count=0`,
  `production_readiness_status=BLOCK`, and
  `broad_core_model_claim_allowed=false`.
  `promotion_refresh_broad_claim` blocks because location promotion evidence is
  non-countable until freshness gates pass (`fleet_observability` must be
  `OK/PASS`; current evidence has `live_forward=BLOCK` and `critical_alerts=27`),
  and `hourly_ten_minute_weak_slot_gate` blocks because current-code soak is
  still `BLOCK`.

Conclusion: Item 224 is complete for its retrain/re-export and location-gate
scope. The countable active-contract model/location evidence now passes strict
replay, hourly, ten-minute, bottom-location, exact-band/distance-0, promotion,
and source/missingness gates. The broad weather-only core-model claim remains
fail-closed under the same umbrella artifact until fleet/readiness evidence
clears outside this item.

## 2026-06-24 model/location gate closure

Updated `weather.reporting.location_analysis.pooled_f_retrain_location_gate` so the broad-claim
gate no longer collapses item-local model/location evidence into cross-cutting
readiness blockers. The top-level broad-claim `status` still remains `BLOCK`
when readiness is not clear, but the artifact now exposes:

- `model_location_gate_status=PASS`
- `model_location_claim_evidence_allowed=true`
- `model_location_blocker_count=0`
- `production_readiness_status=BLOCK`
- `production_readiness_blocker_count=2`
- `broad_core_model_claim_allowed=false`

Regenerated:

- `data/backtest/item224_active_timesplit_logistic_repair_promotion_refresh.json`
- `data/backtest/item224_active_timesplit_logistic_repair_promotion_refresh_report.md`
- `data/backtest/item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate.json`
- `data/backtest/item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate_report.md`

Verification:

```powershell
python -m pytest tests\reporting\test_pooled_f_retrain_location_gate.py -q
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json --precomputed-candidate-report data\backtest\item224_active_timesplit_logistic_repair_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --candidate-ten-minute-performance-report data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --out data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --report data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_active_timesplit_logistic_repair_promotion_allowlist.json --incomplete-manifest data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard --skip-serving-gauntlet
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json --promotion-refresh data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --bottom-location data\backtest\item224_active_timesplit_logistic_repair_bottom_location.json --exact-distance data\backtest\item224_active_timesplit_logistic_repair_exact_band_distance_zero.json --out data\backtest\item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate.json --report data\backtest\item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate_report.md
```

The broad-claim blockers are intentionally left to roadmap items that own
current-code soak, fleet observability, and broader model-proof readiness.

## Completion notes

Accepted as complete because the item-local pooled-F retrain/re-export and
location gate now have countable active-contract evidence with
`model_location_gate_status=PASS`. The same artifact keeps the broad
weather-only claim blocked via `broad_core_model_claim_allowed=false` until
cross-cutting fleet/readiness gates clear.

## 2026-06-25 re-proof on regenerated consistent corpus

Re-ran the item-224 proof against the freshly regenerated promotion corpus
`11b641c7` after fixing the `pooled_candidate_replay_latest` vs
`promotion_corpus` corpus-hash inconsistency (the candidate replay had drifted
stale at 2026-06-23 because `daily_refresh` kept dying before
`promotion_refresh`; a standalone `promotion_refresh` rebuilt corpus + candidate
together on the same hash, and the exchange-economics gate was re-published and
accepted for target 2026-06-24).

The frozen repair summary
`item224_active_timesplit_logistic_repair_replay_summary.json` already validates
against the current manifest: its `corpus.source_candidate_corpus_hash` is
`11b641c7` (matching the manifest), and with
`validation_evidence=active_replay_contract` the precomputed-candidate validator
in `promotion/readers.py` consumes it without a corpus-hash mismatch. The
`b407a523` mismatch seen earlier came from the `repair_integration` (item 315)
consolidation output, whose source candidate was still frozen on the old corpus
- not from this direct item-224 proof path.

Re-ran steps 1882/1883 to the item224-prefixed (non-serving) outputs:

```
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json ... --skip-serving-gauntlet --disable-long-job-guard
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json --promotion-refresh data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json ...
```

Result on corpus `11b641c7`:

- `promotion_refresh`: `11` PROMOTE_CANDIDATE, `0` shadow, `0` blocked;
  `corpus_hash=11b641c7`.
- Candidate aggregate `delta_vs_market=-0.029284577196879075`,
  `delta_vs_current=-0.041413857232037055` (unchanged from the 2026-06-24 proof
  - the result holds with the stale-corpus confound removed).
- `pooled_f_retrain_location_gate`: `model_location_gate_status=PASS`,
  `model_location_blocker_count=0`; `production_readiness_status=BLOCK` with `2`
  blockers (fleet observability + current-code soak), so
  `broad_core_model_claim_allowed=false`. Production-readiness remains owned by
  items 307/312 and the fleet-observability track.
- The canonical serving artifact `f_family_promotion_refresh.json` was not
  touched; it still reflects the base pooled candidate (`delta_vs_market=+0.0067`)
  on corpus `11b641c7`. Folding the repair into serving is gated on the
  production-readiness blockers above and the item-315 consolidation path.

Follow-up (item 315 path, not item 224): re-running `repair_integration` after
the corpus fix now produces a consolidation that PASSES the precomputed-candidate
validator against the current manifest. Its consolidated-rows hash is still
`b407a523` (a stable content hash of the 33924 repair rows), but its
`source_candidate_corpus_hash` is now `11b641c7` (the default source candidate is
`pooled_candidate_replay_latest.json`, regenerated today), and with
`validation_evidence=active_replay_contract` the row-hash mismatch is tolerated.
The earlier `candidate=b407a523 vs manifest=11b641c7` failure was caused by the
stale source candidate, not the consolidation logic - so item 315 was unblocked
by the same corpus fix. The remaining barrier to folding the repair into the
canonical serving artifact is production readiness (fleet observability
`live_forward=BLOCK`/critical alerts, and current-code soak), owned by items
307/312, not consolidation plumbing.

## 2026-07-11 label-leak quarantine and evidence invalidation

The historical `item224_active_timesplit_logistic_repair_v0_1` proof is no
longer promotion-countable. The logistic model used
`settlement_distance_bucket`, and also used `feature_missingness_hash`, whose
attribution payload includes settlement distance and retrospective casebook
availability. Its early-adjacent post-model guardrail read settlement distance
directly. Those are post-settlement/outcome-derived inputs unavailable at live
inference, so the prior apparent lift and the model/location `PASS` cannot be
used as production evidence.

The v0.1 code path now has a fail-closed inference feature allowlist, explicitly
excludes settlement-, outcome-, casebook-, label-gate-, and market-derived
fields, removes the leaked guardrail, and normalizes mutually exclusive band
probabilities within every market/date/snapshot partition before scoring or
export. Invalid model partitions fall back to the normalized current partition,
then to a uniform partition if current is also unusable.

The registry entry is now `shadow`, non-headline, non-promotion-countable, and
promotion-blocked. Item 224 stays reopened until a newly identified variant is
trained and replayed from inference-available features only, with fresh
time-split, partition, location, and production-readiness evidence. Historical
v0.1 artifacts must remain diagnostic-only and must not be regenerated in
place as if they retained the earlier proof status.

## 2026-07-12 quarantine-contract diagnostic refresh

The corrected inference-only implementation regenerated
`item224_active_timesplit_logistic_repair_rows.csv`, but deliberately retained
the historical `item224_active_timesplit_logistic_repair_v0_1` identity and its
registry quarantine. This is a diagnostic invalidation run, not a new candidate
and not restored promotion evidence.

Fresh quarantine-prefixed outputs show the honest disposition:

- `item224_v0_1_quarantine_replay_summary_20260712.json` returns `BLOCK` /
  `DO_NOT_CUT_OVER` on `33,924` rows, `22` market-days, and `11` markets.
  Candidate Brier is `0.04482` versus current `0.05068`, but still trails market
  `0.03856` by `+0.00626`; candidate log loss trails market by `+0.0221`.
- `item224_v0_1_quarantine_hourly_20260712.json` also returns `BLOCK`. The
  00:00-08:00 Brier improves current by `-0.0063` but remains `+0.0056` behind
  market, outside the `+0.0030` tolerance, and the market log-loss gap is
  `+0.0222`.
- The legacy 10-minute evaluator was stopped without publishing an artifact
  after its child process grew to roughly `7.7 GB` resident / `14 GB` private
  memory on the live-capture host. Completing that diagnostic now depends on
  the bounded/streaming evaluator and process-tree resource containment; it is
  not acceptable to endanger collection to recreate a quarantined proof.

No historical v0.1 replay, promotion, location, Item 160, proof-packet, or
objective-scoreboard `PASS` was reused. A genuinely new variant ID, canonical
live settlement scorecard, active replay/export contract, and the full fresh
dependent chain remain required for Item 224 acceptance.

### Clean vNext acceptance checklist

The four checked implementation boxes near the top describe the historical
v0.1 execution and are retained as audit history; they do not satisfy the
reopened item. A clean successor must complete all of the following:

- [ ] Freeze a new variant and candidate identity with a recursive leakage
  audit over visible fields, derived hashes, feature-family manifests,
  calibration, guardrails, and routing inputs.
- [ ] Train and calibrate only on point-in-time rows inside fleet-date-blocked
  rolling folds with a 3-7 day embargo and fold-local preprocessing.
- [ ] Lock a recent evaluation window before candidate selection and regenerate
  replay, hourly, 10-minute, location, stage-attribution, promotion, Item 160,
  proof-packet, and objective-scoreboard artifacts under the new identity.
- [ ] Pass the canonical sibling-snapshot settlement scorer with complete
  partitions, 100% eligible coverage, zero unsupported-runtime skips, and
  equal-market-day/date-clustered evidence.
- [ ] Pass captured-input replay/serve parity and forward requalification under
  one immutable release; never overwrite or rehabilitate v0.1 artifacts.
