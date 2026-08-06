# Workstation handoff `-09-11a` — make MM days countable before the first one is wasted

Written 2026-08-04 by the operations master agent on the production host. Read this on
`origin/master` and execute it. **This is the highest-priority open work.**

## The situation

The operator's directive is **weeks, not months** to a live market-making test. `-09-10a`
(`99fc5ba8`) established that the current gate cannot decide, and specified a real one. But it also
found that **the evidence needed to score a day is not being retained.**

On `2026-08-02` and `2026-08-03`, all 12 event folders retained raw and summary books, and **0 of 12**
retained `market_ws_events.csv`, `market_ws.jsonl`, `market_trades.csv`, or `trades_long.csv`.
**Books alone cannot prove a strict-through execution**, so the pessimistic fill rule — the core of
the acceptance criterion — is not computable, and both days are permanently non-countable.

The release #1 build runs imminently. The moment it produces a release pointer, promotion flips to
PASS and the maker starts quoting for the first time. **If this defect is still present then, every
day of the clock is silently uncountable, and we discover it weeks later** — the exact failure this
project keeps repeating and has now twice caught just in time.

**A day that cannot be scored cannot count. This mission makes days count.**

## AMENDED 2026-08-05 — the live payload now names the blockers, use it

This handoff was written before the chain produced a countability verdict. It now has, and it is more
specific than my original scope. **Work the named list, not my guesses.** From
`data/backtest/daily_refresh_status.json`, `summary.trading_evidence`, target day `2026-08-04`:

```text
mm_maker_countability_gate_status : BLOCK
mm_counts_toward_live_forward     : false
mm_paper_conservative_fills       : 0
mm_evidence_mode                  : post_settlement_evaluation
mm_evidence_starvation_status     : NOT_ACTIVE_DAY
mm_maker_countability_blockers    :
    evidence_mode=post_settlement_evaluation
    live_forward_gate=BLOCK
    preflight=WARN
    model_variant_bakeoff_skipped_variants=66
    quote_starvation=quote_starved_infra
    fill_evidence_completeness=BLOCK
```

**Two of these were not in my original scope and may matter more than what was:**

- **`quote_starvation=quote_starved_infra`** — the maker is quote-starved for **infrastructure**
  reasons, which is a *different* cause from the promotion block. Promotion PASS alone will not fix an
  infra starvation. Find out what `quote_starved_infra` actually means in code and what clears it.
- **`evidence_mode=post_settlement_evaluation`** — the maker is running in post-settlement evaluation
  rather than live-forward. **A post-settlement day cannot, by construction, count toward a
  live-forward gate.** Determine what selects this mode and what it takes to be in live-forward mode
  on a normal day.

Also unexplained and worth a look: **`model_variant_bakeoff_skipped_variants=66`**.

**One thing has already improved:** `mm_paper_score_freshness_status: PASS`, with
`mm_paper_latest_completed_active_day: 2026-08-04`. The maker-scoring binding fix merged in the
01:15 quiet window on 2026-08-05 (`498757fb`) and the scorer is no longer dark. That outage is closed;
do not re-solve it.

**Treat clearing these six as P0**, ahead of the priorities below — though `fill_evidence_completeness`
is the same defect as P1, and `live_forward_gate` is downstream of the others. Report each blocker's
root cause and what clears it, even where the fix is not yours to make.

## Scope, in priority order

### P1 — retain the evidence that proves a strict-through fill

Determine exactly why the execution tapes are absent on 08-02/08-03 — not written, written and
pruned, disabled by config, or never wired for the paper path — and repair it so that **every future
event-day retains what the pessimistic fill rule needs.**

State the root cause explicitly. If retention is a config default rather than a code path, say so;
the fix may be operational rather than a merge.

**Verify by construction, not by inspection:** show a day-shaped case where a strict-through fill is
provable end to end from retained artifacts alone.

### P2 — fix the silent horizon fallback

