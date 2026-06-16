# 90. Large Module Decomposition For Calibration And Market Operations [COMPLETE 2026-06-16 - CALIBRATION AND PREFLIGHT SPLITS LIVE]

Goal: reduce high-risk "god modules" by splitting large calibration and market
operation files along stable responsibility boundaries.

Source: 2026-06-16 architecture review. Several active modules are over one
thousand lines and combine dataset construction, model training, replay,
artifact writing, report rendering, CLI parsing, and operational state
management. The biggest pressure points include `pooled_feature_model.py`,
`pooled_candidate_replay.py`, `feature_model.py`, `market_making_run.py`,
`mm_paper.py`, `mm_exchange.py`, `observation_trigger.py`, and
`data_layer_audit.py`.

Why this is missing: the code evolved quickly around live research and local
operations. The files are tested, but their size makes review, ownership, and
behavior-preserving changes harder than necessary.

- [x] Pick one target module at a time and capture its public functions, CLI
  commands, generated artifacts, and tests before moving code.
- [x] For calibration modules, split toward `dataset`, `training`,
  `postprocessing`, `artifacts`, `reports`, and `cli` submodules where those
  boundaries already exist in the function groups.
- [x] For market-making modules, split exchange request planning, adapter
  implementations, lifecycle reconciliation, paper scoring, run orchestration,
  and report rendering into separate modules.
- [x] Keep existing CLI commands and compatibility wrappers stable while each
  module is decomposed.
- [x] Add focused import guards or ownership notes so extracted modules do not
  immediately re-couple into one broad dependency surface.

Acceptance: the largest active modules are decomposed into smaller
responsibility-specific modules without changing documented commands, generated
artifact schemas, or replay/backtest behavior.

## Design

First decomposition target: `weather.calibration.pooled_candidate_replay`.

Why this target first:

- It is one of the two largest active modules and it mixes replay orchestration,
  candidate feature construction, CLOB-overlay scoring, conservative bridge
  policy, shadow-variant CSV export, artifact IO, promotion verdicts, report
  handoff, and CLI parsing.
- The cleanest low-risk boundary is the scoring/shadow-policy layer: those
  functions already operate on row dictionaries and artifact payloads, and they
  do not need to instantiate models or walk snapshot folders.
- Keeping the old module as the public compatibility facade lets existing tests,
  scheduled commands, and local imports continue to use
  `weather.calibration.pooled_candidate_replay`.

Implementation shape:

- Add `weather.calibration.pooled_candidate_scoring` for:
  artifact loading/hash helpers, probability validation, band probability
  mapping, candidate/current/market score comparisons, CLOB overlay gate
  decisions, item-69 shadow-variant row generation, conservative bridge policy,
  and exact-winner diagnostics.
- Keep `pooled_candidate_replay.py` focused on snapshot/corpus loading,
  feature-row construction, candidate probability attachment, microstructure
  model training, promotion verdict aggregation, report handoff, and CLI
  behavior.
- Re-export the moved names from `pooled_candidate_replay.py` during the
  migration so tests and external callers do not need an immediate import
  rewrite.
- Extend the import architecture guard so the extracted scoring module cannot
  import the orchestration module.

Second decomposition target: `weather.market.market_making_run`.

Why this target second:

- It is the active market-making orchestrator and combines run setup, preflight
  live gates, remediation incident generation, quote-loop orchestration,
  lifecycle/budget output, report assembly, and CLI parsing.
- Exchange adapters, paper scoring, policy decisions, support helpers, and paper
  reports already live in separate modules; the remaining high-value split is
  to move live preflight verification and remediation policy out of the run
  orchestrator.

Implementation shape:

- Add `weather.market.market_making_preflight` for data-layer live gates,
  platform-verification gates, secret-material checks, supported-platform
  validation, remediation rule ownership, incident assembly, and remediation
  risk-event rows.
- Keep `market_making_run.py` as the public run facade and CLI owner, with
  compatibility imports for callers that still import preflight helpers from
  the old module.
- Extend the import architecture guard so the extracted preflight module cannot
  import the run orchestrator.

Verification strategy:

- Run focused pooled-candidate replay tests after the split.
- Run focused market-making run tests after the preflight split.
- Run the architecture guard.
- Run the full suite before marking the item complete.

## Completion

Completed 2026-06-16.

- Added `weather.calibration.pooled_candidate_scoring` and moved row-level
  replay scoring, CLOB overlay gates, shadow-variant export helpers,
  conservative bridge policy, artifact hash/load helpers, and exact-winner
  diagnostics out of `pooled_candidate_replay.py`.
- Kept `weather.calibration.pooled_candidate_replay` as the CLI/orchestration
  facade for corpus loading, feature construction, candidate attachment,
  microstructure model training, promotion verdict aggregation, and report
  handoff.
- Added `weather.market.market_making_preflight` and moved data-layer live
  gates, platform verification, secret checks, remediation rules, incident
  assembly, and remediation risk events out of `market_making_run.py`.
- Kept `weather.market.market_making_run` as the date/budget run facade and CLI
  owner while re-exporting moved helper names for compatibility.
- Extended `tests/operations/test_import_architecture.py` to include the new
  modules and prevent extracted modules from importing their orchestration
  facades.

Verification:

- `.\venv\Scripts\python.exe -m pytest tests\calibration\test_pooled_candidate_replay.py -q` (28 passed)
- Focused pooled-candidate/promotion consumer slice: 53 passed.
- `.\venv\Scripts\python.exe -m pytest tests\market\test_market_making_run.py -q` (20 passed)
- `.\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py -q` (7 passed)
- `.\venv\Scripts\python.exe -m pytest` (794 passed)
