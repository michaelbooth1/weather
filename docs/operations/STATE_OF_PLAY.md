# State of play

**Last rewritten: 2026-08-06.** Read this first, then `ESTABLISHED_FINDINGS.md`.

> **REWRITTEN, never appended. Capped at ~90 lines.** The one document answering *"what is
> happening right now?"* — the question the rest of the canon does not. `ESTABLISHED_FINDINGS`
> owns what we know, `RETRACTED_AND_FALSE_LEADS` what is false, `AGENT_CONTEXT` invariants,
> `DELEGATION_CONTRACT` how to work. **Over the cap means something stopped being current — cut
> it.** Stale content here is worse than none: it will be believed.

**Objectives:** 1. protect the Toronto capture streak · 2. **find a model that beats the market —
we do not** · 3. the market-making bot is the end goal.

## Where the model actually stands

**The cool bias is seasonal coverage** (`-09-31a`, §2): base HGB centre−settlement is **−0.1848**
in-season vs **−1.0193** out, contrast **−0.8346 [−1.4378, −0.2159]** at 83.17% power, while the
market's contrast is **flat** (−0.0057, spans zero). So it is not the weather.

The archive holds **May 10 – Jun 30 only, every year**. It is August, so **every date we serve is
out-of-season**, and the first retrain blocks at **0 / 12,600 cells**.

**But the gap does not vanish in-season** (`-09-34a`, §4e): served in-season is
**1.4233x [1.2428, 1.6589]** — excludes 1.0. Nearly unbiased, still losing, on a **resolution**
deficit. The seasonal contrast is **not powered**; no direction may be claimed.

**So bias and sharpness are separate problems and we have a fix for one.** The retrain is
**necessary, not sufficient.** Do not promise it will close the gap. Do not cite a Brier or P&L
gain from it — the severity-tail contrast is underpowered too (47.65%).

## The critical path

```
extend the archive season window  ->  stage the PIT corpus  ->  first retrain  ->  release #1
        (-09-33a, awaiting merge)      (0/60 units today)      (-09-20a lane)
```

That path fixes the **centre** (74.97% of oracle excess loss). **Nothing is yet aimed at
resolution**, which §1 says recalibration cannot supply. That is the open strategic gap.

## Decided — do not relitigate without new evidence

- **Release #1 is DEFERRED** until a retrained candidate exists
  ([why](release-one-deferred-until-a-retrained-candidate.md)) — it would freeze artifacts
  measured a full degree cool on the dates we serve. The lock does **not** expire; the 7-day rule
  is rolling source recency.
- **Free-tier Open-Meteo only, no paid API. Training population 2021–2025.** Closed; **do not
  stop a mission on either.**
- **Nothing is reserved today**; the window arms at candidate freeze.
  `reserved-confirmation-window.md` wins over every other document.

## Do not redo these — they are answered

- **The free-source "blindness" repair is NO-GO** (`-09-26a`, §4b). Pooled Brier crosses zero.
- **Release #1 is not sufficient for promotion** — the early-hour Brier gate refuses
  independently. Whether it is *necessary* is **unestablished** (§9).
- **Do not tune the severe-tail band-suppression lever before the retrain** (§4d) — today's
  model/market disagreement is substantially the cool bias itself.

## In flight

| Ref | What | State |
| --- | --- | --- |
| `-09-35a` | rotate snapshot + observation-trigger logs | **next to dispatch** |
| `-09-33a` +`-09-20a` | season window + retrain lane | awaiting merge (**roll-sensitive**) |
| `-09-28a` | model input-surface gate | awaiting merge (roll-sensitive, additive) |
| `fix-wu-404` | scraper 404 misclassification | awaiting merge (roll-sensitive) |
| `-09-29a`, `-09-31a`, `-09-32a`, `-09-34a` | chain split, seasonal ×2, severe-tail | awaiting merge (roll-free) |

**No mission is running.** The unowned strategic question is **resolution/sharpness** — nothing
addresses it, and it is now the larger half of the gap.

## Open, unowned

- **Resolution / sharpness** — the larger half of the gap, nothing aimed at it. See above.
- **`clob_enrichment` closure dormant ~10 days**, no task drives it; nobody has asked whether it
  should run. Watched at CRITICAL by the staleness sweep.
- **`daily_learning` + market-beating scoreboard dead since 2026-07-10**, unreachable past the
  settled-day barrier. `-09-29a` fixes reachability on merge.
- **Disk: production has ~11 days headroom** (123.8 GB free, ~10.9 GB/day). The workstation is
  full because production `/MIR`s 532 GB to it nightly. Sealing/tiering is blocked by the *same*
  barrier — `-09-29a` unblocks both.
  [workstation-disk-and-mirror-scope.md](workstation-disk-and-mirror-scope.md).

## Daily reads

`data/alerts/STALENESS_SWEEP.md` (**"should this have refreshed by now?"**, 08:10) ·
`data/alerts/MORNING_BRIEFING.md` (host health) · `data/backtest/daily_refresh_report.md` (chain).

Use `scripts\ops\roll_verdict.ps1 -Branch <b>` for merge timing. **Never derive it by hand.**

## Update this file when

A decision changes, the critical path moves, or a mission returns. **Rewrite the affected
lines — do not append.** If you are adding rather than replacing, ask what became untrue.
