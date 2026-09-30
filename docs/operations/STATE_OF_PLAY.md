# State of play

**Last updated: 2026-09-30 01:30 America/Toronto (ALL LIVE TRADING PAUSED; exam integration #134 HELD: plugin re-run evaluated no bands; disk is the exam's main risk; ~97 GiB free).**
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
- **Exam-period merge policy (2026-09-27):** during panel UTC days 09-30..10-13 only disk-relief and exam-tooling
  roll-sensitive merges land; everything else waits until after 10-13. Nothing joins an integration branch before its CI is green.
  (A same-day "source freeze" claim was wrong: source hashes bind only from manifest build to the scored run, both ~10-15.)
- 2026-09-26/27 decisions and the 2026-09-29 decisions (watchdog adoption, 5f approval, 5g after #128, part 3 keeps the
  Stage 0/1 paper-run tool, GitHub hardening, Clarification 2 drafting with k = 0.3, 111f/111g/111h, order-journal
  deployment) are rows in [DECISION_LOG](DECISION_LOG.md).
- **Workstation sessions are Claude Code** (Codex lapsed 2026-09-29); dispatch prompts start from
  [the session preamble](WORKSTATION_SESSION_PREAMBLE.md).

## Current truth

- **Production source:** `master` = `origin/master` `b0032a907` (docs); code tip `85092752a` (2026-09-29 01:23): 110k, 110m
  part 1, 110n, fresh 110q, 110v part 1. Integration #134 (exam line + #128, tip `0ec3f157f`, CI green) was NOT merged
  2026-09-30: the 111a production re-run (09-26 data, COMPLETE in 130 s) evaluated no band end to end: 0 legs on 7,371
  decisions, `fair_value:served_snapshot_release_unbound` on 7,367, `missing_captured_band_metadata` 65,912
  (`data/alerts/weather-plugin-111a-20260926/`). The plugin sits inside #100, so the exam line waits for a fix.
- **Watchdog adopted 2026-09-29 13:35** from `weather-watchdog-deployed-110n-1fc7ba35` (pins verified). Order journal (110x)
  runs every 5 min from a pinned worktree `weather-manual-order-journal-deployed-4ccc92de` (option B; option A after 10-13).
- **Host incident 2026-09-29 ~19:50-20:05:** short power outage (owner-confirmed; Kernel-Power 41, 6008), no dump; boot recovery 0x0; 88a now
  pid 3860; ~20 min of 88a lost (last minutes of calibration day 09-29, first 9 min of panel day 09-30: coverage
  exclusions, not zeros). Stage-A 09-29 economics gate PASSED (110q works); exit 2 now from a promotion-lane block.
- **Disk:** ~97 GiB free after 09-30 deletes (taker detail 3.18 GiB logical/1.8 on disk, 5f 3.53 GiB; receipts
  `data/alerts/storage-decisions-20260929/`). Measured net decline ~11-12 GiB/day (not the watchdog's 7); the reboot's
  +10 GiB was pagefile reset (16 GiB, may regrow to 32). Pessimistic: 50 GiB suite floor ~10-04, 88a 40 GiB stop ~10-05,
  inside the panel. **91a nightly (09-30):** dry run PASS filled the 32 GiB budget (4,851 closed-day files); the 1 GiB
  first apply compressed 7 files at 3-4:1 then stopped on a 385-byte MFT-resident file (zero savings stops the batch):
  fix 111i (owner 09-30: select closed market-days after 2 days, not 14), then register. Other levers: 5g after #128, 111g #142 (~0.9 GiB/day), owner-signed manifests.
- **Settlement source:** venue resolves on weather.gov WRH hourly data; master hard-codes WU; agreement 359/360 (EF §10c).
- **Wallet (recorded reads, `data/wallet_ledger/`):** 09-28 01:40Z cash 283.95, no positions, no open orders; the owner's manual
  one-sided resting orders earned 8.25 pUSD of rewards on 09-27 UTC (orders now gone). Reader status INCOMPLETE is expected.
  The reader now starts at the owner's workstation logon (task `WeatherWalletReader`, [runbook](wallet-reader.md)).
- **Maker core / exam tooling:** harness, prereg, execution pack, T+1 scorer, bundle export, storage classes are in #134;
  111e (#144) makes the exam executable per the unsigned Clarification 2 draft
  (`docs/research/maker-replay-clarification-2-2026-09-29.md` on branch `codex/exam-fixes-handoffs-20260929`); 111f measured competitor reaction (share halves in 2-4 min; ~1 h sessions k 0.27-0.32).
- **Replay exam (signed v1):** calibration 09-27..29, panel 09-30..10-13, settlement 10-14, single look **2026-10-15**. As
  frozen it cannot execute (2026-09-29 deep audit): bundle field refused, no calibration producer, unmeasured ceilings, a
  refusal inside scoring spends the look; enrolment is only possible on 10-15. Clarification 2 (owner signs) fixes the
  mechanics only. Second candidate (#137) exam 10-16..10-29, look 10-31.
- **One-sided thesis review (2026-09-27):** one-sidedness concentrates informed flow; the model trails the market in every
  measured slice; observation decidedness is the only directional signal; one-sided reward score is S/3 inside a 0.10-0.90 mid.
- **Forecast:** 111h (#146) re-derives NBM guidance with parser v2 at all hours from retained bulletins (extract on production,
  analysis on the workstation); NBM layers 2/3 after 10-13.
- **YouTube:** its model may feed the maker later (read-only); capture moves here after 10-15 with a measured 7-day disk cost.

## Ordered critical path

1. **Disk (exam at risk):** 91a dry run -> low-budget apply -> register by 10-02; land #142 (111g) and 5g after #128.
2. **Exam line:** fix the plugin's release binding and band metadata (workstation), re-run on production, then land #134 +
   #144 (+#142, #143) in one quiet window; owner signs Clarification 2; calibration export and ceiling rehearsal.
3. **10-15:** universe inventory, manifest build/verify/enrol, single look (late look to 10-31 only on an operational refusal).
4. **Roll-free batch 09-30 06:30:** #132 (carries #110), #130, #131, #135, #136, #138, #139, #140; #141 alone on 10-01.
5. **Research:** 111h extract (night 09-30/10-01); everything roll-sensitive and non-exam after 10-13.

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture. Worktrees: `GIT_LFS_SKIP_SMUDGE=1`;
  pytest: `--basetemp`, `TEMP`/`TMP` inside a cleaned root.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay, release binding and
  evidence retention remain mandatory. Languages: stay Python; native code only by the efficiency-audit decision rule.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
