# State of play

**Last rewritten: 2026-08-08 (evening audit).** Read this first, then `ESTABLISHED_FINDINGS.md`.

> **REWRITTEN, never appended. Capped at ~90 lines.** Answers *"what is happening right now?"* —
> **not what we know.** `ESTABLISHED_FINDINGS` owns findings and every interval ·
> `RETRACTED_AND_FALSE_LEADS` what is false · `OPEN_BACKLOG` what is unowned · `AGENT_CONTEXT`
> invariants · `DELEGATION_CONTRACT` how to work. **Cite numbers from §-references, not this page.**

**Objectives:** 1. protect the Toronto capture streak · 2. **find a model that beats the market — we
do not** · 3. the market-making bot is the end goal.

## Four clocks, none of them running

The through-line, and the shape to distrust everywhere: **a stopped counter looks identical to a
satisfied one.**

| Clock | Reads | Actually |
| --- | --- | --- |
| Capture streak | **15 / 14 FULL** | ends **2026-08-04**. The 4 days since are unsettled; 08-07 (41 min) and 08-08 (20 min) carry in-window gaps projecting to **partial**. Banked 15 is safe; not advancing. |
| MM countable days | counter ticks | **7 of 55**, last counted **2026-07-12** (§8b) |
| Archive coverage | `fleet-coverage` **OK 12/12** | covers **05-10 → 06-30 only** — zero rows for any August target |
| Execution-tape days | *no counter exists* | **never started** (§8c). The only route to `f`, and it accrues only in calendar time. |

## THE critical path: extend the archive. It becomes actionable tomorrow.

