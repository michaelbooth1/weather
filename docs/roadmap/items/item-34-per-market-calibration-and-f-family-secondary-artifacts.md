# 34. Per-Market Calibration And F-Family Secondary Artifacts [COMPLETE - EMPIRICAL GATED]

Goal: generalize the Toronto calibration/forecast/lag work (items 21-23) to the
F family as data accrues.

- [x] Build F-family probability-calibration, forecast-error, and settlement-lag
  artifacts once F days settle.
- [x] Per-market trust gating: serve the ML model only where trust > threshold,
  else empirical fallback.
- [x] Calibrate by cutoff hour and floor distance per family.

Acceptance: each F market is either calibrated-and-promoted or honestly
empirical, never overconfident.

Implementation result (2026-06-11): added `src.family_secondary_artifacts`,
which trains the whole F family, writes pooled family artifacts plus per-market
secondary artifacts, and emits `artifacts/manifests/f_family_secondary_artifacts.json` as the
serving gate manifest. The family-level artifacts are now:
`artifacts/calibration/probability_calibration_f_family.json` (`16,940` rows),
`artifacts/calibration/forecast_error_model_f_family.json` (`12,969` rows), and
`artifacts/calibration/settlement_lag_model_f_family.json` (`2,493` lead rows). Per-market
probability-calibration, forecast-error, and settlement-lag artifacts were also
written for all 11 F markets, with all artifact statuses `ok` in
`data/backtest/f_family_secondary_artifacts_report.md`.

Serving gate result: `TorontoHighTempModel` now loads the family manifest and
`FeatureModelMixin` suppresses feature-model serving for governed F markets
whose `serving_gate.mode` is `empirical`; `model_identity` includes the family
manifest for F replay hashes. At ship time the trust scores (`15/100`) and one
settled F day per market kept all 11 F markets honestly empirical:
`trust 15 < 25; settled_days 1 < 2`. The 2026-06-14 promotion refresh clears
that minimum day/trust gate for all F markets, promotes Atlanta and Austin in
the action report, and keeps the other nine F markets shadowed because they are
not yet better than market prices on pinned rows. Toronto is not governed by
the F manifest.

Replay evidence: `data/backtest/f_family_secondary_replay_report.md` reran the
pinned promotion corpus after the gate landed. The safety gate is intentionally
conservative and worsens one-day aggregate replay (`0.0668` replayed Brier vs
`0.0500` recorded and `0.0396` market) because the unproven F ML models are
withheld. This is the expected Item 34 tradeoff: no F market is promoted until
trust/day-count evidence supports it. The next accuracy path is accumulating
more F-family settled days, then flipping individual markets from empirical to
ML only when the manifest gate and promotion gauntlet both clear.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - EMPIRICAL GATED`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

