# Denver KDEN vs KBKF venue-rule daily max, 2026-07-31..09-29 (2026-10-23)

Status: dated research note, workstation desk study (item 7, lane F, of the 2026-10-23 more-markets work), read-only.
No code, config, scheduled-task or capture-host change was made. It asks whether Buckley (KBKF), the station in the
built-in Denver spec, WU store and `config/locations.json`, can stand in for Denver International (KDEN), the station
the venue names from the 2026-10-23 event onward. It extends
`docs/research/metar-vs-wu-agreement-2026-10-23.md` (on `claude/research-metar-wu-agreement-20261023`, not yet on
master), which measured KBKF only.

**Number labels.** **[M]** = measured here, with its method. **[C]** = computed from measured inputs. **[NM]** = not
measured, with the reason.

## Answer in five lines

1. **The venue switched Denver to KDEN with the 2026-10-23 event** [M, metadata]. In the git history of
   `config/location_market_events.json`, the latest Denver event naming KBKF is 2026-10-22 and the earliest naming KDEN
   is 2026-10-23. Public Gamma metadata agrees (10-20 and 10-22 name Buckley; 10-23 names KDEN).
2. **KBKF is a poor proxy for KDEN under the venue rule.** Over 61 local dates, the two daily maxima match exactly on
   **9/61 (14.8%)** and are within 1 °F on 34/61 [M].
3. **KDEN runs cooler.** Mean KDEN − KBKF = **−1.08 °F** (mean absolute 1.44 °F). KDEN was lower on 43 days, equal on 9
   and higher on 9 [M].
4. **38/61 days (62%) land in a different 2 °F band** under the assumed even-start ladder. Under an odd-start ladder the
   figure is 41/61 [M].
5. **Recommendation:** for event dates from 2026-10-23, switch Denver's label to KDEN. Do not reuse the KBKF-trained model
   for KDEN events, even with an offset; see [Recommendation](#recommendation).

## Data and method

**Fetch** [M]. Owner-approved, free, read-only: one IEM ASOS request per report type for KDEN, two requests in all.
The endpoint was `mesonet.agron.iastate.edu/cgi-bin/request/asos.py`. Parameters were identical to the earlier study:
UTC 2026-07-31 00:00 to 2026-10-01 00:00 (exclusive), `report_type` 3 (routine) and 4 (special) fetched separately.
KDEN returned 1488 routine and 129 special rows. The KBKF files are the earlier study's, reused unchanged. The files
are kept in the session scratchpad, not in the repository or `data/`. SHA-256 prefixes: KDEN_rt3 `d54919e6`, KDEN_rt4
`8fd68f31`, KBKF_rt3 `56362303`.

**Venue-rule daily max** [M]. This follows the venue's 10-23 Rules, as in the earlier study's venue-rule series.

- **Reports:** `report_type=3` (routine) only, so SPECIs are excluded. Corrected routine reports (`COR`) are kept.
- **Temperature:** the RMK `T[01]ddd[01]ddd` group, in tenths of °C. Where that group is missing or malformed, the
  body `TT/` whole °C is used instead.
- **Conversion:** `weather.units.c_to_native(c, "F")` (°C x 9/5 + 32), then `round_half_up` on each report.
- **Daily value:** the max per local date of `valid`, in `America/Denver`. The time zone comes from
  `spec_for_id("denver").tz`.
- **Date filter:** rows with a local date after 2026-09-29 are dropped before use.

**IEM `tmpf` precision** [M]. IEM `tmpf` is never used for the label. It appears only in a per-report diagnostic.

- **KDEN:** `tmpf` is almost all whole °F (1451/1464 reports). Half-up `tmpf` equals the T-group half-up value on
  1464/1464 reports.
- **KBKF:** `tmpf` carries one decimal of °F (fractions .2 to .8 on 924/1457 reports). Half-up `tmpf` exceeds the
  T-group value by 1 °F on 50/1457 reports. Every one of those 50 has a `tmpf` ending in `.50`: IEM's rounding to 0.1 °F
  lands on x.5, and half-up then rounds it up again. This is the KBKF "0.5 °F" artefact the earlier study found.
- **Handling:** reading the raw T-group bypasses the artefact, the same way the earlier study's venue-rule series did.

**Coverage** [M].

- Both stations have all 61 local dates (2026-07-31..09-29).
- KDEN has at least 24 routine reports every day. KBKF has 22-23 on six days (08-13, 08-15, 08-19, 08-24, 09-10, 09-25).
- KDEN had 16 routine reports with no T-group that the strict pattern accepts. 15 carry a malformed group: a wrong
  digit count, a group fused to `SLP`, or a truncated value (for example `T0333044`, `SLP169T01720111`,
  `T012390072`). One has no group at all. KBKF had none. The body value was used for these 16. Any KDEN label
  implementation needs an explicit rule for malformed groups, because the venue's own parser behaviour is unknown [NM].
- **Sensitivity check** [M]. Shifting each of those 16 body values by −0.5 °C or +0.4 °C changes no daily max. None of
  them sets a day's maximum.

**Band ladder (assumption).** The ladder is the earlier study's: interior 2 °F bands starting on even degrees (e.g.
`76-77°F`), tails ignored. A flip is `floor(KDEN/2) != floor(KBKF/2)`. The Aug-Sep ladders were not read. The
odd-start figure (`floor((x-1)/2)`) is given as a sensitivity.

