# GEFS 00/12/18Z forward recorder (Lane L13, 2026-10-30)

Research / shadow only. The coordinator gave the GO on 2026-10-30. This recorder is a sibling of the GEFS 06Z recorder
(`tools/research/gefs_forward_recorder.py`, output `C:\t\l6g\forward\gefs`). That recorder, its worktree `C:\wt\l13g` and
its task are untouched.

## What it records

- **Source.** Free NOAA GEFS v12 data from the AWS open bucket `noaa-gefs-pds`. Access is anonymous HTTPS with no key.
- **Product and coverage.**
  - Product `pgrb2sp25`, message `TMP:2 m above ground` only.
  - Each message is located by its `.idx` and fetched with an HTTP Range request (about 0.76 MB per message).
  - Cycles 00, 12 and 18Z; members `gec00` and `gep01..gep30`; steps f003..f072 by 3.
  - 744 messages per cycle: about 563 MB per cycle, about 1.7 GB per day.
- **Stations.** The 12 markets of `forward_local_day.MARKET_TZ`, with coordinates from the market registry.
- **Decoding.** It reuses `gefs_member_point_fetch` unchanged: the decoder, `station_corners` and `bilinear`. Identity checks are the same as the 06Z recorder's, plus a plausibility check of 150–350 K.
- **Rows.** Each row carries:
  - `available_utc`: the later of the `.grib2` and `.idx` S3 `LastModified` times;
  - the listing, idx and range fetch times;
  - the idx and message sha256;
  - `fetch_lag_s`;
  - `backfill`: true when the fetch happened more than 12 h after the cycle.
- **Points.** Each point carries the bilinear and corner values, and `local_date` / `local_time` from `forward_local_day`. These use ZoneInfo, so they are DST-correct; 2026-11-01 is 25 h long.

## Back-fill

- The bucket keeps every cycle with its original `LastModified`. So cycles from 2026-10-28 00Z onward are back-filled with true availability times, and every such row is flagged `backfill: true`.
- Order: live cycles (less than 12 h old) go first, newest first. Then back-fill cycles, oldest first.
- Nothing before 2026-10-28 00Z is requested.

## Layout and closing

- **Files.** Each cycle has an append-only `<out>/<YYYYMMDDHH>/rows.jsonl`, with every line fsynced. `manifest.json` is written atomically once every slot is ok or closed. The manifest holds:
  - the slots missing;
  - the backfill and live row counts;
  - the code sha256 of the four files.
- **Closing a cycle.** It closes when no slot is open, or at cycle + 36 h if no open slot has a try left.
  - A slot that is unlisted at close becomes `object_missing`.
  - A slot that failed 8 tries goes to `gaps.jsonl` as `slot_missing`.
- **Guards**, the same as the 06Z recorder:
  - below-normal priority;
  - 3 MB/s throttle and a 1,500 MB hourly ceiling;
  - a 200 GB per-process network cap;
  - a 5,000 MB output cap;
  - a 20 GB free-disk floor;
  - `RECORDER_PAUSE` and `STOP` files;
  - a single-instance lock.

## Running

- **Output:** `C:\t\gefs_cycles\forward`.
- **One cycle in the foreground:** `--once-cycle YYYYMMDDHH`.
- **Launcher:** `tools\research\gefs_cycles_forward_recorder_launch.ps1`.
  - It is WMI-detached and pinned to the LF git blobs of the recorder, `gefs_forward_recorder.py`, `gefs_member_point_fetch.py` and `forward_local_day.py` in `C:\wt\l13gc`.
  - Its alive check matches `*gefs_cycles_forward_recorder*`. The 06Z launcher matches `*gefs_forward_recorder*`, which never matches this recorder's command line.
- **Registrar:** `tools\research\register_gefs_cycles_forward_recorder_task.ps1`.
  - Task name: `L13 GEFS 00/12/18Z forward recorder (logon)`.
  - Shape: AtLogOn with a PT6M delay (staggered from the other recorders), Interactive/Limited, IgnoreNew, StartWhenAvailable off.
  - It requires `-ExpectedLauncherSha256` and refuses the real ScheduledTasks module under `WEATHER_TASK_TEST=1`.
  - Run it with `-WhatIf` first. Registration needs the owner's yes through the coordinator.
- **Tests.** The registrar tests use the hardened stub harness:
  - ScheduledTasks is imported first, then the stubs are defined;
  - the harness checks that the stubs still resolve;
  - task names are fake.
