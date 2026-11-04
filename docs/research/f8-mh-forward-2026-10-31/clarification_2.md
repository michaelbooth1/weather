# F8-MH forward screen (ledger row 104): Clarification 2, PT-1 claims no date

Date: **2026-11-03.** Written by WS lane L59 on master's order (R21 item 4, rulings.md:200; master assigned it to L59 on 11-03). Docs only. No forward snapshot, METAR, `high_so_far`, label, price or receipt was read.

This file clarifies the frozen design `freeze.md` (sha256 `273c1070df0cb87c9c25366d5f8b37d61b766e2f0f2faa550c633e2a19523316`) and Clarification 1 (sha256 `eef842e8a40da1f9041a038bec6ab6ece6103d16235cb2b58c0231f3e115d260`). **Neither file, the code nor any pin in `SHA_PINS.md` is edited.** The regime, statistic, population, controls, labels, window, date gate (on or after 2027-01-27) and single look stay exactly as frozen and DECIDING.

## 1. Why

Master ruling R21 (2026-11-01; receipt `../pt1-not-runnable-2026-11-03/receipt.md`) found PT-1 with candidate C-PT NOT RUNNABLE under method rules 4 and 6. PT-1 will not be bound, so it will never have a look or a look receipt. freeze.md:87 orders F8-MH's look "on or after PT-1's look", and freeze.md:90 requires a receipt sha256 for each claiming look, PT1 included.

## 2. The PT1 slot

The PT1 receipt slot (freeze.md:90) takes the R21 NOT RUNNABLE receipt's raw sha256:

`8c45c8d99dabf1e38b21ad3ebd6e1b015a723b54054dd73d72e2373686cf7c35`

That receipt satisfies "on or after PT-1's look" (freeze.md:87). The look's own date gate, on or after 2027-01-27, is unchanged, and so is the order after every other claiming look (B/MG-2, MG-1, L6_G, row 72).

## 3. The §8 PT-1 row, restated

freeze.md:147 reads, as frozen: PT-1, "PT_D0 12-12 .. 01-25, look on or after 01-27", read only after PT-1's look. Restated: **PT-1 claims no date** (NOT RUNNABLE, R21). No F8-MH window date is held for PT-1. Its slot is the receipt above. F8-MH never alters PT-1 or any successor; a successor PT-1 under a new prereg would claim its dates in its own freeze and order itself by rule 9.

## 4. What does not change

Code, tests and `SHA_PINS.md` are unchanged. Clarification 1 stays pinned in code; this Clarification is a docs record that tells the look which sha to supply for PT1. No B-bound file is edited.
