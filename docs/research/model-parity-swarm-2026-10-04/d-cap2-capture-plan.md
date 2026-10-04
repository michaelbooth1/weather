# D-CAP2: production capture-plan draft for IEM METAR and IEM MOS (DESIGN ONLY, development)

> **DRAFT. DESIGN ONLY. DEVELOPMENT.** Written by swarm agent D-CAP2 on 2026-10-04, about 03:00 local, on
> the workstation. No code, config, Scheduler, serving or capture change has been made, and nothing here
> authorises one. Every number is a development read on dates that 79a/81a/111h already inspected
> (DESIGN rule 7). Nothing was scored, so nothing was registered and there is no HARNESS_SHA256 result.
> Production data was not read; the production code was read in the swarm worktree `C:\pt\swarm`.

## Verdict

1. **METAR/SPECI: no new capture.** Production already fetches the aviationweather.gov (AWC) METAR JSON
   for every market on every capture pass (about every 9 min) and retains the raw payload. Every input the
   remaining-rise / decided-band family and the D-DEFECT evening restoration need is captured today:
   running max (`guidance_physical_floor`), current reading (`current_temp` / `metar_temp`), the rows, and
   therefore the time of the max. What is missing is **capture hardening**, not a source:
   - **M1. Persist per-report `receiptTime`** (it is in the AWC JSON that production already stores raw;
     `parse_metar_payload` drops it). This replaces the constant valid+10 min availability basis with a
     measured one and fixes the KBKF (Denver) case, where valid+10 is optimistic (T26: median lag 10.4 min,
     p95 113 min, 80.7% of reports later than +10).
   - **M2. Parse report type (METAR/SPECI), the COR token and the T-group tenths** into the stored rows, or
     prove they are replay-derivable from the retained raw text, so the serve-side stage and the
     history-built tables use one shared parser (train/serve parity by shared code).
   - **M3. Make the stale/missing METAR path an explicit stage fallback** (served unchanged), and record it.
   - **M4. A versioned history-table builder** for the frozen-table forms (T1 q table, T2/T3 remaining-rise
     pmf): extend `weather.sources.metar_history` (today it pulls IEM `tmpc` only, no raw text, no report
     type, no COR flag) or add a sibling builder, with the fit cutoff and refresh policy bound into the release.
2. **IEM MOS (MAV/MET/MEX/LAV + NBE): do not capture.** The MOS-specific increment over captured inputs is
   null: T7 control c1 (captured NBM v2_mean) carries about 90% of the morning gain; paired r1 - c1 00-16
   is -0.0015 [-0.0049, +0.0019] (statistics refuter); T7-r2's 17-23 gain is the decided-band family. The
   only residual sign is t7-r2 at 13-14 over ladder rung 2 (-0.0063 [-0.0119, -0.0006], 10/11), which is a
   post-hoc hour slice and is **not** an increment over the no-source t3-r3 rung (-0.0031 [-0.0077, +0.0017]).
   An optional, research-only shadow capture (section 4.4) is costed for completeness in case the owner wants
   to keep that 13-14 question alive prospectively; the default recommendation is decline.
3. **Countability.** The drafts that lean on METAR (evening WU-anchor restoration, the 13-16/15-16
   remaining-rise table, and the floor in MG-1) become countable on new dates without any new source, once
   M1-M3 are live and verified for a full prior day and the stage runs in shadow with a replay check
   (section 5). No draft needs MOS.

## 0. Inputs read (all development; no number re-derived here)

- T20 serveability map (`C:\swarm\out\t20\result.json` report_md): what production captures, cadence, code lines.
- T26 METAR PIT re-derivation from AWC `receiptTime` (`C:\swarm\out\t26\report.md`).
- A-IEM-1 (METAR), A-IEM-2 (MOS; reconstructed report, cited from its `result.json`), A-IEM-3 (neighbours).
- T7 and its refuters (R-PIT-T7 report; R-STAT-T7 board line), LADDER, D-DEFECT, D-RUNG1C, D-MORNING.
- Production code: `src/weather/model/model_sources.py` (`fetch_metar` :1353, `parse_metar_payload` :1312,
  `metar_query_hours` :1400, `parse_utc_time` :2403), `src/weather/sources/metar_history.py`,
  `src/weather/model/model_distribution.py` (lock-in stages; `official_current_stale` :530).

## 1. Which board items depend on these sources

