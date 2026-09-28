# State of play

**Last updated: 2026-09-26 12:00 America/Toronto (ALL LIVE TRADING PAUSED to build the informed maker; storage decisions 1-9 approved; one-wallet portfolio ledger ordered).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23, refined 2026-09-25)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows. **B. An
informed, domain-neutral market maker:** model fair value flows into a maker core that widens, pulls and re-centres on
information (weather first, YouTube views next). Going in blind is ruled out. Plan: [informed maker design](informed-maker-design-2026-09-25.md);
history: [forward plan](forward-plan-2026-09-23.md), [item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md).

## Current authority

- **No live trading (owner 2026-09-25): all live trading is paused, including RE-1, which suspends the 09-19 RE-1 exception.**
  The owner starts any future live run personally; before any RE-1 resumption the pause and bleed limit go into code (deferred).
- Owner 2026-09-19: implementation authority toward live testing; heavy work only 00:30-09:00 under the shared lease
  ([host load policy](HOST_LOAD_POLICY.md)); eligibility resolved, tunnel down during live sessions.
- Owner 2026-09-23: **no second disk**; off-PC Drive archive as needed. 2026-09-26: storage decisions **1-9 approved, 10 keep,
  11 no** ([assessment](../roadmap/audits/storage-value-assessment-2026-09-26.md) §4): replay_cache deleted under an owner waiver;
  exact-path delete manifests; 91a; Drive campaigns; order_books_long twin deletion; registry fixes; compress-on-close.
- Owner 2026-09-26: exchange-economics baseline re-accepted (06-27 → 09-26 snapshot); one wallet carries several campaigns
  (weather maker, future YouTube maker, owner manual trades), so a one-wallet portfolio ledger attributes every lot (110i).
- Owner 2026-09-25 ([DECISION_LOG](DECISION_LOG.md)): informed maker design approved (`src/maker_core/`, v0 centre = market mid,
  grade-'none' fair value quotes both legs symmetrically, Windows Credential Manager for maker credentials); afternoon centering
  stage to be switched off (110g); wallet reader reports INCOMPLETE P&L while a settled lot is unredeemed (110f); records from
  actual wallet reads only; the owner deletes the plaintext Desktop credentials file on production.
- Owner 2026-09-21: model work unpaused; pre-register before scoring. 89a Clarification 12 (panel B 09-25..10-08) approved.

## Current truth

