# Workstation report 2026-08-03 — build the PIT forecast corpus

## Verdict

The immutable, training-only point-in-time forecast corpus lane is implemented
on `codex/workstation-build-pit-forecast-corpus-2026-08-31a`, based exactly on
`b7345ab2e6b0e1367ccdc5b096ca06a2da0efd7f`.

No network client exists in the lane. This mission made no provider call,
performed no fetch, fit, retrain, candidate build, promotion, pointer, release,
scheduler, capture, archive, sidecar, analog, cache, or `data/` write. The only
task execution output is the requested dry-run plan under the declared run
root.

## Implemented contract

`weather.sources.forecast_training_corpus` now owns:

- a self-hashed immutable planner with enumerated market/year/date/cutoff,
  endpoint, model, fixed lead, variable/unit bindings, request parameters,
  request hashes, and call-equivalent estimates;
- request-keyed raw staging with allowlisted HTTP metadata, retrieval time,
  raw SHA-256, byte and row counts, field/unit checks, exact hourly envelopes,
  issue/run evidence, and an append-only failure ledger;
- resume that skips only a complete receipt whose self-hash, byte count, and
  raw response hash still match;
- strict rejection of zero rows, target-year rows, rows outside the immutable
  request window, missing/null fields, invalid units, empty or stitched issue
  identity, invalid issue/availability time, and issue or availability after a
  requested cutoff;
- all-unit normalization into native-unit hourly profiles, cutoff-specific
  daily highs, and exact field-status coverage rows carrying request/raw/issue
  lineage;
- fully verified temporary materialization followed by one atomic rename to a
  content-addressed `corpora/<corpus_id>` path, with overwrite refusal; and
- a verified explicit reader that never consults the legacy active archive.

The corpus verifier binds the plan, file inventory, file hashes and byte
counts, exclusions, positive row counts, coverage totals, and corpus identity.
The retraining preflight reconstructs the exact planned market/date/cutoff
matrix, verifies field and issue-contract status, matches daily and coverage
PIT timestamps, and checks the complete 24-hour profile matrix and derived-row
hashes before record assembly.

Pooled feature assembly accepts the corpus only through
`--pit-forecast-corpus-manifest`. When set, ambient
`forecast_daily.csv`/`forecast_long.csv` loading is unreachable. Forecast high,
gap, and supported profile columns use the same cutoff-specific resolver;
provider/run/lead/hash provenance is copied into the assembled training row.
The three forecast-relative marine fields are nulled rather than retaining
legacy-derived sidecar values.

All forecast profile columns have an executable disposition. Forty-one are
mapped to the 21 planned Previous Runs fields. The twelve air-quality and
ensemble-history columns are explicitly excluded. Forecast-relative marine,
the forecast-error secondary artifact, late-day continuation, and analog
distance are separately excluded with reasons; the active analog archive stays
pinned.

## Failure-mode proof

Fixture-only tests prove:

- one missing request blocks publication before a `corpora/` directory exists;
- a zero-row response is a failed staged unit and is written to the failure
  ledger;
- corrupting a staged raw body makes resume incomplete;
- target-year, stitched/empty-issue, invalid-unit, incomplete-envelope, and
  post-cutoff availability inputs cannot become complete staging units;
- a failed staging matrix cannot materialize;
- publication outside the active archive is content-addressed and atomic;
- a second publication of the same identity is refused rather than overwritten;
- a publication root overlapping the active archive is refused; and
- C and F market values remain native end to end, with Celsius exposed only as
  an explicit derived alias.

## Dry-run plan receipt

The review artifact is:

`scratch/runs/pit-forecast-corpus-2026-08-31a/pit-forecast-plan-2021-2025.json`

Its identifiers and scope are:

| Field | Value |
| --- | --- |
| Mode | `dry_run_no_network` |
| Network authorized | `false` |
| Provider probe authorized | `false` |
| Plan SHA-256 | `1811831b419afbf3610c5265e2fd5707e476baaa0ac31257cb2272f87b33c0fe` |
| File SHA-256 | `f5e6915b7a267502a4303eb571770c7abf5a806a0a91798dbe92ab666801e967` |
| File bytes | `611408` |
| Training years | `2021, 2022, 2023, 2024, 2025` |
| Target year | `2026`, structurally excluded |
| Season | May 10 through August 31, 114 days/year |
| Markets | all 12 registered markets |
| Cutoffs | local hours 07 through 20 |
| Source | Open-Meteo Previous Runs, `gfs_seamless`, fixed lead day 1 |
| Planned source fields | 21 |
| Request units | 60 market/year requests |
| Variable bindings | 1,260 |
| Expected market-dates | 6,840 |
| Expected market/date/cutoffs | 95,760 |
| Expected field/date/cutoff cells | 2,010,960 |
| Estimated call-equivalents | 1,026 |

The receipt is a proposed request contract, not evidence of provider support.
Every request is marked `probe_required_before_collection`.

## Verification

```text
python -m pytest -q tests/sources/test_forecast_training_corpus.py \
  tests/calibration/test_forecast_training_contract.py
16 passed

python -m pytest -q <PIT tests plus adjacent pooled, historical-source,
  feature-store, schema-registry, and import-architecture suites>
126 passed, 12 warnings

python -m compileall -q app src tests
PASS

python -m weather.schema_registry audit --strict
PASS (517 registered, 852 discovered, 0 unregistered)

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 594 Markdown files)
```

The warnings are existing scikit-learn missing-column warnings from feature
store fixtures, not failures in this lane.

## Specification findings and remaining blockers

Two facts remain deliberately unresolved because this mission prohibited the
only actions that could answer them:

1. The earlier provider analysis established long GFS temperature support but
   did not establish 2021–2023 availability for every cloud, radiation, and
   thermodynamic field, nor prove that fixed-offset values form one coherent
   cutoff-safe issue envelope. The single authorized provider probe must test
   those exact requests and supply conservative availability evidence. Any
   missing field/year or rolling/stitched issue semantics leaves the real build
   blocked; the lane will not narrow the matrix silently.
2. The all-market base-retrain implementation is not present at the mandated
   `b7345ab2` base; it remains on its independent Item 26 topic branch. Directly
   editing that absent candidate here would have violated the exact-base and
   independently-mergeable constraints. This branch supplies the explicit
   corpus reader, pooled-record assembly flag, and mandatory preflight contract.
   When the two topic branches are stacked, the base-retrain corpus manifest
   must bind this preflight receipt and its plan/corpus hashes before fitting.
   Until that small cross-branch binding is made, a real base retrain remains
   blocked.

No serving construction was changed. Therefore the new fixed-lead contract is
not yet proof of train/serve feature parity and grants no fit authorization.

## Roll-sensitive files

These changed files match `SOURCE_PATTERNS`:

- `src/weather/calibration/forecast_training_contract.py`
- `src/weather/calibration/pooled_feature_assembly.py`
- `src/weather/calibration/pooled_feature_cli.py`
- `src/weather/schema_registry_recent_data.py`
- `src/weather/sources/forecast_history.py`
- `src/weather/sources/forecast_training_corpus.py`

No `scripts/**/*.ps1` or `tools/**` file changed. Tests and documentation are
outside `SOURCE_PATTERNS`.
