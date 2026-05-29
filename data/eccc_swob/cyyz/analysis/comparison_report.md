# ECCC SWOB vs Wunderground Daily High Comparison

Generated at UTC: `2026-05-28T18:06:02.772762+00:00`

## Scope

- Station: `CYYZ` (Toronto Pearson International)
- Target window: `05-28 +/- 7 days`
- Minimum SWOB rows per scored day: `18`
- SWOB daily high proxy: max of air temperature and SWOB rolling one-hour max.
- WU source: daily summary, with snapshot `wu_history_high_c` overriding stale or missing current-day summaries when higher.

## Overall Metrics

| Metric | Value |
| :--- | :--- |
| Days compared | 2 |
| Mean bias (SWOB - WU) | 0.30 C |
| Mean absolute error | 0.30 C |
| Exact bucket match rate | 100.0% |
| SWOB exceeds WU rate | 100.0% |
| SWOB misses WU rate | 0.0% |
| SWOB reaches WU final high rate | 100.0% |
| Lead timing sample | 1 days |
| Mean lead minutes | 180.00 |
| Median lead minutes | 180.00 |

## Bucket Differences

| Bucket diff (SWOB - WU) | Count |
| :--- | ---: |
| +0 | 2 |

## Interpretation

SWOB is currently above WU on the matched sample (exceeds 100.0%, misses 0.0%). Across 1 rows with timing, SWOB first reached the WU final high 180.0 minutes before WU's first max timestamp on average.

## Matched Days

| Date | SWOB Max | WU High | Diff | Buckets | SWOB First Reach | WU First Max | Lead Minutes | WU Source |
| :--- | ---: | ---: | ---: | :--- | :--- | :--- | ---: | :--- |
| 2026-05-26 | 28.2 C | 28.0 C | +0.2 C | 28/28 | 15:00 | 18:00 | 180 | wu_daily_summary |
| 2026-05-27 | 25.4 C | 25.0 C | +0.4 C | 25/25 | 16:00 |  |  | snapshot_history_high |
