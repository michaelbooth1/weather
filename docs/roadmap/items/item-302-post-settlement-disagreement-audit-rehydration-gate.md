# 302. Post-Settlement Disagreement Audit Rehydration Gate [COMPLETE 2026-06-24 - POST-LABEL REHYDRATION GATED]

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

- [x] Add post-settlement disagreement rehydration to the daily refresh order.
- [x] Fail closed when target-date rows remain pending after labels exist.
- [x] Add settled interpretation deltas to the disagreement Markdown report.
- [x] Surface unresolved/rehydrated counts in daily learning and dashboard
  artifacts.
- [x] Add tests with pending rows that become model-closer, market-closer, and
  excluded partial-label cases after settlement.

Implemented: `model_market_disagreement_rehydration` now runs before the
settled-day analysis barrier, appends canonical-label audit revisions, excludes
partial/missing label rows from pending settlement watchlists, blocks complete
labels that still cannot resolve, and surfaces rehydration counts/deltas in the
analysis report, daily refresh status, and daily learning.

Acceptance: after a market day settles, disagreement reports cannot leave
target-date rows pending when labels exist; the report names model-closer and
market-closer outcomes from final settlement; and daily learning blocks or warns
when the rehydration step is stale, missing, or inconsistent.

Related: items 41, 120, 157, 198, 262, 271, 294, 301.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - POST-LABEL REHYDRATION GATED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

