# Row 90 amendment 1: controls only (lane L8, 2026-10-30)

Committed before the controls run, and before any code for it was written. The amendment changes no input, no
candidate and no verdict rule of `rule_toronto_eccc_p0.md` (sha256
`b8718b46d0244054be26834a0a35d28f0ff2ed45d8056e0393334ce5df4b0b0d`). It adds three controls that the first run
did not carry, because the rule ran them only for a survivor.

## Why

Master ruled row 90's KILL PROVISIONAL (2026-10-30). GEM-SEAMLESS has ρ_c −0.1724 [−0.3247, −0.0085], with the CI
excluding 0 on the negative side. That is what a sign or orientation bug in a newly ported table would leave. The
disagreement placebo cannot catch it, because it inherits the same table.

## Leakage

These are the dates and outcomes already read under this rule (07-12, 08-01..09-29). Control 2 also reads 13-16
on the same dates, which row 77 already read with the same tapes and labels. No date after 2026-09-29 is read,
and nothing from 09-30..10-15.

## Inputs (unchanged, pinned)

- Replay SHA256SUMS `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82`.
- Tape SHA256SUMS `a07966fbcf89b0563d3eab91797e1f12fe475715daab15f5fbc876665b09d2c0`.
- WU CYYZ label files `1ced925a605b6f4e82fa20cbe238b9c91d841a9390da604bc648b630dac920e1` and
  `c9e16b1d4cf624cde3f4b6b02cde5d483747a7ed67f70750fd1f5cc27594433a`.
- Control 2 only, read-only from row 77's run:
  - `C:/t/l8tor/p0_out/arms.json`, sha256 `16ba22cfcd14dd7ecb6c53e42237ca5ddceb2f98d2f7865e1849d422ac2ee3d5`;
  - `C:/t/l8tor/p0_out/receipt.json`, sha256 `6baa2703f144fc8bcf0226d6e5542a2ca11903edef83fee89368290037c7876b`.

## Control 1: the w = 0 identity

`market_blend.w0_identity(score_t, restrict(c_fit))` on the 07-12 tables, for GEM-SEAMLESS, CITYPAGE-FH and the
synthetic SYN+ of control 3. PASS iff `max_abs_diff == 0` and `R_all_hours == 1` for each.

## Control 2: row 77 reproduction through the ported table

Row 77's receipt prints **no served or MG-1 control line**. `mr_gate.market_controls` was not run there: its MG-1
expectation is the US pooled value, and Toronto has no MG-1 frame. There is no served or MG-1 value to match.

This control instead reproduces row 77's printed P0 lines from the ported table. That is a stronger check, because
it exercises m, y, the band order, the floor mask, the population and the placebos end to end.

1. Build the ported table with local hours 07-16 (row 77's block), on the same dates, burn-in and pinned inputs.
2. Inject row 77's Arm A and Arm B band vectors from `arms.json`, exactly as row 77's driver did:
   - floor-impossible bands set to 0;
   - renormalised to sum 1 on the covered snapshots;
   - the market elsewhere.
3. Run the same 20 disagreement placebos, the paired P0 (10,000 draws, seed 20261024) and the c-deranged
   diagnostic.

Values matched against `receipt.json` `6baa2703…`:

| Item | Expected |
| --- | --- |
| Fit table snapshots | 4,688 |
| Score table snapshots | 3,584 |
| Population snapshots | 3,447 (both arms) |
| Population dates | 46 (both arms) |
| Fit covered | 4,677 (both arms) |
| Arm A ρ_c | +0.03764172837095834 |
| Arm A mean ρ_pl | −0.001095181676727265 |
| Arm A Δ | +0.038736910047685605 [−0.07616574804555928, +0.15018103228313204] |
| Arm A p | 0.24897510248975102 |
| Arm A c-deranged ρ | −0.012223825461082728 |
| Arm B ρ_c | −0.012324213602725504 |
| Arm B mean ρ_pl | −0.027182155258833014 |
| Arm B Δ | +0.01485794165610751 [−0.085185576074755, +0.11407750799243875] |
| Arm B p | 0.39906009399060094 |
| Arm B c-deranged ρ | −0.018079928713931107 |

PASS iff every count is equal and every statistic matches to the printed precision (|difference| < 5e-5,
4 decimals). The maximum absolute difference is reported.

## Control 3: synthetic positive control

Population: the 07-12 fit table, with every fit snapshot covered.

- For snapshot i on date d, let μ_i be the market mean (`band_geometry`, the same μ the type C signal uses) and
  Y_d the pinned WU CYYZ label (native °C).
- The realised market residual is r_i = Y_d − μ_i.
- σ is the population SD of r over the fit-table snapshots.
- ε_i ~ N(0, σ²), drawn by `numpy.random.default_rng(20261031).normal(0, σ, n_fit)` in fit-table snapshot order.

Two injected candidates, each through the full row 90 path (type C, sign +, `mr_sweep.p0_candidate`):

- **SYN+**: value μ_i + r_i + ε_i (that is, Y_d + ε_i).
- **SYN−**: value μ_i − (r_i + ε_i).

BH is applied at q 0.10 over this pair, K = 2.

- **SYN+ PASSES** iff it is testable, BH-rejected, has Δ > 0 with a Δ 95% lower bound > 0, passes control 1, and
  passes the 07-12 w gate (`mr_gate.gate_candidate`, with c_pl,0 as the placebo).
- **SYN− PASSES** iff its point Δ is < 0. Its CI is reported.

## Outcome (pre-declared)

- All three controls PASS: the row 90 KILL stands. GEM's negative ρ stays descriptive.
- Any control FAILS: row 90 is VOID. The port is fixed, the fix is disclosed (its diff goes to the coordinator
  first), and row 90 is re-run once under the same rule.

## Run

- A new `--controls-only` mode of `loyo_screen toronto-eccc-p0`, with a new `--out` (`C:/t/l8tor/eccc_ctrl`) and
  tests.
- Admission by the coordinator, then one `workstation_heavy -Queue` run from a clean worktree.
- It writes only under `--out` and never overwrites.

Standing rule from master: any P0 on a newly ported or built table carries controls 1-3 in its first run.
