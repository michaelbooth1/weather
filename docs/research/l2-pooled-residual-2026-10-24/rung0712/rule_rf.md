# L2 rung 07-12 R-F pre-registration (blends vs the composite's actual pre-13 arm, MG-1 + L6)

Written 2026-10-25 before any R-F row exists. R-D rule C:\t\l2\rung0712\rule_rd.md (sha 7d497e3c...), R-D result
C:\t\l2\rung0712\blend\rung_blend.json (sha 53ba558b...). Development evidence only; no edge claim; nothing after
2026-09-29; nothing touches MG-2 or L8's branch.

## Arms (07-12, identical rows)

- **L6 (incumbent):** the MG-2 pre-13 arm, `free_source_candidates.l6_stack.predict` byte-identical to L8's
  `claude/mg2-composite-binding-v2-20261025` @ 710f0c672, frozen coefficients C:\t\mg2\freeze_cap\mg2_coefficients.json
  part `l6_stack` whose canonical sha must equal 07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9
  (refused otherwise), nowcast C:\t\mg2\l6cap_ctl\nowcasts.parquet whose file sha must equal
  3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3 (refused otherwise). No refit. Caveat stated now:
  the frozen L6 coefficients were fitted on every dev snapshot through 2026-09-29, so on this window the incumbent is
  in-sample (favours L6).
- **blend_mg1:** R-D's walk-forward blend of MG-1 and P3d_N_fix, recomputed by the same rule (must reproduce R-D's
  07-12 dR vs MG-1 -0.0467 to 1e-9: positive control).
- **blend_l6:** the same construction with L6 in place of MG-1: p = w * p_P3d_N_fix + (1 - w) * p_L6 where both are
  covered (else p_L6); w(h, d) = exact Brier minimiser over [0, 1] on covered snapshots at hour h dated in
  [2026-08-01, d).
- **Controls:** the `mg1.predict` vector equals `loss_atlas.mg1_frame` (max abs diff reported, must be <= 1e-12);
  L6 equals MG-1 exactly outside 07-12 and where the nowcast is missing (counts reported).

## Population, intervals, reading

- Same as R-A / R-D: scorecard folds 2026-08-01..09-29 (scored 08-15..09-29), crossed date x market and
  date-clustered 95% intervals, 2,000 draws, seed 20260921; dR = mean_cell(Brier_arm - Brier_ref) /
  mean_cell(Brier_market); capture-time inputs (P3d_N_fix vectors cd0034b9..., B_N 83cf9bbe...).
- References: L6, MG-1, P3d_N_fix, B_N, served. Scopes covered (arm, reference, L6 and P3d_N_fix all covered) and
  blended. Groups 07-12, h07..h12; pools ALL, PRIMARY5 (descriptive), per market.
- **Reading (PRIMARY: ALL, covered, 07-12, date-clustered), per blend:** WIN vs L6 if upper < 0 and no hour h07..h12
  has lower > 0; HARM if lower > 0; otherwise NULL. Crossed intervals, PRIMARY5 and per market are reported only.
  blend_l6 vs blend_mg1 is reported only. Weights reported per hour (mean, first, last).
- **If a blend WINS vs L6:** L2 drafts (does not apply) a dated MG-2 pre-13 Clarification text, what a new rule sha
  would bind, and an L8 v2 control re-run plan.
