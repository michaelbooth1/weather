# Gap audit: disk-reclaim tie-break (gap-disk-reclaim-tiebreak)

Auditor: Claude (subagent), 2026-09-19 ~03:20-04:00 local, on the live 16 GB production capture host.
Read-only. No project file was modified, staged or committed. This report is the only write.

Question put to this gap: three auditors disagree on the largest candidate reclaim lever
(worktrees: "~70 GiB, critical" vs "~10 GB, low" vs "~10 GB"). How much is safely reclaimable right
now, and which levers are admissible with under 20 GiB free?

## 1. Bottom line

1. **Measured, not extrapolated: 175 of 200 linked worktrees hold fully smudged LFS model pickles.
   Each smudged `artifacts/models/hgb` directory is exactly 371,560 KiB allocated (362.85 MiB).
   175 x 371,560 KiB = 65,023,000 KiB = 62.0 GiB (66.6 GB decimal).** This is a full census of every
   linked worktree (one non-recursive `ls` each), not a sample. 23 worktrees hold 131-134 byte
   pointers; 2 have no `artifacts/` directory at all.
2. **recent-work was right on size and on tier; storage-capacity-9 and agent-governance F6 were wrong
   by about 6x.** Both "~10 GB" figures are 200 x ~50 MB of *tracked* content. Neither looked at the
   LFS smudge state. recent-work's 70.5 GiB assumed 199/199 smudged from 5/5 samples; the true rate
   is 175/200 (87.5%), so it overstated by ~12%. storage-capacity's *risk* cautions (locked
   worktrees, scheduled tasks bound to checkouts) are valid for worktree **removal**, but none of
   the three considered the cheaper lever below.
3. **The lever is un-smudging, not removal.** Replacing the 27 `.pkl` files in each smudged linked
   worktree with their Git LFS pointer text frees ~61 GiB by touching ~4,700 large files. It does
   not remove a worktree, a branch, a commit, an untracked receipt or an ignored file. It is
   reversible offline from the local `.git/lfs` store (`artifact-storage-policy.md:96-100`). Full
   removal of all 200 worktrees would add only ~10-12 GiB more while deleting ~420,000 small files
   and everything untracked in them.
4. **The waste is still being created.** `docs/git-workflow.md:133` prescribes a bare
   `git worktree add` with no `GIT_LFS_SKIP_SMUDGE`. Nothing under `scripts/` sets it. Worktrees
   created on 09-15, 09-16, 09-17 and 09-18, with the disk already in the red, each materialised
   363 MiB. 28 worktrees created *by the storage/capacity/archive effort itself* hold 9.9 GiB of
   pickles, about 13% of what the five-week archive campaign reclaimed.
5. **Free-space figures reconcile.** 21 "GB" (09-18 21:20), 18.5 (22:05), 11.3 (~02:00-02:30 09-19)
   and the 14.2 trough (09-18 04:50) are one instrument (`status.ps1:1298`, `Free / 1GB`, so GiB
   labelled "GB") read at different phases of the 13-16 GiB daily sawtooth. They imply a 09-19 04:50
   trough of roughly 6-8 GiB, matching storage-capacity's projection.
6. `C:/tmp` and worktree-local `data/` directories are not levers (well under 1 GiB visible; the
   PIT corpus in `C:/tmp` is hard-linked and part of a frozen pre-registered test; do not touch).

Health grade for this dimension: **D**. The single largest admissible reclaim on a disk 1-2 days
from exhaustion is pure duplicate data that no project document records, and the default workflow
adds 363 MiB more with every new worktree.

## 2. Scope and method

Whitelisted shell only, strictly serial, every command piped through `head`:
`git worktree list`, `git branch --merged master`, `git branch -a/-r --contains <sha>`,
`git log`, `git show --stat`, `git ls-files`, and non-recursive `ls -la` of one directory at a
time. No python, no `du`/`find`/`wc`, no recursion, no `git status` in other worktrees, no network,
no read of production `data/`.

- `git worktree list | head -n 200`: 200 lines shown (1 main + 199 linked). A 200th linked
  worktree (`scratch/w/split-qualification-20260914`) falls on line 201 and was confirmed by a
  non-recursive `ls` of `scratch/w` (25 directories, 24 listed by git before truncation). Total
  linked = 9 (`C:/tmp`) + 164 (`Desktop/github/weather-*`) + 2 (`.claude/worktrees`) + 25
  (`scratch/w`) = **200**. recent-work saw 199 because `C:/tmp/wt-audit-rollfree-20260919` was
  created at 09-19 03:00, after its run.
