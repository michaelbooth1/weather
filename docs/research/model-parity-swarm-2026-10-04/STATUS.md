# Model-parity swarm v2 — STATUS

**As of 02:15 local, 2026-10-04.** All numbers development. Phase: **hunting T1-T17 complete**; T18 (EMOS) and T20 (serveability) running; then T19, spares, deep dives, synthesis.

## Headline so far
1. **Evening (17-23) loss = serving-path defect** (D-DEFECT, confirmed on a production payload, ATL 2026-09-20 23:55):
   late-day lock-in stages are no-ops since WU was disabled; the calibration taper re-spreads mass above the high.
   Restoring the lock-in on captured inputs closes 71-85% of the 17-23 gap. Fix = restore lock-in + gate calibration
   above `lockin_high` — **proposal only, owner decision.** `d-defect-evening-stage.md`.
2. **No external T+0 source adds information over what production already captures.** Every source hunter's gain
   versus served is reproduced by a no-source control (captured NBM v2_mean in the morning; remaining-hours /
   floor collapse in the afternoon/evening):
   - T5 NBH: 00-16 increment over v2_mean null (+0.0027 [−0.0037, +0.0098]); "capture NBH for the morning" closed.
   - T6 NBS, T8 HRRR, T10 ECMWF IFS: LEAD vs served on the classifier, but the statistics refuter DISQUALIFIED each as a
     source lead (no-source control matches); PIT refuters found no leakage.
   - T7 MOS: MOS-specific increment null. T9 HRRR lagged ensemble: NULL. T17 market arrival: WEAK ≈ null.
   - T11 soundings, T13 neighbours, T14 cloud: WEAK (~−0.001). T12 NWS revision: NULL.
3. **Morning route** = known 79a/81a/111h family (EF 10h/10j/10p): draft pre-registration
   `d-morning-v2-guidance-prereg-draft.md` (DRAFT, UNSIGNED; parser repair first; two reservation collisions are owner decisions).

## Acquisition (all complete)
METAR/SPECI 2024-05..09-29; MOS; 63 neighbours; 1-minute ASOS (truth only); NBH+NBS 1608/1608; Single-Runs (HRRR/NBM/IFS);
HRRR-AWS byte-range check; ECMWF 134/134; soundings; GOES.

## Disk / issues
C: free 147 GB; C:\swarm 0.73 GB; no STOP. A tool guard blocked many agents' report.md writes; the orchestrator
materialised those reports from `result.json` (`report_md`) or, where absent, from the agent's returned summary (marked as reconstructed).
