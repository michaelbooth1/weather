# F8-MH forward screen (ledger row 104): Clarification 1, scope statement and two non-deciding disclosure splits

Date: **2026-10-31.** Master's ruling (b) on regime breadth, made before any forward read. No forward snapshot,
METAR, `high_so_far`, label, price or receipt has been read for any window date, and none was read to write this.
The S0 receipt is unchanged and S0 was not re-run.

This file clarifies the frozen design `docs/research/f8-mh-forward-2026-10-31/freeze.md` (sha256
`273c1070df0cb87c9c25366d5f8b37d61b766e2f0f2faa550c633e2a19523316`) and the S0 spec `s0_spec.md` beside it. Neither
file is edited. **The frozen regime (freeze §2), statistic, population, controls, labels, dates and single look stay
exactly as frozen and DECIDING.** This file adds a scope statement and two disclosures. It changes nothing that
decides.

## Why

S0 (receipt `s0_receipt.md`) showed that the frozen flag fires on 32-43% of market-hours at 04-06 on Oct-Dec history.
With the NBM gate G dropped before any count, "midnight-set max and ≥ 3°F drop by the cutoff" also holds on ordinary
radiative-cooling nights, not only on frontal midnight highs. Master ruled (b): the frozen regime stays deciding, and
its scope is stated as it is.

## 1. Scope (verbatim)

The arm tests: "01-06 book mass above H on cooling nights (midnight-set max, ≥ 3°F drop), broader than the frontal story".

**A KILL at edge size closes the broad version only.** It does not close a narrower frontal-signature arm (a
regime that adds, for example, a dewpoint drop, a wind shift or a pressure rise). Any such arm would be its own row,
frozen before its own count. Equally, a SCREEN-POSITIVE result here would describe cooling nights in general, not
fronts in particular.

## 2. Two disclosure splits (non-deciding)

Both splits use the same statistic and the same method as the frozen disclosures (freeze §7): the frozen
`mr_sweep.p0_candidate`, type C toward H, on the **same** regime population, with zero tilt (value = the market mean)
outside the subset. They are reported at the look. **They never decide, never label, never gate and never change the
verdict, the population or a control.**

(a) **Hour band:** local hours 01-03 against local hours 04-06.

(b) **Day max equal to H on the WU whole scale, or not.**
- "Equal" is the frontal case: the midnight-set max was the day's max. "Not equal" means the day rose above H later.
- The day max is the snapshot's `settlement_high` from the look layout's labels, mapped through
  `mg_serve_core.wu_whole_f(v, "half_up")` (a whole degree is unchanged). It is compared with the snapshot's H.
- **This split is OUTCOME-DEFINED.** It is computed only at the look, from the labels, after the verdict and its
  numbers are fixed. It is disclosure only and never a label, a filter or a gate.
- No forward label is read for it before the look gate opens. A snapshot whose `settlement_high` is missing or not
  finite falls in neither subset and is counted. If the labels carry no `settlement_high` column, split (b) is
  recorded as unavailable and the look continues. A disclosure problem never stops or changes the look (it is not
  a rule (e) event).

## 3. Code

- `tools/research/forward_f8/f8_mh.py` pins this file's sha256 as `CLARIFICATION_1_SHA256` and checks it in its
  guards.
- The two splits are returned under the statistic's `"disclosure"` key with `"non_deciding": true`, the same way
  row 72's Clarification 1 did. The frozen `"disclosure_non_deciding"` key stays as it was.
- The verdict path is unchanged. A synthetic test shows that the label, the testable flag, the D3 numbers, the
  result and the controls are identical with and without the disclosure.
- No B-bound file is edited. The imports stay read-only and blob-checked against B's manifest.
- The new code sha256 is recorded in `SHA_PINS.md`.
