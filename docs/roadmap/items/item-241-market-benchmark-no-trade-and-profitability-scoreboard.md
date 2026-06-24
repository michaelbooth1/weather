# 241. Market Benchmark No-Trade And Profitability Scoreboard [COMPLETE 2026-06-22]

Goal: compare taker model decisions to market-price baselines by slice and
route to no-trade where the market is consistently smarter than the model.

Source: `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-22.md`.
June 20 evidence showed market top-winner hit rate beating model top-winner hit
rate, while tail fills and untrusted-current-high fills continued to lose.

Why this matters: the highest-EV action is often not a trade. If market prices
outperform the model in a market/hour/tail/source slice, the taker bot should
avoid donating spread and fees while collecting evidence for future repair.

## Design

1. Score model top-winner, market top-winner, traded band, and no-trade
   baselines by market, local hour, current-high distance, tail flag, and
   source state.
2. Add a no-trade router for slices where market baselines beat model edge or
   where settlement evidence is insufficient.
3. Track avoided loss, missed gain, traded PnL, and opportunity count so the
   router can be evaluated honestly.
4. Use the scoreboard to scale only slices that win after fees, across markets,
   and out of sample.

- [x] Add market-vs-model benchmark scoring to daily taker reports.
- [x] Add slice-level no-trade recommendations and blocks when market evidence
  beats model evidence.
- [x] Track avoided-loss and missed-gain metrics for no-trade decisions.
- [x] Add promotion tests requiring model edge to beat market/no-trade
  baselines after fees.

Acceptance: taker strategy reports identify market-smarter slices, block or
downsize those fills, and profitability claims show traded PnL alongside
avoided-loss and missed-gain accounting.

Follow-up hardening 2026-06-23: item 259 adds a current-run artifact verifier
that must find benchmark, avoided-loss, missed-gain, and no-trade fields before
item 241 reports can support live-profitability or promotion evidence.

Related: items 202, 214, 235, 238, 240.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

