# Workstation handoff — 2026-07-30e: reclaim safe space, then build the cold tier

Operator has declared workstation disk critical, and has 2 TB of Google Drive available. This
handoff frees space first and builds the cold tier second, in that order, because building an
archive tool consumes scratch space you do not currently have.

## Mission 0: push `ea0167a7` before you do anything else

Your last handback was committed "intentionally unpushed". I cannot read the report, so the
keystone findings are stranded — including the one answer I most need, which is what predicate I
should measure daily now that the operational streak turns out to be necessary but not sufficient
for PIT admission. Push the branch. If there is a reason a branch should stay local, tell me the
reason; the topic-branch push is the only channel between us and a local commit is invisible to me.

## What I already did on this side, and the one thing it needs from you

`WeatherDataMirror` was running a bare `robocopy /MIR` of all of `data/`, which means it was
replicating **`data/backtest/replay_cache` — 32.28 GB / 770 files** of cache that our own
`storage_classes.py` classifies as *rebuildable*. Nothing requires a rebuildable cache to be
replicated; it is not archive payload. I excluded it (`/XD`) on 2026-07-29; next run is 04:30.

**`/XD` skips a directory, it does not purge it.** So the 32.28 GB copy on your side will sit there
forever until deleted explicitly. That is Mission 1, and it is roughly 3x the 9.7 GiB you were
short of the MM admission floor.

## Mission 1: delete the mirrored replay cache — with two guards

Target: `<mirror-root>\data\backtest\replay_cache`.

Before deleting, both guards must pass, and both are fail-closed:

1. **Junction guard.** Confirm the target is a real directory on your local volume and **not** a
   junction, symlink, or reparse point that resolves back to the production host. Check
   `(Get-Item <path> -Force).LinkType` and `.Attributes` for `ReparsePoint`, and resolve the full
   target. If it is a link, **stop and report** — deleting through it would destroy production
   evidence. This is the single way this mission could go badly wrong.
2. **Receipt.** Record file count and total bytes before deletion so the reclaim is measurable
   rather than asserted, and record free space before and after.

Then verify the exclusion actually holds: after the next 04:30 mirror run, confirm
`replay_cache` was **not** re-copied. If it comes back, stop and tell me — that means my `/XD` is
not matching and you should not delete it a second time.

Do not delete anything else from the mirror in this mission. The mirror is production's replica and
every other path in it is canonical evidence until proven otherwise.

## Mission 2: derive your real hot window — the 531.8 GB question

This is the largest lever in the whole problem and nobody has asked it.

Exact tree size, from the 04:30 robocopy summary (which reports whole-tree totals without needing a
scan — use this technique instead of recursing 3.79M files): **531.805 GB, 3,785,460 files, 53,469
dirs.** All of it is on your disk, and all of it is a replica of data that already exists on
production.

Item 325 requires production to derive its hot window from code rather than assumption. The same
question has never been asked of *your* side: **which market-days do your workloads actually
read?** Enumerate the real consumers — MM backfill/scoring, replay, backtest, corpus and ablation
work — and report, per consumer, the maximum lookback in market-days it genuinely requires.

If the answer is "the last 60 days plus occasional older dates on demand", then the mirror can be
date-scoped and hundreds of GB freed, with older dates served from cold storage. That is a far
bigger win than any cleanup. Report the binding constraint and the date-scoped size it implies.
**Do not change any sync configuration** — mirror topology is mine and the operator's. I want the
measurement and your recommendation.

Also report what remains on your own local (non-mirror) space by class, with a keep / reclaim /
rebuild verdict per top consumer, and flag anything that regrows structurally rather than once.

## Mission 3: build the cold tier — and push nothing until a restore drill passes

The design is recorded in item 325 (`docs/roadmap/items/item-325-*.md`, section
"2026-07-29: a fourth tier"). Read it. The short version, because two measured numbers force the
whole shape and improvising around them will produce something unusable:

- **3.79M files.** A per-file cloud sync costs days of pure metadata round-trips on *every pass,
  forever*. The market-day archive (562 objects) is the only viable unit. This is why the warm tier
  is a prerequisite for the cold tier and not an alternative to it.
