# DWD MOSMIX forward-capture recorder: design note (lane L13, 2026-10-29)

Dated research note, not canonical guidance. Master ruled on the 10-28 audit that this recorder should be built.
**Status: built and tested, NOT registered and NOT running.** Registering the task or starting a persistent
recorder needs the owner's yes in the coordinator's chat. **No model work on MOSMIX until about 45 days of capture
exist.**

- **Source:** DWD MOSMIX, free official open data from `https://opendata.dwd.de/weather/local_forecasts/mos/`.
  It is anonymous HTTPS with no key, no account and no credentials, so it is not a paid source.
- **Code:** `tools/research/mosmix_forward_recorder.py`, with launcher and registrar beside it.
- **Tests:** `tests/sources/test_mosmix_forward_recorder.py`.

## What is recorded

| Product | Issues | Content | File used | Size |
| --- | --- | --- | --- | --- |
| MOSMIX-L | 03, 09, 15, 21 UTC | 247 hourly steps, 114 elements (TTT, TX, TN, ...) | per-station `MOSMIX_L/single_stations/<id>/kml/MOSMIX_L_<YYYYMMDDHH>_<id>.kmz` | 10-18 KB per station |
| MOSMIX-S | every hour | 240 hourly steps, 40 elements (TTT and TX included) | `MOSMIX_S/all_stations/kml/MOSMIX_S_<YYYYMMDDHH>_240.kmz` (no per-station product exists) | about 36 MB |

**L: per-station files.** For MOSMIX-L I chose the per-station single-file product, not the 78 MB all-stations file.

- On the 09Z issue of 10-29, station 72494's placemark was byte-identical in the single-station file and in the
  all-stations file (324,879 bytes).
- Both files carried the same server `Last-Modified` (10:12:48Z).
- Recording 14 stations therefore costs about 0.2 MB per issue instead of 78 MB, with no loss of content.

**S: covers our stations.** MOSMIX-S covers all 14 points; its placemarks have the same ids and coordinates as L's.
The recorder takes S too. Each hourly all-stations file is handled like this:

- The file is downloaded and hashed (sha256).
- Our 14 placemarks are cut out byte-exact into a small subset KMZ (about 78 KB). The subset keeps the original
  header up to the first placemark, our placemarks in pinned order, and the original trailer.
- The raw file is kept for 7 days and then pruned; see Retention.

**Header.** Each issue's header also names the NWP runs the issue drew on (`ReferencedModel`, for example ICON and
ECMWF/IFS 00Z for the 09Z issue). The index records this.

## Station mapping

Sources:
- **Ours:** `config/locations.json`.
- **MOSMIX:** the KMZ placemark, at 2-decimal degrees, and the DWD station catalogue
  (`mosmix_stationskatalog.cfg`, 5,649 stations).
- **Distance:** haversine.
- **Elevation diff:** MOSMIX minus ours.

| Market | Our station | MOSMIX id (name) | Role | Distance km | Elev. diff m | Match |
| --- | --- | --- | --- | --- | --- | --- |
| toronto | CYYZ | 71624 (TORONTO) | primary | 1.0 | +2 | good |
| nyc | KLGA | 72503 (NEW YORK, KLGA) | primary | 2.3 | −2 | good |
| atlanta | KATL | 72219 (ATLANTA GA., KATL) | primary | 3.1 | +3 | good |
| austin | KAUS | 72254 (AUSTIN, KAUS) | primary | 13.1 | +45 | **check**: the same ICAO, but placed at 30.30, −97.70 (the old Mueller field), not Bergstrom |
| chicago | KORD | 72530 (CHICAGO, KORD) | primary | 3.4 | +1 | good |
| dallas | KDAL | 72259 (DALLAS, KDFW) | primary | 19.4 | +34 | **poor**: Love Field has no MOSMIX point; DFW is the nearest |
| denver | KBKF | 72469 (DENVER, no ICAO) | primary | 10.4 | −78 | **poor**: Buckley has no point; 72469 sits at the old Stapleton site |
| denver | KBKF | 72565 (DENVER INT., KDEN) | secondary | 19.0 | −47 | recorded as an alternative |
| houston | KHOU | 72243 (HOUSTON TX., KIAH) | primary | 36.6 | +17 | **poor (worst)**: Hobby has no point; IAH is 37 km inland to the north |
| houston | KHOU | 72242 (GALVESTON, KGLS) | secondary | 60.5 | −11 | recorded: coastal, on the other side of Hobby |
| los-angeles | KLAX | 72295 (LOS ANGELES, KLAX) | primary | 1.5 | +8 | good |
| miami | KMIA | 72202 (MIAMI, KMIA) | primary | 5.1 | +2 | good (2-decimal coordinates) |
| san-francisco | KSFO | 72494 (SAN FRANCISCO, KSFO) | primary | 1.3 | +4 | **good** (see below) |
| seattle | KSEA | 72793 (SEATTLE, KSEA) | primary | 1.2 | +15 | good |

**San Francisco.** KSFO has its own MOSMIX point at the same airport.

