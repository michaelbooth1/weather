# Implementation log — 2026-09-19 02:20 → ~04:00 America/Toronto

Owner instruction (02:20): *"Once the audit finishes, implement all high priority findings now. You have full
authorization to make any change needed."*

**Bottom line: three verified fixes are written, tested and pushed on two branches. Nothing has been adopted into
production**, because this session's permission classifier blocks production-deploy steps (even the read-only
`roll_verdict.ps1`) and modification of other agents' worktrees. Adoption is two commands, below. **No file on `master`
or in the production working tree was modified.**

## 1. Done — written, tested, pushed

### Branch `claude/audit-rollfree-fixes-20260919` (ps1 + tests only → roll-free by the project's rule)
Worktree `C:\tmp\wt-audit-rollfree-20260919` (created with `GIT_LFS_SKIP_SMUDGE=1`; ~50 MB, not 413 MB).

| Commit | Finding | What | Verification |
| --- | --- | --- | --- |
| `0b6d4f288` | `ps-ops-1` HIGH | **Memory guard kill path was inert for 27 days.** `Stop-VerifiedProcessTree` assigned to `$pid` = PowerShell's constant `$PID`. Renamed; added an explicit refusal to terminate the guard itself. | New **executing** test (real function, synthetic rows) asserts children-first kills `[4300, 4200, 4100]`; new ratchet over every `scripts/ops/*.ps1` for assignment to a read-only automatic variable (runs on Linux CI). **Both fail on the old script** (`stopped == []`) **and pass on the fix.** Module: 9 passed. Runtime proof of the bug: `memory_commit_guard.log` 2026-09-10T21:29. |
| `e3c957e4e` | `storage-capacity-1`, `live-ops-state-1` CRITICAL | **Disk headroom measured at the daily low**, low-to-low slope, days until the *low* reaches zero; refuses the slope when the prior day is thinly sampled; alarm is independent of the 24h/48h "burst" downgrade; `daily_low` added to status JSON and console. | 3 new tests (2 executing, built from the real 09-17/18 trough shape: 25.9 → 14.2 GB ⇒ 1.2 days) + the existing burst test: 4 passed. |
| `e3c957e4e` | new (§7 of the report) | **Status-test fixture no longer copies the repo per test.** Bare origin borrows objects via git alternates; ref seeded directly. | Measured real disk per fixture test **550.8 → 56.7 MiB**, 19 s → 5.2 s; test passes. |

Effect on adoption: the guard task runs `scripts\ops\memory_commit_guard.ps1` from the main repo with **no hash pin**, so
the fix is live within a minute of merge. **`status.ps1` is different:** `WeatherHostHealthWatchdog` runs hash-pinned
copies of `health_watchdog.ps1` and `status.ps1` from the detached worktree `weather-watchdog-deployed-aa99048`, so the
*briefing* keeps the old arithmetic until the watchdog is redeployed. Manual `status.ps1` runs get the fix at once.

