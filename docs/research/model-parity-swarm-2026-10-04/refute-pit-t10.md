# R-PIT-T10: PIT/leakage refuter for T10 (ECMWF IFS). All numbers are development reads.

Verdict: NOT DISQUALIFIED on PIT or leakage. Shifting availability by +1 h or +2 h does not change any
result. None of the claimed LEAD blocks collapses or changes class under the shift, and no violation of
rules 1-5 or 8 was found in the code. This verdict clears point-in-time and leakage only. I agree with the
hunter's attribution that the IFS increment is NULL.

Per claimed LEAD block (from stratum, all-row, candidate - served):
- 17-23 (t10-r2): LEAD -0.028683 [-0.040340,-0.019341], 11/11. Survives PIT. It is PIT-clean, but carries
  no IFS information: paired r2 - c1 (no-source control) is -0.000257 [-0.000940,+0.000236]. Under the
  01:50 steering note this is the evening serving-defect family, not an information lead.
- 13-16 (t10-r2): LEAD -0.009034 [-0.019084,-0.000474], 8/11. Survives PIT. It stays LEAD at +1 h and
  +2 h, with 9/11 markets negative. The upper bound is close to 0, about -0.0005. The hunter's claim that
  it loses to t3-r3 (+0.0026) belongs to the statistics lens and was not re-derived here.
- all (t10-r2): LEAD -0.013182. Survives PIT.
- 06-09 (t10-r1): LEAD -0.008778 [-0.017621,-0.000493]. Survives PIT; identical at +1 h and +2 h.
- r1 13-16: WEAK at +0, then LEAD at +1 h and +2 h with an upper bound just below 0. This is boundary
  noise, not a collapse.

## Availability re-derived from primary sources
- Fresh anonymous S3 HEAD requests, 01:57 local, on 6 objects across 3 runs. Each returned Last-Modified
  to the second:
  - 20260805 00z 24h .index and .grib2: 07:34:05Z and 07:34:04Z
  - 20260912 12z 6h and 48h grib2: 19:34:04Z and 19:34:11Z
  - 20260925 00z 0h .index: 07:34:01Z
  - 20260925 00z 45h grib2: 07:34:09Z

  These match values.parquet available_utc_measured exactly.
- The ETags are plain MD5 (single PUT, not multipart), so Last-Modified is the time the upload completed.
- The measured lag is 7.5669-7.5708 h on all 50,116 rows.
- T10 uses the max LastModified per station-run and asserts point-in-time on all 110,077 covered
  snapshots.
- The step-0 mx2t3 placeholders (1,474 rows) are excluded.
- METAR is used only in the history fit and in the c1 anchor. Its availability is valid + 10 min (constant)
  on routine, non-COR rows.
- Open-Meteo is not used.

## Shift re-runs (harness 8db69adc...)
Script: tools/research/model_parity/r_pit_t10_shift.py, which imports T10's own functions. The +0 run
reproduces T10 exactly.

| variant | 13-16 | 17-23 | all | 00-16 |
|---|---|---|---|---|
| +0 | LEAD -0.009034 | LEAD -0.028683 | LEAD -0.013182 | WEAK -0.006893 |
| +60 frozen | LEAD -0.009043 [-0.018867,-0.000600] 9/11 | LEAD -0.028683 | LEAD -0.013102 | WEAK -0.006780 |
| +60 refit | LEAD -0.009052 | LEAD -0.028683 | LEAD -0.013097 | WEAK -0.006773 |
| +120 frozen | LEAD -0.008904 [-0.018441,-0.000526] 9/11 | LEAD -0.028693 | LEAD -0.013010 | WEAK -0.006646 |
| +120 refit | LEAD -0.008899 [-0.018451,-0.000517] 9/11 | LEAD -0.028697 | LEAD -0.012790 | WEAK -0.006338 |

- r2 - c1 for 17-23 stays at -0.00026 to -0.00027 in every variant, with intervals that span 0.
- Before-stratum signs are negative throughout.
- Coverage is 99.34%. 0 rows fall after 09-29, and no leakage tripwire fired.

## Code check
- R1 point in time: pass.
- R2: pass. Inputs come from candidate_inputs (allow-listed), and only kind, low and high are read from
  bands.
- R3: pass. The fit uses local dates 07-25..07-31 and runs before 08-01 (asserted); winner and settlement
  are never read.
- R4: pass. The harness floor is applied, plus B zeroing.
- R5: pass. The code asserts dates <= 09-29.
- R8: pass. There is no hour gate.
- Registry: pass. Registered at 01:50:29; first score at 01:50:58.

## Not disqualifying
- T10 used the measured timestamp, not the manifest's +8 h conservative timestamp. The d1 diagnostic and
  the +1 h and +2 h runs here cover the conservative case.
- The t3-r3 and c2 attributions belong to the statistics lens and were not re-checked here.
