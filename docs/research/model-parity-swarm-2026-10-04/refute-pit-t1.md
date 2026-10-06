# R-PIT-T1: PIT/leakage refutation of T1 (decided-band collapse) - development only

**Verdict: NOT DISQUALIFIED for the 17-23 LEAD (t1-r2). DISQUALIFIED as a LEAD for 13-16: that claim collapses to WEAK under a +1 h availability shift.**
No leakage found. No rule 1-5 or rule 8 violation found in the code. The baseline, the fit and the hunter's obs table
reproduce exactly. The one load-bearing claim this lens could not verify from a primary source is the IEM feed lag
itself (+10 min after valid); it is not load-bearing for 17-23 because the result survives +60 and +120 min.

Refuter: r-pit-t1 (Fable). Candidate: T1, rules t1-r1/t1-r2/t1-r3/t1-r2lag60, code
`C:\pt\swarm\tools\research\model_parity\t1_decided_band.py` sha256 `4a6aa874e221ac96abcdb887ac0e07b282d33dc5c2f1548e23cda3b4421c95c2`.
HARNESS_SHA256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74` (current).
Refuter code: `C:\pt\swarm\tools\research\model_parity\r-pit-t1_refute.py`; outputs `C:\swarm\out\refute-pit-t1\`
(result.json, five `*.score.json`, `refit\fit_params.json`, `run.log`). No rule was registered by this refuter.
All numbers are development numbers on the 111h table, from stratum (08-23..09-29, a development read), all-row
primary estimand (served fallback), candidate - served Brier unless stated.

## 1. Availability shift (the task's main test)

Hunter's basis: METAR/SPECI available at valid + 10 min, COR excluded. The refuter re-ran t1-r2 through the harness
with every row available later (`valid+60` reproduces the hunter's `t1-r2lag60`).

| availability | covered | 17-23 from, cand - served [95%] | mkts -/+ | gap closed | 17-23 before | 13-16 from | 13-16 class |
|---|---|---|---|---|---|---|---|
| valid+10 (hunter) | 31,929 | -0.026412 [-0.037948, -0.017499] | 11/0 | 0.886 | -0.029520 | -0.003573 [-0.006609, -0.001123] | LEAD |
| valid+60 (hunter lag60) | 29,265 | -0.024892 [-0.036427, -0.016153] | 11/0 | 0.835 | -0.027711 | -0.002264 [-0.004679, -0.000104] | LEAD |
| **valid+70 (+1 h)** | 28,400 | **-0.024405 [-0.035862, -0.015688]** | 11/0 | 0.819 | -0.026982 | -0.002019 [-0.004353, +0.000091] | **WEAK** |
| **valid+130 (+2 h)** | 25,583 | **-0.022733 [-0.033831, -0.014429]** | 11/0 | 0.762 | -0.024591 | -0.001279 [-0.003513, +0.000897] | **WEAK** (7/11) |
| t1-r3 sunset-only, valid+130 | 19,407 | -0.019540 [-0.029376, -0.012295] | 11/0 | 0.655 | - | not covered | NULL |

17-23 loses about 8% of its estimate per hour of extra lag and stays LEAD on every condition (interval, size, both
strata, 11/11 markets) at +2 h. It does not collapse. The sunset-only variant, which needs METAR only to exist for the
day and not to be fresh, carries -0.0195 on its own. The leakage tripwire stayed empty in every run; 17-23 candidate
Brier 0.0043-0.0058 vs market 0.00086.

13-16 is different: its LEAD rests on the 5%-of-gap size bar (about -0.0012) and on fresh METARs; at +1 h the interval
includes 0 (8/11 markets), at +2 h 7/11. "13-16 also classes LEAD" should not be carried forward; report it as WEAK.

## 2. Inputs and availability re-derivation (rule 1)

Only one external input: IEM ASOS METAR/SPECI (A-IEM-1), `C:\swarm\data\iem\metar\<ICAO>.parquet`.
- `available_utc - valid_utc` is exactly 10.0 min on every row of all 11 stations. COR rows flagged and excluded by the
  candidate. Routine rows are the hourly METARs (valid minute :51/:52/:53 on >99.9%; no 5-minute MADIS rows).
- Primary-source feed-lag check: NOT achievable tonight. IEM's AFOS archive (`/api/1/nws/afos/list.json`, which carries
  an `entered` ingest time) returns no `MTR<id>` products for 2026-09-15 by pil or by cccc; `/cgi-bin/afos/retrieve.py`
  ignores the date range and serves only the current day. The refuter did not read current-day products on purpose
  (COMMON: no data dated >= 09-30). `asos.py` exposes no ingest time. So "+10 min" is an assumption at the DESIGN
  minimum ("valid time + >= 10 min"), not a measurement. Mitigation: section 1; not load-bearing for 17-23.
- Backfill risk (rows IEM added later from other archives) cannot be excluded from the archive alone; bounded because
  the candidate needs only the latest routine row or any same-day row, and the +2 h shift (which drops the freshest row
  for most snapshots: median age of the latest joined row at 17-23 is 42 min, 95th pct 68 min) leaves the result intact.
- `tmpf` is IEM's stored value; on KATL `tmpf == round(tgroup_f)` on 99.99% of rows with a T-group (same text in real
  time). Not a leak.
- Date bounds: max `local_date` 2026-09-29 for every station; 4-11 rows per station have UTC valid on 09-30 (local
  evening of 09-29). These are the target day's own METAR text, not market or settlement records. Snapshots carry
  `date <= 2026-09-29` (asserted by hunter and harness); 0 rows after 09-29 in every score JSON.
- PIT join: `searchsorted(available_utc, captured_at_utc, side="right") - 1`, so every joined row is available at or
  before capture; the refuter re-audited independently (0 late rows across 110,807 snapshots) and regenerated the
  hunter's `t1_obs_pit.parquet` (runmax, def_1, past_sunset identical on all rows).
- Sunset is deterministic (NOAA equation, zenith 90.833; sign convention checked, KATL mid-September about 23:37Z).
- Stations: the table's own `station` column (atlanta KATL, austin KAUS, chicago KORD, dallas KDAL, denver KBKF,
  houston KHOU, los-angeles KLAX, miami KMIA, nyc KLGA, san-francisco KSFO, seattle KSEA) keys the METAR files.

## 3. Code rule checks (rules 2, 3, 4, 5, 8)

- Rule 2: the candidate reads only `h.candidate_inputs()` (allow-listed) plus the METAR parquet. Token scan for
  winner/settlement/p_market/best_bid/best_ask/market_mid/is_winner/`data()`/`d.y`/`se_market`: the only hit is the
  word "settlement" in the docstring. PASS.
- Rule 3: the fit reads METAR only, filters `local_date <= 2026-07-31` first and asserts it. Refit into the refuter's
  directory: X=1, N=1, H=15, n_points 59,035, every q cell identical to 1e-12, history 2024-05-01..2026-07-31, 0 points
  after the fit end. The fit "label" is the history day's own METAR max (truth side on history). Nothing is fitted on
  the evaluation table. PASS. (RISE_CAP 3% and the grid ranges are pre-scoring analyst choices; 172 of 181 grid points
  pass the cap and the chosen point is the max-coverage one as the registered text says; multiplicity belongs to the
  statistics refuter.)
- Rule 4: the candidate zeroes bands with `high < floor_bucket`; the harness re-applies 81a's mask and renormalises
  (`floor_applied: True` everywhere). Mass moves into the band containing the captured `floor_bucket`: on the 28,803
  decided 17-23 rows the floor is `high_so_far` (WU prints, printed-only) in 28,561 and `guidance_physical_floor` (max
  over observed sources captured at snapshot time) in 242. Never weakened. PASS. Data-quality note: `floor_bucket -
  round(METAR running max)` is 0 on 97.5% of decided 17-23 rows, +1..+3 on 2.1%, -1..-16 on 0.3%, and +10 on 31 rows
  (captured WU floor 10 F above the METAR max; immaterial to the estimate, worth a look by T20).
- Rule 5: asserted in hunter code and harness; 0 rows after 09-29; no market, settlement or exam record for >= 09-30
  opened by either code path. PASS.
- Rule 8: no NBM/NBP guidance is used; H=15 is an observation-condition hour gate chosen on history; q hour buckets
  fixed before scoring. PASS.
- Rule 6 observed (all-row primary, `reason_counts` {absent, candidate}; matched labelled).
- Benign warning: `np.round(k).astype(int)` (line 259) on rows whose floor band is the open top band (`high = inf`);
  no band lies above the floor there, so no effect.

## 4. Decomposition relevant to serveability (not a refutation)

Of 32,008 17-23 snapshots, 28,868 are decided: 19,502 past sunset, 9,366 by the fallen condition alone. Two thirds of
the decided set needs only the clock and the captured floor (zero-parameter serving stage). Production already
captures a METAR source among `guidance_physical_floor`'s inputs; T20 should confirm the at-t METAR current temperature
is stored per snapshot for the fallen path.

## 5. Not done by this lens

IEM ingest lag from a primary source for the window (archive unavailable, section 2); S3/Open-Meteo re-derivation
(candidate uses neither); statistics (intervals, multiplicity, one-market/one-week: statistics refuter); the hunter's
"winner above floor band" diagnostic (not in the code file; label-side diagnostic, not an input).

## Defects

1. 13-16 "LEAD" is not robust: WEAK at +1 h (interval includes 0, 8/11), 7/11 at +2 h. Carry 13-16 as WEAK.
2. The +10 min METAR availability basis is assumed, not measured from a primary source; 17-23 is insensitive to it
   (+2 h still LEAD), 13-16 and 00-16 are not.
3. 31 decided 17-23 rows have a captured floor 10 F above the METAR running max (captured-input data quality).

Note: `report.md` and the docs copy `refute-pit-t1.md` were not written by this agent: the harness blocked report .md
writes from the subagent (as it did for T1). This text is `result.json["report_md"]` for the orchestrator to materialise.
