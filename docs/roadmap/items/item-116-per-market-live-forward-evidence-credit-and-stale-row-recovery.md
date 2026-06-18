# 116. Per-Market Live-Forward Evidence Credit And Stale-Row Recovery [COMPLETE 2026-06-17 - PER-MARKET CREDIT LIVE]

Goal: preserve countable per-market model-review and paper-trading evidence
when one market is stale, while keeping broad all-market/live-trade claims
fail-closed.

Source: the June 17 paper-live-forward run produced quote activity, but the
report still had `Counts toward live-forward gate: false`: NYC was stale, model
review and paper trading counted for 11 of 12 markets, and live-trade
permission counted for 0 of 12 because the run was keyless paper-live-forward.

Why this matters: the all-selected live-forward verdict should stay false when
any required gate fails, but throwing away the other 11 markets' model-review
or paper-trading evidence slows the same independent-evidence growth that the
promotion process needs.

## Design

This extends item 101's reconciled gate artifact and item 110's evidence-mode
classification. It changes evidence accounting, not live order safety.

1. Store per-market evidence credits for each class:
   `model_review_evidence`, `paper_trading_evidence`, and
   `live_trade_permission_evidence`.
2. Let model-review and paper-trading evidence be countable per market when
   their own gates pass, even if the all-selected run verdict is false because
   another market is stale.
3. Keep live-trade-permission evidence false in keyless paper modes and whenever
   live-pilot/platform gates are absent.
4. Add stale-row recovery for the first failing market gate: trigger a bounded
   snapshot/model refresh or source-status repair before the next tick, then
   record whether the retry cleared the market.
5. Feed per-market evidence credits into daily learning, fleet observability,
   and the market-making dashboard so audits can distinguish "11 markets
   counted, 1 stale" from "nothing countable happened."

- [x] Persist per-market evidence-credit rows from `live_forward_gate.json`.
- [x] Add stale model/source-row recovery attempts before the next tick.
- [x] Add daily summaries for countable markets by evidence class.
- [x] Keep all-selected and live-trade verdicts fail-closed when any required
  gate or live-pilot condition is missing.
- [x] Add a regression for the June 17 pattern: one stale market, 11 countable
  model-review markets, 0 live-trade-permission markets.

Acceptance: a paper-live-forward run with one stale market contributes
per-market model-review/paper evidence for the fresh markets, marks the stale
market with owner/remediation, and still makes no broad all-market or live
trading claim.

## Completion Notes

Implemented on 2026-06-17:

- `live_forward_gate.json` market rows now carry `stale_recovery` metadata for
  the first failing gate, including owner, root cause, suggested command, last
  good timestamp, observed age, and threshold.
- `mm_paper_report.json` persists scoreable per-market evidence-credit rows and
  summary counts for `model_review_evidence`, `paper_trading_evidence`, and
  `live_trade_permission_evidence`.
- `mm_paper_report.md`, `fleet_observability_report.md`, and
  `daily_learning_report.md` surface the per-market evidence counts separately
  from the broad live-forward/live-trade gate.
- Daily learning adds a `live_forward_partial_credit` learning when model-review
  evidence is countable per market, but keeps broad live-forward and live-trade
  permission gated by all-selected/live-pilot requirements.
- The summary de-duplicates recovered stale rows: if a later scoreable run
  clears a market, older stale rows remain auditable but no longer appear as a
  currently blocked market in the count summary.

Verification:

- `python -m pytest -q tests\market\test_mm_paper.py tests\reporting\test_fleet_observability.py tests\reporting\test_daily_learning.py`
  passed with 33 tests.
- Regression coverage includes the June 17 pattern: one stale market, 11
  countable model-review markets, 11 countable paper-trading markets, 0
  live-trade-permission markets, and an empty strict live-forward day list.
- Current refreshed artifacts show recovered per-market model-review/paper
  credit: `data/backtest/mm_paper_report.json` and
  `data/backtest/fleet_observability.json` report 12 model-review markets, 12
  paper-trading markets, and 0 live-trade-permission markets; daily learning
  remains `BLOCKED` by the broad live-forward SLO.
