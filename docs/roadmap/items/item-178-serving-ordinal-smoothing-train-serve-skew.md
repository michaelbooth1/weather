# 178. Serving-Time Ordinal Smoothing Train/Serve Skew [PARTIAL 2026-06-22 - GATE REFRESHED, VALIDATION BLOCKED]

Goal: eliminate the train/serve skew where serving de-sharpens the feature-model
distribution with an ordinal-smoothing layer that the per-hour temperature/blend
tuning never saw.

Source: `docs/roadmap/core-model-audit-2026-06-20.md` finding H1. Serving calls
`ordinal_smooth_distribution(sigma=0.75, blend_weight=0.50)` on the HGB output
([model_distribution.py:472](../../../src/weather/model/model_distribution.py#L472))
before the climatology blend, but `fit_temperature_blend_grid`
([feature_model.py:1237](../../../src/weather/calibration/feature_model.py#L1237),
[feature_probability_calibration.py:64](../../../src/weather/calibration/feature_probability_calibration.py#L64))
tunes the per-hour `temperature` and `blend_weight` on the **raw** HGB output.
`ordinal_smooth_distribution` appears only in serving and one unit test, never in
training.

Why this matters: the served distribution is de-sharpened twice (a fixed 50%
ordinal blend, then the tuned temperature/prior weight), and the tuning that
chose those values was blind to the first step. The net effect is a distribution
flatter than anything validated â€” the exact symptom items 168/169 measured
(predawn winner band `24.2%` model vs `34.6%` market; probability spread over
more bands). The smoothing constants are also global, applied identically across
every hour and regime, including the predawn slots already too diffuse.

## Design

1. Choose a policy: either fold the ordinal smoothing into the LOO objective
   (tune `sigma` and its blend weight per hour, allowing 0) or remove it and let
   the tuned temperature own all sharpening.
2. If folded: apply the exact serving transform inside the tuning grid before
   scoring, and export the chosen smoothing parameters in the per-hour bundle so
   serving reads them instead of the hard-coded `0.75`/`0.50`.
3. Add a serving-parity test: for a fixed feature vector, the distribution scored
   during tuning equals the distribution served.
4. Re-tune and re-export artifacts; gate the change on weak-slot and per-market
   replay so predawn slices improve rather than only the aggregate.

- [x] Decide fold-vs-remove: remove the serving-only smoother for current
  artifacts and require any future smoother to be tuned/exported by the
  validation objective before serving can apply it.
- [x] Make the serving smoothing parameters artifact-driven, not literals.
- [x] Add the train/serve parity test for the feature-model distribution.
- [ ] Retrain, re-export, and validate predawn winner probability movement
  without regressing ramp/late-day tolerances (items 169/170).

Acceptance: the served feature-model distribution is byte-equivalent to the
distribution scored during tuning (parity test passes), and a retrain raises
predawn winner probability toward market with no ramp/late-day regression.

Related: items 169, 170, 182; `[[model-audit-2026-06-09]]`.

## 2026-06-21 implementation update

Removed the unvalidated serving-only ordinal smoothing from the active feature
path. Serving now reads `ordinal_smoothing` from the active feature artifact and
defaults to disabled when the field is absent, which is the correct behavior for
all existing artifacts because their LOO temperature/blend tuning scored the raw
temperature-scaled HGB/LR distribution.

New artifact exports explicitly include:

```json
"ordinal_smoothing": {
  "enabled": false,
  "source": "disabled_until_tuned_in_validation_objective"
}
```

Future artifacts can re-enable ordinal smoothing only by exporting tuned
`sigma` and `blend_weight` values under `ordinal_smoothing`; serving no longer
has hard-coded `sigma=0.75` / `blend_weight=0.50` literals.

Tests now cover:

- HGB serving output equals `temperature_scale_distribution(raw, artifact_temp)`
  when smoothing is absent.
- Existing artifacts default to smoothing disabled.
- Explicit artifact smoothing config is honored.
- Distribution-stage snapshots record the unsmoothed feature distribution by
  default and apply smoothing only when the artifact config enables it.

The full retrain/replay step remains open: the current code removes the skew,
but item completion still requires regenerated artifacts and weak-slot,
per-market, ramp, and late-day validation.

Verification:

- `python -m pytest tests\model\test_feature_model_calibration.py tests\model\test_estimate_distribution.py tests\calibration\test_feature_probability_calibration.py tests\calibration\test_intraday_calibration.py -q`

## 2026-06-22 Retrain Attempt

The active pooled F-band retrain command from `nightly_retrain --dry-run` was:

```powershell
python -m weather.calibration.pooled_feature_model --family-unit F --objective band --holdout-year 2025 --artifact artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl --out data/backtest/f_family_pooled_band_model_v0_3_report.md
```

It did not complete within a 15-minute interactive command budget and was
stopped. `artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl` and
`data/backtest/f_family_pooled_band_model_v0_3_report.md` kept their prior
timestamps, so this attempt produced no valid re-export evidence. Completion
still requires running the full retrain under the long-job guard or another
controlled longer window, then rerunning promotion/weak-slot validation against
the regenerated artifact.

## 2026-06-22 Guarded Retrain

The guarded nightly retrain slice completed the pooled feature export,
artifact registry refresh, and promotion refresh:

```powershell
python -m weather.operations.nightly_retrain run --no-fail-on-daily-learning-blocker --skip-settled-day-freshness --skip-daily-learning --skip-family-secondary --skip-shadow-ab-monitor --step-timeout-seconds 7200
```

`pooled_feature_model_band` passed in `3652.533s`, writing
`artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl` and
`data/backtest/f_family_pooled_band_model_v0_3_report.md` at
`2026-06-22T02:53:22Z`. The artifact uses schema `pooled_feature_band_hgb_v0.3`,
feature schema `toronto_feature_store_v1.13`, objective
`binary_market_band_brier_source_reliability`, and still has no serving-only
ordinal smoothing term; per-hour artifact temperatures include `07:00=0.55`,
`08:00=0.55`, `09:00=0.65`, and `10:00=0.75`.

The retrain does not close this item yet. The promotion refresh completed but
returned `blocked`: candidate replay Brier is `0.0395` versus current `0.0409`
and market `0.0308` (`delta_vs_current=-0.0014`, `delta_vs_market=+0.0087`),
with `austin`, `denver`, and `houston` promote-ready but eight F markets still
blocked. The current-serving hourly gate remains blocked because early-hour
model Brier trails market by `0.0159 > 0.0030`; the 10-minute current-serving
gate also remains blocked by `0.0130 > 0.0030`.

## 2026-06-22 Active-Candidate Gate Evidence

The initial promotion refresh did not pass active-candidate hourly evidence
into readiness, and its candidate 10-minute evidence was for the stale
`item147_time_split_alpha` variant. I regenerated both candidate-performance
reports from the active promotion candidate export,
`data/backtest/item82_miami_fallback_shadow_variants.csv`, whose variant id is
`pooled_f_candidate_miami_current_fallback_v0_1`:

```powershell
python -m weather.reporting.candidate_hourly_performance --variant-rows data\backtest\item82_miami_fallback_shadow_variants.csv --json-out data\backtest\pooled_f_candidate_miami_current_fallback_hourly_candidate_performance.json --report-out data\backtest\pooled_f_candidate_miami_current_fallback_hourly_candidate_performance_report.md
python -m weather.reporting.ten_minute_model_performance --item147-rows data\backtest\item82_miami_fallback_shadow_variants.csv --json-out data\backtest\pooled_f_candidate_miami_current_fallback_ten_minute_performance.json --report-out data\backtest\pooled_f_candidate_miami_current_fallback_ten_minute_performance_report.md --slot-csv-out data\backtest\pooled_f_candidate_miami_current_fallback_ten_minute_by_slot.csv --candidate-csv-out data\backtest\pooled_f_candidate_miami_current_fallback_ten_minute_candidate_by_slot.csv
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\pooled_candidate_replay_latest.json --precomputed-candidate-report data\backtest\pooled_candidate_replay_latest_report.md --candidate-hourly-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_ten_minute_performance.json --skip-serving-gauntlet
```

The bounded promotion refresh wrote
`data/backtest/f_family_promotion_refresh.json` at
`2026-06-22T04:09:23Z`; it used the precomputed guarded-retrain candidate replay
and kept the same `3 promote / 8 blocked` market disposition. After the
source-family inventory preflight fix, I reran the bounded promotion refresh at
`2026-06-22T04:14:28Z`; `source_family_preflight` is now `PASS` and no longer
appears as a readiness blocker. The candidate evidence now matches the active
candidate id, but both mitigations are still `NOT_APPLIED` because the candidate
gates are `BLOCK`:

- Candidate hourly gate: `BLOCK`; early-hour candidate Brier trails market by
  `0.0090 > 0.0030`, with log-loss trailing by `0.0312 > 0.0100`.
- Candidate 10-minute gate: `BLOCK`; weak-slot candidate Brier trails market by
  `0.0181 > 0.0030`, with log-loss trailing by `0.0529 > 0.0100`.
- The candidate does improve weak-slot Brier versus current by `-0.0023`, but
  that is not enough for promotion because the market-relative gate still fails.

Remaining unblock: build a daily-first predawn/weak-slot remediation that
improves the active candidate's market-relative early-hour and 10-minute
weak-slot Brier/log-loss without regressing ramp/late-day tolerances, then rerun
the same candidate-hourly, candidate-10-minute, and promotion-readiness gates.

## 2026-06-22 Predawn Weak-Slot Repair Probe

I added an exportable no-market predawn repair probe that fits weak-slot
logistic winner-centering on the train split, blends it with the active
candidate, normalizes each snapshot partition, and leaves non-weak-slot
probabilities at current-serving probabilities. The repaired rows are exported
under a distinct variant id,
`pooled_f_candidate_miami_current_fallback_predawn_repair_v0_1`, so this is
honest candidate evidence rather than pretending the active replay artifact
already contains the repaired policy.

The tuned probe used:

```powershell
python -m weather.reporting.research.predawn_weak_slot_repair --candidate-rows data\backtest\item82_miami_fallback_shadow_variants.csv --ten-minute-report data\backtest\ten_minute_model_performance.json --calibrator-blend 0.30 --calibrator-extrapolation 2.0 --calibrator-power 3.0 --output-variant-id pooled_f_candidate_miami_current_fallback_predawn_repair_v0_1 --candidate-rows-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv --json-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_weak_slot_repair.json --report-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_weak_slot_repair_report.md
python -m weather.reporting.candidate_hourly_performance --variant-rows data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv --json-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_hourly_candidate_performance.json --report-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_hourly_candidate_performance_report.md
python -m weather.reporting.ten_minute_model_performance --item147-rows data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv --json-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_performance.json --report-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_performance_report.md --slot-csv-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_by_slot.csv --candidate-csv-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_candidate_by_slot.csv
```

The repair validation now passes. On all weak slots, the repaired candidate
scores Brier `0.0511` versus current `0.0805` and market `0.0601`
(`delta_vs_current=-0.0294`, `delta_vs_market=-0.0090`); log-loss also clears
market (`delta_vs_market=-0.0055`). On the held-out eval split, it remains
positive versus both current and market (`delta_vs_current=-0.0142`,
`delta_vs_market=-0.0035`, log-loss `delta_vs_market=-0.0028`) while shrinking
effective-band spread versus current by `-0.0660`.

The formal candidate 10-minute gate now passes for the repaired rows:
`candidate_ten_minute_gate=PASS`, with weak-slot winner probability `47.3%`
versus current `26.1%` and market `35.1%`.

The broader hourly candidate gate is still blocked, but the residual is smaller
than the active candidate's original blocker. The repaired 00:00-08:00 slice has
candidate Brier `0.0437` versus current `0.0479` and market `0.0389`;
`delta_vs_market=+0.0048` still exceeds the `+0.0030` tolerance, and log-loss
`delta_vs_market=+0.0252` still exceeds the `+0.0100` tolerance.

## 2026-06-22 Repaired Variant Promotion-Refresh Wiring

I added a replay-shaped candidate summary adapter for repaired variant row
exports, registered schema `candidate_variant_replay_summary_v0.1`, and used it
to pass the repaired predawn variant into promotion refresh without relabeling
the old active replay artifact:

```powershell
python -m weather.reporting.candidate_lifecycle.candidate_variant_replay_summary --variant-rows data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv --source-candidate-json data\backtest\pooled_candidate_replay_latest.json --json-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary.json --report-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary.json --precomputed-candidate-report data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary_report.md --candidate-hourly-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_performance.json --skip-serving-gauntlet --disable-long-job-guard --out data\backtest\f_family_promotion_refresh_predawn_repair.json --report data\backtest\f_family_promotion_refresh_predawn_repair_report.md --incomplete-manifest data\backtest\f_family_promotion_refresh_predawn_repair_incomplete.json
```

The adapter intentionally marks this as `row_export_surrogate` validation, so it
is promotion-refresh-compatible evidence but not active replay/export contract
evidence. The repaired summary wrote
`data/backtest/pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary.json`
and scored aggregate Brier `0.0403` versus current `0.0412` and market `0.0310`
(`delta_vs_current=-0.0009`, `delta_vs_market=+0.0092`). It remains `BLOCK /
DO_NOT_CUT_OVER` because it trails market and is not active replay contract
evidence.

The follow-up repaired promotion refresh wrote
`data/backtest/f_family_promotion_refresh_predawn_repair.json` and confirmed the
key unblock: `10-minute gate mitigation = APPLIED` because the repaired replay
summary, candidate hourly report, and candidate 10-minute report all use variant
id `pooled_f_candidate_miami_current_fallback_predawn_repair_v0_1`. The
candidate 10-minute gate is `PASS`, with weak-slot Brier `0.0511` versus current
`0.0805` and market `0.0601`.

Promotion readiness is still `OPEN` with `0 promote / 0 shadow / 11 blocked`.
Remaining blockers are:

- Aggregate market-relative skill: repaired candidate still trails market by
  `+0.0092` Brier.
- Blocked validation: the summary is row-export surrogate evidence, not an
  active replay/export contract rerun.
- Per-market blocks: all 11 F markets are blocked in the repaired refresh.
- Candidate hourly gate: still `BLOCK`; repaired early-hour Brier trails market
  by `+0.0048 > +0.0030`, and log-loss trails by `+0.0252 > +0.0100`.
- Operational gates outside this item: live-forward SLO is `BLOCK` and tape

Remaining unblock: promote the repaired policy from probe CSV into the active
replay/export contract, broaden the repair only if it clears the full
00:00-08:00 hourly gate without ramp/late-day/lock-in regression, and keep items
146/157 moving so operational readiness no longer masks model-readiness
evidence.

## 2026-06-22 Serving Ordinal Smoothing Gate

Added `weather.reporting.serving_gates.serving_ordinal_smoothing_gate` with schema
`serving_ordinal_smoothing_gate_v0.1`.

Artifacts:

- `data/backtest/serving_ordinal_smoothing_gate.json`
- `data/backtest/serving_ordinal_smoothing_gate_report.md`

Command:

`python -m weather.reporting.serving_gates.serving_ordinal_smoothing_gate --out data\backtest\serving_ordinal_smoothing_gate.json --report data\backtest\serving_ordinal_smoothing_gate_report.md`

Result: **BLOCK** with 3 remaining validation blockers, but the original
ordinal smoothing train/serve skew is now explicitly separated and marked fixed.

Passing evidence:

- Active artifact has `0` enabled ordinal smoothing configs, so serving has no
  extra smoothing layer that the validation objective did not see.
- Predawn repair and candidate 10-minute weak-slot gate pass:
  `delta_vs_current=-0.0293`, `delta_vs_market=-0.0089`.
- Ramp, late-day, and lock-in guardrails pass for the scoped predawn repair.

Remaining blockers:

- Candidate hourly early gate is still `BLOCK`; early-hour candidate Brier
  trails market by `+0.0048 > +0.0030`.
- Active replay/export contract is still `BLOCK`, with cutover
  `DO_NOT_CUT_OVER`; the repaired evidence is a row-export surrogate, not an
  active artifact replay.
- Broad retrain/location gate is still `BLOCK` because the active artifact uses
  `toronto_feature_store_v1.13` while runtime is `toronto_feature_store_v1.14`.

## 2026-06-22 serving ordinal gate refresh

Regenerated the serving ordinal smoothing gate after the upstream pooled-F
retrain/location gate refresh:

- `data/backtest/serving_ordinal_smoothing_gate.json`
- `data/backtest/serving_ordinal_smoothing_gate_report.md`

The refreshed gate remains `BLOCK` with `3` validation blockers, while the
original train/serve skew fix remains explicitly passing:

- `artifact_smoothing_policy`: `PASS`; the active artifact has `0` enabled
  serving-only ordinal smoothing configs, so serving is not applying an
  unvalidated extra smoother.
- `predawn_weak_slot_repair`: `PASS`; the repaired candidate 10-minute
  weak-slot gate still passes with weak-slot Brier deltas
  `delta_vs_current=-0.0293` and `delta_vs_market=-0.0089`.
- `ramp_late_guardrails`: `PASS`; ramp, late-day, and lock-in guardrails remain
  clear for the scoped predawn repair.

Remaining blockers:

- `candidate_hourly_early_gate`: early-hour candidate Brier still trails market
  by `+0.0048 > +0.0030`.
- `active_replay_contract`: active replay/export contract remains `BLOCK` with
  cutover `DO_NOT_CUT_OVER`; the repaired rows are still surrogate row-export
  evidence.
- `broad_retrain_location_gate`: pooled-F retrain/location gate remains
  blocked because the active artifact is stamped with
  `toronto_feature_store_v1.13` while runtime uses
  `toronto_feature_store_v1.14`.

This keeps item 178 partial: the serving-only ordinal smoothing skew is fixed
and guarded, but acceptance still requires a schema-current active replay/export
contract and hourly early gate clearance.

## 2026-06-22 proof packet mapping

Proof-packet blocker: `weather_only_model_proof_packet.gates.served_distribution_contract`.
Serving parity evidence for this item must flow through the packet served-
distribution contract field before it can count toward weather-only readiness.
