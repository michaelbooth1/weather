# Workstation handoff — 2026-07-29b: unblock your disk, then finish the MM run

You stopped correctly. A fail-closed stop at a policy floor with no data touched is the right
outcome and I would rather have that handback than a completed run of unknown provenance.

This answers both of your questions and re-gives the cleanup, which the operator has moved up.
**The cleanup now comes first**, because it is what unblocks the commercially important work.

## Answer 1 — the disk, and where to look

Authorized, with a specific lead.

I measured my own host this morning: `data/backtest/replay_cache` holds **32.28 GB across 770
files**, against the **10 GiB** diagnostic ceiling your own Mission 2 recommended. That is 3.2x
the ceiling on a *production* host that runs replay far less than you have this week. You have
been running pooled candidate replay across many missions and several worktrees, so I expect
your equivalent to be larger, and I expect it to be most of your shortfall.

**You may reclaim, on your host, without further approval:**

- replay caches under any of your worktree/run roots — `operator_cache` class, rebuildable by
  construction;
- superseded mission run roots whose reports are already committed and pushed;
- stale `scratch/worktrees/*` checkouts for branches already pushed and handed back;
- your own pytest temp roots, build artifacts, and `__pycache__`.

**You may not touch, under any circumstances:**

- the mirror, at any path, read-only as always — it is our only off-host copy;
- anything under a production `data/` root;
- artifacts that a **pushed report's numbers depend on**. This week's findings — the regime
  split, the 1.243x, the cool-bias characterisation — must stay reproducible. If a run root
  backs a number I am carrying in memory, keep it or re-derive it cheaply and say which.

Prefer your own `replay_cache_retention` planner over `rm` where it applies; you built it for
exactly this and it proves rebuildability rather than guessing. For your own scratch, ordinary
deletion is fine — the tool's ceremony exists to protect production data, not your run roots.

Report free space before and after, and what the largest single contributor actually was. If
you clear the floor and still cannot reach 66 GiB, stop again and tell me; do not start
deleting things from the "may not" list to get there.

## Answer 2 — the 17 gaps: amend, but only uniformly and only before scoring

The seven primary July 9 events missing `eventSlug` are a **data-completeness** fact, not a
contract preference, so I am not going to make you drop them on principle. But an identity
amendment made after seeing which rows it unblocks is exactly the shape of the item-224 mistake,
and I want the difference to be structural rather than a promise.

**You may amend the pre-score identity contract if and only if all of these hold:**

1. The amendment is **uniform** — applied to all events, not to the 17, and not conditioned on
   whether a row currently validates.
2. It is **committed before any scoring runs**. Analysis is `NOT_RUN` right now, which is what
   makes this legitimate; that property must still hold at the moment the amendment lands.
3. It **reproduces the existing 1,619 complete events exactly** — same identities, same
   membership. If the amended identity silently changes what any already-complete event *is*,
   it is a loosening and not an amendment, and it is rejected.
4. You report the coverage delta: complete before, complete after, and which gaps remain.

If any of those fails, the contract stays frozen and you run the analysis on the complete subset
with the exclusion declared in the report.

Either way I want the same thing at the end: **a statement of whether the excluded events could
change the verdict.** A bound is enough. If the MM answer is the same with and without them, the
gaps are a footnote; if it only holds when they are included, that is a caveat I need to see
before anyone spends money on it.

Finish the 147 remaining valid events first — the backfill was interrupted by disk, not by a
defect, and a complete backfill may reduce the question to nothing.

## Then: the MM run, which is the point

Once disk is clear and the backfill is complete, run the analysis, rewards, and cool-bias
scoring that came back `NOT_RUN`. That is the commercially important item and it has now slipped
several days.

The reason it matters more than it did when it was queued: on the clean POST regime we are
**1.243x** the market's Brier with **better-than-market reliability** (`0.005978` vs
`0.007215`). A well-calibrated book that is slightly less sharp than the market is a far better
maker candidate than the 1.7x, badly-calibrated one we thought we had. The maker question
deserves a real answer against real economics.

Carry `-29a` (the cool-bias origin and the predeclared held-out conditional correction) behind
it, unchanged.

## Guardrails

Unchanged, except for the explicit scratch-reclaim authorization above. `data/` read-only,
single declared output root, no model/blend/predictor/config/serving/release change, no
retraining, no scheduler or capture change. Topic branches only, no PR/merge/master push.
NOT-DONE stays first-class — you used it correctly today.

## Handback

`docs/roadmap/agent-report-<date>-workstation-mm-scaled.md`, extended: disk before/after and
the largest contributor; the identity-amendment decision with its four checks or the frozen
alternative; the coverage delta; then the MM analysis, rewards, and cool-bias scoring.

Context: streak 7/14, lock ~2026-08-03. Storage build merged here at 01:15 (`efe6014f`); my own
replay-cache reclaim runs today.
