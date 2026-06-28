# 320. Capture-Cadence Due-Boundary Tolerance For Strict-Complete Day Coverage [COMPLETE 2026-06-27 - DUE-BOUNDARY TOLERANCE LIVE]

Goal: stop the snapshot loop from systematically under-capturing at the
interval boundary, so a clean collection day can actually reach the >=80%
capture-ratio material-coverage bar (item 319) instead of structurally topping
out around ~0.74 even with zero outages.

Source: 2026-06-27 cadence investigation during the live collection watch. With
the stability fixes in place (items 307 / 320-adjacent debounce + pre-local-day
guard + capture-liveness), june-27 had no dark windows, all afternoon
settlement windows covered, and no decisive gaps - yet every one of the 12
markets graded PARTIAL with `capture_ratio` between 0.59 and 0.74, all below the
0.80 material-complete threshold. The blocker is no longer outages; it is a
structural cadence shortfall at the due boundary:

- The managed loop fires on a clean ~10.0-minute period (measured: iteration
  period median 10.0 min over a 3h window; iteration elapsed ~1 min, sleep
  ~9 min, so the loop is healthy and on-cadence).
- But per-market write cadence is ~13 min, not 10 (measured: toronto steady
  state, last 4h, median gap 13.3 min, max 20.0 min) - i.e. a meaningful
  fraction of ticks skip a market entirely, producing ~20 min gaps.
- Root cause is the due check in
  `weather.collection.snapshot_store.SnapshotStore.is_due`:
  `return last is None or now - last >= self.interval`. The threshold is exactly
  the interval with no tolerance. Because the loop period equals the snapshot
  interval (both 10 min), each tick lands right at the boundary, and sub-cycle
  timing jitter makes `now - last` fall a hair short of `interval` on a large
  share of ticks. A near-miss skips the write, so that market waits a full extra
  cycle (~20 min). Over a day this pulls effective cadence to ~13 min and
  `capture_ratio` (which assumes `expected = elapsed / interval`) to ~0.7.

Why this matters: item 319 made settled-label promotion countability a material
grade requiring `capture_ratio >= 0.80`. At a structural ~13 min cadence no day
can clear that bar on capture ratio, regardless of stability - so "first
strict/material-complete current-code day" is unreachable by cadence alone, not
because of dark windows. The afternoon settlement windows are still covered, so
the day remains usable for model-vs-market, but it never grades materially
complete on capture ratio.

Why it is not already covered: items 16/17 built the managed loop and supervisor
cadence; item 319 set the 0.80 material bar; the prior 2026-06-27 stability work
(re-adoption debounce, pre-local-day capture guard, capture-liveness alarm)
removed outage-driven gaps. None of them touch the boundary near-miss in
`is_due`: a healthy on-cadence loop still under-writes because the due predicate
has no tolerance for the loop's own jitter.

## Design

1. Add a small due tolerance to `SnapshotStore.is_due` so a market is due when
   `now - last >= interval - tolerance`, where `tolerance` is a small fraction
   of the interval (e.g. ~10%, ~60s for a 10-min interval). This absorbs the
   loop's sub-cycle jitter so an on-cadence ~10-min tick is never rejected for
   being a few seconds short, restoring a clean ~10-min per-market cadence
   without changing the nominal interval or causing cadence creep (the loop
   period still rate-limits writes to one per tick).
2. Make the tolerance a named, configurable attribute on the store (default
   derived from the interval) so it is explicit and testable, not a magic
   literal, and so the strict (zero-tolerance) behaviour remains expressible.
3. Keep `next_due_at` consistent with the new predicate for reporting.
4. Do not change `force` captures, observation/event-cadence paths, or the
   settled-label grading thresholds - this is purely the scheduled-cadence due
   boundary.

- [x] Add a configurable due tolerance to `SnapshotStore.is_due`
  (`now - last >= interval - tolerance`) defaulting to ~10% of the interval.
- [x] Keep `next_due_at` / reporting consistent with the tolerant predicate.
- [x] Add tests: a market last written just under the interval (within
  tolerance) is due; a market written well within the interval is not; the
  strict path (tolerance 0) still requires a full interval; force still bypasses.
- [x] Confirm the cadence math: with the tolerance, a 10-min loop yields a clean
  ~10-min per-market cadence and `capture_ratio` >= ~0.9 over a clean window,
  versus the ~0.7 boundary-skip baseline.

## Completion Notes

Completed on 2026-06-27.

Added `SNAPSHOT_DUE_TOLERANCE = timedelta(seconds=60)` and a `due_tolerance`
constructor argument on `weather.collection.snapshot_store.SnapshotStore`
(default 60s, i.e. ~10% of the 10-min interval; pass `timedelta(0)` for the
strict zero-tolerance behaviour). `is_due` now returns due when
`now - last >= interval - due_tolerance`, and `next_due_at` reports the matching
`last + interval - due_tolerance`. Nothing else changed: `force` captures, the
triggered/observation cadence path, and the item-319 settled-label grading
thresholds are untouched. This is purely the scheduled-capture due boundary.

Why a tolerance rather than a faster poll: `capture_snapshot` builds the model
before `maybe_write` consults `is_due`, so polling faster than the interval
would multiply wasted model builds on not-due markets. The tolerance fixes the
boundary near-miss at zero extra build cost and cannot cause cadence creep - the
loop period still rate-limits writes to one per tick, and a market written well
inside the interval is still not due.

Verification:

- `.\\venv\\Scripts\\python.exe -m pytest tests\\collection\\test_collection_robustness.py tests\\collection\\test_forecast_payload_persistence.py tests\\collection\\test_live_variant_predictions.py -q`
  - 53 passed (incl. new `test_due_tolerance_absorbs_boundary_jitter` and the
    updated `test_scheduled_due_ignores_recent_triggered_snapshot`).
- Cadence simulation of a 10-min loop with sub-cycle boundary jitter:
  strict (0s) -> `capture_ratio` 0.633 (matches the observed live 0.59-0.74
  june-27 range); tolerant (60s) -> `capture_ratio` 1.0 (loop-rate capped).

Acceptance: an on-cadence ~10-min loop tick that lands a few seconds short of
the interval boundary now writes instead of skipping, so per-market write
cadence tracks the loop period (~10 min) instead of stretching to ~13 min, and
`capture_ratio` over a clean outage-free day clears the item-319 0.80
material-coverage bar instead of structurally topping out near 0.74 - while a
market written well inside the interval is still not due, `force` still bypasses,
and the strict zero-tolerance predicate remains available. Live confirmation of
the per-market cadence will show on the next clean current-code collection day
as the loops re-adopt the change.

Related: items 16, 17, 25, 212, 305, 319.
