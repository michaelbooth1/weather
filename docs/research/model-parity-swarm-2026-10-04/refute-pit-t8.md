# R-PIT-T8: PIT/leakage refutation of T8 (HRRR latest run, Open-Meteo Single-Runs) - development

**Verdict: NOT DISQUALIFIED on point-in-time or leakage grounds.** I found no leakage. Rules 1-5 and 8 hold in the code. Neither claimed LEAD block collapses when availability is shifted +1 h.

Neither block stands as an HRRR lead:

- **17-23 (t8-r1, -0.0282).**
  - The result is PIT-clean and stable under the shift: -0.0281 at +1 h and -0.0279 at +2 h, LEAD both times, 11/11 markets.
  - The no-source control t8-c1 scores -0.0286 at every delay.
  - Paired r1 - c1 is +0.0004 at the design delay, +0.0005 at +1 h, and +0.0007 [+0.0000, +0.0015] at +2 h.
  - The calibrated r2 is worse than no source: r2 - c1 = +0.0017 [+0.0007, +0.0029].
  - This is the D-DEFECT evening serving defect. The LEAD class is real; the attribution to HRRR is not. The hunter says the same.
- **06-09 (t8-r2, -0.0079).**
  - It survives +1 h narrowly. With frozen parameters it is -0.0079 [-0.0161, -0.0001], 9/11, LEAD; refit gives -0.0079 [-0.0160, -0.0001], LEAD.
  - At +2 h it becomes WEAK: -0.0076 [-0.0158, +0.0001], both frozen and refit.
  - It is LEAD only through the 5%-of-gap bar, and the upper bound sits about 0.0001 from zero, so it is fragile.
  - It adds nothing over the captured guidance. Production's already captured hrrr_high (c2) gives -0.0074 [-0.0158, -0.0002], 10/11, LEAD, independent of the shift.
  - Paired r2 - c2 is -0.0005 / -0.0005 / -0.0002 (design / +1 h / +2 h), with 3/11 markets negative.
  - It belongs to the "served under-uses captured guidance" family. It is not a capture case for Single-Runs.

All numbers are development. HARNESS_SHA256 is 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74. The design-delay (d3) reproduction matches T8 exactly.

## 1. Availability re-derived from primary sources

The only external candidate input is Open-Meteo Single-Runs HRRR (ncep_hrrr_conus): runs 06/09/12/15/18/21Z, eligible at run + 3 h.

**AWS S3 LastModified (independent).** I listed the final-lead object of every HRRR run from 2026-07-25 to 09-29 with anonymous ListObjectsV2: 402 runs, f48 for 06/12/18Z and f18 for 09/15/21Z. The raw list is hrrr_final_lastmodified.txt. Lag after run time:

| final lead | mean | p95 | p99 | max |
|---|---|---|---|---|
| f18 | +88 min | | +101 min | +163 min (09-14 15Z) |
| f48 | +108 min | +116 min | +125 min | +202 min (09-23 18Z) |

- I checked the +202 min outlier (09-23 18Z) lead by lead.
  - f00-f34 were on S3 by 19:32Z (+92 min). Only f35-f48 were rewritten, at 21:22Z.
  - For T+0 snapshots, those leads are reachable only as the local-midnight endpoint for central, mountain and Pacific target 09-24, at snapshots from 09-24 05Z onward. That is after 21:22Z, so no value was used before it was public.
- 09-14 15Z/18Z were complete by +163 min, inside +3 h.

**Other sources.**
- A-HRRR-AWS (12/18Z f00-f12, 1,742 objects): the latest object landed at +92 min.
  - Single-Runs equals the AWS GRIB within 0.29 F at 10 of 11 stations, so the archive holds the operational run, not reprocessed data.
  - KSFO is a different grid cell, a point-selection effect, not leakage.
- Open-Meteo publication: the meta.json samples show HRRR at +91.5 and +93.1 min.
  - My own live sample (10-04 05:58Z) showed the 04Z run available at +94.5 min (last_run_availability_time 1791092073, init 1791086400).
  - Open-Meteo therefore trails S3 by only minutes.
- Caveat, not disqualifying: there is no historical per-run Open-Meteo publication stamp. For the 48 h synoptic runs, Open-Meteo's ingest time is inferred (about 2 h), not measured. The +3 h design delay is about 1 h conservative against every S3 object a T+0 snapshot uses.
- IEM METAR is a fit input only (local dates 07-25..08-22), never a served input. available_utc = valid + 10 min on every KATL row (n = 24,588). The c1 fit base uses available_utc <= t.
- The c2 control requires production's hrrr_fetched_at <= captured_at_utc. The 105 snapshots without that stamp fall back to served.

## 2. Re-run with availability shifted (harness; refute_pit_t8_shift.py)

