# Workstation handoff — 2026-07-31d: prove the hard floor cannot exceed settlement

The rescued-floor result is the best measured improvement to the **served** lane we have had. Incumbent
Brier `0.063698529 → 0.057345359` (`-0.006353169`), concentrated in hours 15-17 and 18-23 exactly as
the mechanism predicts, with the pooled preblend correctly unmoved. The stopping rule does not fire.
Your reading of my `0.001357125` question is right and I accept it: that number lives in the
already-floor-aware preblend lane, so a base-model floor fix should not move it, and it didn't.

The point-in-time work is also the right shape. Distinguishing a METAR observed at 17:52 from its
18:00 display label, and reporting the 806 non-reconstructing max summaries as a provenance limit
rather than quietly dropping them, is the standard I want.

**I am not merging it yet, and the reason is one measurement you did not take.**

## The blocker: this makes an unvalidated observation a hard floor

On the empty-WU path `effective_observed_floor_high` feeds `hard_floor_bucket`, which zeroes mass —
you measured that yourself: cumulative below-floor mass `1363.939243 → 0`. Its provenance is 8,037
`max_since_7am` values and 3,563 cutoff-aligned current observations.

Both of those quantities are ones this codebase has already refused to make hard, in writing, on
evidence:

- `validated_current_max_floor_bucket`: *"Most markets still use max-since-7am only as soft support
  because the pinned validation found **over-final rows**."* Only `miami` is in
  `VALIDATED_WU_MAX_HARD_FLOOR_MARKETS`.
- `apply_current_observed_floor`: *"these are non-resolution readings and **must never act as a hard
  floor**"*, and *"max-since can **overstate the eventual WU settlement bucket** by rounding."*
- the comment you rewrote in `model_distribution_constants.py`: *"v0.4.8 made SWOB hard and was
  wrong; the 2026-06-09 audit found the current/METAR floor near-hard (0.001) the same way, and the
  stage/ablation analyses measured **both floors net-negative for Toronto**."*

You did not hide any of this — you rewrote the comment to carve out an explicit empty-WU exception,
and your distinction is real: the prior failures were about a supporting source *disagreeing with an
existing WU print*, and with no print there is nothing to disagree with. I accept that much.

But it does not cover the failure mode that matters. "Over-final rows" and "overstates by rounding"
are properties of **the station reading itself**, not of its relationship to WU. An empty WU history
does not make a station reading more accurate; it only removes the cross-check that would have caught
it. And 8,037 of your 11,600 new floors are exactly the quantity pinned validation declined to trust
for 10 of 11 markets.

The consequence is asymmetric in a way a pooled mean hides. A hard floor above the settled value puts
**zero** mass on the truth — an unbounded per-snapshot loss, and on live capital a guaranteed loss of
stake. Roughly 100 such snapshots would still sit inside your `-0.006353169` net gain without ever
surfacing.

We have been here before with the pooled/individual split: blanket floor projection recovered
`116.67%` of the eligible penalty pooled while **worsening 1,460 individual cases**, which is why it
was rejected. Your fix is a better mechanism than that one, and I expect it to survive this test. But
it has to take it.

## Mission 1: the safety audit (blocking, do this first)

On the same frozen population, join every enforced floor to the **realized settled bucket** and report:

1. how many snapshots had `effective_observed_floor_bucket > settled_bucket` — the count, and the
   distribution of the overshoot in buckets;
2. that count split by market, by rescue source (`max_since_7am` vs `cutoff_aligned_current_observation`),
   and by local-hour group;
3. the per-snapshot Brier change distribution, not just the mean: how many snapshots **worsened**, by
   how much, and the worst individual case, with its snapshot id;
4. the same for the postblend lane.

If the answer is zero over-final floors, say so plainly — that is the evidence that widens the
contract, and it is worth more than the Brier number because it retires a standing prohibition.

If it is not zero, do not argue the mean. Report it, then implement the fallback below.

## Mission 2: the fallback, only if Mission 1 finds over-final floors

Keep the rescue, make it **hedged rather than hard** on the empty-WU path — the existing
`LIVE_FLOOR_HEDGE` / learned catch-up machinery, which exists for precisely this and is already
tuned. Then re-measure the full Brier table.

I expect most of the gain to survive, because it concentrates in hours 15-23 when the daily high is
established and a hedge below an established high costs very little. If the hedged variant retains
most of `-0.006353169`, it is strictly the better trade: nearly all the skill, none of the tail risk.

Report both variants side by side and recommend one. If hard genuinely dominates hedged *and*
Mission 1 came back clean, I will merge hard.

## Mission 3: Toronto

Your population is the 11 F markets again. Toronto is the streak market, the only market release #1
can bind, and the one you already showed is affected at 591/1,213. The comment you rewrote says both
prior hard-floor attempts were measured **net-negative for Toronto specifically**.

So run the same before/after, by-hour, and the Mission 1 safety audit on Toronto's own frozen POST
population. Toronto is Celsius, where one bucket is a larger physical step than in Fahrenheit, so an
over-final floor is both less likely and more expensive. I want its number separately, not pooled
into an F-family average.

## Mission 4: the number the operator actually asks for

You reported incumbent Brier before and after, but never against **market** on that identical
population. The served lane was last measured at `1.664x` market, and it is what we publish.

Give me the served lane versus market before and after, same population, same weighting — and the
ratio. Your report has market at `0.037368631`, but that came from the broader confounded pooled
table, so compute it properly on the accepted population rather than reusing that figure.

## Recorded from your report

- WU stopped as an **authentication outage** on 2026-06-27 (last usable row 05:19:11Z, first auth
  failure 05:28:14Z), and only became policy on 2026-06-30 with `5735b573`. Outage first, policy
  second — that ordering matters, and I had assumed the reverse.
- WU's causal value is **not identifiable** from the frozen corpus: no all-fresh slice, no WU-present
  overlap, no WU feature group in the ablation. Accepted, and I accept the correction that the
  `78.93%` statistic is forecast-source disagreement and cannot be reassigned to missing WU.
- Recommendation accepted: **do not buy or re-enable the paid provider.** A bounded research-only
  capture from the existing free page-backed collector, compared against station rescue, is the next
  valid measurement — propose it, do not run it yet.

## Priority

1 gates everything. 2 only if 1 finds over-final floors. 3 and 4 are independent of both and are what
decide whether this changes release #1's story.

Still deferred: MM, cold tier and the 500 GB cap, pointer creation, C-family candidate run.

## Guardrails

Unchanged: `data/` read-only under the deny-write ACL, outputs under one declared run root outside the
mirror, topic branches only, no PR, no merge, no master push, no promotion, no pointer change, no
serving change, no scheduler/capture/mirror/ACL change, no paid-provider change, never read or expose
the sync credential. POST-regime numbers only.

Continue on `codex/workstation-fix-floor-toronto-2026-07-31b` — do not rebase away `b77cfbed`, I want
the hard variant preserved as the thing the audit judges.

## Handback

`docs/roadmap/agent-report-<date>-workstation-floor-safety.md`: the over-final floor count and the
per-snapshot regression distribution first, then Toronto, then the served-lane-versus-market ratio,
then the hedged variant if it was needed. Push before you start and again at handback.
