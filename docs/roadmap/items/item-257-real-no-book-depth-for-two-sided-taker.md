# 257. Real NO-Book Depth For Two-Sided Taker [OPEN 2026-06-23 - SYNTHETIC COMPLEMENT DEPTH LIMITS SCALE]

Goal: replace synthetic NO-book complement sizing with real captured NO-token
book depth before scaling the two-sided/fade-overpriced taker arm.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-23.md`
and item 253. The two-sided arm is implemented, but its closeout notes say the
NO book is currently derived from the YES-book complement when real NO-book
fields are absent.

Why this matters: the NO-side edge is the most promising structural expansion,
but synthetic complement prices are not enough for live sizing. Real execution
needs actual NO-token best ask, displayed depth, spread, freshness, and
slippage/depth accounting.

## Design

1. Join real NO-token best bid/ask/depth into taker candidate rows from the
   CLOB microstructure capture.
2. Preserve a provenance field that distinguishes real NO-book rows from
   no-arbitrage complement rows.
3. Make live-qualification and scale-up require real NO-book depth, not
   synthetic complement depth.
4. Add settlement replay comparing YES-only, synthetic NO, and real-NO-depth
   two-sided variants.

- [ ] Add real NO-token depth fields to the taker candidate tape.
- [ ] Gate two-sided live scale on real NO-book freshness and displayed depth.
- [ ] Add replay diagnostics separating synthetic-complement fills from
  real-NO-book fills.
- [ ] Add tests for stale/missing NO-book depth and synthetic-only
  non-promotable status.

Acceptance: the two-sided taker arm can still run in paper with synthetic
complement evidence, but live promotion or size increases require real NO-token
book depth, freshness, fee, and slippage evidence.

Related: items 202, 238, 240, 241, 253, 256.
