# Lowest-temperature desk study — pre-registration addendum A1 (2026-10-02)

Status: addendum to the pre-registration, frozen at the commit that adds it. That commit comes before any Q1-Q3
value is computed. Historical evidence once the report's addendum section lands.

| | |
| --- | --- |
| **Owns** | Estimands, data and decision rules for three owner questions (Q1 settlement definition, Q2 NBP minimum input, Q3 evening lows) added on 2026-10-02 after the first report. |
| **Read when** | Reading the "Addendum A1" section of [the report](../roadmap/agent-report-2026-10-02-lowest-temperature-desk-study.md). |
| **Parent** | [Pre-registration](lowest-temperature-desk-study-preregistration-2026-10-02.md) (`aa1fbdac`). The parent says it is never edited after its commit, so this addendum is a separate file. Nothing here changes F1, F2 or the go/no-go rule. |

## Boundaries (unchanged unless stated)

- Desk study. No capture, no credentials, no `src/` behaviour change, no model fit, no candidate, no α, no ledger row.
- **No 88a or exam data for UTC 2026-09-30..10-14 is read.** In addition, for this addendum:
  - IEM METAR requests end at **2026-09-30T00:00Z (exclusive)**. No observation at or after that instant is requested.
  - Whole-year responses (IEM CLI JSON, ECCC daily CSV) are cut at parse: rows dated 2026-09-30 or later are dropped
    before any value is stored or printed.
  - NBP tokens are used only when both the bulletin issue time and the token valid time are before 2026-09-30T00:00Z.
  - The Rules page is read from a lowest-temperature event whose target date is **on or before 2026-09-29**, so no
    exam-window book is the object of the read. Only the Rules text is recorded.
- New free sources, explicitly asked for by the owner on 2026-10-02: the Iowa Environmental Mesonet (IEM) ASOS archive
  and its NWS CLI archive, the ECCC climate bulk CSV (Toronto daily), and one Polymarket page rendered in the
  workstation browser pane. All are public and free; no credential is used.
- [Reserved confirmation window](../operations/reserved-confirmation-window.md): NONE RESERVED (checked 2026-10-02).

## What was looked at before this commit

- The parent pre-registration, the report and its analysis appendix (all committed).
- 95d `markets.csv` at `8c683766d` (read from git into a scratch directory, not `data/`): band labels only. Every
  lowest-temperature band for the 11 US cities is a 2 F band with an even lower edge ("68-69 F"); 333 markets per city
  (567 for Miami and NYC). Toronto bands are whole °C. No price, reward or outcome was tabulated.
- The workstation payload store `data/forecast_payload_cas/sha256/*.blob`: file sizes, modification dates
  (2026-07-13..08-12, about 176 files over 5 MB) and the first 300 bytes of three files (NBP headers
  `NBM V5.0 NBP GUIDANCE ... 1200/1300/1900 UTC`). No TXN value was read.
- `src/weather/sources/nbm_probabilistic_tmax.py` function names and the TXNP1/2/5/7/9 -> p10/25/50/75/90 map; EF §10k.
- Directory names under `data/eccc/cyyz` (hourly only; no daily file) and `data/metar`.
- No METAR, CLI, ECCC daily or NBP value has been fetched or computed for this addendum.

## Q1 — which minimum settles: hourly METAR rows or the daily summary/CLI?

**Data.** IEM ASOS archive (`/cgi-bin/request/asos.py`), stations ATL, AUS, BKF, DAL, HOU, LAX, LGA, MIA, ORD, SEA, SFO,
CYYZ, fields `tmpf` and raw `metar`, report types routine (3) and special (4), UTC 2026-07-31T00:00 to 2026-09-30T00:00.
Duplicate valid times keep the routine report. Temperature per row: the `T` remark group (tenths °C) when present,
otherwise the body temperature (whole °C), converted to °F for K stations; CYYZ stays in °C as reported.

**Study days.** Local civil dates **2026-08-01..09-28**. 2026-09-29 is dropped as a dated deviation from the request:
its local day ends 04:00-07:00Z on 09-30, past the request cap, so its minimum would be incomplete.

**Two minima per station-day.**
- **H (hourly-rows minimum):** min over all rows (routine + SPECI) whose valid time falls in the local civil day,
  rounded to a whole native degree (half up) after taking the minimum. Variant H_routine: routine rows only.
  Variant H_LST: the same over the Local Standard Time day (01:00-00:59 local clock during DST).
