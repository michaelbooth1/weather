# R-P Clarification RP-2: the translation span covers the arm's own keys

Written 2026-10-26, after the first `loyo` launch stopped with
`RPError: bucket 99 outside the span [64, 98]` inside the first inner fit, and before any gate, fit, score or
parity verdict was produced or read. It applies to `rule_rp.md` (sha256
`ed3236fa40cfc4cec35d2bcf1da129799716f399a3cb97199d3aa7fb632bbaa2`) as clarified by RP-1 (sha256
`f71a566a7d66808ccd1f2a9b4dc56fb38919ff0a21769e1d51b1621f182bea74`). It changes no gate, threshold, feature, arm,
grid, seed or kill.

1. **What the rule assumed.** Rule v3 ("Translation, Span") takes J = [min space, max space] for the market's
   `buckets[market]` and assumes every key of the arm lies in J.
2. **What R-A does.** `pooled_residual_model.predictive_distribution` gives mass to every integer in its own kernel
   range [floor(yhat + s(min z - 1.5)), ceil(yhat + s(max z + 1.5))], floor-censored, plus a 2% climatology mix on
   the bucket space. Arm keys can therefore lie outside the span of `buckets[market]`.
3. **Clarified span.** For each row, J = [min(space ∪ arm keys), max(space ∪ arm keys)], where "space" is
   `buckets[market]` as before and "arm keys" are the keys of that row's untranslated incumbent distribution
   (R-A's distribution on training rows; R-H's or P3d_N_fix's dictionary on dev). Every other clause applies
   unchanged on this J: edges go to its end integers, the floor moves mass onto F or the nearest end of J, and
   scoring sums over J.
4. **Why.** It is the only reading under which the translated arm at (a, b) = (0, 0) is the incumbent itself, as
   the grid's tie order and gate 2 (B_P vs B_N) presuppose. Clamping out-of-span mass onto the ends of the
   narrower J would alter the incumbent at δ = 0. Every label still lies in J.
