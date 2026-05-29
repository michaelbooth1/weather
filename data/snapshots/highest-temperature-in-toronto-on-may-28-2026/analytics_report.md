# Snapshot Analytics Report

**Event:** `highest-temperature-in-toronto-on-may-28-2026`  
**Source CSV:** `data/snapshots/highest-temperature-in-toronto-on-may-28-2026/snapshots_long.csv`  
**Report Generated:** `2026-05-28 14:03:08`  
**Analyzed Snapshots:** 30 snapshots, 330 band rows, 11 bands  
**Capture Window:** `2026-05-28 08:55:13 -0400` to `2026-05-28 13:55:24 -0400` local time  
**Edge Threshold:** 5.0%

## Detailed Design

This report treats `snapshots_long.csv` as the immutable tape of model, market, and source-state observations.

- Validate schema, duplicated snapshot-band rows, expected row coverage, and capture cadence.
- Summarize each price band by model movement, market movement, edge extremes, and persistence.
- Surface latest positive and negative edges separately from historical edge episodes.
- Track realized/live weather markers alongside market snapshots so forecast and observed-temperature context stays auditable.
- Emit stable artifacts: `analytics_report.md`, `snapshots_analytics.png`, `weather_markers.png`, and `edge_heatmap.png`.

## Data Quality

| Check | Result | Detail |
| :--- | :--- | :--- |
| Required columns | PASS | All 11 required columns are present. |
| Snapshot-band coverage | PASS | 330 rows observed; 330 expected from 30 snapshots x 11 bands. |
| Duplicate snapshot-band rows | PASS | 0 |
| Missing numeric values | PASS | edge=0, market_yes=0, model_probability=0 |
| Timestamp parsing | PASS | 0 rows failed timestamp parsing. |
| Capture cadence | INFO | median 10.2m, max gap 11.0m |

## Latest Snapshot

Latest snapshot `20260528T135524-0400` was captured at `2026-05-28 13:55:24 -0400`.

| Range | Model | Market Yes | Edge | Best Bid | Best Ask | Last |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 13 C or below | 0.0% | 0.1% | -0.0% | - | 0.1% | 0.1% |
| 14 C | 0.0% | 0.1% | -0.0% | - | 0.1% | 0.2% |
| 15 C | 0.0% | 0.1% | -0.0% | - | 0.1% | 0.4% |
| 16 C | 0.0% | 0.1% | -0.0% | - | 0.1% | 0.1% |
| 17 C | 0.0% | 0.1% | -0.1% | - | 0.2% | 0.1% |
| 18 C | 0.0% | 0.3% | -0.3% | 0.1% | 0.5% | 0.1% |
| 19 C | 5.9% | 34.0% | -28.1% | 32.0% | 36.0% | 32.0% |
| 20 C | 46.8% | 49.5% | -2.7% | 48.0% | 51.0% | 50.0% |
| 21 C | 18.4% | 17.0% | +1.4% | 15.0% | 19.0% | 20.0% |
| 22 C | 24.2% | 0.9% | +23.3% | 0.9% | 1.0% | 1.2% |
| 23 C or higher | 4.7% | 0.4% | +4.3% | 0.3% | 0.6% | 0.3% |

## Weather Markers

| Marker | Latest | First | Max | Max Time | Min |
| :--- | :--- | :--- | :--- | :--- | :--- |
| WU printed high | 19.0 C | 16.0 C | 19.0 C | 13:44:57 | 16.0 C |
| Weather.com current | 20.0 C | 14.0 C | 20.0 C | 13:55:24 | 14.0 C |
| Weather.com max since 7 AM | 20.0 C | 14.0 C | 20.0 C | 13:44:57 | 14.0 C |
| ECCC SWOB max | 18.6 C | 16.9 C | 18.6 C | 13:03:30 | 16.9 C |
| Weather.com forecast max | 20.0 C | 19.0 C | 20.0 C | 13:24:01 | 19.0 C |
| Open-Meteo forecast max | 19.6 C | 20.2 C | 20.2 C | 08:55:13 | 19.5 C |
| ECCC forecast high | 22.0 C | 21.0 C | 22.0 C | 10:48:18 | 21.0 C |

## Bucket Summary

