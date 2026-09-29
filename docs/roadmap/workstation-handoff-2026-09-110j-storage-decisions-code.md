# Workstation handoff 2026-09-110j — code for the owner's storage decisions 5, 6, 7 and 9

Written 2026-09-26 by the production agent. Owner, 2026-09-26: storage decisions **1-9 approved, 10 keep, 11 no**
([storage value assessment](audits/storage-value-assessment-2026-09-26.md) §4). Production executes 1, 2, 3 and 8 itself
under exact manifests and lands mission 91a (decision 4). The four decisions below need code first. Base: `master`.
Production free space is ~80 GiB and falls ~5-8 GiB/day, so order the work by bytes returned per day of effort.

Use **one branch per part** so roll-free pieces can land at any hour and roll-sensitive ones in a quiet window. For every
changed file, state roll-free or roll-sensitive (capture supervisors import it).

## Part A — registry corrections (decision 7) — `codex/storage-registry-corrections-20260926`

In `weather.operations.storage_classes` and the owning docs (`data-storage-class-contract.md`,
`data-retention-policy.md`): rotated `clob_diagnostics*` and rotated `diagnostics*` JSONL become operator logs eligible
for archive; add `fetch_fanout` receipt rows (`.claim` files older than 7 days are TTL-deletable, monthly tar.gz for the
rest); exclude WU atomic-write `*.tmp` orphans from canonical protection when the 4 proofs hold (writer PID not alive or
its start time is after the file's mtime, file older than 24 h, no open handle, the final file exists); reclassify
`forecast_history` from operator_cache to canonical; add a `maker_evidence` (88a) retention row = canonical, keep forever.
**Record the owner's 2026-09-26 replay_cache waiver:** `backtest/replay_cache` may be deleted from an owner-signed
exact-path manifest without the release reachability manifest (no release pointer exists on production). Keep
`observation_triggers` rotations protected (panel B source until 10-08 is scored).

## Part B — `order_books_long.csv.gz` twin deletion (decision 6) — `codex/order-books-long-twin-delete-20260926`

Extend `weather.operations.closed_day_projection_tiering` so a closed day older than 14 days may remove
`order_books_long.csv.gz` only when the same folder's `order_books.jsonl.gz` exists, the day is not split, and an exact
rebuild of the long table from the JSONL matches the gz byte-for-byte after decompression (or row-for-row with a stated
canonical ordering). Plan → rebuild proof → apply, with the existing lease, writer and quiescence checks, a per-night byte
budget and a receipt. Never touch the ~93 folders that have no raw JSONL. Amend `data-storage-class-contract.md:21` and
`data-retention-policy.md:270-272` in the same change. Report how many days qualify on a synthetic inventory and the
plan command production will run.

## Part C — compress-on-close at the source (decision 9) — `codex/compress-on-close-20260926`

First target: `clob_tokens.jsonl` (the largest growth, ~81 MiB/file average), then `clob_tokens.csv`. After the event
day closes and the writer has released the file, compress it (NTFS compress-and-retain via the 91a verifier, or gzip plus
reader support — pick one and prove every reader). Second: stop writing the remaining duplicate `*_long.csv` projections
(`snapshots_long`, `features_long`, variant and explanation long CSVs) **only after** listing every reader and migrating
it to the canonical JSONL; `snapshots_long.csv`/`features_long.csv` absence currently makes a day invisible to labels,
settled_days and the admissibility clock, so that migration comes first. The order-book long CSV is already off
(`config/storage_pressure.json`). Keep writer changes minimal; they are roll-sensitive.

## Part D — Drive lane extensions (decision 5) — `codex/cold-archive-lane-extensions-20260926`

Extend the verified cold-archive lane (`production_cold_archive_*`) so it can take, in this order: rotated diagnostics
(after Part A), `mm_runs` quote-intent CSVs (EF §8bb dates 07-31..08-08 stay hot), variant predictions/explanations older
than 30 days (make `discover_tapes` and `captured_input_parity_evidence` archive-aware first; confirm whether a current
event-day manifest is required and, if so, backfill it), and `price_history_raw/` (one tar per event subtree; >10k files).
Keep stage → upload → independent workstation restore within 24 h → reclaim, owner approval per campaign.

## Also (small, roll-free) — include in Part A

- The host-health watchdog reports `WeatherMarketMakingDailyRoll` and its supervisor as "unexpectedly DISABLED"; both are
  retired on purpose (paper maker retired 2026-09-25). Add them to the expected-disabled set with the decision reference.
- Document the exchange-economics re-acceptance procedure in the owning runbook: on 2026-09-26 the Stage-A
  `exchange_economics_rule_drift` step blocked the settled-day barrier because the accepted baseline dated from 06-27
  (per-market fee profiles, min size 5, rebate terms). The owner approved re-acceptance; production ran
  `python -m weather.market.exchange_economics accept --target-date <today> --acknowledge-payout-asset-conflict`
  and kept the old baseline under `data/alerts/economics-baseline-20260926/`.

## Boundaries and deliverables

Fixtures and synthetic folders only; no production data, credentials or venue calls. Tests include the repo-wide audits
(`test_schema_registry.py`, `test_import_architecture.py`, `test_agent_docs_audit.py`, `test_path_policy.py`). Push is
authorized. One report per part, `docs/roadmap/agent-report-2026-09-110j-<part>.md`, verdict first, with roll
classification and the exact production commands.
