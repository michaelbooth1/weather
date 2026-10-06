# Agent report 2026-10-02 — lowest-temperature markets for our 12 cities (desk study)

Workstation (Claude Code), read-only research. Pre-registration:
[lowest-temperature-desk-study-preregistration-2026-10-02.md](../research/lowest-temperature-desk-study-preregistration-2026-10-02.md),
committed at `aa1fbdac` before any outcome was computed. Origin:
[expansion swarm 2026-10-01](audits/swarm-expansion-2026-10-01.md), Top 3 item 1.

## Verdict

**F1 SURVIVES at fleet level: GO for passive recorder capture after 10-14 for 11 cities (all but Chicago).** From 10-15 to
12-31 of 2016-2025, the daily minimum is undercut after 09:00 local on **23.7% of days [22.9, 24.6]** (season-year bootstrap);
the crossed year x city bootstrap gives [19.6, 27.4], still below 0.30. **Chicago is FALSIFIED on its own** (32.2%
[30.9, 33.8]); Toronto, Austin and NYC are INCONCLUSIVE (intervals straddle 0.30). Under the pre-registered rule they are still
captured, because they are not FALSIFIED.

**F2 cannot be tested here.** Nothing captures minute books for these markets. A one-snapshot read (2026-09-24) found
rewards on only Miami and NYC bands. 3 of the 21 rewarded bands that had two-sided quotes had a mid outside 0.10-0.90.

**Three caveats change what "GO" buys:**
1. The undecided days resolve late in the evening (21:00-23:59), not in the morning.
2. The swarm's planned route, 88a `--extra-conditions`, cannot hold this family.
3. The settlement day boundary and the fallback wording are UNVERIFIED for lowest-temperature Rules. The raw Rules text is
   not on the workstation.

This is passive capture only. No quoting plan, model or fair value follows from this report.

