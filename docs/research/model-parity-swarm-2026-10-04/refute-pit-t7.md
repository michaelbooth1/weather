# R-PIT-T7: PIT/leakage refutation of T7 (MOS/NBE consensus). Verdict: NOT DISQUALIFIED (development)

No leakage found. Every claimed LEAD block of t7-r1, t7-r2 and t7-c1 survives availability shifted +1 h and +2 h (all models, including the measured NBE). The best block, t7-r2 17-23 at -0.027978, survives every shift tried, up to +6 h on all models. All numbers are development, and the from stratum was inspected before. HARNESS_SHA256 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74.

## Blocks that stand (from-stratum all-row candidate - served: base / +1 h / +2 h)
- t7-r2: every block is LEAD at base, +1 h and +2 h.
  - 00-05: -0.0161 / -0.0160 / -0.0160
  - 06-09: -0.0170 / -0.0170 / -0.0168
  - 10-12: -0.0122 / -0.0116 / -0.0118
  - 13-16: -0.0129 / -0.0126 / -0.0121
  - 17-23: -0.0280 [-0.0396, -0.0186] / -0.0280 [-0.0396, -0.0186] / -0.0279 [-0.0395, -0.0185]
  - 00-16: -0.0148 / -0.0147 / -0.0145
- t7-r1: LEAD stands in 00-05 (-0.0163 / -0.0162 / -0.0161), 06-09 (-0.0173 / -0.0172 / -0.0170), 10-12 (-0.0135 at all three) and 00-16 (-0.0137 / -0.0136 / -0.0136). 13-16 stays WEAK and 17-23 stays NULL; T7 did not claim either.
- t7-c1: LEAD stands in 00-05 (-0.0154 / -0.0148 / -0.0133), 06-09 (-0.0159 at all three), 10-12 (-0.0121 at all three) and 00-16 (-0.0122 / -0.0120 / -0.0114). 13-16 stays WEAK and 17-23 stays NULL; neither was claimed.
- leakage_suspect_groups is empty in all 15 refuter scores, and the date guard counted 0 rows after 2026-09-29.

## Caveats for the synthesis (framing, not PIT defects)
- The r2 17-23 gain is the decided-band family, X = max(floor, Y), and is barely sensitive to which guidance is used or how stale it is:
  - all models at +6 h: -0.0279
  - LAV only at +3 h: -0.0281
  - without LAV: -0.0221
  - NBE only: -0.0053
  Do not count it again alongside T1/T2.
- c1 is a Gaussian on the captured NBM v2_mean, with no MOS. It is robust to the shifts and carries about 90% of the morning gain. The MOS-specific increment is about -0.001.

## 1. Availability re-derived from primary sources
- NBE (S3 blend_nbetx LastModified)
  - I re-listed 10 cycles with anonymous ListObjectsV2: the 2 earliest-lag, the 2 latest-lag, 4 random 00/12Z and 2 random off-synoptic cycles. The stored available_utc equals the live S3 LastModified to the second in 10/10.
  - The 35-min lags occur only on off-synoptic May cycles, which are fit history only.
  - In the evaluation window IEM has 00Z and 12Z only. Median lags are 80 and 98 min, with a minimum of 76 min.
  - Long lags of up to 29 h are re-uploads, which only make the timestamp conservative.
  - 220 rows have no listing and are excluded.
  - Status: measured, OK.
- MAV
  - Availability is runtime + 4h30, based on the NCO production-status schedule: GFS MOS completes at 04:12Z for 00Z runs and 16:13Z for 12Z runs.
  - There is no per-object timestamp: IEM keeps no ingest time and has no AFOS copy.
  - Status: schedule evidence.
- MET, MEX and LAV
  - Availability is +4h00, +5h00 and +1h00. These are assumptions, not measurements.
  - I did not measure live NOMADS or tgftp listings, because they are dated after 2026-09-30 (COMMON STOP rule).
  - The shift tests below cover this.
- Captured NBM v2 (c1)
  - The basis is response_received_at.
  - In 5 spot checks it was at or after the S3 blend_nbptx LastModified. Examples: 01Z captured at about 04:00Z vs S3 about 02:05Z; 07Z captured at 08:19Z vs S3 08:18Z.
  - Status: PIT, OK.
- Floor
  - These are harness-captured production features, so they are out of T7's scope (81a/F1).
- IEM METAR
  - Used only as fit truth for local dates 06-01..07-31, never as an input.
- Not used by T7: Open-Meteo, HRRR, ASOS 1-minute.

## 2. Shift re-runs (harness)
- Method:
  - r-pit-t7_shift.py reuses T7's functions unchanged.
  - The availability column is shifted for every model, NBE included, in both the fit and the scoring, on top of T7's lags.
  - r-pit-t7_c1_shift.py rebuilds the c1 centre from each market-day's captured issue history. At snapshot t it uses the latest pair with v2_available_at + lag <= t; otherwise the row falls back to served.
  - At lag 0 this reproduces T7's c1 exactly.
- Stress tests, all LEAD in every block:
  - r2 with all models at +6 h: 17-23 -0.0279, 00-16 -0.0139
  - r2 without LAV: 17-23 -0.0221, 00-16 -0.0142
  - r2 with LAV only at +3 h: 17-23 -0.0281
  - r4 (NBE only) at +1 h and +2 h: 00-16 -0.0121, 17-23 -0.0053
- Coverage:
  - r1 and r2 stay at 0.9934.
  - c1 falls to 0.9809 at +1 h and 0.9550 at +2 h.

## 3. Rules 1-5 and 8 in code (t7_mos_consensus.py, t7_controls.py, harness.py)
- Rule 1: PASS.
  - Run selection uses searchsorted(side=right) on available time, so av <= t.
  - build() asserts h.assert_point_in_time on the latest run used for each snapshot. Times are tz-aware UTC ns.
  - r2 uses only values valid after t, from runs available by t.
  - c1 asserts v2_available_at <= t.
- Rule 2: PASS. Candidates read only h.candidate_inputs(), which is allow-listed. FORBIDDEN is checked in candidate_inputs() and again in score().
- Rule 3: PASS.
  - No winner or settlement value is read.
  - b_h and s_h are fitted on local dates 06-01..07-31 against METAR.
  - Nothing is tuned on the table.
- Rule 4: PASS.
  - The harness floor is on by default, and unfloored was never used.
  - r2 additionally zeroes floor_impossible bands.
- Rule 5: PASS.
  - Date assert: 0 rows.
  - MOS runtimes >= 09-30 were dropped at tidy.
  - Nothing dated 09-30 or later was read.
- Rule 8: PASS.
  - No guidance/served hour switching.
  - The n_x 15:00 valid hour and LAV 10-18 were registered at 00:55:18, before the first score at 00:58:05.
  - Moving 15:00 to 14:00 or 16:00 changes only 13-16 (-0.0120 and -0.0133); all blocks stay LEAD.

## 4. Unverifiable but not load-bearing
- MET, MEX and LAV lags are not measured per object.
- Under a strict rule-1 reading only r4 is fully measured. r4 is LEAD in every block under +1 h and +2 h, but its 17-23 effect is only -0.0053.

## Files
- Code:
  - C:\pt\swarm\tools\research\model_parity\r-pit-t7_shift.py
  - C:\pt\swarm\tools\research\model_parity\r-pit-t7_c1_shift.py
- Outputs, in C:\swarm\out\refute-pit-t7\:
  - *.score.json
  - shift_results.json
  - c1_shift_results.json
  - extra_results.json
  - logs
- No processes left running.

