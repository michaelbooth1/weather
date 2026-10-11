# State of play

**Last updated: 2026-10-11 08:30 America/Toronto (N5 landed RS-A, RS-B and RF; early N6 landed DST-H3 and #272 D1; shadow restarted on the new code; journal re-pinned after a wallet-reader merge; 91a unblocked after an unresolved 10-09 attempt; owner away since 10-10 22:02).**
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
- **Owner away since 2026-10-10 22:02** ("keep things working and improving"; session 0 may move). Owner-only steps wait.
- Heavy work only 00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)). Merges: roll-sensitive
  01:00-04:00 only; roll-free 00:30-09:00 (the lease refuses later); docs-only by the light path before 12:00; never 12:00-00:30.
- **Merge freeze lifted 2026-10-03, except 88a** (owner reading 10-07): the bytes of `maker_evidence_capture.py`,
  `maker_evidence_store.py` and the 88a schema record, and 88a capture behaviour (#118, #172, #177, stacked #182), wait until
  after 2026-10-14. Shared schema-registry record additions are not frozen.
- Owner decisions 2026-09-30..10-10 are rows in [DECISION_LOG](DECISION_LOG.md).
- **Testing (owner 10-04, PR #205):** focused + affected tests, PR CI (Windows lane #262 on 3.11.0) as full-suite evidence;
  every night head pre-gated on its stacked base; host-only behaviour (3.11.0 stdlib) needs a host run.
- **Workstation: one Claude Code chat directed by the production agent** (owner 10-03; [preamble](WORKSTATION_SESSION_PREAMBLE.md)).
  Relayed owner approvals bind it for serving-model and merge decisions, never for money or credentials (owner 10-06).
  Credentials are never committed or pushed (owner 10-09; ratchet `test_no_tracked_credentials.py`).
- **Landed is not running.** A merge that adds a loop, nightly, scorer or task is finished only when its activation row
  (host, who, when, verify command) is in Open commitments below and the verify command has run once.

## Current truth

- **Production source:** `master` = `origin/master` (read it with git). N5 10-11: RS-A `2745f00d` (#259, #210, #270), RS-B
  `a0d70a4c` (snapshot heartbeat, v0.2 backoff, #265, #267), RF `a915eae3` (#272, #273); then the host-load hook fix, the
  wallet-reader HTTPError close fix (290 focused tests on host 3.11.0), and early N6 `28f64f23` (DST-H3, #272 D1).
- **Forward maker shadow ACTIVE** (`WeatherMakerShadowRunner`, 24/7, 12 bands, hazard 0.001, paper only), restarted by the STOP
  file at 10-11 02:22 on the RS-B code. Stop only with `data\maker_shadow\STOP`, never a kill. Parity definition: DECISION_LOG
  10-08. Scoring embargo: `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13 (a reviewed code change lifts it).
- **Journal pin:** `WeatherManualOrderJournal` pins five module files including `wallet_reader_client.py`; any merge touching
  one makes it exit 3 until re-registered ([runbook](manual-order-journal.md)); missed 10-11 03:35, re-pinned 04:37.
- **Host Python is 3.11.0;** the upgrade with a release re-bind is approved (owner 10-09) for one night >= N6; tzdata 2026.3 with it.
- **DST audit:** DST-H3 landed, so its interim merge guard is retired; OD30 (the 11-01 night rule) stays until the owner retires it.
- **LFC live test:** preregistration SIGNED 10-09 14:09, clarifications C (10-09 20:28) and D (10-10 15:39) SIGNED. Code is a
  pinned, locked workstation worktree, never master. Session 0 off-panel planned UTC 10-12 ~15:00Z (may move); session 1 not
  before UTC 10-15. N-11/N-12 fix `fe5f54cf` touches `wallet_reader_client.py` (journal re-pin when it lands).
- **Build line** `codex/maker-replay-v2-build-20261003` = `89618c30`; inventory fix `f22bea07` and U6 D6 `07dd7825` wait for an
  owner yes. `WeatherReplayBundleExportNightly` stays unregistered until an owner yes (>= 10-16). No release store on the host.
- **Maker replay v2** (panel UTC 09-30..10-14 never read): gate spec v3.4 is the frozen oracle basis; OD18 fresh oracle
  author on this host from a filtered standalone handout. Signature when the gates pass (~10-18..20); look by 11-15.
- **Model, morning:** MG-1 SIGNED 10-04 at `b044e0f1`; needs parser v2 (#190); scored on dates >= 10-15.
- **Live seals** must all be RESEALED before any live attempt (#229). **C3 console rehearsal** never ran on the host; deferred (owner 10-09).
- **Pinned deployments (detached, locked worktrees):** watchdog `1794fd3b`, cold snapshot (91a `6e5ff47`; `979c0e7`
  removed 10-11), exam U6 `89618c30`; exact paths are the task actions (`Get-ScheduledTask`).
- **Disk / 91a:** the 10-10 and 10-11 06:50 runs refused at preflight because the failed 10-09 attempt had no resolution record
  (not the heartbeat). Resolved 10-11 07:01; a manual run 07:01-08:16 PASSED (about 16 GiB freed). Policy expires 10-30.
- **88a retention hold:** keep 88a data for UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Maker replay v2:** W1/W2/F3 kernel fixes (gate-logic T1-T3 on the build line); Q2 horizon follow-up (#269); oracle
   handout cut then the fresh oracle author; P1-P4 on calibration dates only; gates; signature ~10-18..20.
2. **LFC:** owner restarts the reader and places the client json; session 0 (date may move); N-11/N-12 before session 1.
3. **Merges, N7 (10-12):** one RF head, landed alone: DST-M5 + M6, DST-M4 (S4U guard; may need a host re-register), Defender follow-ups; after 10-14:
   #118, #172 + #182, #177; host Python upgrade night.
4. **Measurements (09-29 only; never 88a 09-30..10-14):** desk-study power rule #263. **Research:** NBS/NBH probe; T+1/T+2
   NWP timing; no-METAR floor gap (item 337).

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| Restart the wallet reader on master; LFC client json in the pinned worktree | owner | before session 0 | `summary` from both PCs |
| Session 0 timing; build-line merges; evening-fix scoring prereg; OD30 retirement | owner | on return | DECISION_LOG rows |
| 88a extra-conditions byte copy + sha for session 0 | production | session 0 T-40 | workstation sha matches |
| Scope and run the pinned watchdog redeploy + re-register (DRIFT since #273, DST-H3) | owner scope, production runs | before 11-01 | `status.ps1 -Json` watchdog CURRENT |
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
