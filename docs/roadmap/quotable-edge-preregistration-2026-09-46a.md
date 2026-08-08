# Quotable-edge pre-registration 2026-09-46a

Status: frozen before outcome inspection for mission `-09-46a`.

This declaration implements
[`workstation-handoff-2026-09-46a-does-a-quotable-edge-exist.md`](workstation-handoff-2026-09-46a-does-a-quotable-edge-exist.md).
It is committed before the analysis reads the `outcome` or squared-error columns. The result commit
must not change this file. Its SHA-256 and commit hash must be reported in the handback.

## 1. Frozen population and positive control

The analysis uses the repaired served distribution on the sealed `-09-34a` replay population:

| Evidence | Required value |
| --- | --- |
| Repaired band rows | `scratch/runs/gap-remeasure-repaired-2026-09-44a/band-score-rows.csv` |
| Band-row SHA-256 | `9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae` |
| Measurement manifest SHA-256 | `cf21b67e3236395da800176c27e5c3a571a838e8cc28a491ec48e23e497e7c3e` |
| Support | 50 dates, 12 markets, 524 promotion-countable market-days, 12,289 snapshots, 135,179 band rows |
| Target dates | `2026-06-03` through `2026-07-30` only |
| Provenance | wholly before the `2026-07-31` / `b77cfbed` boundary |

The analysis must stop before reading outcomes unless a fresh or retained `-09-43a` replay receipt
reports `status=PASS`, `positive_control.status=PASS`, `rows=840`, `exact_rows=840`, and maximum
recorded-distribution L1 difference `0`. This is the required pre-repair-code versus recorded-
incumbent positive control. The receipt SHA-256 goes in the final report.

The predictor-preparation phase may read only roster, probability, forecast, and captured-book
columns. It writes a predictor sidecar and quantile thresholds before the outcome phase starts. The
outcome phase must bind their hashes, this declaration's hash, the positive-control hash, and the
band-row hash in its result manifest. Reserved dates remain none at declaration time; the maximum
date above is nevertheless fail-closed.

## 2. Endpoint and sign

For band row `i`, repaired served probability is `q_i`, captured market YES mid-price is `m_i`, and
the one-hot settlement outcome is `y_i`.

```text
model Brier  = mean((q_i - y_i)^2)
market Brier = mean((m_i - y_i)^2)
edge         = market Brier - model Brier
```

Positive edge favors the model. Market probabilities are not renormalized for scoring, preserving
the retained comparator. Snapshot-level partitions include every band in each selected snapshot;
band-level partitions select individual band rows. Every reported value remains mean one-versus-
rest binary band Brier, so P0 and P1 share the same squared-probability unit.

## 3. Quote-time predictors

Only information captured at or before the effective cutoff may define membership:

- local effective cutoff hour, market, and the predeclared in-season `B` / out-of-season `C` stratum;
- repaired-model and captured-market probabilities;
- normalized categorical entropy of each snapshot distribution (market probabilities are normalized
  only for this predictor, never for scoring), plus model-minus-market entropy;
- the serving extractor's cutoff-aligned `forecast_high`, `forecast_disagreement`, and
  `forecast_source_count`; disagreement is converted to Celsius-equivalent only to make fleet bins
  comparable;
- band midpoint minus `forecast_high`, measured in native one-degree settlement-band units; tail
  bands use their printed boundary;
- captured `best_bid`, `best_ask`, cumulative volume, and liquidity from the identical tape row.

No settlement, outcome, squared error, winner label, hindsight market correctness, post-cutoff row,
or outcome-derived feature may define membership.

Entropy quartiles use NumPy linear quantiles over the 12,289 predictor-only snapshot rows. The exact
cutpoints are written and hashed before outcomes are unsealed. Ties go to the lower quartile; duplicate
cutpoints leave a declared cell empty rather than changing `K`.

## 4. Complete hypothesis family (`K = 117`)

Every cell below is one hypothesis. Empty cells stay in the family with `p=1`; `K` never shrinks.

| Axis | Cells | K |
| --- | --- | ---: |
| Effective cutoff hour | each integer `07` through `20` | 14 |
| Market | `atlanta`, `austin`, `chicago`, `dallas`, `denver`, `houston`, `los-angeles`, `miami`, `nyc`, `san-francisco`, `seattle`, `toronto` | 12 |
| Season stratum | `B`, `C` | 2 |
| Signed forecast distance, bands | missing; `<-2.5`; `[-2.5,-1.5)`; `[-1.5,-0.5)`; `[-0.5,0.5]`; `(0.5,1.5]`; `(1.5,2.5]`; `>2.5` | 8 |
| Repaired-model entropy | empirical Q1, Q2, Q3, Q4 | 4 |
| Market-implied entropy | empirical Q1, Q2, Q3, Q4 | 4 |
| Model-minus-market entropy | empirical Q1, Q2, Q3, Q4 | 4 |
| Forecast disagreement, C-equivalent | missing; `<=0.5`; `(0.5,1]`; `(1,2]`; `>2` | 5 |
| Forecast source count | missing/0; 1; 2; 3+ | 4 |
| Market band probability | `[0,.02)`; `[.02,.10)`; `[.10,.25)`; `[.25,.50)`; `[.50,.75)`; `[.75,.90)`; `[.90,.98)`; `[.98,1]` | 8 |
| Signed probability gap `q-m` | `<-.20`; `[-.20,-.05)`; `[-.05,.05]`; `(.05,.20]`; `>.20` | 5 |
| Hour group x coarse probability gap | four hour groups x `model_lower_10pp`, `within_10pp`, `model_higher_10pp` | 12 |
| Season x hour group | two strata x four hour groups | 8 |
| Coarse forecast distance x hour group | `near_abs_le_1`, `middle_abs_1_to_3`, `far_abs_gt_3` x four hour groups | 12 |
| Captured top-of-book spread | missing/invalid; `<=.002`; `(.002,.01]`; `(.01,.045]`; `>.045` | 5 |
| Captured liquidity, dollars | missing; `<25`; `[25,100)`; `[100,500)`; `>=500` | 5 |
| Captured cumulative volume, dollars | missing; `<10k`; `[10k,30k)`; `[30k,65k)`; `>=65k` | 5 |
| **Total** |  | **117** |

