# Agent report 2026-09-111g — correction: partial write stop after production review of PR #142

**This corrects the [111g landing report](agent-report-2026-09-111g-compress-on-close-landing.md).
That report said all four CSVs were retired and projected about 1.2 GiB/day. Both claims are wrong.
Only `snapshot_explanations_long.csv` is retired. The corrected projection is about 0.9 GiB/day with one
compress-on-close run a night.** The CI result and head SHA for the fix are in the reply that hands this
report back, because they postdate this commit.

- PR: https://github.com/michaelbooth1/weather/pull/142. Reviewed head `ca8bec01`; the CI failure was real.
- Fix commit: `7d8feaea` (`fix: keep writing CSVs that production readers still parse`).

## What production review found

1. **Tests expected three CSVs the write stop no longer wrote.** The 2026-09-26
   [storage assessment](audits/storage-value-assessment-2026-09-26.md) said `snapshots_long.csv` and
   `features_long.csv` must not be removed on their own. The instruction was: trace every reader, and where a
   production reader still needs a CSV, keep writing it rather than change the tests.
2. `tests/operations/test_cold_archive_catalog.py:295` expected an int and received `'1'`.
3. The `test_ops_script_ratchets` operating reference had drifted.

## Reader trace

Most readers are migrated. They go through `projection_io`, the common `weather.io` readers,
`discover_settled_folders` or `read_market_day_artifact`. Those readers include labels, `settled_days`, the
admissibility clock, settled-day freshness and the settlement ledger. The canonical inventory is
[snapshot projection readers](../operations/snapshot-projection-readers.md). The trace found these remaining
dependencies:

| Reader | CSV | Failure on a JSONL-only day | Path |
| --- | --- | --- | --- |
| `collection_health.snapshot_times` | snapshots | Runs `csv.DictReader` on `snapshots.jsonl`, so zero snapshots and `action_required` | Live cadence, fleet health, data-layer audit |
| `live_variant_settlement_scorecard.read_rows` | variant_predictions, snapshots | Runs `json.loads` on CSV text from `open_projection` and raises `JSONDecodeError` | daily_refresh step with a fail-on flag |
| `settled_day_root_cause` (snapshot read) | snapshots | Raw `.open` on `.jsonl`, so the day silently has no rows | daily_refresh step |
| `feature_quality_quarantine.discover_snapshot_folders` | features, snapshots | Raw glob by CSV name, so new days are silently skipped | Operator CLI |
| `SnapshotStore.backfill_feature_component_sidecars` | features | Creates a partial `features_long.csv` that shadows `features.jsonl` | `backfill-core-sidecars` CLI |
| `SnapshotStore.backfill_snapshot_explanations` | explanations | Creates a partial CSV that shadows the JSONL | `backfill-explanations` CLI |

Lesser findings:

- The cadence-quality backfill is a visible no-op.
- The research tool `measure_replay_trust_09_75a` hard-fails.
- The closed-day archive records the JSONL as raw evidence instead of building parquet for those families.

**Per-CSV verdict:**

- `snapshots_long.csv`: still needed.
- `features_long.csv`: still needed.
- `variant_predictions_long.csv`: still needed.
- `snapshot_explanations_long.csv`: **truly unread duplicate** once its backfill writer stops creating it.
  Every reader is migrated.

## What changed

- Capture writes `snapshots_long.csv`, `features_long.csv` and `variant_predictions_long.csv` again. This
  undoes that part of the write stop, and the tests for them are reverted to master's expectations.
- `snapshot_explanations_long.csv` stays retired. `backfill-explanations` now uses `append_projection`. The two
  explanation tests read through `read_csv_rows` and assert that the CSV is not created.
- `read_jsonl_tail_with_diagnostics` no longer runs canonical JSONL through the CSV projection. A native JSONL
  reader returns JSON-typed records. Only the CSV tail reader projects, and its one production caller reads
  `market_ws.jsonl`.
- `OPERATING_REFERENCE.md` is regenerated. Only constant line numbers moved.

Retiring the other three later requires fixing the readers in the table first, then a new reader trace.

## Corrected expected reclaim

The measurements are those in the landing report: the frozen 2026-08-12 mirror, 12 markets, and July/August
sizes. `snapshot_explanations_long.csv` measured 31.8 MB (Toronto) and 26.3 MB (Seattle) logical, mean
about 29 MB per market-day. Only two samples exist for this file.

| Component | Landing report | Corrected |
| --- | ---: | ---: |
| Writer switch | ~56 MB × 12 ≈ 0.63 GiB/day (four CSVs) | ~29 MB × 12 ≈ **0.32 GiB/day** (explanations only) |
| Compress on close, one run a night | ~0.6 GiB/day | ~0.6 GiB/day (unchanged) |
| **Total** | ~1.2 GiB/day | **~0.9 GiB/day** |

- At about 11 GB/day net decline, this is a small relief and not a fix.
- After 91a compresses folders aged 14 days or more, the writer switch's durable saving shrinks to the
  explanations file's compressed residual (measured 3.2x, so about 0.1 GiB/day). Its first-14-day saving is
  the full logical size.
- Landing-report production step 4 is corrected: on the first new event day, confirm that capture made no
  `snapshot_explanations_long.csv` and that `snapshot_explanations.jsonl` grows. `snapshots_long.csv` **is**
  still expected.

## Verification

- Workstation, through `scripts\ops\workstation_heavy.ps1 -Kind pytest` with `--basetemp C:\tmp\pt142`:
  **2257 passed, 4 skipped, 208 subtests passed.**
  - It covered `tests/collection`, `tests/market`, `tests/backtesting` and `tests/calibration`.
  - It covered the feature store and projection IO tests.
  - It covered these operations tests: compress-on-close, admissibility clock, cold archive catalog, ops-script
    ratchets, closed-day archive, daily refresh, freshness, storage classes, observation trigger and import
    architecture.
  - It covered these reporting tests: live-variant scorecard, root cause, data-layer audit and feature
    quarantine.
- Module-size and knowledge-structure audits: 19 passed. `agent_docs_audit`: PASS.
- Full GitHub CI on the pushed head: see the handback reply.

## What was NOT done

There was no production access and nothing was written to `data/`. There was no registration, no merge to
master, and no force-push or rebase. No new measurement was taken, so the GiB/day figures reuse the landing
report's mirror samples.
