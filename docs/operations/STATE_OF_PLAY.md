# State of play

**Last updated: 2026-10-12 12:50 America/Toronto (owner back; LFC postponed incl. session 0; N7 landed; N8/N9 planned; DST-M2, build-line merges and the host Python upgrade approved, upgrade details pending).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25/27)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows. **B. An
informed, domain-neutral market maker** (weather first, YouTube views next) that widens, pulls and — only where evidence
supports it — takes a side. Going in blind is ruled out. Plan: [informed maker design](informed-maker-design-2026-09-25.md).

## Current authority

- **Live trading paused (owner 2026-09-25).** The live fill-calibration (LFC) test is **postponed, session 0 included**
  (owner 2026-10-12); no live attempt is scheduled. No agent places, cancels or signs orders. Owner trades stay
  `owner-discretionary`.
- **Owner back as of 2026-10-12** (away 10-10 22:02 to 10-12); owner-only steps resume.
- Heavy work only 00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)). Merges: roll-sensitive
  01:00-04:00 only; roll-free 00:30-09:00 (the lease refuses later); docs-only by the light path before 12:00; never 12:00-00:30.
- **Merge freeze lifted 2026-10-03, except 88a** (owner reading 10-07): the bytes of `maker_evidence_capture.py`,
  `maker_evidence_store.py` and the 88a schema record, and 88a capture behaviour (#118, #172, #177, stacked #182), wait until
  after 2026-10-14. Shared schema-registry record additions are not frozen.
- Owner decisions 2026-09-30..10-12 are rows in [DECISION_LOG](DECISION_LOG.md).
- **Testing (owner 10-04, PR #205):** focused + affected tests, PR CI (Windows lane #262 on 3.11.0) as full-suite evidence;
  every night head pre-gated on its stacked base; host-only behaviour (3.11.0 stdlib) needs a host run.
- **Workstation: one Claude Code chat directed by the production agent** (owner 10-03; [preamble](WORKSTATION_SESSION_PREAMBLE.md)).
  Relayed owner approvals bind it for serving-model and merge decisions, never for money or credentials (owner 10-06).
  Credentials are never committed or pushed (owner 10-09; ratchet `test_no_tracked_credentials.py`).
- **Landed is not running.** A merge that adds a loop, nightly, scorer or task is finished only when its activation row
  (host, who, when, verify command) is in Open commitments below and the verify command has run once.

## Current truth

- **Production source:** `master` = `origin/master` (read it with git). N7 landed 10-12 01:22 as one RF head `d67b5798`
  (DST-M5 + M6 UTC merge deadlines, DST-M4 S4U guard UTC ages, Defender follow-ups), after N5/N6 on 10-11.
- **Forward maker shadow ACTIVE** (`WeatherMakerShadowRunner`, 24/7, 12 bands, hazard 0.001, paper only), restarted by the STOP
  file at 10-11 02:22 on the RS-B code. Stop only with `data\maker_shadow\STOP`, never a kill. Parity definition: DECISION_LOG
  10-08. Scoring embargo: `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13 (a reviewed code change lifts it).
- **Journal pin:** `WeatherManualOrderJournal` pins five module files including `wallet_reader_client.py`; any merge touching
  one makes it exit 3 until re-registered ([runbook](manual-order-journal.md)).
- **Host Python is 3.11.0;** upgrade approved as the [runbook](HOST_PYTHON_UPGRADE_RUNBOOK.md) §11 sign-off (owner 2026-10-12),
  four details pending (master-agent confirming): the night, G7 (its "after LFC session 0" gate is being revised on a separate
  branch), Q12 `STOP_AUTHORIZED`, the gap-overrun choice. No phase runs before all four. No host release store (case A).
- **DST audit:** DST-H3 landed, so its interim merge guard is retired; OD30 (the 11-01 night rule) stays until the owner retires it.
- **LFC** (postponed, above): its signed documents stay SIGNED; N-11/N-12 fix `fe5f54cf` touches `wallet_reader_client.py`.
- **Build line** `codex/maker-replay-v2-build-20261003` = `89618c30`; inventory fix `f22bea07` and U6 D6 `07dd7825` APPROVED to
  merge (owner 10-12). `WeatherReplayBundleExportNightly` stays unregistered until a separate owner yes (>= 10-16).
- **Maker replay v2** (panel UTC 09-30..10-14 never read): gate spec v3.4 is the frozen oracle basis; OD18 fresh oracle
  author on this host from a filtered standalone handout. Signature when the gates pass (~10-18..20); look by 11-15.
- **Model, morning:** MG-1 SIGNED 10-04 at `b044e0f1`; needs parser v2 (#190); scored on dates >= 10-15.
- **Live seals** must all be RESEALED before any live attempt (#229). **C3 console rehearsal** never ran on the host; deferred (owner 10-09).
- **Pinned deployments (detached, locked worktrees):** watchdog `1794fd3b`, cold snapshot (91a `6e5ff47`; `979c0e7`
  removed 10-11), exam U6 `89618c30`; exact paths are the task actions (`Get-ScheduledTask`).
- **Disk / 91a:** the unresolved 10-09 attempt was resolved 10-11 07:01 (manual run PASSED, ~16 GiB freed); policy expires 10-30.
- **88a retention hold:** keep 88a data for UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Maker replay v2:** W1/W2/F3 kernel fixes (gate-logic T1-T3 on the build line); Q2 horizon follow-up (#269); oracle
   handout cut then the fresh oracle author; P1-P4 on calibration dates only; gates; signature ~10-18..20.
2. **Merges:** N8, night of 10-13: RS `claude/integration-20261013-n8-rs` `c6977df5`, then RF2 `...-n8-rf2` `1c64f917`
   (fallback RF `...-n8-rf` `9bf466af`). N9, night of 10-14, roll-sensitive, only after N8 lands: DST-M2 via
   `claude/integration-20261014-m2-rs` `fc136e2c`. Build line: `f22bea07` + `07dd7825`. After 10-14: #118, #172 + #182, #177.
3. **Host Python upgrade:** the four pending §11 details and the G7 revision, then §T, Phase A and B, and the cutover night.
4. **Measurements (09-29 only; never 88a 09-30..10-14):** desk-study power rule #263. **Research:** NBS/NBH probe; T+1/T+2
   NWP timing; no-METAR floor gap (item 337).

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| Host Python §11: named night, Q12 `STOP_AUTHORIZED`, gap-overrun token (master-agent confirming) | owner | before G0 | DECISION_LOG row |
| G7 revision of the upgrade runbook (LFC postponed) | master-agent | before the named night | revised G7 on master |
| Merge `f22bea07` + `07dd7825` into the build line | production | next admitted window | both in the build-line tip |
| Evening-fix scoring prereg; OD30 retirement | owner | open | DECISION_LOG rows |
| Restart the wallet reader on master; LFC client json in the pinned worktree | owner | before LFC resumes | `summary` from both PCs |
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
