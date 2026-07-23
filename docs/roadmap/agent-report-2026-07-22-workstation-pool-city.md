# Agent Report - 2026-07-22 Pooled vs Per-City Training

## Outcome

**Keep the pooled geographic training topology.** On the untouched 2025
confirmation window, the canonical continuous-density HGB trained across all
12 markets materially outperformed both one-model-per-city training and
leave-one-city-out (LOCO) training. This is a research conclusion about model
topology, not permission to promote an artifact or trade live.

Equal-city macro market-band Brier was `0.047053` pooled, `0.071389` per-city,
and `0.070298` LOCO. Relative to the alternatives, pooled reduced macro Brier
by 34.1% and 33.1%, respectively. It also won on density log loss, winning-
bucket Brier, and point-forecast MAE, so the result is not an artifact of one
proper score or one weighting convention.

| Confirmation metric | Pooled | Per-city | LOCO |
| --- | ---: | ---: | ---: |
| equal-city macro band Brier | 0.047053 | 0.071389 | 0.070298 |
| equal-city macro band log loss | 0.184811 | 0.308333 | 0.378625 |
| equal-city macro winner Brier | 0.435050 | 0.575592 | 0.526390 |
| equal-city macro MAE F | 1.0424 | 1.3434 | 1.7618 |
| band-weighted micro Brier | 0.047623 | 0.072138 | 0.070768 |

## Frozen design

- Markets: all 12 built-ins, 11 settling in F and Toronto settling in C.
- Hours: 07 through 20 local, one model per hour and training scope.
- Balanced panel: 162 complete fleet dates and 12 x 14 rows per retained date.
- Training: 2015-2023, 133 dates and 22,344 rows.
- Development: 2024 only, 15 dates and 2,520 rows; used only to choose density
  width and shape.
- Confirmation: 2025 only, 14 dates and 2,352 rows; scoring only.
- Feature context: climate and static source-reliability context frozen as of
  `2024-01-01` exclusive, before development or confirmation assembly.
- Models: 350 total = 14 pooled + 168 per-city + 168 LOCO.
- Trainer, feature frame, HGB hyperparameters, canonical-F density grid, and
  native C/F market-band projection were identical across regimes. Only the
  geographic fit scope changed.
- LOCO excluded the scored market from both training and 2024 density tuning.

The input manifest contains 262 path records: 245 were opened/read, 12 were
checked present without being opened, and five were checked and absent. It
binds 455,841,527 read bytes. All present files were independently rehashed
immediately before execution with zero mismatches. The source mirror remained
read-only.

Key identities:

- run ID: `df853773dfea2af3e1f1bb1227248ac34d640d99f907ea173ee8f838adc30f1b`;
- corpus contract: `981e406e40612f84aaf80b9c8afc9fa7b79b5cf9ad2427bc882dd32e247c12eb`;
- input-manifest contract: `86b6838c3a46371cc5bf8b8719243414430319e7870464e4d70229a0326de07e`;
- executed model-source contract:
  `6dcd4541174958df20677e24ddef87f6eb9b7eeffe1f8da0b056bed923fcdcb0`.

## Paired confirmation evidence

The primary paired comparison aggregates the exact native-band sufficient
statistics by whole fleet date. Delta is left minus right Brier, so negative
favors the left regime. Intervals use 10,000 bootstrap resamples of the 14
fleet dates; the sign test is exact.

| Unit | Comparison | Mean delta | 95% CI | Better / worse dates | Sign p |
| --- | --- | ---: | ---: | ---: | ---: |
| ALL | pooled - per-city | -0.024467 | [-0.028466, -0.020592] | 14 / 0 | 0.000122 |
| ALL | pooled - LOCO | -0.023172 | [-0.026538, -0.019762] | 14 / 0 | 0.000122 |
| ALL | per-city - LOCO | +0.001295 | [-0.004858, +0.007322] | 6 / 8 | 0.790527 |
| C | pooled - per-city | -0.018347 | [-0.037293, -0.002220] | 11 / 3 | 0.057373 |
| C | pooled - LOCO | -0.012824 | [-0.018345, -0.006950] | 12 / 2 | 0.012939 |
| F | pooled - per-city | -0.024888 | [-0.029351, -0.020748] | 14 / 0 | 0.000122 |
| F | pooled - LOCO | -0.023967 | [-0.027581, -0.020206] | 14 / 0 | 0.000122 |

