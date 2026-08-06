# Workstation forecast-lookahead measurement — 2026-08-03

## Decision

**The point-in-time corpus repair remains a prerequisite for the first retrain, not a
footnote.** The stitched forecast is not optimistic in temperature sign: at the least
disruptive honest comparator (lead 1), it is `0.707 C-equivalent` cooler on average and
the year-clustered 95% interval crosses zero (`[-1.548, +0.134]`). It is, however,
optimistic in accuracy: it is `0.923 C-equivalent` closer to configured WU settlement
(`95% CI [0.550, 1.296]`) and wins on `72.4%` of market-days. The apparent advantage
grows monotonically to `2.151 C-equivalent` at lead 7.

That accuracy gain is real enough to justify the 2021–2025 point-in-time restriction.
It is not proof that the defect causes the observed cool bias. A no-fit substitution
through the frozen per-market HGBs moves their raw centre `0.100 C-equivalent` cooler
and their pre-floor, blend-weighted centre `0.070 C-equivalent` cooler (`95% CI
[-0.139, -0.0004]`). The direction is consistent with the cool displacement, but the
effect is small, heterogeneous, in-sample, and conditioned on models trained on the
defective input.

The corpus repair must cover more than the two daily scalars. The same issue-less
stitched source also feeds all forecast-profile features, three forecast-relative
marine features, the forecast-error secondary artifact, the late-day continuation
artifact, and analog selection. The first-retrain contract should either rebuild each
from cutoff-valid issue rows or exclude it.

## Run boundary

This was a measurement-only run from exact base
`027f65bfde2b2fbb6f6865f393e85c712a8d13ec` on branch
`codex/workstation-size-forecast-lookahead-2026-08-29a`. All generated evidence is
under the single declared run root:

`C:\Users\Michael\Documents\github\weather\scratch\runs\forecast-lookahead-2026-08-29a`

The repository `data/` ACL was verified before and after the run. Both the operator
identity and `CodexSandboxOffline` retain explicit deny entries for write and delete.
No provider call, network read, fetch, archive write, fit, candidate, promotion,
pointer change, serving change, scheduler change, or fresh/reserved date was used.
The measurement read only 2021–2025 May 10–June 30 forecast rows, the matching
configured-WU settlement prefix, the matching WU hourly year/month partitions, and
tracked frozen HGB artifacts.

## Method

- Paired universe: 12 markets x 260 dates x 7 fixed leads = `21,840`
  market-date-lead rows. Coverage is `100%` in stitched daily, fixed-lead daily, and
  configured-WU settlement inputs.
- Difference sign: `stitched - fixed lead`; negative means the stitched archive is
  cooler. Positive MAE advantage means stitched is closer to settlement.
- Market tables remain in each market's native settlement unit. Fleet aggregation
  divides Fahrenheit deltas by 1.8 and reports C-equivalent differences.
- Every interval is a two-sided 95% Student-t interval over the five annual means,
  rather than an IID interval over thousands of correlated market-days.
- Fixed lead 1 is the conservative honest comparator for model sensitivity. Its
  stored issue-time basis is `fixed_lead_day_offset`; it is safe before any
  target-day cutoff but is not an exact reconstruction of a named model run.
- The no-fit sensitivity pass rebuilds the exact selected legacy feature shape from
  matching WU hourly observations, then changes only `forecast_high` and its derived
  `forecast_gap`. It scores the tracked per-market HGB unchanged. `43,673 / 43,680`
  rows (`99.984%`) score; seven Toronto rows on 2024-06-25 have no usable historical
  record through 13:00 and are explicitly listed as skipped.

## Fleet result by lead

All values below are C-equivalent. The stitched forecast's own settlement error is
constant across comparators: bias `-0.154`, MAE `0.715`, and RMSE `1.047`.

