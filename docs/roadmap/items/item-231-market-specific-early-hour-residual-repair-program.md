# 231. Market-Specific Early-Hour Residual Repair Program [COMPLETE 2026-06-22 - MARKET MANIFESTS AND REJECTED-FAMILY REGISTRY LIVE]

Goal: create market-scoped early-hour residual repair experiments for the
markets that keep the pooled F-family candidate outside promotion tolerance.

Source: `docs/roadmap/audits/early-hour-model-performance-audit-2026-06-22.md`.
The audit names Seattle, NYC, Austin, Miami, and San Francisco as priority
residual markets, and the 60-day roadmap also calls out Los Angeles. Existing
item 147 evidence shows simple branch selection, residual alpha, rank
sharpening, and forecast-side postprocessing do not hold up.

Why this matters: the fleet-wide candidate can improve while specific markets
remain too weak to serve. Market-specific residual work needs its own corpora,
features, and pass/fail reports so promotion can be partial by market without
hiding persistent local failures.

## Design

1. Generate one market-scoped corpus, candidate row export, and daily-first
   validation report for each blocked residual market.
2. Prioritize no-market features likely to differ by location: source
   disagreement, source availability/missingness, overnight forecast movement,
   coastal/marine context, time-to-heating, and forecast-relative winner cases.
3. Reuse the location-specific promotion allowlist so successful markets can
   promote without broad-cutting blocked markets.
4. Add a no-go registry for repair families already rejected by chronological
   evidence.
5. Require each market experiment to report current, candidate, market,
   candidate-vs-current, candidate-vs-market, and guardrail deltas.

- [x] Create market-scoped manifests for Seattle, NYC, Austin, Miami,
  San Francisco, and Los Angeles residual experiments.
- [x] Run paired daily-first replays per market with current and market
  baselines.
- [x] Add a rejected-repair registry entry for each failed postprocess family.
- [x] Feed passing markets into the per-market promotion allowlist while
  keeping failed markets blocked or shadowed.

Acceptance: each residual market has a durable validation report; a market can
move to promote/shadow only when its candidate gap is within `0.0030` of market
without aggregate, adjacent-band, ramp, or late regression; and failed repair
families are recorded so they are not rerun as broad promotion attempts.

Related: items 147, 218, 219, 222, 224, 227, 230.

## Completion Notes

Added `weather.reporting.market_residual_repair_program` with schema
`market_residual_repair_program_v0.1`. The report consumes candidate row
exports, builds a market-scoped manifest for each residual market, scores each
candidate against current and market with the item-230 exact/distance target
and adjacent/ramp/late guardrails, and writes a rejected-family registry so
failed postprocess families are not silently rerun.

Generated artifacts:

- `data/backtest/market_residual_repair_program.json`
- `data/backtest/market_residual_repair_program_report.md`
- `data/backtest/market_residual_repair_rejected_registry.json`
- `data/backtest/market_residual_repair_manifests/item231_austin_early_residual_v0_1.json`
- `data/backtest/market_residual_repair_manifests/item231_los_angeles_early_residual_v0_1.json`
- `data/backtest/market_residual_repair_manifests/item231_miami_early_residual_v0_1.json`
- `data/backtest/market_residual_repair_manifests/item231_nyc_early_residual_v0_1.json`
- `data/backtest/market_residual_repair_manifests/item231_san_francisco_early_residual_v0_1.json`
- `data/backtest/market_residual_repair_manifests/item231_seattle_early_residual_v0_1.json`

The first run compared `item147_time_split_alpha` and the predawn repair row
export, and imported the existing basket no-go dispositions. The program status
is `BLOCK`, with `3` shadow-only markets and `3` blocked markets:

- `austin`: predawn repair clears the market-scoped gate and is recommended as
  `KEEP_SHADOW`, not promotion permission.
- `miami`: `item147_time_split_alpha` clears the market-scoped gate and is
  recommended as `KEEP_SHADOW`.
- `san-francisco`: `item147_time_split_alpha` clears the market-scoped gate and
  is recommended as `KEEP_SHADOW`.
- `seattle`: remains `BLOCK_CANDIDATE`; predawn repair regresses current on the
  exact-band target (`+0.0016`).
- `nyc`: remains `BLOCK_CANDIDATE`; Item 147 trails market on the exact-band
  target by `+0.0037`, above tolerance.
- `los-angeles`: remains `BLOCK_CANDIDATE`; Item 147 trails market on the
  exact-band target by `+0.0076`.

The rejected registry has `11` entries covering the existing basket no-go
dispositions, `item147_forecast_centering_exact_winner`, and the predawn repair
family where they failed market-specific gates. Passing market-scoped diagnostics
are kept as shadow recommendations because these row-export manifests are not
active serving permission artifacts.

Verification:
`python -m pytest tests\reporting\test_market_residual_repair_program.py tests\reporting\test_exact_band_distance_zero_calibration.py tests\reporting\test_bottom_location_winner_centering.py tests\reporting\test_predawn_weak_slot_repair.py tests\reporting\test_candidate_variant_replay_summary.py tests\reporting\test_candidate_hourly_performance.py tests\reporting\test_variant_basket_selection_validation.py tests\calibration\test_promotion_refresh.py tests\operations\test_schema_registry.py tests\reporting\test_roadmap_backlog.py -q`
passed with `76 passed`.

Run command:

```powershell
python -m weather.reporting.market_residual_repair_program --known-no-go data\backtest\item147_blocked_markets_variant_basket_no_go.json --known-no-go data\backtest\item147_blocked_markets_variant_basket_with_item32_no_go.json --out data\backtest\market_residual_repair_program.json --report data\backtest\market_residual_repair_program_report.md --manifest-dir data\backtest\market_residual_repair_manifests --rejected-registry-out data\backtest\market_residual_repair_rejected_registry.json
```
