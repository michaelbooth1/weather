# Workstation handoff `-09-14a` — fix the watcher stretch, and check the rule it breaches

Written 2026-08-05 by the operations master agent on the production host. Read this on
`origin/master` and execute it. **This is the last unowned item on the MM critical path.**

## What is already known — do not re-diagnose it

`-09-13a` (merged `92fa5230`) found the mechanism and deliberately stopped short of repairing it,
because the complete repair is roll-sensitive:

- **One watcher breach: `152.371s` against a `120s` tolerance.**
- **Root cause: six synchronous triggered snapshots stretching a watcher iteration to `174.125s`.**
- LA's `stale_code` was **process-wide deployment drift across all 12 markets**, not an LA defect. It
  is **already resolved** — the 01:15 roll onto current code cleared it; `stale_code_market_count` is
  now `0` on all three loops. **Do not re-fix this.**
- My own `99 stale / 33 permission` framing was **wrong** — a post-window rollover tick, not the
  active window. Do not build on it.

Host state verified 2026-08-05 ~11:50 (invisible to the mirror, so take these as given):

```text
blocked_market_count     3        denver, los-angeles, miami
first_failing_gate       clob_freshness x3, useful_work_liveness x1
stale_model_market_count 0        model inputs CLEAN
max gaps                 denver 201.0s, los-angeles 151.8s, miami 207.5s   (threshold 140.1s)
age at block time        11.7s    the books were FRESH when the block was raised
```

## P1 — fix the iteration stretch

Six synchronous triggered snapshots inside one watcher iteration stretched it to `174.125s`, which
breaches the `120s` watcher tolerance and produces the >140s CLOB gaps that block markets.

Fix the stretch. The shape of the repair is yours to choose — bounding, deferring, decoupling, or
making the triggered work asynchronous — but it must satisfy:

1. **A slow or numerous triggered-snapshot batch can never stretch the watcher iteration past its
   tolerance.** Prove the bound, do not assert it.
2. **No triggered snapshot is silently dropped.** Trading latency for lost observations is not a fix.
   If work must be shed under load, it must be recorded as shed, with what and why.
3. **Reversible in one step**, and state exactly how to revert.

## P2 — check whether the rule is measuring the right window

**Do this before concluding the fix is sufficient.** `clob_freshness` blocks on the **maximum gap
across the day, not current age** — the three markets were blocked while their books were 11.7
seconds old, by gaps that had occurred hours earlier. **One ~3-minute gap poisons an entire
market-day.**

So: **were the blocking gaps even inside the MM active window (07:00–20:00 local)?**

The book audit applies its own `gap_policy` (`ignore gaps ending before …`), which suggests some
windowing already exists. **Determine whether that window is aligned with the MM active window.**

- If a gap at 05:30 local can block the 07:00–20:00 maker day, **that is a correctness defect in the
  gate**, not a tuning question, and it should be fixed on those grounds.
- If the blocking gaps genuinely fall inside the active window, **the rule is right and P1 is the
  whole fix.** Say so.

> **Do NOT loosen this gate to make the numbers look better.** Change the rule only if it is measuring
> the wrong thing, and say explicitly which of the two cases you found. This project has already been
> burned by a gate that falsely rejected a better candidate 99.885–99.9905% of the time; the opposite
> error — quietly widening a gate until days start counting — would be worse, because it would produce
> a green MM clock that means nothing. **A gate that is correct and still blocks is the right outcome.**

Also state plainly whether whole-day poisoning is the right semantics **given 12 markets and a 140.1s
threshold.** If breaching a few markets most days is the expected case rather than the exception, the
MM clock will lose markets continuously, and the operator needs to know that now rather than on day 20.

## P3 — the maker rollover repair

`-09-13a` states that **registering `WeatherMakerExecutionCapture` alone is insufficient for a
countable day**, and that the watcher **and** maker-rollover repairs must pass readiness first.
Specify and, if roll-safe, implement the rollover repair. Note the 07:05 run on 2026-08-05 was
**quarantined at 08:33** and a fresh run started — say whether that is related, expected, or a
separate defect.

## P4 — what it takes for a countable day

Give the mechanical pre-window check: what must hold, for all 12 markets, for a maker day to be free
of both `clob_freshness` and `useful_work_liveness` blocks. Expressed so it can be verified **before**
the window opens, not diagnosed after.

## Deliverable

1. P1–P4, with evidence rather than assertion.
2. **Per-file roll-safety verdicts** by import closure, not the `SOURCE_PATTERNS` glob.
3. **Exact revert instructions.**
4. An honest statement of the residual: after this fix, how many markets would still block on a
   typical day?
5. A `## What would falsify this` section.

## Constraints

**The Toronto capture streak outranks everything in this mission, without exception.** This is the
producer path the streak depends on. Do not change, restart, re-adopt, or reconfigure a running
capture loop. Build and prove the repair; **the operator applies it in a 01:00–04:00 quiet window.**

**Do not touch the release or PIT path, and do not merge.** The release #1 build runs tonight; two
roll-sensitive branches (`-09-11a`, `-09-12a`) are already queued behind it, so state clearly where
yours belongs in that order and whether it conflicts with either.

**Do not weaken the trusted observed-high floor. Do not relax the promotion gate.** The 12 markets
currently blocked on `live_trade_permission` are the promotion gate working as designed pre-release.

**Reservation:** re-based 2026-08-04, nothing reserved today, window armed but undated.
`docs/operations/reserved-confirmation-window.md` is the single source of truth; re-read it.

**Network:** `git fetch` and `git push` only. No provider calls.

Push `codex/workstation-fix-the-watcher-stretch-2026-09-14a`. **No PR, no merge.** Report to
`docs/roadmap/agent-report-2026-08-05-workstation-fix-the-watcher-stretch.md`.

## How to disagree

If the stretch cannot be bounded without risking capture coverage, **say so and stop** — the streak
is worth more than the MM clock, and a repair that trades observations for latency is not a repair. If
P2 shows the gate is simply correct and MM will keep losing markets, say that plainly; it is a
material fact about the timeline and the operator would rather have it now.
