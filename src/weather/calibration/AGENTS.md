# Calibration Instructions

These instructions apply to training, replay, calibration, and candidate
artifact code under `weather.calibration`. Inherit
[package guidance](../AGENTS.md).

- Training operates in each market's native unit and must use the same feature
  definitions, cutoff semantics, and schema meanings as live model extraction.
- Use time/market-safe splits, proper scoring, protected slices, and explicit
  data-quality/countability gates. Do not treat in-sample fit or calibration
  improvement as proof of edge over market prices.
- Default outputs are candidates or local reports. Do not write into an active
  release, mutate an immutable release, or promote because a training command
  completed successfully.
- Preserve artifact provenance, feature lists, estimator/dependency
  compatibility, fit receipts, and replay identities. Schema changes require
  readers, writers, serving, fixtures, and tests to move together.
- Long jobs must use existing guards, bounded/cache-aware execution, and
  resumable outputs. Avoid loading an unbounded local corpus into memory.

Run matching `tests/calibration` tests plus model parity/release tests for any
serving-facing change. Read [Model Instructions](../model/AGENTS.md) and the
[Nightly Retrain Runbook](../../../docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md).

## Update this file when

Update when training/evaluation policy, candidate output boundaries, artifact
provenance, long-job safety, or calibration verification changes.