- MOSMIX is station-based MOS: the forecast is statistically fitted to the station's observations.
- That means R-Q's coastal grid-cell problem (a 0.5° GEFS cell around SFO) does not apply in the same form.
- This is shown by the geometry only, not yet by data. A fair check is MOSMIX TTT against KSFO's observations once
  forward data exist; that is model work and waits for the 45 days.

**Gaps and poor matches:**
- Three markets have no MOSMIX point at their settlement airport: Dallas (KDAL), Denver (KBKF) and Houston (KHOU).
- Austin's point carries stale coordinates.
- The recorder records two secondaries (72565 and 72242) so that a later study can choose without a capture gap.
- A recorded neighbour is not the settlement station. Any use of these four markets must say so.
- Dallas, Denver and Houston are poor matches (IAH 37 km). Any later model use must test those three separately or exclude them.

**Pins.** The pins are `STATIONS` in the script. Every fetched placemark is checked against its pinned id,
coordinates and elevation. If DWD moves a station, the file is recorded `invalid` and is not kept.

## Point in time by construction

- **Index row per file.** Every fetched file gets a row in `<out>/<D>/index.jsonl`, where D is the UTC issue date.
  The file is append-only and every line is fsynced. Each row holds:
  - product, issue time (from the file name), and the document's own `IssueTime`, checked equal;
  - station, URL, `Last-Modified` (server) and ETag;
  - **our fetch time**, bytes and sha256;
  - path, KML member and KML sha256, plus the subset path and subset sha256 for S;
  - referenced models.
- **Raw files.** L raw KMZs are kept under `<out>/L/<YYYYMMDDHH>/`. S raw KMZs and subsets are kept under
  `<out>/S/<YYYYMMDDHH>/`.
- **Day manifests.** `<out>/<D>/manifest.json` is written once, when every issue of D is fetched or closed as
  missing. It pins:
  - the index file's sha256;
  - the sha256 of every kept file;
  - the station table and the recorder's sha256;
  - the maximum `Last-Modified` and fetch times.

  This is the same pinning as the GEFS recorder.
- **Availability rule.** `issue_available(rows, product, cutoff)` returns the newest issue whose `Last-Modified` is
  at or before the cutoff. With `require_fetched=True` it also requires our own fetch to be at or before the cutoff;
  this is the stricter live variant.
- **Backfill.** A backfilled file keeps its true (late) fetch time.
- **Limitation.** A file is fetched once. A silent republication by DWD under the same name would not be seen.
  The ETag and sha256 are recorded, so a later audit can detect it.

## Issue times and our serve cutoffs; DST on 11-01

**DWD schedule.** DWD issue times are UTC and do not move with DST. Europe left summer time on 10-25, before this
recorder exists. Publication lags were read from the server listings of 10-27..10-29:

| Product | Issue | Lag after issue |
| --- | --- | --- |
| L | 03Z | +76-77 min |
| L | 09Z | +72-73 min |
| L | 15Z | +75-76 min |
| L | 21Z | +72-73 min |
| S | every hour | +39-41 min |

**Our clocks.** Our cutoffs are local h:00. US and Canadian DST ends 2026-11-01 02:00 local, so every cutoff moves
one hour later in UTC. The table gives the newest **L** issue available at each local cutoff:

| Zone | Before 11-01 | From 11-01 |
| --- | --- | --- |
| Eastern (nyc, atlanta, miami, toronto) | 09Z lands 06:13, 15Z lands 12:16: **h07-h12 → 09Z**, h13-h16 → 15Z | 09Z 05:13, 15Z 11:16: h06-h11 → 09Z, **h12 → 15Z** |
| Central (austin, chicago, dallas, houston) | 09Z 05:13, 15Z 11:16: h06-h11 → 09Z, h12-h16 → 15Z | 09Z 04:13, 15Z 10:16: h05-h10 → 09Z, **h11 → 15Z** |
| Mountain (denver) | 09Z 04:13, 15Z 10:16, 21Z 16:13: h05-h10 → 09Z, h11-h16 → 15Z | 09Z 03:13, 15Z 09:16, 21Z 15:13: h04-h09 → 09Z, h10-h15 → 15Z (h10 newly), h16 → 21Z (newly) |
| Pacific (los-angeles, san-francisco, seattle) | 09Z 03:13, 15Z 09:16, 21Z 15:13: h04-h09 → 09Z, h10-h15 → 15Z, h16 → 21Z | 09Z 02:13, 15Z 08:16, 21Z 14:13: h03-h08 → 09Z, h09-h14 → 15Z (h09 newly), h15-h16 → 21Z (h15 newly) |

For **S**, at every local h:00 the newest issue is the one from about 1.3 hours earlier, in any season.

**Consequences:**
- At each zone's boundary hour, the 11-01 shift hands a fresher L issue to that cutoff.
- An hour-indexed feature therefore changes meaning across 11-01.
- Any later model work must key on the recorded issue age (cutoff minus issue time, from `Last-Modified`), not on the
  local hour.
