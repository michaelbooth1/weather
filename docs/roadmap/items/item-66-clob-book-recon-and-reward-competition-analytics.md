# 66. CLOB Book Recon And Reward-Competition Analytics [COMPLETE 2026-06-16 - BOOK RECON LIVE]

Goal: turn the fast CLOB tape into measured harvest windows, competitor maps,
and executable-price evidence for market-making decisions.

Why this is missing: item 38 captures and models CLOB features, and item 44
scores paper fills/rewards once quote runs exist. The roadmap still needs an
owned recon layer that answers what the book itself says before policy changes:
where competition is thin, where flow is toxic, and which prices are executable
at realistic sizes.

- [x] Build a book-recon report over captured CLOB tapes: qualifying resting
  size inside the reward spread by market, band, side, hour, and day.
- [x] Measure top-of-book lifetime, quote refresh cadence, spread/depth
  turnover, executable price at configured sizes, and near-settlement depth
  collapse.
- [x] Estimate passive-flow toxicity from observed trades and book mids:
  markout of the passive side at short horizons before we risk live capital.
- [x] Re-score known-edge and promotion slices against executable book mids and
  depth, not only Gamma prices or raw market yes prices.
- [x] Track reward campaign changes, min-size/spread settings, and realized
  competitor size so harvest-mode assumptions expire automatically.
- [x] Feed recon outputs into the known-edge map, market-making policy
  parameters, and paper scoring reports with stable artifact schemas.

Acceptance: harvest windows, quote sizes, reward/rebate assumptions, and
edge-mode candidates are derived from measured CLOB competition and executable
depth, not from one-off manual observations or stale research notes.

Completion notes:

- Added `weather.market.clob_recon` and `python -m src.clob_recon` to build
  `clob_book_recon_v0.1` JSON, markdown, and slice CSV artifacts from captured
  `order_books_summary.csv`, WebSocket/trade, and price-mid tapes.
- The recon slices measure reward-qualifying depth, executable prices at
  configured sizes, top-of-book lifetime, refresh cadence, spread/depth
  turnover, near-settlement depth collapse, min-order/tick settings, and short
  passive-flow markouts.
- `mm_policy` and market-making runs now consume recon policy suggestions
  (`quote_size`, `harvest_half_spread`, `min_depth_1pct_total`) when the recon
  artifact exists, with diagnostics persisted in policy snapshots and run
  summaries.
- Paper reports include a CLOB Recon section, and known-edge map generation now
  emits measured CLOB recon permission cells.
