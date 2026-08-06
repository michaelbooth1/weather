# Workstation report 2026-08-03 — can we even detect the win?

## Reservation recommendation

**No: 2026-08-06 through 2026-08-19 is not sufficient. If a formally powered
single confirmation remains mandatory, reserve 490 additional target dates
now: 2026-08-20 through 2027-12-22, for 504 dates total.**

That is the point-estimate N for 80% power at the optimistic top of the honest
served-effect range. It contains no variance-estimation buffer. It is also the
plain answer the project needs: a greater-than-16-month untouched confirmation
is not a realistic single-candidate test. At the 2.5% gap-closure midpoint the
same endpoint needs 2,337 dates, through 2032-12-28. If the true effect is zero,
no finite reservation can detect a win.

The current 14 dates should therefore never be described as a powered
confirmation. If the owner does not reserve the full 490-date extension, keep
the existing 14 dates clean for directional evidence and explicitly downgrade
the future claim rather than relaxing the test after seeing it.

## Expected served-level effect

The honest planning range is **0 to 5.39% of the served incumbent-versus-market
Brier gap**, or `0` to `0.001151` absolute fleet Brier on the measured
09:00–14:00 population.

This range is deliberately much smaller than the upstream diagnostic:

- the raw conditional correction closed 24.69% of the raw HGB-market gap,
  `0.007784` absolute, with its interval excluding zero;
- the same out-of-fold correction closed only 5.39% of the served gap,
  `0.001151`, with candidate-minus-incumbent interval
  `[-0.007011, +0.004711]` crossing zero and only three of five dates better;
- the severe-tail diagnostic reduced fixed-tail SSE 25.53% and positive excess
  30.06%, improving all five dates, but it addresses only the incumbent-frozen
  tail; and
- the forecast lookahead accounts for about `0.070 C-equivalent`, 5.8% of the
  `1.2131 C-equivalent` raw centre displacement, and its repair is cool-signed.

The retrain directly targets stale prior and contiguous class support, so zero
through the measured 5.39% served closure is more credible than carrying the
24.69% raw result through downstream floor, blend, cap, and calibration stages.
The range includes zero because the observed served interval does.

## Detectable effect and required N

Every source row was reduced market-day first. Fleet variance is two-way
clustered by target date and market, converted to a fleet-date-equivalent
standard deviation, with test degrees of freedom capped by the 12-market
dimension. Toronto uses one Toronto market-day per date. Snapshot and band-row
counts never enter N.

The one-sided design uses alpha `0.05` and power `0.80`.

| Endpoint | Population | 14-date MDE | MDE as baseline share | N at upper effect | N at midpoint |
| --- | --- | ---: | ---: | ---: | ---: |
| Pooled all-hour Brier | Fleet | 0.002236 | 10.47% | 53 | 246 |
| Pooled all-hour Brier | Toronto | 0.009875 | 88.02% | 3,350 | 15,550 |
| **09:00–14:00 Brier** | **Fleet** | **0.006899** | **32.30%** | **504** | **2,337** |
| 09:00–14:00 Brier | Toronto | 0.009875 | 88.02% | 3,350 | 15,550 |
| Frozen severe-tail SSE | Fleet | 0.045887 | 9.59% | 4 | 9 |
| Frozen severe-tail SSE | Toronto | 0.247965 | 58.94% | 69 | 269 |

The pooled all-hour fleet variance is only a three-date proxy from an older
forward-chained gated-candidate OOF result, not a measured effect of this
retrain. It cannot displace the declared early-day objective. Toronto is worse:
the all-hour gate copied Toronto exactly, so the permitted Toronto 09:00–14:00
variance was used rather than treating a structural zero as perfect precision.

Fleet evidence is what the retrain will actually produce. The candidate-safe
base-retrain step is all-market and fleet-atomic. Toronto-only is a useful
sentinel but cannot be the efficacy test; its conditional diagnostic worsened
on every one of the five permitted date point estimates, and its 14-date MDE is
88% of Toronto's entire served-market gap.

The fleet severe tail is easily powered if the 25.53% diagnostic effect
transfers. It must remain secondary: the cited score population has only 4.26%
of rows carrying 60.2% of loss, membership is incumbent-frozen, Toronto is
unstable, and a tail win does not establish pooled proper-score improvement.

## The catastrophic-slice gate is a lottery

The current rule blocks if any one of 53–54 protected-slice point estimates
regresses by more than the pooled point improvement. It makes no sampling-error
or familywise-error allowance.

A deterministic 200,000-repetition simulation preserved each protected
dimension as a partition, shared the whole-date shock across slices, scaled
slice noise by published support, and calibrated it to both the lower all-hour
and primary two-way-cluster variance estimates. Under a true effect that is
uniformly better by the optimistic `0.001151`:

- the 54-slice rule falsely rejects **99.885% to 99.9905%** of good candidates;
- deleting any one slice to make 53 leaves the rate at **99.838% to 99.9905%**;
- capture hour alone creates a 99.30% to 99.93% false-rejection chance; and
- market alone creates an 87.06% to 97.06% chance.

This is unacceptable. The earlier 19-of-54 and 3-of-53 failures cannot be
interpreted as nineteen or three proven broken regimes under this rule.

