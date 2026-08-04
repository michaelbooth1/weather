# Workstation report — 2026-08-03: where does the improvement go?

## The number requested first

**The frozen raw-HGB correction survives the real serving pipeline at 18.32% of the served
incumbent-versus-market Brier gap, not 5.39%.** Its paired final-model Brier effect is `-0.003913`,
with a date-and-market clustered interval of `[-0.013567, +0.003133]`; the gap-closure interval is
`[-21.03%, 55.81%]`. The point effect retains 50.27% of the raw correction's absolute Brier
improvement, but the interval still crosses zero.

The requested 24.69% → 5.39% waterfall does not exist. The accepted `-08-24a` analysis fitted two
different out-of-fold targets: `raw_conditional_shift` was applied to HGB, while
`served_conditional_shift` was separately fitted and applied directly to the final served
distribution. Recomputing those two frozen headlines gives 24.6854% and 5.3870% exactly, but the
latter is not the former propagated through serving. Pushing the frozen raw correction through the
real pipeline produces:

```text
raw HGB 24.69% gap closure
  → post-live signals 27.96%
  → trusted floor 11.35%
  → plausible cap 18.21%
  → pre-calibration 18.21%
  → final served 18.32%
```

The top absorber is the trusted observed-high floor. It removes `0.004956` Brier of paired benefit,
`[+0.000415, +0.010836]`, or 63.68% of the raw point improvement at that boundary. **This is by
design and correct. The floor stays.** The valid upstream diagnostic—making the corrected HGB
floor-compatible before running the unchanged floor again—does not recover the loss: it yields
16.34% served gap closure, `[-24.89%, 55.50%]`, slightly worse than the unmodified correction.
There is no evidence for a cheap floor fix.

Among adjustable stages, removing the feature blend entirely gives the largest no-fit point bound:
20.33% served gap closure, `[-13.40%, 58.77%]`, only 2.01 percentage points above the real pipeline.
It also worsens absolute Brier for both the incumbent and corrected lanes, so it is not a valid
serving recommendation. Replacing the copied parent probability calibrator with identity gives
18.21%, `[-22.00%, 57.54%]`, effectively unchanged. An honest no-fit point envelope is therefore
**16.34% to 20.33%, with every interval crossing zero**. The propagated point effect is materially
larger than 5%, but it remains uncertain.

## Verdict

The claimed 78% downstream leak was mostly a comparison error. On a true same-input causal
waterfall, 49.73% of the raw absolute Brier improvement disappears by the final output, not 78%.
The disappearance is dominated by a legitimate physical floor, and a later plausible-cap stage
recovers part of it. Neither the blend nor calibration is a demonstrated defect on this population.

No first-retrain contract change is required. The already-built contract at `71d18318` explicitly
fits candidate-specific blocked-OOF HGB/blend and exact-distribution calibration, replaces each
market's probability-calibration artifact, and disables the stale market-bin transform. It does not
copy the old HGB calibrator. Preserve those clauses; do not regress them during integration. The
same contract's target-date-aligned prior and contiguous support are the right upstream direction,
but this experiment does not justify adding a hard pre-floor projection.

No fit, retrain, candidate, candidate score, weather/provider or production-network call,
reserved-date read, archive/artifact/prior or cache write, floor change, promotion, pointer,
serving, scheduler, capture, mirror, ACL, production-host, PR, merge, or master action occurred.

## Scope and causal contract

