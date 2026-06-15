# 46. Date/Budget Market-Making Run Orchestrator [COMPLETE 2026-06-15 - OPERATOR WORKFLOW LIVE]

Goal: make the first market-making operator workflow a single target day plus
total budget, without mixing orchestration concerns into the pure quote policy.

Research source: `docs/research/MM_INITIAL_TEST_RUN_DESIGN.md`. The operator
should be able to choose a date and a total budget; the run should discover the
tracked weather markets for that day, call the pure `mm_policy`, enforce
preflight gates, write run artifacts, and keep total run risk inside the
operator budget.

- [x] Add a `src.market_making_run` wrapper around `src.mm_policy` /
  `weather.market.mm_policy` with `--date`, `--budget-usdc`, `--mode`, market
  selection, and explicit live-confirmation flags.
- [x] Create one run folder per invocation under `data/mm_runs/<date>/<run_id>/`
  with `run_config.json`, `preflight.json`, `quote_intents_long.csv`,
  `budget_ledger.jsonl`, `risk_events.jsonl`, `fills_long.csv`, and
  `run_report.md`.
- [x] Implement target-date market discovery through `market_registry.all_specs()`
  and `config_for_date()`, resolving each tracked weather market to the correct
  event slug, snapshot folder, token IDs, condition IDs, reward config, min
  size, tick size, and current book state.
- [x] Add preflight gates for active events, current snapshot/model rows, current
  source-status rows, CLOB tokens/books, strict CLOB freshness, fresh
  observation-trigger state, promotion state, reward metadata, and, in live
  modes only, account/platform/wallet/allowance/heartbeat/user-WS readiness.
- [x] Write complete quote/no-quote rows for every eligible band and explicit
  no-quote rows for ineligible bands, including `budget_exhausted`,
  `missing_preflight`, and `stale_input` reason codes.
- [x] Support `shadow` first, `paper-live-forward` as the all-day unattended
  mode, and later `live-pilot` only after item 45's live gate passes.

Acceptance: an operator can run one command with only date, budget, and mode;
the keyless shadow run covers all selected tracked markets, writes a complete
run folder, never emits live-trade permission in shadow, fails closed on stale
CLOB/watcher inputs, and produces a report explaining selected markets,
unquoted markets, quote counts, budget usage, and next gating status.

Implementation status (2026-06-15): `src.market_making_run` /
`weather.market.market_making_run` now orchestrates one target date plus a run
risk budget around the pure `mm_policy`. It discovers selected markets through
the registry and `config_for_date()`, writes `data/mm_runs/<date>/<run_id>/`,
runs target-day preflight gates, calls the pure policy for current band rows,
applies a conservative run-budget ledger, converts stale or missing-gate rows to
explicit fail-closed no-quotes, and writes a durable report. Shadow and
paper-live-forward never emit live-trade permission; live-pilot is accepted only
as a gated mode requiring `--pilot`, `--confirm-live-orders`, and a passing
live-readiness JSON while item 45 remains the real-money gate.

Validation: `pytest tests\market\test_market_making_run.py -q` passed
(4 tests); `pytest tests\market\test_mm_policy.py tests\market\test_market_making_run.py -q`
passed (11 tests); full `pytest -q` passed (449 tests, 84 subtests);
`compileall src tests` passed; `python -m src.market_making_run --help` exposes
the operator CLI, and a temp-root CLI smoke wrote the expected run artifacts.
