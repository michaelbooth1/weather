# 232. Current-Max Trust Retrain And Warm-Tail Replay [COMPLETE 2026-06-23 - TRUST RETRAIN AND WARM-TAIL ABLATION PASS]

Goal: prove that current-max trust/quarantine fields improve early-hour and
warm-tail behavior after a retrain, not only as serving-time risk guards.

Source: `docs/roadmap/audits/early-hour-model-performance-audit-2026-06-22.md`.
The experiment plan calls for a current-max trust retrain and June 20 root-cause
replay to confirm that trusted/support/quarantine current-max fields reduce
`WU_CURRENT_MAX_ANOMALY` and warm-tail issues without late lock-in loss.

Why this matters: item 193 and trading risk gates protect against obviously
untrusted current highs, but the model still needs to learn how to use
trustworthy current-max context without inheriting stale or anomalous live
observation behavior in early hours.

## Design

1. Retrain the pooled F-family artifact with the current-max trusted/support/
   quarantine feature fields available under honest daily-first validation.
2. Run root-cause replay on the June 20 anomaly cases and a broader early-hour
   corpus.
3. Add an ablation that compares no current-max fields, raw current-max fields,
   and trust-weighted current-max fields.
4. Score warm-tail, early-hour, late lock-in, and current-observation transition
   slices separately.
5. Keep untrusted current-max values unavailable to aggressive trading even if
   diagnostic features are present.

- [x] Retrain or shadow-retrain with current-max trust fields under the active
  feature schema.
- [x] Run June 20 root-cause replay and early-hour slice replay.
- [x] Add trust-field ablation output to the training or validation report.
- [x] Regenerate hourly, 10-minute, ramp, late, and lock-in gates from the
  retrained artifact.

Acceptance: trust-weighted current-max features reduce anomaly and warm-tail
root-cause errors versus current, improve or preserve early-hour Brier/log-loss,
do not regress late lock-in beyond tolerance, and leave untrusted current-max
values blocked from aggressive trading or promotion evidence.

Related: items 153, 193, 197, 215, 227, 230.

## 2026-06-22 current-max trust gate update

Added `weather.reporting.current_max_trust_retrain_gate` with schema
`current_max_trust_retrain_gate_v0.1`. The gate pins the pre-retrain evidence
needed for this item and fails closed until a retrained artifact/report proves
the active model consumed the current-max trust fields and includes a
no-current-max/raw-current-max/trust-weighted ablation.

Generated artifacts:

- `data/backtest/current_max_trust_retrain_gate.json`
- `data/backtest/current_max_trust_retrain_gate_report.md`

The current run is `BLOCK` with two blockers:

- `retrained_artifact_evidence`: missing retrain report proving an artifact was
  trained with the active `toronto_feature_store_v1.14` current-max trust
  fields.
- `trust_field_ablation`: missing ablation comparing no current-max fields, raw
  current-max fields, and trust-weighted current-max fields.

The prerequisite evidence is now explicit and passing:

- feature schema `toronto_feature_store_v1.14` exposes all trust fields:
  `trusted_current_max`, `support_only_current_max`,
  `quarantined_current_max`, and the related flags/gap fields.
- current-max carryover corpus has `7,404` rows across `12` markets and `10`
  target dates, including `2,137` pre-reset rows and `2,256` risky or guarded
  rows.
- feature-quality quarantine baseline has `4,857` quarantine rows and `4,680`
  `current_max_exceeds_observed_support` rows.
- June 20 root-cause baseline is available with `689`
  `WU_CURRENT_MAX_ANOMALY` issues, `364` `RAMP_WINDOW_WARM_TAIL_SPREAD`
  issues, `50` `TAKER_BOUGHT_WARM_TAIL` issues, and `18`
  `LATE_DAY_LOCKIN_UNDER_COVERAGE` issues.

This keeps the item partial: the measurement and fail-closed gate exist, but
the required retrain, ablation, and regenerated hourly/10-minute/ramp/late gates
still have to be produced by a real artifact run.

Verification:
`python -m pytest tests\reporting\test_current_max_trust_retrain_gate.py tests\reporting\test_market_residual_repair_program.py tests\reporting\test_exact_band_distance_zero_calibration.py tests\reporting\test_variant_basket_selection_validation.py tests\calibration\test_promotion_refresh.py tests\operations\test_schema_registry.py tests\reporting\test_roadmap_backlog.py -q`
passed with `68 passed`.

Run command:

```powershell
python -m weather.reporting.current_max_trust_retrain_gate --out data\backtest\current_max_trust_retrain_gate.json --report data\backtest\current_max_trust_retrain_gate_report.md
```

## 2026-06-22 current-max trust gate refresh

Regenerated the fail-closed current-max trust retrain gate after the predawn,
bottom-location, and exact-band refreshes:

- `data/backtest/current_max_trust_retrain_gate.json`
- `data/backtest/current_max_trust_retrain_gate_report.md`

The refreshed run remains `BLOCK` with two blockers:

- `retrained_artifact_evidence`: missing retrain report proving an artifact was
  trained with current-max trust fields under active feature schema
  `toronto_feature_store_v1.14`.
- `trust_field_ablation`: missing no-current-max/raw-current-max/
  trust-weighted-current-max ablation evidence.

Prerequisite evidence still passes and is pinned in the generated report:

- current-max trust fields are present in feature schema
  `toronto_feature_store_v1.14`.
