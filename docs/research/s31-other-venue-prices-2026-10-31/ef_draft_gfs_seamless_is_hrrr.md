# DRAFT for ESTABLISHED_FINDINGS (master lands; next free section after §10am at drafting)

### 10an. Open-Meteo `gfs_seamless` is HRRR over the United States inside HRRR's horizon, so "GFS" and "HRRR" from the multimodel feed are one source: L14, 2026-10-31 (docs plus the X63 probe; no data re-read)

- **Fact.** For US points, Open-Meteo's `/v1/gfs` `gfs_seamless` returns HRRR values for every hour that HRRR
  covers, and GFS after that.
  - L2's live probe measured the handover at about 57 h (register X63, probe `1081d6d7…`, master ruling
    2026-10-30: NOT A DEFECT).
  - The provider documents the design (<https://open-meteo.com/en/docs/gfs-api>, page sha256 `c88ac6fb…`). The
    API "combines them with high-resolution HRRR forecasts", "them" being NOAA GFS. High-resolution data
    exist for the United States only. A "Seamless" model combines one provider's models.
  - Captured rows agree. In row 78's `features.parquet`, `mm_gfs_seamless == mm_ncep_hrrr_conus` on 110,692 of
    110,692 rows, because the 2-day capture window keeps target hours inside the horizon.
- **Consequence.** Any test, feature or blend that lists `gfs_seamless` and `ncep_hrrr_conus` as two sources
  counts one source twice. Any CONUS read that calls `gfs_seamless` "GFS" at short lead is reading HRRR.
  - Row 78's K = 17 is effectively 16. BH recomputed from the recorded p-values (receipt `02c46630…`) still
    rejects nothing: the smallest q goes from 0.8125 to 0.7647. No verdict changes.
  - `open_meteo_gfs_high_delta` and `open_meteo_hrrr_high_delta` are duplicate columns.
  - The multimodel medians (`reference_high` fallback, run-to-run change) double-weight HRRR.
  - The range spreads (`OM-MM-SPREAD`, `open_meteo_multimodel_next_3h_spread`) are unaffected.
  - F4's `gfs_seamless` (row 9) and L4's "GFS" member (X6) are HRRR-in-horizon reads.
  - The full list is in `docs/research/s31-other-venue-prices-2026-10-31/gfs-hrrr-duplication-2026-10-31.md`.
- **Not established.** Whether Open-Meteo **Previous Runs** `gfs_seamless` history for 2021-2025 (the PIT
  training corpora) was HRRR-blended at day-1 leads, and from what date. If its composition changed over time,
  "GFS" history is a time-varying blend. That is a parity question for the owning lane.
- **Do not re-chase** the equality as a capture defect (X63).
- **Reopen if** Open-Meteo changes seamless blending, or a capture window extends past the HRRR horizon.
