# 25. Market-Day Data Collection And Label Quality [COMPLETE]

Goal: build the dataset that makes items 20 and 21 statistically meaningful.

- [x] Keep collecting complete 10-minute market/model/forecast tapes for every
  Toronto market day.
- [x] Add a daily settlement finalization command that freezes WU final high,
  settlement bucket, and evidence source after the market resolves.
- [x] Add collection-quality grades per day: complete, partial, stale-source,
  missing settlement, or manually overridden.
- [x] Surface quality grades in the item-20 backtest report.
- [x] Exclude or downweight partial days in model-vs-market metrics.
- [x] Backfill or manually reconcile known sparse settlement days where possible.

Acceptance: the backtest dataset grows by clean market days, not just by more
correlated intraday rows.

Codex implementation status (2026-06-01): complete for the code and operating
policy. Settlement-label finalization, coverage-aware grading, strict backtest
filtering, and live coverage monitoring are in place.
`src/market_day_labels.py` now provides
`python -m src.market_day_labels finalize`, writes per-folder `settlement.json`
files, and writes `data/backtest/market_day_labels.csv` with settlement bucket,
source, snapshot count, band count, row count, quality grade, quality reason,
coverage-clean flag, capture ratio, max gap, and coverage reason. It
distinguishes `complete`, `partial`, `stale_source`, `manual_override`,
`missing_tape`, and `missing_settlement`, and uses `src.collection_health` to
mark days partial when the decisive afternoon window is not covered or the tape
has large gaps. `src.backtest` reads `settlement.json` when present, includes
the quality grade in the Run Inputs And Settlement table, and supports
`--quality-grades` to include only accepted-quality market days in headline
metrics. `src.collection_health` now has a live mode and strict machine-readable
output so the same coverage policy can be checked before a day is already lost:
`python -m src.collection_health --live --strict --json <snapshot-folder>`.
`src.snapshot_tracker --status` now includes the active market day's collection
state alongside heartbeat health. On 2026-06-01 at 10:00 local, the live June 1
tape reported `COLLECTING` with no action required rather than a false
completed-day warning. May 27 and May 30 remain explicitly reconciled as
`partial`; their missing intraday coverage cannot be backfilled honestly, so
they stay out of strict headline metrics.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_market_day_labels.py tests\test_collection_robustness.py -q`: 21 passed after live collection status was added.
- `.\venv\Scripts\python.exe -m pytest tests\test_market_day_labels.py tests\test_backtest.py -q`: 26 passed.
- `.\venv\Scripts\python.exe -m src.market_day_labels finalize data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026`: wrote 3 labels, now `complete=1, partial=2`. May 27 is partial because the tape starts at 14:35, and May 30 is partial because it has a 74-minute collection gap.
- `.\venv\Scripts\python.exe -m src.backtest data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026 --quality-grades complete,manual_override`: regenerated
  `data/backtest/backtest_report.md` with quality grades and an explicit
  `complete, manual_override` quality filter. The strict headline sample now
  includes only May 28: 704 scored band rows, model Brier 0.0583 versus market
  Brier 0.0394, Brier skill -0.478.
- `.\venv\Scripts\python.exe -m src.collection_health --live data\snapshots\highest-temperature-in-toronto-on-june-1-2026`: reported June 1 as `COLLECTING`.
- `.\venv\Scripts\python.exe -m src.snapshot_tracker --status`: reported loop
  state `RUNNING` and collection state `COLLECTING`.
- `.\venv\Scripts\python.exe -m pytest -q`: 141 passed.
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.

Follow-up now completed: item 26 uses the clean/partial labels as a hard gate
for ensemble and ablation research, and includes a fast sampled research mode
so model comparisons do not require multi-hour full leave-one-out retrains.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

