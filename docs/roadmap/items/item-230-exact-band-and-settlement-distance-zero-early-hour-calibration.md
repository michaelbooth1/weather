# 230. Exact-Band And Settlement-Distance-0 Early-Hour Calibration [PARTIAL 2026-06-22 - GATE REFRESHED, DISTANCE-0 AND ONE-ABOVE BLOCKED]

Goal: repair the exact-band and settlement-distance-0 early-hour calibration
gap without causing one-above, ramp, or late-day regressions.

Source: `docs/roadmap/audits/early-hour-model-performance-audit-2026-06-22.md`.
The audit says the remaining gap is concentrated in exact `eq` bands and
settlement-distance `0`, and warns against rerunning broad alpha sweeps already
rejected by item 147.

Why this matters: early-hour underperformance is not only generic sharpness. The
model misses the eventual winner in precise near-forecast bands, and the prior
exact-winner repairs traded settlement-distance-0 improvement for one-above
regression. A promotable fix must improve the target cells without moving risk
into adjacent bands.

## Design

1. Build a daily-first blocked-validation candidate focused on exact-band and
   settlement-distance-0 slices.
2. Use inference-available no-market features: overnight forecast movement,
   source disagreement, source freshness, time-to-heating, forecast pressure,
   and forecast-relative band geometry.
3. Score exact-band, settlement-distance-0, one-below, one-above, broad early,
   ramp, and late slices in one paired replay.
4. Compare against item 147's rejected postprocess lanes so the new candidate
   proves new signal rather than another alpha sweep.
5. Report market-level and aggregate effects before promotion eligibility.

- [x] Add a candidate or validation report that isolates exact-band and
  settlement-distance-0 early-hour performance.
- [x] Add one-above and adjacent-band guardrails to the same report.
- [x] Run paired daily-first replay against current, market, and the strongest
  existing item 147 candidate.
- [x] Promote only if target-slice lift clears tolerance without aggregate or
  per-market regression.

Acceptance: paired daily-first replay improves exact-band and
settlement-distance-0 Brier/log-loss versus current, keeps the market gap within
`0.0030` on aggregate and promoted markets, shows no one-above/ramp/late
regression beyond tolerance, and documents why the candidate is not one of the
previously rejected broad-alpha/postprocess repairs.

Related: items 70, 147, 160, 178, 228, 231.

## 2026-06-22 exact/distance gate update

Added `weather.reporting.research.exact_band_distance_zero_calibration` with schema
`exact_band_distance_zero_calibration_v0.1`. The report consumes Item-69-style
candidate row exports, infers early/ramp/late/lock-in regimes from local capture
time when cutoff metadata is absent, scores daily-first exact-band and
settlement-distance-0 early slices against current and market, and includes
one-above, one-below, adjacent, broad-early, ramp, late, and lock-in guardrails.
It computes signed one-above/one-below offsets from the per-snapshot winning
exact band so two-degree bands are treated as adjacent by order rather than by
numeric `+1`.

The active predawn repair row export now has a direct item-230 gate:
`data/backtest/exact_band_distance_zero_calibration_report.md` and `.json`.
It remains `BLOCK` with three aggregate blockers:

- exact-band early improves current Brier by `-0.0021`, but still trails market
  by `+0.0047`, above the `+0.0030` tolerance.
- settlement-distance-0 early improves current Brier by `-0.0119`, but trails
  market by `+0.0478` and market log-loss by `+0.1946`.
- one-above early regresses current Brier by `+0.0036`, above the guardrail
  tolerance.

The strongest existing Item 147 row export was also scored with the same gate:
`data/backtest/item147_time_split_alpha_exact_band_distance_zero_calibration_report.md`.
That comparison confirms this is not solved by the rejected Item 147 postprocess
lane. Item 147 clears aggregate exact-band early (`delta_vs_market -0.0008`),
but settlement-distance-0 early still trails market by `+0.0142`, one-above
regresses current by `+0.0056`, one-below by `+0.0181`, and adjacent early by
`+0.0133`.

The item stays partial because the validation and guardrail surface is now live,
but no candidate currently clears the target market tolerance and adjacent-band
guardrails. Next work should be a new no-market signal or retrained artifact,
not another broad alpha/exact-winner sweep.

Verification:
`python -m pytest tests\reporting\test_exact_band_distance_zero_calibration.py tests\reporting\test_bottom_location_winner_centering.py tests\reporting\test_predawn_weak_slot_repair.py tests\reporting\test_candidate_variant_replay_summary.py tests\reporting\test_candidate_hourly_performance.py tests\calibration\test_promotion_refresh.py tests\operations\test_schema_registry.py tests\reporting\test_roadmap_backlog.py -q`
passed with `67 passed`.

Run commands:

```powershell
python -m weather.reporting.research.exact_band_distance_zero_calibration --variant-rows data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv --out data\backtest\exact_band_distance_zero_calibration.json --report data\backtest\exact_band_distance_zero_calibration_report.md
python -m weather.reporting.research.exact_band_distance_zero_calibration --variant-rows data\backtest\item147_time_split_alpha_variant_rows.csv --out data\backtest\item147_time_split_alpha_exact_band_distance_zero_calibration.json --report data\backtest\item147_time_split_alpha_exact_band_distance_zero_calibration_report.md
```

## 2026-06-22 gate refresh after predawn/bottom-location updates

I regenerated both exact-band gates:

- `data/backtest/exact_band_distance_zero_calibration.json`
- `data/backtest/exact_band_distance_zero_calibration_report.md`
- `data/backtest/item147_time_split_alpha_exact_band_distance_zero_calibration.json`
- `data/backtest/item147_time_split_alpha_exact_band_distance_zero_calibration_report.md`

The active predawn repair remains `BLOCK` with 3 aggregate blockers. It still
improves current on the target slices, but not enough for market-relative
promotion: exact-band early is `-0.0021` versus current but `+0.0047` versus
market; settlement-distance-0 early is `-0.0119` versus current but `+0.0478`
versus market and `+0.1946` log-loss versus market. The one-above early
guardrail still regresses current by `+0.0036`, above the `+0.0030` tolerance.

The Item 147 comparison remains `BLOCK` with 4 aggregate blockers. It clears
aggregate exact-band early (`delta_vs_market=-0.0008`) but fails
settlement-distance-0 early (`+0.0142` versus market) and regresses one-above,
one-below, and adjacent early guardrails by `+0.0056`, `+0.0181`, and `+0.0133`
versus current. This keeps the original conclusion intact: the rejected
Item 147 alpha lane is not the missing item 230 repair.

Item 230 remains `PARTIAL`. The validation surface is live and current, but no
available no-market candidate clears the exact/distance-0 target while
protecting adjacent bands. The next implementation has to add new
inference-time signal or retrain the artifact; another broad exact-winner alpha
sweep would repeat the failing comparison above.

## 2026-06-22 proof packet mapping

Proof-packet blocker: `weather_only_model_proof_packet.gates.exact_band_distance_zero_gate`.
Exact-band and settlement-distance-0 work must clear this packet field or be
kept diagnostic-only.
