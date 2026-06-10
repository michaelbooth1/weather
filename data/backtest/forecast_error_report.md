# Forecast Error Report

Generated: 2026-06-10T15:33:58.107089+00:00

## Scope

- Training rows: 3000
- Daily archive rows: 296
- Settled snapshot forecast rows: 2704
- Target dates: 309 (2018-05-10 to 2026-06-09)

## Component Score

Scores compare the learned forecast-error distribution to the previous point-cap proxy on exact settled buckets.

- Artifact replay learned Brier: 0.8439
- Artifact replay cap-proxy Brier: 0.8472
- Artifact replay Brier delta vs cap: 0.0033
- Artifact replay learned log loss: 2.1547
- Artifact replay cap-proxy log loss: 2.7763
- Artifact replay log-loss delta vs cap: 0.6215

## Leave-One-Year Daily Archive

- Rows: 296
- Learned Brier: 0.8354
- Cap-proxy Brier: 0.7185
- Learned log loss: 1.9860
- Cap-proxy log loss: 1.6525

## Source Error Stats

| Source | N | Bias obs-fc | MAE | RMSE | Within 1 C | |error| >= 2 C |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| eccc_citypage | 170 | -1.406 | 1.406 | 1.893 | 52.9% | 47.1% |
| open_meteo | 1558 | 0.957 | 1.601 | 2.488 | 53.1% | 25.7% |
| weather_forecast | 1272 | 1.019 | 1.303 | 2.166 | 74.7% | 25.3% |

## Live Use

Live inference consumes `src/forecast_error_model.json` through the `forecast_cap` component slot, so calibrated empirical weights remain compatible while the component itself becomes a learned distribution rather than a one-bucket cap proxy.
