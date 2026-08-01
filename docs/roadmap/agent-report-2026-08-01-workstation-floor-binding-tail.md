# Workstation floor-binding severe-tail diagnosis — 2026-08-01

## Verdict

**The hard floor binds materially where the model loses, but the floor is not
the defect.** It removed more than 1% of the pre-floor mass on 6,895 / 9,032
severe rows (76.34%) and 4,447 / 6,125 severe snapshots (72.60%). Those rows
carry 73.80% of the daily-weighted severe positive excess and 79.61% of the
accepted strict centre-oracle reduction. However, material binding is almost
equally common in the complete replay (72.41% of snapshots): severe snapshots
are enriched by only 0.20 percentage points. Binding is ubiquitous on this
path, not a selector that by itself explains entry into the tail.

The direct intervention points the same way. On the severe rows, applying the
floor improved 4,771 selected-band Brier terms, worsened 4,199, and left 62
unchanged. Its net daily-weighted selected-row Brier change was **-0.04957**;
negative is an improvement. Across the 6,077 floor-active severe snapshots,
the mean total-distribution Brier change was **-0.07260**. The trusted floor
therefore remains correct and useful.

The loss that survives is an **above-floor conditional-distribution error**.
Among the 6,895 materially bound severe rows, no selected severe band and no
settled winner lay below the floor. Both centre and scale were materially wrong
on 4,730 rows (68.60%), contributing 69.83% of this subset's severe excess;
centre-only and scale-only residuals contributed another 11.10% and 14.84%.
The post-floor model put its mode on the settled band only 22.64% of the time,
versus 78.22% for the market, and 54.40% of rows had a wrong model mode at the
floor band or the band immediately above it.

**A floor-aware HGB retrain is worth specifying, but a generic penalty on mass
below the floor is not.** The strict mechanism-linked subset—material floor
binding plus a pre-floor model centre cooler than the market—contains 59.56%
of the accepted 74.97% centre ceiling. That is equivalent to at most **44.65
percentage points of the full severe-tail baseline** under hindsight-perfect
centre replacement. This is the defensible addressable upper attribution for
an HGB-coolness fix; an achievable retrain result must be lower and separately
measured. The specification should preserve the hard-floor invariant and test
whether training can improve the joint centre, scale, and near-floor modal
allocation conditional on information available at effective time.

## Scope and exact reproduction

