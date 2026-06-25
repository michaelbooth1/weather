# 261. Taker Canary Tail-Share Demotion On Unsettled Sample [COMPLETE 2026-06-23 - HIGH-TAIL UNSETTLED CANARY DEMOTION LIVE]

Goal: enforce canary demotion and paper-only status whenever the active taker
canary has both `WARN_HIGH_TAIL_SHARE` and a missing settled sample, until it
is requalified on settled after-fee evidence.

Source:
`docs/roadmap/audits/trading-stack-performance-strategy-audit-2026-06-23.md`.
The June 22 `low_price_tail_capped` canary had `8` fills, no settled sample,
`6` low-price-tail fills, a `0.75` tail fraction, `MISSING_SETTLED_SAMPLE`,
and `WARN_HIGH_TAIL_SHARE`.

Why this matters: item 237 made the active canary paper-only until
requalified, but the current run-state combination needs an explicit demotion
rule. A high tail share with no settled sample is not a promotion candidate; it
is an unresolved risk signal.

## Design

1. Update `next_run_policy_gate`, daily roll status, or the relevant promotion
   gate to demote the active canary when both warning conditions are present.
2. Surface the demotion reason in operator-facing status artifacts.
3. Keep the canary paper-only until it has complete settled labels, positive
   after-fee and after-slippage evidence, no unresolved fills, and acceptable
   tail exposure.
4. Add regression coverage using the June 22 `low_price_tail_capped` evidence
   shape.
5. Route requalification back through the post-fix taker campaign instead of
   allowing ad hoc live-size restoration.

- [x] Add a demotion decision for `WARN_HIGH_TAIL_SHARE` plus
  `MISSING_SETTLED_SAMPLE`.
- [x] Expose the paper-only reason in next-run and daily roll status.
- [x] Add a June 22-style fixture or replay test that produces the demotion.
- [x] Require requalification before promotion or live-size restoration.

Acceptance: a June 22-style active canary state produces a paper-only demotion
decision, and the canary cannot promote or live-size until settled after-fee
evidence passes and low-price-tail fill fraction is at or below `0.50`.

## 2026-06-23 Completion Note

Implemented in `weather.market.taker_bot_finalization`,
`weather.reporting.trading_evidence`, and
`weather.reporting.daily_progress_ledger`.

- `next_run_policy_gate` now emits
  `WARN_HIGH_TAIL_SHARE_MISSING_SETTLED_SAMPLE` when a post-cutover active
  canary combines high low-price-tail exposure with missing settlement-scored
  evidence.
- The demotion keeps the canary paper-only, sets
  `paper_only_reason=warn_high_tail_share_missing_settled_sample`, routes
  requalification through `post_fix_taker_campaign`, and prevents promotion or
  live-size restoration.
- Settlement finalization, trading evidence, and the daily progress ledger now
  preserve the paper-only reason, demotion code, and requalification route.
- Regression coverage uses a June-22-style `low_price_tail_capped` shape with
  `WARN_HIGH_TAIL_SHARE`, `MISSING_SETTLED_SAMPLE`, zero settled orders, and
  tail fraction above `0.50`.

Verification:

- `python -m pytest tests\market\test_taker_bot.py tests\operations\test_taker_bot_daily_roll.py tests\reporting\test_trading_evidence.py tests\reporting\test_daily_progress_ledger.py -q`
  - `61 passed, 5 subtests passed`
- `python -m pytest tests\operations\test_schema_registry.py -q`
  - `3 passed`

Related: items 237, 256.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - HIGH-TAIL UNSETTLED CANARY DEMOTION LIVE`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

