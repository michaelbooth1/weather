# 195. Ramp-Window Ordinal Centering And Warm-Tail Spread Repair [COMPLETE 2026-06-21 - RAMP WARM-TAIL DAMPENER LIVE]

Goal: improve ordinal centering during the morning-to-early-afternoon ramp,
where the final high is not locked in but current observations already rule out
some warm-tail shapes.

Source: the June 20 hourly and 10-minute audits. The `09:00-14:00` regime had
model Brier `0.0713` versus market `0.0583`, winner probability `26.1%` versus
market `37.6%`, and effective-band spread `0.97` bands wider than market.
Weak local slots included `08:00-09:10`, `12:30`, and `14:10`. Typical misses:
NYC final `82-83 F` while the model topped `84-85 F`; Chicago final
`76-77 F` while the model topped `78-79 F`; Houston final `84-85 F` while the
model topped `90-91 F`.

Why this matters: existing early-hour work focuses heavily on predawn. June 20
shows the bigger trading damage can happen after the market opens and after
some current observations exist, when the model still spreads too much mass
one to three bands warm of the eventual winner.

## Design

1. Add a ramp-window casebook keyed by local slot, forecast gap, current-high
   state, source disagreement, and winner rank gap.
2. Train a candidate ordinal-centering correction for `08:00-14:59` local that
   uses observed trajectory, time-to-forecast-peak, and forecast-source
   robustness.
3. Add a warm-tail spread penalty when current path plus robust forecast anchor
   imply the final band should remain near the market/modal cluster.
4. Evaluate by exact winner, adjacent-winner mass, Brier, log-loss, and
   taker-fill counterfactual P&L.
5. Keep this separate from market-price blending; use market prices only as a
   benchmark and quote-risk overlay.

- [x] Add ramp-window winner-rank and adjacent-mass sections to settled-day root-cause reporting.
- [x] Build a June 20 ramp-window casebook for NYC, Chicago, Houston, Seattle,
  Austin, and Toronto.
- [x] Implement a no-market serving ordinal-centering candidate for local `08:00-14:59`.
- [x] Replay the candidate through focused model and taker counterfactual
  gates.
- [x] Require improvement on warm-tail false-positive
  exposure.

Acceptance: the ramp-window candidate reduces local `08:00-14:59` winner-rank
gap and warm-tail false positives on June 20 and the broader settled corpus,
without relying on market prices as a core weather-model input.

Completion note 2026-06-21: the distribution pipeline now has a
`ramp_warm_tail_dampening` stage for local `08:00-14:00`, keyed by robust
forecast high, current/observed bucket, warm-outlier state, and high
disagreement. The stage records metadata and component snapshots when active.
The June 20 low-tail taker replay materially capped warm-tail loss, and focused
tests prove the dampener reduces mass above the robust anchor.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - RAMP WARM-TAIL DAMPENER LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

