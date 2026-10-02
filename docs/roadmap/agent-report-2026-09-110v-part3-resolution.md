# Agent report 2026-09-110v Part 3 — owner-selected complete batches

**Verdict: PASS for fixtures; adoption after 2026-10-13 only.** The owner
resolved the sparse-token conflict by ordering complete batches on static
identity changes plus hourly refreshes. This is the final Part 3 handback,
superseding the partial verdict in [the preserved earlier report](agent-report-2026-09-110v-part3.md).
That published entry remains historical evidence, not the adoption verdict.

Branch `codex/clob-write-on-change-20260927`, based on integration
`e3bc4dc88a785e989258ac9e24b286879568d8d1`. The earlier report describes
the Gamma cache and enrichment append paths; those remain included.

## Complete batch contract

- Compare sorted complete batches on all existing non-Gamma/non-capture-time
  token columns: token, condition, market/event identity, band, outcome,
  unit/bin metadata, order-book-enabled, active/closed flags, and descriptive
  identity fields. Include observed book tick size and minimum order size in
  the comparison without adding columns to the token tape.
- Append every token with the original CSV/JSONL schemas on any identity
  change, first successful poll of each UTC hour, or local day rollover.
  Volatile Gamma changes alone do not force a batch.
- An atomic, stat-bound sidecar survives process restarts. Missing, corrupt,
  stale or incompletely committed cache state causes an extra complete batch.
  Previously existing CSV/JSONL bytes are never changed or migrated.
- Gamma discovery is cached for 600 seconds. Order books still poll at their
  configured cadence; their native prices remain independent of Gamma TTL.

## Volatile field reader inventory

Repository search covered `src/`, `app/` and `tools/` for token tape names,
token-row projections, and every `gamma_*` field. Generic archive/projection/
quality readers preserve rows; they do not interpret Gamma prices or volume.

| Fields/readers | Evidence path and retained resolution |
| --- | --- |
| `gamma_yes`, `gamma_no`, `gamma_outcome_price`, `gamma_volume`, `gamma_liquidity` | No computational field reader found. Token rows retain hourly values. These five fields are **not** in book summaries; no contrary coverage claim is made. Raw book JSONL embeds its capture token object. |
| `gamma_best_bid`, `gamma_best_ask` | `market_making_run_support.assemble_market_harvest_inputs_for_market` copies token rows then overlays current books/features. Fallback consumers are `taker_bot_tape_io.market_mid`, `taker_bot_sizing`, `taker_bot_strategy_evaluation`, `taker_bot_two_sided`, and `taker_edge_permission`. Both fields already exist in `BOOK_SUMMARY_COLUMNS` and are written by `summarize_order_book` at each book poll. |
| `gamma_last_trade_price` | `mm_paper_scoring.load_book_rows/load_mark_rows` and `taker_bot_scoring.load_mark_rows` read book summaries, not token tapes. The field already exists in book summaries at each poll. |
| Complete token groups | `market_latest_inputs`, `market_making_run_support`, `portable_live_candidate_preflight` keep their current newest-batch reader behavior. No sparse rows are introduced. |

**Separate live compatibility limitation:** portable candidate preflight
requires token age <= 600 seconds. An unchanged hourly batch fails its existing
`collector_tokens_fresh` check during much of an hour. That gate remains
intact; this handback is not live-readiness authority. A future live resumption
must address that contract explicitly. No volatile field was silently removed.

## Fixture results and expected volume

**173 tests and 22 subtests passed**, including all seven repo-wide audits
in every focused run; compileall passed. Tests cover every static key field,
tick/min size, volatile-only changes, process restart, day/hour rollover,
corrupt caches, complete groups in every hour, old-byte preservation,
CSV/JSONL row parity and poll-resolution book-summary field coverage.

The fixture simulates 20 tokens, one poll per minute, 24 hours, volatile
Gamma changes each minute, stable identity:
**28,800 rows/day before -> 480 after per tape (98.33% fewer)**.
At a constant 15-second cadence the same identity would give
115,200 -> 480 (99.58% fewer). Each distinct static change outside an hourly
refresh adds one full batch (20 fixture rows). These are fixture expectations,
not observed production volumes; outages, restarts and cache loss add batches.

## Roll and adoption

Source files `clob_token_cadence.py`, `clob_capture_cache.py`,
`market_microstructure_capture.py`, `market_microstructure_features.py`
are treated as roll-sensitive capture code/dependencies. The test file is
test-only; operations documentation, reports and correspondence index are
roll-free. Authoritative `roll_verdict.ps1` remains UNDECIDABLE locally:
the four production closure files are absent. Production must rerun it.
No venue calls, credentials, production data, scheduler changes or rollout.
Exam merge policy forbids adoption before the handoff's after-October-13 window.
