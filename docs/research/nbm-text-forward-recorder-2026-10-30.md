# NBM text forward recorder (Lane L13, 2026-10-30)

Research / shadow only. The recorder keeps a point-in-time forward record of the National Blend of Models text
bulletins for the 12 market stations. It uses free NOAA open data with no key, no credentials and no paid source. Nothing
imports it, nothing is served from it, and it reads no outcome, price or label.

## Source

- Bucket: `https://noaa-nbm-grib2-pds.s3.amazonaws.com`. Access is anonymous HTTPS.
- Object path: `blend.<YYYYMMDD>/<HH>/text/blend_<product>tx.t<HH>z`.
- NBM is issued every hour. Text bulletins appear about 40–80 minutes after the cycle.
- Products recorded:
  - **NBH**: hourly, 1–25 h.
  - **NBS**: 3-hourly, to 72 h, with TXN.
  - **NBE**: 12-hourly extended, with TXN.
  - **NBP**: probabilistic, TXN percentiles. It is not issued every hour; on 2026-10-30 it was absent at 03Z and 06Z, and still absent from 18Z at 19:58Z.
- NBE costs one more 21 MB GET per hour, so it is included.
- The NBX product is in the bucket but is not recorded.
- Each bulletin holds about 9,600 station blocks, and all 12 market stations are present in all four products. CYYZ included.
- Values are in the published units, so temperatures are in deg F at every station, CYYZ included.

## What is kept

- **One listing per open cycle.** The S3 listing `LastModified` is the true publication time. The archive keeps it, so even a catch-up fetch knows when each bulletin became available.
- **One GET per product present.** Each GET is about 21–30 MB.
- **Only the 12 station blocks are kept.** Each block is stored verbatim (`raw`) plus a fixed-width column parse:
  - Cells are 3 characters, right-aligned under the `FHR` row, or under the `UTC` row for NBH.
  - Row values are integers, with the forecast hour and valid time for each column.
  - Values past the last column, such as the NBE climatology, go to `unaligned`.
- On the 2026-10-30 12Z bulletins this parse succeeded on all 9,591 blocks of all four products.
- Raw bulletins are never written to disk.
- Product rows carry:
  - the key and listed size and ETag;
  - the response `Last-Modified` and ETag;
  - our fetch time and `fetch_lag_s`;
  - the sha256 of the bytes;
  - `backfill`: true when fetched more than 4 h after the cycle.
- Block rows repeat these, plus `issued_utc` parsed from the block's own header. It must equal the cycle, or the product is `invalid`.

## Layout and idempotence

- Output root: `C:\t\nbm_text\forward`.
- Each cycle has an append-only `<YYYYMMDD>/<HH>/nbm_text.jsonl`.
- **Write order.** A product's block rows and its `product` row are written in one fsynced append, with the `product` row last.
  - Readers trust blocks only when an ok `product` row with the same `file_sha256` follows them.
  - A torn write is simply fetched again.
- **When a cycle closes.** It gets `manifest.json` (with `rows_sha256`) when:
  - every product is ok; or
  - 4 h after the cycle, if the listing still lacks a product. That product is recorded `not_issued`. For NBP this is routine and not a gap; for the others it goes to `gaps.jsonl`.
- **Missing products.** A product that keeps failing (6 tries) is closed `missing` and logged in `gaps.jsonl`. So is one still failing at 48 h.
- **Restarts.** Closed cycles and ok products are never fetched again. On start the recorder catches up as far back as 72 h, but not before 2026-10-30 00Z.
- **Order.** Live cycles (at most 4 h old) go newest first, then catch-up cycles oldest first.
- **Guards**, as the ENS and ECCC recorders have:
  - below-normal priority;
  - 3 MB/s throttle and a 1,500 MB hourly ceiling;
  - a per-process network cap;
  - `RECORDER_PAUSE` and `STOP` files;
  - a single-instance lock;
  - a 20 GB free-disk floor;
  - a 5 GB output cap.
- **Volume.** About 2.5 GB/day downloaded and about 4 MB/day kept.

## Running

- **Dry run, one foreground cycle:** `venv\Scripts\python.exe tools\research\nbm_text_forward_recorder.py --out C:\t\nbm_text\dryrun --once-cycle 2026103018`. The dryrun output folder is separate from the live one.
- **Launcher:** `tools\research\nbm_text_forward_recorder_launch.ps1`.
  - It is WMI-detached and pinned to the recorder's git blob in `C:\wt\l13nbm`.
  - Its alive check matches `*nbm_text_forward_recorder*`.
  - It refuses when the STOP file exists, when a recorder is alive, or when the blob differs.
- **Registrar:** `tools\research\register_nbm_text_forward_recorder_task.ps1`.
  - Task name: `L13 NBM text forward recorder (logon)`.
  - Shape: AtLogOn with a PT5M delay, Interactive/Limited, IgnoreNew, StartWhenAvailable off, a 10-minute limit for the launcher only.
  - It requires `-ExpectedLauncherSha256`.
  - Run it with `-WhatIf` first. Registration needs the owner's yes through the coordinator.
- **Test safety.** `tests/sources/test_nbm_text_forward_recorder_registrar.py` runs the registrar only behind the hardened harness:
  - ScheduledTasks is imported first, then the stubs are defined;
  - the harness checks that the stubs still resolve;
  - task names are fake.
  - The registrar itself refuses the real module under `WEATHER_TASK_TEST=1`. See the HRRR keepalive incident note on 2026-10-30.