| Board item | Source role | Status after verification | Capture consequence |
|---|---|---|---|
| D-DEFECT / LADDER rung 1 (evening WU-anchor restore S1/S2/S6 + S7 gate; D-RUNG1C: bundle S3-S5) | METAR running max + `max_times` + current reading | 17-23 -0.0252 [-0.0350, -0.0174], 85% of gap, 11/11 (development) | None new; M1-M3 hardening |
| T1 / T2 / T3 / T4 / T15 / T16 (remaining-rise / decided-band family) | IEM METAR history (fit <= 07-31) + at-t METAR | LEAD in 17-23, but an unconditional collapse does as well; treated as a serving defect | None new; M4 if a frozen table is ever served |
| t3-r3 at 15-16 (the 13-16 residual; D-RUNG1C) | IEM METAR history table + at-t METAR | beats rung 2 at 15-16 by -0.0181 [-0.0251, -0.0112], 11/11 | M1-M4 (frozen table) |
| T7 MOS/NBE consensus | IEM MOS (MAV/MET/MEX/LAV/NBE) | MOS-specific increment null; 13-14 borderline only | Decline (section 4) |
| T13 neighbours, T14 sky cover | IEM neighbour METAR; METAR `cover` | WEAK/NULL | Decline neighbours; `cover` already captured |
| T17 information arrival | METAR timing | study only | M1 makes the arrival study repeatable on new dates |
| MG-1 morning (D-MORNING draft) | METAR only through the 81a floor | parser-v2 dependency, not METAR | M3 (floor fallback) only |

## 2. METAR/SPECI: what production does today

- **Source.** `https://aviationweather.gov/api/data/metar?ids=<ICAO>&format=json&hours=<n>` (free, public
  NWS AWC, no key). `n = min(24, elapsed local hours + 2)`, so every pass carries every report since local
  midnight (`metar_query_hours`, :1400). `parse_utc_time` converts `reportTime` to station-local time and
  rows are filtered to the target local date (:1318), so the floor is a true since-midnight max across DST
  (DST ends 2026-11-01; the filter is tz-aware).
- **Cadence.** One fetch per market per capture pass. Snapshot gap median 9.1-9.2 min, p10 2.5-4 min,
  168-186 snapshots per market-day (T20). Not cached (only the Open-Meteo family reuses a cached fetch).
- **Latency.** AWC receipt - valid: median 3.2-4.5 min at 10 stations, KBKF 10.4 min (T26). Production picks
  up a new METAR max about 3.8 min after valid time (T17). Effective serve latency is therefore receipt lag
  plus up to one pass gap: typically 4-14 min, KBKF up to about 2 h on its tail.
- **What is stored.** `raw_payload` (the full AWC JSON, retained per snapshot, content-addressed:
  `collection/snapshot_store.py:1640-1720`, T20) plus parsed rows (`time`, `datetime`, `report_time`,
  `temp_native` from AWC `temp` in deg C with T-group tenths, converted to native deg F **unrounded**,
  dewpoint, wind, `cover`, `raw`). Derived features: `current_temp`, `same_day_max`, `max_since_7am`,
  `guidance_physical_floor` (max of all day rows), `high_so_far` (a running max only from 07:00; before 07:00
  it is the current reading). `trusted_current_max` is null on 100% of rows (WU off).
- **What is dropped.** `receiptTime` (and `obsTime`) from each AWC row; there is no parsed report type, COR
  flag or T-group field (they are recoverable from `raw` text). This is the M1/M2 gap.
- **Disk.** Already being spent. AWC JSON is about 570 bytes per report (T26: about 4.4 MB for 7,672
  reports). A payload carries up to about 30 reports (about 17 KB); a new unique payload appears roughly
  once per new report (about 26-35 per station-day). Upper estimate: about 0.3-0.5 MB per station-day,
  i.e. **about 100-170 MB per month for the 11 US markets**, if no payload deduplicates (estimate; not
  measured on the capture host, because production data is out of scope tonight). M1/M2 add a few fields per
  parsed row: well under 1 MB/month.

## 3. METAR capture plan (hardening, no new source)

### M1. Per-report receipt time (availability evidence)

- **What.** Copy AWC `receiptTime` (and `obsTime`) into each parsed row as `receipt_time_utc` /
  `obs_time_utc`. Add the production `response_received_at` of the payload (already the availability basis
  used for NBM). At serve time no extra availability rule is needed: **a report present in a payload
  received at or before `captured_at_utc` is point-in-time by construction.** `receiptTime` is needed for
  parity with the history tables and for audit, not for serve PIT.
