# 124. CLOB Order-Book Retention Coverage And Storage Budget [COMPLETE 2026-06-18 - CLOB MANIFEST AUDIT LIVE]

Goal: make CLOB order-book, price-history, and websocket tapes either
explicitly backed up and restorable or explicitly classified as rebuildable,
then keep their local storage growth inside an operator-visible budget.

Source: the 2026-06-18 data-layer audit found that the latest tape backup
status was `OK`, with 2,582 backed-up files and a passing restore drill, but
the backup manifest had zero `order_books` entries. Local snapshot storage
contained 72 `order_books_long.csv` files totaling about 86.4 GB, and the
largest single-day files were already multi-GB. The current backup policy
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
2. Broaden the backup manifest and retention policy for irreplaceable CLOB
   artifacts beyond `clob*` filename patterns.
3. Add a backup status diff that reports local critical-candidate files that
   are absent from the latest manifest.
4. Add a restore drill that proves at least one order-book long table, one
   order-book raw JSONL tape, one price-history tape, and one websocket tape
   are restorable with checksums intact.
5. Define a storage budget and compaction plan for `order_books_long.csv`,
   such as compressed columnar rollups, depth-limited summaries, raw JSONL
   hash manifests, or tiered archival, without losing replay/scoring evidence.
6. Report local bytes, backed-up bytes, and excluded bytes by CLOB artifact
   class in the daily backup/status output.

- [x] Add tests that fail if a new `MarketMicrostructureStore` artifact path
  is not covered by the retention classification.
- [x] Update tape backup include/exclude rules for `order_books*`,
  `price_history*`, and `market_ws*` artifacts according to the
  irreplaceable/derived classification.
- [x] Add a manifest audit that fails `OK` status when a local irreplaceable
  CLOB artifact is missing from the backup manifest.
- [x] Add a restore-drill fixture or small real sample for order-book and
  websocket tapes.
- [x] Add daily size reporting and alert thresholds for `order_books_long.csv`
  growth.
- [x] Document the compaction/retention policy in the operator runbook.

Acceptance: the backup status cannot report `OK` while an irreplaceable CLOB
order-book, price-history, or websocket artifact exists locally but is absent
from the latest backup manifest. Restore evidence proves the artifact class is
recoverable, and the status report shows local/backed-up/excluded bytes by
CLOB artifact class.

## Completion Notes

Implemented CLOB artifact policies in `weather.operations.tape_backup` for
tokens, order-book summary, order-book long, raw order-book JSONL,
price-history, websocket, and derived CLOB feature artifacts. Backup status now
audits local critical candidates against the latest manifest and returns
`MISSING_CRITICAL_FILES` instead of `OK` when irreplaceable local CLOB tapes are
absent. Restore drills now include CLOB class evidence, and the status report
shows local, backed-up, missing, excluded, and warning bytes by CLOB artifact
class.

Current production evidence (2026-06-18): `data/backtest/tape_backup_status.json`
correctly reports `MISSING_CRITICAL_FILES`, with 312 missing critical files and
107,925,936,287 missing critical bytes. The CLOB coverage section shows
116,043,863,560 local CLOB bytes, 8,001,397,554 backed-up bytes, and 270 missing
required CLOB files. Restore-drill SLA remains `OK`, so the remaining action is
to run a backup/export that includes the newly classified CLOB tapes.

Verification:
`python -m pytest -q tests/operations/test_tape_backup.py tests/operations/test_schema_registry.py`
