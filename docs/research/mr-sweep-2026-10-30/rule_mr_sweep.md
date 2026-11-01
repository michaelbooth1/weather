# MR P0 sweep: which capture-time signals predict the market's error? (lane L3, 2026-10-30)

Pre-registered before any read of a dev-window feature, outcome or price for this sweep. One run. Development
evidence only (dev window, provisional). Parent rule: the MR gate `docs/research/mr-gate-2026-10-30/rule_mr.md`
(sha256 `37cb46be8d8ddb272ac69638d71de8d023eddff2384e0a6824e00a18417f34ac`). Its w-gate machinery is reused
unchanged for survivors (section 6). Code: `src/weather/calibration/mr_gate.py` (`ebb4967a7`) and its sweep
extension on `claude/mr-sweep-20261030`. The run env is disclosed in the receipt and ledger row.

## 1. Population and data

- Layout `C:/swarm/v3layout` (manifest `harness_v3_layout/1`). Dev scorecard default folds:
  - burn-in 2026-08-01..08-14;
  - scored 2026-08-15..09-29 (43 dates, 11 US markets, °F).
  - Nothing after 2026-09-29 is read.
- Snapshots: every scored snapshot at every local hour 00-23 (all five layout blocks pooled). Entries: every band
  of those snapshots.
- Market `m` = `Table.p_market` (raw YES prices, as in the MR gate). Outcome `y` = the band's winner indicator.
  Market error `e = y − m`.
- Market moments per snapshot use the normalised market `m̃ = m / Σm`:
  - μ_m = Σ m̃_b z_b and σ_m² = Σ m̃_b (z_b − μ_m)², floored at 0.25 °F².
  - z_b is the band's representative temperature:
    - interior band of integers low..high: z_b = (low + high)/2;
    - lower open band "≤ H": z_b = H − W/2;
    - upper open band "≥ L": z_b = L + W/2;
    - W = the snapshot's median interior width (high − low + 1).
- Feature values come from the captured replay inputs `data/inbox/replay-inputs-le0929` (SHA256SUMS recorded).
  - Joined by `row_key = market|snapshot_id`; NBM v2 fields come from the layout's own columns.
  - Read only. No cache is rebuilt or re-downloaded (interim cache rule, master 2026-10-30).

## 2. Capture-time validity (a value is used only if its receipt time is shown)

A candidate value is **covered** at a snapshot iff all of these hold:

- the source record has `ok` true;
- the value is finite;
- its receipt time ≤ the snapshot's `captured_at_utc`.

Receipt time by source:

- **Open-Meteo sources** (`open_meteo`, `open_meteo_multimodel`, `open_meteo_global_models`, `global_ensemble`):
  the source's `fetched_at`.
- **METAR** (`metar`): `fetched_at`, and also `data.report_time` ≤ capture and `data.target_date_match` true.
- **NBM v2** (layout): `v2_available_at` with `v2_available_basis` = `response_received_at`, and `v2_status` ok.

Coverage is reported per candidate. A candidate with fewer than 20 covered scored dates or 1,000 covered snapshots
is UNTESTABLE: its p is set to 1 and it still counts in K.

## 3. Candidate list (fixed; K = 17 tested)

Each candidate's type fixes its band signal `s_b` (section 4).

Open-Meteo per-model highs (S14 / S29; type C, x = the model's target-day high, native °F; a member absent from
`day_model_highs` is uncovered):

| # | id | source . field |
| --- | --- | --- |
| 1 | OM-GFS | `open_meteo_multimodel.day_model_highs.gfs_seamless` |
| 2 | OM-HRRR | `open_meteo_multimodel.day_model_highs.ncep_hrrr_conus` |
| 3 | OM-NAM | `open_meteo_multimodel.day_model_highs.ncep_nam_conus` |
| 4 | OM-IFS | `open_meteo_global_models.day_model_highs.ecmwf_ifs025` |
| 5 | OM-AIFS | `open_meteo_global_models.day_model_highs.ecmwf_aifs025` |
| 6 | OM-GRAPHCAST | `open_meteo_global_models.day_model_highs.gfs_graphcast025` |
| 7 | OM-AIGFS | `open_meteo_global_models.day_model_highs.ncep_aigfs025` |
| 8 | OM-BEST | `open_meteo.day_max_native` (the best-match forecast high) |
| 9 | OM-MM-SPREAD | `open_meteo_multimodel.day_high_spread` (type S) |
| 10 | OM-GM-SPREAD | `open_meteo_global_models.day_high_spread` (type S) |

GEFS, control vs member centre (type C):

