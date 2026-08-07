# Workstation disk: it is a mirror problem, not a workstation problem

Status: canonical plan, 2026-08-06. Written because the workstation is nearly full and the
instinct — delete on the workstation — does not work on its own.

## The reframe

**The workstation does not generate that data. Production pushes it there nightly.**
`C:\Users\micha\ops\mirror-weather-data.ps1` (not in git) runs `robocopy /MIR` from production's
`data\` to `\\DESKTOP-RFCD2GH\weather-mirror\data` at 04:30 daily.

`/MIR` means **anything deleted on the workstation is re-copied the next night** unless it is also
excluded at the source. Every reclaim below has to happen in the mirror scope, not on the target.

## Current numbers

| | |
| --- | ---: |
| Mirrored tree (log, 2026-08-06 04:30) | **532.664 GB**, 3,866,862 files, 65,773 dirs |
| Changed bytes that run | 36.977 GB copied, 495.687 GB skipped |
| Production free | **123.8 GB** of 930.6 GB |
| Production burn | **~10.9 GB/day** (418.6 GB free on 07-10 → 123.8 GB on 08-06) |
| **Production headroom** | **~11 days** |

**Production is closer to full than the workstation is.** Fixing only the workstation buys the
wrong host time.

Largest directories, from `data_retention_inventory.json` — **note it is dated 2026-07-10 and is
27 days stale**, because it sits past the settled-day barrier (below):

| Directory | Size | Files |
| --- | ---: | ---: |
| `snapshots` | **169.7 GB** | **3,180,411** |
| `backtest` | 44.0 GB | 3,097 |
| `taker_runs` | 18.4 GB *(74.7 GB by 08-03)* | 2,000 |
| `noaa_ghcnh` | 6.2 GB | 4,187 |
| `wunderground` | 4.9 GB | 74,292 |
| `metar` / `reanalysis` / `mm_runs` | ~3.5 GB each | — |

`snapshots` is the whole problem: **82% of the mirrored file count.** The 3.87M-file enumeration,
not the bytes, is why a nightly run takes ~28 minutes wall and ~6 hours of thread time.

## What has already been done — and the pattern to copy

The mirror already carries three exclusions, each added after a real incident and each documented
in the script:

- `*.claim` — ephemeral fetch locks; racy to copy, caused a false exit-11 on 2026-07-27.
- `data\backtest\replay_cache` — **32.3 GB** of *rebuildable* cache. Nothing requires a
  rebuildable cache to be replicated.
- `data\taker_runs` — **74.7 GB**, mostly counterfactual replay tape. The taker posts no orders
  and no workstation mission reads it.

**Both large exclusions required a one-time manual deletion on the workstation**, because `/XD`
skips a directory rather than purging it. Any new exclusion needs the same two steps: exclude at
source, then delete once on the target.

## The one large consumer that is NOT mirrored: `scratch\`

Everything above is about the mirrored tree. The workstation's **repo checkout** also carries
`<checkout>\scratch\`, reported at **~55 GB** on 2026-08-06. It is a different kind of problem and
a much easier one:

- **It is outside the mirror scope.** The mirror targets `\\DESKTOP-RFCD2GH\weather-mirror\data`;
  `scratch\` sits in the checkout. **`/MIR` will not restore it**, so no source-side exclusion is
  needed first — the two-step rule above does not apply here.
- **It is gitignored and untracked** (`.gitignore`: `scratch/`). Nothing in it is versioned.
- It holds **three superseded naming generations** — `workstation-research-output/<slug>-<date>`
  (July), `agent-runs/<mission>` (late July), `runs/<slug>-<date>` (August) — which is direct
  evidence nothing has ever cleaned it.
- [DELEGATION_CONTRACT.md](DELEGATION_CONTRACT.md) §6 already treats these paths as non-durable:
  workstation scratch paths appearing in a report are "the most common defect in an otherwise
  correct report", because they do not exist on the host that has to reproduce the work.

**Two guards before deleting any of it:**

1. **`scratch\worktrees\` is the dangerous subtree.** A worktree can hold uncommitted work that
   exists nowhere else, and agent reports live only on unmerged branches. Check `git status` and
   `git log origin/<branch>..HEAD` in each worktree; remove only clean, fully-pushed ones.
2. **Filter on recursive FILE mtimes, never directory mtimes.** A directory's timestamp does not
   update when files change deep inside it, so an actively-running mission's `runs\<slug>-<date>`
   folder can look days stale at the top level. "The current mission does not seem to be touching
   it" is exactly the observation this makes wrong.

Mission-local `venv\` directories under scratch are rebuildable; deleting them costs a reinstall,
not evidence.

## Why the designed fix is stuck, and what actually unblocks it

There is already a tiering design — closed market-days sealed into the parquet archive and moved
to the 2 TB cold Drive (tier 4), per
[data-storage-class-contract.md](data-storage-class-contract.md) and
[closed-market-day-parquet-archive-contract.md](closed-market-day-parquet-archive-contract.md).

**It is blocked, and has been since at least 2026-07-10:** the retention inventory reports
`event_day_manifests: manifest_count 0, pass_count 0`. Nothing is finalized-PASS, so nothing is
eligible to seal, so nothing can be tiered.

**And the reason is the same one that killed the learning loop.** `data_retention_inventory`,
`closed_day_parquet_incremental` and the sealing steps all sit **past
`settled_day_analysis_barrier`**, which the chain has died at or before on every run since
2026-07-10. The tools that would tell us what to delete, seal what is safe to archive, and move it
cold **have not run in 27 days.**

**So the disk problem and the dead-learning-loop problem are one blocker.** `-09-29a` (chain
promotion/learning lane split, awaiting merge) is what reopens both.

## The path forward, in order

**1. Land `-09-29a`.** Nothing else unblocks the sealing and tiering path. Until the chain gets
past the barrier, every tiering decision is being made on 27-day-old inventory data.

**2. Re-run the retention inventory** once the chain completes, and re-read the table above. Do
not act on the stale numbers for anything irreversible.

**3. Bound the mirror's `snapshots` scope — the single biggest lever.** The workstation does not
need a full replica. Research missions read *selected* dates: `-09-31a` used 12,289 snapshots
across 50 dates, not 3.18 million files. Mirror a bounded recent window and let missions request
older blocks on demand. This is the operator's own proposal and it is the right architecture.

**4. Seal and tier closed market-days to the 2 TB cold Drive** once (1) makes them eligible.
Sealed-market-day unit only, per the storage-class contract.

**5. Only then consider deletion.** Deleting canonical tape before an off-machine copy is proven
is prohibited by the retention policy, and `verify_mirror_restore.ps1` exists precisely because a
robocopy exit code proves a copy ran, not that it can be restored from.

## The tradeoff being accepted, stated plainly

`\\DESKTOP-RFCD2GH\weather-mirror` is described in `verify_mirror_restore.ps1` as **the only copy
of `data\` that is not on the production host.** Narrowing the mirror narrows the only off-host
backup. That is a real loss of durability, not a free win.

It is consistent with the standing operator decision that **profitability outranks durability**
and that the backup gap should not block progress. Recording it here so the choice is visible
rather than discovered later: **after step 3, older snapshots exist only on production until step
4 puts them on the cold Drive.** Steps 3 and 4 should therefore land close together, and step 4
should not be deferred indefinitely.

## What NOT to do

- **Do not delete on the workstation without excluding at source first.** `/MIR` restores it.
- **Do not delete `data\backtest\replay_cache` on production.** It is excluded from the mirror
  because it is rebuildable, which is not the same as disposable; `storage_classes.py` gates its
  local deletion on a reachability manifest.
- **Do not delete the "redundant" CSV half of a split long projection.** 20 market-days were split
  into disjoint gz + plain halves; the halves are not duplicates.
- **Never re-add `lfs: true` and never delete `.git/lfs`** ([git-lfs-policy.md](git-lfs-policy.md)).

## Update this file when

The mirror scope changes, the cold tier starts accepting sealed market-days, or the retention
inventory is refreshed after the chain reaches it.
