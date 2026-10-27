# MG-3 refit note RF-1: the 07-12 blend weights refitted once against the season-matched L6

Written 2026-10-26 by lane L2, **before the refit**. No refit has run. No SM-L6 vector has been joined to a label.

## Authority

- **MG3-DC-1 §2.2** (rule `a7c69761…`): MG-2's 07-12 arm is the season-matched L6 (SM-L6), so MG-3's blend partner
  is SM-L6. The weights are "refitted ONCE by the unchanged rule `4fb02a2c…` function on dev 2026-08-01..09-29 with
  the bound L6 arm's dev vectors; ledger row 40 before the fit".
- **Coordinator, 10-26:** "Hash RF-1 and fill the row 40 tip before the refit."

## Only the partner changes

Everything in `rule_mg3_blend_weights.md` (`4fb02a2c…`) is unchanged except the L6 input row:
- layout;
- P3d_H vectors `a2dc30e2…`;
- fit dates 2026-08-01..09-29;
- coverage: P3d_H covered and partner covered;
- the minimiser `blend_weight` / `solve_weight`;
- w*(h) on all fit dates, h07-12.

| Input | Was (frozen table `c7b8ebc0…`) | RF-1 |
| --- | --- | --- |
| L6 partner | `l6_vector` from part `07a67425…`, nowcasts `3806687c…` | **SM-L6 dev vectors** `C:/t/l3/sml6/dev/l6_stack_season_dev_vectors.parquet`, sha256 `2366d67c5cdd6eb26b98064807210ade1c657829b7fa8e683535b94a9a2faa76` (L3, from the SM-L6 final state `800072c7…`, part `07a67425…`, nowcasts `714fa14e…`), joined on the layout `row_key` and `band_index` through the scorecard's own candidate path (`Table.candidate_vector`) |

## Checks (each refuses the refit; none is tunable)

1. **Control (unchanged rule, old partner):**
   - R-R's walk-forward weights reproduce to 1e-12 (`4fb02a2c` §2).
   - The old-partner w*(h) equal the frozen table `C:\t\l2\mg3\weights\blend_l6_H_weights.json` (sha256
     `c7b8ebc08d31ca30e5289d453ec2260bcc6659b32b379410f58b0d2b9b03530a`) to 1e-12.
2. **Vector identity:**
   - The parquet's sha256 is `2366d67c…`.
   - It has no duplicate (row_key, band_index).
   - Recomputing the partner with `l6_vector` (part `07a67425…`) and the season nowcasts
     `C:/t/l3/sml6/dev/nowcasts_season_dev.parquet` (sha256
     `714fa14e04c416da922803514fea1de8fe64459a0ea543878ddddfd6bc34896a`) gives the same vector to 1e-9 on every
     snapshot, with the same coverage mask.
3. **Coverage:**
   - Every fit-table snapshot that the old partner covered is covered by SM-L6.
   - Per hour, the share of P3d_H-covered snapshots with an SM-L6 vector is ≥ 0.95.

## Output

`C:\t\l2\mg3\weights_sm\blend_l6_H_weights.json`, with its sha256 sidecar, holding:
- w*(h) h07-12;
- the control, the old w* and |new − old| per hour, coverage per hour;
- the input shas, the module sha, this note's sha256 and the commit.

Nothing is overwritten. The old table stays as the Aug-Sep-L6 branch's record.

## Limits

- Data ≤ 2026-09-29. Labels are read (Brier minimiser), nothing is scored. Ledger row 40 covers this.
- The stated limitation of MG3-DC-1 §2.2 stands: Aug-Sep weights for an Oct-Dec partner are a fixed pre-declared
  choice, not season-matched.
- One refit. If a check fails, the refit stops and is reported. There is no second attempt without a new note.
