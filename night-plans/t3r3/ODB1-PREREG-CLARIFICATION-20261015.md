# OD-B1 pre-registration clarification: floor F and the extra fallbacks (2026-10-15)

**For the owner, before signing.** This note does not edit the pre-registration and changes no decision.

- Pre-registration: `docs/research/remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md` on
  `origin/claude/model-preregs-20261013` @ `d2dc8e661e82a9080bc607d8ea8150ea2a3611b2`.
- Stage build: `claude/t3r3-odb1-stage-20261015` @ `44a2fc2b66b0e706c1d48e83a49374f6e9f9587d`. Its artifact
  `remaining_rise_pmf_v1` has sha256 `b727fe1a897f8786afcd89514f0bae4a82d9e03ad951f2d72db9e228dd2afb09`.
- The master's lean is to amend the pre-registration so that it matches the floor the stage actually uses (the
  served floor).

The build implements both items below in their amended form. If the owner keeps the current text instead, the
stage module changes. That gives a new stage code hash and a re-freeze of `config/remaining_rise_floor_stage.json`.
The artifact and its hash are unaffected either way.

## (a) Floor F

**Current text**, at `docs/research/remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md:36`:

> 1. the captured 81a floor F, read as `guidance_physical_floor` (the METAR maximum since local midnight);

**Replacement text:**

> 1. the captured 81a floor F = max of the finite captured values of `guidance_physical_floor` (the METAR maximum
>    since local midnight), `high_so_far` and `trusted_current_max`, as the served 81a floor mask defines it; F is
>    missing only when all three are missing;

**Recommendation: amend.** The max of the three fields is how D2 draft §2 defines the 81a floor ("max of
`guidance_physical_floor`, `high_so_far`, `trusted_current_max`"). The development harness and MG-1 use the same
max. So the stage, the floor mask it applies and the comparator's floor all share one F.

**Context:**
- D2 draft §2 measured that `trusted_current_max` was null on every development row (WU was off). It also measured
  that `high_so_far` ties with the guidance floor after 07:00. The current text's "read as
  `guidance_physical_floor`" describes development practice, not a different rule.
- Today the max and the single field give the same B, so the change costs no power. It only fixes which rule
  governs if `trusted_current_max` is ever populated during the holdout.
- That field is captured at serve time, so it is point-in-time legal. Every floor input must still pass the §8
  PIT validity condition.

**Owner question:** OD-B1a — Amend §1 item 1 so that F = max(guidance_physical_floor, high_so_far,
trusted_current_max), matching the served 81a floor (recommended), or keep F = guidance_physical_floor alone?

## (b) Fallbacks

**Current text**, at `docs/research/remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md:45-46`:

> **Stage:** P(H = B + e) mapped to bands, then the 81a floor mask and renormalisation; fallback to served when F or the
> cell is missing, the METAR payload is flagged `stale`, or the floored mass is 0; placed **after** the final

**Replacement text:**

> **Stage:** P(H = B + e) mapped to bands, then the 81a floor mask and renormalisation; fallback to served when the
> market's native unit is not °F, the artifact hash read at serve differs from the frozen hash, the snapshot's
> station-local date is not the target date, F or the cell is missing, the METAR payload is flagged `stale`, or the
> floored mass is 0 (each fallback row records its reason); placed **after** the final

**Recommendation: amend.** All three added fallbacks are already implied by the rest of the pre-registration:

| Fallback | Why it is already implied |
| --- | --- |
| Unit not °F | The artifact is in °F and the scope is US11. |
| Artifact hash mismatch | The §8 artifact validity condition requires the frozen hash on every eligible row. |
| Snapshot not on the target local date | The cell key is the local clock hour on the target day, and the artifact holds only same-day rises. |

Naming them closes the gap between the text and the code before the hash is signed.

**Context:**
- **Coverage:** none of the three can fire on a valid 13-16 US11 row. A °F market at local 13:00-16:59 on its target
  date, with the frozen artifact, never meets any of them.
- **Artifact mismatch on an eligible row:** the stage falls back to served, and the row records reason
  `artifact_hash_mismatch` and the hash it read. §8 still makes that row void the look, so the fallback never
  substitutes for the validity condition.
- **Earlier-day snapshots:** snapshots taken before the target date fall back instead of borrowing a same-day cell.
  This only affects rows outside the 13-16 primary.

**Owner question:** OD-B1b — Amend §1 "Stage" to name the three added fallbacks (unit not °F, artifact hash
mismatch, snapshot not on the target local date) as implemented (recommended), or remove them from the stage code?
