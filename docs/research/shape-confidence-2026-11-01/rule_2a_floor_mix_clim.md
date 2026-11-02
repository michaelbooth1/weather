# L47 2a rule: LOYO-Brier rung on P3d's FLOOR_MIX_CLIM (written before any scored read, 2026-11-01)

**PARKED by master 2026-11-01, before any LOYO. NEVER RUN.** Reason: step 0 measured the arm shape cost at about
-0.0004 (the shape helps slightly), and the rule-4 mask already renormalises, so the expected effect is at or
below the kill bar. Archive: `C:\archive\ruled-out\l47-floor-mix-clim-parked\`. A reopen needs a fresh rule
revision and a go. The draft below is kept unchanged.

**RULE ONLY. NOT RUN.** The LOYO 2021-25 run needs the owner's go. Ledger row: TBD (coordinator assigns).
This file is frozen once its sha256 is reported. Any change is a v2 file with a new sha.

## Lever

`src/weather/model/mg_serve_core.py:56` fixes `FLOOR_MIX_CLIM = 0.02`. `predictive_distribution` (lines 461-486)
returns `(1 - 0.02) * K + 0.02 * C`:
- K is the floor-censored standardised-error kernel.
- C is the market climatology, which is **not** floor-censored.

This rung asks whether a different weight on a floor-censored climatology beats the fixed mix in LOYO Brier.
mg_serve_core.py and pooled_residual_model.py are B-bound and are imported read-only. The rung is a separate
research module and changes no serving code.

Pre-registered expectation (from step 0, `step0.md`): small. At score time the rule-4 mask already removes
climatology mass below the floor, so the censoring changes scored Brier only through renormalisation. The real
lever is the weight w.

## Data (dev only, no forward cells)

- Rows: `pooled_residual_model.dev_training_frame(C:\t\l2\records)` (Aug-Sep 2021-2025, buckets from the 09-07
  centre) plus `attach_training_nbm` with `C:\t\l9\nbm_corpus\nbm_pit_corpus_rows.jsonl`. These are the same
  inputs as R-I (`C:\t\l2\argv_ri_loyo.json`). Record each input's sha256 in the output before fitting.
- No date after 2026-09-29 is read. No 88a, panel or B forward cell is read.
- Fit: the P3d_N spec, `fit_pooled(train, market_id=False, doy=True, raw_columns=False, bias_by="season")`,
  per cutoff hour. One fit per (hour, held-out year), shared by all arms, so arms differ only in the mix.

## Hours

- **Primary: 13-16** (where P3d serves inside MG-2), pooled.
- Secondary, reported only and never decisive: 07-12 and 17-20.

## Arms, per held-out row

Notation:
- K is the floor-censored kernel exactly as the code builds it.
- C is `smoothed_dist(train_y[market], buckets, alpha=0.10)` from training years only.
- C^F is C with all mass below fb = round_half_up(floor) moved onto fb, the same censoring K gets.

The arms:
- **BASE**: the code's output, `0.98 K + 0.02 C`, normalised. It is produced by calling the read-only code path,
  not re-implemented.
- **ARM(w) = (1 - w) K + w C^F**, with w on the grid {0, 0.0025, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.05}.
  - w* is picked by a strictly nested inner LOYO on pooled 13-16 Brier, using the training years only: one w*
    per held-out year. Ties go to the grid value closest to 0.02.
  - The mix is linear, so per row B(w) = B0 + 2w·Bc + w²·A can be evaluated from K, C^F and y without refitting.
- Descriptive fixed arms, never decisive: ARM(0) and ARM(0.02).

## Scoring

- Brier is the sum over the union of the support and the actual bucket. `fm.brier_score` drops the (1-0)² term
  when the actual bucket is outside the dict's keys; the rung must not inherit that. Report how many rows have
  the actual outside the support and how many have zero probability on the winner, per arm.
- Log loss is reported with a 1e-12 floor and is never decisive.

## Statistic and decision

- Primary: Δ = mean over 13-16 rows of [Brier(ARM(w*)) - Brier(BASE)], with a date-clustered bootstrap (2000
  draws, seed 20261024, 95% percentile interval).
- **KILL if the point estimate of Δ is not < -0.0005.** No other outcome kills or passes on its own.
- If Δ < -0.0005, the result is "survives gate 1". It routes to after-B batching, not a solo forward test,
  because a change of this size is below the dev MDE. Nothing is promoted.
- Report per hour, per market, per held-out year, w* per held-out year, and the ARM(0) and ARM(0.02) Δs.

## Positive control (must pass before any arm is read)

The BASE rows at 13-16 must reproduce R-K's `P3d_N_fix_brier` in `C:\t\l2\rungk\loyo\loyo_rows.jsonl`
(sha256 `bb0bf4943b7105b3f0ded1ec327c80bbdc54d9cbcc657cd10bf50d49eb761ee3`):
- matched on (hour, market, date, year)
- equal within 1e-9
- same row count

R-K's rows use `fm.brier_score`, so the control compares BASE under that same function. The support-union Brier
is computed afterwards. **If the control fails, STOP and report. There is no fallback re-specification.** Arm
results are not computed or read until the control passes.

## Scope notes

- Fixes 10 (high_so_far parity) and 11 (no SPECI in the floor from 10-23) are on the after-B list. Any change
  to w must ship with them: the mix cushions floor and high_so_far errors that LOYO history cannot reproduce.
- Archive on kill: `C:\archive\ruled-out\l47-2a-floor-mix-clim\` with SHA256SUMS, a README and an INDEX.md
  line.
- Heavy run only through `scripts\ops\workstation_heavy.ps1 -Queue`, serial, after the owner's go.
