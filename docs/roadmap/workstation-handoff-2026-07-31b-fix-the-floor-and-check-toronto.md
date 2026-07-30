# Workstation handoff — 2026-07-31b: fix the floor, and tell me about Toronto

Your gate report did the two things I most needed: it killed my theory precisely rather than
politely, and it proved the floor defect in the real serving path instead of the harness. The
counterfactual table — pre-blend Atlanta still missing market tolerance by `0.001357` with no verdict
flipping — is exactly the shape of answer that lets me stop spending cycles on a dead idea.

Recorded and accepted: the gate scores post-blend `candidate_p` and `candidate_preblend_p` never
reaches it; Toronto has *no* verdict because it is absent by construction from the F-family artifact,
allowlist and candidate vector; and the remaining distance to qualification is `0.001357`, not the
`0.009292` research gap.

Also accepted: your rebuttal on the lock process-name check. `python.exe` cannot distinguish a
recycled writer from another Python process, and the one-hour bound prevents the indefinite stall
directly. That is a better argument than my request.

Two notes on scope before the missions. **No live capital is exposed** — the taker is paper
(`taker_bot_daily_roll`: "Daily launcher for paper taker-bot runs", `--budget-usdc 100` is a paper
budget) and the bootstrap keeps `production_capable: false`. So this is the top engineering defect,
**not an incident**; work it carefully rather than fast. And I independently verified before merging
that `captured_input_payload_sha256(p, persisted=False)` is byte-identical to the old
`canonical_payload_sha256(p)` on constructed typed payloads across both the 9→10 and 99→100
boundaries, so the merge cannot change what future captures write.

## Mission 1: does Toronto have this defect?

**Your floor table covers eleven F markets. Toronto is not in it.** Toronto is the streak market, the
point-in-time market, and the only market release #1 could ever bind, so its status is the single
most consequential unknown you have left me.

Two sub-questions, and I think they are the same question:

1. Does Toronto emit below-floor mass in the real serving path, at what rate and mass, and with the
   same 100% concentration in local hours 18-23?
2. **Is the blank top-level field a unit mismatch?** You found all 11,600 affected snapshots had a
   blank `snapshots_long.csv:wu_history_high_c` while the floor path asks
   `row_max_native(history)`. That field is named for **Celsius** and the request is for **native
   unit**. Toronto is our only C market; the eleven affected markets are all F. If that field is
   structurally populated only in Celsius, then it is blank for every F market **by construction** —
   which would explain a 100% blank rate far better than intermittent data loss, and would predict
   that **Toronto is clean**.

If Toronto is clean, the release path is in much better shape than the F numbers imply and the defect
is F-presentation-shaped — which we have been bitten by before. If Toronto is also affected, say so
plainly; it changes what release #1 can honestly contain.

Report the mechanism, not just the rate. I want to know *why* the field is blank.

## Mission 2: fix it at the input contract, not with a projection

Fix the extraction so the distribution/floor path derives the observed floor the same way the feature
path already does — cutoff-aligned WU rows — so that `observed_floor_bucket` is populated and
`distribution_hard_floor_stage` and `calibration_runtime.hard_bin_probability` enforce the floor
natively.

**Do not reach for a post-hoc floor projection.** We already priced that: blanket floor projection
recovers 116.67% of the eligible penalty pooled but **worsens 1,460 individual cases**, so it is not
deployment-safe unblanketed. That is a symptom transform. The defect here is an input-contract bug,
and the sanctioned floor stages already exist and already work — they were simply handed `None`.
Fixing the input makes the existing machinery correct rather than adding a second mechanism that has
to be tuned.

Requirements:

- a regression test that **fails on the current code** and passes on the fix, asserting zero
  below-floor mass when an observed floor exists;
- explicit handling of the 61 genuinely floor-less snapshots — no floor must remain no floor, not a
  fabricated one;
- unit correctness across both families, since Mission 1 may show this is exactly where it broke;
- `data/` untouched, no merge. `model_distribution.py` is loop-loaded, so the merge is roll-sensitive
  and its timing stays with me.

## Mission 3: measure the effect, and prove it is not leakage

Then quantify, POST-only, on the frozen population:

1. Brier before and after the fix, overall and **by local-hour group** using your existing 00-02 /
   03-08 / 09-14 / 15-17 / 18-23 cuts. I expect the gain to concentrate in 15-17 and 18-23 where
   violation rates are 96.84% and 100%.
2. **Does it close the `0.001357`?** Recompute Atlanta's daily-first and row-weighted deltas versus
   market with the floor enforced, on both the post-blend and pre-blend lanes. If enforcing a floor
   that was already observed is enough to bring a market inside `market + 0.003`, that is the
   cheapest qualifying path we have ever had.
3. **Prove it is point-in-time safe.** "We improved by enforcing a floor" is exactly the shape of a
   leakage win. You already established the floor is reconstructible from cutoff-aligned
   `sources.wu_history.data.rows` available to the serving transaction rather than from future
   labels — carry that discipline into the *measurement* too, and state explicitly that no
   post-cutoff row informs any floor used in the improved numbers. If any part of the gain depends on
   information the model did not have at emission time, report the gain as unusable and say which
   part.

A real gain here is worth more than its Brier delta, because it also removes provably invalid output
from what we publish.

## Priority

1, 2, 3. Mission 1 is cheap and could reframe the whole defect. Mission 2 is the fix. Mission 3 tells
us whether the fix is also the promotion path.

Still deferred: MM, the cold tier and the 500 GB cap, pointer creation, and any C-family candidate
run (Mission 1 may argue for one — recommend it, do not start it).

## Guardrails

Unchanged: `data/` read-only under the deny-write ACL, outputs under one declared run root outside the
mirror, topic branches only, no PR, no merge, no master push, no promotion, no pointer change, no
serving change, no scheduler or capture change, no mirror topology change, no ACL change, never read
or expose the sync credential. POST-regime numbers only. Treat any large apparent lift as a leakage
suspect before treating it as a win. Mirror data written in the last ~36 hours may be stale — check
`mirror_status.json` before concluding anything about recent dates.

## Handback

`docs/roadmap/agent-report-<date>-workstation-floor-fix.md`: the Toronto verdict and the blank-field
mechanism first, then the fix with its failing-then-passing regression test, then the by-hour Brier
effect and the `0.001357` recomputation with the point-in-time attestation. Push the branch before you
start and again at handback.
