# State of play

**Last updated: 2026-09-23 America/Toronto (owner strategy recorded; RE-1 session 1 ran, unpaid below the minimum; session 2 tonight on `c771cbb42`; disk binds).**
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
- Owner 2026-09-21: **RE-1** approved as an **attended workstation script the owner starts personally**, at most three
  sessions, none after 2026-09-30, worst case 20-30 dollars; outside the sealed lane and changes nothing in it (mission 84a).
- Owner 2026-09-22: RE-1 capital is a learning budget (losses reported, a fill is data); `H` = 1.00 net/day per 100 deployed.
- Owner 2026-09-23: [RE-1 addendum](../research/liquidity-reward-epoch-addendum-2026-09-23.md) (`BELOW_PAYOUT_MINIMUM` on `k_accrued`,
  either asset, graded adequacy); closes only on adequate `NOT_PAID` or `k_accrued` < 0.1 twice; 10-31 is an owner review.
- Owner 2026-09-23: **no second disk**; off-PC Drive archive as needed ([storage plan](storage-plan-2026-09-23.md)).
- Owner 2026-09-23 ([forward plan](forward-plan-2026-09-23.md)): `R` frozen as a rule; passive maker-evidence capture approved;
  payment tests may use any band and size within the 100 pUSD testing wallet (new pre-registration and tip each time).
  Owner 2026-09-21: model work unpaused; pre-register before scoring. Owner 2026-09-19: eligibility resolved; tunnel down live.
- **Open owner decisions:** the four 80b control-relaxation defaults; whether a Stage 2 grant may precede the Stage 0/1 re-runs.

## Current truth

- **Production source:** `master` = `origin/master` = `198f7ccbc` (2026-09-23; includes the per-chunk `--basetemp` fix
  `e1d766417`). 41 enabled tasks run from linked worktrees (OPERATIONS_DESIGN "What actually executes"). Before any merge,
  get `roll_verdict.ps1` and check for a quiet-window marker.
- **Disk (binding):** ~50 GiB free on 2026-09-23, falling 10-13 GiB/day: the Red/Critical boundary of the storage plan. The
  bounded suite and roll-sensitive landings refuse below 50 GiB. Judge at the ~04:50 daily low. Plan step 2 is done; step 1
  (inventory by data family) is owed.
- **Landing path:** fixed 16-32 GB pagefile (commit limit 32.5 GB; ~22,000 MB = reverted). Suite passed 09-21, stopped at the
  disk floor after chunk 10 on 09-23. Windows restart state: verify in `status.ps1` (the 09-21 owner action expired).
- **Settlement:** repair per date with `settlement_backfill_one.ps1 -TargetDate <d> -Refetch -RepoRoot <repo>`, never
  `chain_recovery_run.ps1`. The alarm looks back 14 days only. No hole was known on 09-21; verify with `status.ps1`.
- **Settlement source:** the venue resolves on the weather.gov WRH "Hourly Data" page since ~2026-08-23 (same stations);
  band agreement 921/921 before and 359/360 after; exact degrees undecided (86a). Master hard-codes WU; no gate detects a switch. EF §10c.
- **Capture:** health in `status.ps1`; it does not prove settled dates; T+1/T+2 reward bands have no canonical tape (D8-01).
- **Armed work:** supervisors, 05:00 projection, 06:00 tiering, refreshes, maker paper roll, 09:30 Stage-A, RE-0 poll (to 09-30).
  Training DISABLED; mirror and taker PAUSED. The deployed watchdog is newer than master: never re-register it from master.
- **RE-1 session 1** (2026-09-23 01:47-02:30Z, 42 min, one NYC T+2 band, `0a7531baf`): venue accrual 0.117 against
  `P_many` 0.105 / `P_single` 0.125; reward % 6.23 against ours 5.69/6.51; YES/NO books mirror (37/42 min); qualifying
  competition 4x within 40 min. Ended on a partial fill: 5.57 NO at 0.48 via a complementary YES buy that crashed the user
  stream; cleanup proven; shares held. Below the 1-dollar daily minimum: **unpaid**. EF §10m (owed), digest.
