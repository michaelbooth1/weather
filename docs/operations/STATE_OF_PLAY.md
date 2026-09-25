# State of play

**Last updated: 2026-09-25 10:45 America/Toronto (night landings: docs, merge-tool fix, 88a + capture registered, 93a, 95c, 94b; 89a INCONCLUSIVE; RE-1 11 of 30).**
Read this first. Then [the findings digest](FINDINGS_DIGEST.md) before any research or economics work.

> **REWRITTEN, never appended. At most 95 lines and about 9 KB, one fact per bullet, detail in the linked owner.** This file owns
> current decisions and current truth. `status.ps1` flags it when its declared date is more than 3 days old. Live readings
> (free space, commit, capture health) come from `status.ps1` and `Get-Volume -DriveLetter C`, not from this file.

## Objectives (owner, 2026-09-23)

Precondition: protect capture and settlement evidence. **A. Forecast:** as good as our own free information allows (NBM
repair first). **B. Maker/rewards:** liquidity rewards with quotes **pulled around information arrival** (new airport
observations, NBM/forecast updates) to avoid informed fills; B does not need a forecast that beats the market. No edge and no
paid reward is proved. Plan, kill rules and owner decisions: [forward plan](forward-plan-2026-09-23.md); [item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md) owns B's history.

## Current authority

- Owner 2026-09-19: implementation authority toward live testing. **No live trading except RE-1.** Heavy work only
  00:30-09:00 under the shared lease ([host load policy](HOST_LOAD_POLICY.md)).
- Owner 2026-09-21: **RE-1** approved as an **attended workstation script the owner starts personally**, at most **thirty
  sessions and sixty attempts** (owner raised 3->10 on 09-23 and +20 on 09-24; attempts are an agent default), none after 2026-09-30, worst case one session's reserve (at most 75 pUSD); campaign bound = the testing wallet (at most 200, no top-ups); outside the sealed lane and changes nothing in it (mission 84a).
- Owner 2026-09-22: RE-1 capital is a learning budget (losses reported, a fill is data); `H` = 1.00 net/day per 100 deployed.
- Owner 2026-09-23: [RE-1 addendum](../research/liquidity-reward-epoch-addendum-2026-09-23.md) (`BELOW_PAYOUT_MINIMUM` on `k_accrued`,
  either asset, graded adequacy); closes only on adequate `NOT_PAID` or `k_accrued` < 0.1 twice; 10-31 is an owner review.
- Owner 2026-09-23: **no second disk**; off-PC Drive archive as needed ([storage plan](storage-plan-2026-09-23.md)).
- Owner 2026-09-23 ([forward plan](forward-plan-2026-09-23.md)): `R` frozen as a rule; passive maker-evidence capture approved;
  payment tests may use any band and size within the testing wallet (now at most 200; new pre-registration and tip each time).
  Owner 2026-09-21: model work unpaused; pre-register before scoring. Owner 2026-09-19: eligibility resolved; tunnel down live.
- **Open owner decisions:** the four 80b control-relaxation defaults; whether a Stage 2 grant may precede the Stage 0/1 re-runs.

## Current truth

- **Production source:** `master` = `origin/master` (docs-only commits after `fcb27f0a8`; no marker left). Landed that night: docs
  `ccd143a6b` (light path, receipt), merge-tool byte restore `e0c5d2d4e`, **88a** `c79b6da0d` (tip `e99de4fe4`: +hook allowlist
  line, +`pytest.ini` `tmp_path_retention_policy = failed`: clone-heavy tests held ~7 GiB per chunk and tripped the 50 GiB floor
  twice), 93a `491a05837`, 95c `a555f3229`, 94b `d77c7c16c`, status UTC fix `fcb27f0a8`. Get `roll_verdict.ps1` before any merge.
