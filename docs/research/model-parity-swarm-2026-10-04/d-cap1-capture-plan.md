# D-CAP1: production capture-plan draft for IEM METAR/SPECI and NBH (DESIGN ONLY, development)

> **DRAFT. DESIGN ONLY. DEVELOPMENT.** Written by swarm agent D-CAP1 on 2026-10-04, about 03:05 local, on the
> workstation. No code, config, Scheduler, serving or capture change has been made, and nothing here authorises
> one. Nothing was scored: no registry rule, no HARNESS_SHA256 result. Every number is development, on dates
> 79a/81a/111h already inspected (DESIGN rule 7). Production data was not read. Production code was read in
> the swarm worktree `C:\pt\swarm`. The sibling plan D-CAP2 (`d-cap2-capture-plan.md`) covers METAR hardening
> (M1-M4) and IEM MOS; this plan does not repeat it. It adds one new capture defect (M0) and the NBH plan.

## Verdict

1. **METAR/SPECI: no new source. But there is a capture defect that must be fixed first (M0, new).**
   Production keys METAR rows to the local date by AWC `reportTime`, which is the nominal hour, not the
   observation time. A routine report observed at 23:5x local has `reportTime` 00:00 the next day. So it
   leaves its own day and enters the next day's running max as a "00:00" reading.
   - **Confirmed on the captured data.** In the 111h table, the captured `guidance_physical_floor` sits above
     the settlement high on exactly the two station-days the emulation predicts: KLGA 2026-09-19 (floor 71.06,
     settlement 70) and KMIA 2026-08-29 (86 vs 85). That is 351 snapshots, held all day until the 23:5x pass.
   - **The cost on KMIA 08-29.** The winning band 84-85 is floor-masked on 181 of 181 snapshots. Every
     81a-floored candidate therefore gives the winner zero all day, while served gives it 0.21.
   - **The cost in the drafts' own season.** The rate is 0.3-0.6% of station-days in Aug-Sep. In Oct-Dec it is
     **2.2%** (2024-25 history), up to 5.4% at KLGA and 4.9% at KORD. The floor can be up to 6 °F too high.
     Every METAR-anchored draft (the evening restoration, the remaining-rise table, MG-1's floor) is scored
     out of season.
   - **The fix.** Key on `obsTime`. That is a parse-only, versioned change.
2. **IEM METAR's role is history only, never a live input.** It is the fit source for any frozen table (D-CAP2
   M4) and an optional nightly row-parity audit (section 2.3). AWC, which production already fetches, stays the
   single serve source.
3. **NBH: decline. No draft needs it.**
   - **Morning:** its 00-16 gain is not an increment over captured NBM v2 (R-T5-INC: paired +0.0027
     [-0.0037, +0.0098]).
   - **13-16:** this is the remaining-rise family. T5 − t3-r3 is +0.0019 [-0.0027, +0.0073] (R-STAT-T5).
   - **15-16:** LADDER's T5 − t3-r3 is +0.0005 [-0.0042, +0.0055].
   - **17-23:** this is the decided-band collapse. Only about −0.0018 over T1-r2 is NBH's own.
   - **Cost if the owner overrides:** about 0.68 GB/day transferred, about 20 GB/month raw, and a new parser
     and payload contract. Section 3 gives the full design.

## 0. Inputs read

- T20 serveability map, T26 METAR PIT re-derivation from AWC `receiptTime`, A-IEM-1, A-NBH (reconstructed
  report; numbers here cite `C:\swarm\data\nbh\MANIFEST.json`), R-T5-INC, R-STAT-T5, R-PIT-T5, LADDER,
  D-DEFECT, D-RUNG1C, D-MORNING draft, D-CAP2.
- Production code (swarm worktree):
  - `src/weather/model/model_sources.py`: `SOURCE_PAYLOAD_CONTRACTS` :106-134 (`metar-parser-v3`),
    `parse_metar_payload` :1312-1351, `fetch_metar` :1353-1398, `metar_query_hours` :1400-1411,
    `parse_utc_time` :2403-2410;
  - `src/weather/model/model_features.py` `guidance_physical_floor` :222-252;
  - `src/weather/sources/metar_history.py` (IEM `asos.py`, keyed on `valid`);
  - `src/weather/sources/nbm_probabilistic_tmax.py` (the NBP template: nomads `blend_nbptx`).
