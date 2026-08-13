# Workstation handoff 2026-09-76a — rebuild the runtime from the identity, not from a commit

Written 2026-08-11 by the production agent. Read on `origin/master` and execute.
**No α, no realized outcome, no candidate, no market comparison, no C endpoint.**
Direct continuation of `-09-75a` (merged `7b2ece24`). Canon:
`docs/operations/REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md`.

## 1. Where we are

`-09-75a` replayed the 368-event decision stratum against **recorded** output and got **114 / 358
matches (31.84%)**, failing in every market and both windows. My toronto source-switch hypothesis
died cleanly: the three bound `M4` rows fail with **identical sources and zero feature differences**.

The defect is the **binding**. Across 10 runtime commits the stratum carries **7 code hashes, 15
artifact hashes and 54 identities**, and **all 358** captured identities differ from their own
commit tree. Every row records model version `v0.5.10`, so **the artifact changed fifteen times
under one version label.** 158 of the 244 failures have zero feature differences — same inputs,
different environment.

**A git commit does not pin what ran, so checking one out cannot reconstruct it.** That is why this
mission stops using commits.

## 2. The mission

`src/weather/model/model_identity.py` records **per-file fingerprints** — `code_files` and
`artifact_files` — not just a combined hash. And `artifacts/` is **tracked**: 108 files, 30 commits
touching it in the window. So the runtime should be rebuildable **file by file from git blobs.**

> **Resolve every captured file fingerprint to a git blob, assemble a synthetic tree per identity,
> re-run the replay, and report the new match rate against the 31.84% baseline.**

### 2a. Resolve the fingerprints

For the **358** bound decision rows (and, if cheap, the 8 identity-only rows, which this method may
rescue — they have identities even though they have no usable commit):

- Search **all reachable objects across every ref, including the 27 unmerged remote branches**, for
  a blob matching each captured file fingerprint. Confirm first that the captured fingerprint is
  comparable to a git blob hash; if it is a content hash of a different form, state the mapping you
  used and prove it on a file you can verify both ways.
- **The 27 unmerged branches are read-only here.** Do not merge, rebase, delete, or write to any of
  them. The operator's standing instruction is that no branch is deleted.
- Report, per identity: files resolved, files unresolved, and **which** files fail to resolve.
  `-09-75a` already found one row where 3 of 11 hashes occur in no reachable commit, so expect
  partial coverage and **measure it rather than working around it**.

### 2b. Rebuild and re-run

Assemble a disposable tree per resolvable identity, run the same replay `-09-75a` ran, at the same
`1e-12` L1 tolerance, on the same rows, and report:

| Report | Against |
| --- | --- |
| match rate under identity binding | the **31.84%** commit-binding baseline |
| match rate on **fully** resolved identities | separately from partially resolved |
| residual L1 distribution | `-09-75a`'s median 0.0154 / p90 0.0424 / max 0.7728 |
| rows rescued that commit binding could not replay at all | the 10 unbound rows |

**Print the resolved `__file__` of every model, calibration and feature module** and confirm the
synthetic tree, not production, is what loaded. A worktree that silently imports production modules
has bitten us.

### 2c. Test the three-way-drift diagnosis

`model_identity.py:100` fingerprints code by reading `SRC_ROOT` **from disk at capture time**, while
the recorded `git_commit` is `HEAD`. Our roll rules make drift expected: a commit touching no loaded
module is roll-free, so `HEAD` advances while the running process keeps its old code.

**If that is right, identity binding will fix the disk-state mismatch but NOT any case where the
running process held code older than the disk.** So: does a residual failure class survive identity
binding? If so, characterise it — does it correlate with proximity to a roll, or to a commit landing
mid-day? **Do not assume my chain; test it and say where it breaks.**

### 2d. If binding is fixed, say what it unblocks — and stop there

State the restored effective N for the decision stratum and for whole B (the commit-binding ceiling
was **16,143 / 28,254 = 57.14%**). **Do not resume the `-09-74a` ceiling mission, do not compute
candidate probabilities, and do not allocate α.** That sequencing is the operator's.

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED** and must not be reassigned.
- **No candidate anywhere** — no recovery rule, no candidate probabilities, no displacement, no
  ceiling. This mission replays the **incumbent** on captured inputs only.
- **No realized outcome.** Replayed-vs-recorded is not an outcome look; either-vs-settlement is.
  Emit `realized_band_read: false`.
- **B only. No C endpoint.** Never pool across `2026-07-31` (anchor `b77cfbed`).
- **DO NOT DELETE OR MODIFY ANY BRANCH.** Read-only access to refs, full stop.
- **Change nothing** in the working tree: not model, calibration, floor, producer, collection,
  scoring, replay or identity code. **In particular, do not "fix" `model_identity.py`** — if you
  find the right fix, describe it in the report and leave the code alone.
- Nothing under production `data/`. **Never weaken the serving floor** (`1.6639 → 1.4980`).
- Historical runtimes go in **disposable** trees under `scratch/`, as `-09-74a`/`-09-75a` did.
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, no promotion, activation,
  release or trading.

## 4. What would close this

- **Identity binding restores reproduction** → replay is trustworthy again on a stated N, the
  `-09-73a` pre-registration becomes executable, and we know the real size of any decision we can
  run. **This is the outcome that unblocks the whole thread.**
- **It does not** → what we served cannot be rebuilt from what we recorded. That is a
  campaign-level fact about every replay number we hold, it belongs in canon in plain words, and the
  right next move is to fix *capture* going forward rather than to keep mining the past.
- **It restores some and not others** → give the recoverable share and the shape of the residual.
  That is the most likely answer and it is a perfectly good one.

**Whatever the result, this is about reproducibility, not about the model being right or wrong.**

## 5. Environment, branch and report

The repo venv on that host points at a removed Python 3.11 — but note `-09-75a` found that
historical inference needs the repository's **existing 3.11** environment, because the preserved
NumPy/scikit-learn binaries are CPython 3.11 builds. Use what `-09-75a` used and say so.
**Install nothing.**

- Branch: `codex/workstation-rebuild-the-runtime-from-the-identity-2026-09-76a`
- Report: `docs/roadmap/agent-report-2026-08-31-workstation-identity-binding.md`
- Extend `-09-75a`'s harness; commit it and a versioned seed alongside the artifacts.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
