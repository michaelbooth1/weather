# 8. Late-Day Tail Model [PARTIAL]

- [x] Learn a separate after-3 PM / after-4 PM / after-5 PM continuation model.
- [x] Condition late-day tail on sun/cloud, wind direction, and whether the current high was first reached recently.
- [x] Add forecast remaining max / forecast gap to the late-day continuation model.
- [x] Make late-day extension risk visible in the dashboard.
- [ ] Blend late-day continuation risk into the final distribution when the feature-model path is active.

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
