# Foreign settlement desk study — WRH vs IEM METAR, and HKO — 2026-10

Dated research evidence (desk study, workstation, 2026-10-02 America/Toronto). Not canonical guidance.
**Read when:** you need the measured settlement-source behaviour for London, Paris, Seoul, Shanghai, Tokyo
or Hong Kong, or you are about to change their `config/locations.json` settlement blocks. The durable
settlement-source finding is owned by [established findings §10c](../operations/ESTABLISHED_FINDINGS.md);
this file is its foreign-station evidence for 2026-09-20..09-29.

Scope: no capture, no credentials, nothing read or written under `data/`, no exchange calls. Sources
were public web pages and the free IEM ASOS archive. Reserved confirmation window at run time:
**NONE RESERVED**. Base: `origin/master` `fd274ac5`.

## Verdict

1. **No mismatches.** For all 50 station-days (5 stations × 10 dates), the daily max per station-local
   date agrees across three sources: IEM ASOS METAR (whole °C), the WRH timeseries render (whole °C),
   and the venue's winning band. 50/50 match at exact-degree level, not just band level.
2. **Hong Kong resolves by truncation, not rounding.** On 10/10 resolved days the venue paid the bracket
   `floor(HKO Absolute Daily Max)`. Four days rule out half-up rounding: 31.9 → 31 °C, 32.5 → 32 °C (twice)
   and 32.7 → 32 °C. This contradicts the repo-wide `"rounding": "whole_degree_half_up"` declared in
   `release_candidate_contract._settlement_rules` for this location.
3. **WRH "Hourly Data" is empty for every foreign station.** The page's own filter
   (`obs.js`) keeps only rows that carry `sea_level_pressure_set_1`. Synoptic's `GLOBAL-METAR` network has
   no such field, so the hourly table renders zero rows. The foreign Rules do not use that view: they
   resolve on "all times" (see Rules below). The EF §10c wording ("Hourly Data") applies to the US markets
   only.
4. **WRH gaps are minor and none moved a max.** **EGLC had no overnight or weekend closure gap.** It
   reported every 30 minutes all day on all 10 dates, weekends included (09-20, 09-26 and 09-27). The
   sampled overnight strings are `AUTO`. One shared outage at LFPB (09-24 22:00 → 09-25 11:30 local) is
   in both IEM and WRH, so it is a station or feed gap, not a WRH gap. The 09-25 max (28 °C, at
   15:30–18:00) came after recovery.

## Method

- **IEM:** `weather.sources.metar_history.MetarClient.fetch(icao, 2026-09-19, 2026-09-30)` then
  `normalize_csv` with a transient `MarketSpec` built from `config/locations.json`. These five cities are
  not in `market_registry`, so `spec_for_id` refuses them. Records were grouped by `valid_time_local[:10]`
  with the IANA zone from `config/locations.json`, and `max(temp_native)` was taken per date. VHHH was
  fetched for Hong Kong comparison only.
- **WRH:** the in-app browser rendered
  `https://www.weather.gov/wrh/timeseries?site=<ICAO>&units=metric&history=yes&start=20260919&end=20260930`.
  `history=yes` is the page's own "Gather Historical Data" mode; `start` and `end` are passed to Synoptic
  as UTC `…0000`/`…2359`. The rendered `#OBS_DATA` table (all data, station-local times) was read per row
  and grouped by local date. Gaps listed below are intervals longer than 75 minutes, plus missing rows
  against the 48/day cadence. Synoptic, the page's backend, returned HTTP 429 on two RKSI attempts; the
  third succeeded.
- **Venue:** for each `highest-temperature-in-<city>-on-september-<d>-2026` event page, the
  server-rendered event JSON gave the winning `groupItemTitle` (`outcomePrices[0] == "1"`) and
  `resolutionSource`. Live Rules were read from the rendered `october-3-2026` pages on 2026-10-02
  ≈22:30 UTC.
- **HKO:** `climat.htm` links to "Daily Extract - Sep 2026" (`/en/cis/dailyExtract.htm?y=2026&m=09`), and
  its "Absolute Daily Max (deg. C)" column was read. Also checked: the Open Data `rhrread` endpoint and the
  `CLMMAXT` daily-max dataset.

## WRH-resolved cities: daily max per local date (°C)

IEM = IEM METAR max; WRH = WRH render max; V = venue winning band. All three agree on every row, so
one value per cell is shown.

