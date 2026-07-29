# Workstation handoff — 2026-07-30a: rehearse release #1 before the lock forces it

This is the highest-leverage thing we can do, and it has a hard deadline.

## The state I got wrong, and what it changes

I had been carrying "A1–A6 unmerged, bootstrap NO-GO on code." That is **stale**. Checking the
actual refs today: your Mission 1 fixes at `09756227` are the merge-base with master, so A1–A6
is **already in master**, and `codex/workstation-pit-simplex-fix-2026-07-24` has an **empty diff
vs master** — the simplex repair landed too. The only unmerged content on the lock-blocker
branch is its report.

So the 2026-07-24 NO-GO was never about missing code. It was:

> `ContractViolation: production preselection requires a contiguous 14-day window`

That blocker is **the streak**, and it clears itself. We are at **8/14**, lock ~2026-08-03.

## Why that is the problem, not the good news

The last end-to-end rehearsal ran against master `1cdb12a4`. Master is now **117 commits**
past that, and tonight it takes the warm tier, which touches `point_in_time_contract.py`,
`io.py`, `storage_classes.py`, and `event_day_manifest.py` — all release-path-adjacent.

Worse: that rehearsal **stopped before training**. Every stage after preselection — candidate
construction, the release artifact, the pointer write, verification — has never run on real
evidence at all. The 2,000-iteration PIT lane ran only on synthetic evidence and returned BLOCK
on 149 simplex failures, which we have since fixed but never re-proven end-to-end.

The PIT contract admits a locked window only while its latest target date is within
`PRODUCTION_MAX_LATEST_TARGET_AGE_DAYS = 7`. So when the streak completes we get a **7-day
window** to build release #1 — on a path that has never been executed past its first gate, on a
master nobody has rehearsed. If it fails on 2026-08-03 we burn that window discovering what we
could have learned this week.

**Everything downstream is gated on release #1.** We cannot act on the blend result, we cannot
prove what production serves, and the MM track cannot trade real money without it. Six weeks of
protecting the streak buys nothing if the thing it gates does not run.

## Mission 1: drive the whole path to a built candidate

Rehearse release #1 on **current master** (after tonight's warm-tier merge — pull first),
using a **conditional, non-authorizing** contiguous 14-day window so preselection admits and the
run proceeds. Keep the discipline your last report used: `conditional_evidence_only=true`,
`production_evidence_authorized=false`, and no real pointer written.

Drive it past every stage that has never executed: preselection → training → candidate
construction → PIT evaluation → release artifact → pointer write → verification. **Report every
gate that fails, with its exact identity and message.** A list of six real failures is a far
better outcome than a green run on a path that flatters itself.

Specifically confirm:

1. The 149 probability-simplex failures are **gone** now the repair is in master. That was the
   last measured BLOCK and it has never been re-run to completion.
2. Candidate construction actually produces artifacts, and the release manifest and declared
   inventory are complete.
3. The pointer resolves through the strict release-root-contained path — the same one
   `replay_cache_retention` needs and cannot currently use, because `artifacts/releases` does
   not exist on the production host and never has.

## Mission 2: does release #1 survive compressed evidence?

This is new risk, created tonight, and nobody has tested it.

The warm tier replaces `order_books.jsonl` with `order_books.jsonl.gz` on every market-day
older than the 30-day hot window. The release path reads snapshot evidence. **Prove the whole
release build still works when its evidence is gzip-tiered**, including any manifest, hash, or
byte-identity check that might have assumed a plain file.

If a release-path reader needs the plain form, that is a hot-window sizing question and I need
the answer before I apply the remaining 180 folders — not after.

## Mission 3: the go/no-go checklist

Produce the thing we will actually execute on lock day: an ordered, exact-command checklist from
locked window to verified pointer, each step with its expected artifact and its failure mode.
Include the rollback. I want to run it, not improvise it.

## What this displaces, deliberately

`-29a` (cool bias) and the remaining warm-tier families both wait. The cool bias is the most
interesting model finding of the week and it will still be there on 2026-08-04. Release #1 will
not wait, because the lock date is set by the streak and not by us.

The MM analysis resumes when your disk clears — the warm tier applies here tonight and the next
`/MIR` should return ~22.4 GB to your mirror. If that clears your floor, run MM **before** this;
it is hours, not days, and it has waited longest.

## Guardrails

Unchanged, and one addition: **no real release pointer, no promotion, no serving change.** This
is a rehearsal that produces a non-authorizing artifact. `data/` read-only, single declared
output root, topic branches only, no PR/merge/master push. NOT-DONE first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-release-one-rehearsal.md`: the failure list first
with exact identities, then the compressed-evidence verdict, then the go/no-go checklist.

Context: streak **8/14**, lock ~2026-08-03, then a 7-day window to build. Production host
158 GB free. Git LFS bandwidth exhausted — see `docs/operations/git-lfs-policy.md`.
