# 228. Predawn Weak-Slot Repair Candidate Gate [PARTIAL 2026-06-22 - PARAMETER SWEEP BLOCKS BROAD HOURLY]

Goal: turn the predawn weak-slot repair from a promising diagnostic probe into
a promotion-compatible candidate gate.

Source: `docs/roadmap/audits/early-hour-model-performance-audit-2026-06-22.md`.
The audit identifies the 03:00-05:50 weak-slot cluster as the strongest repair
target and says the scoped predawn repair should be tested as an explicit
candidate artifact rather than kept as a note.

Why this matters: the repair can only mitigate the production weak-slot blocker
if it is validated through the same replay and candidate-gate contracts used by
promotion refresh. A CSV probe that improves weak slots is not enough if the
active replay artifact, hourly gate, and 10-minute gate do not all point to the
same candidate.

## Design

1. Promote `weather.reporting.predawn_weak_slot_repair` output into an active
   candidate artifact or replay export contract, not only a row-export
   surrogate.
2. Generate candidate hourly and candidate 10-minute reports from the same
   repaired variant id and corpus lineage.
3. Add guardrails for non-weak early hours, ramp windows, late-day lock-in, and
   per-market regressions.
4. Keep the repair no-market: market-informed/CLOB overlays may remain
   quote-risk evidence, but cannot be counted as core weather-model lift.
5. If the repair passes weak-slot evidence but still misses the broad
   00:00-08:00 hourly gate, keep it shadowed and mine the residual markets.

- [x] Export a promotion-compatible predawn repair candidate row export and
  replay summary with separate source-corpus and repaired-row lineage hashes.
- [x] Run candidate hourly and candidate 10-minute gates on the repaired
  variant and require matching variant ids and corpus lineage.
- [x] Add ramp, late, lock-in, non-weak early, and per-market guardrail tables.
- [x] Wire the repaired candidate into promotion refresh without relabeling
  surrogate evidence as active replay evidence.
- [ ] Promote the repaired row export into a true active replay/export contract
  and clear the broad candidate-hourly gate.

Acceptance: weak-slot Brier improves by at least `0.0030` versus current,
weak-slot Brier is within `0.0030` of market, log-loss does not regress, broad
hourly and non-weak guardrails do not regress beyond tolerance, and promotion
refresh applies mitigation only when repaired replay, hourly, and 10-minute
variant ids match.

Related: items 147, 160, 168, 169, 178, 227, 230, 231.

## Implementation Update 2026-06-22

- `weather.reporting.predawn_weak_slot_repair` now writes the repaired
  candidate rows plus matching replay-summary, candidate-hourly, and
  candidate-10-minute gate artifacts from the same command.
- Candidate gate lineage now keeps the pinned promotion `corpus_hash` separate
  from the repaired-row `row_export_corpus_hash`, so promotion refresh can prove
  source-corpus identity without confusing row-export identity for active replay
  evidence.
- Regenerated
  `data/backtest/pooled_f_candidate_miami_current_fallback_predawn_repair_*`
  artifacts from `item82_miami_fallback_shadow_variants.csv`.
- The repaired weak-slot gate passes: candidate 10-minute gate `PASS`, 1,617
  weak-slot rows, 12 market-days, Brier delta versus current `-0.0293`, Brier
  delta versus market `-0.0089`, and log-loss delta versus market `-0.0054`.
- Promotion refresh now loads the repaired candidate reports and fails closed
  for the right reasons: candidate hourly gate `BLOCK` because early-hour Brier
  still trails market by `+0.0048 > +0.0030`, replay summary remains
  `row_export_surrogate / DO_NOT_CUT_OVER`, and readiness stays `OPEN`.

Verification:

```powershell
python -m pytest tests\reporting\test_predawn_weak_slot_repair.py tests\reporting\test_candidate_variant_replay_summary.py tests\reporting\test_candidate_hourly_performance.py tests\calibration\test_promotion_refresh.py -q
python -m weather.reporting.predawn_weak_slot_repair --candidate-rows data\backtest\item82_miami_fallback_shadow_variants.csv --ten-minute-report data\backtest\ten_minute_model_performance.json --calibrator-blend 0.30 --calibrator-extrapolation 2.0 --calibrator-power 3.0 --output-variant-id pooled_f_candidate_miami_current_fallback_predawn_repair_v0_1 --candidate-rows-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv --write-candidate-gates --source-candidate-json data\backtest\pooled_candidate_replay_latest.json --candidate-replay-summary-json-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary.json --candidate-replay-summary-report-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary_report.md --candidate-hourly-json-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_hourly_candidate_performance.json --candidate-hourly-report-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_hourly_candidate_performance_report.md --candidate-ten-minute-json-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_performance.json --candidate-ten-minute-report-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_performance_report.md --json-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_weak_slot_repair.json --report-out data\backtest\pooled_f_candidate_miami_current_fallback_predawn_weak_slot_repair_report.md
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary.json --precomputed-candidate-report data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary_report.md --candidate-hourly-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_performance.json --skip-serving-gauntlet --disable-long-job-guard --out data\backtest\f_family_promotion_refresh_predawn_repair.json --report data\backtest\f_family_promotion_refresh_predawn_repair_report.md --incomplete-manifest data\backtest\f_family_promotion_refresh_predawn_repair_incomplete.json
```

## 2026-06-22 parameter-sweep no-go refresh

I added the registered diagnostic
`weather.reporting.predawn_weak_slot_parameter_sweep`
(`predawn_weak_slot_parameter_sweep_v0.1`) and generated:

- `data/backtest/item228_predawn_weak_slot_parameter_sweep.json`
- `data/backtest/item228_predawn_weak_slot_parameter_sweep_report.md`

The sweep fits the same time-split predawn logistic calibrator once, then
evaluates 2,744 deterministic blend/extrapolation/power settings against the
two active gates that matter for this item: candidate-hourly 00:00-08:00
market tolerance and candidate 10-minute weak-slot tolerance. The result is a
hard no-go for broad promotion: `0` settings pass both gates. `371` settings
preserve candidate 10-minute weak-slot `PASS`, but none clear the broader
candidate-hourly gate.

The best swept setting (`blend=0.35`, `extrapolation=2.25`, `power=1.25`) keeps
the weak-slot repair strong (`delta_vs_current=-0.0289`,
`delta_vs_market=-0.0085`, log-loss delta versus market `-0.0135`) but still
blocks the broad early-hour gate: early Brier trails market by `+0.0041`
against the `+0.0030` tolerance and early log-loss trails market by `+0.0199`
against the `+0.0100` tolerance. Hour 03:00 remains the weak repaired hour
(`+0.0048` versus market) while 04:00 and 05:00 are inside market.

This keeps Item 228 `PARTIAL`. The scoped predawn repair is valid shadow
evidence for weak slots, but it should not be promoted as a broad early-hour
mitigation or relabeled as active replay/export contract evidence. The next
work belongs in the residual repair items: isolate 03:00 and the non-weak
early rows by market before attempting another candidate-hourly promotion.

Verification:

- `python -m pytest tests\reporting\test_predawn_weak_slot_parameter_sweep.py tests\operations\test_schema_registry.py -q`
  passed with `5 passed`.

## 2026-06-22 proof packet mapping

Proof-packet blocker: `weather_only_model_proof_packet.gates.ten_minute_gate`.
Predawn weak-slot work remains scoped to this packet field; it stays
diagnostic-only for broader readiness unless it also changes hourly and market
dispositions.
