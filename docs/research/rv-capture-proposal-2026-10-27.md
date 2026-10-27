# R-V forward-capture proposal (2026-10-27)

Status: dated proposal, accepted by master (98a58e36) with the rulings in §7. The
recorder and parity tool are built and tested but not started; starting waits for
the owner's yes. Nothing is registered or running.
Owner of the decision: the repository owner, through master. Read when: deciding
whether and how to capture MOS/NBE day-max guidance forward for the R-V arms.

## Owner summary

The two R-V arms that are now adopt-candidates (ledger row 54) need one input that
production never captures: the day-max forecast from three free NWS guidance
products (GFS MOS, NAM MOS and NBM extended text "NBE") for the 11 US stations.
We propose a small, separate recorder that asks the free Iowa Environmental Mesonet
(IEM) MOS service for those three products about six times a day. That is roughly
100 small web requests and about 0.5 MB a day, and about 15 MB of disk a month.
It would run as its own process, outside the capture loops, exactly as the HRRR
forward recorder does, and it changes no capture code. Each forecast run is stored
with the time we first saw it, so the forward rows can show that our training
"available after N hours" rule was honest. A parity test then compares the forward
rows with a later IEM archive fetch of the same runs. If approved on 10-28, it could
be live for the 10-29 UTC day and parity-tested by 11-06, ahead of the MG3-DC-1
binding around 11-10. Master has ruled on both open points (§7): post-2026-09-29
IEM model runs are a narrow, named exception for the recorder and parity tool only,
and the recorder runs on the workstation beside the HRRR recorder.

## 1. Source: free, official, keyless

- **Primary:** `https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py`, an HTTP GET
  with `station`, `model`, `sts`, `ets` and `format=csv`. This is the exact URL the
  code uses (`RV_URL`, 51e06ffaa `pooled_residual_model.py:7844`). Its help page
  (read 2026-10-27) asks for a plain GET and mentions no key, account, token or paid
  tier. The Oct-Dec and Aug-Sep corpora were fetched this way, anonymously.
  - IEM republishes NWS MOS and NBM bulletins. It is a free academic mirror of
    official NWS products, not a paid source, so the paid-data rule does not apply.
  - IEM throttles bursts with HTTP 429 or a "Too many requests" body. The existing
    fetcher's 8 s spacing and doubling back-off (`:7845`, `:7890-7911`) handle this.
- **Availability cross-check for NBE only:** the anonymous public bucket
  `https://noaa-nbm-grib2-pds.s3.amazonaws.com/blend.YYYYMMDD/HH/text/blend_nbetx.tHHz`
  lists one object per cycle. We would record only its S3 LastModified and never
  download the object. The a-iem-2 tidy step already uses this
  (`tools/research/model_parity/a-iem-2_mos_tidy.py:66`).
- **GFS and NAM MOS have no free per-bulletin timestamp.** IEM does not expose its
  ingest time (same file, `:76`). The recorder's own first-seen time is therefore the
  availability evidence.
- No product needs a key, account or paid tier, so none is stopped.

## 2. Products, runs, stations and fields (from code)

Sources at 51e06ffaa (claude/rv-c1-20261027) are identical to 974da72dd
(claude/rv-mos-1316-20261026, `:7084-7103`). The later commit only adds the
RV-C1 fetch windows.

| Model (IEM name) | Field | Runs used, UTC day D (latest first) | Training availability lag |
| --- | --- | --- | --- |
| `GFS` (MAV) | `n_x` | 06Z, then 00Z | runtime + 4 h 30 min |
| `NAM` (MET) | `n_x` | 00Z | runtime + 4 h |
| `NBE` | `txn` | 01Z, then 00Z (01Z in 2021-25, 00Z in 2026, a declared rule deviation) | runtime + 2 h |

Source for the table: `RV_SOURCES`, `:7825-7829`.

- **Stations:** the R0 eleven (`R0_MARKETS`, `:87-90`), each resolved through
  `spec_for_id(market).icao` (`:7914`). Today these are KATL, KAUS, KBKF, KDAL, KHOU,
  KLAX, KLGA, KMIA, KORD, KSEA and KSFO. The registry stays the authority.
