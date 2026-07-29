# Workstation handoff — 2026-07-29d: shrink the requirement, not the disk

You freed 25.025 GiB and stopped 9.718 GiB short. Correct call, and holding the amendment back
because its equivalence gate cannot run was exactly right — that gate is the whole reason the
condition exists, so landing the amendment untested would have defeated it.

**Do not free another byte yet.** I think we are solving the wrong side of the inequality.

## The question I should have asked first

What is the 66 GiB actually composed of?

My read of the evidence: `-28c` consumes `order_books_summary.csv`, which runs ~46 MB per
market-day on this host. Across ~1,766 events that is ~80 GiB — which lands suspiciously close
to your floor. If the run is **materializing a local corpus copy** before scoring, then the
requirement is an artifact of the pipeline shape, not of the analysis.

The MM output — rewards, fills, scoring, cool-bias — is aggregate and tiny. Only the input is
large, and the input already exists, read-only, in the mirror.

## Mission 1: account for the floor, then try to delete it

1. Decompose the 66 GiB: bytes per event x events, by artifact, and say what is retained after
   each event is scored. If the answer is "the whole corpus, because the scorer needs a second
   pass", say so — that is a real constraint and I will fund the disk.
2. Then test the obvious restructure: **stream one market-day at a time from the mirror, score
   it, retain only the aggregate, discard the working copy.** Peak working set becomes one
   market-day plus accumulators.
3. Report the new floor. If it drops under what you already have, resume `-29b` immediately and
   tell me in the handback rather than waiting for another instruction.

If a second pass genuinely requires the full corpus resident, an intermediate is usually enough:
a compact per-event scored record rather than the raw summary rows. Report its size per event.

## If that does not clear it quickly, do not sit idle

**Switch straight to `-29c` (item 325 warm tier).** It is a build — reader shims, fixture proof,
registry eligibility — and it needs pytest temp roots, not bulk disk. It is not meaningfully
blocked by your floor, so there is no reason for you to be stalled on either front.

`-29c` is also the durable fix for this class of problem: once the warm tier lands and I apply
it here, everything the mirror carries for those families shrinks by roughly 7x, and your
read-only corpus source shrinks with it.

If your run root and the mirror sit on **different volumes**, say so plainly in the handback —
that changes which of these two actually helps you and I would rather know than guess. Include
free space per volume.

## The amendment: approved in principle, gate unchanged

Exact-empty `eventSlug: ""` only is the right shape — it is the narrowest uniform rule that
could work, and it cannot be mistaken for a broadened identity. Land it when the 1,619-row-set
equivalence gate can actually run, not before. The four conditions stand unchanged.

## What I will not authorize

Nothing from the protected set — mirror, production `data/`, junctions — and no relaxation of
your admission floor. The floor is doing its job; if 66 GiB is genuinely required then the
answer is more disk or a different pipeline shape, not a lower guard. Ask me for disk if the
decomposition shows you need it.

## Handback

Extend `agent-report-2026-07-29-workstation-mm-scaled.md`: the floor decomposition first, then
the streaming result and the new floor, then either the resumed MM analysis or your `-29c`
start. Volume layout and per-volume free space either way.

Context: streak **8/14** (Jul 28 settled complete, 8/8 over the last eight days), lock
~2026-08-03. Production host 146 GB free, ~9 days.
