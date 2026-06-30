# Codex Deep Model Audit - 2026-05-28

Status: fixes implemented and tests passing.

Findings fixed:

- Production feature extraction was not aligned with training cutoffs. The HGB
  and late-day paths were trained on top-of-hour historical rows, but live
  inference could use disabled paid-provider current/current-hour rows inside that hour.
  `src/toronto_model.py` now builds feature, late-day, and analog inputs from
  WU history rows at or before the active cutoff hour.
- The analog search used latest live/current observations instead of the
  cutoff-aligned state. It now compares today's cutoff features to historical
  cutoff features.
- Last-good live-source fallback had no age limit. Failed sources could keep
  same-day cached values alive indefinitely. Last-good live payloads are now
  accepted only when fetched within 90 minutes.
- Snapshot metadata fallback still named the old empirical model. The fallback
  is now updated to v0.4.7.
- `src/data_auditor.py` was hardcoded to the original May 27 target day. It now
  follows the configured/current market date by default.

Validation results:

- `pytest -q`: 37 passed.
- `python -m compileall src tests app.py`: passed.
- May 28 WU data audit: 390 target-window dates checked from 2000-2025; 4
  missing days, 1 sparse day, 0 duplicate timestamps, 0 impossible values.
- May 28 snapshot tape audit: 30 snapshots, 330 band rows, complete 11-band
  coverage, 0 duplicate snapshot-band rows, 0 missing key numeric values,
  median cadence 10.2 minutes and max gap 11.0 minutes.
- Fresh v0.4.7 live build at 2026-05-28 14:03 local used cutoff 13:00, observed
  WU/SWOB floor 19 C, top bucket 20 C at about 46.9%, with 19 C about 24.7%,
  21 C about 14.2%, and 22 C about 11.5%.

Residual risks:

- The checked-in HGB feature model remains uncalibrated. In-sample diagnostics
  are much stronger than the leave-one-out report, so the model should be
  treated as a useful signal but not a fully calibrated probability engine.
- `src/feature_model.py` still has `RUN_LOO = False`; rerunning it will not
  regenerate the validation table unless toggled.
- The feature model still omits archived forecast-max features, despite the
  roadmap spec mentioning forecast max.
- The explanation/deep-dive panel still does not expose quantitative
  contribution accounting and remains partially centered on the hardcoded
  25 C deep dive.

Follow-up live audit (2026-05-28 15:15 local):

- Root cause for exact 19 C showing near zero: ECCC SWOB reached 19.6 C and the
  model rounded that non-resolution source to a hard 20 C observed floor.
  Market rules resolve from Wunderground CYYZ history, so this was too
  aggressive. Fixed in v0.4.8: only Wunderground history can create the hard
  observed floor; SWOB is a soft station-support signal.
- Second issue found: wall clock had advanced to the 15:00 cutoff while
  Wunderground history had only printed through 14:00. The 15:00 HGB model was
  therefore being fed a stale 14:00 settlement-source state. Fixed in v0.4.9:
  feature, analog, transition, and late-day paths use the latest cutoff whose
  Wunderground history row has actually printed.
- Fresh v0.4.9 live build at 15:14 local used wall cutoff 15:00 but effective
  cutoff 13:00, observed WU floor 19 C, and assigned about 18.5% to exact
  19 C, 45.5% to 20 C, 17.7% to 21 C, and 15.6% to 22 C.