- For **every** linked worktree: one `ls -la <wt>/artifacts/models/hgb | head -n 1` (the `total`
  line, in 1 KiB allocated blocks). `total 371560` = smudged; `total 38` (or `116`) = pointers.
  Anything else was listed in full. Two full listings of smudged directories confirm
  `feature_model_hgb_f_pooled.pkl` = 103,734,643 bytes and **link count 1** (independent copies,
  not hard links): `C:/tmp/wt-09-69a` and `scratch/w/recovery-end-to-end-20260917`.
- Root listings (`ls -la <wt> | head -n 40`) for 8 worktrees across all four location classes;
  worktree-local `data/` listed for the 3 that had one.
- `ls -la C:/tmp | head -n 200` and listings of `item40_artifacts`, `item40_ramp_backup`,
  `pit-transfer-20260902` (+ its 8.5 KB manifest), `pit-refetch-2026-08-10`, `clob_v2_venv`.
- Read: `.gitattributes`, `docs/git-workflow.md` (full), `docs/operations/artifact-storage-policy.md`
  (full), `DELEGATION_CONTRACT.md:90-134`, `OPERATIONS_AGENT_ROLE.md:55-129`,
  `branch-retirement-2026-08-11.md:1-60`, `HOST_LOAD_POLICY.md:310-349`, `item-325:1-110`,
  `AGENTS.md:90-149`, `config/storage_pressure.json`, `storage_pressure_policy.py` (full),
  `market_microstructure_capture.py:750-774`, and the three disputed auditor reports.
- Grep (explicit path each time): `GIT_LFS_SKIP_SMUDGE`, `worktree add|remove|prune`, `smudge`,
  disk floors in `replay_cache_compression_admission.py`, `production_cold_archive_stage_cli.py`,
  `clob_order_book_tiering.py`, `status.ps1`.

## 3. Census result

| Location | Linked worktrees | Smudged (371,560 KiB) | Pointer | No `artifacts/` |
| --- | ---: | ---: | ---: | ---: |
| `C:/tmp/wt-*` | 9 | 3 | 6 | 0 |
| `C:/Users/micha/Desktop/github/weather-*` | 164 | 152 | 10 | 2 |
| `weather/.claude/worktrees/*` | 2 | 2 | 0 | 0 |
| `weather/scratch/w/*` | 25 | 18 | 7 | 0 |
| **Total** | **200** | **175** | **23** | **2** |

Smudged in `C:/tmp`: `wt-09-69a`, `wt-prod-baseline-reconcile-96a`, `wt-roll-free-control-plane-0903`.

Pointer worktrees (23):
- `C:/tmp`: `wt-audit-rollfree-20260919`, `wt-model-pit-foundation-20260831`,
  `wt-overnight-ops-reliability-20260901`, `wt-pit-v2-collector-handoff-20260831`,
  `wt-prod-baseline-reconcile-85a`, `wt-review-overnight-ops-81a`.
- `Desktop/github`: `weather-48h-maker-opportunity-20260911`, `weather-archive-dpapi-20260905`,
  `weather-archive-native-qualification-20260905`, `weather-fanout-receipt-publication-20260911`,
  `weather-maker-incentive-payments-20260911`, `weather-maker-plan-20260904`,
  `weather-maker-refocus-baseline-20260905`, `weather-post-reclaim-config-generation-20260907`,
  `weather-post-reclaim-fixture-disk-20260907`, `weather-post-reclaim-native-replay-20260907`.
- `scratch/w`: `archive-immediate-ci-20260913-a1`, `overnight-results-20260913` (pointers rewritten
  at 01:57, 30 minutes after the 01:27 checkout, `total 116`), `overnight-status-only-20260913`,
  `overnight-storage-20260913`, `reliability-audit-integration-20260913`,
  `reliability-empty-rows-20260913`, `reliability-fixture-host-20260913`.

No `artifacts/` directory (sparse or pruned checkout): `weather-capture-health-20260907`,
`weather-watchdog-deployed-aa99048` (locked).

Every other linked worktree in `git worktree list` is smudged. The identical `total 371560` in all
175 means an identical 27-file set since at least 2026-08-11.

