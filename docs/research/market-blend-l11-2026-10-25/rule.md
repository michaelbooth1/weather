# Rule L11-blend (lane L11, 2026-10-25): walk-forward log opinion pool of market and candidate

Written 2026-10-25 before any blend row exists. Development evidence only (C dev scorecard window,
layout `C:\swarm\v3layout`, dates 2026-08-01..2026-09-29; nothing later is read). Code:
`weather.calibration.market_blend` on branch `claude/market-blend-l11-20261025` (based on L10
`89ff6326c`, reusing `weather.calibration.gap_to_market_atlas` loaders and the dev scorecard `Table`).
Nothing below changes after this file's sha256 is recorded; any change needs a dated clarification
written before the rows it affects.

The question: a candidate that loses to the market on its own may still carry information the market
lacks. Does a walk-forward blend of the market-implied distribution and the candidate beat the market?

## Pool (fixed)

- Per snapshot, over its band set: m = the market vector exactly as the dev scorecard scores it
  (`Table.p_market`, raw, not renormalised); c = the candidate's scorecard vector (rule-4 floor mask,
  renormalised, served fallback where the candidate is absent; `Table.candidate_vector`).
- Epsilon floor, ONE value on both inputs: eps = 1e-4 (the scorecard's `LOG_EPS`):
  m' = max(m, eps), c' = max(c, eps).
- g_w = m'^(1-w) * c'^w with w >= 0.
- Hard floor after blending: for w > 0 every rule-4-impossible band (below the observed high, the same
  `Table.impossible` mask the scorecard applies to candidates) is set to 0. This is the exact log-pool
  limit of the candidate's floored zeros (0^w = 0 for w > 0, 0^0 = 1); eps would otherwise undo it.
- Renormalise over the bucket set to the market's own total mass S_m = sum(m): blend = g_w * S_m / sum(g_w).
  Rationale: at w = 0 the blend is then the market vector exactly (no market price is below eps), so the
  w = 0 control is an identity and the market's overround is not silently re-scaled and credited to the
  candidate. Log loss is unaffected (the scorecard's log score renormalises).

## Fitting w (walk-forward by date)

- Grid w in {0.00, 0.01, ..., 1.00}; ties go to the smaller w.
- Objective (primary): the pooled Brier = sum over fitting (date, market) cells of the cell-mean
  per-snapshot Brier (`Table.brier`) over the block's hours, i.e. the R numerator. Secondary: the same with
  the scorecard log score (`Table.log_score`).
- To score date d, w is fitted only on dates <= d - 2 days (dates < d, with the scorecard's one-day
  settlement gap: D-1 settles during D). Fitting dates are the burn-in dates plus earlier scored dates.
- Burn-in: 2026-07-31..08-14 as instructed; the layout has no 07-31, so in practice 08-01..08-14 (14 dates).
  Scored dates: 2026-08-15..09-29 (the dev scorecard's default folds 7/1/7: 43 dates, 473 market-days).
- Fits: pooled 07-12 (PRIMARY), and per block 06-09, 10-12, 12-16, 13-16 (each fitted and scored on its own
  hours). All fits pool the 11 markets (one w per date) except the per-market fits (descriptive).
  Per-hour rows h07..h12 use the primary 07-12 w; h13..h16 use the 13-16 w.
- The w path is held fixed inside the bootstrap (intervals are conditional on the walk-forward w).

## Candidates

1. MG-1 (`r-t5-inc-c1`, `loss_atlas.mg1_frame`, zero fitted parameters) — first; the primary.
2. Composite: before 13:00 the L6 own-obs stack (MG-1 recentred on the own-observation nowcast at 07-12,
   `free_source_candidates/l6_own_candidate.py`, walk-forward per fold), from 13:00 L3 arm A refit on the
   captured forecast. Burn-in vectors of the L6 stack: the two default folds that the scorecard does not score
   (08-01..08-07, empty training pool, so exactly MG-1; 08-08..08-14, trained on 08-01..08-06 under L6's own
   >= 200 snapshots per hour rule), run with min_train_dates 0; scored dates use the default folds unchanged.
   The composite's 13-16 part (and 12-16) is scored only once `C:\t\mg2\control_refit_armA.json` exists, on
   the refit arm A vectors that file names (a dated clarification will name the vector file and its sha256
   before those rows are scored). The lead-1 arm A vectors (`C:\t\l3\dev_l8\...`) are never used for a
   reported composite result; the code refuses them.

## (a) Positive control

All must pass before any blend row is written (exit 7 otherwise):

- served vs market pooled R 1.774 (all hours) and 1.526 (00-16) on the dev scorecard default folds
  (`loss_atlas.positive_control`);
- MG-1 07-12 Brier excess over the market 0.0120 (4 dp);
- composite only: L6 own-stack 07-12 Brier minus MG-1 = -0.0036243 (|diff| <= 1e-6);
- w fixed at 0: blend equals the market vector (max abs difference 0.0) and R = 1.0 exactly, per candidate.

Placebo (reported; its failure makes the reading "not interpretable" but rows are still written): the
candidate's vectors shuffled across dates within (market, local hour) — a fixed-seed (20260921) derangement
of dates per (market, hour); snapshot k of (date d, market, hour) takes the vector of snapshot min(k, n-1) of
the donor date — then pooled with date d's market and floor, fitted and scored exactly as the real blend.
PASS iff the mean walk-forward primary w over scored dates <= 0.05 and the pooled ALL 07-12 R >= 0.999.

Floor-only control (reported): the w -> 0+ limit, the market with the same hard floor and the same mass
renormalisation and no candidate information (M_floor). Its R vs market is reported beside every primary row.

## (b) Comparator fairness

The comparator is the market vector exactly as the scorecard scores it: no floor and no calibration are
applied to it, on identical rows (same snapshots, same cells, same date-clustered and crossed weights). The
blend inherits the rule-4 floor and no other calibration (no temperature scaling, no recentring) through its
candidate leg. Because the floor itself can lower Brier against an unfloored market, M_floor (the market
with the same floor and the same renormalisation, w -> 0+) is reported as the floor-only control, and the
information claim below requires the blend to beat it too.

## (c) Targeted loss slice

Loss atlas `535221e08c1de3964755100fa6688b7eb39a6d99da848decd8f8d0cf4b7ed7d4` (L7, MG-1) and L10 gap atlas
rows `cf8af061799a661c266eb675591e6158ecfdf00ff0c32bcd27a5da940a57ea8b`: MG-1's 07-12 Brier excess over the
market is 0.0120 (R 1.224, ALL); the composite's pre-13 R is 1.156. The blend targets the part of the
market's own 07-12 loss that the candidate can explain. Expected size: small; prior R(blend) in
0.98..1.00 at 07-12 with w in 0.0..0.3.

## (d) MDE and clusters

Reference MDE80 0.084 in R units (MG-1 vs market, ALL 07-12, date-clustered bootstrap, L10 rows above); the
blend's own MDE80 (scorecard `mde80`, effect -0.05, date-clustered) is computed and reported per row.
43 date clusters and 11 market clusters (473 market-days); PRIMARY5 215 market-days. Crossed intervals at
11 market clusters are below the scorecard's 12-cluster power floor: a null is "no increment
demonstrated", not "no effect".

## (e) Dev-window reuse

DEV_WINDOW_LEDGER.md at writing, across branches: base rows 1-19, L3 rows 20-27
(`claude/l3-dev-ledger-rows-20261025`), L8 rows 20-21 (`claude/mg2-composite-binding-20261025`; numbering
collides): 29 rows, 19 of type K, plus the pre-ledger block of 134 rules. This rule adds 2 K rows (MG-1 blend,
composite blend): K candidates 20 and 21 on 2026-07-31..09-29.

## Metrics

- PRIMARY: R(blend) = sum of blend cell-mean Brier / sum of market cell-mean Brier, pooled ALL 11 markets,
  07-12, primary fit, scored dates; date-clustered (`Table.w_date`) and crossed (`Table.w`) 95% intervals,
  2,000 draws, seed 20260921. With it: the w path over scored dates (per date; mean, median, min, max).
- Secondary: PRIMARY5 (atlanta, austin, chicago, dallas, denver); the 13-16 block (and 06-09, 10-12, 12-16);
  per hour h07..h16; per-market w (descriptive, per-market walk-forward fit at 07-12); Brier vs log loss
  (the Brier-fitted and log-loss-fitted blends, each with its Brier R and log-loss ratio).
- Each blend is reported against the market only. No candidate-vs-candidate (arm-vs-arm) deltas.

## Keep/kill rule (reading rule), per candidate, on the PRIMARY row

Let wbar = mean walk-forward primary w over the 43 scored dates; "w > 0" means wbar >= 0.05, "w ~ 0" means
wbar < 0.05. Decision interval: the crossed 95% interval (the date-clustered one is reported beside it).

- **INFORMATION**: w > 0 and blend R crossed upper CI < 1, and the blend's R point is below M_floor's R
  ⇒ we hold information the market lacks (development evidence, provisional; it earns a pre-registration on
  new dates, never confirmation).
- **NOTHING**: w ~ 0 ⇒ the model adds nothing to the market.
- **INCONCLUSIVE**: w > 0 and the crossed upper CI >= 1 (or the blend does not beat M_floor) ⇒ the blend
  leans on the model but no increment over the market is demonstrated at this MDE. If the date-clustered
  upper CI < 1 this is stated.
- **HARM**: crossed lower CI > 1 ⇒ walk-forward blending hurts.
- Any failed control in (a) ⇒ no reading. A failed placebo ⇒ "not interpretable".

The reading rule in the brief's words: "w > 0 with blend R upper CI < 1 ⇒ we hold information the market
lacks; w ≈ 0 ⇒ the model adds nothing to the market."

No epsilon, objective, grid, block or threshold change after the sha256 is recorded.
