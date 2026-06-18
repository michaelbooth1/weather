# 109. Settled-Day Replay Status Artifact Backfill [COMPLETE 2026-06-17 - REPAIR COMMAND LIVE]

Goal: close the training-ready artifact gap by regenerating or deriving
`replay_input_status_long.csv` for settled snapshot folders.

Source: 2026-06-16 settled-day audit. All 12 June 16 market snapshot folders
had settlement labels and core artifacts, but all 12 were missing
`replay_input_status_long.csv`. The data-layer audit failed the
`snapshot_artifact_replay_input_status` gate because only 117 of 141
training-ready folders had that artifact.

Why this matters: the system can have enough settled labels to learn from a
day while still failing the training gate because a derived status artifact is
missing. That turns useful settled days into manual repair work and blocks
daily learning even when the raw replay input exists.

## Design

1. Build a deterministic backfill that reads each folder's `replay_inputs.jsonl`,
   source-status rows, and snapshot metadata, then writes
   `replay_input_status_long.csv` with the same schema as live capture.
2. Mark folders as `training_ready=false` only when the raw evidence required
   to derive the status rows is absent or internally inconsistent.
3. Add a data-layer repair command that runs after settlement finalization and
   before daily learning.
4. Include per-market counts in the repair report: folders scanned, files
   written, evaluation-only folders, and irreparable folders.
5. Add regression coverage using the June 16 pattern: labels are finalized,
   replay inputs exist, and only replay-status artifacts are missing.

- [x] Define the canonical schema for `replay_input_status_long.csv`.
- [x] Add a deterministic settled-folder backfill command.
- [x] Wire the repair into daily refresh before data-layer audit/daily learning.
- [x] Add data-layer audit evidence for derived versus live-captured status
  rows.
- [x] Add a June 16 fixture/regression test for the missing-status pattern.

Acceptance: settled folders with valid replay inputs no longer fail the
training-ready gate solely because replay-status rows were not written during
the live capture window.

## Implementation Notes

- Added `weather.operations.replay_status_backfill`, a deterministic repair
  command that scans settled/training-ready snapshot folders, reuses the
  canonical `weather.backtesting.replay.write_replay_input_status()` schema,
  and writes `replay_input_status.json` plus
  `replay_input_status_long.csv`.
- Wired the repair into `weather.operations.daily_refresh` immediately after
  settlement finalization and before promotion, data-layer audit, snapshot
  evaluation, and daily learning.
- Data-layer audit now treats `folder_status=evaluation_only` as not
  training-ready instead of letting a non-replayable folder masquerade as
  training evidence. The Markdown report also exposes replay status counts, so
  live-captured versus reconstructed evidence is visible.
- Ran the repair against the current snapshot root for `as_of=2026-06-17`.
  It wrote 24 missing status artifacts, found 0 irreparable folders, and all
  12 June 16 folders are `captured`.

## Verification

- `python -m pytest -q tests\operations\test_replay_status_backfill.py tests\operations\test_daily_refresh.py tests\reporting\test_data_layer_audit.py tests\backtesting\test_replay.py`
- `python -m weather.operations.replay_status_backfill --as-of 2026-06-17`
- `python -m weather.reporting.data_layer_audit --snapshots-root data\snapshots --backtest-root data\backtest --out data\backtest\data_layer_audit.json --report data\backtest\data_layer_audit_report.md`

Current evidence: `data/backtest/data_layer_audit_report.md` reports
`snapshot_artifact_replay_input_status` as `PASS` with `141/141`
training-ready folders and replay-status rows `captured=16431,
reconstructed=568`.
