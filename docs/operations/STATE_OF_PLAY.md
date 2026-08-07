# State of play

**Last rewritten: 2026-08-06.** Read this first, then `ESTABLISHED_FINDINGS.md`.

> **This file is REWRITTEN, never appended, and capped at ~90 lines.** It is the one document
> that answers *"what is happening right now?"* — the question the rest of the canon does not.
> `ESTABLISHED_FINDINGS.md` owns what we know, `RETRACTED_AND_FALSE_LEADS.md` what is false,
> `AGENT_CONTEXT.md` invariants, `DELEGATION_CONTRACT.md` how to work. **If this file no longer
> fits in 90 lines, something in it has stopped being current — cut it, do not extend the cap.**
> Stale content here is worse than none: it will be believed.

## The objective

1. Protect the Toronto capture streak. 2. **Find a model that beats the market — we do not.**
3. The end goal is the market-making bot.

## Where the model actually stands

**The cool bias is seasonal coverage, and in-season the model is nearly fine.** Measured
2026-08-06 (`-09-31a`), base HGB, both strata out-of-sample, crossed date × market:

| | In-season | Out-of-season | Contrast |
| --- | ---: | ---: | --- |
| Base HGB centre − settlement | **−0.1848** | **−1.0193** | **−0.8346 [−1.4378, −0.2159]**, power 83.17% |
| Market | +0.0699 | +0.0642 | −0.0057 [−0.1643, +0.1520] — **flat** |

The forecast archive holds **May 10 – Jun 30 only, in every year**. It is August, so **every date
we serve is out-of-season**, and the first retrain blocks at **0 / 12,600 cells**.

**Not established:** that fixing this improves the loss. The severity-tail contrast is
underpowered (47.65%, interval crosses zero). **Do not cite a Brier or P&L gain.**

## The critical path

```
extend the archive season window  ->  stage the PIT corpus  ->  first retrain  ->  release #1
        (-09-33a, awaiting merge)      (0/60 units today)      (-09-20a lane)
```

Everything else is beside this path, not on it.

## Decided — do not relitigate without new evidence

- **Release #1 is DEFERRED** until a retrained candidate exists.
  [release-one-deferred-until-a-retrained-candidate.md](release-one-deferred-until-a-retrained-candidate.md).
  It freezes artifacts measured a full degree cool on exactly the dates we serve. The lock does
  **not** expire — the 7-day rule is rolling source recency, not a countdown.
- **Free-tier Open-Meteo only, no paid API. Training population 2021–2025.** Closed decisions;
  **do not stop a mission on either.**
- **Nothing is reserved today.** The confirmation window arms at candidate freeze.
  `reserved-confirmation-window.md` wins over every other document.

## Do not redo these — they are answered

- **The free-source "blindness" repair is NO-GO** (`-09-26a`): severe SSE 6.7395%
  [0.5208%, 14.3964%], pooled Brier −0.000721 crossing zero, fields present in 8.90% of snapshots.
- **Release #1 is not sufficient for promotion** — the early-hour Brier gate refuses
  independently (0.0205 vs 0.0030, all 12 markets). Whether it is *necessary* is **unestablished**.
- **Do not tune the severe-tail band-suppression lever before the retrain** (§4d) — today's
  model/market disagreement is substantially the cool bias itself.

## In flight

| Ref | What | State |
| --- | --- | --- |
| `-09-34a` | is the market gap itself seasonal? | **running** |
| `-09-35a` | rotate snapshot + observation-trigger logs | queued |
| `-09-33a` +`-09-20a` | season window + retrain lane | awaiting merge (**roll-sensitive**) |
| `-09-28a` | model input-surface gate | awaiting merge (roll-sensitive, additive) |
| `fix-wu-404` | scraper 404 misclassification | awaiting merge (roll-sensitive) |
| `-09-29a`, `-09-31a`, `-09-32a` | chain split, seasonal, severe-tail | awaiting merge (roll-free) |

## Open, unowned

- **`clob_enrichment` closure dormant ~10 days**, no scheduled task drives it. Watched at
  CRITICAL by the staleness sweep; nobody has asked whether it *should* run.
- **~2.7 GB of unrotated active logs** on snapshot and observation-trigger (`-09-35a` fixes).
- **`daily_learning` + market-beating scoreboard dead since 2026-07-10** — unreachable past the
  settled-day barrier. `-09-29a` fixes reachability.

## Daily reads

`data/alerts/MORNING_BRIEFING.md` (host health, every 15 min) ·
`data/alerts/STALENESS_SWEEP.md` (**"should this have refreshed by now?"**, daily 08:10) ·
`data/backtest/daily_refresh_report.md` (the chain).

Use `scripts\ops\roll_verdict.ps1 -Branch <b>` for merge timing. **Never derive it by hand.**

## Update this file when

A decision changes, the critical path moves, or a mission returns. **Rewrite the affected
lines — do not append.** If you are adding rather than replacing, ask what became untrue.
