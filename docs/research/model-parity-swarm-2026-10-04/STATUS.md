# Model-parity swarm v2 — STATUS

**FINAL — 04:58 local, 2026-10-04.** All numbers development. **Swarm complete.** Draft PR #187 (https://github.com/michaelbooth1/weather/pull/187), origin/master merged (conflicts in OPEN_QUESTIONS Q-08/Q-09 and the generated correspondence index resolved). Tests: full repo pytest via workstation_heavy.ps1 7107 passed / 50 skipped / 1 failed (an untracked research file, fixed by committing it; import-architecture 27/27 after); agent_docs_audit PASS; correspondence index --check OK; GitHub CI green on 130ff210 (audit, test, hook x4, native-launch x4). Read `SYNTHESIS.md` first; owner decisions are listed there and in the PR body. Nothing merged, nothing served, no config changed.

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