- **Why.** The hunters' basis valid+10 is conservative at 10 stations but optimistic at KBKF (T26: 288 of
  the 317 leakage-direction running-max changes on 09-05..09-29 are KBKF). Any future pre-registration should
  state availability per report, not a constant offset (T26 section 5).
- **History parity.** IEM `asos.py` has no ingest time and AWC retention is only about 25 days (T26: AWC held
  2026-09-04..09-29 on 10-04). So history tables keep a declared constant offset, **per station**: valid+10
  for 10 stations, and for KBKF a declared larger offset (for example its measured p95, about +115 min), fixed
  before any fit, or KBKF excluded from table fitting. M1 then lets each new month's live lags be compared
  with the declared offset (a drift check, not a refit).
- **Code surface.** `model_sources.py` `parse_metar_payload` (add two fields), feature-store diagnostics
  (non-selectable), snapshot schema doc. Roll-sensitive (loop-imported module): quiet-window merge only.

### M2. Report type, COR and T-group in parsed rows

- **What.** Parse from `raw`: report type (`METAR`/`SPECI`; AWC JSON carries `metarType` too, to be checked
  on one captured payload), a COR flag (token after the time group), T-group tenths and the body integer.
- **Why.** The history tables (A-IEM-1 tidy) exclude COR and distinguish routine/SPECI; production uses every
  row and does not filter COR (T20 section 3). The value difference is small (IEM T-group F equals AWC
  real-time value on 7,493/7,493 matched rows, T26), but **the rule must be identical at fit and serve**:
  one shared parser function in `src/weather/sources/` used by both the history builder (M4) and the serving
  stage. Declared rule: exclude COR at both ends; when a COR replaces an hour, that hour is missing (the
  conservative choice the hunters disclosed).
- **Units.** Declare one conversion: T-group deg C tenths -> deg F unrounded, then the band rule's own
  rounding. KBKF is the known edge (its T-groups are not whole-F; T16).
- **Alternative to new fields.** If owners prefer no schema change, M2 is satisfied by a pinned, tested
  replay function over the retained `raw_payload`; the pre-registration then cites that function's code hash.

### M3. Stale and missing METAR

- **Failure modes.** (a) AWC outage or HTTP error -> last-good payload served, flagged `stale`
  (`official_current_stale`, `model_distribution.py:530`). (b) Station outage or thin reporting (KBKF had 30
  thin days in 882; COR replacement gaps about 2.3% of hours, T26). (c) Late-arriving reports (KBKF tail,
  routine :58 reports received :12-:24 next hour). (d) AWC retention/`hours` cap: the 24 h cap is safe for a
  since-midnight query; a fetch after a long outage still recovers the whole day. (e) Floor null on 0.1-2%
  of rows (T20). (f) Capture-host disk pressure or STALE_CODE restarts dropping passes (a gap in snapshots,
  not in reports: the next pass recovers every report since midnight).
- **Rule.** Any METAR-anchored stage falls back to served when the METAR source is stale beyond one declared
  age (for example no payload received in the last 30 min) or the floor is null, and records the reason.
  The fallback share is a validity condition in every draft (section 5).
- **Backup source (optional, not recommended now).** IEM `asos.py` live or `api.weather.gov` station
  observations are free alternatives, but a second source adds a parity surface (different receipt
  behaviour, no receipt time at IEM). Keep AWC as the single serve source; use IEM only for history.

### M4. History-table builder for frozen-table forms

- Needed only for forms B/C in T20 (T1 q table; T2/T3 remaining-rise pmf by station x month x hour, about 3k
  cells). Form A (D-DEFECT restore) needs no table.
- **Code surface.** `src/weather/sources/metar_history.py` today requests `tmpc,dwpc,...,skyc1-3,wxcodes`
  (`DATA_FIELDS`) and no raw `metar` text or report type. Extend it, or add a sibling builder, to request
  report types 3 and 4 separately with the raw text (as A-IEM-1 did), parse with the M2 shared parser, and
  write a versioned table artifact under `artifacts/` with: fit window (ending 2026-07-31 for the drafted
  rules, or a declared later cutoff that precedes the evaluation window), station list, availability offsets
  (M1), COR rule, conversion, code hash and sha256, bound into the release manifest.
- **Cost.** IEM: 220 requests, about 28 MB parquet for 11 stations x 29 months (A-IEM-1); a monthly refresh is
  about 1 MB and about 22 requests at IEM's 1 req/s politeness. Runs on the workstation, not the capture host.
- **Refresh policy.** Declared before the freeze (for example frozen for the whole evaluation window). A
  monthly refresh during an evaluation is a model change and is not allowed inside a reserved window.

