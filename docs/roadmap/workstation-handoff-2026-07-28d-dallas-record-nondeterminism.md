# Workstation handoff — 2026-07-28d: is the Dallas record hash order-dependent?

`-27g` Missions 2 and 3 remain unrun and still wanted. This is the last thing between you and
them, and it should be quick either way.

## Corrections owed

**My churn hypothesis is dead and you killed it cleanly** — settlement labels are excluded from
prediction and joined afterward, so revision churn cannot change a prediction vector. That is
the fifth mechanism of mine measurement has killed this week. The cheap-disproof framing worked
exactly as intended; keep holding me to it.

**My six-field gate was wrong.** I put `reconciliation_status` in it. You found it moves in all
129 market-days because the current sidecar **carries no `reconciliation_status` at all** for
those entries, so it changes by absence. I should have checked field presence before naming it
as stable. Your refusal to drop it after observing the failure was right; the five verified
stable fields are the real gate.

**And my Dallas diagnosis was wrong.** `promotion_corpus` hashes the replay-record object
separately from settlement, so a settlement freeze could never have explained or repaired it.
You said so plainly and you were correct.

## The coincidence worth one test

Your mismatch is on `dallas|2026-06-30|20260701T002709-0400`. That is **one of exactly two
known same-second collision keys** in 18,793 snapshots — the other being
`austin|2026-07-03|20260703T093322-0400`. Hitting one of two special keys by chance is unlikely
enough to check.

There is a code-visible mechanism. In `src/weather/reporting/promotion/promotion_corpus.py`:

```python
def _record_hashes(records, snapshot_ids):
    wanted = {str(item) for item in snapshot_ids}
    return {
        str(snapshot_id): _hash_json(record)
        for snapshot_id, record in records.items()
        if str(snapshot_id) in wanted
    }
```

`records` is keyed by `snapshot_id`, so it can hold **one** record per key. Where two captures
share a second, whichever was inserted last wins, and the surviving record — and its hash —
depends on load order. `_snapshot_tape_hashes` just above it is order-sensitive too: it hashes
`group.to_dict(orient="records")` under `groupby(..., sort=False)`, so row order inside a group
follows frame order rather than a defined sort.

**This is a hypothesis and it has an obvious way to die:** your earlier preblend report
described the two collision halves as *identical* eleven-band captures. If the two Dallas
records are byte-identical, dict overwrite cannot change the hash and this mechanism is
irrelevant — say so and I will drop it. The replay record is a different object from the band
rows, though, carrying `recorded_distribution` and weather sources, so identical bands do not
imply identical records.

Concretely:

1. Does the Dallas `snapshot_id` map to more than one replay record in the current corpus?
2. If so, do those records differ, and does either one hash to the manifest-pinned
   `97e254a7e03b9e03eec69a7a1bab43308d396d43e40ff7c8f27cdaba63a75b00` or to the current
   `95864f97f05956b957dc72fd00c1df9edeb7242f8fe66d36f91575989823a901`?
3. Does the same hold for the Austin collision key — is it also unstable, or does it happen to
   be stable? Austin behaving identically strengthens the mechanism; Austin being stable while
   Dallas is not weakens it.

If both pinned and current hashes correspond to real records that merely swapped order, this is
a **determinism defect in corpus construction**, not corruption, and I will fix it here after
the lock. If neither matches any current record, that is corruption or drift and I want to know
immediately — do not proceed past it.

## Mirror lag is a standing constraint, not a defect

You are at Dallas revision 16; this host is at 17. That is expected: the mirror syncs at 04:30
and the chain rewrote at 09:44. **Your view of `data/` is stale by up to a day, by design.**
Anything I change here mid-day is invisible to you until the next sync, so never treat a
host-state claim of mine as something you can verify on your copy the same day. Say when a
discrepancy is explained by lag rather than by drift, as you did here.

The missing pre-audit ACL receipt is noted and I would rather have the transparent gap than a
reconstructed one.

## Then run the missions

With the record question answered — resolved or cleanly deferred — run `-27g` Missions 2 and 3
under the `-27b` gate: localize where below-floor mass enters given a clean preblend
(`0 / 124`) and a violating incumbent (`118 / 124`), and price the counterfactual projection.
If the Dallas record cannot be resolved, say what excluding that single snapshot would do to
the estimand and let me decide, rather than excluding it yourself.

## Guardrails

Unchanged. `data/` read-only, single declared output root, no model/blend/serving/config/
release change, topic branches only, no PR/merge/master push, NOT-DONE first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-floor-attribution-2.md`: the three record
questions, then Missions 2 and 3.

Context: master carries all your reports. Streak 7/14. Storage merges here at 01:15 tonight.