The archive holds **52 month-days per year and zero July/August rows in any year**, and every served
HGB was fitted 2026-06-10..13 on it. **`-09-33a` (inside tonight's `-09-43a` merge) deletes
`SEASON_START`/`SEASON_END`** for `archive_window_for_target(target_date, ...)`.

**The merge makes the fetch possible; it does not perform it.** The manifest keeps its May–June rows
until someone runs `python -m weather.sources.forecast_history backfill --target-date <d>` —
**~60 free-tier calls**, ~1s each, already permitted by policy.

> **Highest-value action available tomorrow; nothing else competes.** Not blocked on a decision, a
> measurement, a mission, or the market. **The first retrain cannot run until it is done.**

Causation is **inference, not measurement** — that the cool bias is *caused* by the season window was
never traced through row selection ([detail](the-season-window-blocks-the-retrain.md)). Extend the
archive because the retrain needs it, not because it will fix the bias.

## Where the model stands — see §1, §1b, §4 for every number

- **The blind-block repair did not move the gap, measured precisely** (`-09-44a`, §4): in-season
  **1.423260x → 1.423246x**, paired **−0.0000140 [−0.0022674, +0.0024795]** — **≤0.6% of the distance
  to parity.** Power `0.050` is the α floor at a ~0 effect and means nothing; the interval is the
  result. **Input completeness was a correctness problem, not a skill problem — never cost remaining
  input work as gap closure.**
- **Model-skewed quoting is RETIRED** (`-09-46a`, §1b.2): 114 pre-declared cells, **zero** positive;
  overall **−0.01915 [−0.02444, −0.01443]**. **We match the market only where we already agree with
  it and lose everywhere we differ.** Do not commission work premised on a window where we win.
- **There is NO execution tape and it cannot be reconstructed** (§1b.3, `-09-47a` **NO-GO**):
  1,107,984 rows hold **71** `last_trade_price`, and a `price_change` depletion is observationally
  identical for a cancel and a fill. **No cancellation labels ⇒ no false-positive denominator ⇒
  precision is unestimable, not low.** `A` and `f` are **unidentified, not underpowered** — do not
  accept "improve the classifier". **The only route left is forward capture (§8c), which is a clock
  that has not started.**
- **Four legacy headlines are retired from citation** (§1), incl. **`74.97%`, no replacement**. **Cite
  the stratum** (§1b.4): 1.4233x is in-season; we serve **out-of-season**, at **1.526x–1.542x**.
- **The retrain blocks on 14 cells, not the corpus** — Denver 2025-07-28 has 17 WU hourly rows against
  a floor of 18, **unfillable** (WU, METAR, GHCN return the same 17). **`COMPLETE_DAY_MIN_ROWS` = 18
  is NOT a knob** — it also decides settlement trust and streak completeness. Fix is the code-owned
  exclusion list (`-09-42a`), never a lower floor.

## Decided — do not relitigate without new evidence

- **Release #1 DEFERRED** until a retrained candidate exists
  ([why](release-one-deferred-until-a-retrained-candidate.md)); it would freeze artifacts measured a
  full degree cool. The lock does not expire — the 7-day rule is rolling source recency.
- **Free-tier Open-Meteo only, no paid API. Training population 2021–2025.** Do not stop a mission
  on either. **Nothing is reserved today**; the window arms at candidate freeze.
- **Answered, do not redo:** inputs will not close the gap (`-09-44a`); free-source blindness repair
  is NO-GO (`-09-26a`, 8.90% coverage); contamination is not the lever (§6); Release #1 is not
  *sufficient* for promotion (§9); do not tune severe-tail suppression before the retrain (§4d).

## In flight

| Ref | What | State |
| --- | --- | --- |
| `-09-43a` | **blind-feature repair — lands 6 missions**, incl. `-09-33a`'s target-derived archive | **QUEUED 01:20**; do not queue `-33a`/`-38a`/`-39a`/`-41a`/`-42a` separately |
| `tolerate-benign-capture-race` | **restarts the chain, dead at step 4 since 08-04** | **QUEUED 01:20** |
| `register-two-schema-literals` | last red test on master | **QUEUED 01:20, after `-09-43a`** |
| `-09-44a` / `-09-46a` | **RETURNED** — gap unmoved; no quotable edge anywhere | **QUEUED 01:20** |
| `-09-45a` | maker daily-start race — the capture killer | **MERGED 17:57 today.** Tomorrow's 08:15 report is the first clean read |
| `-09-47a` | **RETURNED — NO-GO, executions are not reconstructable** | ROLL-FREE verified here; **QUEUED 05:15**. `A`/`f` unidentified; only forward capture remains (§8c) |
| `-09-48a` | **RETURNED — NO-GO: no model-independent quoting route exists** | ROLL-FREE verified here; **QUEUED 05:15**. Falsified my map hypothesis; §8bb + a second operator decision in §8c |
| `-09-35a` | **rotate snapshot + observation-trigger logs** | written, **NOT dispatched — top ops item** |

Merges run off allowlists, **not** auto-discovery — some branches are held deliberately.
`WeatherMergeQueueDriver` 05:15 roll-free · `WeatherMergeSensitiveDriver` 01:20 roll-sensitive.

## Open and unowned → [OPEN_BACKLOG.md](OPEN_BACKLOG.md)

Split out 2026-08-08; this page was 71 lines over cap **because it was carrying that list**. Rank 1
is **log rotation** — `observation_trigger_console.log` is **1,045 MB** and an unrotated 489 MB file
crash-looped the CLOB loop on 2026-07-12. `-09-35a` is written and undispatched.

Two things are *happening* rather than merely owed, so they stay here:

- **Settlement backfill 08-05 → 08-07**, one per morning; `WeatherSettlementBackfill20260805` armed
  08-10 05:30. **`-Refetch` is mandatory** or it fetches nothing and exits 0
  ([runbook](wu-settlement-source-down-2026-08-07.md)).
- **THE MAKER CANNOT QUOTE MARKET-CENTRED AT ALL** (`-09-48a`, §8bb): 554,004 post-boundary rows,
  **zero `QUOTE`**. **My "the map is incomplete" guess was wrong** — the map matched **100%** of
  rows; the records say `no_quote` with reason `promotion_block`. Replay: lift the map → all
  blocked by promotion; grant promotion *and* harvest → **the harvest branch still requires model
  fair value**, so removing it gives zero quotes again. **The one strategy `-09-46a` left open is
  not implementable in the current code.** Deliberate architecture, **not a defect** — do not
  "fix" it by deleting the map or relabelling promotion.
- **AND A COUNTABLE DAY NEVER MEANT A QUOTE.** The gate certifies input/evidence eligibility, not
  trading; `fills.jsonl` was never written. **The 8-of-56 clock is a data-plane qualification
  clock** — raising its yield moves the MM decision no closer. Do not cite it as trading evidence.
- **AWAITING AN OPERATOR DECISION: start capturing the execution tape (§8c)** — the only remaining
  route to `f`. **Not** re-arming `clob_enrichment`: that loop was disarmed for producing book volume
  without evidence, and an execution-only tape is the opposite.

## Daily reads

Under `data/alerts/`: `STALENESS_SWEEP.md` (**"should this have refreshed by now?"** 08:10) ·
`MORNING_BRIEFING.md` (host) · `MM_COUNTABILITY.md` (08:15); plus
`data/backtest/daily_refresh_report.md` (chain). `OPERATING_REFERENCE.md` is **generated** — fix the
constant, not the doc. Merge timing is `scripts\ops\roll_verdict.ps1 -Branch <b>`, **never derived by
hand**. **Two standing alarms are expected, not incidents** — `WeatherTrainingWindow` exit **2** and
the chain's exit **1**, both benign per
[RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md) §3.

**`pytest -q` on master is GREEN** — 3,349 passed, 0 failed, once tonight's schema branch lands. **If
something is red, it is yours.** Host: **176 GB** disk, 9.5 GB RAM free.

## Update this file when

A decision changes, the critical path moves, or a mission returns. **Rewrite the affected lines — do
not append.** If you are adding rather than replacing, ask what became untrue.
