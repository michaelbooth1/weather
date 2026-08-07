# State of play

**Last rewritten: 2026-08-06.** Read this first, then `ESTABLISHED_FINDINGS.md`.

> **REWRITTEN, never appended. Capped at ~90 lines.** The one document answering *"what is happening
> right now?"* `ESTABLISHED_FINDINGS` owns what we know, `RETRACTED_AND_FALSE_LEADS` what is false,
> `AGENT_CONTEXT` invariants, `DELEGATION_CONTRACT` how to work. **Over the cap means something
> stopped being current — cut it**; stale content here is believed rather than ignored.

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
archive window  ->  PIT corpus  ->  first retrain  ->  release #1
  DONE 1740/1740     BLOCK §4f      parity: 220        (DEFERRED)
```

**The corpus block is a FEATURE-SET decision, not a collection one** (§4f): the data exists in all
five years, but Open-Meteo serves `_previous_dayN` for only some variables. **`previous_runs=` is a
leakage trap** — it returns the settled analysis unchanged, and would pass a completeness check.

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
| `-09-29a`, `-09-31a`, `-09-32a`, `-09-34a`, `-09-36a` | chain split, seasonal ×2, severe tail, resolution | **ALL MERGED 2026-08-07** |
| `-09-37a` | **restore the settlement source** | **RETURNED, verified** — merges 01:20, roll-sensitive |
| `-09-38a` | first retrained candidate | **RETURNED: archive PASS 1,740/1,740, corpus BLOCK** (§4f) |
| `-09-39a` | close the train/serve parity gap | **RETURNED, verified: 24 unexpected → 0** |
| `-09-35a` | rotate snapshot + observation-trigger logs | written, NOT dispatched |
| `-09-33a` | season window (**contained by `-09-39a`** — merging that lands everything) | awaiting merge (**roll-sensitive**) |
| `-09-28a` | model input-surface gate | awaiting merge (roll-sensitive, additive) |
| `fix-wu-404` | scraper 404 misclassification | **SUPERSEDED by `-09-37a`** — do not merge, it conflicts |

`-09-36a` answered the resolution question: the deficit is **not uniform**, but the Los Angeles
concentration is only **6.85% of the pooled gap**, so **~93% remains uniform and unexplained**,
and no captured signal predicts it. Roll-free merges are now driven daily at 05:15 by
`WeatherMergeQueueDriver` off `C:\Users\micha\ops\merge-queue.txt` (allowlist, not auto-discovery
— several unmerged branches are held deliberately).

## Open, unowned

- **Settlement source: ROOT-CAUSED AND FIXED, awaiting merge.** The client was reading the
  history page's **advertising** `apiKey`, not the weather one — hence 404 on the ad host and
  401 on the real one. `-09-37a` reads the page's injected runtime `API_URL`/`API_KEY`; verified
  on production from an isolated worktree, including the blocking 08-05/08-06 dates. Merges
  01:20 (**roll-sensitive**). Settlement stays frozen at **2026-08-04** until it lands; the
  streak is **15/14 banked and safe**.
  [wu-settlement-source-down-2026-08-07.md](wu-settlement-source-down-2026-08-07.md).
- **Resolution / sharpness** — still the larger half of the gap; `-09-36a` localised only ~7% of
  it and found no usable signal. Nothing is aimed at the remaining ~93%.
- **Disk: production has ~11 days headroom**; the workstation is full because production `/MIR`s
  532 GB to it nightly, plus a ~55 GB non-mirrored `scratch/` tree.
  [workstation-disk-and-mirror-scope.md](workstation-disk-and-mirror-scope.md).
- **4 tests fail on master, unowned** — `test_afternoon_residual_centering`, `test_long_job_guard`
  ×2, `test_tracked_artifact_manifests_match_current_repository_identity`. `pytest -q` is red
  before you start: **diff against these four before believing your change broke something.**

## Daily reads

`data/alerts/STALENESS_SWEEP.md` (**"should this have refreshed by now?"**, 08:10) ·
`data/alerts/MORNING_BRIEFING.md` (host health) · `data/backtest/daily_refresh_report.md` (chain).
Use `scripts\ops\roll_verdict.ps1 -Branch <b>` for merge timing; **never derive it by hand.**
**Two standing alarms are expected, not incidents** — `WeatherTrainingWindow` exit **2** and the
chain's exit **1**; both proven benign in
[RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md) §3. Read it before escalating one.

## Update this file when

A decision changes, the critical path moves, or a mission returns. **Rewrite the affected
lines — do not append.** If you are adding rather than replacing, ask what became untrue.
