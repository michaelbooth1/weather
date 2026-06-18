# 121. Market-Making Tape Encoding And CSV Read Robustness [COMPLETE 2026-06-18 - ROBUST CSV READER LIVE]

Goal: make market-making rollups tolerant of existing tape encoding while
enforcing UTF-8 output for new market/CLOB artifacts.

Source: the 2026-06-17 review found two crashes in
`data/mm_runs/daily_roll_console.log` while reading
`order_books_summary.csv`: `UnicodeDecodeError: 'utf-8' codec can't decode byte
0xb0 in position 802`. Both crashes occurred inside the market-making run path
while building preflight/book-tape evidence. The same log later shows
post-settlement MM runs for 2026-06-16 and 2026-06-17 completing only as
0-quote, preflight-WARN runs.

Why this matters: CLOB/book tapes are high-value live-forward evidence. A
single non-UTF-8 degree symbol or legacy artifact should not crash the rollup,
and new writers should not produce ambiguous encodings that downstream readers
cannot parse.

## Design

1. Centralize CSV reading for market-making and CLOB artifacts through a helper
   that handles UTF-8 with BOM and quarantines legacy non-UTF-8 rows with clear
   provenance.
2. Ensure all new CLOB/book summary writers emit UTF-8 and normalize temperature
   symbols or labels before writing CSV.
3. Add preflight diagnostics that report encoding quarantine counts instead of
   crashing the whole run.
4. Add a one-time repair/audit command for existing `order_books_summary.csv`
   files that contain non-UTF-8 bytes.
5. Include the encoding status in market-making daily roll reports.

- [x] Add regression coverage with an `order_books_summary.csv` containing byte
  `0xb0`.
- [x] Route market-making CSV reads through a robust reader that reports
  encoding issues explicitly.
- [x] Normalize or escape degree-symbol labels in new market/CLOB CSV writers.
- [x] Add an audit/repair command for legacy non-UTF-8 market-making tapes.
- [x] Make daily roll status distinguish "no quotes because gates blocked" from
  "no quotes because rollup crashed before scoring".

Acceptance: market-making daily roll can read or quarantine legacy non-UTF-8
book summary rows without a traceback, and new artifacts are written in a
single documented encoding.

## Completion Notes

Added UTF-8-first CSV helpers in `weather.io` with CP1252/Latin-1 fallback,
per-row encoding provenance, and diagnostic counts. Market-making run support,
CLOB feature generation, recon, paper scoring, policy loading, dashboard reads,
and data-layer audit reads now use the shared path. CLOB/MM writers normalize
degree-symbol labels while writing UTF-8. Added
`weather.operations.market_making_tape_encoding` for audit/repair of legacy
CSV tapes. Market-making run summaries now include `quote_outcome` so zero
quotes caused by preflight gates are distinguishable from missing scoring
output.

Verification:
`python -m pytest tests/market/test_market_making_csv_encoding.py tests/market/test_market_making_run.py tests/market/test_clob_recon.py tests/market/test_mm_paper.py tests/market/test_mm_policy.py tests/operations/test_market_making_daily_roll.py -q`