- **Value selected:** the row with `ftime` = D+1 00Z, the daytime max for local date
  D (`rv_source_value`, `:7961-7974`).
  - Values outside −40..130 °F are discarded (`RV_RANGE_F`, `:7830`).
  - `mos_x` is the mean of at least 2 found sources (`RV_MIN_SOURCES` `:7831`;
    `rv_entry` `:7977-7987`).
  - `v_gap = mos_x − NBM anchor` (`rv_columns`, `:7990-7993`).
- **Arms served:**
  - (a) P3d_V adds `v_gap` at hours 13-16 (`RV_HOURS` `:7823`; `RV_C1_V` `:8113`).
  - (b) SM_HV adds `k_max`, `k_gap`, `k_tcdc` and `v_gap` at hours 13-15
    (`RV_C1_SMHV_EXTRA` `:8114`; `SM_H_HOURS` `:6756`). The `k_*` columns come from
    HRRR, which the existing HRRR forward recorder already captures, so this
    proposal adds only `v_gap`.
- **Cutoff and availability rule.** The training rule takes the latest candidate run
  with `runtime + lag ≤ cutoff instant`, where the cutoff instant is local h:00
  converted to UTC (`:7967-7970`, `:7983`). The forward rule adds one condition: the
  run is usable at cutoff t only if both `runtime + lag ≤ t` **and**
  `first_seen_utc ≤ t`.
  - The earliest cutoff is 13:00 local. That is 17Z for Eastern markets in daylight
    time, and later everywhere else.
  - Every needed run is nominally available by 10:30Z, so the extra condition binds
    only when IEM is late. When it binds, it can only make the input older, never
    newer, which keeps the effective print cutoff intact.

## 3. Host load

These estimates use file sizes only from the Oct-Dec fetch (manifest `3c6cca73…`,
165 CSVs, 141.4 MB). Each file covers one station, one model and one year, over the
93 runtime days from 09-30 to 12-31.

- **Size per station-day, all runs:** GFS 8.5 KB, NAM 4.2 KB, NBE 15.0 KB, about
  27.6 KB in total. For all 11 stations that is 0.30 MB a day.
- **Polls, UTC, at each run's due time (as built):**
  - 02:00 NBE 00Z
  - 03:00 NBE 01Z
  - 04:00 NAM 00Z
  - 04:30 GFS 00Z
  - 10:30 GFS 06Z

  Each request is one station, one model and one UTC day, covering only that day's
  used runtimes. A run still missing is retried after 15, 30 and 60 min and then
  hourly. It is given up 8 h after its due time, or at D+1 01:00Z. On time, that is
  about 55 requests a day. The 2026 NBE stream has no 01Z run, so its hourly retries
  add about 110, giving about 165 a day.
- **Requests per hour:** at most about 35 in the busiest hour (8 s apart). The
  recorder caps itself at 60 an hour.
- **Transfer:** about 0.3-0.6 MB a day. The window holds at most two runs per model,
  and the sweep repeats them.
- **Disk:** about 0.5 MB a day for raw responses plus a jsonl ledger with sha256 and
  first-seen times, or about 15 MB a month. CPU is negligible; the HRRR recorder,
  which parses GRIB, uses under 1 CPU-s an hour.

## 4. Roll classification

- **New, standalone modules** `tools/research/rv_forward_recorder.py` and
  `tools/research/rv_forward_parity.py`, tested in
  `tests/sources/test_rv_forward_recorder.py`. They copy the `RV_SOURCES` table and
  the selection rule instead of importing `pooled_residual_model`, so that no change
  to that research module can roll them. A test pins the copy.
- **Not loop-imported.** No capture supervisor imports `tools/research/`.
- **No changes** to `src/weather/`, the capture loops, config, wrappers or the
  Scheduler.
- **Expected roll_verdict class:** roll-free. A new `.py` file outside every
  loop-import closure cannot stale a supervisor fingerprint. The host verdict is
  master's, from `scripts\ops\roll_verdict.ps1 -Branch <b>`.
- **Separate process (preferred).** It can run outside the capture loops, with the
  same guards as the HRRR recorder:
  - below-normal priority
  - STOP and pause files
  - a single-instance lock with `--wait-lock-seconds` handover
  - per-launch log files
  - an hourly request ceiling
