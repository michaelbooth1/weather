# 250. Austin HGB Per-Location Requalification [COMPLETE 2026-06-22 - AUSTIN HGB FAIL-CLOSED REQUALIFICATION PACKET LIVE]

Goal: Block or shadow Austin HGB serving until the per-location artifact clears market-relative replay, exact-band replay, and live proof-packet gates.
Source: 2026-06-22 Austin weather-model disagreement audit and current calibration artifact evidence. The active Austin path concentrated `96-97F` at 85.4% while the market and independent fair value strongly favored `94-95F`; stored Austin replay already showed the artifact losing to the market baseline.
Why this matters: A location-specific artifact that already loses to market replay should not be trusted live during high-disagreement active days. The serving gate needs to fail closed at the location-artifact level, not only at broad family level.

## Design

1. Define the Austin HGB requalification packet: market-relative score, no-trade baseline, exact-band calibration, warm-tail concentration, and late-day lock-in attribution.
2. Add a fail-closed serving disposition for Austin HGB when the active artifact lacks current requalification evidence.
3. Require active-artifact evidence rather than historical-family evidence for promotion back to live serving.
4. Add shadow candidate tracking for repaired Austin artifacts so they can accumulate market-relative proof without trading authority.
5. Include the Austin disagreement case in the hard-slice replay set used by the decisive model proof packet.

- [x] Austin HGB serving disposition is `BLOCK` or `SHADOW` when active artifact evidence loses to market/no-trade baselines.
- [x] Requalification requires exact-band and settlement-distance-0 replay, not only aggregate multiclass score.
- [x] Proof packet includes the Austin 2026-06-22 disagreement snapshot as a named hard slice.
- [x] Serving logs show whether Austin is using HGB, fallback, blended, or no-trade disposition.
- [x] Repaired artifacts cannot promote without beating market-relative and settlement-scored gates on Austin-specific replay.

Acceptance: Austin HGB cannot serve live solely on broad F-family permission after failing local market-relative replay; requalification requires a fresh per-location proof packet that beats the market/no-trade baselines on the hard slices that exposed the failure.
Related: items 48, 218, 219, 224, 230, 231, 241, and 242.

## 2026-06-22 implementation

Added `weather.reporting.austin_hgb_requalification` with schema
`austin_hgb_requalification_v0.1`.

Generated artifacts:

- `data/backtest/austin_hgb_requalification.json`
- `data/backtest/austin_hgb_requalification_report.md`

Command:

```powershell
python -m weather.reporting.austin_hgb_requalification
```

Result: `PASS` as an enforcement packet with Austin HGB serving disposition
`SHADOW`. The local requalification verdict remains `BLOCK`, so Austin cannot
serve the HGB candidate live.

Current local requalification blockers:

- `local_market_replay`: Austin candidate trails market by `+0.0005`;
  requalification requires `delta_vs_market <= 0`.
- `exact_band_distance_zero_replay`: exact-band/distance-0 gate remains
  `BLOCK`; first blocker is target Brier gap `+0.0047` versus the `+0.0030`
  tolerance.
- `proof_packet_market_disposition`: the weather-only proof packet keeps
  Austin `SHADOW`.

Fail-closed serving evidence:

- The promotion allowlist now denies Austin candidate permission when the
  candidate-level cutover is `DO_NOT_CUT_OVER`.
- Austin's effective promotion state is `SHADOW`, with
  `serving_behavior=current_or_shadow` and
  `permission_behavior=current_or_harvest_only`.
- Stale Austin per-location HGB/coefs artifacts remain historical-only under
  `data/backtest/per_location_artifact_quarantine.json`.

Proof-packet hard-slice field:
`weather_only_model_proof_packet.hard_slices.austin_hgb_requalification`.
The hard slice is `austin_2026_06_22_high_disagreement`, covering the active-day
case where the HGB path concentrated `96-97F` while market and independent fair
value favored `94-95F`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22 - AUSTIN HGB FAIL-CLOSED REQUALIFICATION PACKET LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

