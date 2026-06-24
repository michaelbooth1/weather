# 302. Post-Settlement Disagreement Audit Rehydration Gate [OPEN 2026-06-24 - AUDIT SNAPSHOTS CAN REMAIN PENDING AFTER LABELS SETTLE]

Goal: automatically rehydrate disagreement-audit snapshots after settlement so
operator reviews use final labels, not stale pending rows.

Source: settled 2026-06-23 log audit. The disagreement analysis generated after
settlement still reported most June 23 rows as `pending_settlement` even though
all 12 market labels existed. That left NYC, Seattle, Chicago, Dallas, and San
Francisco disagreements unresolved in the audit report, and some pre-settlement
interpretations changed materially after labels were available.

Why this matters: disagreement snapshots are valuable because they focus human
attention on high-information model/market conflicts. If they are not refreshed
after labels settle, the operator loop can keep reviewing stale pending cases,
miss true market-closer cases, or overstate cases that the final settlement
resolved in the model's favor.

Why it is not already covered: item 41 created the disagreement casebook and
item 271 created the operator loop, but neither requires a post-settlement join
refresh. Item 294 checks daily-analysis input freshness broadly, but it does not
force the disagreement artifact itself to resolve target-date rows once labels
exist.

## Design

1. Add a post-label rehydration step that joins every target-date disagreement
   row to the canonical settled label and rewrites resolution fields.
2. Emit counts for unresolved rows, resolved rows, model-closer rows,
   market-closer rows, and rows excluded because the target label remains
   partial or missing.
3. Block daily audit conclusions when any target-date disagreement remains
   `pending_settlement` after settled-day freshness says labels are present.
4. Add a before/after section to the audit report showing which pre-settlement
   watchlist cases changed interpretation.
5. Surface the rehydrated disagreement status in daily learning and the audit
   operator dashboard.

- [ ] Add post-settlement disagreement rehydration to the daily refresh order.
- [ ] Fail closed when target-date rows remain pending after labels exist.
- [ ] Add settled interpretation deltas to the disagreement Markdown report.
- [ ] Surface unresolved/rehydrated counts in daily learning and dashboard
  artifacts.
- [ ] Add tests with pending rows that become model-closer, market-closer, and
  excluded partial-label cases after settlement.

Acceptance: after a market day settles, disagreement reports cannot leave
target-date rows pending when labels exist; the report names model-closer and
market-closer outcomes from final settlement; and daily learning blocks or warns
when the rehydration step is stale, missing, or inconsistent.

Related: items 41, 120, 157, 198, 262, 271, 294, 301.
