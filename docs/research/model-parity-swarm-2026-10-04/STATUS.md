# Model-parity swarm v2 — STATUS

**As of 01:45 local, 2026-10-04.** All numbers development. Phase: hunting/verification (source hunters waiting on Single-Runs).

## Headline so far
1. **Evening (17-23) loss = serving-path defect, not an information gap** (D-DEFECT, confirmed on a production payload,
   ATL 2026-09-20 23:55): late-day lock-in stages are no-ops since WU was disabled, and the calibration taper
   re-spreads mass above the high. Restoring the lock-in on captured inputs closes 71-85% of the 17-23 gap.
   Fix = restore lock-in + gate calibration above `lockin_high` — **proposal only, owner decision.** See `d-defect-evening-stage.md`.
2. **Morning (00-16): no new source beats the captured NBM v2_mean.** T5 (NBH) 00-16 −0.0073 is PIT-clean but its
   increment over v2_mean is +0.0027 [−0.0037, +0.0098] (null); v2_mean alone −0.0100. "Capture NBH for the morning" is
   closed. T6 (NBS) disqualified by its statistics refuter (source adds nothing). Morning route = known 79a/81a/111h family;
   draft pre-registration `d-morning-v2-guidance-prereg-draft.md` (DRAFT, UNSIGNED; needs the parser repair first; owner decisions on two reservation collisions).

## Board
| Hunter | Verdict | Note |
| --- | --- | --- |
| T1, T2, T3, T4, T7-r2, T15, T16 | LEAD 17-23 (−0.022..−0.028) | one family; = the evening defect; refuters stand on 17-23 |
| T5 NBH | LEAD vs served | 00-16 increment over v2_mean null; refuters: no leakage, only 17-23/06-09 stand statistically |
| T6 NBS | LEAD vs served | refute-stat: DISQUALIFIED as a source lead; refute-pit running |
| T7 MOS | LEAD vs served | both refuters not disqualified; MOS-specific increment null |
| T11, T13, T14 | WEAK (~−0.001) | — |
| T12 | NULL | — |
| T8, T9, T10, T17 | pending (wait on Single-Runs) | |

## Disk / issues
C: free 147 GB; C:\swarm 0.7 GB; no STOP. origin/master merged (EF 10p available). Several agents' report writes were blocked by a
tool guard; the orchestrator wrote those reports from the agents' returned text.
