# R-PIT-T6: PIT/leakage refutation of T6 (NBS latest cycle), development only

**Verdict: NOT DISQUALIFIED on PIT/leakage.** Every claimed LEAD block (r2/r3 in 00-05, 06-09, 17-23, 00-16 and all; r3 in 13-16) passes this lens and holds at +1 h and +2 h availability lag. The +0 run reproduces the hunter's numbers exactly.

I agree with the hunter's attribution: the **NBS-specific increment is null**.
- 17-23 is the schedule-only floor collapse, the T1/T2/T3 decided-band family (see D-DEFECT).
- 00-09 is the captured-NBM-v2 Gaussian, the T7-c1 / R-T5-INC c1 / 81a family.

Neither is leakage, and neither is NBS information. Count nothing here as an independent NBS lead.

HARNESS_SHA256 is 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74; my script asserts it. I imported the hunter's code unchanged: t6_nbs_latest.py sha256 72f3da69...8484 and t6_nbs_controls.py 257f0cd9...c56a. My code is tools/research/model_parity/r-pit-t6_shift.py (sha256 d4dafbe0...d65b), plus scratch checks in C:\swarm\out\refute-pit-t6\ (check_avail.py, s3_head.py, indep_check.py). I registered no rules. Rows after 2026-09-29: 0. The leakage tripwire fired in no group, for any run or lag.

## Per-block judgement (from stratum, all rows, candidate minus served, development)

| rule/block | +0 (reproduced) | +60 min | +120 min | mkts neg +0/+60/+120 | PIT verdict |
|---|---|---|---|---|---|
| r2 00-05 | -0.01360 LEAD | -0.01368 LEAD | -0.01381 LEAD | 10/10/10 | stands (NBM-v2 family, not NBS) |
| r3 00-05 | -0.01311 LEAD | -0.01309 LEAD | -0.01314 LEAD | 11/11/11 | stands |
| r2 06-09 | -0.01094 LEAD | -0.01202 LEAD | -0.01295 LEAD | 9/11/11 | stands |
| r3 06-09 | -0.01461 LEAD | -0.01440 LEAD | -0.01395 LEAD | 11/11/11 | stands |
| r2 10-12 | -0.00147 WEAK | -0.00232 WEAK | -0.00368 WEAK | 6/6/7 | not a LEAD |
| r3 10-12 | -0.00658 WEAK | -0.00728 LEAD | -0.00849 LEAD | 9/9/10 | not a LEAD at +0, the claimed lag (caveat 2) |
| r2 13-16 | -0.00884 WEAK | -0.00884 WEAK | -0.00887 WEAK | 9/9/9 | not a LEAD |
| r3 13-16 | -0.00975 LEAD | -0.00977 LEAD | -0.00982 LEAD | 9/9/9 | stands on PIT; paired vs t3-r3 +0.0019 (no increment) |
| r2 17-23 | -0.02870 [-0.04044,-0.01926] LEAD | -0.02869 LEAD | -0.02867 LEAD | 11/11/11 | PIT-clean; equals c1 collapse (no NBS) |
| r3 17-23 | -0.02858 [-0.04016,-0.01930] LEAD | -0.02857 LEAD | -0.02854 LEAD | 11/11/11 | PIT-clean; equals c1 collapse |
| r2 00-16 | -0.00955 [-0.01636,-0.00325] LEAD | -0.01000 LEAD | -0.01054 LEAD | 9/9/9 | stands |
| r3 00-16 | -0.01147 [-0.01753,-0.00567] LEAD | -0.01156 LEAD | -0.01170 LEAD | 11/11/11 | stands; equals c2 (captured NBM v2) |

- **Controls under the same shifts.**
  - c1 17-23 is -0.0287 at +0, +60 and +120 (11/11).
  - c2 00-16 is -0.00982 / -0.01026 / -0.01076, at least as good as r2 at every lag.
  - The attribution therefore does not depend on the lag.
- **r1 (TXN only)** is unchanged by the lag: 00-16 -0.0094 / -0.0095 / -0.0096. 17-23 is +0.0089 (NULL, 1/11).
- **r2 median latest-cycle age** is 1.2-1.5 h at +0, 2.2-2.4 h at +60 and 3.3-3.4 h at +120.
- **Coverage** is 110,077/110,807 at every lag.
- Nothing collapses under +1 h or +2 h. In 06-12 the effect grows (caveat 2).

## Availability re-derived from primary sources (rule 1)

- **Eval-window inputs are only S3 blend_nbstx.** All 17,688 station-cycles from 07-25 onward come from S3 parts (1,608 objects x 11 stations). The IEM NBS copy feeds only the r3 history fit (3,729 cycles before 07-25).
- **LastModified is consistent and conservative.**
  - The A-NBH ledger and the NBS MANIFEST agree on 1,608/1,608 objects.
  - The HTTP Last-Modified header equals the S3 listing LastModified on 1,608/1,608.
  - Lag after the cycle: min 36.5 min, median 44.3, p99 136, max 857. None is negative and none is under 30 min.
  - Late re-uploads (for example 09-24 00Z/06Z) are kept at their later time, which is conservative.