Availability is set to run + 4 h (+1 h) and run + 5 h (+2 h). "Frozen" keeps T8's parameters; "refit" re-fits them with the shifted run selection. Each cell is the from-stratum all-row candidate - served, with its 95% W interval, the class, and the number of markets negative out of 11.

| rule / block | design (+3 h) | +1 h frozen | +1 h refit | +2 h frozen | +2 h refit |
|---|---|---|---|---|---|
| r1 17-23 | -0.0282 [-0.0399,-0.0187] LEAD 11, before -0.0320 | -0.0281 [-0.0400,-0.0187] LEAD 11 | n/a (no params) | -0.0279 [-0.0398,-0.0185] LEAD 11 | n/a |
| r2 17-23 | -0.0269 LEAD 11 | -0.0268 LEAD | -0.0268 LEAD | -0.0266 LEAD | -0.0266 LEAD |
| r2 06-09 | -0.0079 [-0.0162,-0.0002] LEAD 9, before -0.0092 | -0.0079 [-0.0161,-0.0001] LEAD 9 | -0.0079 [-0.0160,-0.0001] LEAD 9 | -0.0076 [-0.0158,+0.0001] WEAK | -0.0076 [-0.0158,+0.0001] WEAK |
| r3 06-09 | -0.0079 LEAD | -0.0078 LEAD | -0.0078 LEAD | -0.0076 WEAK | -0.0077 LEAD |
| r4 06-09 | -0.0083 LEAD | -0.0082 LEAD | -0.0081 LEAD | -0.0079 LEAD | -0.0080 LEAD |
| r1 06-09 | -0.0080 WEAK | -0.0078 WEAK | n/a | -0.0074 WEAK | n/a |
| c1 17-23 (no source) | -0.0286 LEAD 11 | -0.0286 | -0.0286 | -0.0286 | -0.0286 |
| c2 06-09 (captured hrrr_high) | -0.0074 [-0.0158,-0.0002] LEAD 10 | same | same | same | same |

Paired differences (from stratum):

| pair | design | +1 h | +2 h |
|---|---|---|---|
| r1 - c1, 17-23 | +0.0004 [-0.0001,+0.0010] | +0.0005 [-0.0001,+0.0012] | +0.0007 [+0.0000,+0.0015] |
| r2 - c1, 17-23 | +0.0017 [+0.0007,+0.0029] | +0.0018 | +0.0020 [+0.0008,+0.0034] |
| r2 - c2, 06-09 | -0.0005 [-0.0057,+0.0039] 3/11 | -0.0005 [-0.0058,+0.0041] | -0.0002 [-0.0056,+0.0044] |

- Coverage is 110,077 of 110,807 snapshots at every delay, because older runs fill the gaps.
- h.assert_point_in_time passed on every covered snapshot in all 28 scorings.
- No leakage-suspect groups were flagged, and 0 rows have a target date after 09-29.

## 3. Rules checked in the code (t8_hrrr_latest.py, read in full)

- **Rule 1 (point in time).** Runs are selected only if avail <= captured_at_utc, and only valid hours strictly after t are used. The PIT assert runs on every covered row, and load_hrrr asserts that the manifest delay is 3 h.
  - The null 08-10 18Z run can be labelled "latest", but that only affects the age statistic. Its NaN values are skipped.
- **Rule 2 (no market input).** Only the allow-listed h.candidate_inputs() is used.
- **Rule 3 (no settlement leakage).** No winner or settlement value is read. The METAR fit is asserted to end at or before 08-22.
  - Consequence: the before-stratum reads for r2-r4 and c1 are in-sample. r1 has zero parameters, so 17-23 does not depend on this.
- **Rule 4 (floor).** score() applies the floor, and band_probs also enforces max(B, X).
- **Rule 5 (dates).** The code asserts date <= 09-29, and the count of rows after 09-29 is 0.
- **Rule 8 (no hour gate).** Not engaged: HRRR is not NBP/NBM, and the code has no hour gate.
- **Minor form issue, not leakage.** The remaining-hours window includes the local-midnight valid hour, which belongs to D+1.
- **Registry.** The rules were registered at 01:50:40, before the first score at 01:50:54.

## 4. Bottom line

- PIT is clean and the result is robust to +1 h, so nothing is disqualified.
- 17-23 stands as a classifier LEAD, but it is the no-source collapse (D-DEFECT), not HRRR information.
- 06-09 stands narrowly at +1 h, falls to WEAK at +2 h, and is matched by the captured hrrr_high.
- The HRRR increment is NULL in both blocks. There is no case for capturing HRRR Single-Runs.

Files:
- Code: C:\pt\swarm\tools\research\model_parity\refute_pit_t8_shift.py
- Outputs: C:\swarm\out\refute-pit-t8\ (shift_results.json, 28 *.score.json, run.log, hrrr_final_lastmodified.txt)
- Background PID 61420 exited on its own.

