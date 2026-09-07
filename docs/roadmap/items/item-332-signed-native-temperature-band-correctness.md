# 332. Signed Native Temperature Band Correctness [OPEN 2026-09-07 - SOURCE DEFECTS IDENTIFIED]

Goal: make serving, persisted band identity, settlement and replay agree for
negative and zero temperatures in each market's native unit.

Owner/package: `weather.model`, `weather.backtesting`; coordinate shared
parsing with `weather.units` and the market registry owner.

Source: the [September 7 whole-system audit](../audits/post-reclaim-system-audit-2026-09-07.md),
findings F1/F2, at production source `6714b77d8`. PR 28 commit `016e1c92c`
already implements the shared `weather.units.parse_temperature_band` and its
serving/settlement/market consumers; reconcile and verify that repair first.
The remaining new delta is numeric-zero and legacy-endpoint handling in replay,
cross-consumer coverage and a later bounded impact census. This is a bounded successor
to [item 177](item-177-core-model-validation-and-serving-skew-repair.md), not a
reopening of its previously accepted work.

Why this matters: unsigned label parsing changes negative settlement bands;
truthiness fallback drops valid numeric zero in replay. Both can change the
meaning of a probability without changing the model itself. Historical affected
volume has not been measured; no forecast improvement is claimed.

## Work

- [ ] Reproduce negative exact/range/tail parsing and numeric-zero replay failures
  with focused synthetic fixtures on the workstation.
- [ ] Reconcile PR 28's canonical sign-aware parser and consumer changes;
  extend only demonstrated gaps instead of building another parser. Distinguish range
  separators from minus signs, support the actual venue grammar, validate
  ordering/units, and fail explicitly on unsupported or ambiguous labels.
- [ ] Use explicit missing-value checks for recorded endpoints. Preserve valid
  zero and give explicit typed endpoints precedence over legacy label recovery.
- [ ] Verify serving projection, recorded bins, settlement scoring and replay
  use the same interpretation. Include negative-only, crossing-zero and positive
  C/F ranges, exact values and both tails; conserve distribution/band mass.
- [ ] Export a bounded affected-input manifest before any historical repair.
  Preserve canonical tapes; any corrected projection needs separate provenance.
- [ ] Independently review and run focused owner tests, then obtain the
  canonical roll verdict and controlled adoption evidence for the exact tip.

## Acceptance

Acceptance: the negative controls fail before repair and pass afterward. Zero, signed
endpoints and legacy recovery agree across all consumers, with unchanged
positive-band behavior and native units. Unsupported labels cannot silently
become another band. No evidence is rewritten and no release is promoted by
this item. Record source/test/adoption evidence separately.

Falsification: if a reported path is unreachable for supported inputs, prove
that contract with its callers and narrow the repair. Do not add a new parser
merely to duplicate a correct canonical one.

Estimated effort: half to one engineering day for the remaining replay repair and focused
verification; impact census and production adoption depend on admission.
This work can proceed independently of successful storage reclaim on the
separate admitted workstation.
