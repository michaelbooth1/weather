# Model Live Review - 2026-06-16

Generated from local artifacts on 2026-06-16. This is an intraday/live-forward
review, not settled scoring. June 16 settlement ledgers were not yet finalized
when this audit was run.

## Scope

Reviewed the 12 active tracked high-temperature model locations with June 16
snapshot folders:

- Toronto
- NYC
- Atlanta
- Austin
- Chicago
- Dallas
- Denver
- Houston
- Los Angeles
- Miami
- San Francisco
- Seattle

`config/locations.json` contains a broader location registry, but these 12 are
the locations with active June 16 model tapes and market-making coverage in the
current worktree.

Primary evidence:

- `data/snapshots/highest-temperature-in-*-on-june-16-2026/snapshots_long.csv`
- `data/snapshots/highest-temperature-in-*-on-june-16-2026/features_long.csv`
- `data/snapshots/highest-temperature-in-*-on-june-16-2026/source_status_long.csv`
- `data/snapshots/loop_status.json`
- `data/snapshots/observation_trigger_status.json`
- `data/mm_runs/2026-06-16/20260616T141313690630Z/run_report.md`
- `data/backtest/f_family_promotion_refresh_report.md`
- `data/backtest/location_trust.json`

Latest reviewed snapshot window: about `2026-06-16T20:45Z` to
`2026-06-16T20:46Z`.

## Executive Summary

The model had a usable intraday read in all 12 active locations, but the day
does not count as clean live-forward trading evidence because the market-making
preflight gate was stale and emitted no live-trade permission rows.

On forecast behavior, the model's top band had not been exceeded in any active
location at the latest reviewed snapshot. Seven of 12 locations were already
inside the model top band based on high-so-far: Toronto, Atlanta, Austin,
Chicago, Denver, Houston, and Miami. The five watch locations were NYC, Dallas,
Los Angeles, San Francisco, and Seattle, where the model top band was still
above high-so-far and required another 1 to 2 degrees.

Against market prices, model and market agreed on the top band in 8 of 12
locations. The four top-band disagreements were NYC, Dallas, Denver, and San
Francisco.

Source health was the main operational weakness. Open-Meteo and Open-Meteo
multimodel failed across the US markets in the latest source-status rows, and
Toronto had Open-Meteo plus ECCC GEM/SWOB failures. Core observations and other
forecast sources still kept model rows available, but the source failures reduce
confidence in model-market disagreement on a live trading day.

## Location Table

| Location | High so far | Forecast high | Model top | Model p | Market top | Market p | Read |
| :--- | ---: | ---: | :--- | ---: | :--- | ---: | :--- |
| Toronto | 24 C | 22.1 C | 24 C | 79.6% | 24 C | 98.8% | Correct band so far; market much more confident. |
| NYC | 77 F | 77.1 F | 78-79 F | 65.1% | 76-77 F | 66.0% | Watch: model is one bin warmer than current high and market. |
| Atlanta | 73 F | 73 F | 72-73 F | 62.7% | 72-73 F | 94.2% | Correct band so far; model underconfident versus market. |
| Austin | 90 F | 88 F | 90-91 F | 84.9% | 90-91 F | 90.2% | Correct band so far. |
| Chicago | 76 F | 74 F | 76-77 F | 99.9% | 76-77 F | 97.5% | Strong intraday lock-in. |
| Dallas | 89 F | 90 F | 90-91 F | 43.0% | 88-89 F | 53.0% | Watch: model needs one more degree; low trust score. |
| Denver | 90 F | 91 F | 90-91 F | 50.7% | 92-93 F | 43.5% | Model is cooler than market and currently in-band. |
| Houston | 81 F | 81 F | 80-81 F | 78.8% | 80-81 F | 55.5% | Correct band so far; model materially stronger than market. |
| Los Angeles | 69 F | 71 F | 70-71 F | 38.2% | 70-71 F | 61.5% | Watch: same top as market but model is underconfident. |
| Miami | 94 F | 92 F | 94-95 F | 99.99% | 94-95 F | 98.6% | Strong intraday lock-in. |
| San Francisco | 71 F | 72 F | 72-73 F | 47.7% | 70-71 F | 64.5% | Largest disagreement; model needs one more degree. |
| Seattle | 72 F | 74 F | 74-75 F | 59.0% | 74-75 F | 44.5% | Watch: top band needs two more degrees. |

## Source Health

Latest source-status rows showed:

- US markets: `open_meteo` and `open_meteo_multimodel` failed, consistent with
  rate-limit pressure.
- Toronto: `open_meteo`, `eccc_gem`, and `eccc_swob` failed in the latest
  source-status rows.
- The snapshot loop still wrote all 12 markets around the latest reviewed
  window, and most markets had 9 or 10 fresh sources out of 11 or 12 total
  source rows.

This creates a specific risk: late-day one-bin disagreements may look like model
edge, but the model is operating with degraded independent forecast-source
redundancy.

## Trading Readiness

The latest reviewed market-making report for run
`20260616T141313690630Z` showed:

- Preflight status: `STALE`
- Latest-tick quote rows: `0`
- Latest-tick no-quote rows: `132`
- Live-trade permission rows: `0`
- Counts toward live-forward gate: `false`
- All 12 markets failed preflight at that report point.

The observation-trigger status later showed a running watcher with fresh
heartbeat, but trade permission remained false. The active-day evidence is
therefore useful for model review, but should not be promoted as clean
live-forward trading evidence.

## Historical Trust Context

Promotion refresh remained `PASS_WITH_SHADOWS` with `PER_MARKET_ONLY` cutover.

Promote-ready F markets:

- Atlanta
- Denver
- Houston
- Los Angeles

Shadow F markets:

- Austin
- Chicago
- Dallas
- Miami
- NYC
- San Francisco
- Seattle

The aggregate candidate still trails market Brier in settlement-scored replay:
candidate Brier `0.0421`, current Brier `0.0436`, market Brier `0.0379`.

Location-trust context:

- Toronto: Moderate trust, score 62, 10 settled days.
- All F-family markets: Low trust, mostly score 43, 4 settled days.
- Dallas is weaker at trust score 35.
- Seattle and San Francisco have especially poor historical Brier skill versus
  market in the current small sample.

## Roadmap Items Opened

This audit opened the following roadmap items:

- `docs/roadmap/items/item-100-open-meteo-rate-limit-and-source-fallback-resilience.md`
- `docs/roadmap/items/item-101-live-forward-gate-state-reconciliation.md`
- `docs/roadmap/items/item-102-toronto-eccc-runtime-source-hardening.md`
- `docs/roadmap/items/item-103-late-day-warm-side-disagreement-casebook.md`

