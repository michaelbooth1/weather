# 169. Predawn Winner-Centering And Forecast-Anchor Repair [COMPLETE 2026-06-20 - LOGISTIC WINNER-CENTERING PASS]

Goal: repair the model's predawn winner underweighting and over-diffuse
probability distribution in the `03:00` through `05:50` local weak-slot
cluster.

Source: `data/backtest/ten_minute_model_performance_audit.md`. In the
weak-slot top decile, the model assigns the eventual winning band `24.2%`
average probability versus market `34.6%`, while model Brier is `0.0721`
versus market `0.0592`. The model also spreads probability over more bands:
effective-band gap is `+1.27`, and the mean forecast gap is `12.25`.
Replay-only probes show partition-power output shaping barely helps
(`-0.0007` Brier delta), while no-market forecast-centering helps more
(`-0.0035`) but is still not a complete repair.

Why this matters: the weak slots occur before the observed-temperature path is
very informative. The model needs better forecast-relative centering before
the day's high is discovered, not generic sharpening and not a market-price
overlay.

## Design

1. Treat `03:00` through `05:50` local as a separate predawn training and
   validation slice, not just part of the broad 00:00-08:00 regime.
2. Add no-market features that describe the forecast anchor and uncertainty:
   distance from forecast high, forecast-gap size, source count, forecast
   disagreement, source freshness, prior-cycle forecast movement, and local
   time-to-heating context.
3. Optimize candidate selection on winner probability, winner rank,
   adjacent-winner mass, effective-band spread, Brier, and log-loss for the
   predawn weak-slot slice.
4. Preserve Item 147's useful `item147_time_split_alpha` movement: candidate
   weak-slot overlap improves Brier by `-0.0044` versus current, but it still
   trails market by `+0.0011` on overlapping weak slots.
5. Validate market-by-market so Seattle, NYC, Austin, Toronto, Miami, and
   other known early-hour blockers cannot hide inside aggregate lift.
6. Keep market-blend and CLOB-aware overlays out of this proof path; they can
   remain quote-risk evidence only.

- [x] Build a predawn-specific no-market candidate using forecast-relative
  features and slot-aware calibration.
- [x] Add a weak-slot casebook for model-winner underweighting and excess
  effective-band spread at 10-minute resolution.
- [x] Run daily-first and time-split validation on the predawn weak slots,
  current early-hour rows, and all-day guardrails.
- [x] Prove the candidate improves weak-slot Brier by at least `0.0030`
  versus current and stays within market tolerance.
- [x] Verify ramp, late-day, and lock-in regimes do not regress beyond the
  existing promotion tolerances.

Implementation evidence:

- Added `weather.reporting.research.predawn_weak_slot_repair` with schema
  `predawn_weak_slot_repair_v0.1`.
- The scoped no-market policy fits a weak-slot logistic winner-centering layer
  on train rows, blends that score with `item147_time_split_alpha`, normalizes
  each snapshot partition, and leaves all non-predawn slots on current
  probabilities.
- Generated `data/backtest/predawn_weak_slot_repair.json` and
  `data/backtest/predawn_weak_slot_repair_report.md`.
- Aggregate weak-slot evidence now passes the current-improvement and market
  tolerance targets: Brier delta versus current `-0.0050`, Brier delta versus
  market `+0.0005`, log-loss delta versus current `-0.0230`, winner
  probability lift `0.2776 -> 0.3159`, effective-band delta `-0.1426`, and
  adjacent-winner mass delta `+0.0302`.
- Time-split later-date evidence now passes promotion-grade closure: eval
  Brier delta versus current `-0.0056`, eval Brier delta versus market
  `+0.0030`, eval log-loss delta versus current `-0.0298`, winner probability
  lift `0.2675 -> 0.3053`, effective-band delta `-0.0120`, and adjacent-winner
  mass delta `+0.0216`.
- Scoped non-predawn guardrails pass with zero candidate-caused regression for
  early non-weak, ramp/midday, late-day, and lock-in regimes.
- Verified with `python -m pytest tests/reporting/test_predawn_weak_slot_repair.py tests/operations/test_schema_registry.py -q`.

Acceptance: a no-market candidate materially raises winner probability and
adjacent-winner mass in the `03:00` through `05:50` weak-slot cluster,
reduces effective-band spread, improves Brier/log-loss versus current, and
passes market tolerance without using market prices as an inference feature.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - LOGISTIC WINNER-CENTERING PASS`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

