# Workstation handoff 2026-09-110q — exchange-economics drift: tick-size mix is not a material change

Written 2026-09-27 by the production agent. Stage-A (09:30 task `WeatherDailySettlementPromotionRefresh`) exited 2 on
2026-09-26 and again on 2026-09-27: the settled-day barrier blocks on `exchange_economics_rule_drift` BLOCK
`exchange_economics_material_drift_rescore_required`. On 09-26 that was real drift (baseline from 06-27; owner re-accepted).
On 09-27 the only "material" field is `market_fee_rule_profiles`, and nothing in it changed economically:

- Both accepted and current snapshots contain exactly **two distinct profiles** per city, identical in fee schedule
  (rate 0.05, exponent 1, rebate 0.25, taker-only), `fees_enabled` and `order_min_size` 5; they differ only in
  `order_price_min_tick_size` 0.01 vs 0.001.
- Per-city profile counts are equal (33 or 22). Only the **mix** moved, e.g. Atlanta 12 → 15 markets at 0.001 tick,
  NYC 15 → 12: the venue gives markets priced near 0 or 1 the finer tick, so the mix shifts every day with prices.
- Cause: `normalized_economics_payload` (`src/weather/market/exchange_economics.py` ~795-812) builds a per-location
  **multiset** of per-market profiles, and `market_fee_rule_profiles` is in `MATERIAL_FIELD_PATHS` (~73). Any daily shift
  in the tick mix therefore reads as material drift, so the promotion lane blocks every day.

## Build (branch `codex/economics-drift-tick-mix-20260927`, base `origin/master`)

- Compare fee economics as the per-location **set of distinct fee profiles** (fee schedule, fees_enabled, order_min_size),
  and treat the tick size as its own field: material only if a tick value appears that is outside the venue's documented
  set {0.01, 0.001} (or the set of distinct tick values changes). Keep a non-material diagnostic listing per-city tick mixes.
- A real change (rate, rebate, taker_only, exponent, fees_enabled, min size, a new tick value) must still be material and block.
- Changing the normalized payload changes `snapshot_hash`: keep accepted-baseline compatibility (compare old baselines under
  the new projection, or version the projection) so today's accepted 09-26 baseline passes without another re-acceptance.
- Tests: tick-mix shift only → PASS; rate/rebate/min-size/new tick → BLOCK; old-baseline compatibility; `snapshot_hash`
  stability for identical inputs. Include the repo-wide audits in the focused run.

## Boundaries and deliverables

Fixtures only (you may construct them from the field shapes above); no venue calls or production data. State roll
classification per file (production verifies with `roll_verdict.ps1`). Push and a draft PR are authorized. Report
`docs/roadmap/agent-report-2026-09-110q-economics-drift-tick-mix.md`, verdict first.