- New descriptive check (no scoring): `tools/research/model_parity/d_cap1_reporttime_carryover.py`. Output
  `C:\swarm\out\d-cap1\d_cap1_facts.json`. It reads T26's AWC raw JSON, the A-IEM-1 parquet and the harness
  cache (targets ≤ 2026-09-29; asserted).

## 1. Which drafts depend on these sources

| Draft / board item | METAR role | NBH role | Capture consequence |
|---|---|---|---|
| Evening WU-anchor restoration (D-DEFECT rung 1: S1/S2/S6 + S7 gate; D-RUNG1C bundles S3-S5). Development 17-23 −0.0254, 85% of the gap, 11/11 | Anchor = floor; `max_times`; current reading | none | **M0** + D-CAP2 M1-M3 |
| 13-16 / 15-16 remaining-rise table (t3-r3 form). Beats rung 2 at 15-16 by −0.0181, 11/11 | Floor + current reading at serve; IEM history for the frozen table | none (T5 − t3-r3 at 15-16 +0.0005) | **M0** + M1-M4 |
| T1 decided band (form B) | as above + sunset | none | **M0** + M1-M4; dominated by form A in 17-23 (T20) |
| MG-1 morning (D-MORNING) | Only through the 81a floor (H = max(B, X)) | none (R-T5-INC) | **M0** (the floor is MG-1's collapse point); real dependency is the 83a/83b NBM parser landing |
| Hour-gated guidance composite (Phase-4 draft) | floor | none | **M0** |
| T5 NBH (t5-r1) | floor | NBH TMP/TSD | Decline (section 3) |

## 2. IEM METAR/SPECI

### 2.1 Production today

D-CAP2 §2 has the full picture. In short:
- **Fetch:** production fetches the AWC JSON (`/api/data/metar?ids=<ICAO>&format=json&hours=n`, free, no key)
  on every pass, about every 9 min. `n = min(24, elapsed local hours + 2)`.
- **Storage:** the raw payload is retained per snapshot.
- **Latency:** receipt − valid has a median of 3.2-4.5 min at 10 stations; KBKF is 10.4 min, with a 113 min
  p95 (T26). Production reflects a new max about 3.8 min after valid (T17).
- **Disk:** already spent today. D-CAP2 estimates about 100-170 MB/month for 11 markets, an upper estimate
  that was not measured on the host.

Facts verified tonight on T26's 7,672 AWC reports (2026-09-04..09-29). These were open items in D-CAP2:
- Each AWC row carries `receiptTime`, `obsTime` (epoch), `reportTime`, `metarType` (METAR/SPECI), `rawOb`,
  `temp`, plus `maxT`/`minT`/`maxT24`. `metarType` exists, so report type needs no text parsing.
- AWC `temp` equals the RMK T-group tenths on **7,544 of 7,544** reports that carry a T-group.
- `reportTime − obsTime`: min 0, median 7, p90 9, max 12 min. For a routine report it is the nominal hour; for
  a SPECI it equals the observation time.
- **286 of 7,672 reports (3.7%, all `metarType = METAR`) have a `reportTime` on a different station-local
  date than their `obsTime`.** That is about one report per station-day: the last routine report before
  local midnight.

### 2.2 M0 (new): key METAR rows on `obsTime`, not `reportTime`

**The defect, from code.**
- `parse_metar_payload` (:1317-1319) does `report_time = parse_utc_time(row.get("reportTime"))` and drops
  every row whose local date is not the target date. `time` and `datetime` are also taken from `reportTime`.
- So on day D:
  - (a) the 23:5x routine report of D−1 enters D's rows as a 00:00 reading;
  - (b) D's own 23:5x report is dropped from D;
  - (c) from 00:00 to about 00:5x, `latest`, and so `current_temp`, is D−1's 23:5x report.
- The carried report drops out of the query only at the last pass of D. At about 23:55, `hours` is capped at
  24, so the window starts after it. The captured KLGA and KMIA floors drop at 23:55 and 23:58.
- `guidance_physical_floor` (`model_features.py:222-252`) takes the max of the rows, `same_day_max` and
  `temp_native`. All three inherit the carried value.
- The training history (`sources/metar_history.py`) and every IEM table key on `valid`, the observation time.
  So this is also a train/serve keying mismatch.

**The effect on the 81a floor** (development; `d_cap1_facts.json`):

| Read | Station-days | Floor above the valid-time max | Floor below it |
|---|---|---|---|
| 111h captured table (cache), 2026-08-01..09-29 | 626 | 2 (KLGA 09-19, KMIA 08-29; 351 snapshots, 0.32% of rows) | n/a |
| IEM emulation, Aug-Sep 2026 | 660 | 2 (the same two days, exactly) | 0 |
| IEM emulation, all months 2024-05..2026-09 | 9,686 | 179 (1.85%), up to +6 °F | 31 (0.32%) |
| IEM emulation, **Oct-Dec** (2024, 2025) | 2,024 | **44 (2.17%)**: KLGA 5.4%, KORD 4.9%, KDAL 3.3%, KATL/KAUS 2.7%, KMIA 0% | 17 (0.84%) |

The over rate by month is 0.3-0.6% in Jul-Sep and 1.5-4.4% in Oct-May. It follows cold-front days: a warm
evening, then a colder next day.

- **Where it does harm.** When B = round_half_up(floor) crosses the winning band's upper edge, every
  81a-floored candidate assigns the winner zero for the whole day. This happened on KMIA 08-29: the winning
  band 84-85 was masked on 181/181 snapshots. On KLGA 09-19 the winner 70-71 still contained B = 71, so there
  was no mask.
- **Served's exposure.** Served is barely exposed: its `hard_floor_bucket` does not include
  `guidance_floor` (D-DEFECT §5), and `high_so_far` is a running max only from 07:00.
- **The bias.** The defect therefore biases candidate − served against every floored candidate. It is small
  on this table (one masked market-day) but material out of season, which is when every draft would be
  scored.
- **The evening restoration** anchors `lockin_high` on the same floor, so it inherits the error. On an
  affected day it would lock mass onto a band above the truth.

**Fix (proposal):**
- In `parse_metar_payload`, derive the row time from `obsTime`, falling back to `reportTime` only when
  `obsTime` is missing, and record which one was used. Filter by the station-local date of that time.
- Keep `report_time` as a stored field. Bump the parser contract to `metar-parser-v4`.
- Replay dispatches on the recorded parser version, so old payloads keep v3 behaviour unless replayed
  explicitly under v4.
- `obsTime` is already in every retained raw payload. **No new fetch.**

**Parity effect:**
- `high_so_far`, `current_temp`, `same_day_max`, `max_since_7am` and `guidance_physical_floor` change on
  about one report per station-day, near midnight only.
- HGBC features that read them move *toward* the training keying, which is IEM/WU observation time. This is
  still a versioned model-input change: replay one captured day under v3 and v4 and report the per-snapshot
  served-vector difference before landing.
- It is roll-sensitive (`model_sources.py` is loop-imported), so it goes in the quiet window only, and only
  after the exam-period merge policy allows it.

**Audit item for the operations agent (read-only):** confirm on the captured KMIA 2026-08-29 payloads that the
first rows carry `reportTime` 2026-08-29T04:00Z with `obsTime` at 03:5xZ.

### 2.3 IEM's role: history and audit, not serve

- **History tables (D-CAP2 M4).** IEM `asos.py` is the only free archive reaching back past the AWC retention,
  which is about 25 days (T26).
  - Tables must use the same keying as serve after M0: observation time, station-local date.
  - The same COR rule and the same °C-tenths→°F conversion apply at fit and serve.
  - Availability basis per station: valid + 10 min, except KBKF, which takes a declared larger offset or is
    left out of fitting (T26).
  - Cost: about 22 requests and about 1 MB per monthly refresh at 1 req/s; 220 requests and about 28 MB for
    29 months (A-IEM-1). Runs on the workstation.
- **Optional nightly row-parity audit.**
  - After local close of D, one IEM request per station for D (11 requests, about 25 KB each, under
    10 MB/month).
  - It joins IEM rows to the captured AWC rows on (station, obsTime) and checks value equality (T26 found
    7,493/7,493 equal), missing reports and COR replacements.
  - It records row-level counts and diffs only. **It must not compute daily maxima or labels for any date in
    a reserved window** before that window's look. The obs maximum is the settlement proxy, and computing it
    would be reading outcomes.
  - Free, light, workstation or capture-host off-window. Recommended only if the owner signs a
    METAR-anchored draft.
- **Not recommended:** IEM as a live fallback for AWC. It adds a second parity surface and has no receipt
  time.

### 2.4 METAR failure modes

These add to D-CAP2 M3, which covers stale fallback, outage, KBKF lag, the null floor and pass gaps.

| Failure | Effect | Mitigation in the plan |
|---|---|---|
| `reportTime` date keying (M0) | Floor too high all day on about 2% of out-of-season station-days; too low on about 0.8% | M0; until it lands, the drafts' validity section must count affected station-days and report them (section 4) |
| `hours` cap at 24 | Near 23:5x local the window starts after D−1's carried report (benign today); after M0 the 24 h window still covers local midnight to now on every pass | none needed; assert in M0 tests that a 23:59 pass still includes D's 00:5x report |
| DST end 2026-11-01 (25 h local day) | At 00:xx-01:xx on the fall-back day, `elapsed + 2` keeps a margin; obsTime keying is tz-aware | M0 test on a 25 h day |
| AWC retention (about 25 days) | `receiptTime` cannot be recovered later from AWC | Production's retained raw payloads are the only durable record. Keep them (already done) |
| COR replacing an original | AWC and IEM both keep the corrected report (T26: original recoverable for 6/177) | Declared rule at fit and serve (D-CAP2 M2) |

## 3. NBH (NBM hourly text bulletin): decline, full design for the record

### 3.1 Evidence (development)

- **00-16 (maker-relevant):** T5 − c1 (captured v2_mean, same Gaussian form) is +0.0027 [-0.0037, +0.0098],
  5/11 markets negative. c1 alone is −0.0100 [-0.0179, -0.0035] against served (R-T5-INC). NBH is worse than
  v2_mean in 00-05, 06-09 and 10-12. The morning route is the parser-v2 landing, not NBH.
- **13-16:** T5 − t3-r3 is +0.0019 [-0.0027, +0.0073], with 4/11 markets negative. The non-collapse NBH
  effect is null (R-STAT-T5).
- **15-16:** T5 − t3-r3 is +0.0005 [-0.0042, +0.0055] (LADDER). T5's 15-16 edge over rung 2 and over the
  S1+S2 restoration (D-DEFECT §7) is matched by the no-source t3-r3 rung.
- **17-23:** 97.4% of snapshots are collapse rows (R-STAT-T5). Only the −0.0018 over T1-r2 belongs to NBH.
- **Tail lens (T19):** NBH removes less 00-16 tail than MG-1 at the same non-tail cost.

### 3.2 What a capture would be, if the owner overrides

| Item | Design |
|---|---|
| Product | `blend_nbhtx.tHHz`, NBM hourly station text, every cycle 00-23Z. Fields needed: TMP and TSD (T5); keep the station block whole |
| Endpoint | nomads `.../blend/prod/blend.YYYYMMDD/HH/text/blend_nbhtx.tHHz` (same host and path pattern as NBP, `nbm_probabilistic_tmax.py`), or anonymous S3 `noaa-nbm-grib2-pds` (A-NBH) |
| Cadence | Once per cycle, by a fan-out fetch like NBP's, never once per market per pass. This needs the 83b held-cycle reuse pattern: EF 10l counted 729 NBP downloads (24.9 GB) in 15 h without it |
| Latency (S3 LastModified − cycle, A-NBH manifest) | Median 38-48 min off-cycle, 63 min at 01Z, 77 min at 00Z, 76 min at 07Z, 95 min at 12Z. Late uploads were measured: 2026-09-24 00-12Z +4 to +14 h; 08-31 12-13Z +2 h; 09-14 17-18Z +3 h; 09-23 19-20Z +2-3 h |
| Availability basis | Production's own `response_received_at` / `first_seen_at` per object (the NBP rule in MG-1), never a fixed lag |
| Transfer | About 28.5 MB per object (45.75 GB for 1,608 objects) × 24 = **about 0.68 GB/day, about 20.5 GB/month**, all national |
| Retained disk | Extract the 11 station blocks (about 0.15 MB/day, **about 5 MB/month**) plus the object's sha256, LastModified and size. **Do not retain raw** on the 16 GB capture host: about 20 GB/month |
| Code surface | New `src/weather/sources/nbm_hourly_text.py` (URL, cycle candidates, station-block parser; model it on `nbm_probabilistic_tmax.py`); a fetcher entry plus the fan-out in `model/model_sources.py`; a new `SOURCE_PAYLOAD_CONTRACTS` row (`nbm-hourly-text-parser-v1`); snapshot diagnostics, not selectable as model features; tests. Roll-sensitive, so quiet window only |
| Train/serve parity | t5-r1 is zero-parameter, but its remaining-hours window must use the same local-day hour set and the same 81a floor (after M0). The research parser (`a_nbh_*`, `t5_nbh_latest.py`) must reproduce the production parser on the same bytes (a replay check). NBM version strings change at upgrades (`nbm_version` header), so the parser must fail closed on an unknown layout |
| Failure modes | Late or missing cycle: use the previous cycle with its age recorded, or fall back to served. Nomads 403/rate limit: S3 fallback with the same object identity (sha256). Partial object: verify size and sha before parsing. Station missing from the bulletin: fall back for that market. Disk pressure from a raw-retention mistake |

**Countability.** No signed or drafted pre-registration uses NBH, so this capture would make nothing
countable. A new NBH pre-registration would need:
- a fresh rule on new dates (≥ 2026-10-15, out of season);
- an increment hypothesis against MG-1 and t3-r3, not against served, because both comparisons above are
  null;
- its own power read under the 11-cluster floor.

Nothing in the swarm supports drafting one. **Recommendation: close "capture NBH" for both the morning and
the afternoon.**

## 4. How the capture makes the drafts countable

This applies to all METAR-anchored drafts and adds to D-CAP2 §5 conditions 1-6.

1. **M0 before the first eligible date.** Parser `metar-parser-v4` (obsTime keying) has been live and verified
   for at least one full prior local day in every US market before the first T+0 snapshot (Eastern 00:00) of
   the first eligible date. The look's validity check asserts that every scored snapshot's METAR rows carry
   parser v4.
   - **If the owner sequences M0 after a draft's freeze:** the draft must say so up front. It must count and
     report the affected station-days (floor above the valid-time max at any snapshot), with the primary
     estimate given with and without them beside it. They are not dropped from the primary. Dropping
     outcome-correlated days after the fact is not allowed.
2. **Floor provenance.** Each scored snapshot records the floor's source row (obsTime, receiptTime, report
   type). The 81a floor is never weakened. M0 corrects its input and does not loosen it.
