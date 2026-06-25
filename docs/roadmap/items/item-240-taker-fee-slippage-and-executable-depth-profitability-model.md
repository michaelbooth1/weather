# 240. Taker Fee, Slippage, And Executable-Depth Profitability Model [COMPLETE 2026-06-22]

Goal: make taker scoring, bakeoff, and profitability claims include fees,
spread/slippage, and executable order book depth before any live-use decision.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-22.md`.
The bot config uses `taker_fee_rate: 0.0`, while provider fee documentation
lists a Weather taker fee schedule and maker fee `0`. Marketable orders execute
against the book, so paper fills must account for available depth and spread.

Why this matters: a strategy that is barely profitable before fees or assumes
free top-of-book liquidity can become negative live. Promotion and live-profit
claims need executable net PnL, not frictionless paper PnL.

## Design

1. Add a fee-rate adapter or versioned fee config snapshot by market type and
   execution side.
2. Simulate fills against actual best-ask depth and spread for marketable
   taker orders.
3. Store gross PnL, fee PnL, slippage PnL, and net executable PnL separately.
4. Require after-fee and after-slippage PnL for bakeoff, settlement
   finalization, daily learning, and promotion gates.
5. Mark any legacy run that lacks executable friction modeling as
   paper-no-fee, not profitable live evidence.

- [x] Add Weather taker fee configuration with provenance and effective date.
- [x] Add depth-aware taker fill simulation using captured order book data.
- [x] Add fee/slippage/net fields to taker scoring and strategy summaries.
- [x] Add tests showing a pre-fee-positive strategy can fail after executable
  friction.

Acceptance: taker reports and promotion gates use after-fee,
after-slippage, executable-depth net PnL, or explicitly mark the run as
paper-no-fee evidence that cannot justify live profitability.

Follow-up hardening 2026-06-23: item 259 adds a current-run artifact verifier
that must pass before item 240 fields can support live-profitability or
promotion evidence.

Related: items 202, 214, 234, 237, 238, 241.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

