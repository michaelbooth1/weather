# Workstation Safest-Bets Homepage Agent Report — 2026-07-21

## Handoff identity

- Branch: `codex/safest-bets-home`
- Worktree:
  `C:\Users\Michael\Documents\github\weather\scratch\worktrees\weather-safest-bets-home`
- Base `origin/master` commit: `d330ad97d73f18cd2bb14bd17d873b0c7735f46b`
- Implementation commit: `42a500a4`
- Report commit: pending; a commit cannot contain its own final object ID
- Push, pull request, merge, promotion, release mutation, live-trading action,
  scheduler action, and production-host action: not performed at report draft
  time

This work belongs to the development workstation. The production capture host,
its scheduled tasks, and the read-only nightly mirror remain outside the change
scope.

## Outcome and scope

This branch replaces the Streamlit overview with a paper-only homepage headed
**Safest bets right now**. The homepage is designed to answer a narrower
question than the former raw-edge view: which persisted paper-taker decisions
currently clear every conservative display gate? It is not a promise of a
winning outcome and is not a live order surface.

The work is intentionally limited to:

- a read-only reporting adapter over existing taker-run evidence;
- a new homepage presentation for a small, deduplicated shortlist;
- explicit unavailable, loading, stale, blocked, and no-bet states;
- deterministic service and Streamlit tests; and
- documentation of the operator-facing behavior.

It does not change model probabilities, calibration, market collection,
strategy evaluation, order sizing, the edge-permission map, paper ledgers,
release binding, or any live-trading permission. It does not run the taker bot
from Streamlit. The page consumes decisions already made and persisted by the
paper pipeline.

## Decision and safety contract

“Safest” is a conservative presentation policy, not a guarantee. A candidate
may appear only when the selected run and the candidate both pass the homepage
contract. If evidence is missing or ambiguous, the page shows fewer bets or no
bets; it never fills the cards with a weaker fallback.

Run-level admission requires:

- the newest discoverable run summary for the current local target date;
- a recent, parseable, complete summary in paper mode;
- passing upstream dependency, tape-integrity, and exchange-economics states;
- a locally resolved and recent taker edge-permission summary; and
- no inference from an older run when the newest file appears partial or
  malformed during synchronization.

Candidate-level admission requires an already-gated paper buy decision with a
paper fill, positive after-cost expected value, an executable price and fair
probability, an active market, fresh model and order-book inputs, an
`all_fresh` source state, allowed cadence and taker-edge permission, sufficient
independent-day evidence, and no adverse-selection or benchmark no-trade
blocker. A NO-side candidate additionally requires a fresh, depth-eligible real
NO token book; a synthetic YES-complement price is not sufficient.

Freshness is recomputed at page-load time from the persisted evaluation time;
the page does not reuse frozen evaluation-time ages. Run, permission-map, and
candidate timestamps more than 60 seconds in the future fail closed, while the
small tolerance permits ordinary workstation clock skew during synchronization.
When legacy persisted rows omit market status, they remain eligible only if the
run configuration proves that active-market enforcement was enabled upstream.

The displayed conservative win estimate is bounded by both the calibrated fair
probability and the executable fill bound for the selected side. This keeps a
real NO candidate independent of a stale YES-side implied-probability field.
Candidates are ordered by that
estimate, then after-cost expected value and evidence quality, with fresher
inputs winning deterministic ties. At most one recommendation is retained per
event so many correlated tail contracts cannot occupy the shortlist.

A price above 90% remains eligible. High price by itself is neither a reason to
include nor exclude a bet: the same positive-after-cost, evidence, freshness,
permission, and liquidity requirements apply. The displayed stake, maximum
loss, and profit-if-right are descriptions of the persisted capped paper fill,
not an instruction to trade or permission to spend real funds.

Native settlement units and the persisted market range label are preserved
end-to-end. Legacy field names ending in `_c` are not used to reinterpret a
Fahrenheit market as Celsius.

## Homepage presentation

The first viewport is intended to make the operating boundary obvious:

- paper-only and read-only status;
- the evidence refresh time and current state;
- up to three BUY YES or BUY NO cards with city/date and native range label;
- executable price, conservative win estimate, after-cost edge, capped paper
  stake, maximum loss, and profit if right;
- independent-day/sample evidence and freshness; and
- direct links to the existing market, Operations, Market Making, and History
  views for investigation.

