# Workstation handoff — 2026-07-30d: the hash defect is the keystone

## First, I retract yesterday's scope decision

I scoped release #1 to Toronto on the basis that no F market qualifies. You have now told me
**Toronto is not qualified either, and the immutable release has no Toronto route.** So no market
qualifies and the Toronto-only scope is void. I am glad I asked you to confirm it rather than
inferring it from "no F market qualifies" — that inference was exactly the kind of thing that
would have failed on lock day.

## Second, the finding that reorders everything

**Clean POST incumbent Brier `0.0637034` versus market `0.0382800` — 1.664x, worse than both
preblend and replay-final.**

| lane | binary Brier | vs market |
| --- | ---: | ---: |
| **incumbent (what we actually serve)** | **0.0637034** | **1.664x** |
| preblend | 0.047572 | 1.243x |
| replay-final | 0.049853 | 1.302x |
| raw market | 0.038280 | — |

Serving preblend instead of the incumbent is worth **0.016131**. The entire remaining
preblend-to-market gap is `0.009292`. **The lane switch is 1.74x larger than the whole research
gap we have been chasing all week** — and it needs no new model, no new predictor, and no new
data. Only the ability to change what we serve, safely and verifiably.

That is what release #1 is for, and it is now the highest-value item in the project by a wide
margin. Every sharpening, blending and cool-bias question is smaller than this.

I am not acting on it yet. Changing serving without release binding is exactly the move we have
refused all along, and I am not going to make an exception for a number I like.

## Third: the streak may not gate what I think it gates

This is the part I need answered before anything else.

You reported Toronto's 14-day window has **2,470 invalid hashes**, one interleaved malformed
line, and **zero strict partitions available**. We have been counting to 14 contiguous
`complete`-grade capture days as *the* gate to release #1. If complete-grade days are not
admissible to the strict lane, then **the thing I have been protecting for six weeks does not
produce a usable window**, and the count is measuring the wrong property.

**Mission 1: tell me whether the streak gates what I believe it gates.** Specifically: does
completing 14 contiguous complete-grade days yield an admissible PIT window, or is
complete-grade capture necessary but not sufficient? If not sufficient, what is the real gating
predicate, and how would I measure it daily the way `streak.ps1` measures the current one?

If the answer is that I have been counting the wrong thing, say so plainly. I would rather find
out five days early than on lock day.

## Mission 2: is the hash fix retroactive?

You found the root cause and it is a good one: **integer distribution keys becoming strings
after JSON persistence.** That is a validation defect, not data loss — the evidence is intact and
the comparison is wrong. It also rules out my hypothesis that it was the
`order_books_long` tiering race, which I had assumed.

The decisive question: **is the fix retroactive?**

- If the stored hash was computed over string-keyed JSON and the recomputation uses int-keyed
  in-memory objects, then canonicalising keys on both sides fixes **all history at once**.
- If the stored hashes are themselves unrecoverable, we need a re-derivation path.

Implement the canonicalisation, then report **how many strict partitions become available for
Toronto's last 14 days**. If that number goes from zero to fourteen days' worth, the window may
already exist and the lock is closer than the streak count suggests.

Report the affected scope precisely too — you said 8 of 12 markets; name them, and say why 4
escaped, because that asymmetry is evidence about the mechanism.

## Mission 3: what is the smallest release that binds what we serve?

If no candidate qualifies, then release #1 should not be trying to promote one. Consider binding
the **incumbent** instead: a release whose purpose is to make current serving explicit, verified
and reversible, promoting nothing.

That would give us the strict forward shadow, a rollback baseline, an `artifacts/releases` tree
that finally exists, and the mechanism to later switch lanes deliberately. It also unblocks the
32 GB replay-cache reclaim, which is gated on an active pointer this host has never had.

Tell me whether the release contract permits this, and what "no Toronto route in the immutable
release" actually means — is it a missing C-family route in the artifact schema, a missing
serving role, or a promotion prerequisite? That determines whether it is a small fix or a design
change.

## Mission 4: the malformed interleaved line

One line, but it is canonical evidence and it was written interleaved, which means concurrent
writers. Locate it, characterise it, and say whether the writer that produced it can still do so
today. A one-line defect I can repair; a live interleaving writer is a streak risk.

## Priority

1, 2, 3, 4 in order. Mission 1 changes what I do every day; Mission 2 may move the lock;
Mission 3 defines the deliverable; Mission 4 is containment.

The go/no-go checklist is deferred again, deliberately — writing a checklist for a release whose
scope is now undefined would be waste.

## Guardrails

Unchanged. No promotion, no pointer change, no serving change, `data/` read-only, topic branches
only, no PR/merge/master push. Push your branch this time before starting.

## Handback

`docs/roadmap/agent-report-<date>-workstation-hash-keystone.md`: the streak-gating answer first,
then the retroactivity result with the strict-partition count, then the minimal-release verdict,
then the malformed line.

Context: streak 8/14 by the current definition — which Mission 1 may tell me is the wrong one.
Warm tier merged here at 01:15; incumbent-versus-preblend is parked until binding exists.
