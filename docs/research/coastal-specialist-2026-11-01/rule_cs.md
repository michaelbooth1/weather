# Rung R-CS pre-registration DRAFT: coastal grid-cell choice and HRRR block gradients at 07-12

**Status: PARKED 2026-11-01 (master), not killed.** Reasons: the dev HRRR was refetched from AWS and is not
capture-time; a winner would be Aug-Sep only, and P3d_H's 07-12 gain did not carry into Oct-Dec; the prior is
about 0.001 pooled; the KSFO grid gap is already exploited by R-R. Reopen if either (1) at least 30
forward-recorded Oct-Dec HRRR 07-12 dates with block fields are readable under rule 9, or (2) the price-history
atlas shows a coastal-specific seasonal gap. Master approved the draft at sha `ec9df693…` and then parked it before
any module was built or any gate was run. No ledger row exists. A reopen needs a fresh rule revision and a go.

Written 2026-11-01 by lane L49 (WS) as a **batch member**, before any scored read. Status: DRAFT until the
coordinator assigns the row and master gives the go; the sha256 of this file is reported to the coordinator.

- **Ledger row:** TBD (coordinator assigns; K row after row 106 and the T+1 freeze, C21).
- **Evidence class:** development selection evidence only. No edge claim. No serving, capture or scheduling
  consequence. Nothing dated after 2026-09-29 is read; nothing from 2026-09-30..10-15; no B forward cell.
- **What has been read before writing:** inputs only (S0, `s0_coastal.md` in this folder). No outcome, label
  or price has been joined to any block statistic.

**Form.** R-R's form (`C:\t\l13\rr\rule_rr.md`, sha256
`e3d92e1aa779957db90c9627f3ccdc9052d7f9f2d6f7ae50843ebadbd0f5bb22`; register X34). Where this rule is silent,
R-R (and through it R-K, RK-1 and R-F) applies verbatim. Scope narrows to the five coastal markets
san-francisco, seattle, los-angeles, nyc, miami (stations KSFO, KSEA, KLAX, KLGA, KMIA), cutoff hours h07-h12,
Aug-Sep.

## Disclosures

1. **Motivation is dev-informed.** The coastal centre gap (market MAE 1.17 vs the post-hoc blend 1.48; SF 2.03
   vs 1.18, Seattle 1.74 vs 1.09; `docs/research/morning-loss-diagnosis-2026-10-24.md` Analysis 5) was
   measured on the dev window. X38's SF ρ +0.24 lead was chosen after seeing results. **Only gate 2 (LOYO
   2021-25) is on data no one has scored with block statistics.** The dev gate can only refute.
2. **The cited +4.29 °F KSFO grid-point gap is already exploited** by R-R's RN-1 land-cell rule (SF gate 3
   −0.0534 [−0.0948, −0.0151]). This rung tests what remains: per-market cell choice beyond RN-1 and the
   day-varying within-block gradient.
3. **Marine data sources are not reopened:** NDBC/CO-OPS SST and onshore (ledger row 87), AFD text (X10),
   METAR low cloud and the R-H onshore tag stay as recorded. The only marine-layer structure here is HRRR's
   own 3x3 temperature gradient.
4. **Not a width rung.** X38/X39 closed the 3x3 spread as a width signal at all hours. Block columns enter the
   mean model only (see Implementation). If that cannot be built, the rung does not run.
5. **The prize is small.** P3d's 07-12 excess vs the market: Seattle +0.0152, NYC +0.0119, SF +0.0062 (null),
   Miami +0.0039 (null) (`rungh/rh_summary.md` §4). A quarter of that is about 0.002 on these markets.
6. **S0 facts that shaped the design (inputs only):** only KSFO's block has water cells; KLGA and KMIA blocks
   are near-uniform (range mean 1.4 and 2.2 °F); KLAX has a 6 °F west-east gradient; constant offsets are
   absorbed by P3d's (market, season) bias.

## Data

