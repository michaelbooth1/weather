# Workstation handoff — 2026-07-28b: the maker has never quoted (a standing queue)

The observed-max queue is **accepted and closed**. It is three clean negatives in a row and
that is exactly what I wanted from it:

- Mission 1: 0/37 strictly readable. The archive has support in 37/37, but issuance is not
  readability and you refused to promote it.
- Mission 2: in the uncertain cohort only 10 of 347 comparable rows cross a band, **two of
  those contradict the WU winner**, and the market still wins every leave-one-date-out panel
  (`0.568883` vs `0.741867`).
- Mission 3: the authority gate activates on 0/86 and 0/38 — the projection is *identity*,
  so the floor fix I was considering would have changed nothing.

That kills the observed-max thread outright, and it settles the collector question: **no
collector change is warranted.** Gating that decision on Mission 2 was right, and you saved us
a live-source change that would have bought nothing.

**This handoff is a queue. Work in order, do not idle.**

## Where this program actually stands

Directional edge has now been eliminated three independent ways: recalibration cannot close
the gap (98.88% resolution), no slice is historically exploitable, and the one concrete
information lead is dead. I am not asking for a fourth attempt.

But look at what the decomposition actually said about the model's *shape*: reliability
contributes only **1.12%** of the gap. **We are well calibrated and unsharp.** That is a poor
directional trader and — in principle — a perfectly serviceable market maker, because maker
P&L comes from spread capture and rebates while the dominant risk, adverse selection, is a
*calibration* failure. Our weakness is the part that matters least for making markets; our
strength is the part that matters most.

So I looked at what the paper maker has actually been doing. Nine completed active runs,
`net_pnl_after_fees_incentives_usdc: 0.0`, and:

```
quote_rows                      174504
quote_legs                           0        <-- we have never quoted
blocked_fraction                   1.0
known_edge_allowed_false_rows   174504        <-- every row
known_edge_permission_blocked    63272
stale_input_blocked_rows         81961
contextual_event_gate_suppressed 61875
fill_evidence_vacuous             True   (reason: no_quote_legs)
```

**The maker has never placed a single quote in 174,504 opportunities.** The nine days of
`PASS` are vacuous — the report says so itself. And the dominant blocker is that quoting
requires a *known directional edge*, which is precisely the thing we have now proven three
times over that we do not have.

The end-goal of this platform is sitting behind a precondition the evidence says we cannot
satisfy.

## Mission 1 (first, and it may end the queue): size the prize

Before anyone unblocks anything, establish whether making markets here is worth doing at all.
Using our own captured book and trade tape, per event-day and per market: realistic spread
capture at achievable queue position, the actual maker rebate and reward pool, and realistic
filled volume. Prior live-verified economics suggested rewards on the order of **$1 per event
per day**, which across 12 markets is a very small number.

**If the honest ceiling is tens of dollars a day, say so plainly and stop.** That is a
complete and valuable answer, and it would mean the correct decision is to stop spending
engineering time on this platform's trading ambitions rather than to keep optimising toward a
prize that cannot pay for the effort. Do not let the rest of this queue talk you out of that
finding.

## Mission 2: audit the known-edge gate

Only if Mission 1 shows a prize worth chasing.

Why does quoting require a known directional edge? Find the original rationale in the code and
docs — there may be a good one, such as adverse-selection protection in thin books, and I do
not want it removed by someone who has not understood it. Then assess it against standard
market-making practice, where two-sided quoting is priced from a fair-value estimate and
protected by spread width, size limits and inventory caps rather than by requiring an edge.

Report: what the gate protects against, whether that protection is achievable another way, and
what a spread-and-rebate-only quoting policy would need in order to be safe. **Design and
argument only — do not change any trading surface.**

Also characterise the other blockers: `stale_input_blocked_rows` is 47% of rows, which looks
like an operational fault rather than a policy decision, and `contextual_event_gate` suppresses
another 35%.

## Mission 3: the counterfactual fill

Had we quoted two-sided at defensible width, what would have filled, and what would adverse
selection have cost? Use the conservative fill simulator that already exists — it reads the
real trade tape, so this is measurement rather than fantasy.

The specific hypothesis to test: **our calibration is good enough that symmetric quoting is
not systematically picked off.** If that fails, market making is as dead as the directional
track and we should know immediately. Report P&L decomposed into spread capture, rebates, and
adverse selection, so we can see which term dominates.

## Guardrails

- `data/` read-only with proven deny-write ACL; single declared output root.
- **No trading, sizing, quoting, collector, model, serving, scheduler, promotion, release or
  pointer change.** All three missions are measurement and written design.
- Topic branches only; push without asking; never master, no PRs, no merges.
- Leakage discipline unchanged. A counterfactual fill study is especially exposed to using
  post-trade information to decide fills — state the argument.
- NOT-DONE / NOT-REHEARSED first-class. A negative Mission 1 is a success, not a shortfall.

## Handback

`docs/roadmap/agent-report-<date>-workstation-mm-gate.md`: the prize sizing with explicit
magnitude, the gate audit with its original rationale, and the counterfactual fill decomposed
into spread, rebates and adverse selection. Push all topic branches.

Context: streak 6/14 expected today, earliest lock ~2026-08-03, advancing on its own. Your
observed-max report is merged (docs-only, roll-free). Master is `19385654`.
