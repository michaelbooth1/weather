# Workstation handoff 2026-08-17a — what did the gate cost us?

Run this **now**. It consumes no fresh scoring dates and must not create a candidate.

`-08-16a` is queued behind it and still must not run before 2026-08-05 04:30.

## The question

The 20% floor-informativeness gate bought safety by narrowing. On July 31 it excluded **1,425 of
2,156 snapshots — 66%** — and those rows now receive the incumbent unchanged. The severe-tail
reduction fell from 58.23% (ungated, July 27–30) to 30.71% (gated, July 31); those are different
windows so the comparison is loose, but the direction is not in doubt.

The excluded population is *defined* by the floor not yet binding: early and mid-day rows, before the
observed high is informative. The failing hours were 3–4, 8–11, 13–14 and the passing hours were
17–23.

**That excluded population is the 09:00–14:00 slice this project adopted as its primary objective.**

So the candidate may be improving the part of the day already known to be solved and declining to
touch the part we said mattered most. I want that answered before the last ordinary dates are spent
confirming a candidate that might be aimed at the wrong population.

## Hard boundary — diagnosis only

This mission **describes**; it does not select.

- **No new candidate, no variant, no threshold change, no refit, no smoothing change.**
- **Do not use anything you find here to choose a parameter.** July 31 is already-scored evidence.
  Selecting on it would corrupt the `-08-16a` comparison exactly as selecting on July 27–30 would
  have.
- Any hypothesis this generates is a *future* mission with its own fresh evidence. Fresh dates are
  nearly exhausted, so say what you would test rather than testing it.

You may re-analyze July 22–26 and July 31, which are already spent. Do not read August 1–3 — they are
reserved for `-08-16a` — and do not touch August 6–19.

## What I want answered

**1. Who is excluded.** Characterize the 1,425 excluded snapshots by capture hour, market, and
forecast-relative position. What fraction of the 09:00–14:00 primary-objective window falls outside
the gate? Give it as a percentage of both snapshots and band rows.

**2. Where the remaining loss lives.** Of the incumbent's total positive excess Brier and of its
severe rows, how much sits inside the excluded population versus the qualified one? If the excluded
two-thirds carry most of the remaining loss, the gated candidate is a win on the easy part and I want
that stated in one sentence.

**3. Whether the severe tail moved or relocated.** The gated candidate cut severe rows on qualified
data. Did total severe rows across *all* rows fall by the same amount, or did the excluded population
retain its own?

**4. Why hours 14 and 17 fail.** We diagnosed D1 to a precise mechanism and never did the same for
these. Hour 17 *passed* ungated at `-0.005742` (severe 125 → 85) and failed gated at `+0.008626`
(severe 42 → 43); hour 14 failed both times, at `+0.018144` then `+0.007065` against a bar of
`0.006860`. Are these the same mechanism as D1, a different one, or single-day noise? Name it as
precisely as the D1 diagnosis did.

**5. What you would try next, and on what evidence.** Given the excluded population needs something
other than a floor-anchored continuation — the floor is genuinely uninformative there — what is the
most promising mechanism, and what would falsify it? Rank by expected value, and be explicit about
which are cheap and which need the confirmation window.

## What I do not want

A recommendation to widen the gate. Lowering the threshold was already measured: `1%` and `5%` both
failed the catastrophic bar decisively. If your analysis points back at the gate, that is a finding
about the *objective* being wrong for those rows, not about the cut point.

## Constraints — unchanged

- Base on `codex/workstation-repair-d1-anchor-2026-08-15a` @ `8377873e`. All branches in this chain
  are held and unmerged on purpose. Do not merge any of them.
- **Do not read, enumerate, evaluate, or substitute 2026-08-01 → 08-03** (reserved for `-08-16a`) or
  **2026-08-06 → 08-19** (final confirmation set).
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary; do not straddle it.
- **Never weaken the trusted observed-high floor.** Control, not a tunable.
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror; declare root and timestamp before inspecting any result.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. A clear negative answer to question 2 — that
the excluded population carries most of the remaining loss — would be the most useful thing this
mission could produce, and it should be reported as prominently as a positive one.
