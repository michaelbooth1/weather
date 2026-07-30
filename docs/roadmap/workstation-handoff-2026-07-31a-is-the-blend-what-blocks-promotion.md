# Workstation handoff — 2026-07-31a: is the blend what blocks promotion?

## First, your July 24 verdict was right about the bytes and wrong about the cause

You concluded "most consistent with workstation/source divergence." It was **staleness**, and I can
prove it with my own repair receipt. You read 31,069,317 bytes / `7b58a04b...`. That hash is exactly
the `original_file_sha256` recorded before I wrote anything, and
31,069,317 − 31,061,162 = **8,155 bytes = fragment A precisely**. You audited the pre-repair file.

`WeatherDataMirror` last ran 05:06; I repaired at 22:20. Two of your other BLOCKs are the same
artifact — Jul 28's `ledger_label_missing` exists because each chain run settles *yesterday*, so Jul
28's revision was written during Jul 29's 09:30 chain, after your sync.

**Standing rule from now on: before concluding anything about data written in the last ~36 hours,
treat the mirror as up to 24 hours stale.** Same-day repairs and same-day settlements are invisible to
you. Say "the visible tape shows X, which may be stale" — which is close to what you did write, and
that careful wording is the only reason this was diagnosable rather than alarming. Do not upgrade it
to a divergence claim without an age check.

I re-ran your clock on live production data from a detached worktree. **July 24 grades PASS /
`release_admissible` — "all production source checks passed"**, and the clock reads
**`contiguous_pass_days: 8`, `streak_start_date: 2026-07-21`**, identical to `streak.ps1`. Your tool
verified my repair including the self-hash and distribution-mass checks I had no way to run myself.
That is exactly what I wanted it for.

Worktree note for your own use: a root-level `weather/` package shadows `src/weather` via cwd, so run
from a neutral directory with `PYTHONPATH=<worktree>\src`, not from the repo root.

Your branch merges here in tonight's quiet window. I reviewed both loop-loaded files first.

## The question that decides whether the lock is worth anything

The lock is on rails: both clocks read 8, ~Aug 3, measured rather than hoped. So the binding
constraint moves to what we can actually *do* with an admissible window — and right now the answer is
"bind an all-shadow research release with `production_capable: false`", which changes nothing about
what we serve.

Meanwhile the largest measured number in the project is untouched: **what we serve (incumbent) is
0.0637034 = 1.664x market; preblend is 0.047572 = 1.243x. Switching lanes is worth `0.016131`, which
is 1.74x the entire remaining preblend-to-market gap of `0.009292`.** No new model, predictor, or
data required — only the ability to change what we serve.

But that switch means promoting a candidate, and the promotion gate rejects every market. So either
the gate is right and the 1.243x is unreachable in production, or **the gate is measuring the wrong
lane**. I have a specific suspect, and three separately-recorded findings point at it:

1. On the clean POST regime the blend **hurts**: preblend 0.047572 versus replay-final 0.049853.
2. `replay-final` introduces **rounded-floor-infeasible mass**, and the 7,193 rows where it does carry
   **132.10%** of net POST blend harm — clean partitions actually benefit from blending.
3. Below-floor cases: **preblend 0 of 124, replay-final 108, incumbent/recorded 118.**

Point 3 is the one that should worry us most, and it is not a tuning observation. It says the lane we
serve emits **provably infeasible probabilities** — mass below an already-established floor — in 118
of 124 eligible cases, while preblend never does. That is a correctness defect in the serving path,
not a skill deficit.

So: **if the promotion gate evaluates candidates on post-blend output, the blend may be what fails
them.** In which case fixing or bypassing the blend unlocks the gate *and* delivers the lane switch
*and* removes invalid output, all from one change.

## Mission 1: what does the promotion gate actually measure?

Enumerate the real gate criteria as implemented — not as documented. For each criterion state whether
it is computed on **pre-blend** or **post-blend** output, and name the code path.

Then, for Atlanta (which you established genuinely fails) and Toronto, report **per-criterion pass/fail
with the actual numbers and thresholds**. I want to see which specific criterion fails and by how
much, not an aggregate verdict.

Finally, the decisive counterfactual: **would the same candidate pass if the gate saw its pre-blend
output?** If yes, name every criterion whose verdict flips. If no, say so plainly — that kills the
cheapest theory in the project and is worth knowing immediately.

## Mission 2: is the below-floor mass real in the SERVING path?

This has only ever been measured in the offline harness, and we have been burned there before: the
`NOT_ACCOUNTED_FOR` finding survived weeks before your forward shadow showed the incumbent reproduces
recorded output to 2.23e-16 and the discrepancy was a harness artifact. Do not repeat that.

Using the real serving path, determine whether the incumbent emits below-floor mass **in production
output**, on real recorded evidence. If it does, characterise it: how often, how much mass, which
hours and markets, and whether the floor is an already-observed quantity at the time of emission
(which would make it a hard logical error rather than a modelling choice).

If we are publishing infeasible probabilities to a live market, that outranks every efficiency
question on the board and I want it stated in one sentence I can act on.

## Mission 3: conditional — the smallest candidate that could qualify

Only if Mission 1 says a pre-blend lane would pass. Then: what is the smallest, reviewable change that
makes a qualifying candidate exist and be releasable — a blend bypass, a targeted floor projection
(noting the earlier finding that blanket floor projection recovers 116.67% of the eligible penalty
pooled but **worsens 1,460 individual cases**, so it is not deployment-safe unblanketed), or something
else?

Scope it; do not implement it. I want the option priced before anyone builds it.

## Priority

1, then 2, then 3. Mission 1 is a read of existing code and existing numbers and could redirect the
entire project. Mission 2 is the one that could turn out to be urgent. Mission 3 is conditional on 1.

Explicitly **not** this cycle: MM (your `NOT_VIABLE_CURRENT_TRACK` economics verdict stands), the cold
tier and the 500 GB cap (operator deferred both; disk is comfortable on both hosts), and pointer
creation (a separate operator decision — your five conditions are recorded and I will bring it as its
own decision with evidence).

## One hardening request, small

Your `_lock_is_stale` fix is the right shape and it closes a real corruption path. But when the PID is
readable it drops the age bound **entirely**, and `_process_is_running` accepts any live PID with no
process-name check. A recycled PID would hold a market-day lock forever, skipping snapshot writes into
a `partial` grade and resetting the streak. Fail-closed is the correct bias — corruption is far worse
than a stall, and a stall is visible within minutes — but add a generous backstop: treat the lock as
stale if the recorded owner is live yet the lock exceeds ~30-60 minutes, since no legitimate snapshot
transaction runs that long. My `mirror-weather-data.ps1` equivalent also matches on process name;
yours does not.

## Guardrails

Unchanged: `data/` read-only under the deny-write ACL, outputs under one declared run root outside the
mirror, topic branches only, no PR, no merge, no master push, no promotion, no pointer change, no
serving change, no scheduler or capture change, no mirror topology change, no ACL change, never read
or expose the sync credential. Report POST-regime numbers only, and treat any large apparent lift as a
leakage suspect before treating it as a win.

## Handback

`docs/roadmap/agent-report-<date>-workstation-promotion-gate.md`: the per-criterion gate table with
pre/post-blend attribution first, then the pre-blend counterfactual verdict, then the serving-path
below-floor finding. Push the branch before you start and again at handback.
