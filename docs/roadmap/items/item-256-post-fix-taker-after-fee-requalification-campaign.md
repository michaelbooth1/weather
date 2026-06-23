# 256. Post-Fix Taker After-Fee Requalification Campaign [OPEN 2026-06-23 - NO FRESH COMPLETE-LABEL PROFIT SAMPLE]

Goal: collect a fresh paper-only champion/challenger campaign under current
taker defaults and require complete-label, after-fee, after-slippage evidence
before any live promotion.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-23.md`.
The last labelable runs are settlement-negative in aggregate (`-96.611751`
USDC over `154` settled fills), all settled rows are `paper_no_fee`, and the
active June 22 `low_price_tail_capped` run has `8` unresolved fills with no
settled sample.

Why this matters: items 234-241 added the right gates, but they do not create
the missing evidence. The bot needs a clean post-fix sample under the current
fee, bad-tail, cadence, current-high, and bakeoff defaults before any
profitability claim can be counted.

## Design

1. Relaunch paper taker runs under current source defaults, not the stale
   `daily_roll_status.json` launch config.
2. Run the full champion/challenger set every day, including
   `low_price_tail_capped`, trusted current-high/adjacent arms, and the
   two-sided/fade probe.
3. Settlement-score each day as labels arrive and require `3-5` complete-label
   days before promotion.
4. Track net PnL after fees, slippage, executable depth, drawdown,
   per-market stability, tail fraction, unresolved fills, and MTM sign flips.
5. Keep every arm paper-only until the full campaign passes.

- [ ] Start a fresh paper campaign with current taker defaults and full
  bakeoff strategies.
- [ ] Finalize each labelable run through the watchdog within SLA.
- [ ] Build a campaign ledger with complete-label day count, after-fee net PnL,
  drawdown, tail exposure, and market-benchmark comparison.
- [ ] Require explicit operator review before any live-size change.

Acceptance: no taker strategy is considered live-qualified until a fresh
post-fix campaign has at least `3-5` complete-label days, sufficient fills,
positive after-fee/after-slippage PnL, stable per-market slices, no unresolved
orders, and no material MTM/settlement sign-flip pattern.

Related: items 234, 237, 238, 240, 241, 253.