The old orange-gradient audit wall was replaced with a restrained navy and
charcoal surface, high-contrast metrics, compact evidence cards, and clear teal
paper/read-only signals. The sidebar calls the unchanged `overview` route
**Home**. Responsive card and statistic layouts stack cleanly on narrow screens,
and the prior corrupted icon text is no longer part of the homepage.

When nothing clears the contract, the primary message is **No bets clear every
safety gate right now** with named blocker counts. Missing `data/`, a partial
copy, stale evidence, or a global gate failure receives a distinct fail-closed
state rather than an exception or an unsafe recommendation. Provenance details
remain available for audit without dominating the first screen.

## Data provenance and write boundary

The intended local inputs are repository-owned ignored runtime artifacts:

- `data/taker_runs/<target-date>/<run-id>/run_summary.json`
- `data/backtest/taker_edge_permission_map.json`

The reader resolves these paths through `weather.paths` and performs bounded,
targeted reads. It does not recursively scan the multi-million-file `data/`
tree, append to tapes or ledgers, mutate a summary, refresh permissions, or
invoke a collector or trading loop. Any production-absolute path embedded in a
copied summary is treated as provenance only; the workstation resolves the
permission artifact from its own clone.

The workstation `data/` sync was still in progress during final verification.
A read-only loader call against the main clone returned `LOADING` with blocker
`run_artifact_incomplete`: the current run folder existed, but
`data/taker_runs/2026-07-21/taker-20260721-1e563ae1/run_summary.json` was not yet
present. The loader did not fall back to an older run and no real candidate is
claimed from that incomplete copy. No production-host or mirror write was
performed. Deterministic tests use small temporary fixtures rather than
depending on ignored local data.

## Verification status

Deterministic adapter and homepage coverage passed with:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\reporting\test_safe_bets.py tests\app\test_app_overview.py
```

Result: **33 passed**. This covers 94-cent favorite eligibility, positive
after-cost value, permission and independent-day gates, stale/partial inputs,
global blockers, elapsed-time freshness, far-future timestamp rejection, fresh
real NO books, persisted native range labels and strategy-arm status,
one-per-event deduplication, deterministic ordering, READY rendering, and
fail-closed no-data states.

The combined app, adapter, and two-sided taker regression passed with:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\app tests\reporting\test_safe_bets.py tests\market\test_taker_bot_two_sided.py
```

Result: **66 passed**.

The four existing taker-policy safety tests also passed independently:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\market\test_taker_bot.py `
  -k "pre_fee_positive_edge or unpermissioned_slice or market_no_trade_precondition or budget_allocation_ranks"
```

Result: **4 passed, 77 deselected**.

Additional final-state checks:

- `python -m compileall -q app src tests`: **PASS**.
- `python -m weather.operations.agent_docs_audit`: **PASS** (18 agent files
  and 457 Markdown files).
- `git diff --check`: **PASS**.
- `python -m pytest -q tests\operations\test_import_architecture.py`:
  **21 passed** after the two new critical files were staged.
- Independent contract review after the final future-skew fix: **no actionable
  findings remain**.

Using the repository browser-control skill, the local Streamlit page was
inspected at desktop size and at 390 by 844 pixels. Both layouts had no browser
console errors. The inspection covered the real `NO_DATA` state and an isolated
three-card READY fixture containing 94% and 92% priced bets, native Fahrenheit
and Celsius labels, and a qualifying real-NO-book candidate. Cards, statistics,
badges, blocker detail, provenance, and narrow-screen stacking remained
readable. The synthetic fixture was removed afterward, and the final local page
returned to `NO_DATA`; none of those fixture bets is a real recommendation.

## Post-sync validation still required

The deterministic and visual contracts are verified. After the workstation
sync completes, the remaining validation is a targeted real-data comparison:

1. Confirm the missing current `run_summary.json` and the local permission map
   have both landed completely and recently; the loader must leave `LOADING`
   without selecting an older run.
2. Compare any resulting homepage candidates with their persisted
   `latest_orders` rows and confirm the page neither invents a candidate nor
   changes its capped paper stake.
3. Recheck the displayed freshness, real NO-book evidence, positive after-cost
   value, independent-day count, native-unit label, event deduplication, and
   provenance identifiers against those local artifacts.
4. Record the exact artifact timestamps and sync provenance here. The
   workstation copy remains best-effort evidence, not canonical production
   truth.

The production master retains ownership of review, quiet-window integration,
release decisions, and any future trading authorization. This branch remains a
read-only paper/research surface until those separate controls say otherwise.
