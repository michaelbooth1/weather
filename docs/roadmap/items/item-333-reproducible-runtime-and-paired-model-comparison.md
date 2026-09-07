# 333. Reproducible Runtime And Paired Model Comparison [PARTIAL 2026-09-07 - INCUMBENT CONTROL PREPARED; VERIFICATION OPEN]

Goal: make a model comparison reproducible and capable of distinguishing an
improvement from replay drift, label mismatch and sampling noise.

Owner/package: `weather.model`, `weather.collection`, `weather.backtesting`,
`weather.reporting.validation`; one integration owner coordinates contracts.

Source: findings F3-F5 of the
[September 7 whole-system audit](../audits/post-reclaim-system-audit-2026-09-07.md),
[the established replay limitation](../../operations/REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md),
and [item 321](item-321-model-production-readiness-evidence-integrity-and-staged-release-program.md).
This item owns the bounded engineering repair; item 321 retains release and
promotion ownership. No new alpha allocation or candidate fit is authorized.

Why this matters: the current manually maintained model identity misses
serving dependencies and cannot restore unavailable runtime bytes. The replay
CLI's aggregate Brier PASS can coexist with failed fidelity. Packaged PIT
intervals resample dates but do not implement the paired crossed date-by-market
comparison required for model-versus-market claims.

## Work

- [x] Define separate claims: diagnostic current-code replay, same-environment
  paired candidate experiment, and actual served-runtime reproduction. Each
  output declares its supported claim and missing evidence.
- [x] Assess PR 7's loaded-process identity v0.3, deterministic BOM and
  release-binding implementation and its retained mutation controls. Record
  reusable components and exact residual gaps before coding.
- [ ] Reconcile the bounded reusable runtime foundation without reviving the
  separately refused collector or importing unrelated PIT/release work.
- [ ] Reuse immutable releases/CAS to preserve source, model artifacts,
  effective configuration and dependency closure once per loaded bundle.
  Bind process-loaded identities to captured inputs; do not hash changing
  working-tree files as a substitute or duplicate a bundle on every snapshot.
- [ ] Restore a new bounded forward sample in a fresh process and reproduce
  its full distribution and market-band probabilities under declared
  tolerances. Missing/mutated/unbound bytes must refuse proof. Measure storage
  cost and capture overhead before adoption.
- [ ] Require a faithful incumbent control before interpreting candidate
  deltas. Candidate identity may differ intentionally; both arms must share
  the pinned input/label population and environment. Fidelity failures,
  reconstructed exclusions and unsupported rows must affect the claim gate.
- [ ] Extend the existing packaged PIT evaluator with paired crossed
  date-by-market deltas, effective cluster counts, and candidate-specific
  power/MDE output. Preserve embargoed date folds and fold-local fitting.
- [ ] Validate inference separately from scoring determinism: predeclare null
  and coverage checks for the endpoint and actual cluster structure, including
  attainable acceptance and rejection controls. Retain sparse-tail coverage
  failures; do not copy historical quantiles/MDE floors onto a changed panel.
- [ ] Report early-hour and severe-tail behavior and the distribution of
  per-row replay error. An acceptable mean must not hide concentrated errors.
- [ ] Inject source, artifact, corpus, label, regime, cutoff and inclusion
  mutations; prove they cannot produce a qualified comparison PASS.

## Acceptance

Acceptance: a retained manifest can reproduce both arms in a fresh process; a copied
incumbent produces the declared zero control; deliberate mutations fail the
appropriate proof. A model-versus-market result reports paired uncertainty
with the governing crossed clusters, native units, cutoff and label provenance.
The declared null/coverage controls must support the interval's claimed use;
a deterministic clone alone does not prove inference validity. Insufficient
power produces an explicit inconclusive result. The CLI cannot
conflate an aggregate regression check with serving fidelity or improvement.

Dependencies: the usable-evidence census in
[item 331](item-331-post-reclaim-model-economics-and-research-plan.md) and signed
band correctness in [item 332](item-332-signed-native-temperature-band-correctness.md).
Actual served-runtime claims additionally require the new forward bundle proof;
honest same-environment diagnostic comparisons can begin sooner.

Falsification and stops: do not resume exhausted historical Git-blob recovery.
If an existing immutable bundle already reproduces the selected runtime,
demonstrate it and implement only the missing bindings. Stop candidate outcome
interpretation when fidelity, labels, support or power are inadequate. Preserve
the trusted observed floor; never alter a gate merely to pass a candidate.

Estimated effort: first assess the reusable PR 7 implementation; provisionally
allow two to four engineering days for forward bundle reproduction
and two to three for the comparison extension, with some overlap. Forward
evidence elapsed time is unknown. Heavy work runs on the admitted workstation;
capture changes use separate guarded adoption and measured resource budgets.

## September 7 bounded source preparation

The [incumbent-control contract](../../operations/replay-incumbent-control.md)
now separates the ordinary diagnostic Brier gate from an explicitly requested
numerical control. It requires the full nonempty pinned snapshot population,
complete replay/tape hash maps, usable pinned label values, unique raw records
and exact declared identities. Every distribution must have valid coordinates
and probability mass, and every row must meet the existing L1 tolerance.
A low mean cannot hide one bad row. Continuous Fahrenheit coordinates are
compared without integer collapse or renormalization.

Requested controls refuse missing/mutated support, reconstruction, changed or
legacy identities and invalid distributions. Missing label pins cannot fall
back to mutable daily summaries. The numerical check does not qualify the
label's settlement authority. Failed controls cannot overwrite a saved baseline;
save and comparison modes are mutually exclusive. The report and fidelity CSV
retain per-snapshot errors and population exclusions. Intentionally changed
candidate identities remain valid diagnostic inputs, with the weaker claim
visible in the CLI, report and baseline.

Source `4af51a1641878569d2acb115398a833739388e02`, merged into the local
preparation branch at `ffa25125fe89e8a46fcb3c2f8d808cd480e8be54`, and its
synthetic fixtures have undergone independent static review. After the owner's
specific transfer/publication approval, the admitted workstation focused run at
combined source `88bacc6a0bd0e163d25b2bd7e6cf894c03637dd3` passed 535 tests and
20 subtests, including the replay and incumbent-control fixtures. The exact
receipt and wider file scope are recorded in [item 331](item-331-post-reclaim-model-economics-and-research-plan.md#september-7-preparation-handback).
The wider Windows suite and its path-failure diagnosis are recorded there;
compilation passed, and no full-suite PASS is claimed. No historical tape, settlement
outcome, model artifact or candidate fit was consumed by this slice.

### Existing runtime foundation disposition

The assessed current PR 7 source is
`2e20e59aae08e7367dc79e1b8102c0551e7f6904`, a 55-file branch. Its original
small identity v0.2 proposal is superseded. Reusable components include the
loaded-process identity v0.3, deterministic model BOM, loaded source-binding
marker, release binding and mutation controls. The collector's separate
source-contract NO-GO does not invalidate those components.

A wholesale merge would also import broader PIT/release work and conflicting
roadmap ownership. Do not treat the old three-file patch as the current
implementation or silently import the full branch. Forward-adapt only the
reviewed runtime components under this item, preserving their provenance and
current capture/release contracts. They are assessed, not integrated here.

Remaining acceptance work: bind complete loaded source/artifact/config/
dependency bytes to immutable forward inputs; restore a bounded sample in a
fresh process and reproduce distributions and served bands; measure capture
and storage costs; implement paired crossed date-by-market inference and
candidate-specific support/power; calibrate null, coverage and attainable
decision controls. The numerical incumbent control alone completes none of
those broader proofs and supports no model-improvement claim.
