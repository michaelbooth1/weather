# State of play

**Last updated: 2026-10-06 03:40 America/Toronto (ALL LIVE TRADING PAUSED; evening fix #191 LIVE `094f5b39`; roll-free batch #226 `a103ef8b`; #230 held (host-suite precondition failure); 91a 10-06 attempt resolved; ~106 GiB free).**
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
  01:00-04:00 only; roll-free 00:30-09:00 (the lease refuses later); docs-only by the light path before 12:00; never 12:00-00:30.
- **Merge freeze lifted 2026-10-03, except 88a:** changes to 88a capture code or behaviour (#118, #172, #177, stacked #182)
  wait until after 2026-10-14 so the unread panel is captured by one 88a code version.
- Owner decisions 2026-09-30..10-05 are rows in [DECISION_LOG](DECISION_LOG.md) (10-04: swarm, MG-1, P1-P5, v2 rule 1, CI
  deadline scale; 10-05: #191 floor rule, rule-1 readings, `_summary_status` fail-closed, #195 merge, Austin 10-03 out of v2 panel).
- **Testing (owner 2026-10-04, PR #205):** definition of done = focused + affected tests with PR CI as full-suite evidence,
  effective once the Windows CI lane (#209) lands; until then a local full suite for Windows-executing scripts. Workstation
  focused runs (<= 25 files, no `serial`) are lease-exempt; full suites queue (`workstation_heavy.ps1 -Queue`, #213).
- **Workstation: one Claude Code chat directed by the production agent** (cross-session messaging, owner 2026-10-03; bigger decisions to the owner first); prompts start from [the session preamble](WORKSTATION_SESSION_PREAMBLE.md).
  Claude Code has no host-load hook; the S4U guard is its backstop. Use a short `--basetemp` there (Windows MAX_PATH).

## Current truth

- **Production source:** `master` = `origin/master` `a103ef8b`. 10-06 night (sequencer, Fable-reviewed): #191 `094f5b39`
  (evening lock-in v3, roll-sensitive, suite 24/24); #226 `a103ef8b` (#199-#203, #209 Windows CI lane, #216, #218 CI deadline
  scale, #219, #222, #223 EOF check). #230 (#228 + #229 live-launcher stdin) FAILED the host suite on its tests' console-text
  precondition only (outcomes correct); held for a test fix. Any live seal must be RESEALED after #229 lands.
- **Model, evening (EF §10q):** #191 v3 is LIVE from 2026-10-06 01:43 (anchor = same-day observed station high,
  observation-time keyed; no mass below it; owner floor rule 10-05). Replay <= 09-29: floor check PASS, 17-23 mass above the
  anchor 0.332 -> 0.075, 0 v3 anchors settled below. First live evening: 10-06; check lockin-anchor-v3 in served payloads.
- **Model, morning:** MG-1 (captured NBM v2 guidance read) SIGNED 2026-10-04T16:10Z at `b044e0f1`; narrow reservation;
  needs parser v2 (#190) landed; scored on new dates >= 10-15.
- **Exam `maker-replay-2026-10-15`: closed NOT EXECUTED (owner 2026-10-03)**; panel UTC 09-30..10-14 never read.
  [Plan B audit](../roadmap/audits/exam-plan-b-2026-10-03.md).
- **Successor: maker replay v2** (design PR #176 `4bbce397`, approved 1-6): per-band event schedule (cost linear in bands),
  T+1/T+2 bands only, compact v0.2 bundles, the 32 GB workstation runs rehearsal and look, ceilings and an executability gate
  from calibration-only rehearsals **before** signature, a reachability gate. UTC 10-15 settlement-only; δ_ref = the signed
  hurdle. Build W0-W8 on `codex/maker-replay-v2-build-20261003` (exam tree's v0.1 stack as base); signature by 2026-10-23,
  look by 2026-11-15. The capture host may export only within the nightly wrapper (2 GiB, 2,700 s): v0.1 needs 5-10 GiB, so
  the v0.2 exporter measurement (S2/P1) decides whether exports stay on this host.
- **111h closed (EF §10p):** US NBM guidance at all hours misses the line; the afternoon is harmed. Morning lead (§10h/§10j)
  stands; an hour-gated candidate needs a new pre-registration on new dates.
- **Settlement:** US markets settle on the WRH "Hourly Data" rows; foreign markets on the WRH Temp column; Hong Kong pays the
  floor of the HKO absolute daily maximum (#169 config, roll-free). Lowest temperature is the hourly-row minimum. EF §10c.
- **Pinned deployments (detached, locked worktrees):** watchdog `weather-watchdog-deployed-110n-1fc7ba35`; order journal
  `weather-manual-order-journal-deployed-ebe72984`; cold-snapshot nightly `weather-cold-snapshot-deployed-979c0e7` (its
  runner accepts the new resolution record, so no re-pin was needed); exam tree `weather-exam-deployed-664c894` (closed; v2 provenance).
- **Disk:** 91a nightly reclaims ~5-20 GiB a night but failed 3 of 4 nights (10-03, 10-04, 10-06) on transient reads of a
  capture status file; each was resolved by `-VerifyRetained` (10-06: 756 files, 5.58 GB). #238 (owner-approved) moves it
  to 06:50-09:00 and makes those reads retry; it applies after landing and a production re-pin. Check
  `scratch\cold_snapshot_compression
ightly-<date>-*\wrapper-result.json` each morning. Policy expires 10-30.
- **88a retention hold:** keep 88a data for UTC 09-27..10-15 (v2 calibration/panel/settlement) and 10-15..10-30 (desk-study
  panel); lossless compression allowed.
- **Learning lane:** Stage B (`WeatherEveningEvidenceRefresh`) disabled since 2026-08-13. Stage A exits 2 daily on the known
  `live_variant_settlement_scorecard` block.
- **Host/workstation:** ProtonVPN removed 10-03 (TAP adapter kept, owner); workstation `data\` owner-deny removed 10-03.

## Ordered critical path

1. **Maker replay v2:** build branch `501f4757` holds W2 (#212), W3-W5 with rule 1 (#195) and rule 4 = B (#237: S3 5.45,
   S5 0 divergences); then W6-W8; production P1-P4 on calibration dates only; gates; owner signature by 10-23. Austin
   2026-10-03 is excluded from the panel (owner).
2. **Merges (Swarm L calendar, owner-approved 10-05):** N1 10-07: preflight #232 + #189, then #207 (quiet window); RF
   batches #238 (91a move) + #153 + #120 + #204, and #105 + #125 + #121; #230 once its test fix lands. Then #190 -> #210;
   #196; #161 -> #162 -> #160; #152 + #173; #163; #142. After 10-14: #118, #172 + #182, #177. M4 merge-tool change on 10-11/12.
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
