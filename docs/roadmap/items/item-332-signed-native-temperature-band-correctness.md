# 332. Signed Native Temperature Band Correctness [PARTIAL 2026-09-07 - REPAIRED AND WORKSTATION-VERIFIED; ADOPTION OPEN]

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

- [x] Reproduce negative exact/range/tail parsing and numeric-zero replay failures
  with focused synthetic fixtures on the workstation.
- [x] Reconcile PR 28's canonical sign-aware parser and consumer changes;
  extend only demonstrated gaps instead of building another parser. Distinguish range
  separators from minus signs, support the actual venue grammar, validate
  ordering/units, and fail explicitly on unsupported or ambiguous labels.
- [x] Use explicit missing-value checks for recorded endpoints. Preserve valid
  zero and give explicit typed endpoints precedence over legacy label recovery.
- [x] Verify serving projection, recorded bins, settlement scoring and replay
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

## September 7 source and verification evidence

The isolated preparation branch reconciles PR 28 at
`0a0804f0721e1e0942cd8d302b5d2b01785491e8` with the current portable parent.
New repair `af2f54302cccb37f8f65a5ff08c517d630394620`, merged at
`81c8615fefdfcf4c55a060573641de400b314a32`, uses the existing
`temperature_band_key` in replay and persisted snapshot-bin projection.
It preserves numeric zero, signed legacy upper endpoints, explicit endpoint
precedence and supported native kind aliases. Invalid replay bands remain
unscored; invalid snapshot bands fail before sidecar publication. Settlement-
distance grouping now preserves zero as a real lower endpoint.

Independent static review passed. On the exact admitted non-capture
workstation, eight focused files passed **200 tests plus 68 subtests** in
8.34 seconds with 12 existing feature-imputer warnings. Coverage includes
signed/zero/positive C/F bands, both tails, crossing-zero ranges, native and
continuous probabilities, JSON/CSV forms and invalid inputs. The retained
JUnit receipt is `scratch/post-reclaim-p2-tests.xml`, SHA-256
`B21427D25E1A71BCC41FE559DC1C5D79AA6C638141F9778D92EC8F98C9B51E7C`.

The same new targeted fixture was run against unchanged PR 28 source in a
separate control checkout: **5 expected failures, 17 passes, 63 deselections**.
Failures exposed numeric `bin_value_c=0` and four legacy negative-upper cases;
positive partition controls passed. Its JUnit receipt is
`scratch/post-reclaim-p2-old-source-controls.xml`, SHA-256
`EAD0AD186104CA647C387BC0BE2E9BD5E5F0F2845F42DA420901C643AD922C44`.
These ignored receipts are retained local evidence, not clean-checkout inputs.

Remaining: bounded affected-input census, final combined-source verification,
canonical roll verdict and guarded adoption/recovery. No historical tape,
settlement evidence or model release was changed. This source correctness
result does not measure historical affected volume or forecast improvement.
