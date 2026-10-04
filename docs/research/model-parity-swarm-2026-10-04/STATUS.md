# Model-parity swarm v2 — STATUS

**As of 00:50 local, 2026-10-04.** All numbers are development. Phase 0 done; infrastructure mostly done (F2 waits on 1-minute data); acquisition in progress; hunting and verification started.

## Done
- **P0 preflight** (00:22): swarm venv ok; NBH bandwidth 39.9 MB/s, so full NBH scope; Single-Runs model ids
  confirmed, multi-location calls work (~8.8k weighted calls planned); IEM needs >= 2 s spacing; no ECMWF
  `scda` path in this window. Details: `C:\swarm\PREFLIGHT.md`.
- **F1 harness** (00:34): HARNESS_SHA256 `8db69adc…`. **Positive control PASS**: −0.006891 [−0.011894, −0.002688]
  exactly; served−served = 0; served/market 1.768×; block shares 22.5/16.6/11.8/15.3/33.9%. Note: the tail definition
  reproduces as 6.075% of rows / 70.38% of excess on this table (EF's 4.387%/64.14% is another panel).
- **F3 gap atlas** (before stratum only, 00:41): 17-23 past-sunset = 20% of the excess (served P(above
  running-max band) 0.377 vs market 0.012, realised 0.009; 11/11 markets).
- **Acquisition complete:** A-IEM-1 METAR/SPECI 2024-05..2026-09-29, A-ECMWF (134/134 runs, LastModified +7.6 h),
  A-Soundings (17 sites; no Denver RAOB), A-GOES (2,134 scenes).
- **Hunters:** T1 decided-band collapse **LEAD** (17-23 from-stratum −0.0264 [−0.0379, −0.0175], 11/11 markets,
  parameters fitted on IEM history <= 07-31) — refuters (PIT + statistics, Fable) running. T12 NWS revision
  direction **NULL**.

## Running
A-IEM-2 (MOS), A-NBH (+NBS), A-SingleRuns; hunters T2, T3, T4, T11, T14, T15; T1 refuters.

## Disk / issues
C: free 148.5 GB; C:\swarm 0.6 GB. No STOP. 111h extract read from `C:\Users\Michael\Documents\nbm-guidance-111h`.
