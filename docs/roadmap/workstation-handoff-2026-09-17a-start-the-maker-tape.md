# Workstation handoff 2026-09-17a — start the maker tape

**Goal: make the market-making decision clock able to start.** It has never started. Not because we
are short of days — because we capture no trade tape at all, so no maker fill can be proven and every
paper day is non-countable. This handoff decides which producer supplies that tape, proves the tape
is sufficient, and prices it on a 16 GB host.

Branch from refreshed `origin/master`. Branch name:
`codex/workstation-start-the-maker-tape-2026-09-17a`.

## What is already established — do not re-derive

Verified on the production host 2026-08-05, cited so you start from fact:

| Fact | Evidence |
| --- | --- |
| The trade tape is off | `data/snapshots/<event>/clob_capture_status.jsonl` last line: `"include_ws_events": false`, `"ws_event_rows": 0`, `"ws_messages": 0`, `"ws_error": null` — not an error, simply never enabled |
| It is off **by design** in the book loop | `DEFAULT_LOOP_INCLUDE_WS_EVENTS = False` (`market_microstructure_constants.py:18`); `_assert_raw_loop_contract` (`market_microstructure.py:1074`) **raises** if you enable price history or WS events on the latency-critical loop and points at `enrichment-loop` |
| The enrichment loop is not scheduled | 31 `Weather*` scheduled tasks; `WeatherClobBookLoopSupervisor` runs raw books; there is **no enrichment task** |
| So no maker fill is ever recorded | `data/mm_runs/2026-08-04/<run>/fills_long.csv` is **header-only, 1 line**; `order_lifecycle.jsonl` is **0 bytes** |
| While the run is not cheap | the same run wrote `quote_intents_long.csv` 193 MB + `model_variant_quote_intents_long.csv` 469 MB + projections ≈ **0.9 GB for that market-day** |
| `-09-10a` already found the consequence | strict-through fills "**not computable** for the inspected 2026-08-02 and 2026-08-03 days … 0/12 retain `market_ws_events.csv`, `market_ws.jsonl`, `market_trades.csv`, or `trades_long.csv`. Books alone cannot prove a strict-through execution" |

**Do not re-litigate any of the above and do not redo `-09-10a`'s power analysis.** Take its table as
given: at the `$25 / tier-20` cap, 80% power needs **15** countable dates (**22** under the
date-shock envelope); at `$50 / tier-50`, **30** (**43** under the envelope).

## P1 — choose the producer, exactly one recommendation

Three candidates. Pick one and justify it from the real call graph, not from preference.

1. **Schedule the existing `weather.market.market_microstructure enrichment-loop`** with WS events
   enabled. Cheapest in code — nothing new merges. But it is unscheduled today and you must say why,
   and whether that reason still holds.
2. **`-09-11a`'s `mm_execution_capture`** (`origin/codex/workstation-make-mm-days-countable-2026-09-11a`,
   `14dd1e84`): a dedicated producer that "subscribes every active built-in token on one connection"
   and is "deliberately separate from the latency-critical raw-book loop", plus
   `register_mm_execution_capture.ps1` and a per-event session receipt the scorer treats as
   mandatory. Correct-looking, but it is a **4th capture loop** and the branch is **roll-sensitive**
   (`schema_registry_data.py` +35, in every capture import closure).
3. Both, or a narrowed variant.

**The hazard you must resolve either way:** both candidates write into the *same* event folders the
latency-critical book loop is writing, through `MarketMicrostructureStore.append_csv` /
`append_jsonl`. Trace `raw_tape_guard` and `raw_tape_lock_anchor_path` and state whether a second
writer can stall, corrupt, or slow the book loop. **The Toronto capture streak outranks the MM track**
— if a producer can degrade book capture, say so and prefer the one that cannot.

## P2 — prove the tape is sufficient, by running it

Assertion is not acceptance. Show that the chosen tape format actually yields a **countable day with
at least one strict-through fill**, end to end, through `mm_day_countability` and `mm_paper_scoring`.

The fill standard is `-09-10a`'s and is not negotiable: a taker SELL must print **strictly below** a
YES bid, a taker BUY **strictly above** a YES ask, and size is capped by the recorded execution size.

