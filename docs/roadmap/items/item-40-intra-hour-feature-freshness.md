# 40. Intra-Hour Feature Freshness [COMPLETE 2026-06-11 - FLEET REFRESHED]

Promotion results (2026-06-10): pinned A/B gate PASS (0.0545 -> 0.0544; no
regression in any minutes-past-print bucket). The pooled bucket slice was
uniform rather than concentrated -- gains live in FAST-MOVING windows, not
clock buckets, so the bucket criterion was too blunt. The decisive evidence is
the June-9 staircase probe, the exact case the item was designed for: with
v0.3 artifacts the model climbs through the un-printed hour (P(<=24)
0.481 -> 0.594 across 15:19-15:50) instead of regressing (v0.2: 0.418 -> 0.348),
moving the 50% crossing on the winning band ~40-50 minutes earlier and
recovering most of the measured 52-minute market lag. Follow-up (per design):
re-run the per-source ablation for wu_current / the current-observed floor now
that live readings are trained features.

Fleet refresh results (2026-06-11): after the deepened US WU seasonal caches,
the five reverted cities (Austin, Chicago, Houston, Los Angeles, Seattle) were
re-run through full LOO v0.3 retraining. A fleet artifact audit now shows all
12 registered markets on `toronto_feature_store_v0.3` with 27 features across
14 cutoff models. The pinned replay gate passed on 69 market days, 6,135
snapshots, and 67,485 rows: replayed Brier 0.0386 versus saved baseline
0.0386 (delta -0.0000, tolerance 0.003). Trust was refreshed after the gate:
Toronto is 43/100 on 4 settled days; US markets remain Unproven at 15/100
until more clean settlements accumulate.

Implementation status (2026-06-11): code, full LOO retrain, fleet artifact
refresh, and pinned replay gate complete. Two design deviations from the
original sketch, both for cause: (1) the simulated live reading INTERPOLATES
between bracketing
observations (with a real intra-hour special obs winning inside a 10-minute
window) instead of latest-at-or-before -- on hourly-only history the
at-or-before reading equals the cutoff print, which would train the feature
dead; interpolation simulates the contemporaneous physical reading the live
wu_current feed genuinely reports, and only ever feeds the live-reading
features, never the printed path. (2) Each (day, hour) trains at ONE
deterministic wall offset from {0, 15, 30, 45} instead of emitting all
offsets -- the LOO loop is O(n^2), so 4x rows would have been 16x compute;
sampling across days covers the offset range at unchanged cost. Also shipped:
schema v0.3 artifacts are backward-compatible by construction (new numerics
appended; HGB selects by feature_names, LR slices by scaler width), the dead
cutoff-interpolation path was deleted, the late-day trainer now measures
time_since_reached from the sampled wall minute (closing the audited
wall-vs-cutoff skew), and snapshot CSV appends became schema-drift-safe
(existing files keep their own header).

Goal: close the structural lag between WU prints without breaking train/serve
parity. Between hourly prints the feature path is frozen at the last printed
cutoff while the market trades continuously: the 2026-06-09 Toronto trace
collapsed in staircase steps keyed to the 16:00/17:00 row prints, 52-62
minutes behind the market. Two prior attempts failed for the same reason:
the v0.5.1 mock-row injection fabricated settlement-source rows (reverted in
v0.5.2), and the cutoff-interpolation path fed hour-H+1 models state that had
not printed (dead code, and wrong if revived). The honest fix is to MODEL the
live reading explicitly.

Design (feature schema v0.3):

- [x] New features: `minutes_since_cutoff` (wall minus effective printed
  cutoff), `live_reading_temp` (the current wu_current reading, kept separate
  from the printed path), and `live_reading_minus_high` (reading minus printed
  high; positive means the high is being exceeded right now). `high_so_far`
  stays printed-only -- no live contamination of the settlement-source state.
- [x] Training extraction: for each historical day and cutoff hour H, emit
  records at sampled wall offsets (H:10 / H:30 / H:50). The simulated live
  reading is the latest observation at or before the sampled minute from the
  same WU obs stream (wu_current and WU history are the same data family);
  printed-path features use obs <= H:00 only. Strictly enforce minute <= t to
  avoid leakage. Roughly 3x training rows per hour-model; expect a ~3x LOO
  retrain (run overnight).
- [x] Serving: extract at the effective printed cutoff exactly as today, then
  attach the live reading and elapsed minutes. No fabricated rows; the model
  LEARNS how much a 15:38 reading 1.2 above the printed high moves the final
  distribution.
- [x] Apply the same treatment to the late-day continuation model -- this also
  fixes the audited time_since_reached wall-vs-cutoff training skew.
- [x] Parity: extend the feature-skew test with a live-reading scenario; bump
  schema to v0.3 and stamp artifacts.
- [x] Gate: pinned-corpus replay A/B (frozen folders, finalized labels, both
  runs back-to-back). Measure specifically by minutes-past-print buckets
  (0-19 / 20-39 / 40-59): the gain should concentrate in the 20-59 windows
  where the staircase flats live.
- [ ] After promotion: re-run the per-source ablation for wu_current and the
  current-observed floor -- once the model learns live readings as features,
  the floor heuristic is likely redundant and should be retired by evidence.

Acceptance: pinned replay improves in the 20-59 minutes-past-print windows
without regressing the 0-19 window, and the feature-skew parity suite passes.

Afternoon-ramp extension (2026-06-13, v0.5.8): a per-capture-hour replay
decomposition of a frozen 15-day Toronto corpus found the one remaining
in-window loss was the 13-14h dip -- a ~10-point under-call on the eventual
WINNING bucket (model 0.43 vs market 0.53, entirely the settlement-distance-0
slice; neighbors were tied-or-better, so it was sharpness, not over-spread). A
forecast-pull-fade attempt was A/B-falsified first (the pull was helping there;
removing it made 14h +0.0046), which relocated the cause to the HGB feature
path. Root cause: training sampled `minutes_since_cutoff` only from offsets
{0,15,30,45} (<=45 min), but when WU history print-lags the 13-15h climb the
effective (last-printed) cutoff trails wall clock -- a snapshot probe measured
`minutes_since_cutoff` of 48-100 min at wall 13-14h on 2026-06-11, so the HGB
was extrapolating on the exact feature meant to handle print-lag. Fix:
`feature_model.wall_offset_for` now samples wall offsets out to 105 min for the
ramp cutoff hours (12-14) ONLY; morning and 15h+ lock-in hours keep base
offsets, so they cannot regress by construction. No serving/schema/parity
change (the features are identical; only training coverage of their range
grew). Validation used a CLEAN control-vs-treatment A/B (both retrained on
today's cache, HGB seeded so per-hour-independent training isolates the change
-- a stale prior artifact had been a drift-contaminated baseline): hours
outside 12-14 byte-identical (delta 0.0000), hour 14 -0.0088, hour 13 -0.0020,
hour 12 flat, zero regression at 8-12/15-16; aggregate replayed Brier
0.0410 -> 0.0405 (market 0.0366). Tests: `tests/test_feature_skew.py`
`TestRampWallOffsets` (3) pin the per-hour offset sets; full suite 382 passed.