Why the state is mixed: `.gitattributes:9` puts `artifacts/models/hgb/*.pkl` under LFS; the Git LFS
filter is evidently installed and smudges by default on this host; and the 23 pointer worktrees are
the ones whose creating session happened to set `GIT_LFS_SKIP_SMUDGE=1` (the only mention in the
repo is one workstation report, `docs/roadmap/agent-report-2026-08-31-workstation-identity-binding.md:152,191`).
There is no pattern by date: 09-13 has both kinds, 09-15..09-18 are all smudged, 09-19 03:00 is
pointer. **Future worktrees will smudge by default** unless the creating agent remembers the
variable.

### (a) Bounded byte estimate

| Bound | What it counts | Worktrees | GiB |
| --- | --- | ---: | ---: |
| Low | Un-smudge only worktrees whose branch is already an ancestor of `master` (= `origin/master`), excluding `overnight-audit-20260918` (at master tip, one day old) | 89 | **31.5** |
| Best | Un-smudge every smudged linked worktree except the locked `weather-overnight-watchdog-20260906` and `overnight-audit-20260918`; subtract 0.354 GiB for each checkout later found to be bound to a live scheduled task | 173 | **~58-61** |
| Measured total | All smudged pickles in linked worktrees | 175 | **62.0** |
| High | Remove all 200 linked worktrees outright: 62.0 GiB pickles + ~50 MB tracked content x 200 (+ NTFS slack, `.pytest_cache`, `.ruff_cache`, small `data/`) | 200 | **~72-75** (the extra ~10-12 GiB is inferred, not measured) |

Caveat that applies to every delete-type lever on this host: `item-325:34-37` records that on
09-13 "Windows shadow storage initially absorbed much of the capacity benefit" until the older
shadow copy expired. Freed clusters that are reused while a shadow copy exists are copied into the
diff area up to its cap, so realised free space can lag computed bytes. Measure success by
`Get-PSDrive` free bytes, not by the sum above.

## 4. Safety of removal / un-smudge

Verified:
- **Detached HEADs: 18** (`wt-09-69a`, `-85a`, `-96a`, `-81a`; `capacity-day-a1/-a2`,
  `capacity-night`, `-a2`; `pr5-merge-preflight`; `watchdog-deployed-aa99048`;
  `wu-outcome-exporter-100c`, `-100e`; six under `scratch/w`). For 17 of them
  `git branch -r --contains <sha>` returns at least one `origin/` branch; the 18th
  (`capacity-day-20260909-a2`, 103543394) equals the tip of the merged branch
  `codex/capacity-recovery-20260908`. No detached commit is local-only as of the last fetch.
- `git log origin/master..master` is empty: local master has no unpushed commits.
- `git branch --merged master` marks **94** worktree-attached branches as ancestors of master; 90 of
  those worktrees are smudged (31.9 GiB), 4 are pointer.
- **Local-only branch tips exist among unmerged worktrees: 5 of 15 sampled.**
  `codex/portable-execution-host-20260827` (c1ed905ae), `codex/core-model-audit-20260815`
  (d5efcd9bf), `codex/model-loaded-identity-v03-20260815` (9f81b3fe5),
  `codex/live-fixed-scope-prep-20260817` (0df52a9c1), `codex/overnight-hardening-20260819`
  (dc93479b2) return nothing from `git branch -r --contains`. Extrapolated to ~89 unmerged
  branch-attached worktrees this is consistent with the "~30 local-only" figure. Removing a
  worktree does not delete its branch, so these commits survive either lever; they matter only
  because this host has no mirror (known_accepted) and a disk-full crash is the imminent risk.
- `weather-portable-execution-host-20260827` shows file mtimes hours after its checkout
  (`AGENTS.md` 12:30, `config/` 12:59, `tests/` 14:20, `README.md` 14:47 vs 11:49) and an 86,230-byte
  `sitecustomize.py` (2,211 everywhere else). It may hold uncommitted work on a local-only branch.
- Two worktrees are `locked`. `OPERATIONS_AGENT_ROLE.md:261` documents a scheduled task
  (`WeatherSuite0969a`) bound to `C:/tmp/wt-09-69a`; `item-325:105` says a sealed one-shot's
  "isolated checkout must remain exact and clean". Task Scheduler is off limits to this audit, so
  **which worktrees are still referenced by a task action is unverified.**
