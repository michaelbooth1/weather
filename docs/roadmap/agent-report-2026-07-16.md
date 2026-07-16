# Bounded Hourly Model Performance Agent Report — 2026-07-16

## Handoff identity

- Branch: `hourly-bounded-2026-07-16`
- Worktree: `C:\Users\micha\Desktop\github\weather-hourly-bounded`
- Base `master` commit: `fe884689e202e88d6ebe31b3f72a7aaf8e16a999`
- Implementation commit: `1f5469dfe9e3481af7a3299865859ea2e550050e`
- Report commit: the follow-up commit containing this file; its final object ID
  is recorded in the operations handoff because a commit cannot contain its own
  final ID.

No merge, push, scheduler change, capture-loop action, release-state mutation,
or runtime `data/` write was performed. The main worktree was not edited. The
only `data/` access was the required read of
`data/logs/memory_commit_guard_status.json` before each verification batch.
The main worktree was clean at isolation; a final read-only status check showed
unrelated, externally appearing changes to `config/location_market_events.json`
and `config/locations.json`. They were not inspected, modified, staged, or
included here.

## What changed

The scheduled hourly driver remains available through
`weather.reporting.hourly.hourly_model_performance`, with its implementation in
`hourly_model_context.py`. It now scores and reduces one labeled market-day
folder at a time through a new bounded `HourlyMarketDayAggregation`:

- fixed sufficient-statistic accumulators retain score sums, five-bin
  reliability state, winner/loser recognition state, driver-field means, and
  snapshot-partition metrics for the overall, per-hour, regime, all-snapshot,
  and early-market views;
- remediation grids retain only Brier/log-loss sums per hour, probe, and
  parameter;
- exact distinct market-day, market, and snapshot counts spill to a temporary
  SQLite index with a bounded one-MiB page cache;
- each folder's scored rows are checkpointed and folded immediately, then the
  row list is deleted before the next folder is opened. The pandas frame inside
  `score_folder` is function-local and is already out of scope when its scored
  rows return;
- only the existing small `days` metadata records, error records, and fixed
  report outputs remain in memory across folders.

The output schema remains `hourly_model_performance_v0.3`. Fields, grouping,
gate thresholds, first-blocker ordering, countability selection, daily metadata,
and remediation output semantics are unchanged. The Stage-A resource declaration
also remains unchanged at 3,072 MiB private memory and 2,048 MiB working set.

`build_remediation_registry` accepts pre-aggregated early-market deltas from the
bounded driver while retaining its existing raw-checkpoint fallback for other
callers.

## Checkpoint-selection equivalence

`hourly_checkpoint_rows` selects the earliest timestamp for each key

`K(row) = (market_id, target_date, band, cutoff_hour)`.

Partition the scored corpus into its market-day folders. Because `market_id`
and `target_date` are components of `K`, a key-equivalence class cannot cross a
market-day boundary. Therefore the minimum-timestamp selection over the union
of all folders equals the union of the minimum-timestamp selections within
each folder. Timestamp ties also retain the same first-seen behavior because
all competitors for a key remain in the same market-day call.

Snapshot-partition aggregation is likewise local: its key is
`(market_id, target_date, snapshot_id, cutoff_hour)`, so no complete partition
crosses a market-day boundary. Partition metrics can therefore be computed and
folded before releasing that day's rows.

The regression test verifies the argument directly on three synthetic
market-days: global checkpoint selection equals concatenated per-day selection,
the earlier duplicate-hour snapshot is selected, and every materialized
overall/hour/regime/all-snapshot/remediation/early-market output matches the
streaming driver to floating-point tolerance.

## Memory regression

The driver-level `tracemalloc` regression builds fresh rows inside the mocked
folder scorer and compares 5 market-days with 50 market-days. Each day contains
all 24 hours, two snapshots per hour, and two bands (96 scored rows and 48
hourly checkpoints). It asserts the complete row counts and requires the
50-day traced peak to be no more than one MiB above the 5-day peak. This fails
if the driver restores a corpus-wide scored-row list while allowing the small
required day-metadata output to grow.

## Candidate-hourly inspection

`candidate_hourly_performance.py` is a separate research/candidate CSV driver;
it does not share `score_folder` or the scheduled hourly aggregation. It still
materializes `source_rows`, `checkpoint_rows`, and a sorted canonical copy for
the exact corpus hash. It was not rewritten in this branch: preserving its
current hash and public list-valued reader requires a separate streaming/spill
design, and it is not the failing Stage-A `hourly_model_performance` step. This
remaining unbounded candidate-only path is explicitly deferred for a focused
follow-up.

## Verification

Every batch read a live memory-guard status with `commit_percent < 70` before
launch.

- Required focused pair:
  `python -m pytest tests/reporting/test_hourly_model_performance.py tests/reporting/test_ten_minute_model_performance.py -q`
  — **13 passed** in 5.57 seconds (`commit_percent=42.6`).
- Supplemental candidate/facade and import-architecture coverage:
  `python -m pytest tests/reporting/test_candidate_hourly_performance.py tests/operations/test_import_architecture.py -q`
  — **23 passed** in 5.37 seconds (`commit_percent=41.7`).
- `python -m compileall -q src tests` — **PASS**
  (`commit_percent=42.6`).
- `python -m weather.operations.agent_docs_audit` — **PASS**
  (18 agent files and 441 Markdown files audited).
- `git diff --check` and the staged-diff check — **PASS**.

The operations master agent retains ownership of merge, runtime adoption, and
the persisted July 15 resume command beginning at
`--resume-from-step hourly_model_performance`.