| # | id | field |
| --- | --- | --- |
| 11 | GEFS-CONTROL | `global_ensemble.day_max_native` (the control run's hourly temperature) |
| 12 | GEFS-MEMBER-CENTRE | (`day_member_high_p10` + `day_member_high_p90`) / 2 |

NBM quantile shape not already killed (type D, sign +):

| # | id | field |
| --- | --- | --- |
| 13 | NBM-SKEW | (v2_p90 + v2_p10 − 2·v2_p50) / (v2_p90 − v2_p10); uncovered when v2_p90 = v2_p10 |

Intraday METAR-derived (from the `metar` source at capture):

| # | id | type, sign | value |
| --- | --- | --- | --- |
| 14 | MET-MAX | C | `same_day_max_native` |
| 15 | MET-COOLING | D, + | `temp_native` − `same_day_max_native` |
| 16 | MET-DEWDEP | D, + | `temp_native` − `dewpoint_native` |
| 17 | MET-COVER | D, − | `cover` ordinal: CLR/SKC/CAVOK 0, FEW 1, SCT 2, BKN 3, OVC/VV 4; anything else uncovered |
| 18 | MET-PRESSURE-TENDENCY | — | **not included**; no prior report is in the record (listed here so the count is explicit) |

So K = 17 tested candidates (rows 1-17). Row 18 is listed only to make the exclusion explicit.

### Exclusions (not tested; one line each)

- **NBM centre:** v2_p50, v2_mean and Open-Meteo `ncep_nbm_conus`. NBM as a centre against the market is closed:
  EXHAUSTION_REGISTER X22 (P3d_N blend with the market, w 0.0051, NOTHING) and DEV_WINDOW_LEDGER.
- **NBM published spread:** v2_stddev (TXNSD), IQR and p10-p90 width. NBM-published spread is closed (X37 R-S KILL);
  IQR and p10-p90 width duplicate it.
- **NBM parser-v1 fields:** `nbm_probabilistic_tmax.*` in the replay and the layout's `v1_*` and `nbm_prob_tmax_*`.
  The parser defect (EF §10k) makes them invalid.
- **ICON (S12):** not in any captured `day_model_highs` on dev dates; no capture-time value.
- **GEFS member mean:** not captured; HELD (master).
- **GEFS member spread** (`day_member_high_spread_80`, `day_mean_member_spread`): GEFS member SD is closed (X43 R-Q).
- **ECCC observations** (`eccc_swob`, `eccc_citypage`): Toronto only, and Toronto has no dev-window market prices in
  the layout, so P0 against the market cannot be formed.
- **ECCC GEM:** out of scope (coordinator). Toronto only, so it would be untestable for the same reason anyway.
- **HRRR from the S3 dev backfill (R-R / R-K inputs):** no receipt time; public availability only.
  `open_meteo_multimodel.ncep_hrrr_conus` (#2) is the captured HRRR.
- **L13 recorder inventory:**
  - the HRRR forward recorder (from 10-26) and the GEFS forward recorder (from 10-28) have no dev-window values;
  - the ECMWF ENS, ECCC GEM and MOSMIX recorders are out of scope (no dev history).
- **Not in the requested families, not swept:** NWS grid / hourly highs, layout `hrrr_high`, `nws_grid_high`,
  `open_meteo_hrrr_high_delta` and `forecast_high`. `hrrr_high` duplicates #2 by another path; `forecast_high` is a
  served composite.
- **METAR wind and pressure:** no pre-statable sign, and no prior report for a tendency.

## 4. Band signals and candidate distributions (no outcome enters either)

Band signal s_b by type:

- **Type C** (forecast high x, °F): s_b = (x − μ_m)(z_b − μ_m) / σ_m².
- **Type S** (spread g): s_b = g_z · ((z_b − μ_m)² − σ_m²) / σ_m².
- **Type D** (scalar g with the pre-stated sign σ): s_b = σ · g_z · (z_b − μ_m) / σ_m.

Here g_z = (g − mean_k g) / sd_k g within market k. The mean and sd are taken over that market's covered
snapshots in the fit table (burn-in + scored), from feature values only.

Each candidate is a band distribution. On covered snapshots:

    c_b = Σm · m̃_b · exp(s_b / σ_s) / Σ_b′ m̃_b′ · exp(s_b′ / σ_s)

- σ_s is the sd of s over the candidate's covered fit-table entries.
- c has the market's band count and sum Σm. Under the 37cb46be log pool, w is then the walk-forward strength of the
  tilt.
- From here on every candidate is handled exactly like an MR-gate candidate vector c.

## 5. P0, the two controls and the decision

The calibration-matched placebo is the independent reviewer's definition, relayed by the coordinator on 2026-10-30.
L8's Toronto row 77 clarification cites this section.

- **Disagreement placebo (calibration-matched), c_pl.**
  - The disagreement is deranged; c itself is not. For snapshot d:
    c_pl(d) = m(d) + (c(d′) − m(d′)), band by band.
  - d′ is d's donor under `market_blend.placebo_vector`: a derangement of dates within (market, local hour), built
    on the fit table (burn-in + scored); snapshot k of a date takes donor-date snapshot min(k, n − 1); band counts
    must match or the run refuses.
  - Implementation: apply `placebo_vector(fit_table, c − m, seed)` to the band array c − m, add the recipient's m,
    then restrict to the score table (`market_blend.restrict`).
  - Clip c_pl to [`market_blend.EPS`, 1] and renormalise each snapshot to sum(m).
  - J = 20 derangements, with seeds 20260921 + j for j = 0..19. Nothing is fitted: the placebo uses no outcome and no
    walk-forward step.
- **Statistics.** All are pooled Pearson correlations over the entries (snapshot × band) of the candidate's population
  P, with e = y − m:
  - ρ_c = ρ(c − m, e);
  - ρ_pl,j = ρ(c_pl,j − m, e).
  - P = the scored snapshots where the candidate is covered and, for every j, its donor is covered.
- **Bootstrap.** Dates are resampled with replacement: B = 10,000 draws, seed 20261024. Draw b uses derangement
  j_b = b mod 20, so the placebo interval carries derangement variance as well as date resampling.
- **Primary: the paired difference** Δ = ρ_c − mean_j ρ_pl,j. Its bootstrap replicate is Δ*_b = ρ*_c,b − ρ*_pl,j_b,b,
  computed on the same date-cluster draw.
  - One-sided p = (1 + #{Δ*_b ≤ 0}) / (B + 1).
  - 95% interval = the 2.5 / 97.5 percentiles of Δ*.
- **Benjamini-Hochberg** at q = 0.10 over the K = 17 p-values (UNTESTABLE p = 1).
- **P0 survivor** iff BH rejects and the lower 95% bound of Δ > 0.
- **Diagnostic only** (never a verdict): the date-deranged placebo of the parent rule, ρ(c_A − m, e). Here
  c_A = `placebo_vector(fit_table, c, 20260921)`, i.e. c itself deranged. Its interval and whether it covers 0 are
  reported.
- **Also reported, not tested:**
  - ρ_c with its interval;
  - mean_j ρ_pl,j with its interval;
  - per-block Δ (00-05, 06-09, 10-12, 13-16, 17-23);
  - per-market Δ.

## 6. w gate for survivors (rule 37cb46be machinery, `mr_gate.gate_candidate`)

- c and the placebo c_pl,0 (seed 20260921, section 5) feed `market_blend.pool()` unchanged.
- **Block:** all hours 00-23, on covered snapshots. Walk-forward w with gap 1 day on grid 0..1.
- **PASS iff**, as in 37cb46be:
  - mean w ≥ 0.05;
  - blend R date-clustered upper < 1;
  - paired blend − placebo Brier upper < 0;
  - paired blend − floor-only Brier upper < 0.
- The w-gate verdict uses only these four checks; P0 was decided in section 5.
- The 37cb46be controls run first and refuse the run on any miss:
  - served R 1.774 / 1.526;
  - MG-1 07-12 excess 0.0120;
  - w = 0 identity (MG-1 and every survivor).
- A survivor that passes is **PASS (w)**. It goes to a tradability replay only under its own rule file and ledger
  row. Nothing is replayed under this rule.

## 7. Outputs

- **Receipt** `mr_sweep.json`, never overwritten. It records:
  - code (git HEAD, dirty flag; a dirty tree refuses);
  - module, scorecard and layout shas, plus the replay SHA256SUMS sha;
  - coverage, every statistic, the BH table and verdicts.
- **Per-date rows** `mr_sweep_rows.jsonl`, one row per (candidate, date):
  - n entries and n snapshots;
  - the six sufficient sums for (c − m, e) and for each (c_pl,j − m, e);
  - for survivors, the date's w and the paired Brier differences.
- **Non-survivors:** one EXHAUSTION_REGISTER line each, drafted and not committed.

## 8. Not done under this rule

- No refit of any candidate.
- No other hour block chosen after the fact.
- No candidate added or removed after the ledger row.
- No read after 2026-09-29.
- No B-bound or `pooled_residual_model.py` edit.