| Local date | London EGLC | Paris LFPB | Seoul RKSI | Shanghai ZSPD | Tokyo RJTT |
| --- | --- | --- | --- | --- | --- |
| 09-20 (Sun) | 20 | 24 | 26 | 28 | 23 |
| 09-21 | 23 | 22 | 27 | 29 | 26 |
| 09-22 | 25 | 24 | 28 | 28 | 30 |
| 09-23 | 23 | 27 | 27 | 29 | 24 |
| 09-24 | 21 | 24 | 25 | 28 | 27 |
| 09-25 | 24 | 28 | 24 | 31 | 27 |
| 09-26 (Sat) | 21 | 23 | 26 | 30 | 23 |
| 09-27 (Sun) | 22 | 28 | 26 | 29 | 24 |
| 09-28 | 19 | 24 | 23 | 26 | 26 |
| 09-29 | 23 | 28 | 24 | 26 | 23 |

**Mismatches: none** (IEM vs WRH 50/50, WRH vs venue 50/50).

Max-time notes that matter for date bucketing:

- RJTT often sets its max at local midnight carry-over: 09-20, 09-23, 09-26 and 09-29 tie at 00:00.
  09-21 peaked at 22:30. Tokyo is sensitive to the local-date boundary, and both sources agree when
  bucketed in Asia/Tokyo.
- ZSPD 09-28 tied at 26 from 01:00 to 22:00.

## WRH gaps (rows missing against the 30-min cadence)

| Station | Local date | WRH | IEM | Effect on max |
| --- | --- | --- | --- | --- |
| EGLC | 09-22 | 46 rows; 11:50 and 12:20 missing | 48 | none (max 25 at 14:20–17:20) |
| LFPB | 09-20 | 47 rows | 48 | none (max 24 at 14:30, present) |
| LFPB | 09-24 → 09-25 | no rows 22:00 → 11:30 | same gap | none observed; the 09-25 overnight min side is unobserved |
| ZSPD | 09-22 | 47 rows | 48 | none |
| RJTT | 09-22 | 47 rows | 48 | none |

- **EGLC closures:** EGLC was not closed in the data. It had 48/48 rows on every date in both sources,
  including 00:00–06:00 local and the weekend. The METAR strings carry `AUTO` (for example
  `EGLC 190050Z AUTO …`), so automated reports cover the hours the airport is shut.
- **Risk:** under the London Rules a WRH outage longer than one day falls back to the WU daily table,
  then to the lowest bracket. Nothing in this window came close to triggering that.
- ZSPD 09-26/27 (49/50 rows) and VHHH carry extra SPECI rows; these are additions, not gaps.

## Hong Kong

| Local date | HKO Absolute Daily Max | Venue band | floor | half-up | VHHH METAR max |
| --- | --- | --- | --- | --- | --- |
| 09-20 | 33.1 | 33 °C | 33 | 33 | 33 |
| 09-21 | 33.0 | 33 °C | 33 | 33 | 33 |
| 09-22 | 30.2 | 30 °C | 30 | 30 | 33 |
| 09-23 | 31.9 | **31 °C** | 31 | 32 | 33 |
| 09-24 | 32.2 | 32 °C | 32 | 32 | 33 |
| 09-25 | 32.5 | **32 °C** | 32 | 33 | 33 |
| 09-26 | 32.1 | 32 °C | 32 | 32 | 32 |
| 09-27 | 32.7 | **32 °C** | 32 | 33 | 33 |
| 09-28 | 32.5 | **32 °C** | 32 | 33 | 33 |
| 09-29 | 33.1 | 33 °C | 33 | 33 | 33 |

- **Rule as observed:** the bracket labelled `N°C` contains [N.0, N+1.0) of the 0.1 °C HKO value, so
  floor applies 10/10 and half-up only 6/10. The Rules say the bracket is chosen by "range that
  contains" the HKO value. The source's precision is stated as one decimal place, so truncation is the
  literal reading, not a venue quirk.
- **VHHH is not a proxy:** it reads up to 2.8 °C higher (09-22: 33 vs 30.2), and it would have picked the
  wrong band on 6/10 days.
- **`rhrread` cannot settle history.** It returns only the latest hourly reading: at 2026-10-03 06:00
  HKT, HKO showed 25 °C, a whole degree. It holds no daily max and no past days, so for 09-20..29 it
  provides nothing. The `CLMMAXT` Open Data series (`opendata.php?dataType=CLMMAXT&station=HKO`) was
  published only through 2026-08-31 at read time. The Daily Extract is the only source that covered the
  window.
- **Revision policy differs from WRH cities:** HKO markets ignore revisions after HKO's initial
  publication and resolve to the lowest bracket if there is no data within seven days. The extract
  updates on working days before 14:00 HKT for the previous day.

## Live Rules, read 2026-10-02 ≈22:30 UTC (events dated 2026-10-03)

Paraphrased to stay within the quoting limit. Each URL below is the authority.

