# C3 kill tier, Revision 2 (2026-10-31): wider of the date-clustered and block-3 bounds (final before freeze)

Lane L16. This file amends the C3 rule a second time. The rule is now:

- the reviewed draft `c3-t1-fair-value-kill-tier-DRAFT.md`, sha256
  `cd4d814f4144a5e0a72d7632f413d000174d2cade4c4ce8d50f0ee5f6f76b5f6`;
- as amended by `c3-t1-fair-value-kill-tier-REVISION-1-2026-10-31.md`, sha256
  `f4cc6e02830935c0fac727a946ffc85112f8f803dc32ed352a46fcf205097916`;
- as amended by this file.

Neither earlier file is edited. Where they differ, this file wins. Master reviewed REVISION-1 on 2026-10-31 and
accepted:

- its wording reading (§1 below);
- run-time power from the fixed formula as the power statement;
- the date-gate trace (no gate found; the read runs as is);
- the dropped `e89cbb523` dependency.

It then added one requirement, which is §2. Nothing has been read: no row 80 data, and no price or outcome after
09-29.

## 1. w-step KILL, stated both ways (REVISION-1 §1, step 6)

The w-step KILL at edge size holds when **the upper 95% bound of the gain (market − blend) is below 0.05 × the
mean market cell Brier on the scored dates**. This is the same condition as **the lower 95% bound of
(blend − market) being above −0.05 × that market Brier**. The bound is the wider bound defined in §2.

## 2. Deciding bounds use the wider of the date-clustered and block-3 intervals (new)

This follows S31 P0 Clarification 2 (`clarification_s31_p0_2.md`, commit `30bb432cbc89446a8802a6552627b44215b4bf1f`
on `claude/s31-venue-inventory-20261031`): when the block-3 interval is wider, the decision uses the wider bound.
Serial dependence is likely at T+1 over 14 dates.

- **Block-3 bootstrap.** The scheme is a circular moving-block bootstrap over the date-ordered target dates present
  in the stratum:
  - ⌈n/3⌉ blocks of 3 consecutive dates, each block wrapping at the end of the sequence, truncated to n dates;
  - converted to per-date counts and applied to the same per-date sufficient-sum rows (P0) and per-date Brier sums
    (w) as the date-clustered bootstrap;
  - B = 2,000 and seed 20261024, the same seed discipline as the date-clustered draws (driver `block_counts`,
    `BLOCK_LEN = 3`).
- **Why circular.** Every date gets equal expected weight. DWL row 84 found that plain moving blocks underweight the
  first and last dates.
- **Gaps.** "Consecutive" means consecutive in the ordered list of dates that are present. A date with no scored rows
  is skipped, not filled.
- **Wider bound.** The lower bound is the minimum of the two lower bounds, and the upper bound is the maximum of the
  two upper bounds. The SE is the larger of the two bootstrap SDs (ddof 1).

Each deciding quantity, from REVISION-1 §1 and §2, takes the wider bound as follows:

| Step | Quantity | Uses |
| --- | --- | --- |
| 2, power | SE_Δ in Φ(Δ_edge / SE_Δ − 1.960), and VIF = N × SE_Δ² | the larger SE |
| 3, P0 edge kill | Δ upper 95% bound < Δ_edge = 0.2236 | the larger upper bound |
| 4, P0 holds | BH at q = 0.10 on the one-sided p, and Δ lower 95% bound > 0 | the smaller lower bound; p = the larger of the two bootstrap p-values |
| 6, w edge kill | (blend − market) lower 95% bound > −0.05 × market Brier | the smaller lower bound |
| w power, reported only | Φ(edge_gain / SE − 1.960) | the larger SE |

- **Step 5 is unchanged.** The w gate (the draft's §3: mean w ≥ 0.05, and blend − placebo and blend − floor
  upper bounds < 0) keeps its date-clustered intervals. The block-3 intervals are reported beside it.
- **K3** uses the same decision path, so its positive, negation and null arms are judged on the wider bounds. They
  still pass in the driver tests.
- **Receipt fields.** The receipt keeps both intervals and both SEs:
  - P0: `delta_ci95_date_clustered`, `delta_ci95_block3` and `delta_ci95` (the wider, deciding one), with
    `se_delta_*`;
  - each paired difference: `ci95_date_clustered`, `ci95_block3`, `ci95_wider` and `se_*`.

## 3. Freeze

Master approved the freeze after this revision. The `pending` DEV_WINDOW_LEDGER row pins:

- this file's sha;
- REVISION-1's sha;
- RULE_REVIEWED_SHA256 `cd4d814f…`;
- the final driver sha.

C3 runs only after the row 80 look receipt and export 2 both exist. Nothing is computed before then.
