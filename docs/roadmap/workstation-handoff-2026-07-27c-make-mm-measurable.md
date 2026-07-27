# Workstation handoff — 2026-07-27c: make market making measurable (a standing queue)

Your viability audit is **accepted**, and the operator has read it and chosen **not** to close
the track yet. The decision is: *make market making measurable, then re-decide.*

That is a direct consequence of your own report. Of the four legs of the `NOT_VIABLE` verdict,
three are established facts — the $19.60 requirement against a $10 cap, competition-normalized
rewards, and rebates too small to carry viability alone. The fourth, **passive-fill adverse
selection, is not a finding at all: it is unidentified**. It is the dominant cost term in any
market-making business, and we currently cannot measure it. A verdict resting partly on an
unmeasured term is worth converting into one that does not.

Two of your findings make that tractable:

- The market WebSocket **does** emit genuine `last_trade_price` executions. The source exists.
- The scorer is what is unsafe: it admits `price_change` rows, duplicates raw and CSV
  messages, and loses execution identity and exchange time.

Also note: the $10 `max_band_notional` is a **software policy default**, not an exchange or
account limit — alongside `quote_size: 5.0`, `max_event_notional: 25.0`,
`max_daily_loss: 25.0`. The cap is a choice we can revisit once the risk is quantified.

**This handoff is a queue. Work in order, do not idle.**

## Prerequisite: fix your Python environment first

You reported `mm_paper` could not collect because the project Python is missing and its
CPython 3.11 NumPy/Pandas wheels are incompatible with a 3.12 fallback. Mission 3 needs the
fill simulator to run, so resolve this before Mission 3 and **state how you resolved it**. If
it cannot be resolved on your host, say so early rather than at the end.

## Mission 1: can we get historical trades without changing the collector?

The obvious approach is to capture trades going forward, which means waiting weeks and
changing a live collector. Check the cheaper path first: **Polymarket's Data API trades
endpoint is historical.** If it serves per-market trade history for already-settled days, we
can reconstruct the tape retrospectively and measure adverse selection against days we already
have books, quotes and settlements for — immediately, with no collector change and no waiting.

Establish: what the endpoint returns, whether it covers our settled corpus, its retention
horizon, rate limits, and whether each record carries **execution identity, exchange
timestamp, price, size, side and token**. Then backfill a bounded corpus into your own output
root — start with a handful of market-days, not everything.

If historical trades are not retrievable, say so; then forward capture is the only route and I
will take the collector decision.

## Mission 2: make the tape scoreable

Fix what you diagnosed. The scorer must admit **only genuine executions**, deduplicate raw
versus CSV representations, and preserve execution identity and exchange time. A fill
simulation built on `price_change` rows is not conservative, it is wrong.

Do this as a candidate on your branch with tests, including a case proving `price_change` rows
are rejected and a case proving duplicate raw/CSV messages collapse to one execution. Do not
change any collector or trading surface.

## Mission 3: measure adverse selection, then re-run viability

The point of the whole queue.

Using the repaired scorer and the backfilled tape, answer: **had we quoted passively at
defensible width, what would fills have cost us in adverse selection?** Decompose P&L into
spread capture, maker rebates, and adverse selection, so we can see which term dominates
rather than only the net.

Then re-run viability across a **range of band caps** — at least $10, $25 and $50 — rather
than assuming one. For each: capital at risk, worst-case inventory, expected reward share
given competition normalization, and net after adverse selection. The specific hypothesis to
test is the one that motivated this whole line: **our reliability is only 1.12% of the
model-market gap, so we are well calibrated; is that calibration good enough that symmetric
passive quoting is not systematically picked off?**

If adverse selection swamps rebates and spread at every cap, market making is closed on
measured evidence rather than an unmeasured term, and you should say so plainly. That is the
outcome this queue exists to make possible.

## Guardrails

- `data/` read-only with proven deny-write ACL; single declared output root.
- **No collector, trading, sizing, quoting, serving, scheduler, promotion, release or pointer
  change.** Scorer work is a candidate on your branch. The collector decision is mine.
- Topic branches only; push without asking; never master, no PRs, no merges.
- Leakage discipline: a fill simulation is unusually exposed to deciding fills using
  information that postdates the quote. State the argument explicitly.
- NOT-DONE / NOT-REHEARSED first-class. A measured negative closes the track honestly and is
  a success.

## Handback

`docs/roadmap/agent-report-<date>-workstation-mm-measurable.md`: the Data API assessment and
what you backfilled, the scorer fix with its tests, and the adverse-selection decomposition
with the viability re-run across band caps. Push all topic branches.

Context: streak 6/14 as of today, earliest lock ~2026-08-03. Master is `0f0b18a9`; your
viability report is merged (docs-only). The enrichment loop I had armed is disarmed — it would
have produced volume without evidence, exactly as your Mission 3 predicted.
