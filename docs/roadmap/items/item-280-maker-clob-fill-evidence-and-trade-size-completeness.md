# 280. Maker CLOB Fill Evidence And Trade-Size Completeness [OPEN 2026-06-23 - MISSING SIZE AND ZERO RECON ROWS WEAKEN FILL SCORING]

Goal: close the maker data gaps that make fill, queue, and reward estimates
less reliable than the quote-intent tape.

Source: the June 21-23 maker paper report showed `5,121` missing-size trade
rows, `84` unresolved resting quote audit rows, and a CLOB Recon section with
`0` book rows / `0` recon slices. Queue companion evidence found many fills or
misses dependent on incomplete book/trade-size data rather than durable
strict-trade-through evidence.

Why this matters: maker P&L quality depends on passive fill probability,
queue-ahead depletion, book-depth availability, and trade size. Without complete
CLOB book and trade-size evidence, the conservative fill gate stays small and
queue estimates remain useful diagnostics rather than promotion-grade evidence.

## Design

1. Ensure market WebSocket/trade capture persists trade size, price, token id,
   side, and capture timestamp for every event used by maker scoring.
2. Ensure CLOB book snapshots used by maker scoring are visible to CLOB Recon,
   with book-row counts and recon-slice counts in the standard maker report.
3. Add unresolved resting-quote lifecycle reconciliation to daily maker scoring
   so stale open quote evidence cannot accumulate silently.
4. Report missing-size rows, missing-book rows, queue-ahead misses, and
   strict-trade-through fills by market, hour, and token.
5. Use the repaired evidence to distinguish true no-touch quotes from missing
   market-data rows.

- [ ] Persist complete trade-size evidence for maker-relevant market events.
- [ ] Wire CLOB book rows into the standard maker CLOB Recon section.
- [ ] Add daily unresolved resting-quote reconciliation and fail-closed status.
- [ ] Add market/hour diagnostics for missing trade size and missing book rows.
- [ ] Re-run maker paper scoring after repair and compare conservative versus
  queue-estimated fill evidence.

Acceptance: the standard maker paper report shows nonzero CLOB recon coverage
for active maker days, materially lower missing-size rows, no unresolved resting
quote audit backlog, and by-market diagnostics for any remaining incomplete
fill evidence.

Related: items 44, 55, 66, 202, 220, 260.
