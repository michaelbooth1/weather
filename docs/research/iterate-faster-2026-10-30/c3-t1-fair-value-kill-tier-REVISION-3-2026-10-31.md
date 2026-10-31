# C3 kill tier, Revision 3 (2026-10-31): the w gate (step 5) also uses the wider bounds (final before freeze)

Lane L16. This file amends **only step 5** of the C3 rule. The rule is now:

- the reviewed draft `c3-t1-fair-value-kill-tier-DRAFT.md`, sha256
  `cd4d814f4144a5e0a72d7632f413d000174d2cade4c4ce8d50f0ee5f6f76b5f6`;
- as amended by `c3-t1-fair-value-kill-tier-REVISION-1-2026-10-31.md`, sha256
  `f4cc6e02830935c0fac727a946ffc85112f8f803dc32ed352a46fcf205097916`;
- as amended by `c3-t1-fair-value-kill-tier-REVISION-2-2026-10-31.md`, sha256
  `23f2b0b3743cb485f0a18d6f44c8b841307cbde1c1d5e37c3960238bd7000fa8`;
- as amended by this file.

None of the earlier files is edited. Where they differ, this file wins. Nothing has been read: no row 80 data, and
no price or outcome after 09-29.

## 1. Step 5, "w holds" (replaces REVISION-2 §2, "Step 5 is unchanged")

Master ruled YES on 2026-10-31. Every interval in "w holds" takes the wider of the date-clustered and block-3
intervals: the minimum of the two lower bounds and the maximum of the two upper bounds. The block-3 interval is the
REVISION-2 circular moving-block bootstrap (blocks of 3 consecutive present dates, B 2,000, seed 20261024).

w holds when all three of these are true:

- mean w ≥ 0.05 (unchanged);
- the wider upper 95% bound of (blend − placebo) is below 0;
- the wider upper 95% bound of (blend − floor-only) is below 0.

Everything else is unchanged:

- steps 1-4, 6 and 7 of REVISION-1 §1, with REVISION-2's wider bounds;
- the power rule;
- the edge sizes;
- the K3 requirements, which still pass on this decision path.

The receipt keeps both intervals for each paired difference (`ci95_date_clustered`, `ci95_block3`, `ci95_wider`).

## 2. Freeze

The `pending` DEV_WINDOW_LEDGER row 100 pins:

- this file's sha as the final rule;
- the REVISION-1 and REVISION-2 shas;
- RULE_REVIEWED_SHA256 `cd4d814f…`;
- the final driver sha.

C3 runs only after the row 80 look receipt and export 2 both exist.
