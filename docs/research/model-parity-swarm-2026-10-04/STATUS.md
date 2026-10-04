# Model-parity swarm v2 — STATUS

**As of 04:13 local, 2026-10-04.** All numbers development. Phase: **verification extras done and folded into SYNTHESIS** (T27 independent reproduction of rungs 1-2: REPRODUCED, rung 1 clears Bonferroni; S7 gate optional, restored strength must reach the calibration taper. R-STAT-MG1: MG-1 and t3-r3 robust but fail multiplicity; 15-16 post-hoc). Running: full repo pytest via workstation_heavy.ps1 (~63%, slow PowerShell-heavy tests; 1 failure so far). Next: triage the failure, push, draft PR.

## Headline (no-source parity ladder, `ladder.md`)
- Two zero-parameter serving fixes using only captured data close 54% [35, 70] of the served−market excess (1.73x → 1.34x):
  evening lock-in restoration (85% of 17-23; confirmed on a production payload) and the MG-1 captured-v2 morning read
  (00-12 to 1.18-1.26x; needs the parser repair). Restoring S3-S5 too adds −0.0032 at 15-16 (`d-rung1c.md`).
- Residual concentrated in 15-16 (still at the high; needs a remaining-rise rule = Phase-4 draft only).
- No external source adds anything beyond the rung. No capture case. All fixes are PROPOSALS for owner decision.

## Deep dives (all DRAFT / UNSIGNED / development)
- `d-defect-evening-stage.md` — evening serving defect + fix shape (restore lock-in + gate calibration).
- `d-morning-v2-guidance-prereg-draft.md` — MG-1 morning read (two reservation collisions = owner decisions).
- `d1-t5-prereg-draft.md` — NBH-1: recommends declining NBH capture and not activating.
- `d2-remrise-prereg-draft.md` — remaining-rise family; 17-23 is mostly the serving defect.
- `d3-t18-prereg-draft.md` — T18 EMOS (captured v2_mean only).
- `d-hg-hour-gated-composite-prereg-draft.md` — gate hours from the bulletin schedule only, nothing scored (rule 8).
- `d-cap1-capture-plan.md`, `d-cap2-capture-plan.md` — capture plans (design only; METAR needs no new source).
- `ladder.md`, `d-rung1c.md`, `r-t5-inc.md` — the decisive analyses.

## Other
T19 tail lens: the tail confirms the board; per-market tail signs cannot rank candidates. T24: NBS availability basis confirmed 1608/1608.

## Disk / issues
C: free 142 GB; C:\swarm 1.5 GB; no STOP.

