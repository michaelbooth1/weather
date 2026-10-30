# ECCC GEM forward-capture recorder: design note (lane L13, 2026-10-30)

Dated research note, not canonical guidance. Master said yes on 10-30 to building this recorder (inventory item #2).
**Status: built and tested, NOT registered and NOT running.** Registering the task or starting a persistent recorder
needs the owner's yes in the coordinator's chat.

- **Source:** the ECCC MSC Datamart dated archive, `https://dd.weather.gc.ca/<YYYYMMDD>/WXO-DD/`. It is free official
  open data over anonymous HTTPS with no key, account or credentials, so it is not a paid source.
- **Code:** `tools/research/eccc_gem_forward_recorder.py`, with launcher and registrar beside it.
  - It reuses `weather.sources.eccc_gridded.build_hrdps_datamart_url` and `parse_hrdps_datamart_filename` for HRDPS.
  - It reuses `tools/research/forward_local_day.py` for the local day; that file is identical to the copy on the ENS
    branch.
- **Tests:** `tests/sources/test_eccc_gem_forward_recorder.py`.
- **Host:** the 32 GB workstation only, built and run like the MOSMIX and ENS recorders.

## What is recorded (station CYYZ, Toronto)

| Model | Runs (UTC) | Product: steps | Template | File per slot |
| --- | --- | --- | --- | --- |
| HRDPS 2.5 km | 00/06/12/18 | 2 m temperature: 1..48 h | rotated lat/lon (3.1) | `model_hrdps/continental/2.5km/.../*_MSC_HRDPS_TMP_AGL-2m_RLatLon0.0225_PTfffH.grib2`, 3.4 MB |
| RDPS 10 km | 00/06/12/18 | 2 m temperature: 1..48 h | rotated lat/lon (3.1) | `model_rdps/10km/.../*_MSC_RDPS_AirTemp_AGL-2m_RLatLon0.09_PTfffH.grib2`, 0.7 MB |
| GDPS 15 km | 00/12 | 2 m temperature: 1..72 h | lat/lon (3.0) | `model_gdps/15km/.../*_MSC_GDPS_AirTemp_AGL-2m_LatLon0.15_PTfffH.grib2`, 1.3 MB |
| GDPS 15 km | 00/12 | 6 h maximum 2 m temperature: 6..72 h by 6 | lat/lon (3.0) | `..._AirTemp-Max_AGL-2m_LatLon0.15_PTfffH.grib2`, 0.8 MB |
| GEPS 0.5 deg | 00/12 | 2 m temperature: 3..72 h by 3 | lat/lon (3.0) | `ensemble/geps/grib2/raw/.../CMC_geps-raw_TMP_TGL_2m_latlon0p5x0p5_<run>_Pfff_allmbrs.grib2` (21 members), 3.9 MB |
| GEPS 0.5 deg | 00/12 | 6 h maximum 2 m temperature: 6..72 h by 6 | lat/lon (3.0) | `..._TMAX_TGL_2m_..._allmbrs.grib2`, 3.7 MB |

**What is kept.** For each file, member and station the recorder keeps the four surrounding grid values, the bilinear
value and the nearest value (kelvin), plus the station's position in grid coordinates (`grid_lat`, `grid_lon`, which
are rotated coordinates for HRDPS and RDPS). The GRIB is decoded in memory and never written to disk.

**No new package.** ECCC files use JPEG2000 packing (GRIB2 data template 5.40), which Pillow decodes; Pillow is already
in the venv.

- Pillow returns 9-16 bit samples left-aligned to 16 bits. The recorder shifts them by `16 - precision`, using the
  precision in the codestream's SIZ marker, and fails if the dropped bits are not zero.
- On real files the 12-bit fields were all multiples of 16 and the 10-bit field multiples of 64, as expected.
- Only grid templates 3.0 and 3.1 (rotation angle 0) and product templates 4.0, 4.1, 4.8 and 4.11 are accepted.
- Each file is checked for the expected parameter, statistic and 6 h window, reference time, forecast end, the window
  end time and, for GEPS, members 0..20. Anything else fails closed.