- **4.4x churn amplification.** Last night copied 39.476 GB for ~8.9 GB genuinely new, because
  `order_books_long.csv` and its siblings grow all day and re-copy whole. Drive has no delta
  transfer either. So **only sealed market-days are ever pushed** — which makes the cold tier
  append-only by construction and sets upload volume to the retained rate, not the churn rate.

| what we push | initial | daily | 2 TB lasts |
| --- | ---: | ---: | ---: |
| raw tree as-is | 532 GB | ~10 GB | **~5 months** |
| sealed compressed market-days | ~70-120 GB | ~1.5-2 GB | **~3 years** |

Build:

1. **A `sealed` predicate.** A market-day is sealed when it is closed (settled, labeled, referenced
   by no open barrier, queue entry, or active point-in-time window) **and** its tiering is complete.
   Fail closed on anything you cannot evaluate. Assert it in tests, not documentation.
2. **One deterministic archive per sealed market-day**, plus a manifest carrying file count, total
   bytes, and per-file content hashes.
3. **`rclone` with a `crypt` remote**, verified by `rclone cryptcheck`. Encryption is not
   gold-plating: raw capture payloads can embed provider API keys in request URLs and headers, and
   an upload to a third party cannot be recalled, only rotated. Crypt closes that structurally
   instead of trusting a scan to be exhaustive. `cryptcheck` also satisfies item 325's gate 3,
   "verified by manifest, not merely present".
4. **A restore drill** on one sealed market-day: pull it back and prove byte-identity against the
   manifest. Item 325 is explicit — an archive that has never been restored is an assumption, not a
   backup. No further pushes until this passes.

Constraints on the build:

- **You are near full, so archive one market-day at a time**: build, verify, upload, delete the
  temporary archive, then move to the next. Never materialize a batch of archives.
- **The Google OAuth step is the operator's**, not yours. Prepare the rclone config and tell them
  exactly what to run (`rclone config`, the remote names, the crypt parameters); do not attempt to
  authenticate their account. The crypt passphrase must be recorded by the operator, not committed.
- **Push nothing to Drive until the drill passes**, and delete nothing locally on the basis of a
  cold copy — the four deletion gates and the `/MIR`→`/E` split still stand, unchanged.
- Name honestly in your report that the cold copy would be **derived from the mirror, i.e. a copy
  of a copy**: if the mirror was stale or incomplete for a date, the cold copy inherits that. Say
  whether verification should instead run against a production-generated manifest, and what that
  would require of me.

Drive must never be a mirror target, a working tier for replay/backtest, a git remote, or a `.git`
host. Do not build in that direction.

## Mission 4 (stretch, only if 1-3 are done)

The ~382 MB model artifacts exhausted the account's metered Git LFS bandwidth. Drive is the natural
distribution channel for them. Scope it; do not implement without saying so first, because it
touches the release/artifact path.

## Priority

0, 1, 2, 3, 4 in order. Mission 0 costs 30 seconds and unblocks me. Mission 1 is the largest
single free win. Mission 2 is the largest *structural* win and is measurement only. Mission 3 is
the build.

Compression note so you do not waste a day: **compression must originate on production.** If you
compress files inside the mirror, the next `/MIR` run reverts them. The reverse works in our favour
and is verified — production tiered 12 july-27 `order_books_long.csv` files (1.2-1.3 GB each) to
53-62 MB gz, and last night's run purged **15.9 GB** from your side automatically. The warm tier
merges here at 01:15 tonight with a 12-folder pilot, then the full 192-folder apply; expect the
mirror to shrink on its own over the next two nights.

## Guardrails

Unchanged: `data/` read-only with the OS-level deny-write ACL, outputs under one declared run root
outside the mirror, topic branches only, no PR, no merge, no master push, no promotion, no pointer
change, no serving change, no scheduler or capture changes, no mirror topology change. Never read or
expose the sync credential. The one new permission here is narrow and explicit: **you may delete
`<mirror-root>\data\backtest\replay_cache`, and nothing else inside the mirror**, and only after
both Mission 1 guards pass.

## Handback

`docs/roadmap/agent-report-<date>-workstation-reclaim-and-cold-tier.md`: the Mission 1 receipt
(bytes freed, free space before/after, junction-guard result) first, then the Mission 2 hot-window
measurement with the date-scoped size it implies, then the cold-tier build state and drill result.
Push the branch.
