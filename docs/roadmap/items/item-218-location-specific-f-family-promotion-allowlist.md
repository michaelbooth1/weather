# 218. Location-Specific F-Family Promotion Allowlist [COMPLETE 2026-06-22 - PER-MARKET ALLOWLIST ENFORCED]

Goal: enforce fail-closed F-family promotion recommendations by market, so a
candidate cannot broad-cut over markets that failed the location audit. The
current v0.1 allowlist is recommendation evidence, not serving authorization.

Source: `docs/roadmap/audits/location-performance-model-audit-2026-06-22.md`.
The active shadow split shows Atlanta, San Francisco, and Denver near market
performance, while Miami, NYC, and Seattle trail market by `+0.0148`,
`+0.0231`, and `+0.0242` Brier respectively. The current promotion refresh
promotes only Atlanta and Houston, keeps San Francisco in shadow, and blocks
Austin, Chicago, Dallas, Denver, Los Angeles, Miami, NYC, and Seattle.

Why this matters: aggregate candidate improvement hides market-specific
regression risk. A broad F-family promotion would ship known market-tolerance
failures into serving and trading permission.

## Design

1. Make the promotion allowlist a generated artifact from
   `f_family_promotion_refresh.json`, keyed by `market_id`, candidate id,
   action, blocker reason, and generated-at timestamp.
2. Require serving and paper/live permission paths to read the allowlist before
   considering a new F-family candidate for a market, while requiring a
   separate supported authorization envelope before acceptance.
3. Keep shadow markets visible but non-serving unless they beat current and
   clear market tolerance on market-day evidence.
4. Add a report section that shows promoted, shadowed, and blocked markets next
   to current Brier, candidate Brier, market Brier, and winner gap.

- [x] Export a durable per-market F-family promotion allowlist.
- [x] Wire the allowlist into serving/paper permission so non-allowlisted
  markets remain on current behavior.
- [x] Add a regression test where a strong aggregate candidate is blocked for a
  market that fails tolerance.
- [x] Regenerate promotion refresh and active shadow reports with the allowlist
  surfaced.

## Completion Notes

Promotion refresh now emits `data/backtest/f_family_promotion_allowlist.json`
and embeds the same `promotion_allowlist` payload in
`f_family_promotion_refresh.json`. Each row is keyed by `market_id`,
candidate id, generated timestamp, action, serving/permission behavior, blocker
reason, and market-level Brier evidence.

The market-making known-edge map and policy snapshot loaders now prefer
`promotion_allowlist.markets` over legacy `decisions.markets`, while keeping
legacy fallback behavior for older refresh artifacts. Non-`PROMOTE_CANDIDATE`
markets are loaded as `BLOCK` or `SHADOW` state and cannot accept the candidate
through paper/live permission paths.

Security clarification (2026-07-23): `promotion_allowlist_v0.1` has no
independent current-input trust root, expiry, or runtime authorization
signature. Runtime consumers therefore treat its `PROMOTE_CANDIDATE` rows as
recommendations capped at `SHADOW` and force its candidate-serving and
candidate-permission claims false. Existing `BLOCK` rows remain blocks. A
future schema must prove an independently verified root envelope and exact
per-market authorization before any recommendation can affect serving or
release eligibility.

The regenerated allowlist has `3` promote markets (`austin`, `denver`,
`houston`) and `8` blocked markets (`atlanta`, `chicago`, `dallas`,
`los-angeles`, `miami`, `nyc`, `san-francisco`, `seattle`). The active
shadow/A-B monitor report now shows that it consumed the allowlist for
`pooled_f_candidate_miami_current_fallback_v0_1`.

Verification:

- `python -m pytest tests\calibration\test_promotion_refresh.py tests\market\test_mm_paper.py tests\market\test_mm_policy.py tests\reporting\test_shadow_ab_monitor.py tests\operations\test_schema_registry.py -q`
- `python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\pooled_candidate_replay_latest.json --precomputed-candidate-report data\backtest\pooled_candidate_replay_latest_report.md --candidate-hourly-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_hourly_candidate_performance.json --candidate-ten-minute-performance-report data\backtest\pooled_f_candidate_miami_current_fallback_ten_minute_performance.json --skip-serving-gauntlet`
- `python -m weather.reporting.candidate_lifecycle.shadow_ab_monitor --promotion-refresh data\backtest\f_family_promotion_refresh.json --candidate-replay data\backtest\pooled_candidate_replay_latest.json --json-out data\backtest\shadow_ab_monitor.json --report-out data\backtest\shadow_ab_monitor_report.md`

Acceptance: a candidate can be recommended for promotion only for markets whose
generated action is `PROMOTE_CANDIDATE`; all other markets remain
shadow/current in serving and permission outputs; promotion reports show the
exact market-level evidence that caused each action; and no recommendation is
authorization without a separately supported, runtime-verifiable envelope.

Related: items 48, 86, 139, 140, 163, 217.