## 4. IEM MOS: decline, with the costed alternative

### 4.1 Evidence (development)

- T7-r1 (literal consensus) 00-16 -0.0137, but control c1 (captured NBM v2_mean, same shape) -0.0122: about
  90% of the morning gain needs no MOS. Paired r1 - c1 00-16 -0.0015 [-0.0049, +0.0019] (R-STAT-T7).
- T7-r2 17-23 -0.0280 is the decided-band family (R-PIT-T7: almost unchanged with all models at +6 h, LAV only,
  NBE only gives -0.0053). It is served by the rung-1 restoration with no MOS.
- Over LADDER rung 2: t7-r2 00-16 -0.0047 [-0.0092, -0.0004] 10/11 (before -0.0026); 13-14 -0.0063
  [-0.0119, -0.0006] 10/11; but against the no-source t3-r3 rung at 15-16 +0.0006, and t7-r2 vs t3-r3 at 13-14
  -0.0031 [-0.0077, +0.0017]. LADDER's verdict: borderline, WEAK at most.
- Multiplicity: T7 registered 7 rules; the swarm registry holds over 100. A 13-14 slice found after scoring
  is a forking-path result and is not a basis for a capture decision (rule 8 also forbids choosing an hour
  gate on this table).

### 4.2 Availability: why IEM cannot make a MOS rule countable

- IEM MOS has no ingest timestamp. In the swarm, NBE/NBS use measured S3 LastModified (median 57-80 min,
  re-uploads up to 29 h are conservative); MAV uses NCO schedule evidence (+4h30); MET, MEX and LAV are
  **assumed** (+4h00, +5h00, +1h00), not measured (A-IEM-2 result.json; R-PIT-T7 section 1).
- Under a strict rule 1 only the NBE-only variant (t7-r4) is fully measured, and its 17-23 effect is only
  -0.0053. A prospective MOS pre-registration would therefore be countable **only** if production records
  its own first-seen time per bulletin; re-reading the IEM archive after the fact would not be point in time.

### 4.3 Default: decline

No MOS capture, no MOS code in `src/weather`, no MOS pre-registration. Close "capture MOS for the morning"
with the c1 evidence, and the 17-23 MOS reading as the decided-band family.

### 4.4 Costed alternative (only if the owner wants the 13-14 question answered prospectively)

- **Scope.** Research-only shadow capture, never a serving input: MAV (GFS MOS, 4 runs/day) and NBE
  (`s3://noaa-nbm-grib2-pds/blend.YYYYMMDD/HH/text/blend_nbetx.tHHz`, 00/12Z at minimum) for the 11 stations.
  MET/MEX/LAV add little (t7-r2 without LAV still -0.0221 in 17-23; morning increment is NBM-driven).
- **Endpoint.** NWS MOS text bulletins from NOMADS/tgftp (free, public; exact product paths to be confirmed
  at implementation, not measured tonight) for MAV; anonymous S3 for NBE. **Not IEM** as a live production
  dependency (rate-limited university service, no receipt time).
- **Availability.** Per object: `first_seen_at` / `response_received_at` from production plus S3
  LastModified for NBE. These are the only bases a prospective rule could count.
- **Cadence.** Poll after each scheduled run (MAV about +4h15 per NCO schedule; NBE after its LastModified,
  median about 80 min), not on every 9-min pass: about 6-30 small requests/day in total.
- **Disk.** Station-block extracts are small: IEM CSV equivalents in the swarm were about 8 KB per
  station-day for MAV and about 8 KB for NBE (A-IEM-2 raw: 13.3 MB and 13.0 MB for 11 stations x 152 days),
  so **about 5-6 MB/month** for both. Raw national NBE text is the cost driver (same order as NBS/NBH, about
  29 MB per cycle, T20): **about 1.7 GB/month at 00/12Z if raw is retained**. Keep station extracts plus the
  national object's sha256 and LastModified; do not retain raw on the disk-constrained capture host.
- **Code surface.** A new `src/weather/sources/mos_text.py` (parser for MAV/NBE station blocks, like
  `sources/nbm_probabilistic_tmax.py`), a capture-side fetcher entry in `model/model_sources.py`, payload
  contract and snapshot diagnostics (non-selectable). Roll-sensitive; quiet-window merge only.
- **Parity.** The T7 rules fit 48 b_h/s_h on 2026-06-01..07-31 against METAR truth: a frozen parameter file
  (release-bound) if ever served. A shadow stage must reproduce the research parser on the same bytes
  (replay check) before its first eligible date.
