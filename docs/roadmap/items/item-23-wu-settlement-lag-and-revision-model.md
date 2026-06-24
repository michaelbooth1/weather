# 23. WU Settlement Lag And Revision Model [COMPLETE]

Goal: learn how Wunderground history catches up to physical observations and
when non-resolution sources should move probability.

- [x] Measure lag between SWOB/METAR/Weather.com current highs and WU history
  printed highs across historical and captured days.
- [x] Estimate probability that WU will later print a bucket already observed
  by SWOB or current Weather.com.
- [x] Measure end-of-day and next-day WU revision frequency.
- [x] Replace ad-hoc soft floors with a learned catch-up probability curve.
- [x] Keep a hard floor only for WU history itself.

Acceptance: non-resolution live observations improve late-day settlement
probabilities without repeating the v0.4.8 hard-floor bug.

Codex implementation status (2026-05-31): complete for the item-23 scope.
`src/settlement_lag_model.py` now trains `artifacts/calibration/settlement_lag_model.json` and
`data/backtest/settlement_lag_report.md` from historical METAR/WU hourly rows
plus settled snapshot tapes containing SWOB and Weather.com current highs. The
artifact learns catch-up rates by source, cutoff hour, and source-minus-WU
bucket gap, and WU revision-up rates by cutoff hour. `src/toronto_model.py`
loads the artifact, and `src/model_distribution.py` uses it when SWOB leads WU:
the learned catch-up probability controls the soft-floor strength, but a
one-bucket hedge is capped at `0.30` minimum so SWOB can never become a hard
settlement floor. WU history remains the only hard floor.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_settlement_lag_model.py tests\test_live_floor.py tests\test_estimate_distribution.py -q`: 19 passed.
- `.\venv\Scripts\python.exe -m src.settlement_lag_model train data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026`: wrote
  `artifacts/calibration/settlement_lag_model.json` and
  `data/backtest/settlement_lag_report.md`.
- Training produced 9045 lag/revision rows: 369 non-resolution lead rows and
  8676 WU revision rows. Global catch-up was 63.7%; source-level rates were
  99.3% for SWOB on the tiny settled snapshot sample, 66.5% for historical
  METAR leads, and 40.9% for Weather.com current highs.
- WU revision-up rates now show the expected intraday decay: about 91.9% at
  10:00, 55.7% at 14:00, 16.3% at 16:00, and 0.3% at 20:00.
- A full-suite regression initially caught over-suppression of the WU floor
  bucket when SWOB had a high learned catch-up rate. The live hedge cap was
  added, then `.\venv\Scripts\python.exe -m pytest -q` passed with 121 tests
  and `.\venv\Scripts\python.exe -m compileall src tests` passed.

Follow-up now completed: item 24 consolidates feature generation and artifact
metadata so these new calibration, forecast-error, and lag components are
auditable from one train/serve feature path.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