The topic branch is based exactly on `master @ 9a9376ef1ccaa3af15ed9da8538f2f061915e28f`.
The sole output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\where-improvement-goes-2026-09-05a`,
outside the mirror. `data/` remained read-only under its deny-write ACL.

The population is exactly July 22–26, effective cutoff 09–14: 12 markets, 60 market-days, 2,868
snapshots. The harness opened only each allowlisted local corpus folder's exact
`replay_inputs.jsonl`; it did not follow the historical manifest's UNC paths. Every selected
captured-input record passed its canonical persisted self-hash. July 27–31, August 1–5, and the
reserved August 6–November 3 window were not read, enumerated, evaluated, or substituted.

The no-fit intervention is exact:

1. Replay the allowlisted captured sources, target date, and build time through the declared-base
   model with the frozen per-market artifacts.
2. At the named post-smoothing `hgb_feature_model` boundary, reweight native buckets within each
   market band to reproduce the frozen uncorrected HGB probabilities exactly.
3. For the paired lane, change only that input to reproduce `-08-24a`'s frozen
   `raw_conditional_probs` exactly. Within-band native allocation stays fixed.
4. Run every actual downstream serving method unchanged, adding diagnostic snapshots only where
   the production instrumentation records an otherwise-unsnapshotted stage.
5. Score snapshot-first mean binary-band Brier. Negative corrected-minus-control delta is
   improvement. Gap closure divides the paired improvement by that stage's incumbent-minus-market
   gap. Survival divides each stage's absolute improvement by the raw-HGB improvement.
6. Use 2,000 deterministic crossed pigeonhole bootstrap replicates, independently resampling target
   dates and markets. This preserves both dependence dimensions requested by the handoff.

Maximum raw-HGB and incumbent-final replay mismatches were `3.33e-16` and `5.55e-16`. The pipeline
therefore reproduces both frozen endpoints to floating-point precision before applying the corrected
input.

## Full causal waterfall

Intervals below use the crossed date/market bootstrap. `Δ Brier` is corrected minus control;
negative improves. `Gap closed` is stage-specific. `Raw survival` is the point share of the raw
absolute Brier improvement still present.

| Stage | Δ Brier [95% interval] | Gap closed [95% interval] | Raw survival |
| --- | ---: | ---: | ---: |
| HGB feature model | `-0.007784` [`-0.022248`, `+0.001618`] | 24.69% [-7.41%, 54.68%] | 100.00% |
| Feature blend | `-0.007178` [`-0.019360`, `+0.000043`] | 24.96% [-0.25%, 52.23%] | 92.21% |
| Bucket-transition blend | `-0.007178` [`-0.019360`, `+0.000043`] | 24.96% [-0.25%, 52.23%] | 92.21% |
| Post-live signals | `-0.007369` [`-0.020152`, `+0.000438`] | 27.96% [-2.66%, 62.62%] | 94.67% |
| Trusted observed-high floor | `-0.002412` [`-0.012873`, `+0.005277`] | 11.35% [-33.29%, 52.20%] | 30.99% |
| Intraday tail | `-0.002412` [`-0.012873`, `+0.005277`] | 11.35% [-33.29%, 52.20%] | 30.99% |
| Plausible cap | `-0.004126` [`-0.014444`, `+0.003687`] | 18.21% [-22.00%, 57.51%] | 53.01% |
| Forecast pull | `-0.004126` [`-0.014444`, `+0.003687`] | 18.21% [-22.00%, 57.51%] | 53.01% |
| Ramp warm-tail dampening | `-0.004123` [`-0.014437`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.97% |
| Afternoon residual centering | `-0.004123` [`-0.014437`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.97% |
| Validated current-max floor | `-0.004123` [`-0.014437`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.97% |
| Settlement-lag adjustment | `-0.004125` [`-0.014437`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.99% |
| Current-observation floor | `-0.004124` [`-0.014433`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.98% |
| WU floor residual | `-0.004124` [`-0.014433`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.98% |
| Late-day continuation blend | `-0.004124` [`-0.014433`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.98% |
| High-has-stood lock-in | `-0.004124` [`-0.014433`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.98% |
| Expanded late-day lock-in | `-0.004124` [`-0.014433`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.98% |
| Standing-high partial lock-in | `-0.004124` [`-0.014433`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.98% |
| Late-day lock-in | `-0.004124` [`-0.014433`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.98% |
| Pre-calibration model | `-0.004124` [`-0.014433`, `+0.003691`] | 18.21% [-22.00%, 57.54%] | 52.98% |
| Overconfidence calibration | `-0.003913` [`-0.013567`, `+0.003133`] | 18.32% [-21.03%, 55.81%] | 50.27% |
| Current-max boundary guard | `-0.003913` [`-0.013567`, `+0.003133`] | 18.32% [-21.03%, 55.81%] | 50.27% |
| Final served model | `-0.003913` [`-0.013567`, `+0.003133`] | **18.32% [-21.03%, 55.81%]** | **50.27%** |

The raw point reproduces `-08-24a`, but its stricter crossed-cluster interval now crosses zero. The
older interval excluding zero resampled market-day clusters as exchangeable units; it did not
preserve the separate five-date and twelve-market dependence dimensions. With only five date
clusters, the wide interval is the honest one for this mission.

## Absorption and legitimacy

Positive absorption means a stage erased paired benefit. Negative absorption means it restored or
amplified benefit.

| Stage | Absorbed Brier [95% interval] | Raw point improvement absorbed | Classification |
| --- | ---: | ---: | --- |
| Feature blend | `+0.000606` [`-0.003626`, `+0.003590`] | 7.79% | **By design and correct on this population.** It improves absolute Brier for both lanes; full removal worsens both. Candidate-specific blend refitting remains appropriate. |
| Post-live signals | `-0.000191` [`-0.002376`, `+0.001643`] | -2.45% | Not an absorber; the stage modestly amplifies the correction. |
| Trusted observed-high floor | `+0.004956` [`+0.000415`, `+0.010836`] | **63.68%** | **By design and correct.** It helps the incumbent far more because both raw lanes still contain physically impossible cool mass. The upstream model must stop putting mass there; the floor must not move. |
| Plausible cap | `-0.001714` [`-0.004842`, `+0.000147`] | -22.02% | Not an absorber; it restores about one-third of the immediate floor loss at the point estimate. |
| Ramp warm-tail dampening | `+0.000003` [`-0.000002`, `+0.000013`] | 0.04% | **By design and correct; immaterial.** |
| Settlement-lag adjustment | `-0.000001` [`-0.000008`, `+0.000001`] | -0.02% | Not an absorber; immaterial. |
| Current-observation floor | `+0.000001` [`-0.000000`, `+0.000002`] | 0.01% | **By design and correct; immaterial.** |
| Overconfidence calibration | `+0.000211` [`-0.000616`, `+0.001136`] | 2.72% | **By design and correct on this evidence.** It improves absolute Brier for both lanes and its attenuation interval crosses zero. No calibration defect is demonstrated. |
| All other named stages | `0.000000` at displayed precision | 0.00% | No-op on this 09–14 feature-model population or no measurable paired absorption. |

No stage is classified “by design but now wrong,” and no defect is identified. The historical
clean-regime blend warning remains relevant to fitting a candidate-specific weight, but it does not
overcome the exact result here: removing the blend raises incumbent Brier from `0.070095` to
`0.075643` and corrected Brier from `0.066182` to `0.070173` at the final output.

## Top-stage and suspect counterfactuals

These diagnostics were declared as no-fit substitutions and were all reported regardless of score.
They are not candidates or serving recommendations.

| Diagnostic | Final base Brier | Final corrected Brier | Δ Brier | Served gap closed [95% interval] | Disposition |
| --- | ---: | ---: | ---: | ---: | --- |
| Real copied-parent pipeline | 0.070095 | **0.066182** | **-0.003913** | **18.32% [-21.03%, 55.81%]** | Causal answer |
| Corrected HGB made floor-compatible upstream; real floor retained | 0.070095 | 0.066605 | -0.003490 | 16.34% [-24.89%, 55.50%] | Does not recover the floor loss; a naive projection is worse |
| Feature blend set to identity for both lanes | 0.075643 | 0.070173 | -0.005470 | 20.33% [-13.40%, 58.77%] | Largest adjustable point effect, but worsens both absolute scores |
| Parent probability calibration set to identity for both lanes | 0.071381 | 0.067257 | -0.004124 | 18.21% [-22.00%, 57.54%] | Calibration is not the leak |

Plainly: the top absorber cannot be “corrected” downstream because it is the physical floor. The
permitted upstream version does not produce a larger effect under the simplest no-fit projection.
The top adjustable-stage number is 20.33%, and the calibration-specific range is approximately
18.21%–18.32%. Neither is a 4.5× multiplier, and every clustered interval includes zero.

## First-retrain contract

The handoff's calibration concern is already resolved in the held implementation it references.
The `71d18318` base-retrain report states that the lane:

- fits blocked-OOF HGB, candidate-specific blend, and exact-distribution calibration jointly;
- replaces all twelve HGB/LR/probability-calibration triples atomically;
- disables the old market-bin transform because candidate scoring is excluded; and
- does not reuse the old HGB calibrator.

Therefore this measurement does **not** require a new contract change. It reinforces three existing
requirements: preserve the physical floor, keep candidate-specific blend/calibration refits, and
score the candidate after the full serving pipeline rather than extrapolating a raw-HGB effect. If
the implementation is later changed to copy the parent's probability calibrator or fixed blend,
that would be a regression against the already-built contract.

## Evidence and verification

An independent verifier did not import the analysis harness. It recomputed every scenario-stage
point estimate and adjacent absorption from 263,856 score rows, independently reconciled the frozen
24.6854% and separately fitted 5.3870% headlines, checked the exact allowlisted date/hour inventory,
and passed 460 comparisons. Verification status is `PASS`.

Repository checks also passed: `weather.operations.agent_docs_audit` audited 18 agent files and 599
Markdown files, and `tests/operations/test_import_architecture.py` passed 21 tests.

The evidence-manifest SHA-256 is
`21cd462c3072e115f58c8e3801a232efc1f64f0e150f6e911260ba251f9a5dbb`.

| Evidence | SHA-256 |
| --- | --- |
| Declaration | `8af14b3a6aaa86c0540af1a60cf642fb2d65c19d9260868717b17cca9d8e7c14` |
| Top-absorber follow-up declaration | `46d11764d8348694113218341737ef9b49a279c63841f3517ca02bfb61021460` |
| Analysis harness | `cd5f44b3a6dfeba2a3f2ccd4d0adfbd33887f8a37b3899bc556bc49de7eb51ca` |
| Stage snapshot scores | `24b655fccc5c21afda5bbc317c485cf8217a47ad7058a325c09e47827501c19d` |
| Waterfall | `71ec24b4d9ff38fde667d39d3443981d2d9c201cc73415cf109d0a9081706cf0` |
| Absorption | `1f5a3822e8664fa13492e5a714556c29c5db42221bf61670b8e6363d7b26414b` |
| Summary | `8748bb6e3bd1522f451a7d4d5320bdc195d371171852e44f176af1259797087e` |
| Replay fidelity | `299610de65a597b71cce4e321ae8276dff6164d0e11569fc6291e88142b4057e` |
| Independent verifier | `17c367a861022911b61fee2dd4917ec840b1f10bcaa0c98936ddec6ef713113e` |
| Verification receipt | `2fb5ae5fbbbc579173f1f5407dbc641ec06e027e270f96622bbf3f6152437e3c` |

`-08-16a` remains queued for 2026-08-05 04:30 and retains priority. No production host,
mirror credential, release, pointer, serving, scheduler, capture, ACL, PR, merge, or master state
changed.
