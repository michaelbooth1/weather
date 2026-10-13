# Lowest-temperature desk study — pre-registration (2026-10-02)

Status: pre-registration, frozen at the commit that adds it. Historical evidence once the report lands.

| | |
| --- | --- |
| **Owns** | The estimands, falsifier rules, data and analysis choices for the workstation desk study of Polymarket "lowest temperature" markets for our 12 cities. |
| **Read when** | Reading or checking [the report](../roadmap/agent-report-2026-10-02-lowest-temperature-desk-study.md), or before reusing these falsifiers on the post-10-14 recorder capture. |
| **Origin** | Falsifiers come from [the 2026-10-01 expansion swarm](../roadmap/audits/swarm-expansion-2026-10-01.md), Top 3 item 1. |

## Question

Are Polymarket lowest-temperature markets for our 12 cities workable for a reward-driven maker with our existing free data,
and should the venue recorder capture them passively after 2026-10-14?

This is a descriptive desk study. It fits no model, scores no forecast, produces no candidate, spends no α (no
[CAMPAIGN_LEDGER](../operations/CAMPAIGN_LEDGER.md) row; it is not a model decision), and places no order.

## Boundaries

- Workstation data only, plus files that would need a production transfer manifest (listed, not fetched).
- No 88a or exam data for UTC 2026-09-30..10-14 is read. No venue or provider call is made.
- [Reserved confirmation window](../operations/reserved-confirmation-window.md): NONE RESERVED at run time (checked 2026-10-02).

## What was looked at before this commit

Disclosed so the order is auditable: file layout and column names of `data/wunderground/<icao>/hourly` and
`daily/daily_summary.csv`; the year/month partition list per station (WU hourly 1982/1995/1997..2026-08); three tail rows of
KORD `daily_summary.csv` (2026-08-07/09/10; daily min values, no timing); the 95d `families.json` record for lowest
temperature / Austin (metadata, pool 0); the swarm audit and 95d/86a reports. No hour-of-minimum, undercut share or band mid
for any lowest-temperature market was computed or read.

## Data

- **Primary observations:** WU history hourly rows (`temp_native`, `valid_time_local`, `minute`) under
  `data/wunderground/<icao>/hourly/year=*/month=*/observations.jsonl` for the 12 configured stations (CYYZ, KATL, KAUS,
  KBKF, KDAL, KHOU, KLAX, KLGA, KMIA, KORD, KSEA, KSFO). WU is the settlement proxy by repository contract; rows include
  non-routine (special) reports. Rows with a null `temp_native` are dropped; duplicate `valid_time_utc` keep the first.
- **Settlement definition:** the retained 95d inventory (`docs/roadmap/weather-market-universe-20260924/`, bulk files from
  commit `8c683766d`) records per family the rule-URL station ids, source regime, native unit and precision, and a SHA-256
  of the raw rule text. The raw text itself is not on the workstation; anything not in those fields is reported UNVERIFIED
  and listed for a transfer manifest.
- **Band snapshot:** 95d `markets.csv` / `book_samples.json` (public, retrieved 2026-09-24, before the exam panel).
- **Forecast inputs:** inventory only from code and EF §10k (NBM `TXN` 12Z-valid tokens are minima); no skill is measured.

## Day definition

Primary: the market's local civil calendar day, 00:00-23:59 in the station's IANA time zone (as `MarketSpec` and the 95d
proposals record for the highest-temperature family). A day is **eligible** when it has observations in at least 20 distinct
local clock hours, including at least 7 of the 9 hours 00-08.

## Primary estimand and falsifier F1

For city c and eligible day d, with `m_am` = min `temp_native` over observations with local time < 09:00 and `m_pm` = min over
observations with local time >= 09:00: day d is **undercut after 09:00** when `m_pm < m_am` (strict; a later tie does not
change the settled value).

- `p_c` = share of eligible days undercut, over the **primary window**: local dates 10-15..12-31 of seasons 2016-2025
  (10 seasons; the months the post-10-14 capture would run). Fleet `p` = equal-weight mean of the 12 `p_c`.
- Interval: 95% percentile bootstrap over season-years (resample the 10 years with replacement, all cities' days of a year
  together; 10,000 draws, seed 20261002). Per city, the same resampling on that city's days.
- **F1 rule (threshold 0.30, from the swarm):** FALSIFIED if the interval's lower bound > 0.30; SURVIVES if its upper bound
  <= 0.30; otherwise INCONCLUSIVE. Applied to the fleet and to each city.

## Falsifier F2 — rewarded bands outside the mid range

Not testable on the workstation: nothing captures minute books for lowest-temperature conditions. Registered for the
post-10-14 recorder capture: a rewarded condition-minute is a minute in which the venue's current reward record for the
condition has a nonzero rate; mid = (best bid + best ask) / 2 of the YES book. **F2 FALSIFIED** if more than 80% of rewarded
condition-minutes, pooled over the 12 cities and the first 14 captured local days, have mid < 0.10 or > 0.90. Today only a
descriptive cross-sectional count from the 95d 2026-09-24 snapshot is reported: share of our 12 cities' lowest-temperature
markets with a nonzero current reward whose best-bid/best-ask mid is outside [0.10, 0.90]. It is labelled a snapshot and
decides nothing.

## Secondary, descriptive (no decision)

1. Hour-of-minimum: local clock hour of the first and of the last observation attaining the day minimum, per city, primary
   window and full year 2016-2025.
2. Decided-by curve: share of eligible days on which the running minimum at the end of local hour h equals the day minimum,
   h = 0..23, per city, primary window.
3. F1 sensitivities (same estimator): full year 2016-2025; 2026-01-01..2026-08-10; cut-off 06:00 and 12:00 instead of 09:00;
   undercut by >= 2 native degrees; WRH "Hourly Data" proxy (minutes 51-59 for K stations, 56-04 for CYYZ, per 86a);
   Local Standard Time day (during DST the day runs 01:00-00:59 local).

## Go/no-go for passive recorder capture after 10-14

- **GO** for the family if fleet F1 is not FALSIFIED; capture the cities whose own F1 is not FALSIFIED.
- **NO-GO** if fleet F1 is FALSIFIED and fewer than 3 cities survive individually.
- F2 cannot block passive capture (capture is what measures it); it blocks any later quoting plan.
- Settlement facts that remain UNVERIFIED are listed as preconditions for any settlement adapter, not for passive capture.

## Update this file when

Never after its commit. Corrections go in the report as a dated deviation.
