# 233. Validate-What-You-Serve Early-Hour Calibration Head [PARTIAL 2026-06-22 - CONTRACT REFRESHED, HEAD TRAINING BLOCKED]

Goal: replace isolated early-hour postprocessors with a calibration head that
is trained and validated on the final served distribution.

Source: `docs/roadmap/audits/early-hour-model-performance-audit-2026-06-22.md`.
The 90-day roadmap calls for moving from postprocessor repairs to a unified
validate-what-you-serve calibration head over the final served distribution,
with continuous-density and exact-band modeling to reduce boundary errors.

Why this matters: many early-hour failures come from interactions among feature
model output, calibration, forecast anchoring, current-high trust, and serving
postprocessing. Validating each component separately can miss the distribution
that users and trading systems actually receive.

## Design

1. Define the final served distribution as the training/validation target for
   calibration, including all production transforms that are allowed for the
   no-market model lane.
2. Train the calibration head under blocked daily-first validation with
   early-hour, weak-slot, exact-band, settlement-distance, ramp, late, and
   per-market slices.
3. Preserve lane separation: market-informed/CLOB transforms remain quote-risk
   overlays unless separately validated as no-market features.
4. Add a serving-parity proof that the distribution scored in validation is the
   distribution emitted by serving for the same captured inputs.
5. Keep older postprocessors as disabled or diagnostic-only unless absorbed
   into the validated head.

- [x] Specify the served-distribution calibration contract and schema.
- [ ] Add a replay harness that scores the final served distribution under
  blocked daily-first validation.
- [ ] Train or prototype an early-hour calibration head with exact-band and
  settlement-distance diagnostics.
- [x] Add train/serve parity reporting prerequisites for the final distribution.

## Progress 2026-06-22

Added `weather.reporting.served_distribution_calibration_contract` with schema
`served_distribution_calibration_contract_v0.1`.

Artifacts:

- `data/backtest/served_distribution_calibration_contract.json`
- `data/backtest/served_distribution_calibration_contract_report.md`

Command:

`python -m weather.reporting.served_distribution_calibration_contract --out data\backtest\served_distribution_calibration_contract.json --report data\backtest\served_distribution_calibration_contract_report.md`

Result: **BLOCK** with 5 blockers. The contract is now explicit and
fail-closed, but no served-distribution calibration head is approved.

Passing evidence:

- Contract schema is specified for the `weather_only_core_model` lane with
  validation target `final_served_distribution`.
- Required validation mode is `active_replay_contract`; row-export probes are
  diagnostic-only until absorbed into a served artifact.
- Serving ordinal-smoothing train/serve skew is fixed by the item 178 gate.
- Weak-slot 10-minute gate passes for the repaired no-market row export
  (`delta_vs_current=-0.0293`, `delta_vs_market=-0.0089`).
- Market-informed overlays remain outside the weather-only core lane.

Current blockers:

- Repaired evidence is `row_export_surrogate`, replay verdict is `BLOCK`, and
  cutover is `DO_NOT_CUT_OVER`; it is not active replay-contract evidence.
- Candidate hourly early gate is still `BLOCK`; early-hour Brier trails market
  by `+0.0048 > +0.0030`.
- Exact-band early gate is still `BLOCK`; exact-band early Brier trails market
  by `+0.0047 > +0.0030`.
- Bottom-location gate is still `BLOCK`; first blocker is Seattle weak-slot
  current regression `+0.0307`.
- Broad retrain/location gate is still `BLOCK` because the active artifact uses
  `toronto_feature_store_v1.13` while runtime is `toronto_feature_store_v1.14`.

Remaining unblock: train or prototype the calibration head as part of the active
served artifact, rerun active replay-contract validation, and clear the hourly,
exact/distance, bottom-location, and broad-claim gates on the same corpus.

Acceptance: the validated distribution is byte-equivalent to the served
distribution for captured inputs, early-hour and weak-slot gates pass under
daily-first validation, exact-band and settlement-distance-0 gaps improve, and
market-informed overlays remain classified outside the no-market model lane
unless explicitly validated.

Related: items 35, 48, 69, 160, 177, 178, 227, 228, 230.

## 2026-06-22 served-distribution contract refresh

Regenerated the served-distribution calibration contract after refreshing the
serving ordinal, pooled-F retrain/location, bottom-location, and exact-band
gates:

- `data/backtest/served_distribution_calibration_contract.json`
- `data/backtest/served_distribution_calibration_contract_report.md`

The refreshed contract remains `BLOCK` with `5` blockers. Passing evidence is
unchanged but now current:

- `contract_schema`: the weather-only core-model contract is specified with
  validation target `final_served_distribution` and required validation mode
  `active_replay_contract`.
- `serving_parity_prerequisite`: item 178 confirms the serving ordinal-smoothing
  train/serve skew is fixed.
- `weak_slot_ten_minute_gate`: repaired weak-slot 10-minute evidence still
  passes with `delta_vs_market=-0.0089`.
- `lane_separation`: market-informed overlays remain outside the weather-only
  core lane.

Current blockers:

- `active_replay_contract`: the available repaired evidence is still
  `row_export_surrogate`, replay verdict is `BLOCK`, and cutover is
  `DO_NOT_CUT_OVER`.
- `early_hour_hourly_gate`: early-hour candidate Brier trails market by
  `+0.0048 > +0.0030`.
- `exact_band_distance_zero_gate`: exact-band early Brier trails market by
  `+0.0047 > +0.0030`.
- `bottom_location_gate`: bottom-location winner-centering remains blocked by
  current Brier regression `+0.0307`.
- `broad_claim_gate`: pooled-F retrain/location gate remains blocked because
  the active artifact uses `toronto_feature_store_v1.13` while runtime uses
  `toronto_feature_store_v1.14`.

No calibration head was trained or approved here. The item stays partial with
the validate-what-you-serve contract refreshed and fail-closed until active
served-artifact evidence clears the same gate stack.

## 2026-06-22 proof packet mapping

Proof-packet blocker: `weather_only_model_proof_packet.gates.served_distribution_contract`.
Calibration-head acceptance must clear the packet served-distribution contract;
row-export probes remain diagnostic-only until absorbed into that field.
