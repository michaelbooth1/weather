# 124. CLOB Order-Book Retention Coverage And Storage Budget [COMPLETE 2026-06-18 - CLOB MANIFEST AUDIT LIVE]

Goal: make CLOB order-book, price-history, and websocket tapes either
explicitly backed up and restorable or explicitly classified as rebuildable,
then keep their local storage growth inside an operator-visible budget.

status was `OK`, with 2,582 backed-up files and a passing verification, but
contained 72 `order_books_long.csv` files totaling about 86.4 GB, and the
covers `clob*` artifacts but misses the artifact names emitted by
`MarketMicrostructureStore`: `order_books_summary.csv`, `order_books_long.csv`,
`order_books.jsonl`, `price_history.csv`, `price_history.jsonl`,
`market_ws_events.csv`, and `market_ws.jsonl`.

Why this matters: market microstructure evidence is now part of model and
market-making analysis, but the retention gate can report healthy while the
largest and most expensive-to-recreate book tapes are not protected. Without a
storage budget or compaction policy, long-table CSV growth can also become the
dominant local disk risk.

## Design

1. Inventory every artifact path written by `MarketMicrostructureStore` and
   classify each as irreplaceable, derived, or discardable.
   artifacts beyond `clob*` filename patterns.
   are absent from the latest manifest.
4. Add a verification that proves at least one order-book long table, one
   order-book raw JSONL tape, one price-history tape, and one websocket tape
   are restorable with checksums intact.
5. Define a storage budget and compaction plan for `order_books_long.csv`,
   such as compressed columnar rollups, depth-limited summaries, raw JSONL
   hash manifests, or tiered archival, without losing replay/scoring evidence.
6. Report local bytes, backed-up bytes, and excluded bytes by CLOB artifact

- [x] Add tests that fail if a new `MarketMicrostructureStore` artifact path
  is not covered by the retention classification.
  `price_history*`, and `market_ws*` artifacts according to the
  irreplaceable/derived classification.
- [x] Add a manifest audit that fails `OK` status when a local irreplaceable
- [x] Add a verification fixture or small real sample for order-book and
  websocket tapes.
- [x] Add daily size reporting and alert thresholds for `order_books_long.csv`
  growth.
- [x] Document the compaction/retention policy in the operator runbook.

order-book, price-history, or websocket artifact exists locally but is absent
recoverable, and the status report shows local/backed-up/excluded bytes by
CLOB artifact class.

## Completion Notes

tokens, order-book summary, order-book long, raw order-book JSONL,
audits local critical candidates against the latest manifest and returns
`MISSING_CRITICAL_FILES` instead of `OK` when irreplaceable local CLOB tapes are
absent. Verifications now include CLOB class evidence, and the status report
shows local, backed-up, missing, excluded, and warning bytes by CLOB artifact
class.

Current production evidence (2026-06-19): Item 146's local cleanup and settled
is now `OK`, verification SLA is `OK`, and fleet observability reports tape
workstation-loss durability is proven.

Verification:
