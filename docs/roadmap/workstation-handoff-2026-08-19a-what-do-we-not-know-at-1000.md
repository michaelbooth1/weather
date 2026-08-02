# Workstation handoff 2026-08-19a — what do we not know at 10:00?

Run this now. It produces **no candidate and no artifact**, and consumes no fresh dates.
`-08-16a` remains queued for 2026-08-05 04:30.

## Why there is no candidate in this mission

`-08-18a` failed on the folds it was fitted on — positive excess `+77.3%`, severe rows
`1,797 -> 3,665`. That is not overfitting; it is the mechanism being wrong.

My reading, which section 1 should confirm or refute: the continuation objective worked because the
floor is a **hard lower bound**, so `D = Y - F` with `D >= 0` genuinely restricts the support. The
forecast is not a bound — `Y` lands on either side — so `Y - forecast` restricts nothing and is
merely a shifted target that the model already consumes, `forecast_gap` having non-zero splits in
154 of 168 bundles.

Three candidates already compete for a shrinking pool of fresh dates. A fourth before the first is
validated is the family-wise error problem that produced the item-224 leakage win. So this mission
deliberately builds nothing.

## 1. Post-mortem: confirm or refute the constraint rule (short)

Test the proposed rule against the evidence you already hold:

> **Anchor reparameterization pays only when the anchor is a constraint, not merely a predictor.**

Does the development evidence support that reading of the `-08-18a` failure, or was it something
else — conditioning, support width, prior mis-specification, or the smoothing form? If the rule
holds, state which other anchors it rules out in advance (climatology, persistence, blend centre,
market mid). If it does not hold, say so; a wrong rule confidently held is worse than no rule.

Keep this short. It exists so we do not repeat the error, not as an end in itself.

## 2. The main question: what information is missing at 10:00?

The excluded population — `floor_available` false or `floor_removed_mass <= 0.20` — carries **81.21%
of remaining positive excess** and **80.10% of remaining severe rows**, and holds **84.58%** of the
09:00–14:00 primary-objective window. The floor is silent there and the forecast is already
consumed. The recorded diagnosis for this project's overall gap is **information, not calibration**:
98.88% resolution against 1.12% reliability.

So: **what do we not know at 10:00 that would move the centre?**

Deliver an audit, not an experiment:

1. **Inventory what the model actually consumes** for early and mid-day rows — which features are
   selected and split on at hours 9–14, and which declared-but-unused fields exist.
2. **Inventory what we capture but do not use.** Fields present in the payloads or sidecars that
   never reach the feature matrix.
3. **Inventory what we do not capture at all.** The highs-projection audit named 850T/mixing height,
   soil moisture, forecast shortwave, and smoke/AOD. Re-derive that list against current code rather
   than trusting the record, and add anything it missed.
4. **Marine features went dark on 2026-06-13** with no refresh, and three of the top-five
   disagreement bands were marine markets. Establish what is actually broken — capture, refresh, or
   feature construction — **read-only**. Do **not** backfill anything: serving reads that path.
5. **Rank by expected value on the excluded population specifically**, not on aggregate Brier. For
   each candidate input state: what it would plausibly explain, how it would be obtained, whether it
   is free or metered, and what would falsify its value cheaply.

## 3. What I want to be told even if it is unwelcome

- If the honest answer is that no available input plausibly closes an 80%-of-loss gap at 10:00, say
  that. It would reframe the whole objective and is worth more than a list of marginal ideas.
- If the answer requires a paid provider, say so with a cost estimate and do **not** procure or
  configure anything.
- If some of the gap is irreducible — genuine atmospheric uncertainty at that lead time that the
  market prices better only because it aggregates more information than any single forecast — say
  that too, with whatever evidence bounds it.

## Constraints — unchanged

- Base on `codex/workstation-forecast-residual-anchor-2026-08-18a` @ `ed0f5ffe`. Every branch in this
  chain is held and unmerged. Do not merge any of them.
- **No candidate, no artifact, no fit, no scoring.**
- **Do not read, enumerate, evaluate, or substitute 2026-08-01 → 08-03** (reserved for `-08-16a`) or
  **2026-08-06 → 08-19** (final confirmation set).
- **Do not backfill, repair, or write any feature, sidecar, or marine path.** Read-only inventory.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change or procurement.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. A ranked, falsifiable list — or a
well-evidenced statement that the gap is not closable with available inputs — is the deliverable.