- If you can capture live WS messages on the workstation for a short window, do that and use real
  bytes. It is a read-only public feed; **no credential, no order, no host state.**
- If you cannot, build the fixture from the recorded message schema and say plainly that it is a
  fixture, not real bytes — then state what real capture would still have to confirm.
- If any required field is absent from the tape (aggressor side, size, timestamp, token identity,
  book-alignment sequence), **name the field and the exact writer that must add it.** A tape that
  cannot prove a fill is worth nothing, and discovering that 6 weeks from now is the failure mode
  this mission exists to prevent.

Also state whether a countable day requires the *maker* to have quoted — i.e. whether the tape alone
is enough, or whether `-09-11a`'s session receipt is load-bearing.

## P3 — price it on a 16 GB host

The production host has **15.75 GB total, ~7.4 GB free**, three capture loops at `AboveNormal`,
a live `HOST_LOAD_POLICY`, and a prior incident where one ad-hoc process took both capture loops
down. Disk is currently **133 GB free** and growing about **27.6 GB/day**.

Give measured or carefully-bounded numbers, not adjectives:

- steady-state RSS and CPU of the chosen producer;
- WS message rate and bytes/day at **12 markets × ~22 tokens**;
- the resulting disk/day delta, against the 0.9 GB/market-day the MM roll already writes;
- process priority it should run at, and what it must yield to.

Close with a plain **GO / NO-GO for a 4th concurrent loop**, and if NO-GO, what to drop to afford it.
Note that taker is deprioritized and its tape was already deleted — that is fair game to trade away.

## P4 — the calendar, composed not re-derived

Assume the tape starts capturing on **2026-08-06**. Using `-09-10a`'s power table unchanged, state:

- the **cheapest decisive pilot** configuration, and whether `$25 / tier-20` is genuinely decisive or
  merely cheaper;
- the earliest calendar date the MM gate could return a real verdict, for both the 22-date and
  43-date paths;
- what fraction of days will realistically be countable, given `clob_freshness` blocks on **max gap
  across the whole day** and one ~3-minute gap poisons a market-day
  (`-09-13a` / `-09-14a` watcher stretch is held, unmerged).

If the honest answer is that countability loss makes 22 dates take much longer than 22 days, **say
that** — it is the number the operator is actually planning against.

## P5 — roll safety and merge placement

Per-file roll verdict from the retained capture-loop **import closures**, not the `SOURCE_PATTERNS`
glob. Name which of the snapshot / CLOB / observation-trigger / CLOB-enrichment closures each changed
file enters. Place your branch in the standing order: `-09-11a` → `-09-14a` → refreshed `-09-01a`
alone → `-09-04a` → refreshed `-09-12a` + PIT seam.

## Boundaries

- **Read-only with respect to production.** Register nothing, enable nothing, start no loop, change
  no scheduled task, write nothing under `data/` on any host, and never write to the mirror or
  `D:\weather-mirror`. Deliver a registration script and a verdict; the operations host registers it.
- Never read or expose `C:\Users\micha\.weathersync.cred`.
- `docs/operations/reserved-confirmation-window.md` wins over this document. **No dates are reserved
  today**; the window is armed but undated. Do not declare, consume, or read a reserved date.
- Do not relax the promotion gate for `harvest_only` rows, do not weaken the trusted observed-high
  floor, and do not change providers or paid tiers.
- No PR, no merge. Commit to the exact branch name above and push that branch only.
- Report to
  `docs/roadmap/agent-report-2026-08-05-workstation-start-the-maker-tape.md`.

## What would falsify this mission

- Finding that WS events *are* captured somewhere for some market-day would falsify the premise; the
  inspected status lines say `ws_event_rows: 0` with `include_ws_events: false`, so show the counter-example.
- Finding that `fills_long.csv` is populated on any run would falsify "no fill was ever recorded".
- Finding that books alone can prove a strict-through fill would remove the need for the tape entirely
  — that would be the best possible outcome, so test it before assuming it is false.
- Finding that a second writer cannot touch the book loop would remove the streak hazard in P1.
