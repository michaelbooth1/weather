# METAR vs. Wunderground Historical Climate Comparison

**Station:** `TORONTO PEARSON INT'L A (CYYZ)`  
**Report Generated:** `2026-05-27 15:34:39`  
**Target Window:** May 20 - June 3 (Years 1982–2025)  
**Total Days Compared:** 656

## Overall Discrepancy Statistics

| Metric | Value |
| :--- | :--- |
| Mean Temperature Bias (METAR - WU) | +0.0133 °C |
| Mean Absolute Temperature Error | 0.0239 °C |
| Exact Bucket Match Rate | 98.32% |
| Rate METAR Max > WU High | 5.34% |
| Rate METAR Max < WU High | 1.52% |

## Summary of Bucket Differences

| Bucket Difference (METAR - WU) | Count | Percentage |
| :--- | :--- | :--- |
| -1 °C | 1 | 0.15% |
| 0 °C | 645 | 98.32% |
| +1 °C | 10 | 1.52% |

## Key Findings & Research Questions

### 1. Does METAR systematically lead, exceed, or miss Wunderground?
- **Close Agreement:** The mean temperature bias is very small (**+0.013 °C**), showing strong agreement between METAR reports and Wunderground printed history. Basis risk is extremely low.

### 2. Analysis of the exact bucket match rate
- The two sources matched the exact whole-degree bucket on **98.3%** of seasonal days.
- On **1.7%** of days, they differed by at least one whole degree. This represents the 'basis risk' between METAR historical data and Wunderground history (the resolution source).

## Top 15 Largest Discrepancies

| Date | METAR Max | WU Max | Temp Diff | METAR Bucket | WU Bucket | METAR Times | WU Times |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2019-05-29 | 15.0 °C | 14.0 °C | +1.0 °C | 15 | 14 | 15:00 | 20:00 |
| 1992-05-22 | 27.7 °C | 27.0 °C | +0.7 °C | 28 | 27 | 17:00 | 15:00, 17:00 |
| 1992-05-24 | 12.7 °C | 12.0 °C | +0.7 °C | 13 | 12 | 17:00 | 17:00, 18:00, 19:00 |
| 1992-05-27 | 16.6 °C | 16.0 °C | +0.6 °C | 17 | 16 | 17:00 | 14:00, 15:00, 17:00, 18:00, 19:00 |
| 1992-06-01 | 21.6 °C | 21.0 °C | +0.6 °C | 22 | 21 | 17:00 | 15:00, 17:00, 18:00 |
| 2004-06-01 | 22.4 °C | 23.0 °C | -0.6 °C | 22 | 23 | 14:00, 15:00 | 15:00 |
| 1992-05-25 | 11.6 °C | 11.0 °C | +0.6 °C | 12 | 11 | 17:00 | 17:00, 18:00 |
| 1992-05-21 | 25.6 °C | 25.0 °C | +0.6 °C | 26 | 25 | 17:00 | 14:00, 15:00, 16:00, 17:00, 18:00, 19:00 |
| 1992-05-29 | 20.6 °C | 20.0 °C | +0.6 °C | 21 | 20 | 17:00 | 15:00, 16:00, 17:00 |
| 1987-05-25 | 16.5 °C | 16.0 °C | +0.5 °C | 17 | 16 | 14:00 | 13:00, 14:00, 15:00, 18:00 |
| 1996-05-26 | 16.5 °C | 16.0 °C | +0.5 °C | 17 | 16 | 14:00 | 13:00, 14:00, 15:00, 16:00, 17:00, 18:00 |
| 1993-06-03 | 19.4 °C | 19.0 °C | +0.4 °C | 19 | 19 | 14:00 | 13:00, 14:00, 15:00, 17:00, 18:00 |
| 2004-05-24 | 20.6 °C | 21.0 °C | -0.4 °C | 21 | 21 | 14:00 | 14:00 |
| 1993-05-31 | 15.6 °C | 16.0 °C | -0.4 °C | 16 | 16 | 14:00 | 14:00 |
| 2000-05-25 | 15.6 °C | 16.0 °C | -0.4 °C | 16 | 16 | 11:00, 14:00 | 11:00, 14:00 |