Behaviour change to expect: once merged, the guard will **really** terminate agent tool trees running pytest /
compileall / inline python / recursive `data\` scans outside 00:30–09:00, trees ≥ 8 GB, and the 92%-commit offender. That
is the documented policy; it simply has not been happening.

### Branch `claude/audit-python-fixes-20260919` (Python → needs the roll verdict and the suite-gated path)
Worktree `C:\tmp\wt-audit-python-20260919`.

| Commit | Finding | What | Verification |
| --- | --- | --- | --- |
| `a20dc0c2d` | `storage-capacity-2` CRITICAL→HIGH | **Projection tiering no longer deadlocks at low disk.** Precondition sized to a pessimistic ¼ of the source instead of the whole source; the writer re-checks the floor every 64 MiB and aborts cleanly (temp removed, source untouched); a candidate blocked at its turn is retried once after later verified deletes free space. Verify-before-delete, quiescence re-checks and cleanup preflight unchanged. `clob_raw_tape_tiering` (canonical evidence) deliberately untouched. | 3 new tests; 9 passed here + 46 across neighbouring tiering modules, **run against the worktree's source** (`module.__file__` checked). |

**Not run:** the full `test_status_script.py` module (see report §7 — it is the module that ate the disk) and the full
bounded suite (cannot start below 50 GiB free; forbidden as a direct run at every hour).

## 2. Blocked by this session's permissions — needs you

| Action | Blocked as | Why it matters |
| --- | --- | --- |
| `scripts\ops\roll_verdict.ps1 -Branch …` and `quiet_window_merge.ps1` | Production Deploy | Adoption of both branches |
| Replacing duplicate pickles in 175 linked worktrees with LFS pointers (~50–60 GiB) | Modify Shared Resources | **The single largest lever on the disk emergency**; reopens the 50 GiB gate for everything else. Script, exclusions and rule waivers: `ready-to-run/README.md` |

### Adoption runbook (owner or an attended ops session)
```powershell
# 1. Roll-free branch: any hour outside 12:00-18:00 (the tool decides; do not derive it by hand)
.\scripts\ops\roll_verdict.ps1 -Branch origin/claude/audit-rollfree-fixes-20260919
.\scripts\ops\quiet_window_merge.ps1 -Branch origin/claude/audit-rollfree-fixes-20260919 -ExpectedTip e3c957e4e91ca4121fe73845c4e9b2c58496c1bc

