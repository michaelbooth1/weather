# 301. June 23 Location Bias And Winner-Rank Repair Packet [COMPLETE 2026-06-24 - LOCATION-BIAS PACKET, REPAIR MANIFESTS, AND PROTECTED-SLICE REPLAY LIVE]

Goal: turn the settled 2026-06-23 location results into a targeted model repair
packet for locations where the served model lost to the market before final
lock-in.

Source: settled 2026-06-23 log audit. All 12 markets eventually had the settled
bucket on top in the final snapshot, but earlier winner rank and confidence were
not competitive everywhere. The model beat market Brier in Chicago, NYC, Los
Angeles, and Miami, but lost badly in Seattle, Toronto, San Francisco, and
Houston, with smaller adjacent-band problems in Austin, Denver, Dallas, and
Atlanta.

Why this matters: the final lock-in logic is doing useful work, but trading and
promotion decisions need the model to rank and size the winner earlier in the
day. June 23 shows specific directional errors: Seattle/Toronto/San Francisco
were too cool, Houston/Austin/Dallas/Denver were too warm or adjacent-band
overconfident, and several locations needed winner-mass concentration rather
than broad all-market retraining.

Why it is not already covered: item 266 added winner-rank parity reporting, item
297 will track directional drift, and item 298 will queue future experiments.
None owns a settled June 23 repair packet that preserves the strong Chicago,
NYC, Los Angeles, and Miami behavior while directly testing the weak-location
failure modes from this day.

## Design

1. Emit a June 23 per-location failure packet with settled bucket, model Brier,
   market Brier, winner probability gap, top-hit split, dominant wrong bucket,
   local-hour window, and direction of bias.
2. Promote Seattle, Toronto, San Francisco, and Houston to priority repair
   slices, with Austin/Denver/Dallas as secondary adjacent-band confidence
   slices and Atlanta as a regression-watch slice.
3. Test targeted repair variants that adjust winner mass or residual centering
   only inside the failing location/hour/signal contexts, preserving the winning
   Chicago, NYC, Los Angeles, and Miami slices.
4. Require replay evidence against market, current served model, and the June 23
   case packet before any repair can enter the normal promotion queue.
5. Feed the resulting case packet into the automatic experiment queue once item
   298 is available.

- [x] Generate the settled June 23 location failure packet and commit it as a
  reproducible backtest/report artifact.
- [x] Add targeted repair manifests for Seattle, Toronto, and San Francisco,
  with secondary manifests for Austin, Denver, and Dallas.
- [x] Add preservation checks for Chicago, NYC, Los Angeles, and Miami.
- [x] Replay repair variants against current, market, and June 23 case metrics.
- [x] Add tests that classify warm/cool directional errors and prevent a repair
  from improving one priority market by regressing the protected winners.

Acceptance: June 23's weak locations have reproducible case packets and repair
manifests, at least one targeted repair replay is scored against current and
market, protected winning locations are explicitly checked for regressions, and
the results are available to daily learning/experiment queue artifacts.

Closed notes:

- Added `weather.reporting.june23_location_bias_repair` with JSON/Markdown
  outputs `data/backtest/june23_location_bias_repair_packet.json` and
  `data/backtest/june23_location_bias_repair_packet.md`.
- The packet classifies Seattle/Toronto/San Francisco cold-miss targets,
  Austin/Dallas/Denver warm-side adjacent-confidence targets, and protected
  Chicago/Los Angeles/NYC/Miami preservation slices.
- Daily refresh now runs the packet after `winner_rank_parity` and before
  `daily_learning`, so item 298 can consume the generated repair manifests.
- Verification:
  `python -m pytest tests\reporting\test_june23_location_bias_repair.py tests\operations\test_daily_refresh.py::TestDailyRefresh::test_default_runner_order_repairs_replay_status_before_data_layer_audit`.

Related: items 21, 35, 48, 157, 219, 230, 232, 266, 297, 298.
