# Workstation handoff 2026-08-12a — build the continuation candidate

You built the judge in `-08-09a` and it has nothing to judge. Build the candidate it was built for.

This amends the `-08-10a` stand-down for one research mission. The stand-down otherwise still holds:
release #1 is not yet built, and nothing here may touch it.

## Why this now

`-08-08a` established that the incumbent HGB already consumes the observed floor — all 168
market/hour bundles select *and* split on the observed-high family, `high_so_far` alone at 267,253
splits. So the gap is not a missing signal. The specification's conclusion was to **change the
learned quantity, not add another copy of the same one**.

`-08-09a` then built the gate harness and self-verified it against the incumbent. Everything is in
place except the thing being measured.

Doing this before release #1 lands means the moment the pointer exists there is a scored candidate
ready for the real gate, instead of starting from zero inside the build window.

## The pre-registered bar — read this before you fit anything

The catastrophic-slice threshold has deliberately been left open until now so that it could be
frozen **before** a candidate exists. It is frozen here:

> **No protected slice may regress by more than the pooled improvement.**

Record this in your report as a pre-registration, with the slice definitions you used, *before* you
report any result. If the candidate wins pooled and loses a protected slice by more than it gained,
that is a **fail**, not a trade-off to argue about. Do not renegotiate the bar after seeing a number.

## The mission

Fit and replay-score the continuation objective from the `-08-08a` specification:

- For cutoff-time canonical floor bucket `F` and settled bucket `Y`, learn the non-negative
  continuation `D = Y - F`, `D ∈ {0, 1, 2, …}`.
- Translate `P(D = d | X, F, floor_available)` back to the absolute bucket `F + d`.
- Condition the local-history/climatology prior to that same support **before** blending.
- Treat the canonical `F` as a control and target origin — **not** as a newly optimized weather
  feature.
- Leave the existing hard-floor stages in place as an independent defence.

Then score it against the incumbent with your own `-08-09a` harness and report whether it passes.

Base on `codex/workstation-gate-harness-2026-08-09a` @ `b9c62ead`. That branch is **unmerged and
held on purpose** — it is roll-sensitive and lands after the lock. Do not merge it, and do not
assume it is on master.

## What I want back

1. The pre-registration block, written before any result.
2. Pass or fail against the frozen bar, pooled and per protected slice.
3. If it fails: which of the three stages — objective, translation, or prior conditioning — carries
   the loss. A null result named precisely is worth more than a marginal win.
4. Whether the severe tail (the 4.26% of rows carrying 60.2% of positive excess Brier) moves, since
   that is the whole reason centre was chosen over width.
5. Anything the harness could not judge, stated plainly rather than worked around.

## Constraints — unchanged, and non-negotiable

- **Reserved forward window `2026-08-06` → `2026-08-19`: do not read, enumerate, evaluate, or swap
  it.** Not for a sanity check, not for a single date.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary; do not straddle it.
- **Never weaken the trusted observed-high floor.** It binds on 76.34% of severe rows and improves
  aggregate Brier. It is a control here, not a tunable.
- `data/` is **strictly read-only** with the OS-level deny-write ACL. All output goes under one
  declared run root outside the mirror. Declare the root and the timestamp before inspecting any
  result.
- **Mirror freshness: gate only on the dates this experiment actually reads.** Do not require the
  mirror to be current to today — it runs 04:30 while the prior day settles ~09:49, so that gate can
  never pass. If the dates you need are absent, say so and stop rather than substituting.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture
  restart, PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no**
  paid-provider change.
- Topic branch only; merge timing stays with the production host.
- Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch name and commit. Expect it to be **held** — this is
research and the production host is two days from a release lock. Do not treat a good result as
authorization for anything.
