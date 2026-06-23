# 265. Settlement-Source Revision And Truth-Label Audit [OPEN 2026-06-23 - LABEL FINALIZATION RISK NEEDS COUNTABLE PROOF]

Goal: measure how often WU final high, Weather.com max-since-7, market
resolution labels, and the canonical settlement ledger disagree or revise after
close.

Source: the 2026-06-23 research audit treated settlement-label uncertainty as a
first-class risk. Item 25 added settlement finalization and label quality
grades, item 153 added a monotonic settlement-normalized live high ledger, and
item 193 quarantined current-max anomalies. The remaining gap is a countable
post-close truth-label audit that compares source revisions and finalization
lag across the sources used to score promotion and trading evidence.

Why this matters: promotion gates, backtests, and taker PnL all depend on the
truth label. If a source revises after close, if WU final and Weather.com
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
4. Compare WU final high, Weather.com max-since-7, settlement-normalized live
   high, canonical ledger label, and market resolution label after the
   finalization window.
5. Rescore affected backtest/trading rows under alternate plausible labels
   where unresolved disagreement could change a pass/fail or PnL conclusion.
6. Add proof-packet counts for finalized labels, provisional labels, revised
   labels, unreconciled labels, and rows excluded from promotion-grade evidence.

- [ ] Add the settlement-source revision audit schema and report.
- [ ] Add source-finalization lag and disagreement counts by market and date.
- [ ] Add raw-payload lineage or explicit missing-lineage reasons for each
  audited label.
- [ ] Add alternate-label sensitivity for promotion and trading reports where
  label disagreement changes the result.
- [ ] Add a promotion blocker when proof-grade evidence depends on provisional
  or unreconciled labels.

Acceptance: any promotion, backtest, or trading report that relies on settled
labels can show whether those labels are finalized, revised, disagreed,
manually overridden, or unreconciled. Promotion-grade evidence must exclude or
explicitly block on unresolved truth-label uncertainty.

Related: items 25, 153, 166, 193, 201, 215, 232, 242.
