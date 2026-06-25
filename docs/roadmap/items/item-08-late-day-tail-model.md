# 8. Late-Day Tail Model [COMPLETE - CONTINUATION BLEND LIVE]

- [x] Learn a separate after-3 PM / after-4 PM / after-5 PM continuation model.
- [x] Condition late-day tail on sun/cloud, wind direction, and whether the current high was first reached recently.
- [x] Add forecast remaining max / forecast gap to the late-day continuation model.
- [x] Make late-day extension risk visible in the dashboard.
- [x] Blend late-day continuation risk into the final distribution when the feature-model path is active.

Codex audit (2026-05-28): partial. Logistic continuation models are exported
for 15:00, 16:00, and 17:00, and the dashboard has a late-day extension risk
panel. Issues found: the late-day feature set omits forecast remaining max, no
late-day validation report is generated, and the learned continuation risk is
displayed but not clearly blended into the final distribution when the feature
model path is active.

Codex update (2026-05-31): still partial. Training and live extraction share
most cutoff-aligned features, but late-day coefficients still omit
`forecast_high` / `forecast_gap`, the report does not score continuation model
calibration, and the visible risk panel is not yet an accuracy-grade
probability adjustment.

Split clarification (2026-06-14): item 22 shipped the artifact-backed
forecast-error tail blend used by live late-day continuation. The remaining
trained late-day work is narrower: put `forecast_high` / `forecast_gap` into the
late-day logistic training artifact and validate that continuation component
directly. That work is split into item 49.

Item 49 completion (2026-06-15): the trained late-day continuation artifacts now
include `forecast_high` and `forecast_gap` for all registered markets, and the
pinned settlement replay improved rather than regressed the final distribution.
The older final-distribution blend checkbox remains open as its own design
question; this update closes only the forecast-gap training/validation split.

Implementation update (2026-06-15): complete. The feature-model serving path now
calls `predict_late_day_continuation()` and blends its calibrated
`continuation_probability` into the exact distribution as an upper-tail target
(`late_day_continuation_blend`) before the existing late-day lock-in step. The
blend is intentionally gated off when live current/METAR/SWOB support already
leads the printed WU high, because the live-observed floor owns that case. The
trained continuation model therefore adjusts unresolved late-day extension risk
without double-counting non-resolution live observations.

Verification:
- `.\venv\Scripts\python.exe -m pytest tests\model\test_late_day_lockin.py tests\calibration\test_forecast_error_model.py tests\model\test_estimate_distribution.py tests\calibration\test_intraday_calibration.py -q` -> 59 passed.
- `.\venv\Scripts\python.exe -m compileall src\weather\model\model_distribution.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - CONTINUATION BLEND LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