| Lead | Stitched - lead, mean (95% CI) | Fixed-lead bias | Fixed-lead MAE | Stitched MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | -0.707 [-1.548, +0.134] | +0.553 | 1.638 | +0.923 [+0.550, +1.296] | 72.4% |
| 2 | -1.122 [-1.606, -0.639] | +0.968 | 1.959 | +1.244 [+0.960, +1.528] | 76.9% |
| 3 | -1.219 [-1.674, -0.763] | +1.065 | 2.108 | +1.393 [+1.101, +1.685] | 77.6% |
| 4 | -1.290 [-1.743, -0.837] | +1.136 | 2.291 | +1.575 [+1.338, +1.813] | 80.1% |
| 5 | -1.242 [-1.686, -0.797] | +1.088 | 2.408 | +1.692 [+1.502, +1.883] | 80.4% |
| 6 | -1.386 [-1.874, -0.899] | +1.232 | 2.623 | +1.908 [+1.625, +2.190] | 81.7% |
| 7 | -1.635 [-2.110, -1.160] | +1.481 | 2.867 | +2.151 [+1.997, +2.305] | 82.6% |

Lead 1 is temporally heterogeneous: its annual signed differences are `-0.570`,
`-1.403`, `-1.422`, `-0.135`, and `-0.005 C-equivalent`. Its annual MAE advantages
are positive in every year: `+0.809`, `+1.306`, `+1.177`, `+0.652`, and `+0.671`.
That is why the sign interval crosses zero while the accuracy interval does not.

## Market-by-lead result

Each row is in the market's native unit (`F` except Toronto in `C`). “Delta” is
stitched minus the fixed lead; “MAE advantage” is fixed-lead absolute error minus
stitched absolute error. Both columns show mean and year-clustered 95% CI. The full
distribution (median, p05, p25, p75, p95, standard deviation, signed biases, RMSE,
and annual means) is in `market-lead-summary.csv` in the run root.

### Atlanta (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | -1.75 [-3.16, -0.35] | +1.84 [+1.29, +2.40] | 82.7% |
| 2 | -2.30 [-2.70, -1.89] | +2.20 [+1.52, +2.88] | 86.5% |
| 3 | -2.57 [-3.42, -1.73] | +2.49 [+1.67, +3.30] | 85.4% |
| 4 | -2.81 [-3.55, -2.07] | +2.93 [+2.63, +3.23] | 82.7% |
| 5 | -2.54 [-3.41, -1.67] | +3.12 [+2.60, +3.63] | 83.1% |
| 6 | -2.91 [-3.87, -1.94] | +3.34 [+2.69, +3.99] | 83.1% |
| 7 | -3.27 [-4.58, -1.97] | +3.78 [+3.03, +4.52] | 89.6% |

### Austin (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | -2.26 [-5.58, +1.06] | +2.43 [+0.63, +4.23] | 77.3% |
| 2 | -3.31 [-6.44, -0.18] | +3.33 [+1.79, +4.87] | 82.7% |
| 3 | -3.51 [-6.25, -0.76] | +3.52 [+2.10, +4.93] | 82.7% |
| 4 | -3.42 [-6.14, -0.69] | +3.53 [+2.13, +4.93] | 85.8% |
| 5 | -3.29 [-5.54, -1.03] | +3.86 [+2.92, +4.81] | 86.2% |
| 6 | -3.15 [-4.72, -1.58] | +3.84 [+3.07, +4.60] | 89.6% |
| 7 | -3.18 [-4.87, -1.49] | +4.08 [+3.67, +4.50] | 89.6% |

### Chicago (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | +0.56 [-0.65, +1.76] | +1.69 [+1.28, +2.09] | 75.8% |
| 2 | +1.42 [+0.89, +1.94] | +2.03 [+1.81, +2.25] | 80.0% |
| 3 | +1.38 [+0.37, +2.39] | +2.71 [+2.49, +2.93] | 81.9% |
| 4 | +1.28 [-0.11, +2.67] | +3.18 [+2.45, +3.91] | 88.8% |
| 5 | +1.31 [-0.22, +2.84] | +3.47 [+3.13, +3.82] | 86.9% |
| 6 | +0.75 [-1.00, +2.50] | +3.77 [+2.96, +4.58] | 87.7% |
| 7 | -0.61 [-2.81, +1.59] | +4.85 [+4.20, +5.49] | 90.4% |

