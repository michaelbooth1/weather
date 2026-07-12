# 219. Bottom-Location Early/Midday Winner-Centering Repair [PARTIAL 2026-07-12 - V0.1 PROOF INVALIDATED, CLEAN REQUALIFICATION REQUIRED]

Goal: build a no-market centering candidate for the bottom locations,
especially Seattle, NYC, and Miami, focused on early and midday winner mass
rather than broad sharpening.

Source: `docs/roadmap/audits/location-performance-model-audit-2026-06-22.md`.
The bottom cohort has `+0.0290` early and `+0.0325` midday Brier excess versus
market, with winner gaps around `-0.156`. Late-day excess is only `+0.0025`.
`predawn_weak_slot_repair.json` passes weak-slot Brier (`0.0620` vs market
`0.0615`) and log-loss, but the eval split remains at the `+0.0030` tolerance
boundary. Existing basket/guard policies still fail the hard markets.

Why this matters: the location gap is a centering failure in the time windows
where observed-high evidence is weakest. Generic sharpening, source freshness,
and existing variant selection have already been tested and do not clear the
hard markets.

## Design

1. Promote `predawn_logistic_winner_centering_item147_blend` into an explicit
   shadow/replay candidate with per-market reporting.
2. Extend the weak-slot candidate into early and midday Seattle, NYC, and Miami
   using no-market inputs only.
3. Score winner probability, winner rank, adjacent-winner mass, Brier, log-loss,
   and effective bands by market, cutoff regime, and market-day.
4. Keep existing item134/item135/item147/item32 basket selection as diagnostic
   only unless a new held-out validation clears tolerance.

- [x] Create an active shadow/replay lane for the predawn/item147 centering
  candidate.
- [x] Add bottom-location early/midday slices to the candidate report.
- [x] Require Seattle, NYC, and Miami to clear weak-slot and early/midday
  market tolerance independently.
- [x] Add guardrails for late-day and lock-in non-regression.
- [x] Build the next no-market repair that clears Seattle, NYC, and Miami
  early/midday market tolerance.

Acceptance: a no-market candidate improves bottom-location early/midday winner
probability and Brier versus current, clears `<= +0.0030` Brier delta versus
market on the hard markets, and does not regress late-day or lock-in slices.

Related: items 147, 160, 168, 169, 178, 218, 222.

## Implementation Update 2026-06-22

- Added `weather.reporting.research.bottom_location_winner_centering` with schema
  `bottom_location_winner_centering_v0.1`.
- The report scores the repaired no-market predawn candidate by hard market
  (`seattle`, `nyc`, `miami`) and by `weak_slot`, `early`, `midday`, `late`,
  and `lock_in` slices.
- Regenerated the repaired predawn candidate row export with `cutoff_hour` and
  `cutoff_regime` preserved for downstream slice gates.
- Generated `data/backtest/bottom_location_winner_centering.json` and report.

Current result: `BLOCK` with 8 required-slice blockers. Miami weak-slot passes,
and all late/lock-in guardrails pass, but the hard markets still fail:

- Seattle weak-slot regresses current by `+0.0307` Brier and trails market by
  `+0.0451`; Seattle early also regresses current by `+0.0014`; Seattle midday
  trails market by `+0.0400`.
- NYC has no weak-slot overlap rows in this repaired export, and NYC early and
  midday trail market by `+0.0359` and `+0.0403`.
- Miami weak-slot passes, but Miami early and midday trail market by `+0.0178`
  and `+0.0339`.

Verification:

```powershell
python -m pytest tests\reporting\test_bottom_location_winner_centering.py tests\reporting\test_predawn_weak_slot_repair.py tests\reporting\test_candidate_variant_replay_summary.py tests\reporting\test_candidate_hourly_performance.py tests\calibration\test_promotion_refresh.py tests\operations\test_schema_registry.py -q
python -m weather.reporting.research.bottom_location_winner_centering --variant-rows data\backtest\pooled_f_candidate_miami_current_fallback_predawn_repair_rows.csv --ten-minute-report data\backtest\ten_minute_model_performance.json --out data\backtest\bottom_location_winner_centering.json --report data\backtest\bottom_location_winner_centering_report.md
```

## 2026-06-22 gate refresh after predawn sweep

