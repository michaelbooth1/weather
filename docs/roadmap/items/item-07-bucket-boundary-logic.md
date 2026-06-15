# 7. Bucket Boundary Logic [IMPLEMENTED - REFINEMENT NEXT]

- [x] Explicitly model exact bucket risk around 24/25/26 C.
- [x] Add conditional probability tables:
  if current max is `X`, probability final is `X`, `X+1`, `X+2`.
- [x] Track whether WU history tends to print whole-degree updates late or skip
  intermediate buckets.

Codex audit (2026-05-28): partial. `get_bucket_transitions()` produces a
dashboard table for current bucket to `X`, `X+1`, `X+2`, and `>= X+3`, plus a
skip-rate statistic. Issues found: the logic is generic to the current bucket,
not explicitly centered on 24/25/26 C, and it tracks skipped intermediate
buckets but not late whole-degree update timing.

Codex update (2026-05-31): the generic transition panel is useful and should
stay, but accuracy work should move beyond display. The next version should
feed calibrated continuation and skip/timing probabilities back into the final
distribution, especially near exact buckets where Polymarket prices can be
sticky.
