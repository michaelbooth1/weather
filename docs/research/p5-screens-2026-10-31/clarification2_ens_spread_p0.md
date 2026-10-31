# Master Clarification 2 to Amendment A3: rule_ens_spread_p0 (row 93)

Date: 2026-10-31. Lane L17. Option (i), approved by master and relayed by the coordinator. It was written
before the row 93 re-read. No outcome, price or label was read to write it.

Scope: this clarification amends only the covered-iff `n_members` term of
`rule_ens_spread_p0.md` (A3, sha256
`25fc62bd2208fab2a88f1c51d2338456887bc6a51acabca0b6950dd6f2174c92`). Section 4's table and the
section 0 text say "51". Every other A1, A2 and A3 term stands unchanged, including the machinery, K = 2,
the blocks, the controls and the kill line.

## 1. Run 1 record

Run 1 (receipt `ens_spread_p0.json` sha256
`b37cca3ad2d7121705dd3581496af86fcf1f982bb9bf1aeb99c3107f0b1b97b4`, archived at
`C:\archive\ruled-out\_p5-ens\run93_A3`) is **UNTESTABLE**. Both arms had 0 coverage, because the premise
of 51 members was wrong. No candidate Δ was computed.

The run 1 synthetic controls passed:
- SYN+ 00-06: Δ 0.0943 [0.080, 0.112]
- SYN− 00-06: Δ −0.0855
- SYN+ 07-12: Δ 0.0999 [0.088, 0.114]
- SYN− 07-12: Δ −0.0647

## 2. Outcome-free member check

The check read only `src/weather/sources/free_screens/ecmwf_ens.py` and the G2 points build:
- the raw run files `data/research/free_sources/ecmwf_ens/raw/*.json.gz`, using the `member` field only;
- `receipts.jsonl`;
- `manifest.json`;
- the `n_members` column of `points.parquet`.

It touched no `t2m` value, outcome, price or label. The members are the GRIB key `number`: the control is
0 and the perturbed members are 1-50.

Every one of the 62 runs from 2026-07-30 to 2026-09-29 carries members **1-50**. **The missing member is
the control, number 0.** No perturbed member is missing. Of the index pieces, 372 list 50 `2t` fields per
step.

The 109 runs from 2024-08-15..09-30 and 2025-07-31..09-30 carry all 51 members, 0-50 (654 pieces of 51
fields). Those runs lie outside this rule's scope (2026 targets from 2026-07-31 to 2026-09-29).

In `points.parquet` (sha256 `bd761fa52869d244addda7fb3746276e1eb6aad2416ac2fdc3291750d7320a7e`, 3,751
rows), `n_members` takes the value 50 on 1,353 rows and 51 on 2,398 rows.

So in the rule's scope, `ens_sd_f` is the SD over the 50 perturbed members. It does not include the
control.

## 3. Clarified term

- **Covered iff** `available_utc` ≤ `captured_at_utc`, **`n_members` = 50**, and the value is finite.
- Any snapshot whose matched points row has `n_members` ≠ 50 is refused (not covered). That includes a
  row with 51 members.
- The candidate is the 50-member perturbed spread, without the control. The mechanism and the prior in
  section 1 are read with "51-member" replaced by "50 perturbed-member".
- The module pins this file by sha256 and records it in the receipt.
- The re-read is a separate invocation (run 2). It runs the SYN+ and SYN− controls in the same invocation.
  It counts +1 in the dev-window reuse ledger.