An equal-city-per-date sensitivity check reaches the same conclusion: pooled
beats per-city on all 14 dates with mean delta `-0.023393`, and beats LOCO on
all 14 with mean delta `-0.023341`. Thus the fleet result is not caused by
cities with more synthetic bands receiving more weight.

Toronto is the only C market. Its pooled-versus-per-city bootstrap interval is
below zero, but the exact sign test is just above 0.05 and the mean is more
favorable than the median (`-0.018347` versus `-0.007439`) because three dates
have large improvements. This is evidence for Toronto, not broad proof for a
multi-city Celsius family.

## Hour and city robustness

Pooled has lower band Brier than both alternatives at every one of the 14
hours in both development and confirmation. The time profile is stable across
years:

| Split / window | Pooled | Per-city | LOCO | Pooled - per-city | Pooled - LOCO |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2024 hours 07-14 | 0.095236 | 0.102440 | 0.134550 | -0.007204 | -0.039315 |
| 2024 hours 15-20 | 0.015101 | 0.063433 | 0.024196 | -0.048332 | -0.009096 |
| 2025 hours 07-14 | 0.090507 | 0.096568 | 0.128279 | -0.006061 | -0.037771 |
| 2025 hours 15-20 | 0.012130 | 0.051918 | 0.023169 | -0.039788 | -0.011039 |

Per-city beats LOCO at hours 07-14, while LOCO beats per-city at hours 15-20,
with the crossover occurring at exactly the same boundary in both years.
Pooled dominates both sides of that tradeoff: cross-city sample size is most
valuable early, while market identity and shared late-day learning prevent the
large late-hour degradation of small per-city fits.

A diagnostic hour-gated hybrid selected the better unpooled topology using
2024 only: per-city at 07-14 and LOCO at 15-20. Its 2025 micro Brier is
`0.056408`, better than either unpooled regime alone but still behind pooled
`0.047623`. Pooled beats that hybrid on all 14 confirmation dates; the mean
daily delta is `-0.008806`, with a 10,000-resample date bootstrap interval
`[-0.011735,-0.005983]` (seed `20260725`). This post-hoc sensitivity rules out
a simple hour gate as an explanation for pooled's win; it is not a new
promotion test.

On confirmation aggregate Brier, pooled beats per-city in all 12 markets and
LOCO in 11 of 12. The exceptions and weak spots matter:

- Atlanta is effectively tied against LOCO: pooled - LOCO is `+0.000244` in
  the aggregate and the daily comparison is 7 wins / 7 losses.
- Miami's pooled - per-city aggregate is only `-0.000779`; under equal daily
  weighting it is `-0.000132`, and pooled wins only 4 of 14 dates. A few large
  gains drive its favorable aggregate.
- Pooled's largest LOCO gains occur in San Francisco (`-0.087807`) and Los
  Angeles (`-0.049781`), while Dallas is nearly tied (`-0.000407`).

The mean predictions clarify the failure modes. Per-city confirmation bias is
nearly zero (`+0.0125 F`) but its MAE is `1.3434 F`, versus pooled bias
`+0.0971 F` and MAE `1.0424 F`; per-city loses through variance and small
hourly samples, not a simple fleet bias. Each per-city model has only 133
training rows, versus 1,596 pooled. LOCO has 1,463 rows but exhibits
market-transfer bias (`+0.4042 F` overall; `+0.4936 F` for F markets and
`-0.5789 F` for Toronto) and MAE `1.7618 F`.

A point-mean blend sensitivity offers little evidence that the discarded
topologies contain complementary signal. On a 0.01 weight grid, 2024 MAE
selects 100% pooled against both per-city and LOCO. Tuning RMSE selects 97%
pooled / 3% per-city and 100% pooled / 0% LOCO. The 3% per-city blend changes
2025 RMSE only from `1.8844 F` to `1.8781 F` and MAE from `1.0424 F` to
`1.0405 F`; no native-band probabilities were available for a proper-score
blend. Treat that tiny point-only change as motivation to test principled
partial pooling on new data, not as a candidate result.

## Runtime, checkpoints, and identity correction

The completed model loop took 1,187.1 seconds (19.8 minutes); total execution
including corpus load, pilot, aggregation, and reporting took 1,226.3 seconds
(20.4 minutes), close to the 1,243.8-second pilot estimate. Peak observed
worker private memory was approximately 1.94 GiB and working set approximately
0.52 GiB. The workstation retained roughly 4.8-8.4 GiB of available physical
memory during the run, so neither stop condition fired.