- **Production source:** `master` = `origin/master` at the 2026-09-26 night landings: 88a floor 40 GiB `45c2ff62f` (worker
  restarted, pid 17840, source hash verified, CAPTURING), `.gitignore` `e5b0f24e0` (`config/local/`, `.claude/settings.local.json`),
  paper-maker-paused flag `2703b65b3` (Stage A passes it; first run 09:30 09-26), **maker core Phase 0 `724f95cd4`, tag
  `maker-core-contracts-v0.1`**, **95b signed band parser `802b967f4`** (fixes negative Celsius labels; bounded suite 22/22 on its third run), schema-audit
  regression fix `dba5a0b99` (Phase 0's quoted profile name `informed_v0` read as a schema version; now `informed-v0`). Get `roll_verdict.ps1` and a `git merge-tree` check before any merge; every docs
  landing regenerates `docs/roadmap/correspondence-index.md`, so resync open branches first.
- **Disk (binding):** 52.6 GiB at 00:32 09-26 → **83.5 GiB at 01:01** after removing 90 merged worktrees (+5.9) and NTFS-compressing
  retired `mm_runs`/`taker_runs` (51.4 GiB logical, 51.4 → 26.2 on disk, 148 folders, 0 errors; receipt
  `data/alerts/disk-reclaim-20260926/`). Underlying loss ~5-8 GiB/day; 88a stops < 40 GiB, the bounded suite < 50 GiB.
  Next levers ([storage assessment](../roadmap/audits/storage-value-assessment-2026-09-26.md)): replay_cache (32 GiB, owner),
  delete manifests (~21-26), 91a registration (largest), Drive campaigns, source-side compress-on-close.
- **Host:** commit ~40%; W32Time Automatic; settlement repair per date via `settlement_backfill_one.ps1 -TargetDate <d> -Refetch`.
- **Settlement source:** the venue resolves on the weather.gov WRH "Hourly Data" page since ~2026-08-23; master hard-codes WU;
  band agreement 359/360; negative Celsius band labels parse correctly since 95b (`802b967f4`). EF §10c.
- **Armed work:** supervisors, 05:00 projection, 06:00 tiering, refreshes, 09:30 Stage-A, `WeatherMakerEvidenceCapture` (88a, every
  minute, public data only). Paper maker and taker retired (tasks Disabled). Training DISABLED; mirror PAUSED.
- **Wallet (recorded reads only, `data/wallet_ledger/`):** baseline 09-25 17:38Z cash 102.97; 09-26 12:40Z cash 2.17. Chicago
  68-69°F Sep 25 YES (75 @0.43) moved from live to resolved, not redeemable, cash unchanged — a loss of its cost. The only live
  lot is the owner's MrBeast 70-80M week-1 position (140 YES @0.72, same wallet); the reader's `BLEED_LIMIT` is an artefact of
  its single campaign baseline until the portfolio ledger (110i) attributes lots per campaign.
- **RE-1 (paused):** 11 of 30 sessions used; first paid day 09-24 +2.13 (k ≈ 1.05); fills and settlements in EF §10m; Miami sold
  75 @0.18 (lot −13.30); `reconcile 12` owed; the code expires 09-30. Tested tip `d90d0a6e6`; `2b9a0ca9e` untested.
- **Maker economics:** takers pay `0.05 x p(1-p)` per share, makers 0, 25% of taker fees fund rebates (EF §10o); reward terms can
  change intraday (Chicago 100 → 20, EF §10m) — read CLOB `/rewards/markets` at decision time.
- **Forecast:** NBM parser layer 1 landed; layers 2 (`abd648c7c`) and 3 (`cee879c45`) queued for quiet windows. The afternoon
  centering stage is still live until 110g lands. The September PIT research is recorded (EF §1m: tested, inconclusive, no free
  v2 source). No T+1/T+2 model yet; the weather plugin's zero-parameter fair value fills that for the maker.
- **Wallet reader:** authenticated read-only LAN API served from the workstation (`codex/wallet-public-reader-20260925`); lands
  on master later.

## Ordered critical path

1. **Informed maker:** Phase 0 landed and tagged. Phase 1 weather plugin (`codex/weather-maker-plugin-20260925`, `c734e5c2b`):
   real-data dry run deferred (no bounded entry point; handoff 110h adds one), then land. Phase 2 replay harness on 88a data; Phase 3 shadow on the workstation; Phase 4 owner-started live.
   Share `maker-core-contracts-v0.1` with the YouTube team.
2. **Disk:** production runs decisions 1, 2, 3, 8 under exact manifests and lands 91a (rebase, bounded suite, dry run, register);
   workstation builds decisions 5, 6, 7, 9 (handoff 110j).
3. **Model:** 110g afternoon stage off (next quiet window); NBM layer 2 then 3; T+1 fair-value pre-registration scored after 10-08
   with 89a panel B.
4. **Wallet reader and portfolio ledger:** 110f done (`7c3184e81`; owner restarts the reader); land with the bounded suite in a
   quiet window. 110i builds the one-wallet portfolio ledger on top. 110g (`ba42a13c8`) lands with a controlled restart.
5. **Canon and ops:** documentation-transaction closeout each night after merges; small PR triage (#29, #30, #54, #55, #65, #68);
   RE-1 PR chain closes after 09-30; master force-push protection (owner).

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic, not an objective.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture. Worktrees: `GIT_LFS_SKIP_SMUDGE=1`;
  pytest: `--basetemp`, then delete it.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay, release binding and
  evidence retention remain mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, a live session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
