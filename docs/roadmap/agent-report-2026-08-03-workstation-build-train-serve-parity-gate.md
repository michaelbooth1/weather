# Agent report 2026-08-03 — build the train/serve parity gate

## Previously unknown finding

**The station serving path drops two additional schema features beyond the nine
known empty active base features: `wind_gust_kmh` and
`wind_shift_3h_degrees`.** The independent training builder populated both from
the captured observation sequence while the serving builder returned both
missing, in all 12 registered markets. The gate emitted 24 unclassified
missingness rows: two fields times 12 markets.

This is a feature-contract finding, not a model-quality claim. The held 10:00
audit did not list either field among the 19 active base features selected by
the audited 09:00–14:00 artifacts, so this mission does not claim a current
probability or Brier effect. No defect was fixed.

## Verdict

**The standalone gate is built and all four required defects were independently
rediscovered.** It compared both real feature-construction implementations over
all 221 feature-schema fields and all 12 registered markets. The proof report is
correctly `BLOCK`: 220 blocking findings plus one exact, evidenced exception for
the deliberate trusted-floor difference.

The implementation is on
`codex/workstation-train-serve-parity-gate-2026-09-03a`, based exactly on
`9275a41ea6d7d3c2a029f6e87c74a9122e8f05a9`. It is standalone. No fit, retrain,
candidate, fresh date, provider call, network client, release-path wiring,
promotion, pointer, serving, scheduler, capture, archive, sidecar, cache, or
`data/` write occurred.

## What was built

`weather.reporting.scorecards.train_serve_feature_parity` now provides a
no-network CLI and reusable comparator that:

1. sends one captured case through
   `build_historical_feature_record` and
   `TorontoHighTempModel.extract_live_features` independently;
2. emits separate findings for value, unit, category, and missingness;
3. fails populated fields whose source was not knowable at the row cutoff;
4. fails missing, discarded, stitched, invalid, or post-cutoff source/issue
   provenance; and
5. names the case, market, cutoff, field, dimension, both path values, and
   direction for every finding.

The gate fails coverage when any registered market lacks a full-schema case or
either builder omits a schema key. Both-missing cells remain explicitly
unobserved; they are not counted as equality proof. The report and input
manifest are separately SHA-256 bound, and the report is self-hashed.

The deterministic fixture derives market coverage from the live registry
rather than copying a market count. It uses a prior-year development case for
full-schema and station-path comparisons. The two WU point-in-time cases carry
forward the permitted `2026-07-22` evidence and contract from the held `-08-30a`
report; no production date row was read or reconstructed in this mission.

## Required defect proof

| Defect | Gate mechanism | Findings | Fields | Markets | Result |
| --- | --- | ---: | ---: | ---: | --- |
| Nine empty base features at 09:00–14:00 | Same normalized station packet; training builds the historical contract while serving uses the actual station adapter | 108 missingness rows | 9 | 12 | REDISCOVERED |
| Stitched `forecast_high` | Actual two-column daily loader result versus cutoff-provenanced live forecast | 4 availability/provenance rows | 2 (`forecast_high`, derived `forecast_gap`) | 1 | REDISCOVERED |
| Forecast-profile provenance discarded | Actual `load_forecast_profiles` projection versus the same raw profile on the serving path | 44 availability/provenance rows | 22 populated profile features | 1 | REDISCOVERED |
| WU surface fields not known by cutoff | Equal retrospective values with both packet receipt times after cutoff | 40 availability rows | 10 | 2 (C and F) | REDISCOVERED |

The important control result is that retrospective equality did not rescue the
WU cases: each value matched and still failed availability.

## False-positive characterization

The fixture explicitly exercised the warned-about trusted observed-high floor.
A lagging WU print and a captured cutoff-safe station high legitimately produce
different `high_so_far` values. The gate retained that row but classified it
through one exact exception for case, market, field, and dimension. The
exception names the `weather.model` owner, durable contract evidence, reason,
and review date. Wildcards and underspecified exceptions fail validation.

The final proof contained:

- 2,323 both-missing cells, all reported as unobserved rather than pass;
- one explicit trusted-floor exception;
- zero unclassified rows attributable to the floor or fixture construction;
  and
