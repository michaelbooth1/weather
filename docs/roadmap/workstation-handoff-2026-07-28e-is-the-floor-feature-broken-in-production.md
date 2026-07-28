# Workstation handoff — 2026-07-28e: is `high_so_far` broken in production, or only in replay?

This supersedes the Mission 1 gate in `-27b`. Missions 2 and 3 of `-27g` stay queued behind it.

## You were right about the collision, and it is fixed here after the lock

Two distinct Dallas records, both hashes genuine, later-wins matching the manifest, and Austin
reproducing it. That confirms an **order-sensitive duplicate-key defect in corpus construction**
— `_record_hashes` keys a dict by `snapshot_id` and silently keeps whichever record was
inserted last. Resolving it without excluding the snapshot, leaving the estimand intact, was the
right call. I own the fix on this host and it lands after the lock.

## One of my four checks was over-strict — the other three were not

**Settlement bound: I was wrong to fail it.** 1,640 raw exceedances with **zero rounded
exceedances** and a largest raw excess of `0.46 F` is not contamination — it is a raw float
compared against a whole-degree settled bucket. The printed floor is
`ROUND_HALF_UP(high_so_far)`, so the rounded check is the one with meaning, and it passed
cleanly. Going forward, **bound-check the rounded floor and report the raw delta as a
diagnostic**, not as a gate. I am narrowing this deliberately and saying so; the raw numbers
stay in the report either way.

The other three stand and are not explainable by rounding:

- 703 non-monotone decreases across 128 of 129 market-days, worst `95.0 -> 82.04 F`;
- 45 value-then-null resurrections across 40 market-days;
- 27 late nulls across 26 market-days.

A running maximum cannot fall 13 degrees, and cannot become unknown after being known.

## The question that decides how much this matters

Everything above is **reconstructed** — 18,793 reconstructed snapshots, 7,095,312 reconstructed
floor features. So there are two very different worlds and I do not know which we are in:

1. **Reconstruction-only.** Your replay path rebuilds `high_so_far` differently from how it was
   computed at capture time. Then this is a harness defect, the production feature is fine, and
   the floor work resumes against stored values.
2. **Production too.** Then it is far more serious than the floor mission, because
   `high_so_far` is not a diagnostic — it is a **model feature**. `pooled_feature_assembly.py`
   carries `high_so_far`, `band_minus_high_so_far`, `band_hi_minus_high_so_far` and
   `band_mid_minus_high_so_far`, and `feature_model.py` builds `high_so_far = max(temps_before)`
   with `rise_from_7am` and `is_extended` derived from it. A non-monotone, occasionally
   vanishing running maximum would mean several trained features are corrupted.

**So compare reconstruction against what was stored.** For the same snapshots, does the stored
feature value show the same 703 / 45 / 27 pathologies, or is it clean? That single comparison
decides between a harness bug and a model-input defect, and nothing else should be built on the
floor until it is answered.

If they disagree, report the disagreement shape — which one is monotone, which one nulls — and
stop. Do not assume the stored one is authoritative merely because it is production.

## Then localize, whichever world we are in

For the 703 decreases specifically:

- Are they concentrated in particular markets, local hours, or calendar dates?
- Does a decrease coincide with a change of observation source, a re-fetch, or a day-boundary
  or timezone edge? `high_so_far` is `max(temps_before)` over observations at or before the
  cutoff, so a decrease means the observation set shrank or its values changed — say which.
- Do the 45 resurrections and 27 late nulls sit in the same markets and hours as the decreases,
  or are they a separate population?

## A hypothesis, flagged as such

If `high_so_far` is corrupted in the stored features, that is a candidate explanation for model
underperformance in exactly the hours where knowing the running maximum matters most — the
afternoon and evening, which is where our deficit is largest.

**This is my sixth mechanism this week and five of the previous five died.** Treat it
accordingly. It dies immediately if the stored feature is clean, and it dies if the affected
rows are too few to move a pooled score — quantify the affected share before entertaining it at
all.

## Then the original missions

With the gate resolved, `-27g` Missions 2 and 3 as written: localize where below-floor mass
enters given a clean preblend (`0 / 124`) against a violating incumbent (`118 / 124`), and price
the counterfactual projection — noting that the floor's own reliability is now part of the
question rather than an assumption.

## Guardrails

Unchanged. `data/` read-only, single declared output root, no model/blend/serving/config/
release change, topic branches only, no PR/merge/master push, NOT-DONE first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-floor-feature-integrity.md`: the stored-versus-
reconstructed comparison first, then the localization, then the missions if the gate allows.

Context: streak 7/14, lock ~2026-08-03. Storage merges here at 01:15 tonight; disk 171.6 GB.
