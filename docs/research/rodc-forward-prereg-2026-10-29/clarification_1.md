# R-ODC forward (ledger row 72): Clarification 1, the P1 bounds check on the WU whole scale

Date: **2026-10-31.** Master's ruling, made before the look. Nothing of P1 has been scored, and no forward
snapshot, WU row, label or outcome was read to write it.

It clarifies the frozen pre-registration `docs/research/rodc-forward-prereg-2026-10-29/prereg-draft.md` (frozen
2026-10-30, D0 2026-10-31). That file is not edited. Where this file and the prereg differ on the P1 bounds check,
this file rules. Everything else in the prereg stands.

## Why

Pinned item 6 refuses an hour under `check_bounds`: the running min never rises, low ≤ current, and low ≤ high.
The frozen scorer (`rodc_forward_scorer.p1_day`, @ `2048c2f496680dd705f47dcc962fdd53dcaaa7d7`, lines 242-246)
compares mixed scales:

- low_so_far is already on the WU whole scale: `wu_whole_f`(min plausible temp_native, half_up) (pinned item 4);
- high_so_far and current_temp come from `_levels` (scorer lines 131-138) and are raw.

So a raw min of 33.5 with a raw current of 33.5 gives a low of 34 > 33.5 and refuses, although nothing is wrong.
Each refused hour counts as a mismatch in the ≥ 2 bucket (`_column`), so false refusals push P1 towards FAIL.

## The clarification

(a) **The scorer-side bounds check used by P1 compares low, high and current all on the WU whole scale**, each
mapped through `mg_serve_core.wu_whole_f(v, "half_up")` before `odc.check_bounds` runs. The running-min
comparison against the previous scored hour uses the same scale (the low is already whole, and the map leaves a
whole degree unchanged).

- The override is in the scorer only: `rodc_forward_scorer.clarified_check_bounds`.
- `odc_metar_features.py` (git blob `1cc4d565468bf4959137a8f6f6cec5b10adfce24`) stays **unchanged**, and so do
  its `check_bounds` and its features.
- The < 30°F plausibility filter in `odc_metar_features.kept_rows` stays exactly as frozen. It is part of the
  candidate.

(b) raw low ≤ raw high implies rounded low ≤ rounded high, so this removes false refusals and hides no real violation.

`wu_whole_f` is monotone non-decreasing: it snaps to the T-group tenth with `round`, then rounds half up. Scope
note: a gap smaller than one rounding step can vanish on the whole scale. In that case the served low and the
rounded high or current are equal on the scale the feature is served on.

(c) **The P1 verdict uses the clarified check.** A record's `refused` flag is the clarified check's result, and
`_column` and `p1_verdict` count it as before.

(d) **Disclosure, non-deciding.** The P1 report (`p1_verdict(...)["disclosure"]`) shows:

- the frozen-check refusal count (`refusals_frozen_check`, the pinned `odc.check_bounds` on the mixed scales,
  recorded per hour as `refused_frozen`);
- the clarified refusal count (`refusals_clarified_check`);
- per column, the mismatch rate with refused hours split out from real mismatches: `refused`, `refused_share`,
  `real_mismatch`, `real_mismatch_share`. Real mismatches are |diff| ≥ 2 or a one-sided None.

None of these fields enters the verdict.

(e) **Same rule as row 103.** If the clarified scorer refuses or errors at the look for any reason other than an
hour's bounds refusal counted under (c), the look stops and master rules. There is no rerun and no fallback.

## Pins

The scorer pins this file's sha256 as `CLARIFICATION_1_SHA256`. The new scorer blob and sha256 and the tests'
blob are recorded in `clarification_1_receipt.md` in this folder.