# 2. Python branch: verdict first; if ROLL-SENSITIVE it needs 01:00-04:00 and the suite, i.e. >= 50 GiB free -> do lever 1 first
.\scripts\ops\roll_verdict.ps1 -Branch origin/claude/audit-python-fixes-20260919   # tip a20dc0c2d3ee13a9293c35f1ce2778ab57d1be02
```

## 3. Deliberately NOT done, with the reason

| Finding | Disposition |
| --- | --- |
| `storage-capacity-6` long-CSV flag (~13 GiB of daily low) | **Staged, not flipped.** `config/AGENTS.md:20-22`: checked-in default must preserve capture; activation is a separate, operator-approved production operation. See `ready-to-run/README.md`. |
| `ops-chain-3` / `data-integrity-2` finalize idempotency | **Not safe unattended.** Dropping `finalized_at` from the label hash changes the hash of every historical ledger row; chain verification recomputes it. Needs a versioned hash and the full suite. Design it on the workstation. |
| `ops-chain-1/2` chain re-admission, step reorder, threshold alignment | Behaviour change to the settlement machinery that I could not qualify tonight (suite gate closed). Smallest correct change per the gap auditor: bounded admission wait + WU look-back range. |
| `time-units-1` sign-blind band parser | **A tested fix already exists** (09-05, third in the stalled queue). Re-implementing would create a fourth conflicting copy. Land the existing one before November. |
| Snapshot hang-detection fix | **Already exists**, local-only and unmerged for 36 days (`edcdaeab5`). Push and land it. |
| `tests-ci-1` fifth host-fixture module (`test_storage_recovery_night_wrapper.py`) | Belongs on the PR 61 lineage, which has moved; needs that branch's owner. Flagged so PR 61 is not re-qualified only to fail again. |
| Settlement backfill of the 10 dates | Operational, ~22 min heavy each under the lease, and the WU restore writes to a nearly full disk. **Disk first**, then `settlement_backfill_one.ps1` per date; 09-16 needs finalize only. 09-04 has already left the 14-day alarm. |
| `storage-capacity-3` capture disk-full handling | Inside the capture import closure: highest-risk roll. Not an unattended 3 a.m. change. |
| `market-maker-1` execution-tape reader / markout study | A feature plus a research mission; belongs on the workstation with a pre-registered kill threshold. |
| `config-artifacts-1` resolution-source validator rule | Measured agreement is 1,052/1,053, so downgraded; a validator that *blocks* the 4×-daily config refresh would be worse than the defect. Should be warning-level; not written tonight. |
| Docs reconciliation (STATE_OF_PLAY, item 325, the 09-06 live test, tasks running from worktrees) | STATE_OF_PLAY is the owner's current-decision file and the facts to record include the 09-06 geoblock episode. That wording is the owner's to approve. Every fact needed is in the report §2C, §6.1, §6.5. |
| Strategy (kill criteria, hurdle, G1 date), 50 GiB floor as a parameter, second disk, `Desktop\.env.txt`, eligibility | Owner decisions. |

## 4. Host safety record for this session
- Audit fan-out: read-only, ≤ 6 agents, 124 agents total, 0 errors. Commit 51–60%, free RAM 7.0–8.3 GB throughout; no
  guard warning; no capture admission failure observed.
- **One incident, mine:** two interrupted test runs consumed ~13.5 GiB of `%TEMP%`; detected by my monitor, cleaned
  (18.66 GiB freed). Details in the report §7.
- Nothing of mine holds the workload lease; 04:45–06:45 is clear for the scheduled tiering jobs.
- Left behind on purpose: two pointer-only worktrees under `C:\tmp\wt-audit-*` (~50 MB each) and their two branches on
  origin. Test temp directories were removed.

## 5. 2026-09-19 09:35-10:05 — owner approved the three staged actions

Owner (attended): *"Replace the duplicate pickles in the worktree with Git LFS pointer file. I approve the decision.
Set write_order_books_long_csv to false. Finally adopt the two branches."*

| Action | Outcome |
| --- | --- |
| **Pointerize worktree pickles** | **DONE. C: 36.9 -> 89.2 GiB free (+52.3 GiB).** 152 worktrees, 3,952 files, 53.85 GiB logical; 28 excluded (2 locked + every worktree an enabled task runs from); 0 skipped dirty; **0 anomalies, 0 errors**. Production pickles untouched (29,230,281 bytes verified). Sampled worktrees read git-clean at 116 KiB. Capture: ON_TRACK, 0.0 min max gap. Manifest: `ready-to-run/manifest.jsonl`; log: `ready-to-run/run.log`. |
| Two defects found by the one-worktree trial, fixed before the full run | (1) msys `grep` **aborted (core dump)** inside the exclusion check, which read as "not excluded" — exclusions now load in pure bash and the script aborts on an empty list. (2) Git treats a changed `st_size` as modified without comparing content, so pointerized files showed ` M` although the blob was identical — the script now runs `git add -- artifacts/models/hgb` (stages nothing; refreshes the cached stat). Round trip proven on `C:/tmp/wt-09-69a`: pointerize -> clean -> `git lfs checkout` (2 s) -> clean. |
| **`write_order_books_long_csv=false`** | **Committed and pushed, NOT yet live**: `claude/activate-long-csv-off-20260919` @ `3dbe8720f`. Includes the dated decision record in item 325 and one test fix: `test_capture_event_books_writes_..._by_default` read the *real* `config/storage_pressure.json`, so the flip would have broken it; it now pins a writing policy. That test edit is **not yet executed** (no Python outside the heavy window while the settlement chain held the lease); `3_adopt_audit_branches.ps1` runs it before merging that branch. |
| **Adopt the branches** | **NOT possible until 00:30.** `roll_verdict.ps1`: both audit branches **ROLL-FREE** (the tiering module is outside every loop closure). `quiet_window_merge.ps1 -DryRun` at 09:55: *"heavy workload 'quiet_window_merge' is outside the 00:30-09:00 window"* — the host lease refuses every other hour regardless of `-Force` or verdict. No merge queue is armed and `merge_queue_driver.ps1` accepts only `codex/` branch names. Ready to run in the window: `ready-to-run/3_adopt_audit_branches.ps1`. Note: `quiet_window_merge.ps1` needs an explicit `-RepoRoot` when launched with `powershell -File` (its `$PSScriptRoot` default was empty). |

Observed in passing: the 09:30 settlement chain **was admitted today** (pythonw started 09:30:02, holds `heavy_workload.lock`);
commit peaked at 75.4% during it and fell to 67.2% by 10:05.
