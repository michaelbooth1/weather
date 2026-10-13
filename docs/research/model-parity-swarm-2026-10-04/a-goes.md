# A-GOES report (model-parity swarm v2, acquisition, development data)

**Status: COMPLETE** (finished 00:44 local, well before the 04:00 abort). No scoring done; no STOP condition hit.

## What was acquired
- Product: GOES-R ABI L2 Clear Sky Mask, CONUS sector (`ABI-L2-ACMC`), anonymous HTTPS on AWS Open Data.
  - `noaa-goes19` (East): KATL KAUS KBKF KDAL KHOU KLGA KMIA KORD
  - `noaa-goes18` (West): KLAX KSEA KSFO
- Window: local target dates 2026-07-25..2026-09-29 (08-01 onward fetched first). First scene of each UTC
  hour, 11Z..23Z on D and 00Z..02Z on D+1 (16 hours per target date).
- Scenes: 2,134 ok, 4 missing (no objects in either bucket for 2026-09-22 11Z and 12Z, an upstream gap),
  6 excluded on purpose (09-30 00-02Z UTC, both satellites, never requested: COMMON date boundary).
- Station-hour rows: 11,737 (1,067 per station). 9 rows have no valid pixels (fill): KLAX/KSFO 2026-08-18T00Z,
  7 eastern stations 2026-08-31T23Z.

## Extraction
- Nearest 2 km fixed-grid pixel to each station (stations.json) via GOES-R PUG projection; checked by inverse
  projection: pixel centres within 0.02 deg of every station.
- Fields: `cloud_frac_3x3` = share of valid 3x3 pixels with BCM==1 (BCM: 0 clear, 1 cloudy); `bcm_center`,
  `acm_center`, `acm_mean_3x3` (ACM 0 clear,1 probably clear,2 probably cloudy,3 cloudy), `dqf_good_3x3`, `n_valid_3x3`.
- Caveat: no parallax correction (cloud tops displaced a few km away from the sub-satellite point); the 3x3
  (~6 km) window only partly offsets it. ACM is day/night but night detection is IR-only and less skilful.

## Availability (point in time)
- `available_utc = max(scene end time from the filename _e stamp, S3 LastModified from ListObjectsV2)`.
  Measured: 3.2-6.7 min after scan start (median 3.4 min). Use a value at snapshot t only if available_utc <= t.
- Every object URL, LastModified, size and sha256 is in `goes_scenes.jsonl`.

## Files (C:\swarm\data\goes\)
- `goes_acm_station_hour.jsonl` (one row per station-hour), `goes_scenes.jsonl` (one row per scene slot incl.
  status, URL, sha256, timestamps), `MANIFEST.json` (coverage per station-day, availability basis, file hashes),
  `fetch.log`.
- Code: `C:\pt\swarm\tools\research\model_parity\a-goes_fetch.py`, `a-goes_manifest.py`.
- Raw handling: one object at a time, held in memory only (never written to disk), discarded after extract.
  Disk used: ~8 MB. Transfer ~9 GB transient.

## Processes
- Fetcher PID 53296 exited normally ("EXIT complete"); nothing left running.
