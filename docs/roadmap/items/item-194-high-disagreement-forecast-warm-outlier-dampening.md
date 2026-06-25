# 194. High-Disagreement Forecast Warm-Outlier Dampening [COMPLETE 2026-06-21 - ROBUST FORECAST SIGNAL CAP LIVE]

Goal: reduce warm-tail probability when one forecast source or model family is
an isolated high outlier during high-disagreement morning/ramp windows.

Source: the June 20 root-cause audit. At weak local `07:00-09:00` snapshots,
several markets had large forecast disagreement and model tops above the final
band. Austin showed global ensemble near `94 F` against final `88-89 F`;
Houston showed NWS/global guidance around `90-91 F` against final `84-85 F`;
Seattle showed NWS/global guidance above the final `70-71 F`; Denver had
Open-Meteo/global warm guidance above final. The model often treated these
warm sources as plausible centering support instead of discounting them as
isolated outliers.

Why this matters: forecast-source count is not the same as independent
agreement. Correlated or isolated high guidance can make the distribution look
well supported while the market and later observations are centered lower.

## Design

1. Cluster forecast sources by family and run time before computing forecast
   high, forecast disagreement, and high-tail support.
2. Add trimmed/median forecast anchors and explicit warm-outlier indicators.
3. Penalize warm-tail mass when the warm side comes from one family and the
   median/official/current path is lower.
4. Backtest by local slot and market on June 20 plus the existing settled
   corpus, with special slices for `forecast_disagreement >= 4 F`.
5. Keep raw source values for diagnostics, but make serving consume robust
   consensus features for centering.

- [x] Add clustered forecast consensus, trimmed high, and warm-outlier features.
- [x] Add high-disagreement warm-outlier rows to settled-day root-cause reports.
- [x] Implement a serving candidate that replaces raw warm-source support with robust
  consensus support in the morning/ramp windows.
- [x] Replay June 20 Austin, Houston, Seattle, Denver, and NYC weak snapshots through the root-cause detector.
- [x] Require the candidate to improve high-disagreement risk posture without
  reducing confirmed warm-winner recall.

Acceptance: high-disagreement snapshots can show whether warm-tail support is
consensus or an isolated outlier, and the serving model does not promote a warm
tail solely because one forecast family is high.

Completion note 2026-06-21: serving now computes robust/trimmed forecast highs
and warm-outlier diagnostics, scales outlier thresholds by market unit, and caps
isolated warm forecast signals toward the robust high before live-signal,
forecast-cap, and forecast-pull stages. The settled-day report flags
`HIGH_DISAGREEMENT_WARM_OUTLIER` cases and maps them back here. Focused tests
cover F-market native-unit outlier detection and the robust signal cap.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - ROBUST FORECAST SIGNAL CAP LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