- **Placement options:**
  - The capture host, as a separate scheduled task. The jobs are light, not heavy
    under the host load policy, but the task registration is master's to do.
  - The workstation, detached like the HRRR recorder. Its three unexplained hard
    kills argue for a watchdog there.
- **Missed polls are recoverable.** The next retry refetches the same runs, and
  first_seen records the delay honestly.

## 5. Parity-test plan

1. **Unit tests (before go-live, built).** A fake IEM drives the recorder through
   simulated days, and the tests check:
   - the allowlist refusals
   - the blackout
   - the lag-and-first-seen cutoff rule with fallback
   - write-once storage
   - the guards
   - exact and mismatched parity against a refetch

   The copied `RV_SOURCES` table is pinned by a test.
2. **Overlap test (after 7 live UTC days).**
   - Refetch the same stations, models and runtimes from the IEM archive with
     `rv_forward_parity.py refetch`, using the declared window in §7.
   - Compare every selected `(station, model, runtime, ftime=D+1 00Z)` value.
     - Pass rule: 100 % exact equality, since the values are integer °F as printed.
     - Also compare `mos_x` for every station, day and hour 13-16, with
       |Δ| ≤ 1e-9 (`RV_C1_PARITY_TOL` `:8115`).
   - Report, without gating:
     - the share of runs where `first_seen_utc > runtime + lag` (pre-declared: any
       share above 5 % means the training lag was optimistic and is escalated)
     - any IEM revisions
   - Thresholds go into a rule file whose sha256 is pre-declared before the first
     comparison.
3. **No labels, prices or outcomes are read.** The test compares inputs only.

## 6. Timeline (assuming a go on 10-28)

| Date | Step |
| --- | --- |
| 10-28 | Build the module and tests on the workstation; push the branch; master gives the verdict |
| 10-28 evening | Start the recorder (detached, or as a task registered by master) |
| 10-29 | First full forward UTC day |
| 11-04 | Seventh overlap day (L+6) |
| 11-06 | Archive refetch (L+8), parity comparison and report to master |
| ~11-10 | MG3-DC-1 binds; leaves about 4 days of margin |

- **Coverage gap.** Forward rows exist only from 10-29. MG-3 rows before that would
  have no PIT MOS. Filling 10-16..10-28 from the IEM archive is possible, but it
  would be archive data, not PIT data, and it needs the ruling below.
- **Rulings.** Both are given in §7. Serving also needs a forward loader; that is a
  later, separate change and is not part of this proposal.

## 7. Master rulings and the build (2026-10-27, 98a58e36)

- **Named exception: post-2026-09-29 IEM model runs.** These are allowed only in
  `rv_forward_recorder.py` and `rv_forward_parity.py`, through one input-fetch
  allowlist (`check_request`). It allows:
  - only the URL `https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py`
  - only the parameters `station`, `model`, `sts`, `ets` and `format=csv`
  - only the 11 R0 ICAOs
  - only the products GFS, NAM and NBE
  - only runtime windows of at most 10 days that do not touch 2026-09-30..10-15

  Anything else raises before a socket opens. The exception never joins outcomes,
  prices or labels. It never enters `pooled_residual_model`, whose research guard
  (`:7922`, `:7955`) is unchanged. No 10-16..10-28 backfill is part of it.
- **Declared parity refetch window.** Runtime days L .. L+6, where L is the first
  full UTC day the recorder runs. If the start is on 10-28, that is
  2026-10-29T00:00Z .. 2026-11-04T23:59Z.
  - The window is refetched once, on or after L+8 00:00Z (11-06 for that start).
  - It is one request per station and product: 33 requests.
  - The tool refuses a window that has not been over for a full day, one longer
    than 10 days, or one touching 09-30..10-15.
  - Comparison: `rv_forward_parity.py compare --start L --end L+6`. The gates are
    §5's exact selected-value parity, no forward run missing from the archive, and
    `mos_x` |Δ| ≤ 1e-9 where both rules pick the same runs. The share of runs first
    seen late is reported, and above 5 % it is escalated.
- **Host.** The workstation, beside the HRRR recorder, with the same guards and the
  same transfer path. No Scheduler entry is made. The recorder starts only on the
  owner's yes, relayed by master.
