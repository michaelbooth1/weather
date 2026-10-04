# Model-parity swarm v2 — STATUS

**As of 01:40 local, 2026-10-04.** All numbers are development. Hunting/verification phase in progress.

## Board (from-stratum all-row, best block; refuters)
| Hunter | Verdict | Block | Estimate | Refuters |
| --- | --- | --- | --- | --- |
| T1 decided-band collapse | LEAD | 17-23 | −0.0264 | PIT stands, stat stands (but unconditional evening collapse scores −0.0287: the "decided" condition carries none of it) |
| T2 remaining-rise climatology | LEAD | 17-23 | −0.0282 | both stand; 13-16 fragile |
| T3 baselines (t3-r3 floor+remaining rise = rung) | LEAD | 17-23 | −0.0219 | both stand |
| T4 obs-trend nowcast | LEAD | 17-23 | −0.0265 | both stand; slope/sky/wind add nothing |
| T7 MOS/NBE consensus | LEAD | 17-23 | −0.0280 | stat stands (MOS-specific increment null); PIT re-running |
| T15 diurnal projection | LEAD | 17-23 | −0.0221 | both stand |
| T16 settlement mechanics | LEAD (dup of T2) | 17-23 | −0.0282 | family already refuted |
| T5 NBH remaining-hours max | LEAD (incl. 00-16 −0.0073) | 17-23 | −0.0282 | refuters running |
| T11 sounding bound | WEAK | 17-23 | −0.0007 | — |
| T13 neighbours | WEAK | 13-16 | −0.0006 | — |
| T14 cloud | WEAK | 10-12 | −0.0011 | — |
| T12 NWS revision | NULL | — | — | — |

Running: T6 (NBS), A-SingleRuns, then T8/T9/T10/T17 (HRRR/IFS/arrival), A-HRRR-AWS; then T18/T19/T20, spares, deep dives, synthesis.

## Infrastructure
F1 harness `8db69adc…`, positive control PASS (−0.006891 exact). F2 venue label (routine+SPECI, T-group tenths→F half-up) matches the winner band 626/626. F3 atlas: 17-23 past-sunset = 20% of the excess.
Acquired: METAR/SPECI 2024-05..09-29, MOS, 63 neighbours, 1-minute ASOS (10/11 stations; truth only), NBH+NBS 1608/1608, ECMWF 134/134, soundings, GOES.

## Orchestration deviation (01:25-01:40)
The first run's refuter cap counted hunters rather than families, so all 12 refuter slots (6 on Fable) went to one
family (remaining-rise/decided-band: T1, T2, T3, T4, T7, T15). Fixed with a family-aware cap (max 6 distinct
families; further members of an already-refuted family are not refuted). A resume attempt re-ran some finished agents
for under a minute and was stopped; the work continues as a second Workflow run (wf_fc8cc1f5-e74) seeded with the
first run's results (`C:\swarm\completed_results.json`). Agent count will exceed ~60 by roughly 8 (extra refuters + the killed in-flight agents re-run).
Refuters reported that writing `report.md` was blocked by a tool guard; their reports are in `result.json` (`report_md`).

## Disk
C: free ~147 GB; C:\swarm ~0.7 GB. No STOP.