- **D (daily summary / CLI minimum):** US: the NWS CLI daily minimum from IEM's CLI archive (`/json/cli.py`), which is
  the climate day (LST). Where a station has no CLI product, D is the RMK 24-hour minimum group (`4sTTTsTTT`) of the
  report nearest 00:00 LST, labelled as such; if neither exists the station-day is "no D" and counted, not imputed.
  CYYZ: ECCC daily climate `Min Temp (°C)` for Toronto Pearson (station found in the ECCC inventory at run time; its
  climate day is ECCC's, recorded as found).

**Counts reported per station** over days with both values: days; H != D (value); **bucket disagreement**, F stations
`floor(H/2) != floor(D/2)` (the venue's even-edged 2 F bands), CYYZ `H != D` (1 °C bands); sign of D - H; and the same
two counts for H vs H_LST (day-boundary effect alone) and H_LST vs D (sampling effect alone).

**Rule (decides only what the report says, nothing operational).** If bucket disagreement H vs D is <= 2% of
station-days at every station, the H/D choice is **immaterial at band resolution** on this window. Otherwise it is
**material**, and which one the venue uses becomes a precondition for any settlement adapter. Data alone cannot say
which one the venue uses; that is answered only by the Rules text (below) and is labelled UNVERIFIED if the text does
not say.

**Rules page.** One lowest-temperature event (target date <= 2026-09-29, one of our 12 cities) rendered on
polymarket.com in the workstation browser pane. Recorded: URL, render date/time, the clauses on source, station, day
boundary, precision and fallback, and a SHA-256 of the whitespace-normalised Rules text. Clauses are quoted as
briefly as the workstation's copying limits allow; the hash lets anyone holding the full text check it.

## Q2 — NBP TXN minimum as a free forecast input (no scoring)

**Data.** Every blob in `data/forecast_payload_cas/sha256/` whose header reads `NBM ... NBP GUIDANCE`; issue time from
the header line. Station blocks for the 11 US stations (and CYYZ if a block exists, flagged).

**Provenance (EF §10k).** Each column's valid time comes from the bulletin's day and `UTC` rows. A `TXN*` token is a
minimum only if its column's valid hour is 12Z; 00Z tokens (maxima) are discarded. Valid date = the UTC date of that
12Z column (for US stations, the morning of that local date). Rows used: TXNP1, TXNP2, TXNP5, TXNP7, TXNP9
(p10, p25, p50, p75, p90), TXNMN, TXNSD. A station-date row is kept only if all five percentiles parse.

**Checks, reported not scored.** (1) Internal: share of 12Z tokens whose TXNMN is below the TXNMN of both neighbouring
00Z tokens (expected near 1 if the 12Z tokens are minima). (2) Monotonicity p10 <= p25 <= p50 <= p75 <= p90.
(3) Magnitude, as in EF §10k: median of p50 minus the observed IEM minimum over local 19:00 (previous day) to 08:00 for
the shortest-lead token, on dates that overlap Q1's IEM pull. It is a provenance check (are these minima?), not skill:
no interval, no comparison with any market, no model.

**Output.** One row per (station, valid date, cycle) with lead hours; a summary per station (station-dates, cycles,
median p90 - p10 by lead band 0-24 / 24-48 / 48-72 h); and the headline per station-date row from the latest cycle
issued before the token's valid time.

## Q3 — share of daily lows reached after 18:00 local, by month

Extends the report's hour-of-minimum table. Same WU hourly data, same eligibility rule and local civil day as the
parent pre-registration, 2016-2025 (and 2026-01..08 descriptively).

- **Primary:** share of eligible days whose day minimum is **first** reached at local hour >= 18 (the low was not reached
  before 18:00), per city x calendar month and fleet (equal-weight mean of the 12 cities).
- **Secondary:** share whose minimum is reached or tied at hour >= 18 (last attainment >= 18).
- Fleet interval per month: 95% percentile bootstrap over the 10 years (10,000 draws, seed 20261002), as the parent.
  Descriptive; no threshold, no decision.

## Labelling

Every table in the report's addendum section is labelled **MEASURED** (computed here from named data) or
**UNVERIFIED** (asserted from documents or definitions not checked against data or the Rules text).

## Update this file when

Never after its commit. Corrections go in the report as dated deviations.
