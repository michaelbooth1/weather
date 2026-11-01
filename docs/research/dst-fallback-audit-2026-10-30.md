# DST fall-back audit for the forward emitters and recorders (lane L2, 2026-10-30)

Dated research note, not canonical guidance. It asks whether the forward emitters and recorders break when clocks
fall back on Sunday 2026-11-01 at 02:00 local, and whether the Open-Meteo label shift of
[established findings §10w](../operations/ESTABLISHED_FINDINGS.md) bites after that date. Durable results belong
in the findings digest. This note is the evidence.

- **Method:** read-only.
  - I read the code each live process runs. Every running recorder file is older than its process start, and each
    worktree is clean.
  - I evaluated the modules' own time functions on synthetic timestamps for 2026-10-31, 11-01 and 11-02, in
    America/New_York, Chicago, Denver and Los_Angeles. No network, no outcome, price or label, and no live task or
    process was touched.
- **Result:** in all four zones, 2026-11-01 is 25 local hours long.

## Probe scripts

The probes are kept on the workstation at `C:\t\l2\dst_probes\`, not in the repository. They import the modules from
their worktrees by absolute path.

| Script | sha256 | What it checks |
| --- | --- | --- |
| `l2_dst_fallback_probe.py` | e1926f39090b4489a9ca86d4de1be256399b201f5b254e7fd0af8f7fdf4dd4ac | day lengths; HRRR snapshots, window ends and dedupe keys; GEFS cutoffs and local-day node filter; `mg2_inputs.deadline`; ECMWF 3-h window counts per local day |
| `l2_om_label_probe.py` | 297aa6baa94e0cf4fecc9c766493c0f801d0f99779b79ba9a720dc1be74b0fe8 | `weather.time.provider_hourly_local_times` against true instants for an 11-01 series fetched before and after 06:00Z; the legacy `replace(tzinfo=zone)` reading |
| `l2_eccc_gem_probe.py` | 955048d53f9925c1d1814ace904ff37378042922c1ec350f238f1b17818691ce | ECCC GEM `forward_local_day` on Toronto: day bounds, 6 h `tmax` inside and crossing counts, local fields, `daily_max` coverage, hourly instants |

## Verdict per emitter and recorder

The audit asked three questions of each one:
1. Does local-day bucketing use a zone-aware conversion?
2. Does 11-01 get 25 hours and the correct window set?
3. Can a scheduled-task trigger or a time-based dedupe double-fire or skip at 01:00–02:00?

| Emitter or recorder | Code read | Verdict |
| --- | --- | --- |
| L6_G daily emit | `tools/research/l6g_forward_daily.ps1` at `5ad794a90`; `mg2_inputs`, `mg2_input_allowlist`, `mg2_input_export` and `l6g_forward_frame` at `origin/master` `1a78e1ba0` | **OK** |
| MOSMIX recorder | `C:\wt\l13mx`, `claude/mosmix-recorder-20261029` | **OK** |
| GEFS recorder | `C:\wt\l13g` at `a31fef9ba` | **OK** |
| HRRR recorder | `C:\wt\l13` at `e8bbe2031` | **OK** |
| ECMWF ENS recorder | `claude/ecmwf-ens-recorder-20261030` at `b59dca2ee` | **Recorder OK; its design note's mapping claim is wrong** (next section) |
| ECCC GEM recorder | `claude/eccc-gem-recorder-20261030` at `ac447ebe0` | **OK** |

Why each one is OK:

- **L6_G daily emit**
  - The task triggers are unzoned local daily triggers at 07:30–22:30, so none falls at 01:00–02:00.
  - The receiver deadline is zone-aware. It is `datetime.combine(D+2, 00:00).astimezone()`: D = 10-30 gives
    11-01T00:00-04:00, and D = 10-31 gives 11-02T00:00-05:00.
  - The export cut uses `ZoneInfo`.
  - A snapshot's local hour is `captured.astimezone(ZoneInfo)`. The frame uses only hours 07–12, so the repeated
    01:xx hour never enters.
- **MOSMIX recorder**
  - It is UTC throughout: files are keyed by UTC issue, folders by UTC issue date, and there is no local-day
    mapping.
  - It uses a UTC clock with relative sleeps.
  - It has a logon trigger only.
- **GEFS recorder**
  - The h:00 local cutoffs and the local-day filter on the 06Z nodes use `ZoneInfo`.
  - The kept node count moves with the offset: NY 6→6, Chicago 6→6, Denver 6→7, LA 7→7. This is the same rule as
    the history, so parity holds.
  - The deadline is UTC (D+1 00Z). It has a logon trigger only.
- **HRRR recorder**
  - Snapshots at 07–16 local and the 17:00 window end use `ZoneInfo`, through wall-clock arithmetic on an aware
    local datetime.
  - `snapshots_between` over 10-31..11-03 gives 121 keys, with no duplicate (station, local date, hour) and every
    day complete.
  - The dedupe keys only on hours 07–16. It has a logon trigger only.
- **ECMWF ENS recorder**
  - It stores UTC run, step and valid rows only.
  - Its clock and its first-try and close timers are UTC.
- **ECCC GEM recorder** (Toronto, `America/Toronto`; checked later on 2026-10-30, after lane L13 pushed it)
  - Its `tools/research/forward_local_day.py` is the same git blob as at ENS `064d91cc3`
    (b5568c3d4805f275bb8b95554afb946d588b89cf), so it applies the same containment rule.
  - On 11-01 the local day is 04:00Z to 05:00Z next day, 25 h. The 6 h `tmax` windows end at 00, 06, 12 and
    18Z, and they give 3 inside and 2 crossing on 10-31, 11-01 and 11-02.
  - A crossing row gets `local_date` null and `straddles_local_midnight` true. Its local bounds carry both offsets,
    for example 20:00-04:00 to 01:00-05:00.
  - Hourly `t2m` instants give 25 distinct instants on 11-01. The repeated 01:00 hour is kept apart by its offset.
  - Run, first-try, late and close timers are UTC (`run + first_try_h`, `LATE`, `CLOSE_AFTER`). It has a logon
    trigger only.
  - **Not DST, noted for consumers:**
    - Under containment, one run's 6 h `tmax` covers only 18 of the day's 24 or 25 hours, so `daily_max`'s
      `covered_hours == day_hours` test can never pass for `tmax`.
    - `daily_max` sums `covered_hours` over every row it is given, so rows from several runs must be grouped by
      run first.
    - The ECCC branch carries no `tests/sources/test_forward_local_day.py`; the ENS branch does.

## ECMWF ENS: the 3-hour window mapping to the local day

The recorder's design note says daily Tmax is "the maximum of the eight 3-hour windows that cover the local
settlement day". No code maps `mx2t3` windows to local days yet. The count of eight is not a constant. The windows
end at 00, 03, … UTC, and local midnight does not fall on that grid.

Window count per local day:

| Zone | Rule | 10-31 | 11-01 | 11-02 |
| --- | --- | --- | --- | --- |
| New_York | window end in (local 00:00, next local 00:00] | 8 | 8 | 8 |
| Chicago | window end in (local 00:00, next local 00:00] | 8 | **9** | 8 |
| Denver | window end in (local 00:00, next local 00:00] | 8 | 8 | 8 |
| Los_Angeles | window end in (local 00:00, next local 00:00] | 8 | 8 | 8 |
| New_York | window overlaps the local day | 9 | 9 | 9 |
| Chicago | window overlaps the local day | 9 | 9 | 8 |
| Denver | window overlaps the local day | 8 | 9 | 9 |
| Los_Angeles | window overlaps the local day | 9 | 9 | 9 |

Before any daily value is derived, the derivation must fix one zone-aware rule (`ZoneInfo`, not a fixed offset) and
must not assume eight windows. Lane L13 owns that branch.

**Adopted rule: containment**, set by lane L13 at `064d91cc3` on `claude/ecmwf-ens-recorder-20261030`; neither
end-in-day nor overlap above is the rule. A window (valid − 3 h, valid] counts only if it lies wholly inside the
`ZoneInfo` local day, and a window that crosses a day boundary is flagged as an edge. On 11-01 that gives Chicago and
Denver 8 inside and 1 crossing, and New York, Toronto and Los Angeles 7 inside and 2 crossing. This audit's probe
gets the same inside counts for its four US zones; Toronto shares New York's offsets.

## §10w: Open-Meteo fixed-offset labels after 2026-11-01

- **Live serving does not bite.**
  - Master has carried the fix since 2026-10-21 (merge `296081373` of `9142f5d21`). It reads labels as label minus
    the response offset, in UTC.
  - It covers the five live sites in `model_sources.py` and `eccc_gridded.py`.
  - In the probe, the fixed reader equals the true instants for an 11-01 series served at −14400 and at −18000.
    11-01 gets 25 labels. Repeated wall-clock labels keep `fold=1`.
- **The training and archive readers do bite, and the direction of the error flips on 11-01.**
  - The training-reader fix `claude/dst-training-readers-fix-20261021` at `a399941e` is held, not on master.
    `forecast_history.local_valid_datetime` and the other readers listed in §10w still do `replace(tzinfo=zone)`.
  - A payload served at −14400 (before the change) puts standard-time labels 1 h **late**. The probe found 46 wrong
    labels in a 72 h window.
  - A payload served at −18000 (any re-download from 11-01 on) puts every daylight-time label 1 h **early**. The probe
    found 27 wrong labels, at −1 h.
  - A rebuild after 11-01 therefore shifts the opposite set of dates from the cached files. Mixing old and new
    downloads mixes both directions. The prior-year October windows of `forecast_history` and the reanalysis
    payloads are the most exposed.
  - The only path from these readers to serving is the `forecast_daily.csv` analogs.
- **Recommendation:** no rebuild of the forecast_history or reanalysis caches until `a399941e` lands. Master adopted
  this as the interim rule below.

## Interim rule (MASTER RULING, effective 2026-10-30 on both hosts)

Relayed by the coordinator on 2026-10-30. This is not an owner decision.

- **No re-download or rebuild** of the `forecast_history`, `open_meteo_archives`, `reanalysis_history` or
  `reanalysis_synoptic` caches until `a399941e` lands.
- **`a399941e` stays HELD.** It lands after 2026-12-21 and after `9142f5d21`.
- **A lever that needs fresh pulls of those caches** uses the fixed readers from `a399941e` on its own branch, and
  its receipt says so.

## M0 keying across 11-01

- **OK.** METAR rows are keyed on `obsTime` → `astimezone(spec.tz)`, and they are ordered by UTC instant. A test
  already covers the fall-back case: 01:15-05:00 sorts after 01:30-04:00.
- **Correction to my interim report to the coordinator.** I said the `report_time_fallback` branch of
  `metar_row_time` compares a UTC date. That is wrong. The fallback goes through `parse_utc_time`, which already
  returns `astimezone(self.spec.tz)`, and the existing test asserts the local reading "13:00" for 17:00Z in Miami.
  It is not a defect, so no fix branch was made.
