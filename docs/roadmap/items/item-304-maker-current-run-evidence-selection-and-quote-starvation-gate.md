# 304. Maker Current-Run Evidence Selection And Quote-Starvation Gate [COMPLETE 2026-06-24 - TRADING EVIDENCE SELECTS TARGET-DATE RUNS AND GATES QUOTE STARVATION]

Goal: make maker trading evidence select the latest countable target-date runs
and explicitly flag quote-starvation by gate before maker evidence is considered
healthy.

Source: settled 2026-06-23 log audit. June 23 maker proof runs eventually passed
preflight and live gates, but produced zero fills and only a few quote-permission
rows. Most quote intents were blocked by known-edge permission, missing book,
stale input, stale book, or snapshot cadence gates. The standard trading
evidence report still referenced stale older maker evidence instead of the June
23 countable proof runs.

Why this matters: passing the live gate is not enough if the policy never quotes
or the evidence report picks the wrong run. The maker bot can be operationally
safe while still producing no market evidence, and a stale evidence selector can
make that invisible to the daily analysis.

Why it is not already covered: item 260 checks maker paper-score freshness and
items 277 through 280 cover liveness, variant bakeoff, clustered gates, and fill
completeness. They do not require trading evidence to select the latest
target-date countable proof folders, nor do they define a daily
quote-starvation gate that separates valid no-edge abstention from stale/missing
book infrastructure.

## Design

1. Update trading evidence selection to discover latest target-date maker runs
   that passed preflight/live gates and prefer those over stale older reports.
2. Add a quote-starvation summary with quote-permission rows, fills,
   markets-covered, total intents, and top blocking gates by reason category.
3. Classify maker days as `countable_with_quotes`, `risk_clean_no_edge`,
   `quote_starved_policy`, `quote_starved_infra`, or `stale_evidence`.
4. Make daily learning block maker evidence countability when latest countable
   proof runs are not selected or quote starvation is unexplained.
5. Carry model-variant bakeoff skips, such as missing probability columns, into
   the maker evidence report so variant evidence cannot look complete when it is
   partly skipped.

- [x] Repair maker trading-evidence run selection for target-date countable
  proof folders.
- [x] Add quote-starvation metrics and blocker taxonomy to maker reports.
- [x] Add maker-day classification for no-quote/no-fill outcomes.
- [x] Surface variant-bakeoff skipped-variant counts in trading evidence.
- [x] Add tests with fresh proof runs, stale report selection, policy
  starvation, and infrastructure starvation.

Acceptance: maker trading evidence covers the latest countable target-date maker
runs, reports quote-starvation by gate, classifies no-fill days by policy versus
infrastructure cause, and fails closed when stale older runs are selected or
variant bakeoff evidence is incomplete.

Related: items 44, 57, 210, 211, 260, 277, 278, 279, 280, 282, 294.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - TRADING EVIDENCE SELECTS TARGET-DATE RUNS AND GATES QUOTE STARVATION`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

