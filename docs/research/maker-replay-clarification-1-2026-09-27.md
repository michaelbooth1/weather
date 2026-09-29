# Maker replay Clarification 1 — prospective panel shift, 2026-09-27

**Status: prospective, UNSIGNED clarification; option A approved by the owner on 2026-09-27.**
Owns only the changes below to the [frozen registration](maker-replay-hurdles-preregistration-2026-09-27.md)
and [frozen execution addendum](maker-replay-execution-addendum-2026-09-27.md). Both original files remain unchanged.
Read all three before calibration, manifest construction or scoring. This document is not an execution approval.

No real calibration, quote-panel, settlement, wallet or replay-result data was read to choose or implement these
changes. Implementation and verification use synthetic fixtures only. The original calibration window had only two
possible capture dates after 88a began on September 25, below its three-date minimum. Thus every city necessarily
fell back to 1.0; the informed policy's net screen suppressed quoting. This is a structural finding, not a data result.

- Calibration uses exactly **2026-09-27 through 2026-09-29**, three closed UTC 88a capture dates. The three-date
  minimum, 1,440 complete band-minute minimum, 30 occupied-minute minimum and quantile rule are unchanged.
- The quote panel is **2026-09-30 through 2026-10-13**, fourteen closed UTC dates. **2026-10-14** supplies settlement
  only, with no active quote intervals or date clusters. The single scored look is **2026-10-15 America/Toronto**.
- A city failing any sparse threshold uses the **pooled all-city Clopper-Pearson upper bound**, applying the same
  `q = 1 - 0.01/M` rule to pooled n/x and distinct contributing dates. Only sparse or empty pooled inventory (or the
  addendum's unavailable/uncomputable fallback) retains `U_m = 1.0`. Report each city's own counts, fallback reasons,
  pooled counts and bound. The scalar remains `hazard_per_minute = max_m U_m` after fallback.
- **05:00–08:00 UTC** on every quote-panel date is prospectively inactive for every policy because production
  quiet-window integrations may restart capture then. These intervals are exclusions, never zeros, and five-minute
  pull horizons crossing them are excluded. This exclusion does not change the calibration denominator.
- Exclude T+2 conditions whose local target date is after **2026-10-14** from the quote universe. Retain them in the
  discovered inventory with an explicit exclusion reason; they cannot create unresolved positions beyond the panel.
- The new authorization ID is **`maker-replay-2026-10-15-v1`**. After the owner signs these exact bytes, production
  appends `REVOKE_MAKER_REPLAY` for `maker-replay-2026-10-12-v1` and a new `APPROVE_MAKER_REPLAY` binding the raw-byte
  SHA-256 of the registration, addendum **and this clarification**. No owner-log row is written by this fixture task.

Everything else remains unchanged, including policy/pricing/fill semantics, the strict net screen, adverse-loss
input, starting portfolio and caps, coverage exclusions, estimator rounding, bootstrap settings, hurdle conjunction,
no interim scored reads, one-look restriction and separate live authority. A failure is reported without extending
the panel or moving the look. Final manifest verification and independent hash enrollment are separate production steps.
