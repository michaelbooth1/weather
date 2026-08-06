# Workstation handoff `-09-15a` — map the held backlog onto the 97 blockers

Written 2026-08-05 by the operations master agent on the production host. Read this on
`origin/master` and execute it.

**This is a large mission and it is not time-sensitive.** Prefer thoroughness over speed.

## The problem

**There are 39 unmerged `origin/codex/*` branches.** Several plausibly clear blockers that the new
retrain preflight now refuses on — and **nobody has mapped which branch clears which blocker.**

`-09-12a` (`b7ee084c`, held) built the all-market base retrain lane and its preflight correctly
returns **BLOCK with 97 blockers across six gates**:

```text
forecast_archive_coverage        36    season ends June 30, outside all late-July dates
point_in_time_forecast_binding   24    no PIT coverage cells, no PIT-bound corpus
class_support                    12    no contiguous native serving support declaration
candidate_specific_calibration   12    no blocked-OOF plan; June 7 weights preserved
artifact_regime_boundary         12    no corpus carrying one exact artifact regime
train_serve_feature_parity        1    retained report BLOCK, 220 findings
```

Meanwhile the backlog contains, among others, `scope-forecast-archive-extension-2026-08-28a`,
`size-forecast-lookahead-2026-08-29a`, `build-pit-forecast-corpus-2026-08-31a`,
`spec-contract-repair-2026-08-21a`, `make-the-first-retrain-count-2026-08-25a` and
`build-base-retrain-step-2026-08-26a`. **Some of that is probably the repair for gates 1 and 2. Some
is probably superseded by `-09-12a`. We do not know which.**

**The cost of not knowing is real and already realised.** `-09-12a` was cut at 23:02 and the maker
binding fix landed at 01:15, touching the same `schema_registry_recent_data.py`. `-09-12a` no longer
merges clean. **With 39 branches, stale ancestry is not a risk, it is a certainty.** Work is rotting
in place.

## What to produce

### 1. Classify every unmerged branch

For each of the 39, exactly one verdict:

- **MERGE** — carries code we want; say which blocker(s) it clears
- **SUPERSEDED** — its content is already in master or in a newer held branch; name the successor
- **REPORT-ONLY** — research whose report already landed on master; the branch itself is not needed
- **NEVER** — see the named exclusions below
- **UNKNOWN** — say so rather than guessing; an honest unknown is fine

State each branch's **base commit, whether it still merges clean into current master**, and if not,
**what changed underneath it.**

### 2. Map MERGE branches onto the 97 blockers

For each of the six gates, say which held branch (if any) clears it, wholly or partly, and on what
evidence. **Then name the gates that have NO branch** — that is the genuinely unbuilt work and it is
the most valuable output of this mission.

Do not claim a branch clears a gate because its title suggests it. Check.

### 3. A safe merge order

Produce an ordered plan accounting for:

- **roll-sensitivity per branch**, by import closure — not the `SOURCE_PATTERNS` glob. Roll-sensitive
  branches merge only in a 01:00–04:00 quiet window and roll all three capture loops.
- **stale ancestry** — which branches need refreshing before they can merge, and in what order so
  refreshing one does not invalidate the next.
- **conflicts between held branches**, found now rather than at 02:00.
- **how many quiet windows this realistically takes.** One night cannot absorb the roll-sensitive
  set; say how to split it.

Already known, use it: `-09-11a` merges clean and is the MM critical path; `-09-12a` needs refreshing;
`-09-14a` has no source conflict with either, only documentation overlap with `-09-11a`.

### 4. What to delete

Branches classified SUPERSEDED or REPORT-ONLY are noise that makes every future audit harder.
**Recommend deletions — do not perform them.** Deleting a remote branch is the operator's call.

## Named exclusions — do not classify these as MERGE

- **`origin/codex/live-canary-bot`** — research only. **Never merge without a new explicit operator
  instruction and a fresh audit.** Not this mission's call, not any mission's call.
- **`origin/codex/workstation-research-2026-07-22`** — rewrites the release/PIT path. The release #1
  build runs tonight. **Do not propose merging it before the build has completed and been reviewed.**
- **`origin/codex/workstation-consolidate-merge-queue-2026-09-01a`** — a 4-commit stack, 16
  roll-sensitive files, whose last commit arms an automatic deleter that runs at 00:05 daily. It may
  well be MERGE, but it needs its own slot and its own analysis; do not fold it into a general
  ordering without saying so.

## The lesson this mission exists to apply

`-09-01a` did this once and found the real defect was **semantic, not textual**: the base-retrain
preflight's forecast coverage was *self-declared* rather than cryptographically bound to the PIT
corpus. Zero textual conflicts; a genuine defect at the seam. Its own conclusion:

> **"Wiring two independently-specified contracts together is where the real defect lives."**
> Neither branch was wrong on its own terms.

**So do not stop at `git merge` succeeding.** Where two held branches both touch a contract, say what
happens when they are wired together. That is where this mission earns its keep.

## Constraints

**Do not merge anything. Do not delete any branch. Do not open a PR.** This mission produces a plan.

**Do not touch the release or PIT path.** The release #1 build runs on the production host tonight.

**Do not weaken the trusted observed-high floor or relax the promotion gate.**

**Reservation:** re-based 2026-08-04, nothing reserved today, window armed but undated.
`docs/operations/reserved-confirmation-window.md` is the single source of truth; re-read it.

**Network:** `git fetch` and `git push` only. No provider calls.

Push `codex/workstation-map-the-held-backlog-2026-09-15a`. Report to
`docs/roadmap/agent-report-2026-08-05-workstation-map-the-held-backlog.md`.

## How to disagree

If a branch cannot be classified without running its tests, say so and leave it UNKNOWN rather than
guessing — a confident wrong verdict here causes a bad merge at 02:00 on a production host running a
14-day capture streak. If the honest answer is that most of the backlog is dead and should be deleted,
say that plainly; a shorter true list is worth more than a long hopeful one.