## Validation of the rotated-pole transform

The 10-30 12Z PT024 HRDPS and RDPS fields were sampled at seven stations through the rotated-pole transform and
compared with GDPS (a regular lat/lon grid) at the same valid time. HRDPS minus GDPS and RDPS minus GDPS:

| Station | HRDPS minus GDPS | RDPS minus GDPS |
| --- | --- | --- |
| CYYZ | +0.19 K | -0.88 K |
| CYUL | -1.25 K | -0.57 K |
| CYVR | -0.59 K | -0.35 K |
| CYWG | +0.57 K | -0.65 K |
| KORD | +0.56 K | -0.32 K |
| CYYC | +3.02 K | +0.30 K |
| CYHZ | -0.97 K | +0.27 K |

The CYYC difference is mountain terrain at 2.5 km against 15 km resolution. The opposite rotation sign puts every
station outside both grids, so the sign is unambiguous.

## Point in time

Every row carries its capture time.

- **File rows** (`<model>/<YYYYMMDDHH>/index.jsonl`, one per attempt): URL, run time, server `Last-Modified`, ETag, our
  fetch time, sha256, byte count and grid summary.
- **Point rows** (`points.jsonl`): run, step, valid time, window, member, station, values, the file sha256, its
  `Last-Modified` and our fetch time, plus the local-day fields described below.
- **Run manifest** (`manifest.json`): written once every slot of the model run is ok or closed missing. It holds the
  slots ok and missing, the sha256 of every file, the sha256 of both jsonl files, the latest `Last-Modified` and fetch
  time, the station table and the recorder's sha256.

The recorder asks only for runs from 2026-10-31 00Z onward; it never back-fills.

## Local settlement day (timezone-aware, DST-correct)

This uses the same rule and module as the ENS recorder (`forward_local_day`). Every point row carries:

- `tz` (`America/Toronto`);
- `start_utc` and `valid_utc`;
- `window_start_local` and `window_end_local`, with their UTC offsets;
- `local_date`;
- `straddles_local_midnight`.

The local day runs from `D 00:00` to `D+1 00:00` in ZoneInfo(tz), so 2026-11-01 is 25 hours long.

- **Instantaneous values** (2 m temperature, window 0) belong to the day that contains their valid time.
- **Window values** (6 h maximum, `(valid - 6 h, valid]`) belong to D only when wholly inside D. This is a containment
  rule. A window that crosses local midnight gets `local_date` null and is never mixed into either day.
- **Hourly coverage of a full local day** comes from HRDPS, RDPS and GDPS 2 m temperature. These are instantaneous
  hourly values, so a day's maximum of them is a sampled maximum, not a true maximum.

**Daily summaries and what "complete" means** (`tools/research/forward_daily.py`, reader `eccc_gem_daily.py`; added
after registration on branch `claude/eccc-gem-daily-20261030`, and the live recorder does not import either):

- A summary covers one series: one model, product, run, station and member. Mixed runs or members are refused, and
  coverage is the union of windows, never a sum. `forward_local_day.daily_max` summed hours across all rows; it is
  kept byte-identical only because the live launcher pins that file's git blob. Use `forward_daily` instead.
- **6 h maximum.** Toronto's local midnight (04Z in EDT, 05Z in EST) is never on a 6 h UTC boundary, so one run's
  windows wholly inside a day cover only 18 of its 24 (25 on 11-01) hours. Such a day can never be `exact`. It is
  complete when it is `bounded`: the inside windows plus the two windows crossing its midnights cover every hour.
  Then the day's maximum lies in `[max, max_upper]`, where `max` uses inside windows only and
  `max_upper = max(max, edge_max)`. Otherwise the day is `partial`.
- **2 m temperature.** A day is `hourly` when every local hour of it starts with a value (25 on 11-01). That gives a
  sampled maximum, not a true one. Otherwise the day is `partial`.

