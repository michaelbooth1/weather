# Workstation handoff 2026-08-25a — make the first retrain count

Run this now. **Diagnosis and specification only: no repair, no retrain, no candidate, no artifact,
no scoring, no fresh dates.** `-08-16a` remains queued for 2026-08-05 04:30.

## Why this is urgent rather than tidy

`-08-24a` established that the cool bias is conditional, is the main upstream mechanism, and comes
from **a stale June prior plus insufficient upper-class support**. Verified on the production host:
every per-market base HGB dates from **2026-06-10 → 06-13**, Toronto's from **2026-06-13**. We serve
August from mid-June models because the learning loop has been dead since then.

Release #1 restarts that loop. But if it restarts into a pipeline that is still broken, we spend the
release and get a fresh model built on stale or wrong inputs. **The first retrain after the pointer
exists is the highest-leverage single event in this project's near future, and it should not be
improvised.**

## 1. Does the nightly path even refresh base artifacts?

The most important question here, and I do not know the answer.

`nightly_retrain` builds *candidates*. Do the per-market base HGBs — `feature_model_hgb*.pkl`, the
artifacts that actually produce `replayed_p` — get refreshed by that path at all, or only by a
separate training route that nothing currently schedules?

**If the nightly path does not refresh base artifacts, release #1 alone does not fix the staleness**,
and we would be one unpleasant surprise away from believing it had. Trace it in code and answer
plainly.

## 2. The June-13 freeze — one event or three?

Marine features stop **2026-06-13**. The last Toronto base artifact is **2026-06-13**. WU
availability broke **2026-06-30**. That is either a coincidence or one freeze with three symptoms.

Establish which, read-only. If a single pipeline or scheduled job stopped, name it — because whatever
stopped will still be stopped when the loop restarts.

Then go further: **what else froze in June that we have not noticed?** Inventory the artifacts,
sidecars, caches, and derived inputs the training path consumes, with their last-refresh dates. I
want the full list of stale inputs, not just the three we stumbled onto.

## 3. Characterize the upper-class support deficiency

We know the prior is stale. We have not characterized the *class-support* half of the cause.

- Which warm classes are under-supported, by how much, and in which markets?
- Is it a seasonal artifact — June training data simply lacking late-July and August warm days — or a
  structural truncation that a refresh would not fix?
- **Would refreshing the prior on current data alone correct it, or does it additionally need
  reweighting, support extension, or a different class definition?**

That distinction sets the retrain's design, and getting it wrong wastes the first run.

## 4. Specify what the first retrain should do differently

Given 1–3, write the specification: what the first post-release retrain must consume, what it must
refresh, what must be verified before it runs, and what would tell us afterwards that it worked.

Include the failure modes. If a stale input would silently poison it, name the pre-flight check that
catches it.

## What I want back

1. A plain yes or no on whether the nightly path refreshes base artifacts, with the code trace.
2. One event or three, with the named pipeline if it is one.
3. The full stale-input inventory with last-refresh dates.
4. The class-support characterization, and whether a refresh alone fixes it.
5. The first-retrain specification, including pre-flight checks.
6. Anything that suggests the restarted loop would *not* actually improve the model. I would rather
   discover that now than after spending the release on it.

## Sequencing

No repair, no candidate, no retrain. This prepares the work that release #1 unblocks; it does not
perform it. Four candidates already contend for two remaining ordinary dates and I am not adding a
fifth.

## Constraints — unchanged

- Base on `codex/workstation-is-the-bias-conditional-2026-08-24a` @ `fd1a0bb7`. Every branch in this
  chain is held and unmerged. Do not merge any of them.
- **Do not read, enumerate, evaluate, or substitute 2026-08-01 → 08-03 or 2026-08-06 → 08-19.**
- **Do not backfill, repair, refresh, or write any artifact, sidecar, prior, cache, or marine path.**
  Read-only inventory. A "helpful" refresh would change serving inputs without a gate.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Question 1 is the one I need most: if the
nightly path does not refresh base artifacts, everything we believe release #1 buys us needs
revisiting.