- **Live S3 HEAD on 24 random objects** (seed 20261004): Last-Modified and ETag match the manifest in 24/24.
- **Re-download and re-parse.**
  - blend.20260915/19/text/blend_nbstx.t19z matches the manifest sha256. The raw object was held in memory only.
  - KORD block, header "9/15/2026 1900 UTC": TXN 66/74/66/79/65, XND, and 23 TMP/TSD values starting 16-00Z (FHR 05).
  - Every value matches the part exactly, valid times included.
- **Part integrity.**
  - Over all 12.5M rows, cycle_utc equals the filename cycle.
  - For TMP/TSD, valid_utc - cycle_utc equals FHR exactly.
  - TXN valid hours are only 00Z and 12Z, so "TXN valid (D+1) 00Z" is the daytime max.
- **IEM NBS available_utc** equals the measured blend_nbstx LastModified (nbm_text_lastmodified.jsonl) for 697/697 runtimes. It is not a fixed lag.
- **Independent re-derivation.** I recomputed r2's mode, mu and sigma on 600 random snapshots straight from nbs_tidy.parquet, keeping only rows with available_utc <= captured_at_utc. I did not use the hunter's StationIndex.
  - Mode and mu agree 600/600, and every value I used was available.
  - Sigma differs in 2/600 rows because of the argmax tie-break: t6 takes the earliest valid time. That is a rule-text ambiguity, not a PIT issue.
- **Code paths.**
  - latest() and remaining() filter every source cycle by avail <= t.
  - The hunter's full_pit_check asserts only the latest cycle. My independent check covers the per-valid-time cycles.
  - REM0 is decided from the valid times of any cycle, available or not. That uses only the schedule, never values, and it can only turn a would-be REM0 row into a served fallback, so it is conservative.
  - c2 uses captured v2_mean/v2_stddev only where v2_available_at <= captured_at_utc, and every value is asserted.
- **IEM METAR feed lag and Open-Meteo publication do not apply.** T6 has no such input at serve time. METAR is truth only, in the r3 history fit.

## Rules 2-5 and 8 in code

- **Rule 2.**
  - Candidates read only h.candidate_inputs(). Its allow-list raises LeakageError on forbidden columns.
  - A grep finds no access to price, mid, bid, ask, winner or settlement.
  - The controls read labels only inside paired scoring.
- **Rule 3.**
  - r1/r2 have zero parameters.
  - r3's b/s are fitted on METAR truth over local dates 05-01..07-31, using cycles before 08-01 only.
  - My refit reproduces TXN (-1.0, 1.0068) and REM (+1.0, 1.3856). Both are frozen under the lags.
- **Rule 4.** score() always applies the floor, and unfloored is never passed. H = max(B, X) only strengthens it.
- **Rule 5.** The code asserts date <= 09-29, and the harness reports 0 rows after that date. No NBS object is issued after 09-29 23Z.
- **Rule 8 passes, with a caveat.**
  - There is no where= gate and no clock-hour gate, and the text was registered before scoring.
  - The TXN-to-REM switch is a property of bulletin content, but it is effectively a UTC schedule gate. Cycles 00-12Z carry TXN valid 00Z D+1; cycles 13Z-23Z do not. The switch therefore falls at about 13:45Z, roughly 06:45-09:45 local.
  - DESIGN s4 prescribes this framing for T5/T6, and no gate time was chosen on this table, so it is not a violation.

## Caveats (none disqualifying)

1. **Attribution.** 17-23 is the no-source collapse: c1 equals r2 at every lag, and paired r2 - c1 is 0.0000. 00-16 equals the captured-NBM-v2 control c2 at every lag. Count neither as NBS. This agrees with the hunter and with R-T5-INC.
2. **Gate-timing sensitivity.** Delaying availability makes r2/r3 *better* in 06-12. r2 06-09 moves -0.0109 -> -0.0120 -> -0.0130, and r3 10-12 moves from WEAK to LEAD.
   - The delay keeps TXN mode active longer, and late morning scores better under the TXN/NBM Gaussian than under the 3-hourly REM max.
   - This is not leakage, because staler information does not do worse.
   - It is the rule-8 hazard: the switch time must not be tuned on this table, and the +60/+120 classes must not be cited as findings.
3. **Rule-text ambiguities.** The sigma tie-break and the schedule-based REM0 test are both immaterial to the estimates.
4. **Development only.** The from stratum is a previously read development stratum, not a holdout.

## Files

All in C:\swarm\out\refute-pit-t6\:
- rpit_t6_shift.json
- rpit_t6_*_plus{0,60,120}.score.json (r1, r2, r3, c1, c2)
- shift.log
- check_avail.py/.json
- s3_head.py/.json
- kord_block.txt
- indep_check.py/.json

Note: a tool guard blocked writing report.md and the docs copy refute-pit-t6.md. This text, in result.json report_md, is the full report.