## Proof fetch (2026-10-30, one off, into `C:\t\eccc_gem\proof`)

- **Scope:** the 12Z run, step 24, every model and product.
- **Result:** 6 GETs, 13.9 MB on the network, 5 s. All 4 manifests were written with no missing slots.

| Model, product | CYYZ value (C) | Server Last-Modified |
| --- | --- | --- |
| HRDPS 2 m temperature | 1.79 | 15:13Z |
| RDPS 2 m temperature | 0.72 | 14:56Z |
| GDPS 2 m temperature | 1.60 | 15:57Z |
| GDPS 6 h maximum | 3.39 | 15:57Z |
| GEPS 2 m temperature, 21 members (low/median/high) | 2.42 / 3.26 / 4.41 | 17:07Z |
| GEPS 6 h maximum, 21 members (low/median/high) | 4.22 / 4.75 / 5.61 | 17:07Z |

- **Times:** all fetched 18:44Z.
- **Local day:** valid 08:00-04:00 local on 2026-10-31. The 6 h maximum window ran 02:00-08:00 local, so its
  `local_date` is 2026-10-31.

## Cost and retention

**Network:** about 1.26 GB per day.

| Model | Per day |
| --- | --- |
| HRDPS | about 650 MB |
| GEPS | about 280 MB |
| GDPS | about 200 MB |
| RDPS | about 130 MB |

- Guards: throttle at 4 MB/s, hourly ceiling 1.5 GB, per-process cap 200 GB.
- The recorder runs at below-normal priority.

**Disk:** about 1 KB per point row, roughly 2,100 rows per day, so about 2 MB per day.

- There is an output-size cap (`--cap-gb`, default 20) and a free-disk floor (`--min-free-gb`, default 20).

**Source retention:** the dated archive keeps about 30 days. The `today/` tree is overwritten daily, and the recorder
does not use it.

- **First try:** a model run is first tried 2.5 h after its run time for HRDPS and RDPS, 3.5 h for GDPS and 4.5 h for
  GEPS.
- **Polling:** every 10 min.
- **Closing a slot:** after 7 days the slot closes as missing.

**Our retention:** keep everything. No rotation is built in. The output lives under `C:\t\eccc_gem\forward`, outside
the repository, and must never be committed.

## How a missed day shows up

- **Recorder not running.** No new `<model>/<run>` directories appear, and `status.json` `updated_utc` goes stale.
  When the recorder comes back within 7 days, it back-fills those runs from the dated archive (all are forward runs).
- **Not published yet.** A 404 before `first try + 9 h` means "not yet". The product's later steps wait, and nothing
  is counted.
- **Missing slot.** A 404 after that point, or any other failure (`fetch_error`, `http_*`, `invalid` with the error
  text), counts as a try and is a `fetch_failed` event in `events.jsonl`. After 8 tries, or 7 days, the slot gets a
  `missing` row in `index.jsonl` and a row in `gaps.jsonl`, and the manifest lists it under `slots_missing`. Later
  steps are still fetched.
- **Run never finished.** A run directory with no `manifest.json` is still open, or the recorder stopped while it
  was open.
- **Paused.** A pause shows as `pause_start` and `pause_end` rows in `gaps.jsonl`.

## Operation

- **Start:** the launcher `tools/research/eccc_gem_forward_recorder_launch.ps1`. It refuses to start when:
  - the STOP file exists;
  - a recorder is already alive;
  - any of the three pinned files (recorder, `forward_local_day.py`, `eccc_gridded.py`) is not its pinned git blob.

  Otherwise it starts the recorder detached through WMI, writes per-launch logs, and adds a line to
  `recorder_pid_log.txt`.
- **Logon task:** `tools/research/register_eccc_gem_forward_recorder_task.ps1`. Run it with `-WhatIf` first; it is
  not registered.
- **Stop:** `New-Item C:\t\eccc_gem\forward\STOP`.
- **Pause:** `New-Item C:\t\eccc_gem\forward\RECORDER_PAUSE`.