- **Disk (binding):** 09-25 lows 50.5 (01:35, suite temp, fixed) and 44.3 (11:20 transient); 88a stops itself < 50 GiB (stopped 11:16-11:21); 13:20 reclaim of 09-03 transfer bundles -> 57.7. Owner 09-24 ~12:45: System Restore capped at 2 GB (+10.7 GiB),
  Windows Search disabled and its index removed (+1.7), Defender excludes `data\`: **58.0 GiB free at 12:50** (Red). Judge from the trail's 24 h minimum. Step 1 inventory done ([storage plan](storage-plan-2026-09-23.md)):
  ~453 GiB of snapshot-folder text is **uncompressed** and compresses 5-20x; mission 91a automates closed-day compression.
  The suite floor is 50 GiB. W32Time Automatic and syncing since 09-25 10:51.
- **Host:** commit limit 32.5 GB (42% used 09-24); settlement repair per date via `settlement_backfill_one.ps1 -TargetDate <d> -Refetch`, never `chain_recovery_run.ps1`.
- **Settlement source:** the venue resolves on the weather.gov WRH "Hourly Data" page since ~2026-08-23 (same stations);
  band agreement 921/921 before and 359/360 after; exact degrees undecided (86a). Master hard-codes WU; no gate detects a switch. EF §10c.
- **Capture:** health in `status.ps1`; it does not prove settled dates; T+1/T+2 reward bands have no canonical tape (D8-01).
- **Armed work:** supervisors, 05:00 projection, 06:00 tiering, refreshes, 09:30 Stage-A. **`WeatherMakerEvidenceCapture` registered
  2026-09-25 02:34** (88a, public data only, every minute, `data\maker_evidence\status.json` CAPTURING, 0 failed cycles; watch its disk).
  **Paper maker roll PAUSED 09-24** (owner: retiring the old maker; both tasks disabled).
  Training DISABLED; mirror and taker PAUSED. **No RE-0 reward capture since 2026-09-22 20:42Z** (the hourly logger was a session process, not a task). The deployed watchdog is newer than master: never re-register it from master.
- **RE-1 verdict (provisional):** session 1 (09-23, unpaid; EF §10m) frozen `INCONCLUSIVE`, addendum `BELOW_PAYOUT_MINIMUM`; formal from 09-26.
- **RE-1 sessions 2-8** (2026-09-24; journal folders are numbered by attempt: attempts 1-9 = sessions 1,2,-,3,4,5,6,7,8):
  s2 `fresh_ask`; s3 ~1 min `cancel_not_terminal` (read lag); s4 Miami 90-91 Sep 25, 88 min, **full fill 75 YES @0.35**;
  s5 56 min `heartbeat_stale`; s6 0 min decode `exception`; s7 ~2 min, fill 18.41 NO @0.59; s8 13 min (`P_many` 0.87), fill
  10 NO @0.40. **UTC 09-24 PAID +2.13 (k ≈ 1.05 vs ~2.03 modelled).** Held lots: 3 settled +6.43 net; 09-25 Miami YES sold 75 @0.18 (+12.95 net, lot -13.30); Chicago 68-69 YES held to settlement (owner). **Accounting = recorded wallet reads only** (`data/wallet_ledger/`, baseline 17:38Z cash 102.968694). s9 (depth rule): 38 min, no fill, stopped by owner test orders; s10 lost to post read lag (fixed `10fa052a0`); s11 (`d90d0a6e6`, Chicago 68-69°F Sep 25, start share 0.56): 72 min, `P_many` 0.38, then a five-trade sweep filled **75 YES @0.43**; reconcile 12 owed; **11 of 30 used**. Inventory policy and bleed limit
  (cash < 60 or campaign P&L < -40: no new sessions): [positions review](../roadmap/audits/positions-review-2026-09-25.md). Fills came on the least-contested bands; on an empty band share is 100% at any size
  or distance, so 75 shares at 1.5 c bought fill exposure for no extra reward (second-opinion audit, owner decision pending).
  92a analysis done (`7f98359`). Current tip `d90d0a6e6` carries the owner-approved selection amendment (local T+1/T+2,
  >= max(75, size) displayed depth each side within max spread), audit and read-lag fixes, 2 s heartbeat, `go <6 hex>`. Earlier code: `c771cbb42` (84g), `1310ca6bf` (84h, 7,360 passed). Not on master. Built, not
  landed: 89a+89c `d3dff0f2b`, 89b `d059cc787`, 90a report `2cb8a0a0e`, 95b signed band parser (roll-sensitive).
- **Maker economics:** weather takers pay `0.05 x p(1-p)` per share, makers 0; 25% of taker fees fund maker rebates (EF §10o). Configured
  pool ~2,800/day same-day, ~4,800 all active (EF §10a). Venue docs: pUSD since 2026-04-28, 1-dollar minimum per UTC day,
  no rollover, per-minute sampling, `Q_min` share. The 86b capacity sampler is PAUSED (mutex, duplicate pagination).
- **Maker candidate:** `codex/stage2-hold-build-20260921` @ `88aa7e43a` (contains the maker reconcile): inert, roll-sensitive,
  not host-qualified; adoption needs the owner's disposition of four control relaxations. It lacks the RE-1 fixes.
- **Forecast:** after 13Z the NBM parser read tomorrow's minimum (EF §10k); the versioned repair and bulletin reuse are built
  (EF §10l). Layer 1 landed (`29e161e7d`); layer 2 `codex/integrate-2-parser-20260921` @ `abd648c7c` (roll-sensitive) is
  **blocked on disk**; layer 3 `codex/integrate-3-reuse-20260921` @ `cee879c45` follows. No candidate is scored before
  post-fix dates exist; nothing new is served or trained.

## Ordered critical path

1. **RE-1:** session 11 end and its share path; `collect-evidence` for attempts 5-11 from 20:00 ET 09-25 (UTC 09-26) on `d90d0a6e6`; next
   sessions per the [live testing plan](live-testing-plan-2026-09-25.md) (accept share 0.15-0.70, start :59-:05, aim >= 180 min).
2. **Disk:** mission 91a (closed-day NTFS compress-and-retain at scale, then compress-on-close at source) until the daily low
   holds at 70 GiB or more (91a is not registered until its nightly run is bounded, so it cannot hold the lease for hours). Tonight: pause-flag tests + land, doc closeout, then 95b if >= 52 GiB;
   wallet reader stays on its branch (served from the workstation) until a later window.
3. **NBM layer 2, then 3:** one per 01:00-04:00 quiet window, host-qualified by the bounded suite, once disk allows.
4. **Pillar B evidence** ([forward plan](forward-plan-2026-09-23.md) 4-6): **88a capture is live** (09-25). **89a `INCONCLUSIVE`/`UNDERPOWERED`: 0 of 480 events admitted, all `no_panel_bands_with_captured_reward_terms`** (tip `2ac227d08`). 88a->89a adapter + Clarification 11 built (100b, `d2dcd3035`, roll-free, not needed on master); **owner approved Clarification 12: panel B 09-25..10-08, scored once after 10-08** selector built and verified (100c, `2b37cae88`).
5. **Stage 2 hold build:** host qualification in a quiet window; owner disposes of the 80b defaults; attended Stage 0/1 re-run
   on landed code. Earliest repository-run live session about 2026-10-01.
6. **Canon repair (roll-free):** retire 98.88/1.12, qualify "~504 dates", EF §10o done. Then redeploy the
   hash-pinned watchdog (trough-based disk arithmetic) and add a bounded retry to the merge tool's tape pre-check.

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic, not an objective.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture. Worktrees: `GIT_LFS_SKIP_SMUDGE=1`;
  pytest: `--basetemp`, then delete it.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay, release binding and
  evidence retention remain mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, an RE-1 session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
