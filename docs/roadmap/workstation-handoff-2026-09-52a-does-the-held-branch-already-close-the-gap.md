# Workstation handoff 2026-09-52a — does the held branch already close the release-bootstrap gap?

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.

## 1. The gap, now precisely characterised

`-09-51a` established that **current master has no supported path from an empty release store to the
first base retrain.** Three reinforcing causes, of which production verified 1 and 3 directly in the
code:

1. The nightly bootstrap builds a **production-capable** release; `load_parent_contract` **raises**
   unless the parent is `RESEARCH_ONLY_CANDIDATE_MODE`.
2. The **research-only** bootstrap requires complete corpus lineage **or** an existing verified
   release. Production has neither.
3. **`base_retrain` runs before candidate release construction** — plan step at
   `nightly_retrain.py:1327`, release construction only at `:2588`.

**This is a code contradiction, not a policy question.** `-09-51a` also settled that creating a
research parent freezes **research scaffolding only** — it does not commit the deferred production
Release #1 nor start its confirmation window. **Do not reopen the deferral; it is not in the way.**

The downstream mechanism is already proven to work once a parent exists. **The gap is confined to
creating one.**

## 2. Why you are auditing and not building

The branch **`codex/workstation-research-2026-07-22`** (3 commits, tip `423eaa59`) already rewrites
**exactly** the files this gap lives in:

| File | Lines changed vs master |
| --- | ---: |
| `src/weather/operations/release_candidate_contract.py` | **+332** |
| `src/weather/operations/nightly_retrain.py` | **+285** |
| `src/weather/operations/release_bootstrap.py` | **+144** |
| plus `test_release_bootstrap.py`, `test_release_lifecycle.py`, `test_nightly_retrain.py` | — |

**It has been held since 2026-07-22 under "do not merge pre-lock".** Release #1 was then deferred
indefinitely, so that hold silently became permanent — **a temporary measure whose justification
expired**, which is a shape this project has been bitten by twice.

> **Writing a fresh fix without reading 720 lines of existing work on the same three files would be
> waste at best and a merge conflict at worst.** Answer whether it already does the job first.

## 3. P0 — does it close the gap? Answer per cause, not in general

For **each** of the three causes in §1, state one of: **closes it**, **partially closes it**, or
**does not address it** — with the specific code that does or does not do so. A verdict of "it
rewrites that file" is not an answer.

Then the composite question: **on that branch, does a supported path exist from an empty release
store to a `base_retrain` that accepts its parent?** Prove it the way `-09-51a` did — **a
conditional rehearsal against a SCRATCH releases root**, never the real store.

## 4. P1 — what would landing it cost, and what else rides along?

The branch was held for a reason, and that reason must be re-examined rather than assumed dead.

- **What else does it change** beyond these three files? `release_artifacts.py`,
  `release_contract.py`, `release_serving.py` and `release_manifest.py` are all in its diff. **Does
  any of it alter serving, promotion, or an existing gate?** Anything touching the serving path is
  the thing to flag loudest.
- **Roll verdict for the branch** via `scripts\ops\roll_verdict.ps1` — never hand-derived. Expect
  roll-sensitive; say which closures and which files.
- **Does it still merge?** It is three weeks behind a fast-moving master that has since absorbed
  `-09-43a`'s six missions. Report conflicts concretely.
- **Was the original hold about something real that still applies?** If you cannot determine what
  "pre-lock" was protecting, **say so** rather than concluding it is safe.

## 5. What would falsify this mission

- **It closes the gap cleanly.** Then the fix has existed for three weeks and the finding is that
  holding it cost us the retrain. Say that plainly — **it is a process finding, not a rebuke.**
- **It does not address the gap at all.** Then it is unrelated work and a fresh fix is needed;
  specify precisely what that fix must do, per cause.
- **It closes the gap but drags in serving or promotion changes we do not want.** The most likely
  outcome, and the most useful: identify the **minimal** subset that closes the gap and what would
  have to be extracted from it.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Do not merge this branch, do not open a PR, and do not push
to it.** You are reading and rehearsing, not landing.

- **Scratch releases root only.** Never write `artifacts/releases/`, never create or modify
  `current_release.json`, never activate or promote. Production's store must still be empty when you
  finish — **verify and state that.**
- Nothing under production `data/`. No order, no live trading, no chain run, no settlement, no loop
  restart. Call no weather-provider endpoint. **Never weaken the serving floor.**
- Fitting is authorized **only** if a rehearsal step genuinely requires it, to a scratch root, and
  you say so explicitly.

## 7. Branch and report

- Branch: `codex/workstation-audit-the-held-release-branch-2026-09-52a`
- Report: `docs/roadmap/agent-report-2026-08-15-workstation-held-release-branch-audit.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never hand-derived.**
**Commit and push whenever you finish, at whatever hour.**
