# State of play

**Last updated: 2026-10-03 23:00 America/Toronto (ALL LIVE TRADING PAUSED; exam closed NOT EXECUTED, panel unread; maker replay v2 build started; merge freeze lifted except 88a changes until after 10-14; ~107 GiB free).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25/27)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows. **B. An
informed, domain-neutral market maker** (weather first, YouTube views next) that widens, pulls and — only where evidence
supports it — takes a side. Going in blind is ruled out. Plan: [informed maker design](informed-maker-design-2026-09-25.md).

## Current authority

- **No live trading (owner 2026-09-25).** The owner starts any future live run personally. The pause and bleed limit are built
  as a fail-closed guard (#180, unmerged); with today's shared
  wallet it would HALT, so a live run first needs a complete ledger (a dedicated wallet). Owner trades stay `owner-discretionary`.
- Heavy work only 00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)). Merges: roll-sensitive
  01:00-04:00 only; roll-free 00:30-12:00; docs-only by the light path before 12:00; never 12:00-00:30.
- **Merge freeze lifted 2026-10-03, except 88a:** changes to 88a capture code or behaviour (#118, #172, #177, stacked #182)
  wait until after 2026-10-14 so the unread panel is captured by one 88a code version.
- 2026-09-30 through 2026-10-03 owner decisions are rows in [DECISION_LOG](DECISION_LOG.md).
- **Workstation: one Claude Code chat directed by the production agent** (cross-session messaging, owner 2026-10-03; bigger decisions to the owner first); prompts start from [the session preamble](WORKSTATION_SESSION_PREAMBLE.md).
  Claude Code has no host-load hook; the S4U guard is its backstop. Use a short `--basetemp` there (Windows MAX_PATH).

## Current truth

- **Production source:** `master` = `origin/master`; last code integration `979c0e752` (2026-10-01 01:38); later merges are
  docs-only light paths until tonight's roll-free batch.
- **Exam `maker-replay-2026-10-15`: closed NOT EXECUTED (owner 2026-10-03).** Calibration 09-27 from pinned `664c8943`: band
  union N_d = 170 conditions, 1.30 GB input per date (~546 MiB allowed), export peak 9.9 GiB beside capture (free RAM fell to
  1.38 GB). Look unspent; panel UTC 09-30..10-13 (+10-14) never exported or read. [Plan B audit](../roadmap/audits/exam-plan-b-2026-10-03.md).
- **Successor: maker replay v2** (design PR #176 `4bbce397`, approved 1-6): per-band event schedule (cost linear in bands),
  T+1/T+2 bands only, compact v0.2 bundles, the 32 GB workstation runs rehearsal and look, ceilings and an executability gate
  from calibration-only rehearsals **before** signature, a reachability gate. UTC 10-15 settlement-only; δ_ref = the signed
  hurdle. Build W0-W8 on `codex/maker-replay-v2-build-20261003` (exam tree's v0.1 stack as base); signature by 2026-10-23,
  look by 2026-11-15. The capture host may export only within the nightly wrapper (2 GiB, 2,700 s): v0.1 needs 5-10 GiB, so
  the v0.2 exporter measurement (S2/P1) decides whether exports stay on this host.
- **Dry-run harness (#167):** v0.1 exports cost 117-160 s and 5.1-5.5 GB per day on the workstation; one 12-city rehearsal
  date is >10x the per-date limits and rehearsal memory scales with events x conditions; the pinned set's pull-opportunity cap
  compares rehearsed events with never-measured pull candidates (defect; fix in v2 W6).
- **Plugin bar PASS (10-02, 09-26 data):** COMPLETE, lead-1 end to end 8,710, identity mismatch 0; one T+1 fair value
  recomputed by hand matched to four decimals.
- **111h closed (EF §10p):** US NBM guidance at all hours misses the line; the afternoon is harmed. Morning lead (§10h/§10j)
  stands; an hour-gated candidate needs a new pre-registration on new dates.
- **Settlement:** US markets settle on the WRH "Hourly Data" rows; foreign markets on the WRH Temp column; Hong Kong pays the
  floor of the HKO absolute daily maximum (#169 config, roll-free). Lowest temperature is the hourly-row minimum. EF §10c.
- **Pinned deployments (detached, locked worktrees):** watchdog `weather-watchdog-deployed-110n-1fc7ba35`; order journal
  `weather-manual-order-journal-deployed-ebe72984`; cold-snapshot nightly `weather-cold-snapshot-deployed-979c0e7` (to be
  re-pinned after #179 lands); exam tree `weather-exam-deployed-664c894` (closed; keep for v2 provenance).
- **Disk:** 91a nightly reclaims ~10-20 GiB a night; 10-03 failed on a race with the CLOB status file (resolved, 9.58 GB;
  cause = the admission check's read, fix #179). A FAILED night blocks later nights until resolved: check
  `scratch\cold_snapshot_compression\nightly-<date>-*\wrapper-result.json` each morning. Policy expires 10-30 (renewal ~10-27).
- **88a retention hold:** keep 88a data for UTC 09-27..10-15 (v2 calibration/panel/settlement) and 10-15..10-30 (desk-study
  panel); lossless compression allowed.
- **Learning lane:** Stage B (`WeatherEveningEvidenceRefresh`) disabled since 2026-08-13. Stage A exits 2 daily on the known
  `live_variant_settlement_scorecard` block.
- **Host:** ProtonVPN removed 10-03 (capture unaffected); TAP-Windows adapter kept (owner); crash dumps automatic.
- **Workstation:** owner-account deny removed from `data\` (10-03); the wallet reader blocks heavy-lease recovery until #170
  (allowlist) lands.

## Ordered critical path

1. **Maker replay v2:** Session A (W0+W1) running; then B (W2 exporter, S2 decides the export host) and C (W3-W5 engine,
   reference, scorer), then W6-W8; production P1-P4 on calibration dates only; gates; owner signature by 10-23.
2. **Merges:** tonight roll-free batch (#141 first, #170, #171, #155, #154, #150, #151, #128, #146, #169, #179, lowest-temp
   study, CI hook fetch-depth); 10-04/05 #152 + #173; 10-05/06 #117 -> #174, #119, #160-#163, #142, #180; after 10-14 #118,
   #172 + #182 (register `WeatherMakerEvidenceLowestTemperature`), #177 (restart 88a explicitly).
3. **Measurements (09-29 only; never 88a 09-30..10-14):** #173 execution-tape and #177 88a disconnect reports.
4. **Research:** NBS/NBH probe (after 111h); T+1/T+2 NWP-timing pilot; hour-gated guidance needs a new pre-registration.
5. **Live:** not before the v2 look and >= 7 days of shadow agreeing with replay; the shadow runner (Phase 3) awaits the owner.

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture. Worktrees: `GIT_LFS_SKIP_SMUDGE=1`;
  pytest: `--basetemp`, `TEMP`/`TMP` inside a cleaned root. Long agent jobs run detached, not as tool background calls.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay, release binding and
  evidence retention remain mandatory. Languages: stay Python; native code only by the efficiency-audit decision rule.
- Approved workstation work is never parked as low priority; production hands out the next item whenever a session frees.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
