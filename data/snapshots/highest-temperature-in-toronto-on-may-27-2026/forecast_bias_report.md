# Forecast Bias And Error Report

**Snapshot folder:** `data/snapshots/highest-temperature-in-toronto-on-may-27-2026`  
**Generated:** `2026-05-27 21:58:25`  
**Archived forecast rows:** 22  
**Scored forecast rows:** 22

## Method

Rows are scored when a target date has a WU final high in `daily_summary.csv`; the latest WU history high in the snapshot tape is used when the local daily summary is missing or trails the live snapshot high.

Forecast error is `forecast temperature - WU final high`.

## By Source

| Source | Rows | Mean Error | MAE | RMSE | Bucket Accuracy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| eccc_citypage | 6 | +1.00 C | 1.00 C | 1.00 C | 0.0% |
| open_meteo | 8 | -4.78 C | 4.97 C | 6.05 C | 12.5% |
| weather_forecast | 8 | -4.38 C | 4.38 C | 5.40 C | 12.5% |

## By Source And Kind

| Source | Kind | Rows | Mean Error | MAE | RMSE | Bucket Accuracy |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| eccc_citypage | daily_high | 6 | +1.00 C | 1.00 C | 1.00 C | 0.0% |
| open_meteo | hourly | 8 | -4.78 C | 4.97 C | 6.05 C | 12.5% |
| weather_forecast | hourly | 8 | -4.38 C | 4.38 C | 5.40 C | 12.5% |

## By Horizon

| Source | Horizon | Rows | Mean Error | MAE | RMSE | Bucket Accuracy |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| eccc_citypage | unknown | 6 | +1.00 C | 1.00 C | 1.00 C | 0.0% |
| open_meteo | 0-1h | 1 | +0.80 C | 0.80 C | 0.80 C | 0.0% |
| open_meteo | 1-3h | 2 | -1.25 C | 1.25 C | 1.57 C | 50.0% |
| open_meteo | 3-6h | 3 | -5.93 C | 5.93 C | 6.11 C | 0.0% |
| open_meteo | 6h+ | 2 | -9.35 C | 9.35 C | 9.36 C | 0.0% |
| weather_forecast | 0-1h | 1 | +0.00 C | 0.00 C | 0.00 C | 100.0% |
| weather_forecast | 1-3h | 2 | -1.50 C | 1.50 C | 1.58 C | 0.0% |
| weather_forecast | 3-6h | 3 | -5.00 C | 5.00 C | 5.26 C | 0.0% |
| weather_forecast | 6h+ | 2 | -8.50 C | 8.50 C | 8.51 C | 0.0% |
