# Lock-readiness plan — target 2026-08-03

## Where we actually are

**Both clocks agree at 10.** Verified 2026-07-31 by running the release-admissibility clock from a
worktree against live production evidence:

```text
contiguous_pass_days : 10
streak_start_date    : 2026-07-21
latest_status        : PASS   (release_admissible)
```

Every day 07-21 → 07-30 grades `release_admissible`, **including 07-24**, so the repaired lost write
holds under the tool that owns the predicate. `streak.ps1` reports the same 10/14 from the same start
date. The operational clock is not flattering us.

**So the lock lands 2026-08-03 if 07-31, 08-01, 08-02 and 08-03 all stay clean**, and the 7-day build
window runs to roughly 08-10.

## The actual risk: the release path is not on master

Fifteen branches are unmerged. Most are inert — `bootstrap-rehearsal`, `pit-simplex`,
`lock-blocker-fixes`, `release-one-rehearsal` and `mm-gate` are 1-2 files each, i.e. their handback
reports; their code already landed. Those can be closed.

Six carry real work, and three of those are release-critical:

| branch | files | src | roll-sensitive | why it matters |
| --- | ---: | ---: | ---: | --- |
| `second-clock-bootstrap-2026-07-30f-keystone` | 19 | 8 | **2** | `release_admissibility_clock.py` **and** `all_shadow_release_bootstrap.py` — the release builder itself |
| `release-one-blockers-2026-07-29` | 17 | 10 | **2** | release #1 blocker fixes |
| `strict-parity-2026-07-29` | 18 | 10 | **2** | parity path |
| `who-breaks-floor-2026-07-27g` | 33 | 14 | 1 | warm tier (deferred 3x) |
| `skill-gap-2026-07-25b` | 31 | 12 | 1 | research |
| `hardening-lock-blocker-fixes-2026-07-24` | 192 | 90 | 0 | needs B1/B3 fixes first |

**The release-admissibility clock is not on master.** I had to build a worktree to read the number
that gates everything. That is the single worst piece of the current setup.

### Why this is urgent rather than annoying

All three release-critical branches touch the same roll-sensitive files (`snapshot_store.py`,
`schema_registry_recent_data.py`). Roll-sensitive merges only happen in the 01:00-04:00 window, at
roughly two per night. Tonight's two slots are already committed to the monitor and frontier branches.
That leaves **08-01 and 08-02 — four slots — for three branches that will almost certainly conflict
with each other**, immediately before the lock.

Three separate merges, each rolling the capture fleet, each able to cost a streak day, in the last 48
hours before a lock we have been chasing since June, is the wrong shape of risk.

**Mitigation: consolidate first, merge once.** Have the workstation rebase all three onto current
master as a single stack, resolve the conflicts there where nothing is at stake, run the full suite on
the combined tree, and hand back **one** mergeable branch. That converts three risky rolls into one.

## Workstreams

### 1. Consolidate the release path (workstation, starts now)

One branch off current master containing `second-clock-bootstrap` + `release-one-blockers` +
`strict-parity`, conflicts resolved, full suite green on the merged tree, with an explicit statement of
what changed during conflict resolution. Do not include warm-tier, skill-gap or hardening — they are
not lock-critical and they add conflict surface.

### 2. Wire the second clock into daily ops (after 1 merges)

Run `release_admissibility_clock grade` after settlement each day, then `collapse`, and surface
`contiguous_pass_days` in `status.ps1` reading only `clock.json`. Correct roots, which cost a cycle
today: `--snapshots-root data/snapshots`, **`--ledger-root data/settlements`** (not `data/backtest`).
After this, both clocks are visible daily and nobody hand-runs a worktree.

### 3. Dress-rehearse the build before the lock (workstation)

Nothing past preselection has ever run on real evidence, and the lock opens only a 7-day window. Build
a throwaway prelock from current evidence and run the entire path to a research-only, all-shadow
release: preselection → lock → candidate fit → locked replay → PIT → promotion qualification →
immutable training-graph verification. Report the **first** failure honestly rather than a green
summary. Every failure found this week is a failure not paid for out of the 7-day window.

### 4. Disk headroom for the build window (mine, decision needed)

~130 GB free, burning ~15 GB/day → exhaustion around **08-08/08-09**. The build window runs to
**08-10**. The build itself consumes disk. As it stands the window gets truncated by roughly two days.

`data/backtest/replay_cache` is 32.3 GB, classified `OPERATOR_CACHE` /
`reachability_bounded_rebuildable_replay_cache`, already excluded from the mirror, and no release
currently pins it — about 2.2 days. Its sanctioned gate is an exact-key reachability manifest rather
than age, so generate that manifest and delete what it proves unreachable. Operator decision.

### 5. Lock-day checklist (mine, pre-staged)

- verify both clocks read 14 from the same `streak_start_date` before declaring the lock;
- **regenerate both sides** of the non-strict `rows[-1]` boundary — candidate replay and corpus
  regeneration changed on degraded rows, and mixing artifacts across that boundary is invalid;
- flip the observed-floor monitor from alert-only to fail-closed
  (`--fail-on-observed-floor-safety`) once the lock is secured;
- confirm no roll-sensitive merge is armed for lock night;
- snapshot `clock.json`, receipts and their hashes as lock evidence before building anything.

## Deliberately not in scope before the lock

Market-making promotion-gate relaxation, C-family prelock/fit/replay, cold tier and the 500 GB cap,
pointer creation, warm tier, hardening branch, MM live capital.
