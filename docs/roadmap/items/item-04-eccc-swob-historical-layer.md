# 4. ECCC SWOB Historical Layer [COMPLETE]

- [x] Backfill or prospectively collect CYYZ SWOB observations.
- [x] Normalize SWOB rows into the same local format as WU history.
- [x] Compare SWOB same-day max versus WU final high by date and season.
- [x] Learn whether SWOB systematically leads, exceeds, or misses the WU settlement source.

Codex audit (2026-05-28): previous material issues resolved. The old
`src/eccc_history.py` climate CSV backfill remains separate, while
`src/eccc_swob_history.py` now owns SWOB XML collection, WU-shaped
normalization, daily settlement-proxy summaries, and SWOB/WU comparison
artifacts with lead-timing support.

Detailed design (implemented 2026-05-28):

- Keep the historical SWOB layer separate from `src/eccc_history.py`, because
  that module is an Environment Canada climate CSV backfill rather than a SWOB
  XML archive.
- Store raw SWOB XML under `data/eccc_swob/cyyz/raw/year=YYYY/month=MM/day=DD`
  with a per-day manifest recording source URL, downloaded file names, and
  fetch status.
- Normalize SWOB XML into WU-compatible local rows under
  `data/eccc_swob/cyyz/hourly/year=YYYY/month=MM/observations.jsonl`, using the
  same core fields as WU history (`station`, `obs_id`, `obs_name`,
  `valid_time_utc`, `valid_time_local`, `local_date`, `local_time`, `minute`,
  `temp_c`, `dewpoint_c`, `humidity`, `pressure`, `visibility`,
  `wind_dir_deg`, `wind_speed_kmh`, `wind_gust_kmh`, `clouds`, `condition`) and
  SWOB-specific max fields (`swob_max_1h_c`, `swob_max_6h_c`,
  `swob_max_24h_c`).
- Rebuild a stable daily summary CSV from normalized SWOB rows. The settlement
  proxy should use the maximum of observed air temperature and SWOB rolling
  one-hour max for same-day scoring, while retaining 6-hour and 24-hour maxima
  for diagnostics.
- Compare SWOB daily maxima with WU final daily highs by date and target-season
  window. Report bias, absolute error, bucket agreement, exceeds/misses, and
  lead timing: the first SWOB observation or rolling max at or above the WU
  final high compared with the first WU time at the final high.
- Provide a CLI:
  `.\venv\Scripts\python.exe -m src.eccc_swob_history fetch|rebuild|compare|run`
  so the layer can be used both prospectively for current SWOB days and later
  for any archived date still available from `dd.weather.gc.ca`.

Codex implementation status (2026-05-28): passes for the expanded item-4
scope. The SWOB layer fetched 51 raw XML observations for UTC 2026-05-26
through 2026-05-28, normalized them into 51 WU-compatible hourly rows and 3
local daily summaries, and generated
`data/eccc_swob/cyyz/analysis/comparison_report.md`, `.csv`, and `.json`.
After filtering partial local days below 18 SWOB rows, the comparison scored 2
target-window days: mean SWOB-WU bias +0.30 C, MAE 0.30 C, exact bucket match
100.0%, SWOB exceeds WU 100.0%, and one reliable lead-timing day where SWOB
first reached the WU final high 180 minutes before WU's first max timestamp.
The 2026-05-27 WU high comes from the snapshot `wu_history_high_c` override, so
that row is scored for level/bucket but not lead timing.
