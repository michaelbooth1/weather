# State of play

**Last updated: 2026-10-09 10:40 America/Toronto (ALL LIVE TRADING PAUSED; N3 landed RS-A (lockin-anchor-v4 v0.5.12), H1 cut script and #258; #259, #261 and the #247 follow-up move to N4; C3 host console rehearsal not run, next date open; owner decisions 10-08 recorded).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25/27)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows. **B. An
informed, domain-neutral market maker** (weather first, YouTube views next) that widens, pulls and — only where evidence
supports it — takes a side. Going in blind is ruled out. Plan: [informed maker design](informed-maker-design-2026-09-25.md).

## Current authority

- **No live trading (owner 2026-09-25).** The owner starts any future live run personally. The pause and bleed limit are a
  fail-closed guard (#180); with today's shared wallet it would HALT, so a live run first needs a complete ledger (a
  dedicated wallet). Owner trades stay `owner-discretionary`.
- Heavy work only 00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)). Merges: roll-sensitive
  01:00-04:00 only; roll-free 00:30-09:00 (the lease refuses later); docs-only by the light path before 12:00; never 12:00-00:30.
- **Merge freeze lifted 2026-10-03, except 88a** (owner reading 10-07): the bytes of `maker_evidence_capture.py`,
  `maker_evidence_store.py` and the 88a schema record, and 88a capture behaviour (#118, #172, #177, stacked #182), wait until
  after 2026-10-14. Shared schema-registry record additions are not frozen.
- Owner decisions 2026-09-30..10-08 are rows in [DECISION_LOG](DECISION_LOG.md).
- **Testing (owner 10-04, PR #205):** focused + affected tests with PR CI as full-suite evidence once the Windows CI lane
  (#262, pinned to host Python 3.11.0) covers them. Every night head is pre-gated on the stacked base it lands on,
  with the full ratchet/audit set (lesson of N3).
- **Workstation: one Claude Code chat directed by the production agent** (owner 10-03; [preamble](WORKSTATION_SESSION_PREAMBLE.md)).
  Relayed owner approvals bind it for serving-model and merge decisions, never for money or credentials (owner 10-06).
- **Landed is not running.** A merge that adds a loop, nightly, scorer or task is finished only when its activation row
  (host, who, when, verify command) is in Open commitments below and the verify command has run once.

## Current truth

- **Production source:** `master` = `origin/master` `6ce62cba`. N3 10-09: RS-A `6ad52c89` (#189, #246 lockin-anchor-v4
  `ML_MODEL_VERSION` v0.5.12, #127 option A, #255 fold); H1 handout cut script `89593f10`; #258 `6ce62cba`. Capture recovered.
- **Host Python is 3.11.0** (gh-98778 broke #259 on the host); an upgrade paired with a release re-bind is an owner question.
- **Maker shadow:** #192 scorer landed; the forward runner (#261) did not land in N3 and goes first in N4. Activation per the
  owner's 10-08 decisions (24/7, 12 bands, hazard 0.001) the first morning after it lands. Parity definition: DECISION_LOG
  10-08. Scoring embargo: `maker_shadow_panel.py` refuses UTC 09-30..10-15 and 10-15..11-13 (a reviewed code change lifts it).
- **Build line** `codex/maker-replay-v2-build-20261003` = `89618c30`: SWOB and U6 merged (owner D1=B), U6 doc fixes. U6
  deploys from that exact tip; `WeatherReplayBundleExportNightly` stays unregistered until an owner yes (>= 10-16).
- **Exchange economics refresh** fails daily since about 10-06: Polymarket reworded `/resources/contracts` (values unchanged).
  Paper runs and live preflight are fail-closed on the stale snapshot until the matcher PR lands (N5).
- **Model, morning:** MG-1 SIGNED 2026-10-04T16:10Z at `b044e0f1`; needs parser v2 (#190); scored on new dates >= 10-15.
- **Live seals:** all must be RESEALED before any live attempt (#229).
- **Maker replay v2** (panel UTC 09-30..10-14 never read): gate spec v3.4 is the frozen oracle basis; OD18 fresh oracle
  author on this host from a filtered standalone handout. Signature when the gates pass (~10-18..20); look by 11-15.
- **C3 console rehearsal:** never run on the host: gates were GO 10-08 and 10-09 08:50 but the
  console was not opened (the owner's Q7 workstation self-test passed 10-07 22:31). Files stay staged in `C:\c3`; next date is an owner question.
- **Settlement:** WRH "Hourly Data" rows (US), WRH Temp column (foreign), floor of the HKO daily maximum (Hong Kong). EF §10c.
- **Pinned deployments (detached, locked worktrees):** watchdog, manual order journal, cold snapshot (91a `6e5ff47`; `979c0e7`
  kept until a clean 06:50 PASS) and exam; exact paths are the task actions (`Get-ScheduledTask`).
- **Disk / 91a:** first 06:50 run 10-09 on the new pin reclaimed 8.66 GB, then failed closed on a capture-admission read:
  the snapshot heartbeat is stale for about 108 s of every 300 s cycle against a 180 s limit. Fix: heartbeat during sleep
  (roll-sensitive, N5). Policy expires 10-30 (renewal week of 10-26 is an owner act). [Runbook](cold-snapshot-compression.md).
- **88a retention hold:** keep 88a data for UTC 09-27..10-15 (v2) and 10-15..10-30 (desk-study panel); lossless compression ok.

## Ordered critical path

1. **Maker replay v2:** W1/W2/F3 kernel fixes (gate-logic waits on T1-T3); Q2 horizon follow-up (#269); oracle handout cut
   then the fresh oracle author; P1-P4 on calibration dates only; gates; signature ~10-18..20. Parity from engine freeze.
2. **Merges, N4 (10-10):** #261, #264, #268 v0.2 tape, #259 fix, #210 + #270 (RS), #262, #247 follow-up, #265-#267; U6
   P0-P4 checks first. N5: heartbeat-during-sleep, econ matcher. After 10-14: #118, #172 + #182, #177.
3. **Measurements (09-29 only; never 88a 09-30..10-14):** desk-study power rule #263 (if N_req <= 14 the embargo end moves
   11-13 -> 10-31 by dated clarification). **Research:** NBS/NBH probe; T+1/T+2 NWP timing; no-METAR floor gap (item 337).
4. **Live:** prerequisites in parallel now (wallet funding and Credential Manager stay owner acts; Poly v2 contracts now
   listed by Polymarket); not before the v2 look and >= 7 days of shadow agreeing with replay.

## Open commitments (every row: owner, due, verify)

| What | Owner | Due | Verify |
| --- | --- | --- | --- |
| Shadow runner activation (#261) | production | first morning after N4 | `maker_shadow_readout.ps1` running, tick < 90 s |
| Re-pin `WeatherManualOrderJournal` to master (#127 landed) | production | 10-09 | task action path not `ebe72984` |
| Redeploy `WeatherHostHealthWatchdog` (#255 landed) | production | 10-09 | task action path not `1fc7ba35` |
| Remove `weather-cold-snapshot-deployed-979c0e7` | production | after a clean 06:50 PASS | path absent |
| N4 night plan file + stacked pre-gates | workstation | 10-09 14:30 | `landing_night_plan_v0.1` file on its branch |
| Econ matcher PR | workstation | 10-10 12:00 | PR open, roll verdict recorded |
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
