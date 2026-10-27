# L5 pre-declared analysis plan: the morning (07-12) served-minus-market loss

Lane L5, 2026-10-24. Written after the positive control only (dev scorecard, served, 08-01..09-29 default folds:
pooled R all 1.774 [1.566, 2.052], 00-16 1.526 [1.369, 1.721]; output sha 3557f797c6ca...). Before this file was
locked nothing beyond that control, column names and fill rates was computed. Descriptive, development evidence only.

## Population and evidence boundary

- Layout `C:\swarm\v3layout` (manifest sha-pinned, 11 US markets, all degF). Scored dates = the kit's default
  fold scheme (08-15..09-29, 43 dates), 473 market-days. Window W = local_hour 7..12 inclusive.
- Market prices / labels only from the layout (all <= 09-29). Settlement high = layout `settlement_high`.
- Weather regime inputs only from our captured replay inputs (`data\inbox\replay-inputs-le0929`): per folder, the
  FIRST line and the LAST line whose `captured_at_local` date equals the target date. Lines are located by
  reading only the timestamp prefix; a line captured after the target date is never parsed (this matters for the
  09-29 folders whose tails run into 09-30 local). Plus layout forecast columns.
- Statistics: one crossed date x market multinomial weight matrix (2,000 draws, seed 20260921, the kit's
  `crossed_weights`) over the 473 cells; ratios of weighted sums. Rankings (top decile) are recomputed inside each
  draw on the weighted population.

## Quantities

- Per snapshot Brier exactly as the kit (mean over bands of (p-y)^2); excess e = Brier_served - Brier_market.
- Market-day excess E = mean of e over that day's W snapshots. Total excess = sum of E (equal market-day cells).
- Band representative degree: eq band (low+high)/2; lte band high-(w-1)/2; gte band low+(w-1)/2, w = modal eq
  width of that snapshot. Centre c = probability-weighted mean of representatives (vector normalised); spread s =
  the matching SD. Secondary: median by linear CDF interpolation.
- Shift operator: spread each band's mass uniformly over its integer degrees (tail bands over w integers beyond
  the edge), each integer k owning [k-0.5, k+0.5); translate by delta degrees; rebin to the same bands (tails
  absorb everything beyond); apply the kit's rule-4 floor mask and renormalise.

## Analysis 1 - decomposition (primary)

- Ordering A: centre part = L_served - L(served shifted by c_market - c_served); shape/width part = the remainder
  L(shifted) - L_market. Ordering B: shape part = L_served - L(market shifted by c_served - c_market); centre
  part = remainder. Reported: both orderings and their average (two-ordering Shapley), as shares of the W total
  excess, with crossed CIs. Supporting: MAE |c-y| served vs market; spread ratio s_served/s_market; mean z^2 with
  z = (y-c)/s for each (calibration of spread; 1 = calibrated).
- Reading: "centre-dominated" if the Shapley centre share CI lies above 50%; "width-dominated" if below 50%.

## Analysis 2 - concentration

- Top decile = the 48 market-days (ceil 10% of 473) with largest E. Report share of total excess and of total
  positive excess, with crossed CIs (decile recomputed per draw), the market composition, and list all 48.

## Analysis 3 - regime frequencies (from our captured data only)

Flags per market-day (METAR rows = hourly routine rows in the last on-date replay line; open-meteo = hourly
forecast in the first on-date line):

- R1 frontal / wind shift: among 00:00-15:00 obs, a pair <= 3 h apart with direction change >= 90 deg and both
  speeds >= 6 kt, OR a dewpoint drop >= 8 F within 3 h.
- R2 cloud / marine layer: >= 50% of 06:00-12:00 obs with a ceiling (lowest BKN/OVC/VV) <= 3,000 ft.
- R3 precipitation: any 00:00-15:00 obs whose present weather contains RA, DZ, TS, SH or GR (not VC).
- R4 overnight-low gap: |min open-meteo hourly forecast 00-08 - observed METAR min 00-08| >= 3 F.
- R5 forecast revision: mean over available {hrrr_high, nws_grid_high_raw, v2_p50} of (value at the last
  snapshot <= 12:59 - value at the first snapshot of the day); flag |.| >= 2 F.
- R6 temperature tendency anomaly: (obs T 11:00 - obs T 06:00) - (open-meteo forecast T 11:00 - T 06:00);
  flag |.| >= 3 F.

Statistic: frequency ratio FR = P(flag | top decile) / P(flag | all market-days), crossed CI with the decile
recomputed per draw. Secondary: the continuous variable's mean on top decile vs all; a market-stratified FR
(expected count from per-market base rates); mean E when flag=1 vs 0.

**Signal rule (regime):** FR 95% CI lower bound > 1.0 AND the flag is present on >= 10 top-decile market-days
spanning >= 3 markets. **Strong** if the Bonferroni (6 regimes) 99.17% CI also excludes 1.0. Anything else is
"no signal" (reported in those words, with the CI).

## Analysis 4 - timing

- For every snapshot 00:00-16:59: c_market(t), c_served(t). Arrival A_x = earliest snapshot time from which
  |c_x - y| <= 1.5 F holds for every later snapshot through 16:59; never = 17:00 (censored). Lead L = A_served -
  A_market in hours, per market-day.
- **Signal rule (timing):** on top-decile days mean L >= N = 2.0 h AND its crossed 95% CI lower bound > 0.
  Also reported on all days, and hourly curves of |c-y| for both.
- Secondary: hourly-mean centres; for lags k = 0..6 h, the coefficient of regressing the served centre change
  over [h, h+1+k] on the market-minus-served centre gap at h (catch-up rate), top decile vs all.

## Analysis 5 - what the market centre tracks (descriptive, for the ranked list)

- In W: MAE of c_market to each captured product {c_served, v2_p50, v2_mean, nws_grid_high_raw, hrrr_high,
  forecast_high, high_so_far} and MAE of each to y; on all days and top decile. A product closer to c_market than
  c_served is information we capture but do not serve. The residual c_market - (closest product) on top-decile
  days is compared across regime flags.
- Secondary baseline: MG-1 (Normal(v2_mean, max(v2_stddev, 1)) on band edges, floor mask, served fallback;
  zero parameters, EF 10q). Analyses 1-3 are repeated on excess = Brier_MG1 - Brier_market to separate "captured
  but unused" from "not captured".

## Deliverable rule

Items in the ranked list must cite at least one signal under the rules above or be labelled "lead, no signal".
Ranking by share of top-decile excess carried by flagged days. No promotion, serving or edge claim.
