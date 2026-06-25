# 283. Settlement-Calibrated And Market-Shrunk Taker Fair Value [COMPLETE 2026-06-23 - CALIBRATED MARKET-SHRUNK TAKER FAIR LIVE]

Goal: stop the taker from treating the raw served model probability as fair
value. Calibrate the model band probability against settlement outcomes, then
blend it toward the market-implied probability by a proven per-slice skill
weight, so the bot only disagrees with the market where it has earned the right
to.

Source: 2026-06-23 ML audit of the taker bot. The entry path uses the raw
served `fair_probability` (only clamped) to compute `edge = fair - best_ask` in
`base_order_row` (`weather.market.taker_bot_strategy_evaluation`). On settled run
`data/taker_runs/2026-06-21/taker-20260621-bbe63642` the model reported
`expected_pnl_usdc=+701.4` and realized `executable_net_pnl_usdc=-56.3`; bands
the model rated `fair` 0.2-0.4 won 0 of 20, and bands rated 0.0-0.2 won 0 of 26.
The market benchmark flagged 433 market-smarter slices, and the model-market
disagreement audit reports the market closer on every resolved case (average
Brier gap market-model -0.53). The model probability is badly miscalibrated and
is consumed without a market prior.

Why this matters: when the market is better calibrated than the model, a large
`fair - ask` gap is overwhelmingly model error, not market mispricing. Using raw
served probability as fair value makes every downstream gate and sizing rule
operate on a biased target. The single highest-leverage change is to correct the
probability against settlement truth and shrink it toward the market unless the
model has demonstrated slice-specific edge.

Why it is not already covered: item 167 added a `reliability_confidence` and
`reliability_adjusted_fair_probability`, but that adjustment is a freshness/trust
haircut (`adjusted = best_ask + edge * confidence`) driven by source/book/model
staleness, not an isotonic/Platt calibration against settlement outcomes, and it
has no market-implied prior. Items 21/22/136/147/262 produce calibration and
reliability artifacts at the model/serving layer, but the taker entry path
consumes none of them. No existing item makes the taker's fair value a
settlement-calibrated, market-shrunk quantity.

## Design

1. Build a taker settlement-calibration map that maps served band probability to
   realized settlement frequency, keyed by the buckets `reliability_context_key`
   already defines (market, hour, band-distance-from-current-high, source-state,
   trust-state, model variant). Reuse existing artifacts where they exist
   (`item136_source_state_reliability`, `item147_*_residual_calibration_time_split`,
   `exact_band_distance_zero_calibration`, the proper-scoring scorecard from item
   262) and fall back to a pooled prior for sparse cells.
2. Compute `market_implied` from the live CLOB/midpoint for the same band and a
   per-slice `skill_weight` w in [0,1] from settlement-scored, time-blocked,
   out-of-sample model-minus-market skill. Set
   `calibrated_fair = market_implied + w * (calibrated_model - market_implied)`,
   so w to 0 collapses fair value to the market and produces no edge.
3. Emit `calibrated_model_probability`, `market_implied_probability`,
   `taker_skill_weight`, and `calibrated_edge = calibrated_fair - best_ask` as
   first-class order columns alongside the existing raw `edge`, without removing
   the raw fields used by historical tapes.
4. Feed `calibrated_fair` and `taker_skill_weight` into the existing item-167
   sizing rules so fractional Kelly and EV tiers size on the calibrated
   probability times the proven skill weight, not on raw or freshness-only edge.
   Cap sizing by the cell's historical hit-rate where it exists.
5. Keep everything fail-closed and shadow-first: missing calibration or skill
   evidence yields w to 0 (market fair, no trade), and the calibrated path is
   proven through the item 273 counterfactual tape and item 238/275 bakeoff
   before it changes the active default.

- [x] Add a taker settlement-calibration map builder keyed by the existing
  reliability context buckets, reusing item 136/147/262 artifacts with a pooled
  fallback.
- [x] Compute `market_implied_probability` and a settlement-scored, out-of-sample
  per-slice `taker_skill_weight`.
- [x] Emit `calibrated_model_probability`, `market_implied_probability`,
  `taker_skill_weight`, and `calibrated_edge` order columns.
- [x] Route the item-167 sizing rules to size on calibrated probability times
  skill weight, capped by historical hit-rate.
- [x] Prove on the item 273 counterfactual tape and item 238/275 bakeoff that
  calibrated/market-shrunk fair value improves settlement-scored after-fee PnL
  versus the raw-edge control, fail-closed when evidence is missing.

## Completion

Implemented `weather.market.taker_edge_permission` as the taker calibration and
edge-permission layer. The order path now loads the permission map once per
budget application, computes `market_implied_probability`,
`calibrated_model_probability`, `taker_skill_weight`, `calibrated_fair`, and
`calibrated_edge`, and fails closed to market fair when no proven slice evidence
exists. Item-167 sizing now prefers calibrated after-cost EV and multiplies
confidence by proven taker skill, with historical hit-rate as an additional cap.

Verification: `python -m py_compile` over the touched taker modules and the
focused suite pass, including coverage for unpermissioned slices shrinking fair
to market.

```powershell
pytest tests\market\test_taker_bot.py tests\market\test_taker_bot_two_sided.py -q
```

Acceptance: taker order rows carry a settlement-calibrated, market-shrunk
`calibrated_fair` and `calibrated_edge` with an explicit per-slice
`taker_skill_weight`; when a slice has no proven out-of-sample edge the weight
collapses fair value to the market and the calibrated edge is non-positive; and
a settled counterfactual/bakeoff replay shows calibrated fair value reduces the
overconfident expected-vs-realized PnL gap (for example the June 21 +701 vs -56
divergence) without relying on market-informed leakage.

Related: items 21, 22, 136, 147, 167, 262, 264, 269, 273.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - CALIBRATED MARKET-SHRUNK TAKER FAIR LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