- `C:/tmp/wt-audit-rollfree-20260919` is live: branch `claude/audit-rollfree-fixes-20260919`
  advanced to 0b6d4f288 at 03:05 today (memory-guard fix + test). It is pointer-state and must be
  left alone. (Observation only: a fix commit was made on a topic branch while this no-changes
  audit was running. It did not touch master.)

**Not verified: uncommitted, untracked or ignored content in any worktree.** `git status` inside
other worktrees is not whitelisted. Sampled roots show `.pytest_cache`, `.ruff_cache`, `.codex`
and small test-written `data/` in some.

Rules that bind (read, with lines):
- `docs/git-workflow.md:14-17`: existing worktrees "must be preserved and reconciled intentionally".
- `docs/git-workflow.md:145-146`: "Do not edit, stage, commit, or clean another task's worktree."
- `docs/git-workflow.md:271-309`: a worktree may be removed only after status is clean, no ignored
  content exists ("obtain an explicit storage/retention disposition before removal"), the branch is
  an ancestor of `origin/master`, post-merge checks pass, and "no operator still needs it". "Never
  delete a dirty worktree, use forced branch deletion".
- `DELEGATION_CONTRACT.md:119-120` and `OPERATIONS_AGENT_ROLE.md:64-66`: never delete a branch;
  never delete `.git/lfs`.
- `OPERATIONS_AGENT_ROLE.md:121-122`: "Confirm first only for irreversible or outward-facing
  actions: bulk deletion ...".
- `HOST_LOAD_POLICY.md:326-333`: no bulk file operations 18:00-00:30; heavy ad-hoc work 00:30-09:00
  with commit < 70% **and >= 50 GB disk free**.

What owner approval is needed, exactly:
1. **Un-smudge (recommended):** one dated owner decision that (i) authorises an operations agent to
   modify the tracked LFS files inside *other tasks'* worktrees (exception to
   `git-workflow.md:145-146`), (ii) waives the literal 50 GB free-disk precondition for a
   delete-only operation (`HOST_LOAD_POLICY.md:333`; the floor protects against work that consumes
   disk, and is circular here), and (iii) names the exclusions: the main production worktree
   (it serves from these pickles), locked worktrees, any checkout referenced by a live task action,
   and `wt-audit-rollfree-20260919`. Per-worktree guard: pickle sizes and mtimes equal the checkout
   minute (unmodified), or `git -C <wt> diff --quiet -- artifacts/models/hgb`. It is reversible
   offline (`git lfs checkout` / `git lfs pull --include=...`, `artifact-storage-policy.md:96-100`),
   and the registry already treats a canonical pointer as the artifact's identity
   (`artifact-storage-policy.md:78-83`). 23 worktrees already live in this state.
2. **Removal:** the SOP itself authorises it only per worktree after all of `:271-305` pass. Doing
   it in bulk is "bulk deletion" (`ROLE:121`) and needs explicit owner confirmation plus a retention
   disposition for any ignored content. For the 94 merged-branch worktrees this is legitimate
   hygiene, but it is hours of serial checks for ~5 GiB beyond what un-smudging already returns.
   Removing a worktree never deletes its branch; `git branch -d` is a separate, prohibited-by-default
   step and is not needed for the reclaim.

## 5. (b) Ranked levers admissible at under 20 GiB free

"Admissible" = the lever's own precondition does not require 20-50 GiB free.