- **RE-1 verdict (provisional):** frozen table `INCONCLUSIVE` (`P_many` < 2); addendum `BELOW_PAYOUT_MINIMUM`, `k_accrued` ≈ 1.1,
  `SHORT`. Formal verdict after `collect-evidence` (earliest 00:00Z 2026-09-26), printed under both tables.
- **RE-1 code:** 84g (complementary-fill handling, payout addendum) accepted 09-23; **session-2 tip `c771cbb42`** (PR 85 line;
  PR 85 full suite at `0a7531baf`: 7,263 passed). Not on master. The 87a live-path qualification kit
  (`codex/live-path-qualification-20260923` @ `800bb9b72`) is not adopted.
- **Maker economics:** taker fee 0 on 377,104/377,104 public trades, so rebates are zero and rewards are the thesis. Configured
  pool ~2,800/day same-day, ~4,800 all active (EF §10a). Venue docs: pUSD since 2026-04-28, 1-dollar minimum per UTC day,
  no rollover, per-minute sampling, `Q_min` share. The 86b capacity sampler is PAUSED (mutex, duplicate pagination).
- **Maker candidate:** `codex/stage2-hold-build-20260921` @ `88aa7e43a` (contains the maker reconcile): inert, roll-sensitive,
  not host-qualified; adoption needs the owner's disposition of four control relaxations. It lacks the RE-1 fixes.
- **Forecast:** after 13Z the NBM parser read tomorrow's minimum (EF §10k); the versioned repair and bulletin reuse are built
  (EF §10l). Layer 1 landed (`29e161e7d`); layer 2 `codex/integrate-2-parser-20260921` @ `abd648c7c` (roll-sensitive) is
  **blocked on disk**; layer 3 `codex/integrate-3-reuse-20260921` @ `cee879c45` follows. No candidate is scored before
  post-fix dates exist; nothing new is served or trained.
- **Live record:** 2026-09-06 Stage 0/1 (zero fills; EF §10f) and RE-1 session 1; neither on master, neither grants authority.

## Ordered critical path

1. **RE-1 session 2 tonight on the 84h larger-size tip `1310ca6bf`** (owner 2026-09-23: more data is worth the test balance;
   size 20/30/50/75 by wallet, reserve <= min(wallet-10, 75); size addendum `docs/research/liquidity-reward-epoch-addendum-2026-09-23b-size.md`
   on its branch). Owner starts it at or after 20:00 ET after a same-day PASS `preflight`; both verdict tables. Freeze `R` done.
2. **Disk:** storage-plan step 1 (inventory) inside 00:30-09:00 under the lease; then compress-and-retain and the Drive archive
   until the daily low holds at 70 GiB or more. Everything that lands waits on this.
3. **NBM layer 2, then 3:** one per 01:00-04:00 quiet window, host-qualified by the bounded suite, once disk allows.
4. **Pillar B evidence** ([forward plan](forward-plan-2026-09-23.md) items 4-6): passive maker-evidence capture before 09-30,
   freeze `R`, then the fill-toxicity desk study and the timing outputs. RE-2 needs a paid verdict and a dated owner grant.
5. **Stage 2 hold build:** host qualification in a quiet window; owner disposes of the 80b defaults; attended Stage 0/1 re-run
   on landed code. Earliest repository-run live session about 2026-10-01.
6. **Canon repair (roll-free):** retire 98.88/1.12, qualify "~504 dates", zero-fee amendment, EF §10m/§10n.
7. Redeploy the hash-pinned watchdog (trough-based disk arithmetic); add a bounded retry to the merge tool's tape pre-check.

## Standing decisions

- International Polymarket only; no paid weather sources; backups deprioritized; streak contiguity is a diagnostic, not an objective.
- Capture-host heavy work is serial, admitted and time-gated; pushing never rolls capture. Worktrees: `GIT_LFS_SKIP_SMUDGE=1`;
  pytest: `--basetemp`, then delete it.
- Native settlement units, WU cutoffs, probability mass, train/serve parity, captured-input replay, release binding and
  evidence retention remain mandatory.

## Update this file when

Rewrite (never append) after an owner decision, an actual source adoption, a measured storage or settlement outcome, an
economic-feasibility result, an RE-1 session or verdict, or when `status.ps1` flags its age. Move history to the owning item.
