# 2. Intraday Model Calibration [COMPLETE]

- [x] Backtest the empirical intraday model by hour using the 652 historical May 20-June 3 target-season days.
- [x] Replace hand-picked blend weights with learned weights for: climatology, high-so-far bucket, wind regime, cloud regime, current max, and forecast cap.
- [x] Score by log loss, Brier score, top-bucket accuracy, and bucket-group accuracy.
- [x] Separate exact-bucket scoring from cumulative markets such as `29 C or higher`.

Detailed design (implemented 2026-05-28):

- Treat the empirical intraday model as a cutoff-hour ensemble with explicit
  probability components: climatology, high-so-far bucket, latest/current
  bucket, wind regime, cloud regime, and forecast cap.
- Validate with leave-one-year-out scoring so every historical day is tested
  against years other than its own.
- Optimize per-hour non-negative component weights against exact-bucket log
  loss, then report both exact-bucket and market-bin metrics.
- Score exact buckets separately from market bins by mapping buckets into
  `19 C or below`, exact `20 C` through `28 C`, and `29 C or higher`.
- Use a non-leaky historical cap proxy during calibration until the forecast
  archive has enough multi-day history; map the learned cap weight onto the
  live Weather.com/Open-Meteo/ECCC forecast cap in production.
- Write `artifacts/calibration/calibrated_weights.json` with metadata, raw and normalized
  weights, component availability, optimizer status, and metrics.
- Write `data/wunderground/cyyz/analysis/calibration_report.md` with the
  design, exact-bucket metrics, market-bin metrics, learned weights, and
  component availability.

Codex implementation status (2026-05-28): passes for the expanded item-2
scope. `src/intraday_calibration.py` now calibrates all six empirical
components, writes exact-bucket and market-bin metrics, and regenerated
`artifacts/calibration/calibrated_weights.json` plus
`data/wunderground/cyyz/analysis/calibration_report.md`. `src/toronto_model.py`
now consumes the new component-weight schema for the empirical fallback while
preserving compatibility with the previous flat weight file.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

