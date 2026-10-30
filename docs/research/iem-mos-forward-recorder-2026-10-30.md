# IEM MOS forward recorder (Lane L13, 2026-10-30)

Research / shadow only. The recorder keeps a point-in-time forward record of the MOS runs that the Iowa Environmental
Mesonet (IEM) archive serves for the 12 market stations. The research corpus was fetched from the same service with the
same CSV columns (`tools/research/model_parity/a-iem-2_mos_fetch.py`), so a forward feature can be computed exactly as
in training. The data is free and public, with no key, no credentials and no paid source. Nothing imports the recorder,
nothing is served from it, and it reads no outcome, price or label.

## Source

- Endpoint: `https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py?station=<ICAO>&model=<M>&sts=<ISO>&ets=<ISO>&format=csv`.
  Access is anonymous HTTPS.
- **One station per request.** The archive reads `station=A,B` as a single unknown station and returns nothing. It
  rejects a repeated `station` parameter.
- Models: NBS, NBE, GFS, MEX, NAM and LAV.
  - Runs seen on 2026-10-30: NBS at 00/06/12/18Z, NBE at 00/12Z, GFS four times a day, MEX and NAM at 00/12Z, LAV hourly.
  - CYYZ has NBS and NBE only. Its GFS, MEX, NAM and LAV answers come back empty. These are logged as `empty` events,
    not errors.
- **Rate limit.** When the archive limits a client, it answers HTTP 200 with the body "Too many requests from your IP
  address, slow down.". The recorder waits at least 5 s between requests. On that body, or on HTTP 429/503, it backs off
  60, 120, 240, 480 and 960 s, then gives up on that pair for the sweep.
- Values are in the published units: deg F at every station, CYYZ included.

## What is kept

- **One version row per run and content.** A run is identified by (model, station, runtime). Each version row holds:
  - the CSV rows exactly as served, as dicts in `rows`;
  - the sha256 of their canonical JSON;
  - `n_rows`;
  - `revision`: 0 for the first content seen, then 1, 2 and so on for later changed content;
  - the request URL.
- A run is appended again only when its content changes, such as an IEM revision or a run still filling in.
  Unchanged reappearances are not written.
- **Point in time.** IEM publishes no ingest time, so availability is bounded by our own fetches:
  - `first_seen_utc` is the fetch that first returned this content.
  - `absent_at_utc` is this process's previous successful fetch for that station and model, provided its window started at or before the runtime and it did not hold the run. Otherwise it is null.
  - `backfill` is true when first seen more than 8 h after the runtime, or when no absent fetch bounds the run. Every run found on a first sweep or after a restart is therefore `backfill`.
- **The request window.**
  - First sweep: the last 72 h.
  - After that: from 6 h before the newest recorded run, but never more than 36 h back.
  - Never before 2026-10-30 00Z.

## Layout and idempotence

- Output root: `C:\t\iem_mos\forward`.
- Each runtime has an append-only file `<YYYYMMDD>/<HH>/<model>.jsonl`. Each version is one fsynced line.
- Process-wide logs: `events.jsonl`, `gaps.jsonl` (pause intervals) and `status.json`.
- **Restarts.** The known (model, station, runtime, sha256) are reloaded from disk and never written twice.
- **Polling.** One sweep every 30 min. A sweep is 72 requests at 5 s spacing, about 6 minutes.
- **Guards**, as the ENS, ECCC and NBM recorders have:
  - below-normal priority;
  - a per-process network cap;
  - `RECORDER_PAUSE` and `STOP` files;
  - a single-instance lock;
  - a 20 GB free-disk floor;
  - a 5 GB output cap.
  - It also refuses an output path inside the repository.
- **Volume.** The dry run below kept 4.9 MB for about 21.5 h of runs, so roughly 5–6 MB/day, and LAV is about 70% of that. The 5 GB cap therefore lasts about two years. A steady-state sweep downloads about 1 MB or less.

## Dry run (2026-10-30 21:24Z, all six models, `--once`)

- Result: 72 requests, 380 run versions, 1.29 MB downloaded, no throttling, no fetch failures.
- Runs recorded for 2026-10-30, 00–21Z:

  | Model | Runs | Stations |
  | --- | --- | --- |
  | NBS | 48 | 12 |
  | NBE | 24 | 12 |
  | GFS | 33 | 11 |
  | MEX | 22 | 11 |
  | NAM | 22 | 11 |
  | LAV | 231 | 11 |

- CYYZ was `empty` for GFS, MEX, NAM and LAV.
- An NBS run is 23 rows, about 15 KB per version line.

## Running

- **Dry run:** `venv\Scripts\python.exe tools\research\iem_mos_forward_recorder.py --out C:\t\iem_mos\dryrun --once`.
  The dryrun output folder is separate from the live one.
- **Launcher:** `tools\research\iem_mos_forward_recorder_launch.ps1`.
  - It is WMI-detached and pinned to the recorder's git blob in `C:\wt\l13iem`.
  - Its alive check matches `*iem_mos_forward_recorder*`.
  - It refuses when the STOP file exists, when a recorder is alive, or when the blob differs.
- **Registrar:** `tools\research\register_iem_mos_forward_recorder_task.ps1`.
  - Task name: `L13 IEM MOS forward recorder (logon)`.
  - Shape: AtLogOn with a PT7M delay, Interactive/Limited, IgnoreNew, StartWhenAvailable off, and a 10-minute limit that applies to the launcher only.
  - It requires `-ExpectedLauncherSha256`, and it refuses reserved characters in the task name.
  - Run it with `-WhatIf` first. Registration needs the owner's yes through the coordinator.
- **Test safety.** `tests/sources/test_iem_mos_forward_recorder_registrar.py` runs the registrar only behind the hardened
  harness:
  - ScheduledTasks is imported first, then the stubs are defined;
  - the harness checks that the stubs still resolve;
  - task names are fake.
  - The registrar itself refuses the real module under `WEATHER_TASK_TEST=1`.