| # | Lever | Bytes | Time | Risk to unmerged work / capture | Approval |
| --- | --- | --- | --- | --- | --- |
| 1 | Un-smudge LFS pickles in linked worktrees (pointers in place of `.pkl`) | **61 GiB measured** (31.5 GiB if limited to merged-branch worktrees) | ~15-30 min scripted, serial (estimate); ~4,700 file deletes | Unmerged work: none (tracked, unmodified, locally restorable). Capture: low if run 00:30-04:30 and never against the main worktree; catastrophic to serving if the main worktree is included | Owner dated decision (see section 4, item 1) |
| 2 | `config/storage_pressure.json` `write_order_books_long_csv=false` at a day boundary | ~+13 GiB of trough headroom per day (doc_claimed: storage-capacity trail, +11.7..+13.8 GiB returned at 05:00 daily); not a slope change | One config line; `config/` is roll-free per `AGENTS.md:103-104` | Work: none. Capture: low; canonical `order_books.jsonl` unaffected (`market_microstructure_capture.py:837`), loader is fail-safe (`storage_pressure_policy.py:30-88`). Mid-day flip leaves a partial CSV that tiering would treat as complete | Owner; reverses the 07-29 item-325 rejection |
| 3 | Protect the 05:00 / 06:00 tiering runs (no lease holder, no reboot 04:45-06:45) | Preserves ~14-16 GiB/day already counted | None | None | None |
| 4 | Remove the 94 merged-branch worktrees per SOP section 7 (after lever 1) | ~5 GiB incremental (inferred), ~37 GiB if done instead of lever 1 | Hours (per-worktree status + ignored inventory; ~200k small-file deletes) | Untracked/ignored receipts lost unless dispositioned; breaks any task bound to the path | Owner confirmation (bulk deletion) + retention disposition |
| 5 | Windows shadow-storage check / cap | Unknown. Only measurement on record is 1.54 GB used at 09-13 02:16 (`item-325:37`), so "10+ GiB" is unsupported | Minutes, elevated shell | None to project data; loses restore points | Owner only |
| 6 | Cold-snapshot NTFS compress-and-retain | ~2 GB per cold calendar day (doc_claimed) | Hours per night | None to work; gated on commit < 70%, which keeps refusing | Owner <=72 h request; floor 8 GiB + 136 MiB, so it becomes inadmissible at tonight's projected trough |
| 7 | Second physical disk for cold `data/` | Ends the race | Days + purchase | Low; cold data only | Owner purchase; `HOST_LOAD_POLICY.md:427-430` already recommends it |
| 8 | Warm-tier gzip of closed-day families | Slope ~6 -> ~1.3 GB/day (doc_claimed) | Days; blocked on event-day manifests since 08-02; roll-sensitive | Moderate | Owner + quiet-window merge; not a 48-hour lever |
| - | `C:/tmp` cleanup | < 1 GiB visible (largest single file 9 MB; two 28 MB pickles; 171 MB transfer copy) | - | `pit-refetch-2026-08-10` is hard-linked (link count 2) and belongs to the frozen pre-registered PIT test: deleting frees nothing and risks the corpus | Not worth raising |
| - | NTFS-compress worktrees | Strictly worse than lever 1 | - | - | - |

Not admissible under 20 GiB (verified floors): archive staging 50 GiB, 20 GiB for one pinned plan,
8 GiB only for a dated window (`production_cold_archive_stage_cli.py:35-44,142-151`); replay-cache
compression 20 GiB + 129 MiB (`replay_cache_compression_admission.py:32`); bounded test suite and
ordinary heavy work 50 GiB (`HOST_LOAD_POLICY.md:333`). Tiering itself needs `source + 1 GiB`
(`clob_order_book_tiering.py:26,309-328`), which is storage-capacity-2's deadlock.

Sequencing: lever 1 first. At the measured 6-8 GiB/day net burn, 61 GiB is roughly 8-10 days of
runway, it lifts free space back above the 50 GiB floor so that the sanctioned lanes and the merge
gate become admissible again, and it costs nothing irreplaceable. Then lever 2 at the next day
boundary. Then fix the default (section 6) so the space is not re-consumed.

## 6. (c) Which auditor's severity was right

- **recent-work-1 (critical, ~70 GiB): right in substance.** Measured 62.0 GiB vs claimed 70.5 GiB
  (-12%: it assumed 199/199 smudged; actual 175/200). Its "94 merged worktrees, ~37 GiB" is 90
  smudged, 31.9 GiB. Its caveats (locked worktrees, task-bound checkouts, per-worktree status
  check) were correct. Critical is defensible: with every sanctioned lane inadmissible, this is the
  largest and fastest admissible reclaim against an imminent capture-crash risk.
- **storage-capacity-9 (low, "~10 GB once") : wrong on size by ~6x**, because it priced only tracked
  content ("At ~50 MB of tracked files each") and sampled one root listing without opening
  `artifacts/models/hgb`. Its ranking table therefore put worktrees 8th of 9. Its risk warning
  ("can break deployed execution sources") is right for removal and is why this report recommends
  un-smudging instead.
- **agent-governance F6 ("on the order of 10 GB - unmeasured, inferred"): same error, honestly
  labelled.** Its 11.3 GB free figure is accurate for its timestamp (section 7).
