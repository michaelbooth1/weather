# State of play

**Last updated: 2026-09-28 02:00 America/Toronto (ALL LIVE TRADING PAUSED; replay exam signed: panel 09-30..10-13, look 10-15; integration landed; 102 GiB free).**
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
- Heavy work only 00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)); roll-sensitive merges 01:00-04:00.
- **Exam-period merge policy (2026-09-27):** during panel UTC days 09-30..10-13 only disk-relief (110j C) and exam-tooling
  roll-sensitive merges land; everything else waits until after 10-13. Nothing joins an integration branch before its CI is green.
- All 2026-09-26/27 owner decisions are rows in [DECISION_LOG](DECISION_LOG.md): storage 1-9 (10 keep, 11 no), economics baseline
  re-accepted, one-wallet ledger, 10 repo-health decisions, replay pre-registration + Clarification 1 signed, efficiency
  approvals, YouTube plugin, one-sided second candidate, wallet reader stays on the workstation, tools 110y/110z.

## Current truth

- **Production source:** `master` = `origin/master` `fbf4d436c` (2026-09-28 01:22, quiet-window tool, bounded suite 23/23, GitHub CI
  green on PR #122): 91a nightly compression (not registered), wallet reader + 110f, **110g afternoon centering OFF** (verified
  `artifact_disabled` in the 05:22Z Toronto snapshot), 110i portfolio ledger, 110j A registry + B twin deletion, size-audit fix,
  owner signatures. Capture workers and execution tape recovered; 88a did not restart (pid 17840, CAPTURING).
- **110q** (economics tick-mix false positive) was reverted out of that landing after its CI failed the live-wrapper sealer; it
  returns 09-28/29 as fresh commits. Until then Stage-A exits 2 daily on the tick-mix drift (settlement still runs).
- **Disk:** 102 GiB free after 2026-09-28 reclaims: replay_cache 32.3 GiB, 8 failed staging tarballs 2.0, rotated console logs
  2.6, incident logs gzip-retained 1.4 (receipts `data/alerts/storage-decisions-20260928/`). Net loss ~7.6 GiB/day; 88a stops
  < 40 GiB, the suite < 50 GiB. Deferred: taker counterfactual files (unnamed; tape recorded as canonical), 5f/5g.
- **Host:** housekeeping 2026-09-28: 18 spent/retired tasks unregistered, WeatherBootRecovery runs from the production tree
  (hash-pinned), 88a trigger PT5M (registrar still asserts PT1M: follow-up), explorer restarted (2.7 GB -> 0.2 GB), Defender
  excludes venv, C:\tmp, C:\pt. Execution-tape worker writes ~3.7 MB/s of status (fix 110v part 1).
- **Settlement source:** venue resolves on weather.gov WRH hourly data; master hard-codes WU; agreement 359/360 (EF §10c).
- **Wallet (recorded reads, `data/wallet_ledger/`):** 09-28 01:40Z cash 283.95, no positions, no open orders; the owner's manual
  one-sided resting orders earned 8.25 pUSD of rewards on 09-27 UTC (orders now gone). Reader status INCOMPLETE is expected.
- **Maker core:** contracts v0.1; weather plugin, 110h dry-run CLI, replay harness (313/313 minute parity with RE-1), execution
  pack (110r), bundle export (110s), shadow runner (110t), T+1 scorer (110u) are on branches; they land 09-28/29.
- **Replay exam (signed):** calibration 09-27..09-29, panel 09-30..10-13, settlement 10-14, single look **2026-10-15**
  (`maker-replay-2026-10-15-v1`; 10-12 authorization revoked). Production calibrates, builds and verifies the manifest and
  enrols its hash on 09-30. A second candidate (`one-sided-edge-v0`, 110w) gets its own exam 10-16..10-29, look 10-31.
- **One-sided thesis review (2026-09-27):** one-sidedness concentrates informed flow; the model trails the market in every
  measured slice; observation decidedness is the only directional signal; one-sided reward score is S/3 inside a 0.10-0.90 mid.
- **Forecast:** NBM layers 2/3 queued (after 10-13); T+1/T+2 fair value frozen pre-registration, scored 10-15 by 110u.
- **YouTube:** its model may feed the maker later (read-only); capture moves here after 10-15 with measured disk (~10-05).

## Ordered critical path

1. **09-28 06:30:** 110h plugin dry run on 09-26 88a data. **09-28/29 window:** plugin + harness + #109 (frozen, unchanged) +
   #112/#113/#114 + 110k + #101 + #102 + fresh 110q + 110v part 1; then register the nightly bundle export and backfill
   09-27..09-29.
2. **09-30:** hazard calibration, panel inventory seal, manifest verify, hash enrolment. Keep 88a >= 40 GiB every day to 10-13.
3. **Disk:** register 91a after a dry run; 110j C during the exam (disk relief); decide the taker files and 5f/5g.
4. **Workstation queue:** 110o (after landings), 110v parts 2-6, 110w, 110x, 110y, 110z.
5. **Canon and ops:** tracker (#110) lands roll-free; nightly docs step; RE-1 PR chain closes 10-01.

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture. Worktrees: `GIT_LFS_SKIP_SMUDGE=1`;
  pytest: `--basetemp`, `TEMP`/`TMP` inside a cleaned root.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay, release binding and
  evidence retention remain mandatory. Languages: stay Python; native code only by the efficiency-audit decision rule.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
