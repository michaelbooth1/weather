# Forecast Error Report

Generated: 2026-05-31T15:33:56.494772+00:00

## Scope

- Training rows: 552
- Daily archive rows: 296
- Settled snapshot forecast rows: 256
- Target dates: 299 (2018-05-10 to 2026-05-30)

## Component Score

Scores compare the learned forecast-error distribution to the previous point-cap proxy on exact settled buckets.

- Artifact replay learned Brier: 0.6387
- Artifact replay cap-proxy Brier: 0.7433
- Artifact replay Brier delta vs cap: 0.1046
- Artifact replay learned log loss: 1.2643
- Artifact replay cap-proxy log loss: 1.7935
- Artifact replay log-loss delta vs cap: 0.5293

## Leave-One-Year Daily Archive

- Rows: 296
- Learned Brier: 0.6417
- Cap-proxy Brier: 0.7185
- Learned log loss: 1.1919
- Cap-proxy log loss: 1.6525

## Source Error Stats

| Source | N | Bias obs-fc | MAE | RMSE | Within 1 C | |error| >= 2 C |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| eccc_citypage | 24 | -1.583 | 1.583 | 1.658 | 41.7% | 58.3% |
| open_meteo | 412 | 0.070 | 0.627 | 0.839 | 82.3% | 2.4% |
| weather_forecast | 116 | 0.448 | 0.672 | 0.991 | 89.7% | 10.3% |

## Live Use

Live inference consumes `src/forecast_error_model.json` through the `forecast_cap` component slot, so calibrated empirical weights remain compatible while the component itself becomes a learned distribution rather than a one-bucket cap proxy.