Hour groups are `open_07_08`, `primary_09_14`, `afternoon_15_17`, and
`lock_in_18_20`. The coarse signed-gap boundary treats exactly `-0.10` as lower, exactly `+0.10` as
higher, and the interior as agreement. Coarse forecast distance excludes missing rows.

## 5. Inference, multiplicity, power, and stability

Each hypothesis aggregates row count and loss sums by `(target_date, market_id)`. Inference uses
10,000 crossed pigeonhole replicates with seed `20260946`: date clusters and market clusters are
resampled independently and cell weights are their product. The interval is the two-sided percentile
95% interval. A market-specific cell has `M=1`, so the market resample is explicitly degenerate and
the result can establish date stability only.

The raw directional p-value for positive edge uses the crossed-bootstrap standard error and a
one-sided normal statistic. All 117 raw p-values receive Holm step-down family-wise adjustment at
alpha `0.05`. Both raw and adjusted values are reported. Observed-effect plug-in power and the
80%-power MDE are reported at raw alpha `0.05` and at conservative family-wide alpha
`0.05 / 117`; power uses the absolute observed edge and never licenses its direction.

A P0 skill candidate must satisfy all of:

1. positive point edge, crossed interval lower bound above zero, Holm-adjusted `p <= .05`, and
   family-wide observed-effect power at least `0.80`;
2. at least 20 date clusters, 100 snapshots, 500 band rows, and 1% of the frozen band population;
3. at least six markets unless the axis itself is the predeclared individual-market axis;
4. positive leave-one-date-out edge in at least 80% of omissions and, when `M > 1`, positive
   leave-one-market-out edge in at least 80% of omissions.

The report must include all 117 cells, their edge distribution, all raw winners, all adjusted
winners, and all failures. A positive but unsupported cell is not a candidate. A market cell cannot
be called fleet-stable.

A skill candidate becomes *quotable* only if at least 80% of its rows have a valid captured book,
at least 80% lie at a captured spread no wider than 4.5 cents, and contemporaneous per-side size
proves `rewardsMinSize` eligibility. The sealed tape has no per-side size field; absent an independent
pre-cutoff join, size evidence is `ABSENT`, never inferred from aggregate liquidity. This may leave a
statistical candidate non-quotable.

## 6. P1 break-even declaration

P1 is an analytic sensitivity bound, not a fitted flow model. For a binary band, define:

- `A`: probability-point adverse move on an informed fill (unmeasured);
- `f`: informed fraction of fills (unmeasured);
- `h`: realized spread capture per filled share, not displayed quote width;
- `e`: model probability edge that correctly anticipates and removes part of `A`;
- `r(p) = .25 x .05 x p x (1-p)`: optimistic maker-rebate value per executed share at price `p`;
- `L`: daily liquidity reward captured per quoted band;
- `Q`: shares resting on each of two sides; and `phi`: fraction of those shares filled per day.

The declared daily expected value is:

```text
EV(e) = 2 Q phi [h + r(p) - f max(A - e, 0)] + L
e_break_even = max(0, A - [h + r(p) + L/(2 Q phi)] / f)
Brier_break_even = 2 A e_break_even - e_break_even^2
```

The final expression is the expected binary-Brier advantage when the model's shift is aligned with
the true informed move. It puts P1 in P0's squared-probability units, but is deliberately labelled an
optimistic translation: a Brier advantage alone does not prove directional flow prediction.

The complete grid is the Cartesian product of:

- `A`: `.005`, `.01`, `.02`, `.045`, `.10`;
- `f`: `.10`, `.25`, `.50`, `.75`, `1.00`;
- `h`: `.001`, `.002`, `.005`, `.01`, `.0225`;
- `phi`: `.05`, `.25`, `.50`, `1.00`;
- price `p`: `.05`, `.10`, `.25`, `.50`, `.75`, `.90`, `.95`;
- `L`: `$0`, `$0.20`, `$1.00` per band-day; and
- `Q`: 20 and 50 shares per side.

This is 21,000 scenarios. `L=$0` is the trading-plus-rebate case; `$0.20` approximates full capture
of one fifth of the measured `$1/event/day` reward; `$1` is an intentionally generous upper bound.
With `L=0`, fill rate scales dollars and must not change the break-even edge. The report must say
plainly that `A` and `f` are unmeasured, report the full grid, and compare any P0 candidate with the
grid without turning the optimistic mapping into a P&L claim.

## 7. Frozen decision outcomes

- `NO_ADJUSTED_EDGE`: no cell meets the P0 skill-candidate rule.
- `EDGE_NOT_STABLE_OR_LARGE`: an adjusted winner fails support or omission stability.
- `EDGE_NOT_QUOTABLE`: a skill candidate lacks book, spread-window, or min-size evidence.
- `EDGE_BELOW_BREAK_EVEN_BOUND`: a skill candidate is below the declared P1 bound for the stated
  scenarios.
- `CANDIDATE_FOR_UNTOUCHED_CONFIRMATION`: a cell clears P0 and the available quoteability/economic
  screens. It remains a candidate only; this mission consumes no confirmation data.

No model is fit, no partition is added after outcomes, no gate is changed, and no result authorizes
promotion or trading.
