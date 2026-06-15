# 56. Market-Making Test Cockpit And Drilldown Diagnostics [COMPLETE 2026-06-15 - COCKPIT LIVE]

Goal: turn `http://localhost:8501/?market=mm` from a useful status page into an
operator cockpit for the live-forward market-making test.

Observed from the running page on 2026-06-15: the first viewport shows latest
run ID, mode, preflight, quotes, live rows, paper scoring totals, and the run
folder. It confirms the test is running, but it does not immediately answer the
operator questions that matter during a blocked or quiet run: why are there no
current quotes, which market or loop is blocking, whether budget is reserved
from current or stale quotes, whether the day counts toward the live-forward
gate, and what should be inspected next.

- [x] Add a run selector and make the selected run explicit; keep "latest run"
  as the default but do not require reading the filesystem path to know the
  current run scope.
- [x] Separate metric scopes in the UI: latest tick, cumulative selected run,
  all paper-scored runs, and live-forward gate history. Do not show mixed-scope
  counts without labels.
- [x] Add a per-market health matrix with source-status freshness, model age,
  CLOB trailing age, CLOB counted gaps, observation-trigger age, promotion
  state, known-edge permission, quote count, reservation count, and top blocker.
- [x] Add a blocker drilldown that groups `NO_QUOTE_*` reason codes by market,
  root cause, owning loop/artifact, first-seen time, last-seen time, and whether
  the blocker is recoverable during the same active day.
- [x] Add a budget and lifecycle panel that shows current open quote risk,
  stale/parked reservations, released budget, reserved-by-market, and the
  difference between run-risk budget and platform balance semantics.
- [x] Show live-forward gate progress: whether the current day counts, which
  SLO input blocks credit, how many locked paper days have cleared, and the next
  gate required before item 45 live pilot work.
- [x] Fix dashboard column/schema drift such as the budget table expecting
  `budget_action` while the ledger currently emits `event`.
- [x] Add a focused Streamlit/dashboard smoke test or artifact-render test so
  future schema changes in run summaries, ledgers, known-edge maps, and paper
  reports do not silently blank key cockpit columns.

Acceptance: from the first screen and one drilldown, an operator can explain
why the bot is quoting or not quoting, which markets are actionable, which loop
or artifact must recover, whether budget reservations are current or stale, and
whether the current day contributes to the MM paper gate.

Implementation update (2026-06-15): `app.views.market_making` now has a run
selector, scoped Latest Tick and Paper Corpus metrics, market-health matrix,
blocker drilldown, lifecycle budget panel, and live-forward gate panel. The
budget ledger table now shows both `event` and `budget_action`, and dashboard
helpers reconstruct current open lifecycle orders from `order_lifecycle.jsonl`.
Validation: `pytest tests\app\test_market_making_view.py -q` passed.
