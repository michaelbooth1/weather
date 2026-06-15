# 1. Snapshot Analytics [CLOSED]

- [x] Build a notebook or CLI report over `data/snapshots/.../snapshots_long.csv`.
- [x] Plot model probability, market yes price, and edge over time for each bucket.
- [x] Add realized weather markers: WU printed high, Weather.com current max, ECCC SWOB max, and forecast max.
- [x] Add summary tables for max positive edge, edge persistence, market movement, and model movement.

Detailed design (implemented 2026-05-28):

- Treat `snapshots_long.csv` as an immutable snapshot tape with one row per
  snapshot per market band.
- Provide a reusable CLI:
  `.\venv\Scripts\python.exe -m src.snapshot_analytics [snapshot-folder]`,
  defaulting to all folders under `data/snapshots`.
- Validate the tape before analysis: required columns, duplicate
  snapshot/band rows, expected row coverage, missing numeric values, timestamp
  parsing, and capture cadence.
- Generate a latest-snapshot table, per-band summary table, threshold-crossing
  events, persistent edge episodes, weather-marker summary, and automated
  takeaways.
- Write stable artifacts next to the source CSV:
  `analytics_report.md`, `snapshots_analytics.png`, `weather_markers.png`, and
  `edge_heatmap.png`.
- Keep generated text ASCII-safe so temperature units do not render as mojibake
  in Markdown.

Codex implementation status (2026-05-28): passes for the expanded item-1
scope. `src/snapshot_analytics.py` now regenerates the report from the latest
`snapshots_long.csv`, validates the tape, writes persistent-edge and
threshold-crossing tables, and emits ASCII-safe Markdown plus three plots. The
May 27 artifact was regenerated over 39 snapshots and 429 band rows.
