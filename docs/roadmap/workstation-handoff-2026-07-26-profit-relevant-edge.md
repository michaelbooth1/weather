# Workstation handoff — 2026-07-26: from Brier gap to profit (a standing queue)

The skill-gap queue is **accepted and closed**. The decomposition is exactly what I asked
for: it answers *what kind of problem this is* rather than chasing a number, and the answer —
98.88% resolution, 1.12% reliability — retires global recalibration as a strategy. The
Mission 3 NOT-DONE was the right call; refusing to weaken the lock rather than manufacture
evidence is the standard. The v0.2 → v0.3 memory-proof disclosure, where you preserved a
failed proof instead of relabelling it, is why I can act on your findings without re-deriving
them.

The seven fixture isolations are validated here: the suite goes from 13 failures to 2, and
both survivors (`test_long_job_guard`, `STATUS_ACCESS_VIOLATION`) already failed beforehand.
You also fixed a latent bug I had missed — the app-architecture ratchet's empty alternation
matching every import. Merge is clean; it lands in tonight's quiet window because
`schema_registry_recent_data.py` is loaded by both capture loops.

**This handoff is a queue. Work the missions in order and do not idle.**

## The reframe: a Brier gap is not a profit opportunity

Operator direction, verbatim in spirit: **nothing matters until the model is profitable.**
That changes how your own result should be read, and it is the reason this queue exists.

Your hour cuts show the widest gap by far is evening lock-in — hour 20 at `0.048180`, 58.30%
of available uncertainty, with market Brier at roughly `0.000001`. It is tempting to treat
that as the biggest prize. It is not, and the distinction is the whole point of Mission 1:

- Where **market Brier is ~0**, the market is already right and prices sit near 0/1. Closing
  our gap there earns **nothing** — there is no mispricing to trade against. What it does
  mean is that our model emits confident *wrong* signals late in the day, which is a
  **loss-avoidance** problem: a taker acting on them bleeds money. We have already paid for
  this once (settled-day taker loss of -66.99).
- Where **the market is genuinely uncertain** and we could hold better information, that is
  the only place profit can come from — and by your own numbers those are the *narrowest*
  gaps (predawn `0.016349`, primary 09:00–14:00 `0.016020`).

So the ranking by Brier and the ranking by money are close to inverted. Establish the second
one.

## Mission 1 (primary): where is there tradeable edge, and where are we merely wrong?

Same frozen corpus and repaired code as your decomposition. No fitting, no tuning.

1. **Stratify by market uncertainty, not by hour.** Bucket partitions by the market's own
   entropy / distance from 0-1. For each bucket report both models' Brier *and* the
   population weight. I expect the evening loss to concentrate almost entirely in
   near-resolved buckets; show whether that is true.
2. **Convert the gap into expected P&L.** For each bucket and hour, compute what a simple
   price-taking rule acting on our model's disagreement with the market would have earned or
   lost, at realistic fees (5% taker, 25% maker rebate — see MARKET_MAKING_PLAN.md). This is
   a *measurement over settled history*, not a backtest of a strategy we intend to run, and
   it must consume no opened-window outcomes. The question is only: **does our disagreement
   with the market have positive expected value anywhere, and where?**
3. **Quantify the evening as a liability.** How much would a naive taker have lost acting on
   our hour-18-to-23 signals? That number sizes the guardrail.
4. **Name the exploitable subset, if one exists.** Market-uncertain, model-informed,
   sufficiently populated to matter. If no subset has positive expected value, **say so
   plainly** — that is a legitimate and important finding, and it would mean the honest next
   step is information work, not deployment.

Deliverable: a ranking of where money is, alongside your existing ranking of where error is.

## Mission 2: why does the model ignore the day it has already seen?

By 20:00 the day's high is largely realized and the market prices it as settled. We do not.
That is a specific, findable defect rather than a vague deficit.

Trace what the model actually consumes at hour 20 versus what exists: is the current-high
trajectory fed in at all, is it stale, is it clipped, does the climatology prior keep
dominating? Your own decomposition named model spread / source reliability, current-high
trajectory, and observation history as the missing information — start there. I want a
**diagnosis with evidence**, not a fix: identify the mechanism and show it, then stop. If it
is a bug rather than missing information, that is the best possible outcome and worth saying
loudly.

## Mission 3: preregister before you build anything

If Missions 1 and 2 point to a concrete information candidate, **preregister it before
touching a model**: the hypothesis, the cut it should improve, the leakage argument, and an
untouched confirmation window. Do not fit it in this mission.

Standing rule, unchanged and non-negotiable: any large improvement is a leakage suspect
first. Item 224 was label leakage; your own 31,092-day cutoff bug was caught the same way.

## Guardrails

- `data/` strictly read-only with a proven deny-write ACL; single declared output root.
- No promotion, release, pointer, activation, serving, scheduler, collector, sizing, or
  trading-surface change. The 2026-07-25 `promotion_refresh` authorization is **spent**.
- Topic branches only; never push master; no PRs, no merges. Merge timing stays with me.
- Rebase on current master before any merge-readiness claim.
- Backups, durability and tape are **out of scope by operator direction** until the model is
  profitable. Do not propose work there.
- NOT-DONE and NOT-REHEARSED lists stay first-class.

## Background, only if a mission stalls

The two `test_long_job_guard` failures are pre-existing and Windows-specific
(`STATUS_ACCESS_VIOLATION`, exit `3221225540`). Low priority — they block nothing — but they
are the last red tests on master once your branch lands.

## Handback

`docs/roadmap/agent-report-<date>-workstation-profit-edge.md` on your topic branch: the
uncertainty-stratified table, the expected-P&L ranking, the evening liability number, the
named exploitable subset or an explicit statement that none exists, plus the Mission 2
diagnosis. Push all topic branches.

Context: streak is 4/14, earliest lock ~2026-08-03, and it advances on its own without
competing for your time. Nothing here is on the lock's critical path — spend the time on
depth.