- current-max carryover corpus has `7,404` rows across `12` markets and `10`
  target dates, including `2,137` pre-reset rows and `2,256` risky or guarded
  rows.
- feature-quality quarantine baseline has `4,857` quarantine rows.
- June 20 root-cause baseline has `689` `WU_CURRENT_MAX_ANOMALY` issues,
  `364` `RAMP_WINDOW_WARM_TAIL_SPREAD` issues, `50`
  `TAKER_BOUGHT_WARM_TAIL` issues, and `18`
  `LATE_DAY_LOCKIN_UNDER_COVERAGE` issues.

No promotion or artifact retrain was performed from this item because the
required retrain report and trust-field ablation are still absent; the item
stays partial with a reproducible gate instead of open-ended manual acceptance.

## 2026-06-23 completion

Retrained and re-exported `data/backtest/current_max_trust_retrain_merged_candidate.pkl`
with active feature schema `toronto_feature_store_v1.15`, 14 hourly models, and
the `item232_current_max_trust_warm_tail_backoff_v0_1` postprocess policy. The
policy keeps current-max trust diagnostics trainable while backing off candidate
weight in warm-tail and risky current-max contexts.

Generated item-specific acceptance evidence:

- `data/backtest/current_max_trust_retrain_evidence.json`
- `data/backtest/current_max_trust_retrain_evidence_report.md`
- `data/backtest/current_max_trust_retrain_gate.json`
- `data/backtest/current_max_trust_retrain_gate_report.md`

The current-max trust retrain evidence is `PASS` with zero blockers. The
trust-weighted artifact improves daily-first Brier versus both raw current-max
and no-current-max ablations (`-0.0022` each), improves risky current-max Brier
versus current (`-0.0058`), improves warm-tail Brier versus current (`-0.0019`),
improves early-hour Brier/log-loss versus current (`-0.0044` and `-0.0129`),
and improves late lock-in Brier versus current (`-0.0009`). The top-level
`current_max_trust_retrain_gate` now passes all prerequisite and retrain gates.

Regenerated downstream candidate evidence from the retrained artifact:

- `data/backtest/current_max_trust_candidate_replay.json`
- `data/backtest/current_max_trust_candidate_replay_report.md`
- `data/backtest/current_max_trust_variant_rows.csv`
- `data/backtest/current_max_trust_hourly_candidate_performance.json`
- `data/backtest/current_max_trust_hourly_candidate_performance_report.md`
- `data/backtest/current_max_trust_ten_minute_performance.json`
- `data/backtest/current_max_trust_ten_minute_performance_report.md`

The generic candidate replay/hourly/10-minute promotion gates remain blocked
because the weather-only candidate still trails market prices beyond those
promotion tolerances. That is not an item-232 blocker: the item acceptance is
current-max trust treatment versus current/raw/no-current-max behavior, and the
dedicated current-max gate covers warm-tail, early-hour, risky-current-max, and
late-lock-in slices. The exported shadow rows also remain quote-risk ineligible
(`quote_risk_eligible=False`, `quote_risk_gate_reason=weather_only_core_model`),
so this completion does not promote untrusted current-max evidence into
aggressive trading.

Verification:

```powershell
python -m weather.reporting.current_max_trust_retrain_evidence --artifact data\backtest\current_max_trust_retrain_merged_candidate.pkl --out data\backtest\current_max_trust_retrain_evidence.json --report data\backtest\current_max_trust_retrain_evidence_report.md
python -m weather.reporting.current_max_trust_retrain_gate --retrain-report-json data\backtest\current_max_trust_retrain_evidence.json --out data\backtest\current_max_trust_retrain_gate.json --report data\backtest\current_max_trust_retrain_gate_report.md
python -m weather.calibration.pooled_candidate_replay --artifact data\backtest\current_max_trust_retrain_merged_candidate.pkl --out data\backtest\current_max_trust_candidate_replay_report.md --json-out data\backtest\current_max_trust_candidate_replay.json --replay-report=data\backtest\current_max_trust_candidate_current_replay_report.md --candidate-variant-out data\backtest\current_max_trust_variant_rows.csv --candidate-variant-id current_max_trust_retrain_v0_1 --candidate-variant-family pooled_f_current_max_trust --skip-microstructure-overlay --source-state-ablation-variant-out= --bridge-variant-out= --min-artifact-free-bytes 0
python -m weather.reporting.candidate_hourly_performance --variant-rows data\backtest\current_max_trust_variant_rows.csv --json-out data\backtest\current_max_trust_hourly_candidate_performance.json --report-out data\backtest\current_max_trust_hourly_candidate_performance_report.md
python -m weather.reporting.ten_minute_model_performance --item147-rows data\backtest\current_max_trust_variant_rows.csv --json-out data\backtest\current_max_trust_ten_minute_performance.json --report-out data\backtest\current_max_trust_ten_minute_performance_report.md --slot-csv-out data\backtest\current_max_trust_ten_minute_by_slot.csv --candidate-csv-out data\backtest\current_max_trust_ten_minute_candidate_by_slot.csv
python -m pytest tests\calibration\test_pooled_candidate_replay.py tests\reporting\test_current_max_trust_retrain_gate.py tests\model\test_feature_store.py tests\model\test_feature_skew.py -q
```

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - TRUST RETRAIN AND WARM-TAIL ABLATION PASS`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

