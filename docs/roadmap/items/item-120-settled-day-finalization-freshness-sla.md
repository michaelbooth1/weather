# 120. Settled-Day Finalization Freshness SLA [COMPLETE 2026-06-18 - NIGHTLY PREFLIGHT LIVE]

Goal: make the prior market day appear in the canonical settlement ledger,
folder-local `settlement.json` files, `market_day_labels.csv`, daily learning,
and promotion corpus before the nightly retrain/promotion decision runs.

Source: the 2026-06-18 review of the now-settled 2026-06-17 market day found
all 12 June 17 snapshot folders present with full tapes, but
`data/backtest/market_day_labels.csv` still topped out at `2026-06-16`, every
per-market settlement ledger also topped out at `2026-06-16`, and all 12 June
17 folders were missing folder-local `settlement.json`. The daily refresh last
ran at `2026-06-17T13:54Z`, before June 17 had settled; the
`2026-06-18T07:30Z` nightly retrain ran daily learning only and blocked on
existing gates without finalizing the newly settled day.

Codex deep data-layer audit update (2026-06-18): the fresh audit report at
`data/backtest/codex_data_layer_deep_audit_2026_06_18.md` failed the data
gate because only 141 of 153 training-ready folders had
`replay_input_status_long.csv`; the 12 missing folders were the June 17 market
folders. The same audit found recent source-lag touchups still needed before
the settled corpus is fully current: WU and METAR were missing June 15-17,
GHCNh was missing June 10-17, and reanalysis was missing June 11-17 for the
active-market sample. Treat replay-status freshness as part of settled-day
finalization, not a separate optional repair.

Why this matters: a clean active-day tape is not useful training or promotion
evidence until the canonical label path sees it. If finalization lags the
nightly decision, the reports can say `run_date=2026-06-17` while still scoring
only through `2026-06-16`, and the operator has to discover the missing day by
manual file inspection.

## Design

1. Add a freshness gate that compares yesterday's expected market folders with
   the latest target date in `market_day_labels.csv`, per-market ledgers, and
   folder-local `settlement.json`.
2. Make nightly retrain run or require a lightweight settled-day finalization
   preflight before daily-learning blockers can short-circuit the job.
3. Distinguish official daily-summary settlements from snapshot-history
   fallback settlements in the report, including source-lag warnings when WU
   daily summaries are stale.
4. Add an operator repair command that can finalize only missing prior-day
   labels without downgrading existing reconciliation evidence.
5. Expose the stale-label condition in daily learning and fleet observability
   as a P0 data freshness blocker.
6. Include `replay_input_status_long.csv`, `replay_inputs.jsonl`, and
   source-status artifacts in the same freshness report so the day cannot look
   settled while replay eligibility is still missing.

- [x] Add a settled-day freshness report with expected folders, label rows,
  ledger rows, and folder-local settlement copies by market.
- [x] Wire the freshness gate into nightly retrain before daily-learning
  short-circuiting.
- [x] Add a safe missing-day finalization command that preserves existing
  reconciled ledger rows.
- [x] Add tests for the June 17 pattern: folders exist, labels/ledgers stop at
  the prior day, and nightly learning reports the wrong effective evidence
  date.
- [x] Record source-lag provenance when daily summaries are stale and labels
  rely on snapshot-history fallback.
- [x] Fail the same gate when prior-day replay-status artifacts are absent and
  print the targeted repair command from the audit remediation manifest.

Acceptance: by the first nightly retrain after a market day settles, the
canonical label outputs include all expected prior-day markets or the reports
name the exact missing markets and repair command.

## Completion Notes

Implemented `weather.operations.settled_day_freshness` with `report` and
`repair` commands. Nightly retrain now runs the repair preflight before daily
learning. The report covers labels CSV, per-market ledgers, folder-local
`settlement.json`, `replay_input_status_long.csv`, `replay_inputs.jsonl`, and
`source_status_long.csv`, with source-lag provenance and separate label and
replay repair commands. Daily learning and fleet observability now surface a
failing settled-day freshness artifact as a P0 data-freshness blocker.

Verification:
`python -m pytest tests/operations/test_settled_day_freshness.py tests/operations/test_nightly_retrain.py tests/reporting/test_daily_learning.py tests/reporting/test_fleet_observability.py -q`

Latest production check (2026-06-18):
`data/backtest/settled_day_freshness.json` reports `WARN` for target date
`2026-06-17`: all 12 expected markets are complete, with zero missing labels,
ledgers, folder settlements, replay inputs, replay-status artifacts,
source-status artifacts, or tapes. The remaining warning is explicit
source-lag provenance: all 12 labels rely on snapshot-history fallback while
daily summaries are stale.
