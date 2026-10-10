# State of play

**Last updated: 2026-10-10 04:40 America/Toronto (N4 landed #247 follow-up with #261/#262/#264, #268 v0.2 tape, #271 econ matcher and the any-LAN wallet reader; the RS head failed on host Python 3.11.0 and moves to N5; forward shadow runner ACTIVE; LFC live test signed, session 0 on UTC 10-12).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25/27)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows. **B. An
informed, domain-neutral market maker** (weather first, YouTube views next) that widens, pulls and — only where evidence
supports it — takes a side. Going in blind is ruled out. Plan: [informed maker design](informed-maker-design-2026-09-25.md).

## Current authority

- **Live trading paused (owner 2026-09-25) except the signed live fill-calibration (LFC) test** (owner 10-09): $100 worst
  case on the existing shared wallet, owner-started sessions ended by hard limits, the owner pausing manual trades from the
  first wallet snapshot to the last. No agent places, cancels or signs orders. Owner trades stay `owner-discretionary`.
- Heavy work only 00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)). Merges: roll-sensitive
  01:00-04:00 only; roll-free 00:30-09:00 (the lease refuses later); docs-only by the light path before 12:00; never 12:00-00:30.
- **Merge freeze lifted 2026-10-03, except 88a** (owner reading 10-07): the bytes of `maker_evidence_capture.py`,
  `maker_evidence_store.py` and the 88a schema record, and 88a capture behaviour (#118, #172, #177, stacked #182), wait until
  after 2026-10-14. Shared schema-registry record additions are not frozen.
- Owner decisions 2026-09-30..10-09 are rows in [DECISION_LOG](DECISION_LOG.md).
- **Testing (owner 10-04, PR #205):** focused + affected tests with PR CI as full-suite evidence once the Windows CI lane
  (#262, pinned to host Python 3.11.0) covers them. Every night head is pre-gated on the stacked base it lands on. A
  workstation run on Python >= 3.11.8 hides 3.11.0-only stdlib bugs (N4 lesson); host-only behaviour needs a host run.
- **Workstation: one Claude Code chat directed by the production agent** (owner 10-03; [preamble](WORKSTATION_SESSION_PREAMBLE.md)).
  Relayed owner approvals bind it for serving-model and merge decisions, never for money or credentials (owner 10-06).
  Credentials are never committed or pushed (owner 10-09; ratchet `test_no_tracked_credentials.py`).
- **Landed is not running.** A merge that adds a loop, nightly, scorer or task is finished only when its activation row
  (host, who, when, verify command) is in Open commitments below and the verify command has run once.

## Current truth

- **Production source:** `master` = `origin/master` `1e0e8479`. N4 10-10: #247 follow-up `26841798` (carried #261, #262,
  #264), #268 v0.2 tape `b0489b31`, #271 econ matcher `8aebd1b5`, wallet reader any-LAN `1e0e8479` (roll-free, by hand).
- **N4 RS head failed** on host Python 3.11.0 (gh-98778 in 3 #259 tests); #259 fixed (`9d409b21c`), rides N5 RS-A.
- **Host Python is 3.11.0;** the upgrade with a release re-bind is approved (owner 10-09), after N5; tzdata 2026.3 with it.
- **Forward maker shadow ACTIVE** since 2026-10-10 04:16 (`WeatherMakerShadowRunner`, 24/7, 12 bands, hazard 0.001, paper
  only). Stop only with the `data\maker_shadow\STOP` file, never a kill. Parity definition: DECISION_LOG 10-08. Scoring
  embargo: `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13 (a reviewed code change lifts it).
- **Wallet reader** admits any private-LAN caller (owner 10-09); `WeatherManualOrderJournal` re-pinned 10-10 04:11 (exit 0).
- **LFC live test:** preregistration set SIGNED 10-09 14:09, clarification C SIGNED 20:28, clarification D drafted for
  signature (fee rule now maker-fee-class: weather is taker-only, EF §10o). Code is a pinned, locked workstation worktree,
  never master (Fable delta-3 PASS). Session 0 off-panel on UTC 10-12 ~15:00Z; session 1 not before UTC 10-15.
- **Build line** `codex/maker-replay-v2-build-20261003` = `89618c30`. U6 deployed and proved 10-10 00:31 (pins match, 7 gated
  refusals); `WeatherReplayBundleExportNightly` stays unregistered until an owner yes (>= 10-16). No release store on the host.
- **Maker replay v2** (panel UTC 09-30..10-14 never read): gate spec v3.4 is the frozen oracle basis; OD18 fresh oracle
  author on this host from a filtered standalone handout. Signature when the gates pass (~10-18..20); look by 11-15.
- **Model, morning:** MG-1 SIGNED 10-04 at `b044e0f1`; needs parser v2 (#190); scored on dates >= 10-15.
- **Live seals** must all be RESEALED before any live attempt (#229). **C3 console rehearsal** never ran on the host; deferred (owner 10-09).
- **RE-1 economics (Q-22):** realized net −36.97 pUSD over the five lots plus rewards; FINDINGS_DIGEST item 7, EF §10m.
- **Settlement:** WRH "Hourly Data" rows (US), WRH Temp column (foreign), floor of the HKO daily maximum (Hong Kong). EF §10c.
- **Pinned deployments (detached, locked worktrees):** watchdog `1794fd3b`, cold snapshot (91a `6e5ff47`; `979c0e7` kept until a
  clean 06:50 PASS), exam U6 `89618c30`; exact paths are the task actions (`Get-ScheduledTask`).
- **Disk / 91a:** the 06:50 run fails closed (snapshot heartbeat stale ~108 s of 300 s vs 180 s); fix in N5 RS-B; policy expires 10-30.
- **88a retention hold:** keep 88a data for UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Maker replay v2:** W1/W2/F3 kernel fixes (gate-logic T1-T3 on the build line); Q2 horizon follow-up (#269); oracle
   handout cut then the fresh oracle author; P1-P4 on calibration dates only; gates; signature ~10-18..20.
2. **LFC:** D signed; reader restarted; session 0 UTC 10-12; N-11/N-12 code fixes before session 1 (UTC >= 10-15).
3. **Merges, N5 (10-11):** RS-A (#259 + #210 + #270), RS-B (snapshot heartbeat + v0.2 backoff + #265 + #267), RF (#272 + #273);
   watchdog re-pin after #273; after 10-14: #118, #172 + #182, #177; host Python upgrade night >= N6.
4. **Measurements (09-29 only; never 88a 09-30..10-14):** desk-study power rule #263. **Research:** NBS/NBH probe; T+1/T+2
   NWP timing; no-METAR floor gap (item 337).

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| Restart the wallet reader on master `1e0e8479`; LFC client json in the pinned worktree | owner | before 10-12 15:00Z | `summary` from both PCs |
| Sign LFC clarification D | owner | before session-0 attest | signature record on the runbook branch |
| 88a extra-conditions byte copy + sha for session 0 | production | 10-12 ~14:20Z | workstation sha matches |
| N5 night plan file + stacked pre-gates | workstation | 10-10 15:00 | `landing_night_plan_v0.1` file on its branch |
| Redeploy and re-register the watchdog after #273 | production | before 11-01 | `status.ps1 -Json` watchdog CURRENT |
| Remove `weather-cold-snapshot-deployed-979c0e7` | production | after a clean 06:50 PASS | path absent |
| 91a policy renewal | owner (production prepares) | week of 10-26 | new policy sha, expiry > 10-30 |

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture. Worktrees: `GIT_LFS_SKIP_SMUDGE=1`;
  pytest: `--basetemp`, `TEMP`/`TMP` inside a cleaned root. Long agent jobs run detached, not as tool background calls.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay, release binding and
  evidence retention remain mandatory; approved workstation work is never parked.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