### Dallas (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | -3.08 [-7.29, +1.13] | +0.27 [-0.55, +1.09] | 52.7% |
| 2 | -5.14 [-8.08, -2.20] | +0.21 [-0.86, +1.27] | 44.2% |
| 3 | -5.11 [-7.82, -2.40] | +0.31 [-0.67, +1.28] | 48.1% |
| 4 | -5.35 [-8.17, -2.52] | +0.70 [-0.10, +1.50] | 51.5% |
| 5 | -5.17 [-7.57, -2.77] | +0.80 [-0.05, +1.65] | 52.3% |
| 6 | -5.32 [-7.40, -3.24] | +1.02 [-0.19, +2.24] | 56.2% |
| 7 | -5.44 [-7.49, -3.39] | +1.10 [+0.02, +2.18] | 52.3% |

### Denver (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | -1.61 [-3.02, -0.20] | +1.65 [+0.99, +2.32] | 71.5% |
| 2 | -1.18 [-2.37, +0.00] | +1.69 [+1.23, +2.15] | 74.2% |
| 3 | -1.62 [-2.89, -0.35] | +2.21 [+1.58, +2.84] | 76.5% |
| 4 | -1.84 [-3.22, -0.46] | +2.79 [+2.08, +3.49] | 83.1% |
| 5 | -1.92 [-3.53, -0.31] | +3.44 [+2.79, +4.10] | 82.7% |
| 6 | -2.72 [-4.23, -1.20] | +4.03 [+3.30, +4.76] | 85.0% |
| 7 | -3.53 [-4.30, -2.76] | +5.14 [+4.26, +6.01] | 85.8% |

### Houston (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | -1.69 [-3.01, -0.38] | +1.75 [+0.39, +3.10] | 70.8% |
| 2 | -2.12 [-3.39, -0.85] | +2.38 [+1.15, +3.61] | 81.2% |
| 3 | -2.31 [-3.83, -0.79] | +2.62 [+1.31, +3.92] | 80.0% |
| 4 | -2.34 [-3.89, -0.80] | +2.86 [+1.53, +4.18] | 81.2% |
| 5 | -2.48 [-3.75, -1.21] | +2.89 [+1.65, +4.14] | 85.0% |
| 6 | -2.41 [-3.16, -1.66] | +2.94 [+1.85, +4.03] | 83.1% |
| 7 | -2.40 [-3.03, -1.76] | +3.00 [+1.83, +4.17] | 83.5% |

### Los Angeles (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | -0.95 [-2.17, +0.27] | +1.26 [+0.58, +1.94] | 74.6% |
| 2 | -2.19 [-2.96, -1.42] | +2.14 [+1.51, +2.76] | 83.5% |
| 3 | -2.41 [-3.14, -1.68] | +2.35 [+1.69, +3.00] | 80.8% |
| 4 | -2.55 [-3.32, -1.79] | +2.56 [+1.84, +3.28] | 84.6% |
| 5 | -2.48 [-3.19, -1.78] | +2.63 [+2.06, +3.19] | 83.5% |
| 6 | -2.68 [-3.42, -1.95] | +2.78 [+2.15, +3.42] | 85.4% |
| 7 | -2.82 [-4.10, -1.54] | +2.96 [+1.86, +4.07] | 87.7% |

### Miami (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | -0.92 [-3.24, +1.40] | +0.88 [+0.17, +1.60] | 64.6% |
| 2 | -1.87 [-2.82, -0.92] | +1.00 [+0.25, +1.75] | 70.4% |
| 3 | -2.01 [-2.68, -1.33] | +1.03 [+0.36, +1.70] | 66.5% |
| 4 | -2.04 [-2.69, -1.40] | +1.16 [+0.37, +1.95] | 70.0% |
| 5 | -1.98 [-2.56, -1.40] | +1.09 [+0.43, +1.75] | 63.8% |
| 6 | -1.85 [-2.63, -1.07] | +1.28 [+0.57, +1.99] | 67.3% |
| 7 | -1.98 [-2.93, -1.02] | +1.45 [+0.77, +2.13] | 70.0% |