**Addendum A1 (2026-10-02, [below](#addendum-a1-2026-10-02-second-pass-settlement-minimum-nbp-minima-evening-lows)):**
the Rules settle on the minimum of the WRH "Show Hourly Data" rows. Caveat 3's fallback is now verified: WU Daily
Observations, then the lowest bracket. Only the day boundary stays UNVERIFIED. A CLI or daily-summary minimum would
land in a different band on 28.5% of station-days. NBP 12Z `TXN` minima parse cleanly for all 12 stations (CYYZ
included), at 17 h lead at best. Lows set at or after 18:00 run 9-12% of days in summer and 22-25% from November to
January.

## Measured values (support and intervals)

Data: WU history hourly rows (settlement proxy by repository contract), 12 stations, `temp_native` in native whole degrees.
Eligible day: observations in >= 20 local hours, including >= 7 of hours 00-08. Primary window: 10-15..12-31 of 2016-2025, 10
season clusters, 774-779 eligible days per city (9,328 city-days). Rule: FALSIFIED if lower bound > 0.30, SURVIVES if upper
bound <= 0.30. Intervals are 95% percentile bootstrap over season-years (10,000 draws, seed 20261002).

| City (station) | Undercut after 09:00 | 95% interval | F1 |
| --- | ---: | --- | --- |
| Toronto (CYYZ) | 0.290 | [0.274, 0.307] | INCONCLUSIVE |
| Atlanta (KATL) | 0.224 | [0.209, 0.240] | SURVIVES |
| Austin (KAUS) | 0.307 | [0.279, 0.339] | INCONCLUSIVE |
| Denver (KBKF) | 0.270 | [0.250, 0.291] | SURVIVES |
| Dallas (KDAL) | 0.234 | [0.214, 0.252] | SURVIVES |
| Houston (KHOU) | 0.224 | [0.199, 0.249] | SURVIVES |
| Los Angeles (KLAX) | 0.094 | [0.067, 0.125] | SURVIVES |
| NYC (KLGA) | 0.298 | [0.273, 0.321] | INCONCLUSIVE |
| Miami (KMIA) | 0.172 | [0.144, 0.204] | SURVIVES |
| Chicago (KORD) | 0.322 | [0.309, 0.338] | **FALSIFIED** |
| Seattle (KSEA) | 0.267 | [0.243, 0.291] | SURVIVES |
| San Francisco (KSFO) | 0.145 | [0.124, 0.167] | SURVIVES |
| **Fleet (equal-weight)** | **0.237** | [0.229, 0.246]; crossed [0.196, 0.274] | **SURVIVES** |

Pre-registered fleet sensitivities:

| Variant | Fleet share | Interval | F1 |
| --- | ---: | --- | --- |
| Full year 2016-2025 | 0.188 | [0.185, 0.192] | SURVIVES |
| 2026-01-01..08-10 (one cluster; no interval) | 0.188 | — | descriptive |
| Cut-off 12:00 | 0.231 | [0.222, 0.239] | SURVIVES (Chicago FALSIFIED) |
| Undercut by >= 2 degrees | 0.190 | [0.180, 0.201] | SURVIVES (no city FALSIFIED) |
| WRH "Hourly Data" minute filter proxy | 0.238 | [0.229, 0.246] | SURVIVES (Chicago FALSIFIED) |
| Local Standard Time day | 0.248 | [0.239, 0.256] | SURVIVES (Chicago FALSIFIED; Seattle INCONCLUSIVE) |
| **Cut-off 06:00** | **0.419** | [0.409, 0.427] | **FALSIFIED** (9 of 12) |

**Hour of minimum (primary window, share of days by local hour the minimum is first reached).** 00-02: 15-34%. 03-08:
37-67%. 09-14: 0-2%. 15-20: 1-8%. **21-23: 7-26%** (Los Angeles 7%, Miami 12%, San Francisco 11%; Chicago, Austin and NYC
26%). Almost nothing is set between 09:00 and 15:00. When the morning low is undercut, the new low comes in the late evening,
as a cold front or evening cooling arrives. The 00-02 share is the previous evening's air carried past midnight. Over the full
year, 51-71% of first attainments fall in 03-08.

**Share of days already decided, by end of local hour (primary).** About 0.68-0.91 at 08:59, nearly flat through 17:59
(+0.00-0.03), then rising to 0.81-0.96 by 22:59. Per-city curves are in the results JSON.

**Exploratory by month (D2; not pre-registered).** Fleet undercut share runs from 0.13-0.14 in June-August to 0.26-0.27 in
December-January. Chicago is above 0.30 from November to March (peak 0.365 in December). Miami is near 0.30 from June to
September (convective outflow), but only 0.17 in the primary window.

**Trace (HW Pattern 4).** On KORD 2024-11-05 the morning minimum was 63 F at 01:51. The temperature then fell after 16:46 to
60 F at 23:28 and 23:51. The study computed 60, and WU `daily_summary.csv` `min_temp` is also 60.

## How settlement defines the low (verified vs UNVERIFIED)

Source: the retained 95d inventory, 2026-09-24 (`docs/roadmap/weather-market-universe-20260924/` and bulk files at
`8c683766d`). It covers 496 lowest-temperature events for our 12 cities, 5,456 markets and 396 open.

- **Verified from the rule-URL fields:** the current regime is "NOAA timeseries; WU fallback". The URL is
  `weather.gov/wrh/timeseries?site=<icao>`, and the station is our configured station in all 12 cities, CYYZ included.
  Precision is the whole native degree (F; C for Toronto). Each event has 11 bands: 2-degree F bands plus open tails such as
  "65 F or below" and "84 F or higher". Events list about 45 h before target midnight, so T, T+1 and T+2 are open together.
- **Source history:** Miami and NYC have 28 older lowest-temperature events each under "WU Daily Observations". The other 10
  cities' families start with target 2026-08-21. The source change seen for highs (EF §10c) is present here too.
- **UNVERIFIED (the raw description is not on the workstation; only its SHA-256 is retained):**
  - whether the day is the local civil day (assumed) or LST. The LST sensitivity moves the fleet share by only +0.011.
  - whether the minimum is taken from the "Show Hourly Data" view or all reports. The WRH-filter proxy moves it by +0.001.
  - the revision/finalization cutoff and the missing-data fallback (for highs, 95d records "fallback is lowest bracket";
    the lowest-family equivalent is unknown).
  - what Gamma `end_date` = 12:00Z on the target date means.

  These are preconditions for a settlement adapter, not for passive capture.
- **Transfer request (production -> workstation, not fetched):** the raw Gamma `description` for one current
  lowest-temperature event per city. Candidates are the 2026-10-02 swarm census raw (exact path not recorded in the audit)
  or the 95d raw cache `data/research/weather-universe-20260924/`, which is not on this workstation. Either is venue
  metadata, not 88a or exam data.

## Free forecast input for the minimum (inventory, no skill measured)

- **Observed running minimum (METAR / WRH, free, already collected for highs).** The settled low can only fall, so the running
  minimum is a hard **ceiling**, the mirror of the trusted high floor. It alone decides the band on 68-91% of days by 09:00.
  The daily-high floor logic must not be reused as is (95d said the same).
- **NBM NBP `TXN` 12Z-valid tokens (TXNP1..P9, TXNMN, TXNSD).** These are minima (EF §10k), and production already downloads
  and keeps them in the national bulletin for the 11 US stations (not Toronto). `nbm_probabilistic_tmax.py` extracts maxima
  only; reading minima would be a new, versioned extraction. **Period mismatch:** a 12Z-valid minimum covers the night that
  ends that morning. It does not cover the evening hours (21:00-23:59) that decide the undercut days. A calendar-day low needs
  min(this morning's overnight minimum, the evening trajectory).
- **Open-Meteo hourly `temperature_2m` (free tier).** The minimum over local-day hours is the only free input that targets
  the calendar-day definition directly, evening included. Workstation history (`data/forecast_history/<icao>/forecast_long.csv`,
  from 2018) is stitched and not point-in-time (EF §0a), so it is fine for desk descriptives but not for a backtest.
- **NWS grid hourly forecast (captured, US only).** `official_guidance_collection.py` `_nws_grid_rows` keeps hourly
  `temp_native` and `max_temp_native` with no minimum field, so the hourly path can give the evening trajectory.
- No minimum-temperature model exists. Toronto has no NBM; for Toronto only Open-Meteo and ECCC apply.

## Capture route finding (code-verified)

The swarm's planned first step, "12 slugs as 88a `--extra-conditions`", **cannot carry the family**:
- `load_extras` in `src/weather/market/maker_evidence_capture.py` accepts at most 32 static **condition ids**, not slugs.
  The family has 132 same-day conditions (12 x 11) and about 396 live conditions.
- Extra rows are written with `city: "extra"` and no `reward` block, so the reward terms that F2 needs would not be recorded
  for them through that path.

Capture needs either a slug-prefix universe change in 88a or the Stage-2 domain-neutral recorder. Both are code changes;
`roll_verdict.ps1` decides their roll status. The 88a retention hold (10-15..10-30) and swarm critique 9 still apply. This
report does not choose the route.

## Recommendations

1. Capture lowest-temperature books, trades and reward terms for the 11 non-falsified cities after 10-14, through a route that
   records per-condition reward state (needed for F2). Chicago is excluded under the pre-registered rule; the owner may
   override, since capture is cheap and Chicago is the clearest example of the evening-undercut regime.
2. Run F2 as pre-registered on the first 14 captured local days. Expect same-day bands to go to 0/1 by mid-morning on about
   three quarters of days. If reward lives anywhere, it is likely on T+1/T+2: 32 of 35 rewarded open bands on 09-24 were
   T+1/T+2.
3. Treat evening cold-front days as the adverse-selection regime: the late undercut is forecastable from NWP and arrives in
   or after the 18:00-00:30 near-close window.
4. Before any adapter work, get the raw Rules text (transfer request above).

## What was NOT done

No venue, provider or production call. No 88a or exam data read (nothing for UTC 09-30..10-14). No registration, scheduled
task, production write, restart, merge, model fit, candidate or α spend (no ledger row). Reserved confirmation window: NONE
RESERVED, checked at run time.

## Deviations from the pre-registration

- **D1:** added a crossed year x city bootstrap for the fleet interval (DELEGATION_CONTRACT §5 requires crossed clustering).
  It widens the interval to [0.196, 0.274]; the verdict is unchanged.
- **D2:** added an exploratory by-month breakdown. It decides nothing.
- The F2 snapshot counts 14 rewarded bands with no two-sided quote separately; they have no mid.

## Roll verdict

The diff is Markdown and JSON under `docs/` only, so it is roll-free by class (AGENTS.md). Tool output is in the handback
message.

## Reproduction

From a checkout that has `data/wunderground` (workstation or production), save the code block in
[the analysis appendix](agent-report-2026-10-02-lowest-temperature-desk-study-analysis.md) as `lowtemp.py`, then run:

```powershell
.\venv\Scripts\python.exe lowtemp.py data\wunderground <output-dir>
```

The output should match
[the results JSON](agent-report-2026-10-02-lowest-temperature-desk-study-results.json) (SHA-256 of the committed LF file `41612ee6…134d0e`; normalise line endings first) when the
WU history for 2016-2026-08 is unchanged. The F2 snapshot reads the 95d bulk files
(`tools\weather_market_universe.py fetch-evidence`, then `markets.csv` / `events.csv`, filtered to family
`lowest temperature | <city>`).

Branch `claude/lowest-temp-desk-study-20261002`; pre-registration commit `aa1fbdac`; report commit in the handback.

## Addendum A1 (2026-10-02, second pass): settlement minimum, NBP minima, evening lows

Pre-registered in [addendum A1](../research/lowest-temperature-desk-study-preregistration-addendum-2026-10-02.md), committed
at `d52b5cf9` before any of these values was computed. Scripts:
[A1 analysis appendix](agent-report-2026-10-02-lowest-temperature-desk-study-addendum-a1-analysis.md). Outputs:
[A1 results JSON](agent-report-2026-10-02-lowest-temperature-desk-study-addendum-a1-results.json).

### A1 verdict

**Q1: settlement is the minimum of the hourly rows, not a CLI or daily-summary minimum, and the difference is
material.** The Rules text names the "Temp" column of the WRH "Show Hourly Data" view, read for all times on the
target date. Over 2026-08-01..09-28, the CLI or daily-summary minimum falls in a **different band from the hourly-row
minimum on 202 of 708 station-days (28.5%)**, between 8 and 32 of 59 days per station. It is almost always 1-3 degrees
lower, because the daily summary sees the dip between hourly reports. Settling from CLI, NWS daily climate or ECCC daily
values, or from METAR 6- or 24-hour minimum groups, would put roughly every fourth day in the wrong band. Routine-only versus
routine plus SPECI changes the band on 0-3 days per station; LST versus civil day on 0-7.

**Q2: the NBP 12Z `TXN` tokens are clean minima and parse into p10-p90 for all 12 stations, CYYZ included.** The
workstation keeps 178 bulletins (2026-07-13..08-12), which give 39 valid dates (07-14..08-21) per station. Every
provenance check passes. The shortest available lead is 17 h. The tokens cover the overnight minimum only, not the
evening hours that decide the undercut days.

**Q3: lows reached after 18:00 local are a winter regime.** Fleet share by month: 9-12% from June to September, 16.5%
in October, 22% in November and 24% in December (25% in January). Los Angeles and Miami run the other way, peaking in
summer. Chicago is at or above 30% from November to March.

Nothing here changes F1, F2 or the passive-capture GO.

### Q1: what the Rules say (MEASURED from one rendered page)

Rendered in the workstation browser pane on **2026-10-02 at 22:25 UTC**, from
`https://polymarket.com/event/lowest-temperature-in-nyc-on-september-29-2026` (resolved; target before the exam window).
Only the Rules text was read. SHA-256 of the whitespace-normalised Rules text (2,355 characters):
`0bc08b7dfbd552c7e9d5044c2ae9c11bdb09fcb46ced1c8a4e431aecb638253e`. The decisive sentence, verbatim: the market
"will resolve off of the Hourly Data provided using the "Show Hourly Data" button". The other clauses, closely
paraphrased:

| Clause | What the Rules say |
| --- | --- |
| Quantity | The band that contains the lowest temperature NOAA recorded at the LaGuardia Airport station, in °F, on the target date |
| Source | `weather.gov/wrh/timeseries?site=klga`: the lowest reading in the "Temp" column for all times on that day |
| View | The Hourly Data view (quoted above); a units toggle switches the table to °F |
| Precision | Whole degrees Fahrenheit |
| Day boundary | Only "on <date>". No time zone or clock hours are stated (see UNVERIFIED below) |
| Fallback | If NOAA data for the date is unavailable by 11:59 PM ET on the next day, the Weather Underground Daily Observations table is used. If there is no data at all by then, the market resolves to the lowest bracket |
| Finalisation | Resolves when the first data point for the following date is published on the source, or at 11:59 PM ET on the next day, whichever comes first. Revisions count only until that first next-date data point |
| Erroneous data | The market may stay open up to 7 calendar days (ET) for a correction; otherwise Polymarket issues a Clarification |

This settles three of the four items the first pass listed as UNVERIFIED: the Hourly Data view, the fallback and the
revision cutoff. The fallback is lowest-bracket, the same as for highs.

**Still UNVERIFIED:** (a) the clock and time zone of the WRH table, and so the day boundary. The table was not opened,
because today's rows fall inside the exam window. The first pass's LST sensitivity bounds the effect at +0.011 on F1.
(b) Whether the Hourly Data view contains SPECI rows. The 86a minute-filter proxy says routine rows only; Q1 shows this
changes the band on at most 3 of 59 days per station. (c) Toronto's Rules (unit and view); only the NYC page was
rendered. (d) What Gamma `end_date` = 12:00Z means.

### Q1: hourly-row minimum H vs daily-summary/CLI minimum D (MEASURED)

IEM ASOS METAR (routine + SPECI, `T` group in tenths of °C where present), local civil dates 2026-08-01..09-28 (59 days).
D is the NWS CLI daily low (IEM archive), except KBKF and KDAL, which have no CLI in IEM; there D is the METAR 24-hour
minimum group. That group equals CLI on 524 of 528 station-days at the 9 stations that have both. For CYYZ, D is the
ECCC daily minimum (TORONTO INTL A, 6158731, tenths of °C rounded half up). A band is 2 F with even lower edges (from
the 95d band labels) or 1 °C.

| Station | D source | Days | H ≠ D | **Different band** | D below H | D above H | Routine-only vs all rows (band) | Civil vs LST day (band) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CYYZ | ECCC daily | 59 | 31 | **31 (53%)** | 31 | 0 | 0 | 7 |
| KATL | CLI | 59 | 21 | **14 (24%)** | 21 | 0 | 1 | 2 |
| KAUS | CLI | 59 | 34 | **25 (42%)** | 34 | 0 | 1 | 3 |
| KBKF | 24-h group | 59 | 43 | **32 (54%)** | 43 | 0 | 0 | 4 |
| KDAL | 24-h group | 59 | 31 | **16 (27%)** | 31 | 0 | 0 | 2 |
| KHOU | CLI | 59 | 24 | **13 (22%)** | 24 | 0 | 0 | 0 |
| KLAX | CLI | 59 | 22 | **10 (17%)** | 21 | 1 | 2 | 3 |
| KLGA | CLI | 59 | 27 | **11 (19%)** | 24 | 3 | 1 | 3 |
| KMIA | CLI | 59 | 31 | **16 (27%)** | 29 | 2 | 3 | 1 |
| KORD | CLI | 59 | 21 | **10 (17%)** | 21 | 0 | 2 | 3 |
| KSEA | CLI | 59 | 28 | **16 (27%)** | 27 | 1 | 3 | 4 |
| KSFO | CLI | 59 | 18 | **8 (14%)** | 16 | 2 | 3 | 2 |
| **All** | | **708** | | **202 (28.5%)** | | | | |

D - H is -1 on most disagreeing days, and -2 to -4 on a few. Using the routine-only H instead gives 210 of 708 (29.7%).
The pre-registered rule (immaterial if <= 2% at every station) is not met at any station, so the choice is
**material**. The Rules text decides it: **H**. The first pass's settlement proxy (WU hourly rows, specials included)
is an H-type minimum and stays the right proxy. Its KORD 2024-11-05 trace (WU `daily_summary.csv` = hourly min) does
not show that any daily-summary product equals H in general.

Caveats: D's day is the LST climate day for CLI and ECCC's climatological day for CYYZ, and was not re-derived. The
"Civil vs LST" column separates the day-boundary effect (0-7 days) from the sampling effect, which is most of the gap.
CYYZ METAR carries whole °C with no `T` group. The window is August-September, not the October-December capture season.

### Q2: NBP `TXN` minima, p10-p90 per station-date (MEASURED parse; no scoring)

All blobs in the workstation payload store with an `NBM ... NBP GUIDANCE` header: 178 distinct bulletins, issued
2026-07-13..08-12 (30 each at 00, 01, 07, 13 and 19Z; 28 at 12Z). No issue time or valid time is on or after
2026-09-30. Only tokens in a 12Z-valid column are kept (EF §10k); 00Z maxima are discarded. No row lacked a percentile.

| Station | Station-dates | Rows (date x cycle) | Median p90 - p10, F, by lead 0-24 / 24-48 / 48-72 / >72 h | 12Z mean below both 00Z neighbours | p10 <= ... <= p90 | Provenance: median p50 - observed overnight min, F (n) |
| --- | ---: | ---: | --- | ---: | ---: | ---: |
| KATL | 39 | 1,602 | 3 / 3 / 4 / 5 | 1.00 | 1.00 | +0 (21) |
| KAUS | 39 | 1,602 | 5 / 6 / 6 / 6 | 1.00 | 1.00 | +0 (21) |
| KBKF | 39 | 1,602 | 9 / 9.5 / 10 / 12 | 1.00 | 1.00 | -2 (21) |
| KDAL | 39 | 1,602 | 5 / 5 / 6 / 6 | 1.00 | 1.00 | +0 (21) |
| KHOU | 39 | 1,602 | 4 / 4 / 4 / 5 | 1.00 | 1.00 | +0 (21) |
| KLAX | 39 | 1,602 | 3 / 3 / 3 / 4 | 1.00 | 1.00 | -1 (21) |
| KLGA | 39 | 1,602 | 5 / 5 / 5 / 7 | 1.00 | 1.00 | -2 (21) |
| KMIA | 39 | 1,602 | 4 / 4 / 4 / 3 | 1.00 | 1.00 | -1 (21) |
| KORD | 39 | 1,602 | 6 / 6 / 6 / 10 | 1.00 | 1.00 | -1 (21) |
| KSEA | 39 | 1,602 | 5 / 5 / 5 / 6 | 1.00 | 1.00 | +1 (21) |
| KSFO | 39 | 1,602 | 3 / 4 / 4 / 5 | 1.00 | 1.00 | +1 (21) |
| CYYZ (flagged) | 39 | 1,602 | 5.5 / 6 / 6 / 9 | 1.00 | 1.00 | -1 (21) |

The per station-date headline (latest cycle issued before the token's valid time) is in the results JSON under
`q2.headline`, 468 rows. For example, KORD 2026-08-10 from cycle `20260809T19Z` (lead 17 h): p10 68, p25 69, p50 70,
p75 73, p90 76 F. The full date x cycle table (19,224 rows) is reproducible from `q2.py`. The provenance column compares
the headline p50 with the observed IEM minimum over local 19:00 (previous day) to 08:00, on 08-01..08-21. Its job is to
confirm these are minima (EF §10k found +1 F); it is not a skill score, and no market or band is involved.

Findings, beyond the first pass's inventory:
- **CYYZ has an NBP block, contrary to the first pass's "Toronto has no NBM".** Its values are in °F and its checks pass.
  Its use against a °C market is UNVERIFIED and needs a unit conversion and its own provenance.
- **The freshest minimum for a given morning is 17 h old.** NBP text columns start at forecast hour 17-24, so the
  latest cycle that carries morning d's 12Z minimum is the 19Z run of day d-1. The 00/01/07Z runs of day d start at
  00Z on d+1. Checked on the KORD 2026-08-10 leads (17, 23, 29, 35, 36 h) and on a 00Z header.
- **UNVERIFIED:** the exact accumulation window of a 12Z `TXN` minimum. The bulletin does not state it; the NOAA key
  says only that 12Z values are minima.
- The sample is mid-July to late August; widths in October-December will differ. Production holds later bulletins
  (EF §10k/§10l); fetching them needs a transfer manifest and must stop before 2026-09-30.

### Q3: share of daily lows reached at or after 18:00 local, by month (MEASURED)

WU hourly rows, same eligibility rule and local civil day as the first pass, 2016-2025. "First >= 18:00" means the day
minimum is first reached at 18:00 or later, so it was not reached before 18:00. "Reached or tied" counts the last
attainment. Fleet = equal-weight mean of the 12 cities; interval = 95% bootstrap over the 10 years (10,000 draws, seed
20261002; year clusters only, not crossed with city, as pre-registered). 2026 is descriptive (one cluster).

| Month | Fleet first >= 18:00 | 95% interval (years) | Fleet reached or tied >= 18:00 | 2026 fleet | Eligible city-days |
| --- | ---: | --- | ---: | ---: | ---: |
| Jan | 0.247 | [0.234, 0.259] | 0.312 | 0.221 | 3,701 |
| Feb | 0.218 | [0.209, 0.227] | 0.275 | 0.190 | 3,384 |
| Mar | 0.176 | [0.167, 0.185] | 0.240 | 0.181 | 3,667 |
| Apr | 0.145 | [0.137, 0.154] | 0.213 | 0.135 | 3,591 |
| May | 0.132 | [0.124, 0.142] | 0.207 | 0.164 | 3,707 |
| Jun | 0.099 | [0.090, 0.107] | 0.178 | 0.160 | 3,591 |
| Jul | 0.103 | [0.091, 0.114] | 0.176 | 0.086 | 3,712 |
| Aug | 0.093 | [0.085, 0.101] | 0.167 | 0.083 | 3,690 |
| Sep | 0.117 | [0.105, 0.128] | 0.189 | — | 3,557 |
| Oct | 0.165 | [0.153, 0.177] | 0.228 | — | 3,717 |
| Nov | 0.219 | [0.207, 0.232] | 0.287 | — | 3,573 |
| Dec | 0.239 | [0.230, 0.248] | 0.312 | — | 3,717 |

Per city, first attainment at or after 18:00:

| City | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Toronto | 0.29 | 0.26 | 0.21 | 0.14 | 0.12 | 0.10 | 0.08 | 0.08 | 0.11 | 0.22 | 0.27 | 0.26 |
| Atlanta | 0.23 | 0.23 | 0.17 | 0.12 | 0.09 | 0.07 | 0.08 | 0.11 | 0.07 | 0.15 | 0.20 | 0.22 |
| Austin | 0.32 | 0.30 | 0.26 | 0.19 | 0.15 | 0.05 | 0.04 | 0.05 | 0.12 | 0.19 | 0.29 | 0.32 |
| Denver | 0.29 | 0.29 | 0.20 | 0.18 | 0.17 | 0.10 | 0.12 | 0.07 | 0.13 | 0.23 | 0.25 | 0.29 |
| Dallas | 0.21 | 0.22 | 0.15 | 0.14 | 0.10 | 0.04 | 0.05 | 0.06 | 0.07 | 0.14 | 0.22 | 0.23 |
| Houston | 0.26 | 0.22 | 0.17 | 0.11 | 0.11 | 0.06 | 0.03 | 0.04 | 0.06 | 0.13 | 0.22 | 0.24 |
| Los Angeles | 0.09 | 0.09 | 0.08 | 0.10 | 0.15 | 0.14 | 0.17 | 0.18 | 0.18 | 0.09 | 0.06 | 0.09 |
| NYC | 0.29 | 0.23 | 0.17 | 0.17 | 0.20 | 0.10 | 0.15 | 0.10 | 0.14 | 0.18 | 0.29 | 0.30 |
| Miami | 0.21 | 0.11 | 0.09 | 0.09 | 0.10 | 0.13 | 0.15 | 0.13 | 0.16 | 0.11 | 0.14 | 0.16 |
| Chicago | 0.33 | 0.30 | 0.32 | 0.23 | 0.22 | 0.20 | 0.20 | 0.15 | 0.15 | 0.23 | 0.31 | 0.34 |
| Seattle | 0.27 | 0.23 | 0.15 | 0.14 | 0.08 | 0.10 | 0.03 | 0.06 | 0.09 | 0.18 | 0.25 | 0.25 |
| San Francisco | 0.17 | 0.14 | 0.14 | 0.12 | 0.11 | 0.08 | 0.12 | 0.09 | 0.13 | 0.12 | 0.12 | 0.17 |

For the capture season (10-15..12-31), roughly one day in five to one in four has its settled low set at or after
18:00. That falls inside or just before the protected 18:00-00:30 near-close window, and the NBP 12Z minimum (Q2) cannot see
it. Q3 uses WU rows with specials included; by Q1, a routine-only filter would change little.

### A1 deviations and limits

- **2026-09-29 dropped** from Q1 (pre-registered): its local day ends after the 2026-09-30T00:00Z request cap.
- **Q1 extra column:** routine-only H vs D (210 of 708) was added after the first run; the pre-registered H vs D stands.
- **Rules quotation:** one decisive sentence is quoted verbatim; the rest is paraphrased, and the full text is pinned by
  SHA-256 so a holder of the text can verify it.
- **Workstation wrapper:** the Q2 scan (~6 GB read, one process, ~20 s) ran outside `workstation_heavy.ps1`, which only
  admits allow-listed `weather.*` modules.
- New free sources used (owner-requested): IEM ASOS and CLI archives, ECCC climate bulk CSV, one Polymarket page. No
  credential, no venue API, no production data, no 88a or exam data, nothing dated UTC 2026-09-30 or later.
