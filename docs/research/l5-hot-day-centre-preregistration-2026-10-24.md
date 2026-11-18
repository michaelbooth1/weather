# L5 hot-day centre lever: pre-registration (2026-10-24)

**Status:** frozen pre-registration. Its sha256 is recorded in the commit that adds it, in the result and in
the lane report; it was committed before any candidate was scored. Development evidence only (dates <=
2026-09-29). Result addenda go in [the L5 diagnosis record](morning-loss-diagnosis-2026-10-24.md), never here.
Coordinator rulings 2026-10-24 (item 1 GO; master direction items 1-6) are folded in below.

## 1. Reconciliation with canon (EF §2, RF §1)

- **Canon:** EF §2: the served cool bias (−0.64387 C-eq) is real, its measured cause is seasonal training
  coverage (in-season base HGB −0.18, out-of-season −1.02 C-eq; the market shows no seasonal movement), and a
  serving-side offset is forbidden ("not correctable at serve": the bias is heterogeneous across markets, so a
  global correction helps some and harms others). RF §1 rejects the age-curve and blindness mechanisms; the
  centre-displacement mechanism is floor truncation.
- **The L5 observation is consistent with that defect, not a new one:** on the dev window (Aug-Sep, outside
  the archive's May-June coverage) served is cold −1.44 F at 07-12 and the coldness grows with heat (gap to
  market +0.40 / +1.34 / +2.71 F by within-market heat tercile), as expected when training never saw the
  heat being forecast. If it is the same defect, the root-cause fix is lane L1's full-year corpus retrain; this
  lever is the fast path.
- **How this lever differs from what was tried and forbidden:** it is **not a serving-side offset on the
  served (HGB) centre**. Both candidates replace the HGB centre with a forecast-only, model-side centre built
  from captured guidance (the MG-1 family, EF §10h/§10j/§10q): candidate 1 debiases the guidance per market
  (heterogeneity handled per market, walk-forward, never global); candidate 2 is a fitted linear model of the
  outcome on captured forecasts. EF §2's prohibition targets a global offset applied to the served HGB vector;
  neither candidate touches that vector or applies a global constant. The L4 lane already showed a per-station
  inverse-MSE blend (NBM v2 + GFS/IFS/ICON day-1) is null over MG-1 at 07-12; candidate 1 differs by using the
  NWS grid high and no Open-Meteo member; candidate 2 differs by regressing in levels (extrapolating) and by
  the overnight-low anomaly.

## 2. Population, scorer and control

- Scorer: `weather.reporting.scorecards.dev_scorecard score --layout C:\swarm\v3layout --from 2026-08-01
  --to 2026-09-29 --hourly`, default folds (7-day, gap 1, min 7 train dates; scored 08-15..09-29, 43 dates,
  11 US markets, 473 market-days), with lane G's paired `--control-module`
  (`claude/free-source-screens-20261023` @ `e57db46c6`, merged into this branch).
- **Control:** `control_mg1_candidate.py` (MG-1 verbatim). MG-1 is compared **only on the dev window
  07-31..09-29**; no MG-1 forward-shadow outcome after 09-29 is read (reserved, read on 11-28).
- Served is reported on the same rows (`model_minus_served`).
- Subsets: `python -m weather.calibration.l5_subset_scores` (same layout, folds, Table and module walk-forward;
  crossed and date-clustered intervals restricted to the subset's cells).

## 3. Candidates (both keep MG-1's sigma = max(v2_stddev, 1), floor and v2 availability rule; both equal MG-1
outside local 07-12, so the paired increment over MG-1 is the 07-12 centre change alone)

- **A1 `l5a_debias_v2_nws`** (`src/weather/reporting/scorecards/free_source_candidates/l5a_debias_candidate.py`):
  per fold, on training snapshots at 07-12, b[m, p] = mean(p − y) for p in {v2_mean (usable), NWS grid high raw}
  over market m, kept when spanning >= 5 training dates (else 0); serve mu = mean of present (p − b[m, p]).
  y = layout `settlement_bucket`.
- **A2 `l5b_linear_forecasts_lowanom`** (`l5b_linear_candidate.py`): per fold, OLS on training snapshots at
  07-12 with all regressors present: y = a[m] + b·[v2_mean, nws_grid_high_raw, hrrr_high, forecast_high,
  overnight_low_anomaly]. overnight_low_anomaly (coordinator ruling 3) = min METAR temperature over on-date
  rows labelled 01-08 with label_time + 10 min <= captured_at_utc, minus the Open-Meteo forecast 00-08 minimum
  from the first on-date capture (tables built by `tools/research/morning_loss/extract_regimes.py` from the
  captured replay inputs; sha256 recorded in the state provenance). Missing any regressor: MG-1's mu.
- **Arm B** (master direction 2): the same two rule forms with their parameters fitted on lane L1's full-year
  2021-25 corpus instead of the dev-window folds, restricted to regressors that exist point-in-time in both the
  corpus and the layout. It is locked as a separate addendum with its own sha256 once master sends the corpus
  id, before it is scored; arm A is not changed by it.

## 4. Decision rule (headline: 07-12 pooled `ALL`)

- **KEEP** iff on the 07-12 pooled row both crossed date x market 95% intervals exclude zero below:
  candidate − served **and** candidate − MG-1 (lane G's common protocol, EF §5 binding interval).
- **LEAD** iff not KEEP but candidate − MG-1's date-clustered 95% interval excludes zero below (master's
  direction 4 trigger: a LEAD or KEEP starts the MG-2 shadow build, reported to master with that label).
- Otherwise **KILL** (no increment demonstrated). Two candidates in arm A: each is judged alone; a lone
  marginal result is read with two looks in mind (no family-wise correction claimed).
- Reported, not decided: per hour 07..12; the L5 top-decile list (selected on served − market loss, so
  descriptive only); hot days (within-market top tercile of 07-12 mean v2_mean, ex ante); per market with LA and
  Dallas called out; the fraction of A2's scored 07-12 snapshots whose mu exceeds its fold's training maximum
  of y for that market (extrapolation actually used); MDE80.

## 5. What is not claimed

No promotion, serving, edge or EF entry follows from any verdict. A KEEP or LEAD earns a pre-registration on
new dates and, per master, an MG-2 shadow-variant build plan with a roll verdict; nothing else.