- **London / Paris / Seoul / Shanghai / Tokyo** (`polymarket.com/event/highest-temperature-in-<city>-on-october-3-2026`):
  - **Source and column:** NOAA data for the named station; the bracket containing "the highest reading
    under the "Temp" column for all times on this day" on `weather.gov/wrh/timeseries?site=<icao>`
    (lower-case ICAO), switched to metric.
  - **Fallback:** WU Daily Observations if NOAA has no data by 23:59 ET the next day; lowest bracket if
    neither does.
  - **Finality:** resolves at the first data point of the following date. Revisions count until then.
  - **Precision:** whole °C.
  - **Station names in the text:** London City Airport Station, Paris-Le Bourget Airport Station, Incheon
    Intl Airport Station, Shanghai Pudong International Airport Station, Tokyo Haneda Airport Station.
  - The text was identical across the five apart from the station name and ICAO.
  - The September events' `resolutionSource` is the same WRH URL for all 50 dates checked.
- **Hong Kong** (`…/highest-temperature-in-hong-kong-on-october-3-2026`):
  - **Source and column:** HKO "Absolute Daily Max (deg. C)" in the finalized Daily Extract via
    `https://www.weather.gov.hk/en/cis/climat.htm`, at one-decimal precision.
  - **Finality:** initial publication is the revisions cutoff.
  - **Missing data:** if there is no data by 23:59 ET on the seventh day, the market resolves to the
    lowest bracket.
  - **Brackets:** whole degrees, `24°C or below` … `34°C or higher`.

## Proposed roll-free diff to `config/locations.json` (NOT applied, do not merge before 2026-10-15)

The change below is not applied on this branch. `config/` is roll-free, but `_settlement_rules` copies
`source_type`, `precision` and `resolution_source_url` into the release-candidate settlement contract.
Landing it would change the settlement-rules payload of any candidate built afterwards, including the
10-15 exam manifest. Land it after the single look, together with a code change that gives Hong Kong
its own rounding rule.

New keys are additive; nothing in `src/` reads them today. The same block pattern applies to Paris
(`lfpb`), Seoul (`rksi`), Shanghai (`zspd`) and Tokyo (`rjtt`), with each city's current WU URL moved to
`fallback_source_url`.

```diff
     {
       "id": "london",
       ...
       "settlement": {
-        "source_type": "wunderground_history",
-        "resolution_source_url": "https://www.wunderground.com/history/daily/gb/london/EGLC",
+        "source_type": "nws_wrh_timeseries",
+        "resolution_source_url": "https://www.weather.gov/wrh/timeseries?site=eglc",
+        "resolution_view": "all_times_temp_column_metric",
+        "fallback_source_type": "wunderground_history",
+        "fallback_source_url": "https://www.wunderground.com/history/daily/gb/london/EGLC",
+        "finality": "first_datapoint_of_following_local_date",
         "station_id": "EGLC",
         "station_name": "London City Airport Station",
         "station_iata": "LCY",
         "station_wmo": null,
         "precision": "whole_degree",
         "unit": "C"
       },
     },
     {
       "id": "hong-kong",
       ...
       "settlement": {
         "source_type": "hong_kong_observatory_daily_extract",
         "resolution_source_url": "https://www.weather.gov.hk/en/cis/climat.htm",
+        "resolution_view": "daily_extract_absolute_daily_max",
         "station_id": "HKO",
         "station_name": "Hong Kong Observatory",
         "station_iata": null,
         "station_wmo": "45005",
-        "precision": "whole_degree",
+        "precision": "tenth_degree",
+        "band_mapping": "floor_to_whole_degree",
+        "finality": "initial_publication",
         "unit": "C"
       },
       ...
       "notes": [
-        "Non-Wunderground settlement source; needs a dedicated adapter before hard settlement floors are trusted."
+        "Non-Wunderground settlement source; needs a dedicated adapter before hard settlement floors are trusted.",
+        "Venue pays floor(HKO Absolute Daily Max): 10/10 resolved days 2026-09-20..29, four of which contradict half-up rounding (docs/research/foreign-settlement-desk-study-2026-10.md)."
       ]
     },
```

## Open questions and limits

- **Not covered:**
  - **Window size:** the sample is 10 dates in one season.
  - **Bracket edges:** at whole-degree METAR precision WRH and IEM cannot disagree at the shoulder, but
    a truncation-versus-rounding question like Hong Kong's could not arise and was not tested.
  - **Fallback never triggered:** no WU fallback happened in this window, so fallback behaviour is
    unobserved.
- **The display depends on a third-party token.** The WRH render is backed by Synoptic's public page
  token, and it was rate-limited (HTTP 429) during this study. A production adapter would need its own
  free route, or should keep using IEM, which matched 50/50.
- **Hong Kong's floor rule is a band-mapping change.** Anything that maps an HKO 0.1 °C value to a band
  with half-up rounding mislabels about 40% of days (4/10 here). Owners: the settlement ledger and the
  release-contract `band_contract.rounding`. Report only; no code changed.
