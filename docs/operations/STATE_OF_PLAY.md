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
| Capture streak | **15 / 14 FULL** | ends **2026-08-04** and **HAS A SHELF LIFE** — `POOLED_PIT_MAX_LATEST_TARGET_AGE_DAYS = 7`, so a banked run stops being usable for a production PIT lock 7 days after its **latest** day. 08-05/08-06 were clean; **08-07 (41 min) and 08-08 (20 min) will grade partial and break contiguity.** |
| MM countable days | counter ticks | **7 of 55**, last counted **2026-07-12** (§8b) |
| Archive coverage | `fleet-coverage` **OK 12/12** | covers **05-10 → 06-30 only** — zero rows for any August target |
| Execution-tape days | *no counter exists* | **AUTHORIZED 2026-08-09, starting.** Bounded pilot runs after 18:00; continuous producer follows (§8c). |

## THE critical path is NOT the archive alone — corrected 2026-08-09

The archive holds **52 month-days per year and zero July/August rows in any year**, and every served
HGB was fitted 2026-06-10..13 on it. **`-09-33a` (inside tonight's `-09-43a` merge) deletes
`SEASON_START`/`SEASON_END`** for `archive_window_for_target(target_date, ...)`.

**The merge makes the fetch possible; it does not perform it.** The manifest keeps its May–June rows
until someone runs `python -m weather.sources.forecast_history backfill --target-date <d>` —
**~60 free-tier calls**, ~1s each, already permitted by policy.

> **NECESSARY, NOT SUFFICIENT — this page said "nothing else competes" and that was wrong.**
> `-09-50a` found the retrain never reaches preflight at all: `load_parent_contract()` demands a
> **verified ACTIVE parent release** and this host has **no release store** (`artifacts/releases/`
> does not exist; `base_retrain` has zero bootstrap paths). **Extending the archive does not let the
> retrain run**, and the second blocker needs a **decision**, not a fetch — see §4a-bis. Release #1
> was treated as downstream of the retrain; the retrain needs a release-shaped parent first.

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
- **THE GOAL IS A BETTER MODEL, NOT A QUALIFIED ONE** (operator, 2026-08-09, §0b). The release and
  qualification machinery is **off the critical path**; the retrain remains desirable and is no
  longer the gate. **Dropping qualification is NOT dropping honesty** — leakage-free walk-forward
  or replay, crossed clustering, power before interpretation, no pooling across `2026-07-31`.
  item-224's "win" was leakage. **The bar for believing a result is unchanged; only the bar for
  shipping one moved.**
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
| `-09-35a` | **RETURNED — sidecar rotation + breaker decoupling** | ROLL-SENSITIVE (6 importable, all 3 closures) verified here. **NOT yet queued — heavy verification owed after 18:00** |
| `-09-49a` | **RETURNED — both follow-ups closed**; parity reported exit 2 → 0 | ROLL-FREE verified here (training-path only, serving cannot change); **QUEUED 05:15**. Parity exit code not yet reproduced on this host |
| `-09-50a` | **RETURNED — the retrain never reaches preflight: no active parent release** | ROLL-FREE verified here; **QUEUED 05:15**. Corpus assembles 12,600/12,600; peak RSS 316 MiB. My target could not test `-09-42a` — see HOW_WE_GET_THINGS_WRONG |
| `-09-51a` | **RETURNED — NO supported path from an empty store to the first retrain** | ROLL-FREE verified here; **QUEUED 05:15**. A CODE contradiction, not a decision — §4a-bis. The Release #1 deferral is **not** the obstacle |
| `-09-52a` | **RETURNED — the held branch closes NONE of the three causes** | ROLL-FREE verified; **QUEUED 05:15**. It does not contain `base_retrain.py` at all. Stays held for **substantive** serving/migration risk, not calendar |
| `-09-53a` | **RETURNED — CIRCULARITY BROKEN. `base_retrain` reached preflight for the first time ever** | ROLL-FREE verified; **QUEUED 05:15**. Contract generalized, not relaxed — checked line by line |
| `-09-54a` | **RETURNED — 6th blocker: the base corpus manifest has NO PRODUCER** | ROLL-FREE verified; **QUEUED 05:15**. Registered + consumed, never written. PIT staging 0/60 |
| `-09-55a` | write the producer, and trace the 21-field endpoint claim | **DEPRIORITISED** by §0b — let its P0 endpoint trace land (useful for the archive regardless); its P1 producer is no longer on the critical path |
| `-09-56a` | **decompose the gap on the current surface** — calibration vs information | **DISPATCHED**. Without it, "small improvements" is guessing. Needs none of the release machinery |

Merges run off allowlists, **not** auto-discovery — some branches are held deliberately.
`WeatherMergeQueueDriver` 05:15 roll-free · `WeatherMergeSensitiveDriver` 01:20 roll-sensitive.

## Open and unowned → [OPEN_BACKLOG.md](OPEN_BACKLOG.md)

**Rank 1 stopped being a risk and became an incident on 2026-08-09: log rotation cost 5 h 54 m of
capture** (04:32 → 10:26). `PermissionError` reopening a 625 MB `diagnostics.jsonl` killed the
snapshot loop; the supervisor then burned its 6/6 restart budget and opened the circuit, which would
not have self-healed for 24 h. Hand-rotated, so **live crash risk is zero and regrowth is
unprevented**. Two design findings in `-09-35a`: the crash mode is **reopening** a big file (so
`.jsonl` is the danger, held-open `.log` consoles are only disk), and **the circuit breaker reads the
file being rotated**, so rotation must not clear safety state.

Two things are *happening* rather than merely owed, so they stay here:

- **Settlement backfill is FOUR dates, not three** — 08-05 → 08-08 — and all four are now armed,
  one per morning 08-10 → 08-13, each with the mandatory `-Refetch`
  ([runbook](wu-settlement-source-down-2026-08-07.md)). **08-05 and 08-06 are the ones that matter
  most**: they were clean, so settling them extends the contiguous complete block to **08-06** and
  pushes the shelf life to **2026-08-13**. 08-07/08-08 are settlement continuity only — they will
  grade partial, so the next 14-day block cannot start before **08-09**, completing ~**08-22**.
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
- **BOTH MM DECISIONS ARE MADE (operator, 2026-08-09, §8c).** (1) **Execution-tape capture is
  authorized and starting** — bounded pilot after 18:00 via `scripts\ops\execution_tape_pilot.py`,
  which **refuses to run inside 12:00–18:00**; the continuous producer is a mission written once the
  pilot returns real numbers. (2) **A paper-only market-harvest lane is authorized but sequenced
  AFTERWARDS** — capture supplies the evaluation that makes the lane's output mean anything. **Do
  not start lane work until capture is producing rows.**

## Daily reads

Under `data/alerts/`: `STALENESS_SWEEP.md` (**"should this have refreshed by now?"** 08:10) ·
`MORNING_BRIEFING.md` (host) · `MM_COUNTABILITY.md` (08:15); plus
`data/backtest/daily_refresh_report.md` (chain). `OPERATING_REFERENCE.md` is **generated** — fix the
constant, not the doc. Merge timing is `scripts\ops\roll_verdict.ps1 -Branch <b>`, **never derived by
hand**. **Two standing alarms are expected, not incidents** — `WeatherTrainingWindow` exit **2** and
the chain's exit **1**, both benign per
[RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md) §3.

**Master is NOT fully green, and this line said it was.** The module-size ratchet went red when
`-09-43a` pushed `weather.model.model_features` to 2,014 lines; fixed 2026-08-09 by documenting the
ownership entry, which is what the ratchet exists to force. **~17 further failures are reported as
environmental** (PowerShell execution-policy, Windows experiment-executor output trees) and are
**unverified on this host** — do not claim green until they are. **If something is red, it is
yours.** Host: **176 GB** disk, 9.6 GB RAM free.

## Update this file when

A decision changes, the critical path moves, or a mission returns. **Rewrite the affected lines — do
not append.** If you are adding rather than replacing, ask what became untrue.