Replace the point bar with a pre-registered **one-sided two-way-cluster max-T
harm-evidence gate**. For each frozen slice, test whether candidate-minus-
incumbent Brier is greater than the pooled-improvement margin. Apply multiway
wild-cluster weights over whole target dates and markets, retain the complete
slice vector, and use the maximum standardized statistic to set one 5%
familywise critical value. Block only when the simultaneous lower confidence
bound proves harm beyond the margin.

The simulation calibrates boundary familywise error to 5.00%; for a uniformly
better candidate its false-rejection rate is 0.79% to 2.77%. Insufficient slice
date support becomes `NOT_EVALUABLE`, never a pass. It requires more evidence
or regime quarantine, not an automatic point-estimate block. Probability mass,
trusted floor, parity, release binding, newly-severe, and every other
deterministic safety gate remain conjunctive and unchanged.

## Pre-registered primary endpoint

Use exactly one efficacy endpoint:

> **Fleet 09:00–14:00 paired daily-first Brier difference.** For every
> countable reserved target date, average snapshot-first 11-band Brier within
> each market-day at effective cutoffs 09:00–14:00, give each of the 12
> registered market-days equal weight, and retain candidate-minus-incumbent
> fleet-date difference as the observation. Test the mean below zero at
> one-sided alpha 0.05 with two-way date/market cluster-robust inference and
> degrees of freedom capped by the market dimension. Use the complete frozen
> reservation with no interim look or endpoint switch.

Pooled all-hour Brier and the incumbent-frozen severe tail remain secondary
safety/diagnostic endpoints. A win still requires all corrected slice and
unchanged deterministic gates to pass. This prevents choosing pooled, morning,
or tail only after discovering which one looks best.

## Evidence boundary and limitations

The analysis consumed published measurements plus aggregate market-day/date
reductions of POST-regime regenerated outputs from the permitted July 22–26
development window. It did not open an underlying row, filename inventory, or
substitute from July 27–31, August 1–3, or August 6–19. The published 19-of-54,
3-of-53, and slice-support counts are declared inputs, not newly recomputed
reserved-window results. No model or candidate was fit, retrained, scored, or
created.

Only three all-hour and five primary/tail source dates exist. The two-way
variance is therefore uncertain; 504 is a point estimate and is more likely
optimistic than conservative. This does not weaken the conclusion that 14 is
underpowered: its fleet-primary MDE is six times the optimistic expected
absolute effect and 32.30% of the whole served gap.

The sole generated run root is:

`C:\Users\Michael\Documents\github\weather\scratch\runs\detect-win-power-2026-09-04a`

| Evidence | SHA-256 |
| --- | --- |
| Aggregate input file | `68c47ccae21d7b954e67320221e422f22463187b4b45a01e98ff53eff15f77ca` |
| Canonical aggregate input | `8c8bf2489a087ce0928818672952754aaf8aff391885b17ce66fb5b4e54e550b` |
| Self-hashed report payload | `308c8bf0cde89418e7580a9c929b725539daecd791c1abca53088d18a8fa532e` |
| JSON file | `5a6418273fd17f6c59c78665218a7f91fecf52ba130578e18f897eed8da37c67` |
| Markdown file | `5e61a951ebbd361231f7c9420769e834ca203c2875a0004e05d847dccafde208` |

The `data/` ACL retained explicit non-inherited deny entries for write/delete
for both the operator and `CodexSandboxOffline`. All generated output stayed
under the declared run root outside `data/`. No network, provider, archive,
artifact, sidecar, prior, cache, fit, retrain, candidate, score run, promotion,
pointer, serving, scheduler, capture, mirror, ACL, production-host, credential,
PR, merge, or master action occurred.

## Implementation and verification

`weather.reporting.scorecards.detectable_win_power` is a standalone,
aggregate-only CLI. It validates the three endpoint contracts and protected
slice partitions, computes exact one-sided noncentral-t power, applies the
two-way-cluster variance/market-df correction, simulates the current and max-T
slice gates, binds the input/report hashes, and refuses output beneath `data/`.

The recorded `runtime_identity.source_scope_files` closures give the exact
roll disposition. The new scorecard module is absent from the snapshot, CLOB,
observation-trigger, and CLOB-enrichment closures. The changed
`src/weather/schema_registry_recent_data.py` is present in all four and is
therefore roll-sensitive if merged. No process was restarted or re-adopted.

Focused verification:

```text
python -m pytest tests/reporting/test_detectable_win_power.py -q
11 passed

python -m pytest tests/reporting \
  tests/operations/test_import_architecture.py -q
894 passed, 1 skipped, 23 subtests passed

python -m weather.schema_registry audit --strict
PASS (0 unregistered schema versions)

python -m compileall -q app src tests
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 597 Markdown files)
```

The repository-wide suite reached **3,295 passed, 4 skipped, and 820 subtests
passed**. Its 13 failures are the existing Windows `MAX_PATH` limitation in
`tests/operations/test_experiment_executor.py`: deeply nested isolated
candidate paths exceed the host limit before repository behavior executes,
even with the short normal temp root used here. The process-scoped PowerShell
bypass cleared the separate script-policy group. No power-design, reporting,
schema, or architecture test failed.
