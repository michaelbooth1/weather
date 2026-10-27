# MG-3 freeze prep (1a-ii): frozen blend_l6_H weights w(h), h07-12 (rule, written before the fit)

Written 2026-10-26 by lane L2, **before the weight fit**, on master's instruction relayed by the coordinator ("frozen
blend_l6_H weights … own rule and ledger row pushed BEFORE its fit … reproduction check against … blend outputs").

**Evidence class: a freeze of R-R's already-scored blend.**
- **Labels read:** dev labels (2026-08-01..09-29) are read, because the weight is a Brier minimiser. This is why the
  rule has a DEV_WINDOW_LEDGER row.
- **Not scored:** nothing new is scored. The fitted table is not a candidate result; it is counted under R-R's
  existing candidate row.
- **Binds nothing.** MG-3 binds only under its own forward rule.

## 1. Construction (R-R's code, unchanged)

The blend is R-R's `blend_l6_H`:
- p = w(h) · p_P3d_H + (1 − w(h)) · p_L6, a **linear pool**;
- **w by hour:** one w per local hour h07-h12;
- **pooled:** over markets;
- **minimiser:** the exact Brier minimiser on [0, 1] (`blend_weight` and `solve_weight`, unchanged).

The serve-time MG-1 fallback and the rule-4 floor are MG-3's, as in R-R's scoring.

**Inputs,** exactly those of `rung_r_score` (rule_rr.md `e3d92e1a…`):

| Input | Identity |
| --- | --- |
| Layout | `C:\swarm\v3layout` (dev scorecard `load_layout`, `make_folds(…, 7, 1, 7)`) |
| P3d_H dev vectors | `C:\t\l2\rungr\emit\dev_P3d_H.jsonl` `a2dc30e2b0790ad4cf4ed167c329c00a6c87d4245fb1d6a55d0f80ffdfc14f3d` (byte-identical to what the frozen 07-12 state re-emits, rule_mg3_p3dh_state.md §3) |
| L6 | `l6_vector` from the MG-2 coefficients `C:\t\mg2\freeze_cap\mg2_coefficients.json` (part `l6_stack` `07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9`) and the nowcasts `C:\t\mg2\l6cap_ctl\nowcasts.parquet` `3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3` |
| Fit dates | `BLEND_FIT_FIRST` 2026-08-01 .. 2026-09-29, the dev scorecard `Table` over those dates |
| Covered | P3d_H covered and L6 covered (as R-R) |

## 2. Positive control (must hold before the frozen table is written)

- **Recompute** R-R's walk-forward weights w(h, d) (`walk_forward_weights`, scored dates of the folds) for both
  `blend_l6_H` and `blend_l6` (P3d_N_fix vectors `C:\t\l2\rungr\emit\dev_P3d_N_fix.jsonl`
  `cd0034b9faec0b687e1184187feeaa39ab151c5f9f8d1c905d3a49a0e7089542`, as R-R).
- **Reproduce** `C:\t\l2\rungr\score\rr_score.json` (sha256 `577b689b6285d6125357b4f658351deaf1c47171352753f6956d29b278261dab`)
  `weights` (first, last, mean per hour) to **1e-12**.
- **FAIL** stops the freeze, with no frozen table.

## 3. The frozen table

w*(h) = `solve_weight(A[sel], B[sel])`, where sel = covered snapshots at local hour h on **all** fit dates
(2026-08-01..09-29). That is one weight per hour, fitted once, as `mg3_design_DRAFT.md` §a.2 proposes.

**Also reported** (not adopted):
- the walk-forward mean and last values per hour;
- |w* − last| per hour.

The choice between the all-dev fit and the last walk-forward value stays with the coordinator or master, per the design
draft. This rule writes the all-dev table and reports the alternative.

## 4. Outputs (outside the repository)

`C:\t\l2\mg3\weights\`:
- `blend_l6_H_weights.json`: w* per hour, the control result, the input shas, the module sha, this rule's sha256 and
  the code commit;
- its sha256 sidecar.

Nothing is overwritten.

## 5. Limits

- Data ≤ 2026-09-29.
- No market price enters the weight. The dev scorecard table loads its capture-time market column (dates ≤ 09-29,
  as every dev rung does), but the weight is a Brier on labels only.
- No change to MG-2, B, PT-1 or MG-1.
- The table becomes binding only through MG-3's forward rule.