`compute_fill_financials` uses settlement when present and **falls back to 30m otherwise**. That is a
horizon mixture inside the scorer, and `-09-10a` established **settlement P&L as primary, with the
30-minute mark as a toxicity diagnostic only.**

Make the horizon **explicit and recorded per fill.** A missing settlement must produce an explicit
`NOT_COUNTABLE` or a clearly labelled provisional value — never a silent substitution that looks like
an acceptance number.

### P3 — build the reward Q-share denominator

`-09-10a` found this **evidence-capable but endpoint-not-ready**: full-depth `order_books.jsonl`
retains competitor levels and size, so an exact sampled Q denominator can be built. Today's number is
a scalar proxy from a CLOB-recon suggestion, flagged `COUNTERFACTUAL_ONLY` /
`does_not_change_pnl=True`.

Build the real sampled denominator. If it cannot be built exactly, say precisely what is missing
rather than shipping a better-looking proxy.

### P4 — implement the countability checklist mechanically

`-09-10a` specified a day-one checklist. Implement it so a date **emits `NOT_COUNTABLE` with the exact
blocker** rather than silently producing a number. This is what converts the gate from a document
into something that cannot be accidentally passed.

It must be impossible for a day to appear countable when its execution tape is missing.

## Sizing — assume `$25 / tier 20`

Per `-09-10a`, `$25/tier-20` needs **22 countable dates** under the date-shock envelope versus **43**
for `$50/tier-50`, because its dispersion-to-mean is far better. **Design and validate for
`$25/tier-20`.** Do not change live sizing config in this mission — flag anything that needs changing
and leave it to the operator.

## What this mission must NOT do

**No live orders, no keys, no wallet, no provider calls, no trading of any kind.**

**Do not touch the release or PIT path.** The release #1 build runs on the production host during
this window; a collision there is far more expensive than a day's delay here.

**Do not relax the promotion gate.** Allowing `harvest_only` rows through `promotion_state: BLOCK` in
paper mode remains an explicit operator decision with a code change, and is **not** delegated here.
You may analyse it; do not implement it.

> **AMENDED 2026-08-04 — the reservation was re-based and NOTHING is reserved today.** This handoff
> originally told you to assume `2026-08-06 → 2026-11-03` stands. The operator re-based it on
> 2026-08-04: the window is armed but undated and begins only when the first retrain candidate is
> frozen. **The MM clock is no longer blocked**, which is precisely why this mission is now the
> critical path.

**`docs/operations/reserved-confirmation-window.md` remains the single source of truth and outranks
this document — re-read it when you run.** If a window has been declared there by then it is
absolute, and note rule 4: **MM paper scoring must stop on declared confirmation dates and does not
inherit an exemption.**

**Roll-safety matters.** Anything inside the capture loops' loaded-module closure rolls all three
loops and must land in a 01:00–04:00 quiet window. **State plainly, per file, whether your change is
roll-free or roll-sensitive**, using the import-closure method — not the `SOURCE_PATTERNS` glob.
Getting this wrong risks the Toronto streak, which outranks MM evidence.

**Network:** `git fetch` and `git push` only.

Push `codex/workstation-make-mm-days-countable-2026-09-11a`. **No PR, no merge.** Report to
`docs/roadmap/agent-report-2026-08-05-workstation-make-mm-days-countable.md`.

## Deliverable

1. Root cause of the missing execution tapes, stated plainly.
2. The repair, with a constructive proof that a strict-through fill is now provable from retained
   artifacts alone.
3. P2–P4 as above.
4. **A per-file roll-safety verdict.**
5. **What must be true on the first post-PASS day for it to count** — the operational payload.
6. A `## What would falsify this` section.

## How to disagree

If the tapes are absent for a reason that cannot be repaired before the build, **say so immediately
and prominently** — that changes the operator's plan, and a late discovery is far worse than an
inconvenient early one. If some acceptance input simply cannot be made countable, name it and say
what the gate should do instead.
