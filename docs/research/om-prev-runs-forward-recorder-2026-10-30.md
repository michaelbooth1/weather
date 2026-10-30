# Open-Meteo Previous Runs forward recorder (L8, 2026-10-30)

Status: draft, **not registered**. Registration needs the owner's yes.

## Purpose

Row 81 (morning battery) could not test run-to-run forecast drift. The current
caches hold one forecast per issue time, and there is no dated record of when a
run was available. This recorder captures the free Open-Meteo Previous Runs
endpoint going forward. Each response is stored verbatim with its receipt time
(`fetched_at_utc`) and sha256, so drift features can later be built only from
values that were provably available at a given moment.

Research/shadow only. It makes one public read-only GET per market per hour,
uses no key or credentials, and has no capture-host, Scheduler or exchange
access.

## Endpoint and query

`GET https://previous-runs-api.open-meteo.com/v1/forecast`. It is the free tier,
needs no key, and returned HTTP 200 when live-probed on 2026-10-30.

- The query is fixed and ordered: `latitude, longitude, hourly, models,
  temperature_unit, timezone=GMT, past_days=2, forecast_days=3`. That gives 120
  hourly rows.
- `hourly` = `temperature_2m` plus `temperature_2m_previous_day1..7`.
- Coordinates are the settlement-station lat/lon of the 12 built-in markets,
  taken from `weather.market.market_registry.BUILTIN_SPECS` and rounded to 5
  decimals. The recorder refuses to run when `WEATHER_MARKET_REGISTRY` is set.
- The unit is each market's native settlement unit (F → fahrenheit,
  C → celsius).
- Models: `best_match, gfs_seamless, gfs_global, ncep_hrrr_conus,
  ncep_nbm_conus, ecmwf_ifs025, gem_seamless`.

### Model findings from the live probe

- `gfs_seamless` equalled `best_match` at 120/120 hours at the US stations
  probed. HRRR equalled `gfs_seamless` at 112/115 hours, so the seamless blend
  is HRRR inside HRRR's range.
- `gfs_global` is therefore added as the pure GFS run: it equalled
  `gfs_seamless` at only 3/48 hours. `ncep_gfs025` returned no data.
- HRRR `previous_day2..7` are all null, because HRRR's horizon is about 48 h.
  `previous_day1` had 115/120 values.
- NBM CONUS is served, including at Toronto.

## Cadence and volume

- The recorder polls hourly, inside the window `[HH:20, HH:50)` UTC: once per
  slot, one request per market, sequential, at least 1 s apart.
- That is 12 requests per hour and 288 per day. There is a hard ceiling of 60
  requests per hour.
- A response is about 36-42 KB, so the recorder writes about 12-14 MB per day
  and about 0.4 GB per month.
- Disk is capped at 5 GB of output and network at 5 GB. The recorder also
  refuses to run below 20 GB free.
- Hourly polling is a deliberate choice. Model update times differ by model and
  are not exposed per run, so an hourly receipt bounds availability to within
  one hour without depending on a per-model schedule.

**Terms caveat:** the free tier is offered under Open-Meteo's non-commercial
terms. The owner should confirm that this use fits before registration.

## Output (`C:\t\om_prev_runs\forward`, outside the repository)

- `<YYYYMMDD>/prev_runs.jsonl`, written as one fsynced append per slot:
  - **fetch rows:** `kind="fetch"`, `slot_utc`, `market`, `icao`, `lat`,
    `lon`, `unit`, `models`, `variables`, `url`, `request_started_utc`,
    `fetched_at_utc` (taken after the body is fully read), `http_status`,
    `server_date`, `response_sha256`, `response_bytes`, `body` (the verbatim
    text), `parse` and `status`.
  - **cycle record:** `rows_ok`, `complete`, `reasons`, `rows_sha256` and
    `late`.
  - `status` is one of `ok`, `guard`, `error:X`, `http_N`, `unusable:reason`
    or `not_utf8`.
- `gaps.jsonl` gets a `slot_missed` line for every slot that was skipped.
- `<YYYYMMDD>/manifest.json` is written when the day closes. It records the
  cycles, the cycles that completed, the missing slots and the file's sha256.
- Control files: a `STOP` file exits the recorder, a pause file skips slots,
  and a lock file guarantees a single instance. `recorder.pid` and
  `recorder_pid_log.txt` are also written here.

## Guards

- **URL allowlist:** GET only, https only, the exact host and path. No
  userinfo, port or fragment is accepted. The query keys must appear in the
  fixed order and the query must equal the generated one, and the coordinates
  must be registry stations.
- **Response limits:** responses are capped at 2 MiB. The parser rejects
  `bad_json`, `api_error`, a wrong hour count, missing or wrong-length series,
  a non-GMT timezone and all-null data.
- **Placement and priority:** the recorder refuses an output directory inside
  the repository and runs at below-normal priority.

## Launcher and registrar

- **Launcher:** `tools/research/om_prev_runs_forward_recorder_launch.ps1`.
  - It starts the recorder detached through WMI `Win32_Process.Create`, but
    only after the recorder file in `C:\wt\omprevrec` matches the pinned LF git
    blob id.
  - It refuses when the `STOP` file exists or a recorder is already alive.
- **Registrar:** `tools/research/register_om_prev_runs_forward_recorder_task.ps1`.
  - It requires `-ExpectedLauncherSha256` and supports `-WhatIf`.
  - It validates the task name: it refuses `/ \ : * ? " < > |` and leading or
    trailing spaces.
  - It creates the working directory before registering.
  - It refuses under `WEATHER_TASK_TEST=1` when the real ScheduledTasks
    commands are present.
  - The task it registers is AtLogOn with a 5-minute delay, IgnoreNew, a
    10-minute limit, and runs Interactive/Limited.

Registrar command, to run only after the owner's yes (`-WhatIf` first):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\wt\omprevrec\tools\research\register_om_prev_runs_forward_recorder_task.ps1 -ExpectedLauncherSha256 <launcher sha256> -WhatIf
```

The launcher sha256 is reported with the branch tip. It changes whenever the
recorder blob pin changes.
