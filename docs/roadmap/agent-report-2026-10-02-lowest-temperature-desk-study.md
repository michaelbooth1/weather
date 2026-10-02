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
[the results JSON](agent-report-2026-10-02-lowest-temperature-desk-study-results.json) (SHA-256 `66b5fd9e…03bb12`) when the
WU history for 2016-2026-08 is unchanged. The F2 snapshot reads the 95d bulk files
(`tools\weather_market_universe.py fetch-evidence`, then `markets.csv` / `events.csv`, filtered to family
`lowest temperature | <city>`).

Branch `claude/lowest-temp-desk-study-20261002`; pre-registration commit `aa1fbdac`; report commit in the handback.
