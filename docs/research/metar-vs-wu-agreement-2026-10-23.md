# METAR vs WU daily-max agreement, 2026-07-31..09-29 (2026-10-23)

Status: dated research note, workstation desk study (item 4 of the 2026-10-23 more-markets work), read-only. No code,
config, scheduled-task or capture-host change was made. It measures how well the free IEM METAR daily maximum agrees
with the configured Weather Underground (WU) history, which is the settlement proxy (AGENT_CONTEXT.md "Settlement and
units"). It builds on mission 86a (`d53e280a7`, EF §10c) and the
more-markets phase 2 scoping study (`docs/research/more-markets-phase2-scoping-2026-10-23.md`
on `claude/research-more-markets-phase2-20261023`, `a7cdac0c0`, not yet on master).

**Number labels.** **[M]** = measured here, with its method. **[C]** = computed from measured inputs. **[NM]** = not
measured, with the reason. Prior results are cited, not re-labelled.

## Answer in seven lines

1. **WU coverage limits the comparison.** The workstation's WU store (`data/wunderground/<icao>/daily/daily_summary.csv`)
   ends at local date 2026-08-10 and has no 2026-08-08 row. So only **10 dates per US market** (07-31..08-07, 08-09,
   08-10) fall in the window. No WU history exists locally for London, Paris, Seoul, Tokyo or Shanghai. WU was not fetched.
2. **Under the repo's rules** (all reports, routine and SPECI, IEM `tmpc` -> native unit -> half-up), METAR equals WU on
   **110/110** US station-days. Mean |diff| is 0 and there are 0 band flips [M]. Those dates are a subset of the 86a
   panel (07-01..08-11, 480/480), so this **replicates 86a; it is not new evidence**.
3. **Under the venue's 10-23 Rules** (routine reports only, RMK T-group tenths °C, half-up to °F), METAR equals WU on
   **108/110** station-days, with **1 band flip** [M]. Both misses (Atlanta 08-10 at -2 °F, Chicago 08-02 at -1 °F) are
   days when a SPECI held the maximum. WU included that SPECI on both days (2/2).
4. **SPECI exclusion matters on all 61 dates** [M]. Over 671 US station-days (07-31..09-29), dropping SPECIs lowers the
   METAR daily-max degree on **15** days and changes the 2 °F band on **9** (1.3%). That is the size of the gap
   between any SPECI-inclusive label (the repo's METAR path and, on the 2/2 evidence above, WU) and the post-10-23 Rules.
5. **Denver's venue station changed.** The 10-23..10-25 Denver events name **KDEN** (Denver International). The
   built-in spec, the WU store and `config/locations.json` all use **KBKF** (Buckley) [M, metadata]. This study measures
   KBKF only, and METAR-vs-WU agreement says nothing about KDEN.
6. **The 6-hour max groups are not usable as a WU proxy.** RMK `1snTTT` maxima whose window lies wholly inside the local
   day exceed the routine+SPECI max on 34-48 of 61 days per US station [M]. This is consistent with 86a's
   `metar_with_6h` result (182/480). Neither the repo nor the venue uses them.
7. **Pilot cities:** IEM METAR yields a daily max on 60/60 local dates (08-01..09-29) for all five, Paris 09-25 thin [M]. WU agreement is [NM].
   The only prior evidence is EF §10c: the WRH max, the IEM max and the venue agreed 50/50 at exact degree over
   09-20..29.

## Scope and boundaries

- **Markets.** The 11 US built-ins (`BUILTIN_SPECS`, `src/weather/market/market_registry.py`) and the 5 pilot cities.
  Station, ICAO, timezone and unit come from `all_specs()` for the US11 and from `config/locations.json` for the
  pilots. Toronto is a built-in but outside this brief's 16 stations, so it was not measured.
- **Dates.** Local dates 2026-07-31..2026-09-29. Nothing after 09-29 was read from `data/`.
- **WU.** WU history was read only through `daily_summary.csv`, with rows dropped at read time unless
  07-31 <= `local_date` <= 09-29. Buckets come from `weather.sources.daily_summary.native_bucket`.
- **METAR.** The free IEM ASOS archive (owner-approved, read-only, serial, 4 s apart, no auth), UTC 07-31 00:00 ..
  10-01 00:00 (exclusive). The CSVs are outside the repo, in the session scratchpad `iem/` folder.
- **Event metadata.** `config/location_market_events.json` plus three public read-only Gamma event GETs. Only the
  `resolutionSource` and `description` fields were extracted. No prices and no outcomes.
- **Not read:** 88a, panel, settlement, snapshot and wallet-ledger content. No `data/` file other than WU history was
  read. The locally captured `data/metar` store was not needed, because it stops at 06-30 (digest).

## Daily-max rules applied (cited from code)

| Rule | Repo source | Applied to METAR as |
| --- | --- | --- |
| Local day | `hourly_record` keys `local_date` on the observation instant in `spec.tz` (`historical_schema.py`); WU does the same from `valid_time_gmt` (`wu_history.py:763`) | IEM `valid` (UTC) -> `spec.tz`. This is the observation time (IEM `valid` = AWC `obsTime`, AGENT_CONTEXT.md), so 00:00 local is included and the D-1 23:5x report is not carried into D |
| Daily max and bucket | `summarize_daily` max over all rows of the local date, then `round_half_up` (`historical_schema.py:180`, `:226`; WU `wu_history.py:815`, `:843`) | Same functions, called directly |
| Rounding | `weather.units.round_half_up` = floor(x + 0.5) (`units.py:125`) | Same |
| Unit | `c_to_native` / `c_to_f`, °F = °C x 9/5 + 32 (`units.py:141`) | Repo path: IEM `tmpc` -> native (`metar_history.normalize_csv`, `metar_history.py:117`). Venue-rule path: T-group tenths °C -> °F -> half-up |
| Print cutoff | Intraday cutoffs 07-20 h (`model_constants.py:26`); effective cutoff = latest cutoff at or before the newest print (`model_distribution.py:1790`); 10-minute alias (`model_base.py:17`, `:160`) | **Not applicable to a final daily max.** The cutoff and alias only move intraday features. The final WU label is the whole local day, so METAR uses the whole local day too |

**Routine vs SPECI.** IEM `report_type=3` (routine) and `report_type=4` (special) were downloaded separately.

- **Repo-rule series:** both types, deduplicated on (station, observation time) by `metar_history.dedupe_records`.
  This matches `MetarClient` (no report-type filter) and the 86a method ("routine and special reports").
- **Venue-rule series:** US = type 3 only. Pilots = types 3 + 4, because IEM labels the foreign half-hourly :20
  reports as type 4. Those reports are routine under the Rules ("including one issued off the nominal hour"). IEM's raw
  text carries no SPECI prefix, so true foreign SPECIs cannot be separated out. Foreign SPECIs are therefore included,
  and this is noted as a limitation.

**6-hour groups.** Not used in either series (the repo does not use them). They were computed only as the diagnostic
in line 6.

**Unit and precision check** [M, per report, US routine]. The repo path and the T-group half-up give the same whole
°F on every report at 10 stations. At KBKF, IEM `tmpf` is stored to 0.5 °F, so the repo path is 1 °F above the T-group
value on 51/1480 reports. The daily max was unaffected on 61/61 dates.

**Band definition.** The 10-23..10-25 built-in events in `config/location_market_events.json` have interior US bands
2 °F wide, starting on even degrees (e.g. `76-77°F`), with open tails. The pilot cities have 1 °C single-degree bands.
A band flip is `floor(METAR/2) != floor(WU/2)` for °F and `METAR != WU` for °C. Tails are ignored (an infinite
interior ladder). The Aug-Sep ladders were not read, so the even-start parity is assumed to hold then.

## Per-market results

The METAR column counts local dates with a METAR max inside the fetch window. WU dates are 07-31..08-07, 08-09, 08-10
for every US market. Diffs are METAR - WU in whole native degrees.

| Market | ICAO | Unit | METAR days | n (with WU) | Repo rule: exact | Repo rule: diffs | Repo rule: mean abs | Repo rule: band flips | Venue rule: exact | Venue rule: diffs | Venue rule: band flips |
| --- | --- | --- | ---: | ---: | --- | --- | ---: | ---: | --- | --- | ---: |
| nyc | KLGA | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 10/10 | 0: 10 | 0 |
| atlanta | KATL | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 9/10 | 0: 9, -2: 1 | 1 |
| austin | KAUS | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 10/10 | 0: 10 | 0 |
| chicago | KORD | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 9/10 | 0: 9, -1: 1 | 0 |
| dallas | KDAL | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 10/10 | 0: 10 | 0 |
| denver | KBKF | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 10/10 | 0: 10 | 0 |
| houston | KHOU | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 10/10 | 0: 10 | 0 |
| los-angeles | KLAX | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 10/10 | 0: 10 | 0 |
| miami | KMIA | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 10/10 | 0: 10 | 0 |
| san-francisco | KSFO | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 10/10 | 0: 10 | 0 |
| seattle | KSEA | F | 61 | 10 | 10/10 | 0: 10 | 0 | 0 | 10/10 | 0: 10 | 0 |
| london | EGLC | C | 60 | 0 | [NM] | — | — | — | [NM] | — | — |
| paris | LFPB | C | 60 | 0 | [NM] | — | — | — | [NM] | — | — |
| seoul | RKSI | C | 60 | 0 | [NM] | — | — | — | [NM] | — | — |
| tokyo | RJTT | C | 60 | 0 | [NM] | — | — | — | [NM] | — | — |
| shanghai | ZSPD | C | 60 | 0 | [NM] | — | — | — | [NM] | — | — |
| **US11 total** | | | 671 | 110 | **110/110** | 0: 110 | 0 | **0** | **108/110** | 0: 108, -1: 1, -2: 1 | **1** |

All [M]. Venue-rule mean |diff|: Atlanta 0.2 °F, Chicago 0.1 °F, the rest 0 [C].

**The two venue-rule misses** [M]:

- **Atlanta 08-10:** routine max 92, WU 94, SPECI at 15:39. The band moves from 92-93 to 94-95.
- **Chicago 08-02:** routine max 76, WU 77, SPECI at 17:15. Both values fall in the 76-77 band.

**SPECI effect on all dates** [M, METAR only, no WU]. These are the US days where the routine-only max is below the
routine+SPECI max: 15 of 671 station-days. NYC 3, Atlanta 2, Chicago 4, Los Angeles 1, Miami 3 and San Francisco 2.
The other five markets had none. 9 of those days change the 2 °F band: NYC 2, Atlanta 2, Chicago 3, Los Angeles 1 and
San Francisco 1. For the pilot cities, the :20 half-hourly reports raised the max over the :50-only series on 6-11 days
per city (London 9, Paris 10, Seoul 7, Tokyo 11, Shanghai 6). Hourly-only sampling is therefore not safe for them.

**Missing and thin days.**

- **WU:** no 08-08 row in any market (also `local_missing` in 86a). There are no rows after 08-10, because the
  workstation store was last rebuilt 2026-08-12. 51 of 61 window dates per US market have no WU [M].
- **METAR (US):** every local date 07-31..09-29 has data. Days with fewer than 24 routine reports: Denver 6 (22-23
  reports; 08-13, 08-15, 08-19, 08-24, 09-10, 09-25), Los Angeles 2 (08-31, 09-16), Miami 2 (08-30, 09-29), NYC 1
  (09-12), Austin 1 (09-03) [M]. A missing hour can lower a max; none of these days is in the WU overlap.
- **METAR (pilots):** local 07-31 is excluded for all five, because their local day starts before 07-31 00:00 UTC (the
  approved fetch start). Paris 09-25 has only 25 reports, against 48 on a typical day [M].

## Resolution-source text (event metadata only)

Three built-in events dated 10-23 or later were read by public read-only Gamma GETs
(`https://gamma-api.polymarket.com/events/<id>`), extracting only `resolutionSource` and `description`. Verbatim
`resolutionSource` values:

- NYC, 2026-10-23 (event 1228408): `https://aviationweather.gov/api/data/metar?ids=KLGA&format=raw&date=2026-10-24T04:00:00Z&hours=27`
- Chicago, 2026-10-24 (event 1234085): `https://aviationweather.gov/api/data/metar?ids=KORD&format=raw&date=2026-10-25T08:00:00Z&hours=30`
- Denver, 2026-10-25 (event 1239499): `https://aviationweather.gov/api/data/metar?ids=KDEN&format=raw&date=2026-10-26T09:00:00Z&hours=30`

The three `description` texts (701-707 words) are one template [M]. With the station name, ICAO, date and URL
substituted, their SHA-256 is identical (prefix `023dce0a04da9da5`). Summary, not a quotation:

- **Value:** the highest routine-METAR temperature at the station on the local date. It comes from the RMK T-group in
  tenths °C, or from the body whole-°C group when no T-group is present. A line that "begins with SPECI is a special
  observation and does not count".
- **Conversion:** °F = °C x 9/5 + 32, rounded half up to a whole °F.
- **Timing:** the local date includes any DST shift. Resolution comes at the first METAR of the following day, or
  11:59 PM ET the next day if that is earlier.
- **Fallback:** the WU Daily Observations table if AWC has no routine observation.
- **Revisions:** COR is accepted, and revisions count until the next day's first datapoint.

The full text is reproducible from the GET above. The pilot cities' 10-23 Rules text was not read [NM].

## What this means

- **For the US11 up to 08-10:** IEM METAR with SPECIs reproduces the WU label exactly. That is now 110 more
  station-days, all on dates already inside 86a's 480.
- **The new US Rules exclude SPECIs**, and WU includes them. The routine-only METAR series is the venue-faithful
  label from 10-23. A WU or SPECI-inclusive label would have mis-banded about 1.3% of station-days in Aug-Sep
  (9/671) [C]. This is a finding for EF §10c and the owner's label-source decision (phase 2 scoping §e decision 1). It
  is not a decision.
- **Denver** needs a KDEN station decision before any comparison to the venue means anything.

## Not measured, and why

- **WU agreement for 08-11..09-29 (US).** The local store ends 08-10, and fetching WU was out of scope.
- **WU agreement for the pilot cities.** There is no local WU history and no `MarketSpec`/`wu_history_id`.
- **Toronto.** Out of this brief's 16 stations.
- **KDEN.** Not fetched; outside the 16 stations.
- **Venue agreement.** Prices and outcomes were not read by design.
- **Tail-band effects.** Historical ladders were not read.
- **Foreign true-SPECI separation.** IEM raw text lacks the prefix.

## Reproduction recipe

The helper scripts were study-specific and are not committed. To redo it:

1. **Fetch.** For each of KLGA KATL KAUS KORD KDAL KBKF KHOU KLAX KMIA KSFO KSEA EGLC LFPB RKSI RJTT ZSPD and each
   `report_type` in (3, 4), make one serial GET to `https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py`, sleeping
   about 4 s between requests (32 requests in all). Parameters: `station=<ICAO>`, `data=tmpf`, `data=tmpc`,
   `data=metar`, `year1=2026&month1=7&day1=31`, `year2=2026&month2=10&day2=1`, `tz=Etc/UTC`, `format=onlycomma`,
   `latlon=no`, `missing=M`, `trace=T`, `direct=no`, `report_type=<n>`.
2. **Repo-rule series.** Run `weather.sources.metar_history.normalize_csv(text, spec)` on both files, then
   `dedupe_records`, then `weather.sources.historical_schema.summarize_daily`, and read `max_temp_bucket` per
   `local_date`. For the pilots, build a spec-like object with `icao`, `tz` (ZoneInfo from `config/locations.json`),
   `display_unit="C"`, `id` and `city_label`.
3. **Venue-rule series.** Read the report_type 3 file (types 3 + 4 for the pilots). Parse the RMK
   `T[01]ddd[01]ddd` group (else the body `TT/` group). Convert with `c_to_native`, apply `round_half_up` per report,
   and take the max per local date of `valid` in `spec.tz`.
4. **WU.** Read `daily_summary.csv` under the WU store for the station (`weather.paths.data_path() / "wunderground" /
   <icao>`). Keep rows with 07-31 <= `local_date` <= 09-29 only, and use `native_bucket(row)`.
5. **Compare.** Take diff = METAR - WU. A band flip is `floor(x/2)` for °F and the identity for °C. The 6-hour
   diagnostic uses RMK `1[01]ddd` groups whose [valid - 6 h, valid] window lies inside one local date.
