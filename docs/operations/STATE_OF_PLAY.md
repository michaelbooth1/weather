# State of play

**Last rewritten: 2026-08-06.** Read this first, then `ESTABLISHED_FINDINGS.md`.

> **REWRITTEN, never appended. Capped at ~90 lines.** The one document answering *"what is happening
> right now?"* `ESTABLISHED_FINDINGS` owns what we know, `RETRACTED_AND_FALSE_LEADS` what is false,
> `AGENT_CONTEXT` invariants, `DELEGATION_CONTRACT` how to work. **Over the cap means something
> stopped being current — cut it.** Stale content here is worse than none: it will be believed.

**Objectives:** 1. protect the Toronto capture streak · 2. **find a model that beats the market —
we do not** · 3. the market-making bot is the end goal.

## Where the model actually stands

**The cool bias is seasonal coverage, not the weather** (`-09-31a`, §2). The archive holds
**May 10 – Jun 30 only, every year**, so in August **every date we serve is out-of-season** and the
first retrain blocks at **0 / 12,600 cells**.

**But the gap does not vanish in-season** (`-09-34a`, §4e): served in-season **1.4233x, excluding
1.0** — nearly unbiased, still losing, on a **resolution** deficit. The seasonal contrast itself is
**not powered**; claim no direction from it.

**So bias and sharpness are separate problems and we have a fix for one** — the critical path:

```
extend the archive season window  ->  stage the PIT corpus  ->  first retrain  ->  release #1
        (-09-33a, awaiting merge)      (0/60 units today)      (-09-20a lane)      (DEFERRED)
```

That fixes the **centre** (74.97% of oracle excess loss); **nothing is aimed at resolution**, which
§1 says recalibration cannot supply. So the retrain is **necessary, not sufficient**: promise no gap
closure and cite no Brier or P&L gain. Intervals and power live in §2 / §4d / §4e — **cite them
from there, never from here.**

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

- **The free-source "blindness" repair is NO-GO** (`-09-26a`, §4b).
- **Release #1 is not sufficient for promotion**; whether it is *necessary* is unestablished (§9).
- **Do not tune the severe-tail band-suppression lever before the retrain** (§4d).

## In flight

| Ref | What | State |
| --- | --- | --- |
| `-09-36a` | localise the market's resolution advantage | **written, NOT dispatched** |
| `-09-35a` | rotate snapshot + observation-trigger logs | **written, NOT dispatched** |
| `-09-29a`, `-09-31a`, `-09-32a`, `-09-34a` | chain split, seasonal ×2, severe-tail | **ROLL-FREE — mergeable at any hour** |
| `-09-33a` +`-09-20a` | season window + retrain lane | awaiting merge (**roll-sensitive**) |
| `-09-28a` | model input-surface gate | awaiting merge (roll-sensitive, additive) |
| `fix-wu-404` | scraper 404 misclassification | awaiting merge (roll-sensitive) |

**No mission is running**, and neither handoff has a branch on origin — by
[mission-dispatch-reconciliation.md](mission-dispatch-reconciliation.md) both are *never dispatched*.
Relay one before writing a third. **And nothing is scheduled to merge anything:**
`WeatherQuietWindowMerge{,2,3}` last ran 2026-08-01 with no next run, so for the four roll-free
branches "mergeable at any hour" has quietly meant *never merged*.

## Open, unowned

- **Resolution / sharpness** — the larger half of the gap. `-09-36a` is written to attack it and
  is sitting undispatched.
- **`daily_learning` + market-beating scoreboard dead 27.9 days** (since 2026-07-10) — objective
  #2's own scorecard, unreachable past the settled-day barrier.
- **Disk: production has ~11 days headroom** (123.4 GB free, ~10.9 GB/day); the workstation is full
  because production `/MIR`s 532 GB to it nightly. Sealing/tiering is blocked by the *same* barrier.
  [workstation-disk-and-mirror-scope.md](workstation-disk-and-mirror-scope.md).
- **Settlement is 2 days behind** (latest 2026-08-04). The 08-06 chain fetched **0 of 12** — the
  WU-404 trap, where a plain resume fetches nothing. `WeatherChainRecovery20260807` is armed for
  01:30 with `-Refetch`, the only form that fetches at all.

**`-09-29a` is one roll-free merge and it clears the middle two.**

## Daily reads

`data/alerts/STALENESS_SWEEP.md` (**"should this have refreshed by now?"**, 08:10) ·
`data/alerts/MORNING_BRIEFING.md` (host health) · `data/backtest/daily_refresh_report.md` (chain).
Use `scripts\ops\roll_verdict.ps1 -Branch <b>` for merge timing; **never derive it by hand.**

**Three standing alarms are expected, not incidents:** the `clob_enrichment` CRITICAL,
`WeatherTrainingWindow` exit **2**, the chain's exit **1**. Proven benign in
[RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md) §3 — read it before escalating one.

## Update this file when

A decision changes, the critical path moves, or a mission returns. **Rewrite the affected
lines — do not append.** If you are adding rather than replacing, ask what became untrue.
