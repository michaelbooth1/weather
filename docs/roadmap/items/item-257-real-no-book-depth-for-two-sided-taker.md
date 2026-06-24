# 257. Real NO-Book Depth For Two-Sided Taker [COMPLETE 2026-06-23 - REAL NO-BOOK DEPTH GATES LIVE]

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

- [x] Add real NO-token depth fields to the taker candidate tape.
- [x] Gate two-sided live scale on real NO-book freshness and displayed depth.
- [x] Add replay diagnostics separating synthetic-complement fills from
  real-NO-book fills.
- [x] Add tests for stale/missing NO-book depth and synthetic-only
  non-promotable status.

Acceptance: the two-sided taker arm can still run in paper with synthetic
complement evidence, but live promotion or size increases require real NO-token
book depth, freshness, fee, and slippage evidence.

Related: items 202, 238, 240, 241, 253, 256.

## Completion Evidence

Completed on 2026-06-23:

- Taker discovery now loads both YES and NO order-book outcomes, while
  market-making keeps its YES-only default loader behavior.
- Candidate/order tapes carry real NO-token best bid/ask, displayed depth,
  freshness, provenance, and real-depth eligibility fields.
- Two-sided strategy scoring records real, synthetic, stale, and missing-depth
  NO-side fill counts, and promotion gates block two-sided scale when NO fills
  lack fresh real NO-book depth.
- Coverage added for real NO-book order-tape capture, synthetic-only
  non-promotable status, stale NO-book non-promotable status, and missing-depth
  non-promotable status.

Verification:

- `python -m pytest tests\market\test_taker_bot_two_sided.py tests\market\test_taker_bot.py -q`
  passed with `59 passed, 5 subtests`.
- `python -m pytest tests\market\test_market_making_run.py -q` passed with
  `26 passed`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - REAL NO-BOOK DEPTH GATES LIVE`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

