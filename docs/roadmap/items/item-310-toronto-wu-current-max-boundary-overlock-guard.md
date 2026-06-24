# 310. Toronto WU Current-Max Boundary Over-Lock Guard [COMPLETE 2026-06-24 - SUPPORT-ONLY CURRENT-MAX BOUNDARY GUARD LIVE]

Goal: prevent support-only WU current-max evidence from becoming an exact-band
lock-in when the settlement source and official observations still indicate a
boundary state.

Source: the Toronto June 24, 2026 25 C audit. The latest local snapshot had
`model_probability=0.8258` for 25 C while market YES was about `0.38` to
`0.40`. The model distribution put 24/25/26 at `6.9 / 82.6 / 7.8%`, while the
market put the same adjacent bands at `30.5 / 38.0 / 29.5%`. The component tape
showed the core forecast stack near a boundary, but the live-floor path pushed
25 C toward lock-in after `wu_max_since_7am_c=25.0` even though printed WU
history was still `24.0` and official observations did not independently
confirm a settled 25 C print. The row also had
`snapshot_cadence_quality_state=gappy` and quote permission denied.

Why this matters: this is not mainly a forecast-model preference for 25 C. It
is a serving-time evidence-classification failure. A support-only current max
can be strong evidence that the final settlement bucket is at least 25 C, but
it does not determine exact 25 C until the model separately prices 26+ risk.
When that distinction is lost, the model crushes adjacent-bucket risk, trails a
market that is correctly pricing the boundary, and can turn degraded snapshots
into false high-conviction quotes.

## Design

1. Split support-only `wu_max_since_7am_c` handling into cumulative evidence
   for `final_bucket >= current_max_bucket` and exact-band allocation across the
   current and warmer adjacent buckets.
2. Price 26+ risk from forecast/error distributions, source disagreement,
   remaining heating potential, and settlement-lag evidence before assigning
   exact 25 C probability.
3. Add a conflict cap for states where WU history is one bucket lower than
   support-only current max and official observation sources do not confirm the
   higher bucket.
4. Prevent late-day lock-in, WU-floor residual, and settlement-lag adjustment
   stages from raising exact-band probability above the conflict cap in that
   state.
5. Treat `snapshot_cadence_quality_state=gappy` or denied quote permission as
   diagnostic-only for this repair: replay and report the case, but do not use
   it as high-conviction quote evidence.
6. Add a Toronto June 24, 2026 25 C regression slice and a broader
   current-max/printed-history boundary slice to the stage-attribution and
   candidate replay reports.

- [x] Add a current-max boundary classifier that distinguishes confirmed,
  support-only, conflicting, and stale current-max states.
- [x] Apply an exact-band conflict cap when printed WU history is 24 C,
  support-only current max is 25 C, and official observations do not confirm
  25 C.
- [x] Reallocate capped exact-band mass through the normal adjacent-bucket
  distribution instead of dumping it into one neighboring bucket.
- [x] Add regression coverage for the Toronto June 24, 2026 25 C snapshot and
  at least one broader historical boundary slice.
- [x] Update explanation/stage-attribution output so operators can see
  cumulative `>=25` evidence separately from exact 25 C lock-in.
- [x] Keep gappy or quote-denied snapshots excluded from aggressive quote
  permission even when the model has a large apparent edge.

Acceptance: on the Toronto June 24, 2026 25 C case, support-only
`wu_max_since_7am_c=25` can lift `P(final >= 25 C)` but cannot by itself push
exact 25 C into lock-in while WU history remains 24 C and official observations
do not confirm 25 C. Candidate replay must preserve material adjacent 24/26
risk, reduce the 25 C overconfidence versus current, pass broader boundary and
late-lock-in guardrails, and keep gappy or quote-denied rows diagnostic-only.

Related: items 59, 153, 170, 182, 200, 212, 215, 230, 232.

## Completion Notes

Completed 2026-06-24. The serving distribution now classifies support-only
current max boundary states as `confirmed`, `support_only`, `conflicting`, or
`stale`. Toronto one-bucket conflicts where WU history is lower and official
observations do not confirm the higher current-max bucket receive a final
post-calibration exact-band cap, with excess mass redistributed through the
adjacent printed-lower and warmer buckets from the normal reference shape.

The model component payload exposes `current_max_boundary`, the waterfall now
has a `Current-max boundary guard` stage, and replay reports include a
`By Current-Max Boundary` slice for broader support-only one-bucket diagnostics.
Focused tests cover the June 24-style Toronto 24/25/26 boundary state, direct
cap redistribution, official-confirmed no-op behavior, Toronto-only serving
scope, and candidate replay/report boundary slices.
