# 261. Taker Canary Tail-Share Demotion On Unsettled Sample [OPEN 2026-06-23 - WARN_HIGH_TAIL_SHARE PLUS MISSING SETTLED SAMPLE MUST PAPER-ONLY]

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

- [ ] Add a demotion decision for `WARN_HIGH_TAIL_SHARE` plus
  `MISSING_SETTLED_SAMPLE`.
- [ ] Expose the paper-only reason in next-run and daily roll status.
- [ ] Add a June 22-style fixture or replay test that produces the demotion.
- [ ] Require requalification before promotion or live-size restoration.

Acceptance: a June 22-style active canary state produces a paper-only demotion
decision, and the canary cannot promote or live-size until settled after-fee
evidence passes and low-price-tail fill fraction is at or below `0.50`.

Related: items 237, 256.