- **Countability.** First eligible date = the first date >= 2026-10-15 after continuous capture verified for a
  full prior day, after the freeze commit; out of season (EF 1c); power for a 13-14-sized effect is not
  established here (a separate D-MORNING-style power read on the before stratum would be needed, and the
  11-cluster floor applies). Recommendation stays: decline.

## 5. How the capture makes the draft pre-registrations countable

Common conditions for every METAR-anchored draft (proposed text, owner decision):

1. **Inputs captured PIT in production.** Every stage input is either a stored per-snapshot field or
   reproducible by a pinned replay function from the retained `raw_payload` (code hash in the pre-registration).
2. **M1-M3 live and verified** for at least one full prior local day in every US market before the first T+0
   snapshot (Eastern 00:00) of the first eligible date: parsed rows carry `receipt_time_utc`, report type, COR
   flag and T-group, and the stale fallback reason is recorded.
3. **Shadow stage.** The candidate stage is computed and stored but not served during the window, so served
   stays the comparator; replay reproduces the stored vector on 100% of snapshots within 1e-12, else the look
   is VOID.
4. **Dates.** First eligible date >= 2026-10-15, after the freeze commit's Toronto date, promotion-countable,
   no skipping; out of season (EF 1c); fixed-market date-clustered primary with the crossed estimate beside
   and the 2026-09-30 DECISION_LOG guardrails verbatim (as in the D-MORNING draft).
5. **Validity conditions tied to capture.** METAR-stage coverage below a declared share (for example 95% of
   snapshots in the claimed block) -> VOID; any input with receipt or payload time after `captured_at_utc`
   -> VOID; KBKF reported separately beside the primary, because of its receipt lag.
6. **Comparator binding.** If the evening restoration is promoted inside another draft's window, that draft
   reports pre/post segments (D-MORNING section 2 already states this).

Per draft:

| Draft | METAR/MOS inputs | Capture needed | Countable when |
|---|---|---|---|
| Evening WU-anchor restoration (rung 1: S1/S2/S6 + S7 gate; D-RUNG1C bundles S3-S5) | floor, METAR `max_times`, current reading, stale flag | M1-M3 (no new source) | Owner approves the versioned change; shadow stage live + replay check (D-DEFECT section 6 replay of `estimate_distribution`); conditions 1-6. Zero new parameters. |
| 13-16 / 15-16 remaining-rise table (t3-r3 form; T2-r1 alternative) | IEM history table + at-t floor and current reading | M1-M4 (table artifact release-bound) | Table frozen and bound before the freeze; same parser at fit and serve; conditions 1-6. Any hour composition with rung 2 is a Phase-4 draft only (rule 8). |
| T1 decided band (form B) | as above, plus sunset (computed) | M1-M4 | Same as the table draft; dominated by form A for 17-23 (T20). |
| MG-1 morning (D-MORNING) | METAR only via the 81a floor | M3; the real dependency is the 83a/83b NBM parser landing | Per D-MORNING section 3. |
| Hour-gated guidance composite (Phase-4) | floor only | M3 | Gate fixed from the bulletin schedule alone. |
| T7-r2 MOS 13-14 (not drafted; not recommended) | MAV + NBE | Section 4.4 shadow capture | Only with production first-seen times; IEM archive is not PIT. |

## 6. Owner decisions this enables

1. **Approve or decline M1-M3** (METAR capture hardening, no new source, roll-sensitive code in
   `model_sources.py`; quiet-window merge after the exam-period merge policy allows it). Recommended:
   approve; it is the precondition for counting any METAR-anchored draft with measured availability.
2. **M4 only if** a frozen-table draft (13-16 remaining rise) is signed.
3. **Decline MOS capture** (section 4.3). Optional 4.4 only to answer the 13-14 borderline prospectively.
4. **Decline neighbour-METAR capture** (T13 WEAK/NULL). `cover` is already captured (T14 r4 about -0.001).

## 7. What this draft does not claim

- No number here is evidence; all are development reads on previously inspected dates.
- The METAR disk figure is an upper estimate from AWC payload sizes, not a measurement on the capture host.
- The MAV/MET/MEX/LAV availability lags are assumptions (A-IEM-2); the MOS endpoint paths in 4.4 are not
  verified.
- That AWC JSON rows stored by production contain `receiptTime` is inferred from the public API's shape
  (T26 fetched the same endpoint) and from production retaining the raw payload verbatim; it should be
  confirmed on one captured payload by the operations agent before M1 is scoped.
- Nothing authorises a code, config, Scheduler, capture, serving, reservation, alpha or merge action.
