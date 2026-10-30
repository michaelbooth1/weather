# ECMWF ENS forward-capture recorder: design note (lane L13, 2026-10-30)

Dated research note, not canonical guidance. Master said yes on 10-30 to building this recorder (inventory item #1).
**Status: built and tested, NOT registered and NOT running.** Registering the task or starting a persistent recorder
needs the owner's yes in the coordinator's chat.

- **Source:** ECMWF open data, `https://data.ecmwf.int/forecasts/`. It is free official data (CC-BY-4.0) over
  anonymous HTTPS with no key, account or credentials, so it is not a paid source.
- **Code:** `tools/research/ecmwf_ens_forward_recorder.py`, with launcher and registrar beside it.
- **Tests:** `tests/sources/test_ecmwf_ens_forward_recorder.py`.
- **Host:** the 32 GB workstation only, built and run like the MOSMIX recorder.

## What is recorded

| Item | Value |
| --- | --- |
| Cycles | 00 and 12 UTC (`--cycles`; 06/18 are also published but carry fewer steps) |
| Steps | 3..72 h by 3 (`--steps`) |
| Parameter | `mx2t3`: maximum 2 m temperature over the 3 h ending at the step (`--params mx2t3,2t` adds instantaneous 2 m temperature) |
| Members | 50 perturbed members (`pf` 1-50). The open-data `ef` file carries no control; a `cf` row would be recorded if one appeared |
| Stations | the 12 market stations, pinned to the market registry (a test checks the pins) |
| Kept per station, member and step | the four surrounding 0.25 deg grid values, the bilinear value and the nearest value (kelvin) |

**Daily Tmax is derived, not stored.** The daily maximum for a station is the maximum of the eight 3-hour windows
that cover the local settlement day, so 24 steps of mx2t3 cover day 1 to day 3 of each run.

**Point extractions only.** Each step file is about 100 MB. The recorder reads the step's JSON-lines `.index`, then
fetches only the `mx2t3` message of each member with an HTTP byte range (about 0.3 MB each). The raw GRIB is decoded
in memory and never written to disk.

**No new package.** The messages use CCSDS/AEC packing (GRIB2 data template 5.42), which normally needs eccodes or
libaec. The recorder carries a pure-Python/numpy decoder of the CCSDS 121.0-B adaptive Rice code with the unit-delay
preprocessor. It skips every RSI block cheaply and fully decodes only the blocks that hold a station's grid corners.
Grid, product and packing templates are checked, and anything unexpected fails closed.

## Point in time

Every row carries its capture time.

- **Index rows** (`index.jsonl`, one per step attempt): URL, run time, the index's server `Last-Modified`, ETag, our
  fetch time, sha256, and per message the byte range, sha256, `Last-Modified`, ETag and our fetch time.
- **Point rows** (`points.jsonl`): run, step, valid time, member, station, values, the message sha256, its
  `Last-Modified` and our fetch time.
- **Run manifest** (`<YYYYMMDDHH>/manifest.json`): written once every step is ok or closed missing. It holds the URL
  stem, steps ok and missing, the message count, the latest `Last-Modified` and fetch time, the sha256 of both files,
  the station table and the recorder's sha256.

The recorder asks only for runs from 2026-10-31 00Z onward (`FORWARD_FIRST`); it never back-fills.

## Validation

- **Decoder.** A reference AEC encoder in the tests round-trips every coding option (split, zero-block, second
  extension, uncompressed), and a corrupt stream fails closed.
- **Real data, full field.** A full decode of a real message consumed the stream exactly, and the partial (corners
  only) decode matched it.
- **Independent check.** Member 10 at three stations agreed with the Open-Meteo ECMWF ensemble member 10 within 0.3 K.
- **Consistency.** `mx2t3` minus `2t` was non-negative at 98.4% of grid points. The small negatives cluster in the
  morning warming band, which is expected for a 3-hour maximum against an instantaneous value on an interpolated grid.

## Proof fetch (2026-10-30, one off, into `C:\t\ecmwf_ens\proof`)

- **Run and scope:** run 2026-10-30 00Z, steps 24 and 48.
- **Result:** 100 range GETs plus 2 index GETs, 34.8 MB on the network in 24 s. It produced 1,200 point rows
  (0.58 MB) and a manifest showing both steps ok.
- **Times:** the server `Last-Modified` was 07:40Z; we fetched at 18:30Z.
- **Step-24 member spread** (3 h maximum ending 00Z on 10-31):

  | Station | Low | Median | High |
  | --- | --- | --- | --- |
  | KLGA | 14.0 C | 15.3 C | 16.8 C |
  | CYYZ | 10.9 C | 12.1 C | 13.4 C |
  | KAUS | 18.0 C | 20.1 C | 23.0 C |

## Cost and retention

**Network:** about 17 MB per step, so about 0.42 GB per run and 0.85 GB per day for two cycles.

- Guards: throttle at 4 MB/s, hourly ceiling 1.5 GB, per-process cap 200 GB.
- The recorder runs at below-normal priority.

**Disk:** about 7 MB per run and 14 MB per day of point rows, about 5 GB per year.

- There is an output-size cap (`--cap-gb`, default 20) and a free-disk floor (`--min-free-gb`, default 20).

**Source retention:** ECMWF open data keeps about four days. A slot not fetched within 72 h of its run time is closed
as missing; it cannot be recovered later from this source.

**Our retention:** keep everything. No rotation is built in. The output lives under `C:\t\ecmwf_ens\forward`,
outside the repository, and must never be committed.

## How a missed day shows up

- **Recorder not running.** No new run directories appear, and `status.json` `updated_utc` goes stale. When the
  recorder comes back within 72 h, it fetches the open runs; any slot older than that is closed `missing` at once.
- **Missing slot.** The run's `index.jsonl` gets a `{"status": "missing"}` row. The slot is also appended to
  `gaps.jsonl`, and the manifest lists it under `steps_missing`. A slot closes missing after 8 failed tries or 72 h.
- **Run never finished.** A run directory with no `manifest.json` is still open, or the recorder stopped while it
  was open.
- **Paused.** A pause shows as `pause_start` and `pause_end` rows in `gaps.jsonl`.
- **Rejected data.** A failed fetch or validation (`fetch_error`, `http_*` or `invalid` with the error text) is a
  `fetch_failed` event in `events.jsonl`, and the step is retried.

## Operation

- **Start:** the launcher `tools/research/ecmwf_ens_forward_recorder_launch.ps1`. It refuses to start when:
  - the STOP file exists;
  - a recorder is already alive;
  - the recorder's git blob is not the pinned one.

  Otherwise it starts the recorder detached through WMI, writes per-launch logs, and adds a line to
  `recorder_pid_log.txt`.
- **Logon task:** `tools/research/register_ecmwf_ens_forward_recorder_task.ps1`. Run it with `-WhatIf` first; it is
  not registered.
- **Stop:** `New-Item C:\t\ecmwf_ens\forward\STOP`.
- **Pause:** `New-Item C:\t\ecmwf_ens\forward\RECORDER_PAUSE`.
- **Attribution:** use of the data requires ECMWF attribution (CC-BY-4.0).
