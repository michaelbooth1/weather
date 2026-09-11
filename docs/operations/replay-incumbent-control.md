# Replay incumbent distribution control

Status: canonical diagnostic contract. Owner: `weather.backtesting`.

`python -m weather.backtesting.replay_backtest` scores current-code replay.
Its aggregate Brier delta is descriptive. A diagnostic PASS does not establish
model improvement, a qualified candidate comparison, or historical serving
reproduction.

## Two separate checks

| Check | Supported claim | Failure behavior |
| --- | --- | --- |
| Default replay and `--gate` | Diagnostic aggregate Brier comparison; changed candidate identities are expected | The aggregate check exits 1 on regression, missing/incompatible corpus binding, or invalid numbers. Its message retains numerical fidelity warnings. |
| `--require-incumbent-control --corpus PATH` | Numerical reproduction of every pinned incumbent distribution under the same declared identity | Any unsupported or unfaithful control exits 1 before baseline publication. This is an explicit incumbent check, not a default requirement that candidates have the incumbent identity. |

The incumbent check is preparation for a comparison. The current identity
covers selected code/artifact fingerprints; it does not prove which complete
runtime bytes were loaded. Restoring immutable source, artifacts, effective
configuration and dependency closure, reproducing served band probabilities
after calibration, and paired statistical inference remain separate work.
[Item 333](../roadmap/items/item-333-reproducible-runtime-and-paired-model-comparison.md)
owns that broader scope.

## Population and numerical contract

The control uses the entire manifest's entry-level `snapshot_ids`, keyed by
event slug and snapshot ID. Manifest summary counts cannot define the expected
population. Each entry must have complete SHA-256 maps for both
`replay_record_hashes` and `tape_row_hashes`; input verification warnings fail
the check. Every entry also needs a finite integral settlement bucket and a
nonblank settlement source; missing or malformed label pins fail without
reading mutable daily history. This validates usable pinned values, not the
settlement source's authority. Missing or extra snapshots, duplicate manifest/fidelity rows, and
duplicate raw pinned replay records fail. Raw records are checked before the
legacy later-record-wins index can hide a duplicate.

A control requires a nonempty population of captured, exact-identity rows.
Legacy, intentionally changed and reconstructed rows remain separate
diagnostic cohorts and cannot supply the incumbent control. Narrowing folders
or `--market` must still cover the entire supplied manifest. Use a separately
prepared bounded manifest for a smaller question. An empty selection fails
without expanding to all local tapes. Settlement overrides, a daily-summary
override and reconstructed inclusion are diagnostic-only CLI options.

Both distributions must be nonempty mappings with finite coordinates and
finite probabilities between zero and one. Native buckets must be whole
degrees without colliding numeric keys. Continuous-density payloads use the
canonical payload recognizer and retain their full Fahrenheit grid coordinates.
Representations must agree. Comparison performs no normalization or coordinate
rounding. Probability-mass validation reuses
`worker_release_binding.RECORDED_DISTRIBUTION_MASS_TOLERANCE`.

Every exact-identity row must have finite, nonnegative L1 at or below
`replay_fidelity.FIDELITY_FAITHFUL_L1`. The maximum row error controls the
verdict; a low mean cannot hide concentrated errors. Invalid and above-tolerance
counts remain visible. This is a distribution check; captured market-band rows
need not form a complete partition and are not forced to sum to one.

## Invocation and retained output

Replay is heavy work. Follow the [host load policy](HOST_LOAD_POLICY.md) and
the assigned workstation's admitted wrapper before running it. These module
arguments illustrate a bounded incumbent check:

```powershell
python -m weather.backtesting.replay_backtest --corpus data/backtest/selected-corpus.json --require-incumbent-control --out data/backtest/incumbent-control.md --save-baseline data/backtest/incumbent-diagnostic-baseline.json
```

The paths are illustrative ignored runtime state, not clean-checkout fixtures.
A failed completed check retains its diagnostic Markdown report and
`<report-stem>.fidelity.csv` with every attempted snapshot's identity, L1 and
distribution-error reason. Support counts and bounded missing/extra examples
remain in the report. A request with no selected tapes fails before replay.

`--save-baseline` and `--gate` are mutually exclusive. A requested control must
pass before either CLI baseline publication or the `save_baseline` API writes
a baseline. The saved JSON labels its Brier scope as diagnostic and retains
fidelity/control status. A changed candidate can subsequently use `--gate`
without `--require-incumbent-control`; its diagnostic PASS still does not
qualify the candidate.

## Update when

Update when control selection, identity cohorts, distribution validation,
tolerance ownership, CLI failure order, baseline claims or retained diagnostics
change. Keep roadmap status and runtime-restoration progress in their owners.
