# State of play

**Last updated: 2026-10-01 11:30 America/Toronto (ALL LIVE TRADING PAUSED; Clarification 2 SIGNED; exam line #134 still HELD: plugin mass incomplete; 91a nightly registered; ~107 GiB free).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25/27)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows. **B. An
informed, domain-neutral market maker** (weather first, YouTube views next) that widens, pulls and — only where evidence
supports it — takes a side. Going in blind is ruled out. Plan: [informed maker design](informed-maker-design-2026-09-25.md).

## Current authority

- **No live trading (owner 2026-09-25).** The owner starts any future live run personally; pause and bleed limit go into code
  first. The owner's manual trades share the wallet and stay `owner-discretionary`, outside automated data.
- Heavy work only 00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)). Merges: roll-sensitive
  01:00-04:00 only; roll-free 00:30-12:00; docs-only by the light path before 12:00; never 12:00-00:30.
- **Exam-period merge policy (2026-09-27):** during panel UTC days 09-30..10-13 only disk-relief and exam-tooling
  roll-sensitive merges land; everything else waits until after 10-13. Nothing joins an integration branch before its CI is green.
- 2026-09-30 owner decisions (swarm items: estimand for future pre-registrations, fsync fix after 10-13, Desktop ACE removal,
  cleanup, learning-lane diagnosis, research order, YouTube plugin after 10-15, candidate 2 via a pinned worktree by 10-12;
  token-batch rule; wallet reader at logon; 91a two-day rule; no phone alerts, no UPS) are rows in [DECISION_LOG](DECISION_LOG.md).
- **Workstation sessions are Claude Code** (Codex lapsed 2026-09-29); dispatch prompts start from
  [the session preamble](WORKSTATION_SESSION_PREAMBLE.md). Claude Code has no host-load hook; the S4U guard is its backstop.

## Current truth

- **Production source:** `master` = `origin/master` `979c0e752` (2026-10-01 01:38, roll-free, suite 23/23): integration #147
  (#130, #131, #132 carrying #110, #135, #136, #138, #139, #140) plus #148 (111i cold-snapshot tiny-file skip, two-day rule).
- **Exam line #134 still HELD.** The 111j plugin re-run (09-26 data, plugin `ad041d6d`, COMPLETE) now binds bands end to end
  (lead 1: 2,512; lead 2: 2,539; band-identity mismatch 0), but all 9,268 records have only partial probability mass:
  `book_not_captured` 24,615 (88a books selected bands only), `nonincreasing_percentile_knots` 7,325,
  `missing_point_in_time_forecast` 1,584; 0 legs (`data/alerts/weather-plugin-111j-20260926/`). Landing needs a workstation
  fix for the knots; owner 10-01: mass must be complete over the captured band set. #134 and #128 conflict on the index.
- **Pinned deployments (detached, locked worktrees):** watchdog `weather-watchdog-deployed-110n-1fc7ba35`; order journal
  `weather-manual-order-journal-deployed-ebe72984` (User-Agent fix #127; runner `3d12c5c7`, modules `f935f59f`); cold-snapshot
  nightly `weather-cold-snapshot-deployed-979c0e7` (task `WeatherColdSnapshotNightly`, 00:30, 32 GiB policy `a049bf01`
  valid to 10-30). The journal's 403s were a missing User-Agent, not a geoblock.
- **Host incidents:** two unclean power losses: 2026-09-29 ~19:50-20:05 (~20 min of 88a lost) and 2026-09-30 14:05:39
  (Kernel-Power 41, no bugcheck; ~13 min of capture in the graded window, ~18 min of 88a on 09-30 in total). Coverage
  exclusions, not zeros. Owner set Windows Update active hours 09:00-03:00 and capped shadow storage at 2 GB (both verified).
- **Disk (91a):** the failed 09-30 attempt is RESOLVED (8 files verified). 10-01 dry run PASS (4,634 closed-day files fill the
  32 GiB budget; tiny files skipped with reasons); 1 GiB apply PASS: 1,147 files, 680 MiB reclaimed (~3.0:1). First real
  nightly 10-02 00:30. **Lease collision:** on any night with a 00:30 integration suite, disable the nightly before 00:30 and
  re-enable after; stagger the future exam export before registering it. Other levers: #142 (111g), 5g after #128.
- **Learning lane (diagnosed 10-01, read-only):** daily refresh is split. Stage A (09:30) runs through `fleet_observability`;
  its five in-chain learning steps run but are GAPPED because the settled-day barrier is DIAGNOSTIC_ONLY. Stage B
  (`WeatherEveningEvidenceRefresh`: promotion refresh, shadow, scorecards, `daily_learning`, scoreboard) has been
  **disabled since 2026-08-13**, so those steps never run. Re-enabling needs a trigger that avoids the 00:30 nightly lease.
- **Wallet:** the reader runs on the workstation at owner logon from worktree `weather-wallet-reader-8a669d68` (#150, not
  yet landed; #149/#150 conflict with master). Journal clean at 09-30 21:44Z: 9 fills recovered, 0 open orders.
- **Settlement source:** venue resolves on weather.gov WRH hourly data; master hard-codes WU; agreement 359/360 (EF §10c).
- **Replay exam (signed v1):** calibration 09-27..29, panel 09-30..10-13, settlement 10-14, single look **2026-10-15**. As
  frozen it cannot execute (2026-09-29 deep audit). **Clarification 2 SIGNED 2026-10-01** (bytes at `a8c0b846b`, SHA-256
  `1719fd1e…`; late look to 10-31 while unreserved, ×15 power-of-two ceilings, k = 0.3 label); the v2 authorization row
  follows once 111e (#144) teaches the verifier a second clarification. Candidate 2 (#137) runs from a pinned worktree.
- **One-sided thesis review (2026-09-27):** one-sidedness concentrates informed flow; the model trails the market in every
  measured slice; observation decidedness is the only directional signal; one-sided reward score is S/3 inside a 0.10-0.90 mid.
- **Swarm audit 2026-09-30:** 23 agents, verified synthesis and corrections in
  [audits/swarm-audit-2026-09-30.md](../roadmap/audits/swarm-audit-2026-09-30.md).

## Ordered critical path

1. **Exam line:** workstation fixes plugin knots and captured-set mass verdict -> production re-run -> land #134 + #144 (+#142,
   #143) after index resync in one quiet window; v2 authorization rows; calibration export and ceiling rehearsal.
2. **Disk:** watch the first 91a nightly receipt (10-02); land #142 (111g); 5g after #128.
3. **10-15:** universe inventory, manifest build/verify/enrol, single look (late look to 10-31 while unreserved).
4. **Learning lane:** give Stage B a non-colliding trigger, then re-enable it.
5. **Research:** fill-toxicity desk study (top); 111h extract; hourly NBS/NBH probe after 111h; one reward scan incl. YouTube.

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture. Worktrees: `GIT_LFS_SKIP_SMUDGE=1`;
  pytest: `--basetemp`, `TEMP`/`TMP` inside a cleaned root. Long agent jobs run detached, not as tool background calls.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay, release binding and
  evidence retention remain mandatory. Languages: stay Python; native code only by the efficiency-audit decision rule.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