## Results

All values are venue-rule daily maxima in °F, over local dates 2026-07-31..09-29.

| Measure | Value | Label |
| --- | --- | --- |
| n (dates with both stations) | 61 | [M] |
| Exact match KDEN = KBKF | 9/61 (14.8%) | [M] |
| Within ±1 °F | 34/61 (55.7%) | [M] |
| Mean KDEN − KBKF | −1.08 °F | [M] |
| Mean absolute difference | 1.44 °F | [M] |
| Mean KDEN − KBKF in tenths °C, before rounding | −0.58 °C | [M] |
| 2 °F band flips, even-start ladder (assumed) | 38/61 (62.3%) | [M] |
| 2 °F band flips, odd-start ladder (sensitivity) | 41/61 (67.2%) | [M] |

**Distribution of KDEN − KBKF (°F, count of days)** [M]

| −8 | −3 | −2 | −1 | 0 | +1 | +2 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 3 | 21 | 18 | 9 | 7 | 2 |

**By month** [M]

| Local month | n | Mean diff | Exact | Histogram |
| --- | --- | --- | --- | --- |
| 2026-07 (07-31 only) | 1 | −2.00 | 0 | −2:1 |
| 2026-08 | 31 | −0.94 | 6 | −3:3, −2:9, −1:8, 0:6, +1:4, +2:1 |
| 2026-09 (to 09-29) | 29 | −1.21 | 3 | −8:1, −2:11, −1:10, 0:3, +1:3, +2:1 |

**By local hour of the KDEN maximum** (first report reaching the max) [M]

| KDEN max hour (MDT) | n | Mean diff | Exact |
| --- | --- | --- | --- |
| 09-11 | 2 | 0.00 | 0 |
| 12-14 | 34 | −1.32 | 4 |
| 15-17 | 25 | −0.84 | 5 |

- **Hour of the maximum** [M]. The maximum fell in the same local hour at both stations on 21/61 days. Peak hours are
  similar in shape: KDEN mostly 13-15 h, KBKF mostly 12-15 h.
- **Is the difference systematic?** Descriptively, yes. KDEN is cooler in both months and in both main hour groups. The
  gap is larger when KDEN peaks at midday (12-14 h) than in the afternoon. 43 of the 52 non-zero days are negative.
- **Outlier, 2026-09-16** [M]. KDEN 81 vs KBKF 89 (−8 °F). KDEN's routine reports show a wind shift with gusts around
  14:53 local, and its max stayed near 27 °C. KBKF reached 31.8 °C at 13:58. The KDEN `10283` six-hour group (28.3 °C)
  and its SPECI at 15:01 (27.8 °C) agree that KDEN never approached KBKF that day. This was a real station difference
  on a frontal day, not a parsing error.
- **Other −3 °F days:** 08-10, 08-15 and 08-22.

## Station switch date (metadata only)

**Method** [M]. A scratch script walked every commit of `config/location_market_events.json` (`git log` plus
`git show <commit>:<path>`). For each Denver entry in `active_events` it printed only `event_date` and
`resolution_source_url`. It then made three public read-only Gamma `GET /events?slug=...` requests (10-20, 10-22 and
10-23), printing only `resolutionSource` and the station named in `description`. No prices, outcomes or settlement
fields were read.

