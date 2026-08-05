# Workstation handoff 2026-09-18a — narrow the maker producer

**Goal: make `WeatherMakerExecutionCapture` safe to register, so the MM decision clock can start.**
`-09-17a` proved the tape works and priced it. It also proved the held producer must not be
scheduled. This mission builds the narrowed producer that `-09-17a` specified, so that
`scripts/ops/register_maker_tape.ps1` stops refusing.

Branch from refreshed `origin/master`, carrying `-09-11a` forward. Branch name:
`codex/workstation-narrow-the-maker-producer-2026-09-18a`.

## Start from this, do not re-derive it

`-09-17a` (`13a9f690`) is accepted. Its measurements were reproduced exactly on the operations host
and its two load-bearing code claims were verified against the source. Take all of it as given:

| Established | Value |
| --- | --- |
| Held producer disk cost | **27.33 GB/day** — with 27.6 GB/day existing growth, fills 133 GB free in **2.4 days**. NO-GO |
| Narrowed cost | ~**29.24 MiB/day** at 0.133 executions/s; budget **100 MiB/day**, **64 MiB RSS** |
| Why the gap is 1000x | price changes were **11,202 of 11,478 rows (97.6%)**; executions were **4** |
| Steady state | 186.5 msg/s, 381 rows/s, ~40 MiB RSS, ~33% of one core |
| Lock hazard | `raw_tape_guard` is `attempts=3, sleep_seconds=0.025` then **raises `RawTapeWriterBusy`** — a hard raise, not a wait. The held producer takes that same `clob_raw_tape` anchor at `mm_execution_capture.py:130` and `:223`, once per routed message |
| Strict-through proof | valid, and it needs **no exchange book sequence** — it compares an execution against *our own* paper quote, whose price, size and lifetime we generate and therefore know exactly |

`--help` is the deployed-code contract: `register_maker_tape.ps1` refuses to register unless the
module advertises `--retention-mode`, `executions-only`, `--lock-scope`, `execution-tape`,
`--host-policy-mode`, `pause-training-window`. The held producer has only `--market`,
`--target-date`, `--session-seconds`, `--reconnect-seconds`, `--once`. **Your job is to make that
script stop refusing, honestly.**

## P1 — the three contracts

Implement exactly what `-09-17a` specified. Its section "Exact narrowing contract" is the
specification; follow it rather than re-designing.

**1. Execution-only retention (`--retention-mode executions-only`).** Retain only payload members
whose `event_type` is `last_trade_price`. Do not retain a whole mixed message because one member is
an execution — `-09-17a` measured that intermediate approach at **1.8 GB/day** and it is also a
NO-GO. Retention mode must be explicit, and a mode that retains book or price-change payload must
not be reachable from the registered command line.

**2. Dedicated lock scope (`--lock-scope execution-tape`).** Use a separate anchor,
`root / "mm_execution_tape"`. Keep the raw append, canonical append, and receipt-binding update
inside that guard. **Never take `clob_raw_tape` for an execution read or write.** This is the
contract that protects the Toronto streak; it is the reason the held branch cannot be registered.

**3. Training-window pause (`--host-policy-mode pause-training-window`).** Pause and disconnect for
`WeatherTrainingWindow`, resume after its 04:15 restore, and **record the planned coverage break in
the receipt** so a deliberate gap is distinguishable from a producer failure. Also honour the
protected 18:00–00:30 window for bulk work; small append-only execution evidence is the intended
exception.

## P2 — the writer and the receipt

The shared `ws_summary_rows` contract is insufficient: `-09-17a` found the canonical CSV left
`timestamp_utc` and `trade_time_utc` blank and has no transaction-hash column. Write a dedicated
execution row writer that normalizes the source millisecond `timestamp` into exchange time and
retains `transaction_hash`, `session_id`, and a connection-message sequence.

**Label the connection sequence local.** The public feed exposes no `book_alignment_sequence`; it
must not be fabricated or implied. Local ordering is for audit binding only.

`_append_session_receipts` must bind the subscribed-asset set, the connection-sequence interval, the
execution count **including exact zero**, and raw/canonical tape prefix sizes and hashes.
`build_execution_tape_inventory` may accept a missing execution file **only** when a complete bound
receipt proves exactly zero; a positive receipt count must require matching raw and canonical tapes.

A countable day does not require the maker to quote — a fail-closed or no-edge decision is a valid
zero-action cell — but it does require the producer to have run and the receipt to prove continuous
coverage. **Tape alone is not a countable day.**

## P3 — soak it

A 30-second probe sized this; it cannot clear it. Run a soak long enough to cross a settlement
period, where execution rate is highest and the 0.133/s sample is least representative. Report
bytes/day, peak RSS, CPU share, reconnect count, and any `RawTapeWriterBusy` raised **by any writer**.

**Fail the soak** if it exceeds 100 MiB/day or 64 MiB RSS, or if the book writer ever raises. If it
fails, say so and stop — `-09-17a`'s standing instruction is that we do not buy the maker tape by
risking Toronto. Trade away remaining taker capture workload first; taker is deprioritized and its
tape is already deleted.

## P4 — roll safety, stated accurately

Do not try to keep the schema local. `schema_version()` raises `KeyError` on any name absent from the
central `SCHEMAS_BY_NAME`, so registration in `src/weather/schema_registry_data.py` is **mandatory**,
and that module is in all four capture import closures. **The roll is unavoidable and expected.**

The objective is therefore a single clean quiet-window adoption, not the elimination of the roll:

- keep the registry change **purely additive** — new `SchemaSpec` entries only, no edit to an
  existing entry, so no current consumer changes behaviour;
- give a per-file roll verdict from retained import closures, not the `SOURCE_PATTERNS` glob;
- state which of the snapshot / CLOB / observation-trigger / CLOB-enrichment closures each file enters.

Merge order, with this branch replacing held `-09-11a`:

```text
-09-18a (this, narrowed producer)  ->  -09-14a  ->  -09-17a (roll-free script/report)
  ->  refreshed -09-01a alone  ->  -09-04a  ->  refreshed -09-12a + PIT seam
```

## Boundaries

- **Read-only with respect to production.** Register nothing, start no loop, mutate no scheduled
  task, write nothing under `data/` on any host, never write to the mirror or `D:\weather-mirror`.
  The operations host registers the task after the soak passes.
- Read-only public feed only. No credential, no order, no `C:\Users\micha\.weathersync.cred`.
- `docs/operations/reserved-confirmation-window.md` wins over this document. **No dates are reserved
  today**; the window is armed but undated. Do not declare, consume, or read a reserved date.
- Do not relax the promotion gate for `harvest_only` rows, do not weaken the trusted observed-high
  floor, do not change providers or paid tiers.
- No PR, no merge. Commit to the exact branch name above and push that branch only.
- Report to `docs/roadmap/agent-report-2026-08-06-workstation-narrow-the-maker-producer.md`.

## What would falsify this mission

- A soak showing the narrow form exceeds 100 MiB/day would invalidate the GO and send this back to
  sizing — report it rather than widening the envelope.
- Any `RawTapeWriterBusy` raised by the book writer while the producer runs would prove the dedicated
  lock scope is incomplete, and is a hard stop.
- Finding that execution-only retention loses evidence the countability checklist needs would mean
  the narrowing is wrong, not the checklist — say which field and why books cannot supply it.
- Finding that `register_maker_tape.ps1` can be satisfied without actually implementing a contract
  would mean the guard is cosmetic; report it, because that script is what stands between us and
  scheduling a 27 GB/day producer.