- 24 genuinely unclassified rows, all the new gust/shift missingness finding
  led above.

This fixture proof is not enough to claim a production false-positive rate. It
has broad market/feature coverage but deliberately small temporal diversity.
That is why immediate blocking on every value or missingness difference is not
recommended yet.

## Binding proposal — not implemented

Run this next to, not inside, captured replay/serve probability parity. The
natural later binding point is after captured-input evidence generation and
before production-readiness/release-candidate approval.

Use two stages:

1. **Advisory first** for value/category/missingness differences during one
   representative capture cycle across every registered market and active
   cutoff. Review all unclassified rows and ratify only deliberate contract
   differences such as the trusted floor.
2. **Blocking after that cycle** for active-artifact fields. Missing schema or
   market coverage, a future-known populated field, and missing/discarded issue
   or source provenance should block immediately; those conditions have no
   legitimate compatibility fallback.

A legitimate exception must identify one exact case family, market, field, and
dimension; name an owner; cite contract evidence; explain why both paths are
intentionally different; and carry a review/expiry date. No wildcard should be
accepted. Availability-after-cutoff and discarded forecast provenance should
not be exceptionable.

## Evidence

Declared run root:

`C:\Users\Michael\Documents\github\weather\scratch\runs\train-serve-parity-gate-2026-09-03a`

| Evidence | SHA-256 / result |
| --- | --- |
| Case manifest canonical SHA-256 | `358eaca1ce633b7debf6c68b294b6c7b5f98ae8ecbeaf22c53aefacc9ab73f17` |
| Self-hashed JSON report | `f4693e7e53e713613d6a85c7b1813de577e6db32265c4920cd1ee7d99a2a3295` |
| Registered markets | 12 / 12 |
| Feature schema | 221 / 221 |
| Compared cells | 2,908 |
| Known defects | 4 / 4 rediscovered |
| Coverage blockers | 0 |

## Verification

The repository venv was used for final checks. The initial bundled CPython 3.12
fallback could not load the repository's CPython 3.11 scikit-learn extension;
that was an environment mismatch, not a test failure.

```text
python -m pytest tests/reporting/test_train_serve_feature_parity.py \
  tests/model/test_feature_skew.py -q
23 passed, 666 subtests passed

python -m compileall -q app src tests
PASS

python -m weather.schema_registry audit --strict
PASS (0 unregistered schema versions)

python -m pytest tests/reporting \
  tests/operations/test_import_architecture.py -q
893 passed, 1 skipped, 23 subtests passed
```

An additional full-suite pass reached `3,290 passed`, `4 skipped`, and 17
host-environment failures. The failures are outside this change: three Windows
script/provenance groups cannot dot-source repository PowerShell because this
host disables script execution, and the experiment-executor fixtures exceed
the host's effective Windows path limit even under the shortest accessible
normal temp root. The parity tests, reporting owner suite, architecture ratchet,
schema audit, compile check, and documentation audit are green.

## Data and execution guardrails

The main `data/` ACL retained explicit, non-inherited deny entries for
write/delete rights for both `DESKTOP-RFCD2GH\Michael` and
`DESKTOP-RFCD2GH\CodexSandboxOffline`. This mission read only the loop status
files required for the loaded-module closure. It did not enumerate or read a
prohibited market date, and it wrote only beneath the declared run root and the
topic worktree.

## Loaded-module roll sensitivity

`SOURCE_PATTERNS` overstates the change. The recorded
`runtime_identity.source_scope_files` closures in the snapshot, CLOB, and
observation-trigger loop statuses give the exact answer:

- `src/weather/schema_registry_recent_data.py` **is roll-sensitive**. It is in
  the recorded loaded-module closure for `loop_status.json`,
  `clob_loop_status.json`, and `observation_trigger_status.json` (and the CLOB
  enrichment status).
- `src/weather/reporting/scorecards/train_serve_feature_parity.py` is **not in
  any recorded capture-loop closure**. It is standalone and will not affect a
  loop unless a future integration imports it.
- The test, fixture, and this report are not runtime source files.

No capture process was restarted or re-adopted.