| Event dates (as captured in config history) | Resolution source | Station |
| --- | --- | --- |
| 2026-06-20 .. 2026-08-22 | `wunderground.com/history/daily/us/co/aurora/KBKF` | KBKF (WU) |
| 2026-08-23 .. 2026-10-22 | `weather.gov/wrh/timeseries?site=kbkf` | KBKF (NOAA; the switch already covered by mission 86a) |
| 2026-10-23 .. 2026-10-25 | `aviationweather.gov/api/data/metar?ids=KDEN&...` | KDEN |

- **Latest event naming KBKF:** 2026-10-22 (config history). Its Gamma description names the "Buckley Space Force Base
  Station". 10-20, which is absent from config history, names the same station.
- **Earliest event naming KDEN:** 2026-10-23 (config history, first captured in `41119c42e`). Its Gamma description
  names "Denver International Airport (KDEN)" and the routine-METAR, tenths-°C, local-date rule.
- Some event dates never appear in config history (for example 10-20), because the file keeps only active events at
  each snapshot. The 10-22 → 10-23 boundary is confirmed by both sources.

## Recommendation

**Switch Denver's label station to KDEN for event dates from 2026-10-23. Do not reuse the KBKF model for those events,
even with a bias correction.**

- **Evidence: the label.** Under the venue's own rule, KBKF would give the wrong 2 °F band on about 62% of Aug-Sep
  days, and the right integer on only 15%. Any KBKF-based Denver label from 10-23 is mislabelled most of the time.
- **Evidence: the model.** The difference is not a fixed offset. The mean is −1.1 °F, but the spread runs from −8 to
  +2 °F, and only 21/61 days peak in the same hour. A shift from KBKF to KDEN would not preserve probability mass per
  band.
- **What KDEN needs:** its own training history and serving inputs, with train/serve parity and a release binding,
  through the normal model gates.
- **Until then:** treat Denver events dated 10-23 onward as unsupported for model-driven quoting.
- **This note does not change** `config/locations.json`, the spec or the WU store. That is a separate,
  owner-decided change.
- **[NM] KDEN vs the venue's settled values.** Prices and outcomes were not read by design.
- **[NM] KDEN WU history.** `data/` was not read.

## Reproduction recipe

The scratch scripts are not committed. To redo the study:

1. **Fetch.** Make one serial GET to `https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py` for each
   `report_type` in (3, 4), with `station=KDEN` (repeat for KBKF if needed). Use the parameters `data=tmpf`,
   `data=tmpc`, `data=metar`, `year1=2026&month1=7&day1=31`, `year2=2026&month2=10&day2=1`, `tz=Etc/UTC`,
   `format=onlycomma`, `latlon=no`, `missing=M`, `trace=T`, `direct=no`, `report_type=<n>`, and sleep about 4 s
   between requests.
2. **Daily max.** With `PYTHONPATH=<worktree>/src`, read the `report_type=3` file and set
   `tz = spec_for_id("denver").tz`. Convert each row's `valid` (UTC) to local time, and drop local dates outside
   07-31..09-29. For each report:
   - take the RMK `\sT([01])(\d{3})([01])(\d{3})(?:\s|$)` group as tenths °C, or else the body `\s(M?\d{2})/(M?\d{2})?\s`;
   - convert with `round_half_up(c_to_native(c, "F"))` (`weather.units`).

   Then take the max per local date.
3. **Compare.** Set diff = KDEN − KBKF per date. Count exact matches, build the integer histogram, and count flips
   `floor(x/2)` (even-start) and `floor((x-1)/2)` (odd-start). Group by local month and by the local hour of the first
   KDEN report reaching the max.
4. **Switch date.** For each commit in `git log -- config/location_market_events.json`, parse
   `git show <c>:config/location_market_events.json`. For the `location_id == "denver"` entry, print
   `active_events[].event_date` and `resolution_source_url`. Optionally make a Gamma
   `GET https://gamma-api.polymarket.com/events?slug=highest-temperature-in-denver-on-<month>-<day>-2026` and read only
   `resolutionSource` and the station sentence in `description`.