I regenerated the bottom-location gate after the Item 228 parameter sweep:

- `data/backtest/bottom_location_winner_centering.json`
- `data/backtest/bottom_location_winner_centering_report.md`

The result remains `BLOCK` with 8 required-slice blockers. Across the bottom
cohort, the repaired predawn candidate improves weak-slot Brier
(`delta_vs_current=-0.0615`, `delta_vs_market=-0.0204`), but the broader early
and midday slices still miss market tolerance. This matches the Item 228 sweep:
the current predawn/item147 repair can be a scoped weak-slot shadow lane, but
cannot be promoted as the next broad bottom-location early-hour fix.

Market blockers remain concentrated in the hard slices:

- Seattle weak-slot regresses current by `+0.0307` and trails market by
  `+0.0451`; Seattle early has a small current regression (`+0.0014`) and
  Seattle midday trails market by `+0.0400`.
- NYC has no weak-slot overlap rows in the repaired export; NYC early and
  midday trail market by `+0.0359` and `+0.0403`.
- Miami weak-slot passes, but Miami early and midday trail market by `+0.0178`
  and `+0.0339`.

Item 219 remains `PARTIAL`. The next actionable repair is not another global
predawn calibrator tweak; it needs a no-market residual candidate that directly
targets Seattle/NYC/Miami early and midday winner mass while preserving the
late and lock-in guardrails that already pass.

## 2026-06-22 proof packet mapping

Proof-packet blocker: `weather_only_model_proof_packet.gates.bottom_location_gate`.
Bottom-location work is ordered by this packet blocker; candidate diagnostics
must clear or retire it before the roadmap treats them as readiness progress.

## Completion Notes

2026-06-24: `item224_active_timesplit_logistic_repair_v0_1` is the accepted
no-market repair for this item. The active time-split logistic export trains on
2026-06-07 and 2026-06-08, evaluates on 2026-06-12 and 2026-06-13, excludes
label/market/identity fields from training, and carries `uses_market_features=false`.

`weather.reporting.research.bottom_location_winner_centering` now defaults to:

- `data/backtest/item224_active_timesplit_logistic_repair_rows.csv`
- `data/backtest/item224_active_timesplit_logistic_repair_ten_minute.json`

Regenerated canonical evidence:

- `data/backtest/bottom_location_winner_centering.json`
- `data/backtest/bottom_location_winner_centering_report.md`

Result: `PASS` with `blocker_count=0`. Seattle, NYC, and Miami independently
clear `weak_slot`, `early`, and `midday` required slices under the `+0.0030`
market Brier tolerance and `+0.0100` log-loss tolerance. Aggregate bottom
early/midday winner probability improves from `0.2335`/`0.2743` current to
`0.8918`/`0.8889` candidate, and bottom early/midday Brier improves versus
current by `-0.0695`/`-0.0683` and versus market by `-0.0263`/`-0.0156`.
Late-day guardrails pass for all hard markets; lock-in remains sparse in this
row export.

Verification:

```powershell
python -m weather.reporting.research.bottom_location_winner_centering
python -m pytest tests\reporting\test_bottom_location_winner_centering.py tests\reporting\test_item224_active_timesplit_logistic_repair.py tests\operations\test_schema_registry.py tests\reporting\test_roadmap_backlog.py -q
```

## 2026-07-12 Evidence Invalidation And Reopen

The June 24 completion depended on
`item224_active_timesplit_logistic_repair_v0_1`. Item 224's July 11 audit proved
that candidate used post-settlement `settlement_distance_bucket` directly and
through derived missingness/casebook state. The bottom-location `PASS` therefore
does not establish an inference-available repair and cannot remain acceptance
evidence for this item.

The implementation and historical diagnostics remain useful, but Item 219 is
reopened. The old rows and reports stay diagnostic-only and must not be
overwritten under the same identity.

- [ ] Train a new candidate identity from the canonical point-in-time,
  inference-available feature contract with a passing leakage audit.
- [ ] Re-run Seattle, NYC, and Miami weak-slot, early, midday, late, and lock-in
  gates on fleet-date-blocked rolling validation with date-clustered intervals.
- [ ] Clear live coverage and captured-input replay/serve parity under one
  immutable release before restoring the completion disposition.
