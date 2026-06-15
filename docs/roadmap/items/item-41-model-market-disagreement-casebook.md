# 41. Model-Market Disagreement Casebook [COMPLETE 2026-06-14 - CASEBOOK LIVE]

Goal: turn the project's repeated manual "why does the model disagree with
Polymarket?" investigations into a durable, settlement-scored learning loop.

Codebase audit finding (2026-06-13): the repo has several pieces of this, but
not the missing object. `src.snapshot_analytics` finds per-folder edge episodes,
`app.py` / `src.overview_helpers` show the latest biggest edges, `src.backtest`
scores realized edge/P&L after settlement, and promotion reports decompose
aggregate regressions. What is absent is a fleet-wide casebook that captures
large live disagreements as named cases, preserves the model/market/source/book
context that caused them, then revisits the same cases after settlement to say
who was right and why. This gap is why investigations like "model says 17% while
market says 0.1%" are still manual and easy to lose.

- [x] Build `src.disagreement_casebook` over snapshot and CLOB tapes, scanning
  all active markets for model-market disagreement episodes above configurable
  thresholds (absolute edge, market-price collapse while model stays high,
  model jump without source support, or large CLOB midpoint move).
- [x] Deduplicate contiguous snapshots into one case with start/end time,
  peak edge, market/band, model version, trust score, source freshness, WU
  printed high, live observed sources, forecast consensus/disagreement,
  explanation-driver waterfall, and CLOB spread/depth/imbalance at the peak.
- [x] After settlement, attach the ledger outcome, Brier/P&L contribution, and
  a first-pass error taxonomy: stale source, WU lag/catch-up miss, forecast
  miss, boundary/rounding error, market overreaction, market lead, model
  calibration error, or book/liquidity artifact.
- [x] Emit `data/backtest/disagreement_casebook.json`,
  `data/backtest/disagreement_casebook_report.md`, and a compact daily
  operator report of open cases needing attention.
- [x] Feed the casebook back into item 21/33/35/38 work: top recurring losing
  case types become explicit calibration/features/replay slices, and recurring
  winning case types become candidates for known-edge maps.

Acceptance: every edge over a chosen threshold has a durable case ID and every
settled case is scored as model win/loss/tie with a cause label. The report
must identify the top model-losing case families and prove that any proposed
fix improves those exact cases without regressing the broader promotion corpus.

Implementation status (2026-06-14 UTC): complete. `src.disagreement_casebook`
builds the fleet casebook from append-only `snapshots_long.csv`,
`components_long.csv`, `replay_inputs.jsonl`, `order_books_summary.csv`, and
folder/ledger settlement labels. It groups triggered rows by event, market
band, direction, and episode gap; assigns stable case IDs; attaches peak model,
market, trust, source freshness/value, driver-waterfall, CLOB, settlement,
Brier/P&L, and taxonomy context; and writes the JSON casebook, full Markdown
report, and compact operator report.

Real run:
`.\venv\Scripts\python.exe -m src.disagreement_casebook` regenerated
`data/backtest/disagreement_casebook.json`,
`data/backtest/disagreement_casebook_report.md`, and
`data/backtest/disagreement_operator_report.md` across 105 folders / 123,112
snapshot-band rows. It found 2,345 cases over all 12 markets, with 2,075
settled and 270 still open; model wins/losses/ties were 917 / 1,158 / 0.
Threshold coverage is exact: 18,427 / 18,427 threshold-crossing snapshot rows
are assigned to durable cases. Trigger counts: absolute edge 1,979,
market-price collapse while model stayed high 460, model jump without source
support 1,247, and large CLOB midpoint move 28. Top model-losing families are
now explicit feedback slices: WU lag/catch-up miss 745, stale source 153,
forecast miss 114, boundary/rounding error 83, and market lead 61. Recurring
model wins are captured as known-edge candidates; `market_overreaction` has
917 settled model wins. Every feedback slice carries case IDs and peak snapshot
refs plus the roadmap items that own the next experiment, with the gate that a
candidate fix must improve that exact slice and then pass the pinned promotion
corpus/gauntlet.

Validation:

- `.\venv\Scripts\python.exe -m pytest tests\test_disagreement_casebook.py -q`:
  3 passed.
- `.\venv\Scripts\python.exe -m compileall -q src\disagreement_casebook.py tests\test_disagreement_casebook.py`:
  passed.
- Mojibake/label check on the regenerated casebook/operator reports found no
  corrupted degree glyphs; F/C labels render as ASCII `F` / `C`.
