# Backtesting Instructions

These instructions apply under `weather.backtesting`. Inherit
[package guidance](../AGENTS.md).

- Score frozen captured inputs against authoritative settlement labels. Do not
  rebuild historical claims with future source data or current model state
  unless the output is explicitly classified as reconstructed/non-countable.
- Compare model probabilities with captured market prices using proper scoring,
  calibration, quality grades, and leakage-safe cutoff/split rules.
- Preserve market-day, native-unit, settlement provenance, release identity,
  captured-input hash, and schema lineage through replay.
- Keep weather-only and market-informed evidence separable. Missing/stale/
  partial inputs fail closed or remain visibly non-countable.
- Tests create temporary tapes and ledgers; they never depend on ignored local
  `data/` or network services.

Run matching `tests/backtesting` plus affected model/reporting tests. Model
improvement evidence expectations are in
[Development and Verification](../../../docs/development.md).

## Update this file when

Update when settlement/replay authority, countability, scoring/leakage policy,
evidence lineage, or backtesting verification changes.