| Field | Value |
| :--- | :--- |
| Source | exact `origin/master` `d352bfd1cba8824d97ab5ee6efdb02a7d6f57d64` |
| Topic branch | `codex/workstation-floor-binding-tail-2026-08-07a` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\floor-binding-tail-2026-08-07a` |
| Declaration | `2026-08-01T23:07:50.5811744Z`, before any result was inspected |
| Evidence window | accepted July 22–30 corpus and replay |
| Scale | 108 replay entries; 19,265 snapshots; 9,032 severe rows in 6,125 snapshots |
| Active model route | HGB on 19,265 / 19,265 snapshots |
| Final trace versus accepted replay | maximum absolute probability mismatch `0.0`; centre mismatch `0.0` |
| Accepted severe universe reproduction | maximum excess mismatch `0.0` |
| Accepted centre oracle reproduction | decision mismatches `0`; baseline and forced-positive mismatches `0.0` |
| Reserved forward window | 2026-08-06 through 2026-08-19; **not enumerated, read, or evaluated** |

The analysis reused the accepted pinned corpus, replay rows, severe-row table,
and oracle decisions. It refit nothing and created no candidate or transform.
The accepted replay-row SHA-256 was
`bc1d4e80d65c98274be6d976ead97a391467124304fba14081e47a11aee5b2e8`;
the accepted severe-row SHA-256 was
`5a6a4bfed436619d1dc9887830bf8bdc0d9647be5efa14af649f38afe8b60c16`;
and the accepted oracle-decision SHA-256 was
`06e4b83fe15d162ceff24239406b52ae961a408d1f4ae067d3d12bf2db04aac7`.
No tuning decision was taken from July 27–30.

The retrace retained the distribution immediately before and after the trusted
observed-high floor, after the plausible-high cap, and at the final served
output. `removed mass` below is the normalized pre-floor probability strictly
below the floor-containing market band. `material` was frozen as greater than
1% before results were inspected. Centre and scale mismatches use the frozen
absolute 0.5-band thresholds and compare the post-floor model with the market.

## Severe-tail partition by floor activity

There were no rows in the numerical-active bucket (`0 < removed mass <=
1e-6`). Positive `net floor Δ Brier` means the floor worsened the selected
row; negative means it improved it.

| Floor state / removed mass | Severe rows | Row share | Snapshots | Tail contribution | Tail share | Mean removed mass | Mean centre shift | Centre-ceiling share | Net floor Δ Brier |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| No floor | 62 | 0.69% | 48 | 0.01451 | 0.84% | 0.00% | 0.000 bands | 0.66% | 0.00000 |
| `>1e-6` to 1% | 2,075 | 22.97% | 1,630 | 0.43579 | 25.36% | 0.42% | +0.019 bands | 19.73% | +0.00065 |
| `>1%` to 5% | 2,009 | 22.24% | 1,514 | 0.36119 | 21.02% | 2.46% | +0.073 bands | 19.32% | +0.00112 |
| `>5%` to 20% | 1,620 | 17.94% | 1,074 | 0.28001 | 16.29% | 10.55% | +0.273 bands | 17.51% | +0.00757 |
| `>20%` | 3,266 | 36.16% | 1,859 | 0.62722 | 36.49% | 69.30% | +2.384 bands | 42.78% | **-0.05891** |
| **All material (`>1%`)** | **6,895** | **76.34%** | **4,447** | **1.26842** | **73.80%** | **36.02%** | **+1.214 bands** | **79.61%** | — |

For materially bound rows, median removed mass was 15.52% and the 90th
percentile was 91.85%; the median floor-induced centre shift was +0.404 bands
and the 90th percentile was +3.756 bands. This is not merely numerical
truncation. The `>20%` bucket alone holds 42.78% of the accepted centre ceiling,
yet its negative net floor delta shows that the strongest intervention is also
the one delivering the clearest aggregate correction.

### Binding is not enriched in the tail

| Condition | Full replay snapshots | Full rate | Severe snapshots | Severe rate | Severe minus full |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Any active floor | 19,162 / 19,265 | 99.47% | 6,077 / 6,125 | 99.22% | -0.25 pp |
| Material binding (`>1%`) | 13,949 / 19,265 | 72.41% | 4,447 / 6,125 | 72.60% | +0.20 pp |
| Material + pre-floor model cooler than market | 9,486 / 19,265 | 49.24% | 3,204 / 6,125 | 52.31% | +3.07 pp |

The last row is only mildly enriched (rate ratio 1.062). Its importance comes
from the amount of accepted tail and centre ceiling inside it, not from a sharp
tail-selection effect.

## What remains above the floor

Every selected and winner band in the materially bound subset was at or above
the floor-containing band. The settled band was the floor band on 3,506 rows,
one band above on 705, and at least two bands above on 2,684. The selected
severe band was the floor band on 3,097 rows, one above on 1,887, and at least
two above on 1,911. The problem is therefore not a scored impossible band
below a valid floor.

| Post-floor residual at frozen 0.5-band thresholds | Rows | Row share | Daily-weighted severe excess | Contribution share |
| :--- | ---: | ---: | ---: | ---: |
| Centre and scale | 4,730 | 68.60% | 0.88574 | 69.83% |
| Centre only | 689 | 9.99% | 0.14075 | 11.10% |
| Scale only | 1,203 | 17.45% | 0.18825 | 14.84% |
| Neither | 273 | 3.96% | 0.05368 | 4.23% |

The largest signed geometry was `wide + warm`: 2,846 rows and 43.27% of the
material subset's contribution, with mean post-floor centre excess +1.224
bands and width excess +2.228 effective bands. `wide + cool` followed at 1,454
rows and 18.74% of contribution. This mixed sign is why “remove less cool mass”
is not a sufficient training target: after conditioning on the valid floor,
the model often remains too wide and can be either too warm or too cool.

The near-floor modal allocation is particularly weak. The post-floor model
mode was at the floor or one band above on 5,256 / 6,895 rows (76.23%), but was
wrong there on 3,751 rows (54.40% of all materially bound rows). That is a
conditional shape error after the correctness constraint has already done its
job.

## Market centre below the floor: the uncomfortable case

There were 459 severe rows in 295 snapshots where the normalized market centre
sat below the floor-containing band centre and the market beat the model on the
selected row. The validity check is unambiguous:

- the floor exceeded settlement on **0 / 459 rows and 0 / 295 snapshots**;
- the settled winner was the floor-containing band on all 459 rows;
- the floor bound materially on all 459 rows;
- the market put more probability than the final model on the settled band on
  455 / 459 rows; and
- on the full snapshot Brier, rather than only the selected row, the market won
  291 / 295 times.

The market was not broadly diffuse in the ordinary cases. Its settled-band
probability had mean 0.9827 and median 0.9995, versus model mean 0.4308 and
median 0.4237. Its probability strictly below the floor band had median 0.35%
and 90th percentile 0.40%; one rare case raised the mean to 1.75%. In other
words, the market usually paid a tiny impossible lower tail while concentrating
almost all remaining mass on the valid settled floor band. The model respected
the same floor but stayed too diffuse and/or warm above it. This is market
behaviour paying off, **not an invalid physical floor**.

## How much of the 74.97% centre ceiling is HGB-linked?

| Attribution set | Rows | Snapshots | Strict centre-oracle reduction | Share of accepted centre ceiling | Equivalent share of full severe baseline |
| :--- | ---: | ---: | ---: | ---: | ---: |
| All severe rows | 9,032 | 6,125 | 1.28854 | 100.00% | 74.97% |
| Any active floor, optimistic | 8,970 | 6,077 | 1.28005 | 99.34% | 74.48% |
| Material binding, either centre direction | 6,895 | 4,447 | 1.02576 | 79.61% | 59.68% |
| **Material binding + pre-floor model cooler than market** | **5,059** | **3,204** | **0.76742** | **59.56%** | **44.65%** |
| No floor | 62 | 48 | 0.00849 | 0.66% | 0.49% |

The optimistic floor-active figure is not a credible HGB estimate because the
floor is nearly universal and includes rows with the wrong causal direction.
The material-only figure still mixes cool and warm pre-floor disagreements.
The strict row requires both pieces of the traced mechanism: material mass was
truncated and the pre-floor model was cooler than the market. Its **59.56% of
the centre ceiling / 44.65 percentage points of the severe baseline** is the
appropriate upper attribution.

It is not a forecast that a retrain will realize 44.65 points. The number still
uses the accepted hindsight centre oracle inside a causally screened subset;
it does not model attainable features, preserve every calibration objective,
or account for retrain tradeoffs outside the severe tail. It establishes that
the mechanism is large enough to justify writing a retrain specification. The
specification must then earn an achievable estimate using leakage-safe inputs,
fresh train/serve parity, captured-input replay, full-distribution scoring, and
explicit floor-invariant checks. No retrain or candidate was produced here.

## Evidence and guardrails

The independent validator returned `PASS`. It rejoined the trace and accepted
severe/oracle tables, reproduced all 9,032 rows and the 1.718715 severe-positive
baseline, reproduced the 1.288544 centre ceiling, and independently asserted
zero selected or winner bands below the floor in the material subset and zero
floor-above-settlement snapshots in the complete trace.

Key immutable outputs under the declared run root:

| File | SHA-256 |
| :--- | :--- |
| `analysis-declaration.md` | `935180535dc9aa85aed5c1cebeece294dffe1d2e208309e71d1459c441124b75` |
| `trace_floor_binding.py` | `500c08ccdd014ee08231a8b8cde0db94bb82147e441351a74dec723ebf54075c` |
| `full-snapshot-floor-trace.csv` | `305435e5a83dad7aabec50ac8dd6acc0a524b6b5b7b90df4dddf257d1d9a6c9b` |
| `analyze_floor_binding_tail.py` | `4e20860043fcd54422275b5deffea9be2499bcf8a4b53938c6cac9a3301534a7` |
| `floor-binding-tail-analysis.json` | `0b5dc8e507fd6107da632848ce685d1476609fef913842c2aca168d3cc4da51e` |
| `validate_floor_binding_tail.py` | `16cd5fe1e0f56075c5e8ed1239839ccd325d228baca295bd0b348045daebf300` |
| `validation-summary.json` | `cc52099dbacd9320f75bd48356cd28bc0a86ff1d3af14f6b370820fdc07f7712` |

All analysis outputs stayed under the one declared run root outside the replay
mirror. `data/` was read-only; no August 6–19 path was enumerated; and there was
no config, model, artifact, serving, promotion, pointer, scheduler, capture,
mirror, ACL, or credential change. This handback is documentation-only and
therefore roll-free. No PR, merge, or master push was made.