- The recorder itself is UTC-only and needs no DST handling. DWD-side schedule changes show up in `Last-Modified`.

## Cost

Measured by the one-off test fetch of 2026-10-29 (09Z L for 14 stations, plus the five S issues 09Z-13Z).

| Item | Per day | Notes |
| --- | --- | --- |
| Download | about 0.86 GB | S 24 × 35.7 MB; L 4 × 14 × 10-18 KB ≈ 0.7 MB |
| Disk, permanent | about 2.6 MB | L raw ≈ 0.7 MB, S subsets ≈ 1.9 MB, index/manifest < 0.1 MB. 45 days ≈ 120 MB; a year ≈ 1 GB |
| Disk, rolling | about 6 GB | S raw, 7 days |
| CPU | about 1 min | about 2.3 s per S file (stream-decompress 628 MB of KML and cut 14 placemarks); L negligible |
| Memory | about 100-150 MB peak | one 36 MB S body plus 4 MB chunks |
| Wall | about 18 s per S file | at the 2 MB/s throttle |

The guards are below-normal priority, 2 MB/s, a 200 MB/hour ceiling, a 50 GB network cap per process, a 60 GB output
cap and a 20 GB free-disk floor.

## Retention

- **L raw:** kept indefinitely.
- **S subsets, index and manifests:** kept indefinitely.
- **S raw:** kept for 7 days (`--s-raw-retain-days`), then deleted.
  - Each deletion is logged in `pruned.jsonl` with the file's sha256 and size.
  - The index row keeps the raw sha256, size and `Last-Modified` for ever.
  - The subset records which raw sha it was cut from.
  - Pruning touches only the recorder's own raw S files under its output directory, never tapes, ledgers or
    trading evidence.
  - If the owner wants raw S kept in full, `--s-raw-retain-days 0` disables pruning, at about 26 GB per month.

## Failure handling

**Polling and tries:**
- The recorder polls every 5 minutes.
- An issue is first asked for at issue + 60 min (L) or + 30 min (S).
- A 404 before publication is "not yet". It is not indexed and is not a failure, and the issue's other stations are
  skipped for that pass.
- HTTP errors, short bodies, a missing `Last-Modified`, an `IssueTime` mismatch or a moved station are indexed as
  failures. Each slot gets up to 8 tries.

**Missed cycles and DWD outages:**
- DWD keeps about 48 h of issues (8 L, 48 S).
- After an outage, or after this PC was off or asleep, the recorder backfills the open slots of the last two UTC
  days, oldest first, each recorded with its true fetch time.
- A slot still unfetched at issue + 44 h is closed as `missing` and written to `gaps.jsonl`.
- L always backfills fully.
- S backfill is limited by the 200 MB/hour ceiling, about 5 files per hour. After an outage longer than about 30 h,
  the oldest S issues expire before they are fetched. They are recorded as missing; nothing is invented.

**Process:**
- A step exception is logged and the loop continues.
- Hitting the network cap stops the process (`cap_reached`).
- A single-instance lock, a STOP file (`C:\t\mosmix\forward\STOP`) and a pause file (`RECORDER_PAUSE`, with gaps
  logged) work as in the GEFS recorder.
- The recorder never asks for an issue before `FORWARD_FIRST` (2026-10-29 15Z).

## Isolation and bounds

- The recorder runs on the 32 GB workstation, never on the capture host.
- It runs under its own lock and output directory, `C:\t\mosmix\forward`.
- It is independent of the GEFS recorder and the HRRR tasks.
- It reads no outcome, price or label, and nothing imports it.

## Registration (for the owner; NOT run)

Preconditions:
- Worktree `C:\wt\l13mx` on `claude/mosmix-recorder-20261029` at the pinned recorder blob (the launcher refuses
  anything else).
- The owner's yes.

```powershell
# 1. Inspect (registers nothing):
powershell -NoProfile -ExecutionPolicy Bypass -File C:\wt\l13mx\tools\research\register_mosmix_forward_recorder_task.ps1 -WhatIf
# 2. Register the logon task (AtLogOn +4 min, Interactive/Limited, IgnoreNew, launcher only; the recorder is WMI-detached):
powershell -NoProfile -ExecutionPolicy Bypass -File C:\wt\l13mx\tools\research\register_mosmix_forward_recorder_task.ps1
# 3. Start now without waiting for a logon:
powershell -NoProfile -ExecutionPolicy Bypass -File C:\wt\l13mx\tools\research\mosmix_forward_recorder_launch.ps1
# Stop:
New-Item C:\t\mosmix\forward\STOP
```

## Test fetch of 2026-10-29

This was a one-off foreground probe, not the recorder. It wrote to `C:\t\mosmix\probe_20261029`, with
`FORWARD_FIRST` overridden in the probe only.

- **L 09Z:** all 14 stations `ok`, with `Last-Modified` 10:12:48Z and placemark pins matched.
- **S 09Z-13Z:** all five files `ok`, with no station missing and `Last-Modified` 09:40-13:39Z.
- **Volume:** 19 requests and 178 MB.