- The critic's two spot checks were both right: `weather-archive-dpapi-20260905` is one of the 23
  pointer worktrees, `wt-09-69a` is one of the 175 smudged.
- Nobody had sized worktree-local `data/`: 3 of 3 sampled are tiny (one empty station directory;
  732 KiB of test JSON; one empty `backtest/`). Not a lever.

## 7. Free-space reconciliation

| Source | Value | Timestamp | Instrument / unit |
| --- | --- | --- | --- |
| storage-capacity (trail) | 14.2 | 09-18 04:50, daily minimum before tiering | `data/alerts/disk_free_trail.jsonl`, written by `status.ps1:1361`; GiB |
| Lead auditor | 21 | 09-18 21:20 | `MORNING_BRIEFING.md`, same `$freeDiskGB`; GiB labelled "GB" |
| storage-capacity (trail) | 18.5 | 09-18 22:05, last sample it saw | same |
| agent-governance | 11.3 | briefing as read before its 02:36 09-19 write; by burn rate ~01:50-02:50 | same |

`scripts/ops/status.ps1:1298`: `$freeDiskGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)`.
PowerShell `1GB` is 2^30, so every figure is GiB regardless of the "GB" label; there is no unit
conflict. The overnight burn measured by storage-capacity is 10.3-12.8 GiB between 22:05 and 04:50
(1.5-1.9 GiB/h). 18.5 -> 11.3 takes 3.8-4.8 h at that rate, which lands at ~02:00-02:50, exactly
when agent-governance read it. Continuing to 04:50 gives **~6-8 GiB** at the 09-19 trough,
inside storage-capacity's 5.7-8.2 GiB projection. The three figures are mutually consistent
samples of one sawtooth; the lead's "~4 days" is the evening-phase reading and overstates headroom
(storage-capacity-1 stands). The only oddity is 21 -> 18.5 in 45 minutes (3.3 GiB/h), faster than
the overnight mean; unexplained steps of that size are already noted in storage-capacity section 3.
I did not read the trail or the briefing myself (production `data/` was outside this brief), so the
actual 09-19 04:50 sample is unverified.

## 8. Findings

### gap-disk-reclaim-tiebreak-1 (critical, live_state, new) - 62.0 GiB of duplicate model pickles in 175 of 200 linked worktrees
Evidence: `git worktree list`; one `ls -la <wt>/artifacts/models/hgb | head -n 1` per worktree
(175 x `total 371560`, 23 x pointer, 2 x no directory); full listings of `C:/tmp/wt-09-69a` and
`scratch/w/recovery-end-to-end-20260917` (103,734,643-byte `f_pooled`, link count 1);
`.gitattributes:9`. Falsify by listing any worktree not named in the pointer/none lists above and
finding `total 38`. No project document records this cost (`item-325` has one unrelated
"worktree" hit at line 1292; `docs/operations` has one tangential mention at
`ESTABLISHED_FINDINGS.md:2391`).

### gap-disk-reclaim-tiebreak-2 (high, verified_in_code + live_state, new) - Worktrees still smudge by default; the recovery effort consumed ~9.9 GiB itself
`docs/git-workflow.md:133` has no skip-smudge; grep of `scripts/` for `GIT_LFS_SKIP_SMUDGE` and for
`worktree add|remove|prune` returns nothing, so no tool creates, shrinks or retires worktrees.
`scratch/w/capacity-150gb-20260915`, `-20260916-a2`, `-20260917-a1`, `recovery-end-to-end-20260917`
and `overnight-audit-20260918` are all `total 371560`. 28 smudged worktrees are named
archive/capacity/reclaim/storage/recovery (19 under `Desktop/github`, 9 under `scratch/w`):
28 x 362.85 MiB = 9.9 GiB.