- `C:\t\l13\hrrr_0712\` (`selections.jsonl` sha256 `31bd3d3a7c6456df657e8f99b763a06a80bc41772881f67dc7eeaf5dee1f4e67`,
  `manifest.jsonl` `fef6c307a411e6373af05830b55c4dff8cb23d08f46e18f07949821f08fe88e6`): Aug-Sep 2021-25 for
  LOYO, 2026-07-30..09-29 for dev. Land mask `C:\t\l13\land\land_3x3.json` `22069bee…d7fd6`. R-R's selections,
  unchanged. Labels, NBM anchor and arm inputs exactly as R-R.

## Columns (coastal rows only; NaN on the other six markets)

For a row (market m, date d, hour h) with R-R's selection (`cycle_utc`, `fhs`), let M_k = max over fhs of TMP °F
at block index k (k = 0..8, row-major south→north, west→east).

- `c_sel(m, fold)`: the land cell (LAND = 1) minimising Var(y − M_k) over the **inner training years only** of
  each outer LOYO fold, per market, pooled over h07-12; ties to the RN-1 index, then the lower index. For dev,
  chosen on all five 2021-25 years. It is reported per fold.
- `k_max_cs` = M_{c_sel}; `k_gap_cs` = `k_max_cs` − nbm_mean (R-R's anchor definition).
- `g_ew` = mean(M_2, M_5, M_8) − mean(M_0, M_3, M_6) (east minus west column; all nine cells, water included).
- `g_ns` = mean(M_6, M_7, M_8) − mean(M_0, M_1, M_2) (north minus south row).
- `k_miss` as R-R. No other variable, transform, window or block statistic.

## Arms (identical rows)

- **P3d_CS** = P3d_H with `k_max`, `k_gap` replaced by `k_max_cs`, `k_gap_cs` on coastal rows and `g_ew`, `g_ns`
  added, **in the mean HGB only**. The scale model receives exactly P3d_H's inputs.
- **B_CS** = B_H with `k_gap` → `k_gap_cs` on coastal rows and `g_ew`, `g_ns` (NaN → 0) added to `extra_ols`.
- Incumbents P3d_H and B_H exactly as R-R. Fits per cutoff hour on all 11 markets' rows, as R-R.
- Reported-only ablations: cell choice alone (`g_*` dropped); gradients alone (RN-1 cell kept).

## Implementation

A new research module that imports `pooled_residual_model` read-only (B-bound; never edited), passes the new
columns to the mean HGB and withholds them from the scale model. Its sha is written into this rule's
Clarification before any row is scored. Runs only through `scripts\ops\workstation_heavy.ps1 -Queue`.

## Gates

### Gate 1: parity (inputs only; failure stops without a kill)

Coastal coverage ≥ 0.95 on 2021-25 and dev rows; every block has 9 finite cells in [−60, 130] °F; the land
file and `stations_json_sha256` match; B_H and P3d_H LOYO rows reproduce R-R's artifacts (Brier within 1e-12)
or, where none exists, two runs are byte-identical.

### Gate 2: nested LOYO 2021-25 Aug-Sep — THE KILL GATE

- Statistic: mean per row of Brier(P3d_CS) − Brier(P3d_H) on the five coastal markets, h07-12 pooled,
  date-clustered bootstrap (2,000 draws, seed 20261024).
- **KILL if the point estimate is not < −0.0005, or if the upper 95% bound is ≥ 0.**
- Reported: B_CS − B_H; each market; each hour; the ablations; `c_sel` per fold; the other six markets'
  Δ (harm check, reported).

### Gate 3: dev 08-15..09-29 (refutation only; only after a gate-2 pass and a fresh go)

- dR(P3d_CS − P3d_H) on the five coastal markets, R-R's gate-3 population, date-clustered.
- **KILL (HARM) if the lower 95% bound is > 0.** Otherwise the estimate and its date-level vector go to the
  coordinator's batch. **No solo WIN is claimed at 5 clusters.**
- Reported: blend_l6_CS (R-R's blend with P3d_CS) vs blend_l6_H; R vs the market (capture-time) at 07-12.

### Reported only (no gate)

Oct-Dec 2024-25 (`hrrr_cool0712`), two-fold leave-one-year-out, same statistic, only if the P3d_H Oct-Dec base
from CS-1 reproduces; R10 means it cannot promote.

## Pre-registered kill scope

If gate 2 or gate 3 kills: **HRRR 3x3 cell selection and block-gradient columns are closed as 07-12 centre
inputs on NBM-anchored arms (P3d, B_N, L6, MG-1 families) for the coastal markets, Aug-Sep**, under any cell
rule, gradient axis, block statistic or rung name. The kill does not touch R-R's result, RN-1, 13-16 or 00-06,
or a future wider-than-3x3 block (which needs a new fetch and its own rule). Archive under
`C:\archive\ruled-out\` with an INDEX line.

## Outputs

`C:\t\l49\cs\` (rows, gate JSONs, SHA256SUMS); summary on this branch.