### NYC (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | -0.25 [-2.05, +1.55] | +1.37 [+0.64, +2.10] | 68.1% |
| 2 | -0.74 [-1.70, +0.21] | +1.51 [+0.65, +2.37] | 70.4% |
| 3 | -0.95 [-1.66, -0.24] | +1.92 [+1.11, +2.72] | 76.5% |
| 4 | -1.08 [-1.93, -0.23] | +2.97 [+2.22, +3.72] | 81.2% |
| 5 | -0.89 [-1.87, +0.08] | +2.88 [+2.40, +3.36] | 79.6% |
| 6 | -1.18 [-2.89, +0.52] | +3.87 [+3.14, +4.61] | 83.5% |
| 7 | -1.62 [-3.51, +0.28] | +3.86 [+3.61, +4.11] | 78.8% |

### San Francisco (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | -3.24 [-8.23, +1.75] | +2.77 [-0.18, +5.71] | 69.2% |
| 2 | -6.10 [-6.85, -5.35] | +4.92 [+3.55, +6.29] | 82.3% |
| 3 | -6.14 [-6.77, -5.51] | +5.05 [+3.88, +6.21] | 85.0% |
| 4 | -6.20 [-7.40, -5.01] | +5.27 [+4.18, +6.37] | 85.4% |
| 5 | -6.02 [-6.38, -5.66] | +5.22 [+4.41, +6.03] | 85.8% |
| 6 | -6.56 [-7.39, -5.74] | +5.93 [+5.00, +6.86] | 82.7% |
| 7 | -6.71 [-8.07, -5.36] | +6.34 [+5.13, +7.55] | 85.0% |

### Seattle (F)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | -1.08 [-4.05, +1.89] | +2.20 [+1.10, +3.30] | 81.9% |
| 2 | -2.57 [-4.31, -0.82] | +2.91 [+1.57, +4.26] | 83.1% |
| 3 | -2.83 [-4.48, -1.19] | +3.22 [+1.94, +4.49] | 83.1% |
| 4 | -3.10 [-4.63, -1.57] | +3.43 [+2.33, +4.52] | 85.4% |
| 5 | -3.17 [-4.43, -1.91] | +3.82 [+2.78, +4.87] | 88.1% |
| 6 | -3.36 [-4.65, -2.08] | +4.22 [+3.25, +5.19] | 87.3% |
| 7 | -4.06 [-6.60, -1.53] | +5.51 [+4.12, +6.91] | 91.2% |

### Toronto (C)

| Lead | Delta (95% CI) | MAE advantage (95% CI) | Stitched closer |
| ---: | ---: | ---: | ---: |
| 1 | +0.56 [-0.55, +1.67] | +1.02 [+0.58, +1.45] | 79.2% |
| 2 | +1.03 [+0.32, +1.75] | +1.42 [+1.19, +1.65] | 84.2% |
| 3 | +0.98 [+0.32, +1.64] | +1.49 [+1.22, +1.77] | 84.6% |
| 4 | +0.88 [+0.36, +1.40] | +1.47 [+1.40, +1.55] | 81.9% |
| 5 | +1.01 [+0.07, +1.95] | +1.84 [+1.59, +2.09] | 87.3% |
| 6 | +0.81 [-0.17, +1.79] | +2.32 [+1.94, +2.69] | 89.2% |
| 7 | +0.17 [-1.26, +1.60] | +2.44 [+1.97, +2.92] | 87.7% |

## Direction and bounded model consequence

The fleet sign is cooler, not warmer. At lead 1, stitched is warmer on only
`38.1%` of market-days and exactly equal on `1.5%`. Leads 2–7 are significantly
cooler at fleet level. Market direction is not universal: Toronto and Chicago are
usually warmer than the fixed leads, while most US markets are cooler.

All 168 frozen market-hour bundles select `forecast_high` and `forecast_gap`, but
tree inspection shows an actual split on at least one of them in `154 / 168`
(`91.7%`). The 14 Atlanta bundles select the columns but never split on them; their
lead-1 substitution is therefore exactly inert.

The frozen substitution is a sensitivity bound, not a counterfactual retrain:

