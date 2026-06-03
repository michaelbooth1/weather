# Forecast Error Report

Generated: 2026-06-03T20:54:27.257757+00:00

## Scope

- Training rows: 1131
- Daily archive rows: 296
- Settled snapshot forecast rows: 835
- Target dates: 302 (2018-05-10 to 2026-06-02)

## Component Score

Scores compare the learned forecast-error distribution to the previous point-cap proxy on exact settled buckets.

- Artifact replay learned Brier: 0.7758
- Artifact replay cap-proxy Brier: 0.7540
- Artifact replay Brier delta vs cap: -0.0218
- Artifact replay learned log loss: 1.8668
- Artifact replay cap-proxy log loss: 2.1642
- Artifact replay log-loss delta vs cap: 0.2974

## Leave-One-Year Daily Archive

- Rows: 296
- Learned Brier: 0.7682
- Cap-proxy Brier: 0.7185
- Learned log loss: 1.6406
- Cap-proxy log loss: 1.6525

## Source Error Stats

| Source | N | Bias obs-fc | MAE | RMSE | Within 1 C | |error| >= 2 C |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| eccc_citypage | 55 | -1.218 | 1.218 | 1.421 | 60.0% | 40.0% |
| open_meteo | 686 | 0.514 | 0.943 | 1.686 | 75.1% | 9.8% |
| weather_forecast | 390 | 0.638 | 0.931 | 1.706 | 83.1% | 16.9% |

## Live Use

Live inference consumes `src/forecast_error_model.json` through the `forecast_cap` component slot, so calibrated empirical weights remain compatible while the component itself becomes a learned distribution rather than a one-bucket cap proxy.