The harness's pre-run matrix-derived memory estimate was only 107.6 MB, roughly
19 times below the observed whole-process private allocation. It is therefore a
model-state sizing hint, not a process-memory ceiling. External process
monitoring was authoritative for this run; a future harness revision should
sample private allocation after corpus load before admitting the full model
loop.

An identity defect was caught after the first 40 tasks of an earlier attempt:
measured corpus `load_seconds` had been included in the corpus hash. Identical
inputs and source therefore changed the run ID from the original READY plan
`86ae7cea...` to `8b4e4670...`. That process was stopped. Both the original
plan and all 40 partial checkpoints are preserved under
`scratch/workstation-research-output/workstream_b/pool_city/quarantine/` and
are never reused.

Timing now lives under an explicitly non-contractual field. Two independent
replacement plans took 17.287934 and 16.790560 seconds to load but produced the
same run ID, corpus contract, input manifest, and source contract. The full run
then completed under that replacement ID.

One reporting-only bug initially wrote `runtime.resumed_tasks = 350` by
counting the completion timestamp present on every checkpoint. The
authoritative checkpoint ledger records zero resumed training tasks. Final
aggregation and all 10,000-resample comparisons were regenerated in 0.73
seconds from the 350 completed exact-ID checkpoints, without fitting a model.
The corrected artifact records zero resumed tasks and 350 checkpoints reused
for finalization. Validation proved:

- run ID unchanged;
- results and paired evidence exactly equal before and after correction;
- predictions byte-for-byte equal;
- 350 checkpoint identities valid, zero missing or mismatched;
- newest checkpoint predates reporting correction by more than seven minutes.

The original artifact had also mislabeled the trainer module as
`pooled_band_training`; the callable actually imported through
`pooled_feature_model` is defined in `pooled_density_training`. This affects
only the recorded label, not the invoked function or hashed source. The
correction is explicit in the final JSON, and future checkpoints use the
correct import path.

## Output safety and verification

The benchmark now resolves the supplied data root and refuses any output that
lands inside it before creating a directory. Tests cover a literal
`data/scratch` path and a Windows junction under repository scratch that
resolves back into the mirror. The companion offline Tmax evaluator and
radiation backfill similarly resolve and reject every output, report, raw-cache,
and derived-data target, including relative `..` aliases and nested junctions,
before computation, network use, or writes.

Four benchmark-internal schemas are registered: balanced panel, input
manifest, runtime plan, and checkpoint status. The strict repository scan
reports 835 discovered literals and zero unregistered versions.

Verification completed:

- benchmark focused tests, including deterministic identity, path aliases,
  checkpoint status invariants, and exact scorer parity;
- offline predictor and radiation path-contract suites;
- schema-registry suite and strict literal audit;
- optional-import architecture ratchet after making scikit-learn a required
  dependency.

The broader architecture file has one expected worktree-state failure because
19 project-critical files from parallel workstreams are intentionally
untracked until integration; its other tests pass.

Primary output directory:
`scratch/workstation-research-output/workstream_b/pool_city/`.

Primary files and SHA-256:

- `pool_city_training_benchmark.json`:
  `6e0f5b1fa4941e4f880350cf71b100bf591afc2d6595acdce4ee73125ca7e440`;
- `pool_city_training_benchmark.md`:
  `057ab9fbb183b4b26bd8a1d991dd02cf41b053b5a53a418cadaaed616035e450`;
- `predictions.csv`:
  `b8a66855a8e640b47f2879c46989f0d1927882cea6411b6f345a145bc1b6d3d3`;
- 350-file checkpoint inventory, sorted as
  `<relative path><TAB><size><TAB><sha256><LF>`:
  `4d5301c7bb8d8bcd1e8db67d584f92c8a2eeaac04d88eccbe0252ef5cefe3a1e`.

## Limits and disposition

The confirmation evidence comprises only 14 complete July fleet dates, and
complete-panel filtering can select for cleaner days. The C family contains
only Toronto. Hour/city slices are post-hoc diagnostics without multiplicity
adjustment. This is not release-bound captured-input replay, and forecast
skill is not evidence of edge over market prices.

Within those limits, pure per-city training and pure LOCO transfer are both
decisively rejected as replacements for pooled training. Preserve pooled as
the research baseline. The next useful topology experiment is hierarchical or
partial pooling, evaluated on genuinely new fleet dates or additional
predeclared seasonal windows; do not tune a new topology on the 2025
confirmation outcomes reported here. No serving, release, collector, or live-
trading change follows from this result.