| Range | First Model | Last Model | Model Move | First Market | Last Market | Market Move | Max Edge | Min Edge | Longest +Edge | Longest Threshold Edge | Crossings |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 13 C or below | 0.0% | 0.0% | -0.0% | 0.1% | 0.1% | +0.0% | -0.0% | -0.0% | - | - | 0 |
| 14 C | 0.0% | 0.0% | -0.0% | 0.1% | 0.1% | +0.0% | -0.0% | -0.0% | - | - | 0 |
| 15 C | 0.0% | 0.0% | -0.0% | 0.1% | 0.1% | +0.0% | -0.0% | -0.0% | - | - | 0 |
| 16 C | 18.4% | 0.0% | -18.4% | 0.2% | 0.1% | -0.2% | +18.1% | -0.2% | 2 obs / 10.1m | 2 obs / 10.1m | 1 |
| 17 C | 4.5% | 0.0% | -4.5% | 2.1% | 0.1% | -1.9% | +28.9% | -0.9% | 14 obs / 134.2m | 8 obs / 72.0m | 1 |
| 18 C | 9.3% | 0.0% | -9.3% | 10.0% | 0.3% | -9.7% | +28.5% | -21.5% | 3 obs / 20.6m | 8 obs / 73.2m | 4 |
| 19 C | 27.9% | 5.9% | -22.0% | 40.5% | 34.0% | -6.5% | +16.9% | -28.1% | 5 obs / 41.4m | 6 obs / 51.9m | 8 |
| 20 C | 14.0% | 46.8% | +32.7% | 35.5% | 49.5% | +14.0% | +20.3% | -28.1% | 4 obs / 31.0m | 19 obs / 185.1m | 5 |
| 21 C | 14.0% | 18.4% | +4.4% | 13.5% | 17.0% | +3.5% | +12.2% | -8.0% | 7 obs / 61.9m | 3 obs / 21.1m | 6 |
| 22 C | 11.4% | 24.2% | +12.8% | 3.4% | 0.9% | -2.4% | +23.3% | +0.0% | 30 obs / 300.2m | 9 obs / 82.5m | 5 |
| 23 C or higher | 0.5% | 4.7% | +4.2% | 0.4% | 0.4% | +0.1% | +6.3% | -0.1% | 20 obs / 197.2m | 1 obs / 0.0m | 2 |

## Edge Episodes

| Range | Direction | Start | End | Duration | Observations | Peak Edge | Peak Time |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 17 C | positive | 09:16:12 | 10:28:10 | 72.0m | 8 | +28.9% | 10:07:35 |
| 18 C | positive | 12:32:00 | 12:42:30 | 10.5m | 2 | +28.5% | 12:42:30 |
| 20 C | negative | 08:55:13 | 11:50:17 | 175.1m | 18 | -28.1% | 10:28:10 |
| 19 C | negative | 13:13:59 | 13:55:24 | 41.4m | 5 | -28.1% | 13:55:24 |
| 22 C | positive | 13:55:24 | 13:55:24 | 0.0m | 1 | +23.3% | 13:55:24 |
| 18 C | negative | 11:50:17 | 12:21:14 | 31.0m | 4 | -21.5% | 12:00:20 |
| 20 C | positive | 13:24:01 | 13:44:57 | 20.9m | 3 | +20.3% | 13:44:57 |
| 19 C | negative | 12:32:00 | 12:42:30 | 10.5m | 2 | -20.2% | 12:32:00 |
| 22 C | positive | 10:38:13 | 11:50:17 | 72.1m | 8 | +19.5% | 11:19:38 |
| 16 C | positive | 08:55:13 | 09:05:17 | 10.1m | 2 | +18.1% | 08:55:13 |
| 20 C | negative | 12:32:00 | 13:03:30 | 31.5m | 4 | -18.0% | 12:52:31 |
| 19 C | negative | 10:07:35 | 10:28:10 | 20.6m | 3 | -17.5% | 10:07:35 |

## Threshold Crossings

| Time | Range | Direction | Previous Edge | Current Edge |
| :--- | :--- | :--- | :--- | :--- |
| 08:55:13 | 16 C | positive | - | +18.1% |
| 08:55:13 | 19 C | negative | - | -12.6% |
| 08:55:13 | 20 C | negative | - | -21.5% |
| 08:55:13 | 22 C | positive | - | +8.0% |
| 09:16:12 | 17 C | positive | +2.4% | +18.3% |
| 10:07:35 | 19 C | negative | +3.0% | -17.5% |
| 10:38:13 | 21 C | positive | +3.4% | +12.2% |
| 10:38:13 | 22 C | positive | +4.5% | +9.3% |
| 10:48:18 | 19 C | negative | +2.7% | -6.8% |
| 10:59:17 | 18 C | negative | -3.5% | -6.0% |
| 11:19:38 | 19 C | negative | -2.6% | -9.9% |
| 11:19:38 | 23 C or higher | positive | +4.1% | +5.3% |
| 11:50:17 | 18 C | negative | -3.4% | -8.4% |
| 12:00:20 | 19 C | positive | +3.2% | +13.3% |
| 12:00:20 | 20 C | positive | -14.6% | +6.8% |
| 12:00:20 | 21 C | negative | -1.9% | -6.2% |
| 12:21:14 | 20 C | positive | +2.1% | +11.3% |
| 12:32:00 | 18 C | positive | -16.5% | +24.3% |
| 12:32:00 | 19 C | negative | -2.8% | -20.2% |
| 12:32:00 | 20 C | negative | +11.3% | -10.6% |

## Charts

## Automated Takeaways

- Largest positive edge: **17 C** at +28.9%.
- Largest negative edge: **20 C** at -28.1%.
- Longest threshold episode: **20 C** (negative) for 175.1m across 18 snapshots.
- Largest market move: **20 C** moved +14.0%.