### gap-disk-reclaim-tiebreak-3 (medium, verified_in_code, new framing) - The cheap lever needs an explicit owner exception to three rules, and no script exists to do it safely
`git-workflow.md:145-146` (do not touch another task's worktree), `HOST_LOAD_POLICY.md:326-333`
(bulk file ops only 00:30-09:00 and only with >= 50 GB free), `OPERATIONS_AGENT_ROLE.md:121`
(confirm bulk deletion). An ad-hoc loop over `git worktree list` that does not exclude line 1 would
replace the production serving pickles with pointers.

### gap-disk-reclaim-tiebreak-4 (medium, live_state, known_open) - About a third of unmerged worktree branches are local-only on a host with no mirror
5 of 15 sampled unmerged worktree branch tips are on no remote (listed in section 4). All 17
non-trivial detached HEADs are on a remote; master equals origin/master. Uncommitted state is
unverified everywhere; `weather-portable-execution-host-20260827` shows post-checkout edits.

### gap-disk-reclaim-tiebreak-5 (medium, doc_claimed, known_open) - Shadow storage can absorb delete-type reclaim; the "10+ GiB from VSS" hope is unsupported
`item-325:34-37`. Only recorded measurement: 1,541,144,576 bytes used on 09-13 02:16.

### gap-disk-reclaim-tiebreak-6 (medium, verified_in_code, known_open) - The long-CSV flag is real, fail-safe and roll-free
Trace: `config/storage_pressure.json:4` -> `storage_pressure_policy.py:54-88` ->
`market_microstructure_capture.py:761-766` -> `:837`. `AGENTS.md:103-104` classifies `config/` as
roll-free, which closes storage-capacity's open question. The ~13 GiB/day figure is doc_claimed.

### gap-disk-reclaim-tiebreak-7 (info, live_state) - Auditor tie-break
recent-work right (-12%); storage-capacity-9 and agent-governance F6 low by ~6x (tracked content
only). Section 6.

### gap-disk-reclaim-tiebreak-8 (info, verified_in_code + doc) - Free-space figures are one instrument in GiB and are mutually consistent
Section 7.

### gap-disk-reclaim-tiebreak-9 (info, live_state) - `C:/tmp` and worktree-local `data/` are not levers; the PIT corpus in `C:/tmp` is hard-linked and frozen
`ls -la C:/tmp/pit-refetch-2026-08-10` shows link count 2 on every corpus file;
`pit-transfer-20260902/transfer-manifest.json` declares 171,401,140 bytes.

### gap-disk-reclaim-tiebreak-10 (info, live_state) - A fix branch advanced during the no-changes audit
`claude/audit-rollfree-fixes-20260919` -> 0b6d4f288 (09-19 03:05), worktree
`C:/tmp/wt-audit-rollfree-20260919`, 2 files. Topic branch only; master untouched. Reported so the
owner can confirm it was authorised.

## 9. Strengths

- Pointer-state checkouts are already a supported condition: the registry treats a canonical LFS v1
  pointer as the artifact identity and documents offline restore
  (`docs/operations/artifact-storage-policy.md:78-83,96-100`). That is what makes lever 1 reversible.
- The worktree-removal guard in `docs/git-workflow.md:271-305` is careful (clean status, ignored
  inventory, ancestor-of-origin/master, no forced branch delete), and
  `branch-retirement-2026-08-11.md:1-11,50-60` shows the project checking `--not --remotes` before
  retiring anything.
- Push discipline on the things that matter most: master has no unpushed commits and every detached
  worktree commit is reachable from an `origin/` branch.
- `src/weather/market/storage_pressure_policy.py:30-88` is a well-built fail-safe switch.
- Some sessions already avoid duplication: 23 skip-smudge worktrees, and the PIT corpus uses hard
  links rather than copies.

## 10. Not covered / limits

- Uncommitted, untracked and ignored content in any worktree (`git status` not whitelisted).
- Task Scheduler actions that point into worktree paths (off limits).
- `.git/config` / global git config (the smudge default is inferred from 175 outcomes, not read).
- Whether every LFS object is present in the local `.git/lfs` store (inferred from offline smudges
  on 09-17/09-18; `.git/` is off limits).
- Actual sizes of tracked checkouts, caches, `clob_v2_venv`, `.git`, and anything under production
  `data/` or `scratch/` other than `scratch/w`.
- Remote-tracking refs were not refreshed (no network); "pushed" means "as of the last fetch".
- The 09-19 04:50 trough sample.

## 11. Open questions for the owner

1. Will you authorise a one-time, scripted un-smudge of linked worktrees (exclusions as in section 4)?
2. Which scheduled tasks still have an action path inside a worktree?
3. Should `git-workflow.md` section 2 and the agent launch environments set `GIT_LFS_SKIP_SMUDGE=1`
   for all non-production checkouts?
4. Was `claude/audit-rollfree-fixes-20260919` authorised?
