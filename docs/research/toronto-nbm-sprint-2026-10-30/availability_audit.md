# Toronto NBM sprint: NBM availability audit and version caveat (lane L8, 2026-10-30)

These are master's conditions (1) and (2) of 2026-10-30, to be met before P0 is run or reported. The audit
reads inputs only: NBM manifests and blocks. It recomputes no statistic, and it opens no dev price or
outcome.

## 1. Method: a per-cycle issuance receipt

- **Receipt:** each NBP and NBH object's S3 `LastModified` on the NOAA NBM open-data bucket
  (`noaa-nbm-grib2-pds`, key `blend.YYYYMMDD/CC/text/blend_nb{p,h}tx.tCCz`), as recorded in the corpus
  manifests' `last_modified`.
  - `LastModified` is when the current object version was written. It is therefore an upper bound on first
    availability, which makes the gate conservative.
  - No documented-latency assumption is used.
- **Rule:** a cycle is usable at local hour h of day D iff issued <= `LastModified` <= t(h).
  - Hour h means h:00 America/Toronto in the history frame, and the capture instant t_c on dev.
  - `issued` is the cycle time parsed from the block header (NBH) or from the parser (NBP).
- **Enforcement:**
  - The S2 history frame (`C:\t\l8tor\s2.py`, the `build()` used by the S2 gate) already selected only
    cycles with `LastModified` <= t(h).
  - The P0 driver applies the same rule at t_c to the dev NBP (L14 corpus) and the dev NBH
    (`C:\t\l12\nbs_nbh_2026dev`).
  - The audit re-derives, for every row, the exact NBP cycle (newest, and 07Z) and the NBH cycle that row
    used, and checks the rule independently.
- **Block integrity:** every block sha256 is verified against its manifest by the loaders.

## 2. Result: PASS, no cycle excluded

| Item | Value |
| --- | --- |
| Audit script | `C:\t\l8tor\avail_audit.py` sha256 `b464abd32eec983021e49d4341101c12115ca49a251b09e9ac5b62425a430a8f` (run directly: light, under 1 min) |
| Receipt | `C:\t\l8tor\avail_out\receipt.json` sha256 `a1cfa0f17ede1b3513ed83020258d06e482424edc3e57e5825902ad42044f0ca` |
| Per-row audit | `avail_out\rows.jsonl` (sha in the receipt), one row per frame row with its cycles and receipts |
| History frame rows (Aug-Sep 2021-25, hours 07-16) | 3,049 |
| Rows where any used cycle fails issued <= `LastModified` <= t(h) | **0** |
| NBP cycle used (newest received by t) | 07Z on every row |
| NBP 07Z receipt latency, by year (median, min-max, minutes) | 2021 93.7 (87.6-113.7); 2022 98.5 (93.2-283.7); 2023 90.7 (86.5-123.8); 2024 59.0 (52.9-67.2); 2025 62.8 (59.5-74.6) |
| NBH receipt latency, all used cycles | 35.4-109.9 min after issue; per-cycle medians 38.7-109.9 |
| Dev NBH (992 cycles, 07-30..09-29) | 35.4-650.3 min, median 42.1 |
| Dev NBP (248 cycles) | 61.0-804.2 min, median 74.0; no negative latency |

- **Not backfills:** the latencies match operational dissemination in every year, so none is a later
  re-upload, and no `LastModified` precedes its cycle.
- **The gate binds on time, not on availability:** a later receipt would only remove a cycle.
- **Not used:** the history frame dropped 1 day-hour for no 07Z by t. NBS values are not used by either arm.

## 3. Version caveat: NBM V4.x in training, V5.0 on dev

Both arms are trained on NBM V4.x text guidance and served on NBM V5.0.

| Data | NBM version (from block headers) |
| --- | --- |
| 2021 training | V4.0 (610 rows) |
| 2022 training | V4.0 (609 rows) |
| 2023 training | V4.1 (610 rows) |
| 2024 training | V4.2 (610 rows) |
| 2025 training | V4.3 (610 rows) |
| Dev window (2026-07-30..09-29), all 992 NBH cycles | V5.0 |

- No V5.0 data exists in training. The S2 pass therefore shows the residual model's value on V4.x guidance
  only.
- A change in V5.0's bias, spread (TXNSD) or hourly TMP behaviour is not corrected. It would surface in P0
  as a miscalibrated c.
- Neither a pass nor a kill on dev separates "the information has no value" from "the model does not
  transfer to V5.0".
- This caveat binds the P0 and w-gate readings and any forward use.