3. **MG-1 specifically.** The 83a/83b landing (D-MORNING §2) and M0 can be sequenced as one quiet-window
   integration, or M0 first. Both change served model inputs, so the comparator binding in D-MORNING §2
   applies to each.
4. **Remaining-rise table drafts.** The frozen table is built with v4 keying from IEM `valid` (identical keys).
   The fit cutoff, the KBKF offset and the COR rule are declared before the freeze (D-CAP2 M4).
5. **No NBH condition.** No draft lists NBH as an input.

## 5. Owner decisions this enables

1. **Approve or decline M0** (obsTime keying, `metar-parser-v4`). It needs no new source and is roll-sensitive.
   Recommended: approve, and land it before any METAR-anchored or floored draft's first eligible date. It is
   a correctness fix to the 81a floor's input, it reaches about 2% of out-of-season station-days, and it moves
   serving toward the training keying.
2. **Approve or decline D-CAP2 M1-M3** (receipt time, type/COR/T-group, stale fallback). `metarType` is
   confirmed in the AWC JSON.
3. **Decline NBH capture** (section 3). This closes it for the morning and the afternoon.
4. **Optional:** the nightly IEM row-parity audit (section 2.3), only if a METAR-anchored draft is signed.

## 6. What this draft does not claim

- No number is evidence. Every figure is a development read or a descriptive count.
- The Oct-Dec rates come from an IEM emulation of AWC keying. The emulation rule is that a routine report at
  local minute ≥ 45 of hour 23 moves to the next day. It reproduces the captured table exactly in Aug-Sep
  (2/2 days, the same values), but it was not checked against captured payloads out of season.
- The swarm's scored candidates were not re-scored without the two affected days. The effect on the board is
  one floor-masked market-day (KMIA 08-29), which biases floored candidates against themselves.
- That production's retained raw payloads carry `obsTime` is inferred from the API shape and the verbatim
  retention. It is listed as an operations audit item.
- Nothing authorises a code, config, Scheduler, capture, serving, reservation, alpha or merge action.

## Files

- `tools/research/model_parity/d_cap1_reporttime_carryover.py` (descriptive check; no scoring)
- `C:\swarm\out\d-cap1\d_cap1_facts.json`, `C:\swarm\out\d-cap1\report.md`, `C:\swarm\out\d-cap1\result.json`
