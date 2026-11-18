# One-sided edge maker — second replay registration, DRAFT 2026-09-29

**Status: DRAFT, UNSIGNED. z, a, K and the skilled-cell list are deliberately open. No scoring authorization.**
Proposes the second candidate's single offline replay look. Written by the 110w workstation mission; the owner
signs (or rejects) it after the 2026-10-15 reliability table. This is a prospective protocol, not a result, and not a
live-trading approval. The first registration
([hurdles](maker-replay-hurdles-preregistration-2026-09-27.md),
[execution addendum](maker-replay-execution-addendum-2026-09-27.md),
[clarification 1](maker-replay-clarification-1-2026-09-27.md)) is frozen and is not amended by this file.

## Calendar

- Quote panel: **2026-10-16 through 2026-10-29 UTC inclusive** — 14 closed 88a capture dates.
- Settlement-only bundle: **2026-10-30 UTC**; empty active intervals, no quote minutes or clusters.
- Single scored look: **2026-10-31 America/Toronto**, only after signature, input seal and authorization checks.
- The same no-extension, no-replacement, no-repeat rules as the first registration apply. A miss is BLOCKED or
  UNDERPOWERED; a successor needs a new dated owner-signed registration disclosing every previous read.
- Code boundary: the candidate's sources live under `src/maker_core/`, which the first exam's execution manifest hashes
  in full. They must not be adopted on production master before the 2026-10-15 look has executed.

## Candidate and comparators

The candidate is **`one-sided-edge-v0`** (`maker_core.quoting.one_sided`, replay adapter
`maker_core.replay.one_sided`, report `maker_core.replay.one_sided_report`), at the commit the execution manifest pins.
Comparators on identical captured inputs and starting portfolio/cap assumptions: **`informed-v0`**, **`blind_re1`**,
**`no_quote`**, **`clock_only`**. The clock control is exposure-matched to the **candidate's** pull fraction.

Registered semantics (the code is authoritative; this summary is not an amendment):

- All informed-v0 safety gates; horizons T+0, T+1, T+2.
- Side only from evidence-backed signals. (i) Observation decidedness from the plugin clock with the band shape read
  from captured band rows: a dead band quotes NO only; YES is never quoted on it; NO is never quoted on a reached
  open-top band; an unknown or conflicting band shape quotes nothing. (ii) A model-probability side only when
  `(model_id, horizon)` is in the signed skilled-cell list, the view is `scored`, and
  `z*sigma_eff + a <= |p - mid| <= K*sigma_eff`.
- No signal, or an edge inside the margin: the unchanged symmetric informed-v0 decision.
- One leg at the tightest reward-eligible distance; one-sided reward score `S/3` inside a [0.10, 0.90] mid, else no
  quote; at most one one-sided YES leg per event; pulls on `pull` hints and on `widen` until a fresh view (a dead band's
  NO leg is exempt: the running maximum only rises); cancel on side flip; a filled band holds to settlement.
- Net screen: modeled rewards minus the conservative hazard cost. Expected edge is recorded, never credited.

## Inherited without change

Hazard recipe (execution addendum and clarification 1), fill bounds (strictly_through primary, at_price sensitivity),
`k = 1.0` primary and `k = 0.5` sensitivity, the estimand (mean paired total modelled net per complete market/UTC-day),
2,000 replicates, base seed 20260926 with the seed-plus-one crossed convention, two-sided 90% percentile intervals,
date and crossed date x market inference, and the minimums: 14 quote dates, at least 10 date and 10 market clusters per
contrast after exclusions, at least 100 valid replicates. Exclusions stay exclusions, never zeros.

## Hurdles

1. **Economic:** all four lower bounds strictly above zero under strictly_through, `k = 1.0` — candidate minus
   `blind_re1` and candidate minus `no_quote`, each under date and crossed inference. Same conjunction as the first exam.
2. **Fill endpoint (new):** settlement markout per filled share,
   `(settled value of the filled outcome - fill price)`, averaged per complete market/UTC-day cell of the candidate's
   fills, equal-weight across cells. The **lower 90% bound must be strictly above zero** under strictly_through, under
   both date and crossed inference. A cell with any unresolved fill is dropped whole. Fewer than 10 clusters on either
   axis, or fewer than 100 valid replicates, is UNDERPOWERED.
3. **Reported, not a hurdle unless the owner adds it at signature:** candidate minus `informed-v0` (the question this
   candidate exists to answer), `clock_only`, all `k = 0.5` and at_price contrasts, and the fill endpoint under at_price.

`REPLAY_HURDLES_MET` requires hurdles 1 and 2, every admission minimum and a valid authorization.

## Open parameters — owner signature step after 2026-10-15

| Parameter | Constraint | Value |
| --- | --- | --- |
| `z` | finite, > 0 | PENDING — from the 10-15 reliability table |
| `a` | finite, >= 0.0043 | PENDING (code default 0.0043) |
| `K` | finite, > 0 | PENDING — from the 10-15 reliability table |
| Skilled cells `(model_id, horizon_days)` | cells the table marks skilled | PENDING; empty keeps the model side off |
| Informed-v0 contrast as a hurdle | yes / no | PENDING |
| Pull-efficiency hurdle for this candidate | yes / no (not proposed) | PENDING |

These values enter `EdgeReplayConfig.profile`, so the manifest's `replay_config` binds them. Fixing them after seeing
any panel date voids this registration. The execution pack for this exam (manifest, one-look receipt, CLI path) is
not built yet; it follows the parameter signature.

## Owner-signature block — unsigned

| Binding | Owner attestation |
| --- | --- |
| Owner / decision-log authorization ID | PENDING |
| Decision | PENDING — approve one offline scored look only |
| Frozen protocol path, commit, raw SHA-256 | PENDING |
| Execution manifest path and raw SHA-256 | PENDING |
| Quote dates / settlement-only date / look | 2026-10-16..2026-10-29 UTC / 2026-10-30 UTC / 2026-10-31 |
| Pre-score attestation | PENDING — parameters and criteria frozen before any scored read |

No simulated signature. Approval to write or push this draft is not signing. Recheck the
[reserved-window status](../operations/reserved-confirmation-window.md) before any input access.
