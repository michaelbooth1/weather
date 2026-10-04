# Model-parity swarm v2 — STATUS

**As of 02:45 local, 2026-10-04.** All numbers development. Phase: **hunting + spares done**; T19 (tail lens) and T24 (PIT re-derivation) running; D-RUNG1C (S3-S5 afternoon restoration) running; then deep dives and synthesis.

## Headline: the no-source parity ladder (`ladder.md`)
Two zero-parameter serving fixes, using only captured data, take served/market from 1.73x to 1.34x (pooled 1.768x → 1.328x)
and close 54% [35, 70] of the excess:
- Rung 1, evening lock-in restoration (D-DEFECT; confirmed on a production payload): closes 85% of 17-23.
- Rung 2, MG-1 captured NBM v2_mean read: closes 58/55/40% of 00-05/06-09/10-12 (to 1.18-1.26x). Needs the 83a/83b parser repair.
- Residual concentrated in 13-16 (32%; 15-16 at 2.53x). The no-source METAR remaining-rise rung t3-r3 beats rung 2 at 15-16 by −0.0181;
  D-RUNG1C tests whether restoring the existing 13-19h stages S3-S5 recovers it without a new rule.
- **No external source adds anything beyond the rung** (NBH, NBS, MOS borderline at 13-14 only, HRRR, ECMWF, soundings, NWS revision,
  neighbours, cloud/GOES). No capture case. Fixes are PROPOSALS — owner decisions.

## New since 02:15
- T18 EMOS: LEAD in every block, but the only selected information is captured v2_mean (hrrr_high + forecast_high add −0.0005, null);
  17-23 = the rung/defect family. Both refuters: not disqualified (PIT: v2 availability = NOMADS receipt; holds at +1 h).
- T20 serveability: no new capture worth making; Form A (restore lock-in + gate calibration) recommended; v2 route needs the parser repair
  (v1 parser reads a minimum on 75,049 of 110,807 rows); HRRR effective latency ~2.5-3.5 h.
- Spares: T21 (T6), T22 (T10), T23 (T5) reproduce exactly from registry text; T25 (NBS availability) and T26 (METAR basis; optimistic only for KBKF) confirm, no lead changes.

## Disk / issues
C: free 146 GB; C:\swarm 1.3 GB; no STOP. Reports blocked by the tool guard are materialised by the orchestrator from result.json.
