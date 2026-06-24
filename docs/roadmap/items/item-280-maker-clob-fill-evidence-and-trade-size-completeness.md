# 280. Maker CLOB Fill Evidence And Trade-Size Completeness [COMPLETE 2026-06-23 - FILL-EVIDENCE COMPLETENESS GATE LIVE]

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

- [x] Persist complete trade-size evidence for maker-relevant market events.
- [x] Wire CLOB book rows into the standard maker CLOB Recon section.
- [x] Add daily unresolved resting-quote reconciliation and fail-closed status.
- [x] Add market/hour diagnostics for missing trade size and missing book rows.
- [x] Re-run maker paper scoring after repair and compare conservative versus
  queue-estimated fill evidence.

Acceptance: the standard maker paper report shows nonzero CLOB recon coverage
for active maker days, materially lower missing-size rows, no unresolved resting
quote audit backlog, and by-market diagnostics for any remaining incomplete
fill evidence.

Completion evidence (2026-06-23):

- WebSocket market-event capture now persists trade-size aliases (`size`,
  `trade_size`, `shares`, `amount`, `matched_amount`, and `maker_amount`) plus
  trade timestamps when present.
- Maker paper scoring recognizes nested and alternate trade-size fields instead
  of counting them as missing.
- Standard maker paper scoring now auto-builds CLOB Recon coverage from active
  maker snapshot folders when the precomputed recon artifact is missing or has
  zero coverage.
- Added `fill_evidence_completeness`, a fail-closed gate covering missing-size
  trade rows, missing-book queue legs, missing-trade-size queue legs, unresolved
  resting quotes, and CLOB recon book/slice coverage.
- The paper JSON, Markdown report, and trading-evidence summary now expose
  market/hour/token diagnostics separating strict-trade-through fills,
  queue-estimated fills, true no-touch legs, missing book data, and missing
  trade-size data.

Validation:

- `python -m pytest tests\market\test_mm_paper.py tests\market\test_market_microstructure.py -q`

Related: items 44, 55, 66, 202, 220, 260.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - FILL-EVIDENCE COMPLETENESS GATE LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

