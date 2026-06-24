# 7. Bucket Boundary Logic [COMPLETE - TRANSITION PRIOR LIVE]

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

Implementation update (2026-06-15): complete. `bucket_transition_model()` now
returns numeric exact-bucket transition probabilities conditional on the printed
WU high at the effective cutoff, plus skip rate, update rate, and median first
post-cutoff update minute. `get_bucket_transitions()` still renders the
dashboard X/X+1/X+2/>=X+3 table, but now reuses that numeric payload. The final
distribution consumes the transition probabilities as a low-weight conditional
prior (`bucket_transition_model` and `bucket_transition_blend` components),
gated by sample size so it supplements rather than replaces the HGB and
late-day continuation models.

Verification:
- `.\venv\Scripts\python.exe -m pytest tests\model\test_bucket_transitions.py tests\model\test_market_units.py tests\model\test_estimate_distribution.py tests\calibration\test_intraday_calibration.py -q` -> 49 passed.
- `.\venv\Scripts\python.exe -m compileall src\weather\model\model_features.py src\weather\model\model_distribution.py`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - TRANSITION PRIOR LIVE`.
- The file contains 3 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

