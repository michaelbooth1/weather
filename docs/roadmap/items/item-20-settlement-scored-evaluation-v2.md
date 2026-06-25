# 20. Settlement-Scored Evaluation V2 [COMPLETE]

Goal: make every model change answer "did this beat the market?" with the same
settlement, scoring, and sample accounting.

- [x] Extend `src.backtest` to report metrics by target day, cutoff hour, and
  market-bin type (`lte`, exact, `gte`).
- [x] Add daily-first scoring that avoids treating highly correlated intraday
  snapshots as independent evidence.
- [x] Report first-entry, last-pre-close, and fixed-cutoff performance
  separately.
- [x] Add confidence calibration tables for model and market by hour and band.
- [x] Add a stable "model card" section with Brier skill score, log-loss
  delta, reliability, and P&L by threshold.
- [x] Keep old reports reproducible by recording model version, data snapshot
  paths, target dates, and settlement source.

Acceptance: a model change is not considered accuracy-improving unless item 20
shows improvement versus market prices on settled days, with the sample caveats
visible.

Detailed design (implemented 2026-05-31):

- Keep the original all-snapshot score for continuity, but no longer treat it as
  the only accuracy gate because intraday rows from the same day are correlated.
- Add a daily-first equal-day score so market days with more snapshots do not
  dominate headline Brier/log-loss metrics.
- Add one-row-per-day-band views: first-entry trade P&L, last-pre-close score
  and P&L, and fixed-cutoff score using the first available snapshot at or after
  each configured cutoff hour.
- Add grouped scoring by target date, capture/cutoff hour, and market-bin type.
- Add reliability slices for model and market probabilities overall, by capture
  hour, and by market band.
- Add a stable model-card section recording market days, all-snapshot rows,
  model versions, Brier skill, log-loss delta, and ECE.
- Add run-input metadata for reproducibility: snapshot tape path, target date,
  model version(s), snapshot count, band count, settlement bucket, settlement
  source, and settlement notes.

Codex implementation status (2026-05-31): complete for the item-20 scope.
`src/backtest.py` now produces the V2 report sections and exposes helper
functions for daily-first scoring, last-pre-close row selection, fixed-cutoff
row selection, grouped scores, and grouped reliability. `tests/test_backtest.py`
now covers cutoff/bin metadata, last-pre-close selection, fixed-cutoff
selection, daily-first equal-day scoring, and report-section generation.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_backtest.py -q`: 22 passed.
- `.\venv\Scripts\python.exe -m src.backtest data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026`: regenerated
  `data/backtest/backtest_report.md` over 3 settled-looking market days and
  1760 band rows. All-snapshot Brier skill was -1.500; daily-first Brier skill
  was -1.723. The active May 31 tape was intentionally excluded from this
  validation report because it was still the live/current market day.
- Post-item-25 coverage-aware rerun:
  `.\venv\Scripts\python.exe -m src.backtest data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026 --quality-grades complete,manual_override`
  now includes only the one clean tape, May 28, with 704 scored band rows,
  model Brier 0.0583 versus market Brier 0.0394, and Brier skill -0.478.

Follow-up now unlocked: item 21 should use the item-20 report as the gate for
probability calibration work. The current report shows the model remains
materially overconfident versus Polymarket on the small settled sample.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

