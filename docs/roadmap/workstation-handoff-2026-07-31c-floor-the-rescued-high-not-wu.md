# Workstation handoff — 2026-07-31c: floor the rescued high, not WU

## My spec was wrong, and you built exactly what I asked for

I wrote: "derives the observed floor the same way the feature path already does — cutoff-aligned WU
rows." Those two clauses contradict each other, and you implemented the second one. The feature path
does **not** ultimately depend on WU; when WU is empty it uses a station rescue. So a WU-only
derivation is a no-op on a fleet where WU is empty everywhere, which is exactly what you measured.
That wasted a cycle and the fault is mine, not yours.

Your corrections stand and are more valuable than the fix:

- **My C/F unit hypothesis is dead.** Toronto's blank floor is `paid_provider_disabled` with zero
  captured WU rows, not a Celsius/native mismatch.
- **The previous report's own framing was wrong**, and you caught it: all 11,661 frozen F snapshots
  are WU-floorless. The 11,600 "numeric printed WU floor" values were **station-rescued features**;
  only 61 were genuinely feature-floorless.
- **Toronto is affected too** — 591/1,213 eligible snapshots emit below the station-rescued high,
  with hours 18-23 at 241/284 (84.86%), not 100%. So the release market carries the defect, at lower
  severity than F.

That is two of my theories killed in two cycles, both with numbers. Keep doing that.

## Mission 1: floor the value the feature path actually produces

The violations you measured are relative to the **station-rescued observed high** — that is the real
floor, and it is the value `extract_live_features` already computes and persists. So the fix is to
make `observed_floor_bucket` derive from the *effective* observed high, whatever source rescued it,
rather than from a WU-specific extraction.

Keep what you built for the WU path; it is correct and it will matter if the paid provider is ever
re-enabled. Add the rescue-aware derivation on top so the floor is populated whenever *any* admitted
source establishes an observed high.

Requirements unchanged from before, plus one: the 61 genuinely floor-less snapshots must still end up
with no floor, and the fix must not invent one from a source that has not actually observed anything.

## Mission 2: re-measure, with a stopping rule

Then quantify POST-only on the frozen population: Brier before and after, overall and by your
00-02 / 03-08 / 09-14 / 15-17 / 18-23 cuts, plus Atlanta's daily-first and row-weighted deltas versus
market on both lanes — does it close the `0.001357125`?

**And prove it is point-in-time safe.** This matters more now than before, because the rescued high
comes from a fallback path I have never audited. State explicitly that no post-cutoff row informs any
floor used in the improved numbers. If part of the gain depends on information the model did not hold
at emission time, report that part as unusable and name it.

**Stopping rule, so we do not chase this indefinitely.** If enforcing the rescued floor also produces
no material Brier change, then say so and **stop**. In that case the defect is a correctness problem
worth fixing before release — we should not publish provably impossible mass — but it is *not* a
skill lever, the `0.001357` has to come from somewhere else, and I want the cycle back rather than a
third round of the same hypothesis. Report that verdict plainly; a clean negative is a good outcome
here.

## Mission 3: what did disabling the paid provider cost us?

`paid_provider_disabled` with zero captured WU rows across the whole fleet is a bigger fact than the
floor bug it masked. WU is a configured source that is currently contributing nothing.

Tell me: when did WU capture stop, was it a deliberate priced decision or drift, and what is the
fleet actually losing? Source disagreement has previously been measured at 78.93% of positive excess
loss, so a silently absent source is a candidate explanation for skill we cannot otherwise account
for. Measurement and recommendation only — do not re-enable anything, and do not spend money.

## Priority

1, 2, 3, with the stopping rule governing whether 2 ends the thread. Mission 3 is measurement and may
turn out to matter more than either.

Still deferred: MM, cold tier and the 500 GB cap, pointer creation, and any C-family candidate run.

## Guardrails

Unchanged: `data/` read-only under the deny-write ACL, outputs under one declared run root outside the
mirror, topic branches only, no PR, no merge, no master push, no promotion, no pointer change, no
serving change, no scheduler/capture/mirror/ACL change, never read or expose the sync credential.
POST-regime numbers only; treat any large apparent lift as a leakage suspect first. Mirror data
written in the last ~36 hours may be stale.

Note: `origin/master` now contains your keystone plus lock-backstop branch (merged `2c9bceaa` at
01:15; capture readopted cleanly, streak intact at 8/14). Rebase onto it.

## Handback

`docs/roadmap/agent-report-<date>-workstation-rescued-floor.md`: the rescue-aware fix and its
failing-then-passing test first, then the by-hour Brier effect with the point-in-time attestation and
an explicit verdict against the stopping rule, then the WU-absence finding. Push before you start and
again at handback.
