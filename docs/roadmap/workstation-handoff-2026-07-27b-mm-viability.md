# Workstation handoff — 2026-07-27b: is market making viable at all? (a standing queue)

The mm-gate queue is **accepted and closed**, and stopping at Mission 1 with
`INCONCLUSIVE_NOT_DECISION_GRADE` was correct. I asked you to size a prize; you found the
evidence was vacuous and refused to manufacture a number from a 12-trade fallback. A tidy
"$16/day ceiling" would have been worse than useless because I would have made a stop/continue
decision on it.

Your finding that the **five-contract policy sits below every observed 20/50/100 reward
minimum** is the most concrete thing to come out of that queue, and it survives regardless of
what the tape eventually shows.

## What I found on the production host afterwards

Chasing your "current trade tape is absent", the root cause is not a broken collector. It is
that `market_microstructure` has **two loops by design** — a latency-critical raw-book loop
with an explicit contract forbidding price history and WebSocket sampling, and a **separate
enrichment loop** that owns exactly those. The enrichment loop was written, given its own
status file, diagnostics, pause flag and health function, and **never registered**. It had
never run: no `clob_enrichment_status.json`, no task referencing it.

`load_trade_rows` reads exactly `trades_long.csv`, `market_trades.csv`, `market_ws_events.csv`
— and the enrichment loop writes the third. None has ever existed. I have measured it
(5.7s and 81 KB per market-iteration; widened the WebSocket sample from 1s/5msg to 20s/400msg
after the default produced 24 rows versus 806) and armed it for 01:00 tonight.

So market making now has three known blockers and **not one is model quality**: it never
quotes, its size is below every reward minimum, and there was no tape to score it with.

**This handoff is a queue. Work in order, do not idle. It deliberately needs no new data** —
everything below is answerable from code, artifacts and vendor documentation today.

## Mission 1: audit the known-edge gate

`known_edge_allowed_false_rows` is 174,504 of 174,504. Quoting is gated on possessing a known
directional edge — the thing three queues have established we do not have.

Find the original rationale in code and history before judging it. There may be a good one:
adverse-selection protection in thin books is a legitimate reason to refuse to quote, and I do
not want it removed by someone who has not understood why it is there. Then assess it against
standard practice, where two-sided quoting is priced from a fair value and protected by spread
width, size caps and inventory limits rather than by requiring an edge.

Report: what the gate protects against, whether that protection is obtainable another way, and
what a spread-and-rebate-only policy would need to be safe. Also characterise
`stale_input_blocked_rows` (47% of rows) and the contextual event gate (35%) — the first looks
like a fault rather than a policy.

## Mission 2: what would qualifying for rewards actually cost?

Our policy quotes five contracts; every observed reward minimum is 20, 50 or 100. So today we
would earn no rewards even if the gate opened.

Establish what quoting at a qualifying size implies: capital at risk per market-day, worst-case
inventory if filled on one side, and the exposure if we are wrong at settlement — using our
*own* calibration, since a binary settling against a 20–100 contract position is the real
downside. Then state what the reward pool actually pays at that size, from Polymarket's
published maker-rebate and liquidity-reward rules you already checked.

The question I want answered: **is there a size at which rewards exceed expected adverse
selection, and is the capital required proportionate?** If the honest answer is that
qualifying costs more risk than the pool pays, say so — that closes the track.

## Mission 3: will the tape I just enabled actually score?

Sharp and important. My sample contained `book` and `price_change` events and **no trade
events**. `price_change` means a book level moved; it is not a fill.

Determine from `mm_paper_scoring` whether the conservative fill simulator needs genuine trade
prints or can work from `price_change`, and whether the Polymarket market WebSocket channel
emits trade events at all. If it does not, identify what does — the Data API trades endpoint is
the obvious candidate — and specify what would need capturing.

If my deployment cannot produce a scoreable tape, I would rather learn that from you tomorrow
than discover it in a week of empty reports. **Do not change the collector**; specify.

## Guardrails

- `data/` read-only with proven deny-write ACL; single declared output root.
- **No collector, trading, sizing, quoting, model, serving, scheduler, promotion, release or
  pointer change.** All three missions are analysis and written design.
- Topic branches only; push without asking; never master, no PRs, no merges.
- NOT-DONE / NOT-REHEARSED first-class. **"Market making is not viable" is a legitimate and
  valuable conclusion** — the operator's standing position is that nothing matters until the
  model is profitable, so a well-evidenced negative that closes this track is worth more than
  a hopeful maybe.

## Handback

`docs/roadmap/agent-report-<date>-workstation-mm-viability.md`: the gate rationale and its
alternatives, the qualifying-size risk/reward with explicit magnitude, and the tape
scoreability answer. Push all topic branches.

Background if a mission stalls: the post-blend floor invariant violation is still unfixed and
remains fix-before-release (shadow rows only, no active bleed).

Context: streak 6/14 expected today, earliest lock ~2026-08-03. Master is `a77e9276`.