| Metric | Fleet mean | Year-clustered 95% CI | Interpretation |
| --- | ---: | ---: | --- |
| Raw HGB signed centre, stitched - lead 1 | -0.100 C-equivalent | [-0.199, -0.001] | Stitched-trained HGB is mechanically cooler. |
| Pre-floor blend-weighted signed centre | -0.070 C-equivalent | [-0.139, -0.0004] | Direction is consistent with observed cool displacement. |
| Raw HGB absolute centre movement | 0.310 C-equivalent | [0.259, 0.360] | Average magnitude before empirical blending. |
| Pre-floor blend-weighted absolute movement | 0.226 C-equivalent | [0.189, 0.264] | Practical centre-movement bound with the stored blend weights. |
| Blend-weighted total-variation distance | 0.122 | [0.110, 0.134] | Nontrivial probability-mass sensitivity. |
| Raw HGB Brier advantage of stitched input | +0.080 | [+0.060, +0.101] | Upward-biased, because the frozen model was fit on stitched input. |
| Raw HGB centre-MAE advantage | +0.149 C-equivalent | [+0.087, +0.211] | Also in-sample; not causal retrain lift. |

The absolute centre sensitivity falls through the day: `0.380 C-equivalent` at
07:00, `0.337` at 10:00, `0.227` at 13:00, `0.131` at 16:00, and `0.118` at 20:00.
The trusted observed-high floor and later normalization were not weakened or replayed;
they can further constrain the served consequence. Holding the non-HGB distribution
fixed makes the blend-weighted centre difference exact before that floor, but no-fit
measurement cannot identify the quality of an honestly retrained model.

This bounds the concern usefully:

- The archive feature itself receives roughly `0.92 C-equivalent` of apparent MAE
  advantage from using stitched rather than lead-1 values.
- The current frozen model translates that into only `0.07 C-equivalent` of average
  signed centre displacement, though individual-row probability mass moves enough to
  produce a `0.23 C-equivalent` average absolute centre movement.
- The direction is consistent with, but does not establish, the cool-bias mechanism.
  Most market-level signed intervals cross zero, and the artifact was trained on the
  same defective feature being substituted.

## Provenance audit

The audit followed every direct `load_forecast_daily`, `load_forecast_profiles`, and
`load_marine_water_contrast_features` consumer and inspected the feature loaders used
by the current and pooled training assemblies.

| Surface | Finding | Current consequence | Required repair |
| --- | --- | --- | --- |
| `forecast_high`, `forecast_gap` | `forecast_daily.csv` contains only `local_date,forecast_high_c`; `load_forecast_daily` has no issue-time contract. | Current base HGB, late-day artifact, pooled assembly, and analog selection consume it. | Select the newest issue valid at each training cutoff from an issue-preserving corpus. |
| All `FORECAST_PROFILE_COLUMNS` | `forecast_long.csv` retains source, model, issue basis, lead, and payload hash, but historical rows have blank issue time and `stitched_continuous_archive`. `load_forecast_profiles` then returns only values and valid times, discarding those provenance fields. | Not selected by the 168 legacy market HGBs, but selected by the pooled v0.3 feature universe and therefore relevant to the first retrain. | Build cutoff-valid hourly profiles from issue-preserving rows; do not repair only the daily high. |
| `marine_water_minus_forecast_high`, `marine_onshore_water_minus_forecast_high`, `marine_onshore_cooling_potential` | The marine sidecar builder defaults to `load_forecast_daily`; its row provenance hashes station/SST inputs but not the forecast issue used in these three derived fields. Its loader drops all remaining metadata. | Not in the legacy 168 bundles; present in the pooled feature universe and seven local market sidecars. | Rebuild with a cutoff-valid forecast receipt embedded in sidecar provenance, or exclude the three forecast-relative columns. |
| Forecast-error secondary artifact | `forecast_rows_from_daily_archive` reads the same two-column file, assigns source `open_meteo`, `capture_hour=None`, and `horizon_bucket=daily`. The tracked artifacts' validation reports include daily-archive rows (Toronto reports `n=332`). | Learned source bias/reliability can inherit the lookahead even outside the HGB feature path. | Rebuild daily-archive rows from issue-conditioned forecasts, or omit them and retain only captured snapshot rows. |
| Late-day continuation and analog distance | Both reuse `forecast_high`/`forecast_gap` from the two-column loader. | Same defect, not a new independent source. | Route them through the same cutoff-valid resolver; no compatibility fallback to stitched data. |
| Reanalysis/synoptic sidecar | Its loader drops metadata, but features are explicitly antecedent-day and lagged-month/season values; the stored row retains `antecedent_date`. | No same-class lookahead found. | Preserve/bind metadata in the PIT manifest, but no defect found in its time construction. |
| Marine station/SST features not relative to forecast | The loader drops row provenance, but station rows are explicitly filtered to wall time and the sidecar retains station/SST hashes and cutoff policy. | No same-class lookahead found in the non-forecast-relative columns. | Bind the sidecar manifest in training evidence; no corpus exclusion is required from this audit. |
| WU observation-derived fields | Hourly rows carry local/valid times and the feature builder filters them to cutoff (apart from the separately intentional live-reading simulation). | No issue-provenance defect found. | Keep existing cutoff and trusted-floor contracts. |

