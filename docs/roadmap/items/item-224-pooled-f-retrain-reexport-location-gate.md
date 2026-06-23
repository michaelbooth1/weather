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
