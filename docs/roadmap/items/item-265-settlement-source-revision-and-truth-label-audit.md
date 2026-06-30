# 265. Settlement-Source Revision And Truth-Label Audit [COMPLETE 2026-06-23 - TRUTH-LABEL AUDIT AND BLOCKER LIVE]

Goal: measure how often WU final high, disabled paid-provider max-since-7, market
resolution labels, and the canonical settlement ledger disagree or revise after
close.

Source: the 2026-06-23 research audit treated settlement-label uncertainty as a
first-class risk. Item 25 added settlement finalization and label quality
grades, item 153 added a monotonic settlement-normalized live high ledger, and
item 193 quarantined current-max anomalies. The remaining gap is a countable
post-close truth-label audit that compares source revisions and finalization
lag across the sources used to score promotion and trading evidence.

Why this matters: promotion gates, backtests, and taker PnL all depend on the
truth label. If a source revises after close, if WU final and disabled paid-provider
max-since-7 diverge, or if a manual override hides disagreement, the system can
learn a false edge or reject a valid signal.

## Design

1. Build a per-market-date revision timeline with source, first-seen timestamp,
   post-close timestamp, finalization timestamp, raw high, rounded settlement
   high, bucket, canonical ledger label, and market resolution label.
2. Consume existing raw observation payload sidecars where available, and
   require source hashes or explicit missing-payload reasons for new audit
   rows.
3. Classify each label as `PROVISIONAL`, `FINALIZED`, `SOURCE_STALE`,
   `SOURCE_REVISION`, `SOURCE_DISAGREEMENT`, `MANUAL_OVERRIDE`, or
   `UNRECONCILED`.
4. Compare WU final high, disabled paid-provider max-since-7, settlement-normalized live
   high, canonical ledger label, and market resolution label after the
   finalization window.
5. Rescore affected backtest/trading rows under alternate plausible labels
   where unresolved disagreement could change a pass/fail or PnL conclusion.
6. Add proof-packet counts for finalized labels, provisional labels, revised
   labels, unreconciled labels, and rows excluded from promotion-grade evidence.

- [x] Add the settlement-source revision audit schema and report.
- [x] Add source-finalization lag and disagreement counts by market and date.
- [x] Add raw-payload lineage or explicit missing-lineage reasons for each
  audited label.
- [x] Add alternate-label sensitivity for promotion and trading reports where
  label disagreement changes the result.
- [x] Add a promotion blocker when proof-grade evidence depends on provisional
  or unreconciled labels.

Acceptance: any promotion, backtest, or trading report that relies on settled
labels can show whether those labels are finalized, revised, disagreed,
manually overridden, or unreconciled. Promotion-grade evidence must exclude or
explicitly block on unresolved truth-label uncertainty.

Related: items 25, 153, 166, 193, 201, 215, 232, 242.

## Completion Evidence

Completed on 2026-06-23:

- Added `weather.reporting.source_gates.settlement_source_audit`, schema
  `settlement_source_revision_audit_v0.1`, with JSON and Markdown outputs at
  `data/backtest/settlement_source_revision_audit.json` and
  `data/backtest/settlement_source_revision_audit.md`.
- The audit classifies labels as `FINALIZED`, `PROVISIONAL`, `SOURCE_STALE`,
  `SOURCE_REVISION`, `SOURCE_DISAGREEMENT`, `MANUAL_OVERRIDE`, or
  `UNRECONCILED`; records finalization lag by market/date; records source
  bucket disagreements; and stores raw lineage hashes or explicit
  missing-payload reasons for WU daily summary, snapshot tape, settlement
  ledger, disabled paid-provider max-since-7, and market resolution evidence.
- Alternate-label sensitivity now marks rows where another plausible source
  bucket would change the result, and the target-date gate blocks
  promotion-grade/trading evidence when settled target dates have provisional,
  revised, disagreed, manually overridden, unreconciled, or missing audit rows.
- Daily refresh now runs `settlement_source_audit` after maker paper score and
  before trading evidence. Trading evidence consumes the audit JSON and reports
  `settlement_source_audit_status` plus blockers.

Current generated audit snapshot:

- `201` labels audited.
- `54` proof-grade finalized labels.
- `147` labels block promotion-grade use.
- `143` provisional labels, `2` source-revision labels, `2` source-disagreement
  labels, and `3` alternate-label result-change rows.

Verification:

- `python -m pytest tests\reporting\test_settlement_source_audit.py tests\reporting\test_trading_evidence.py tests\operations\test_schema_registry.py -q`
  passed with `13 passed`.
- `python -m pytest tests\operations\test_daily_refresh.py -q` passed with
  `46 passed`.
- `python -m weather.reporting.source_gates.settlement_source_audit --json-out data\backtest\settlement_source_revision_audit.json --report-out data\backtest\settlement_source_revision_audit.md`
  generated status `BLOCK`, reflecting current non-proof-grade label rows.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-23 - TRUTH-LABEL AUDIT AND BLOCKER LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