The critical new finding is the profile path: repairing only `forecast_daily.csv` would
leave the first pooled retrain exposed to the same stitched archive through dozens of
shape, cloud, radiation, precipitation, and thermodynamic features.

## First-retrain recommendation

Keep the `-08-28a` plan, but make these acceptance criteria explicit before the first
fit starts:

1. Training rows from 2021–2025 must bind an issue-preserving daily forecast and hourly
   profile whose `issue_time <= row cutoff`. Missing cutoff-valid input remains missing;
   the old stitched compatibility files are not a fallback.
2. `forecast_high`, `forecast_gap`, every populated forecast-profile field, and every
   forecast-relative marine field must carry the selected upstream issue identity or a
   receipt hash into the immutable training graph.
3. Rebuild the forecast-error secondary artifacts from the same PIT resolver, or exclude
   their issue-less daily-archive rows from the first retrain.
4. Route late-day training and analog construction through the same resolver so train,
   serve, and research do not silently diverge.
5. Report both coverage loss and honest blocked validation. The measured `+0.923
   C-equivalent` lead-1 MAE advantage shows that the 2021–2025 restriction buys real
   epistemic honesty; sample count alone is not a reason to restore stitched rows.

No serving, artifact, or training-code change was made in this mission.

## Evidence receipts

The two scripts are retained in the run root:

- `measure_forecast_lookahead.py` — SHA-256
  `a8f8261b041f34f8aff5f0667e603580c1ad00059886a4606052ab6ae62091c5`;
- `measure_frozen_model_sensitivity.py` — SHA-256
  `302353408ec8df31afa3e4aead82878449cc0c20003526ac3353da67b0409026`.

Primary evidence:

| File | SHA-256 |
| --- | --- |
| `evidence-manifest.json` | `9c822700b8a66eab6c17cf3be2adaeb9e50f80404c14a9790e99d36b658e6cf0` |
| `paired-observations.csv` | `fd912dbe13da8e5236e1e3ba15b91090657db075ddf0978454c4fa543543d3e1` |
| `market-lead-summary.csv` | `0eb17ba638b297aaaa579a33829b7c0a1bd78147e7385e2093b78ab554757af3` |
| `fleet-lead-summary.csv` | `cf358f93a7bbf4730fe6b2d14a4c772766730e1f3d39f1b1419a45981d51d4cf` |
| `coverage.csv` | `aa44f64007e211a73c118937c8f06aa1480705261179485c39e850686d9e15c7` |
| `frozen-model-evidence-manifest.json` | `065beff391401d651211c74f26c53b2bcd019465f921f59f63a5840e78e4c17c` |
| `frozen-model-observations.csv` | `6b3e530df3dc97abfbf5f59064e5394569eb79ec072c463993b3227d45ece49b` |
| `frozen-model-market-summary.csv` | `aa9f047f0895eaee9e64c49650c0376c2c45f00ac3817062d532ce67bed9974c` |
| `frozen-model-cutoff-summary.csv` | `6a62ab6bdcb052d0c81ea96b6c381ffa21debc5b31f3cd9bea7064ee24855e97` |
| `frozen-model-skipped-observations.csv` | `d33893cbe590185824d7ce65f3d18fccb9fedc02aae50b08f7104fbabb561fb2` |

Both manifests contain per-market hashes of the exact selected forecast,
settlement, WU-hourly, and frozen-artifact inputs. The run root is outside the Git
worktree and none of these generated files is a promotion or release artifact.
