# State of play

**Last rewritten: 2026-08-12 (the recovery-candidate thread closed unpowered; α untouched).** Read
this first, then `ESTABLISHED_FINDINGS.md`.

> **REWRITTEN, never appended. Capped at ~90 lines.** Answers *"what is happening right now?"* —
> **not what we know.** `ESTABLISHED_FINDINGS` owns findings and every interval ·
> `RETRACTED_AND_FALSE_LEADS` what is false · `OPEN_BACKLOG` what is unowned · `AGENT_CONTEXT`
> invariants · `DELEGATION_CONTRACT` how to work. **Cite numbers from §-references, not this page.**

**Objectives:** 1. protect the Toronto capture streak · 2. **find a model that beats the market — we
do not** · 3. the market-making bot is the end goal.

## Four clocks, none of them running — a stopped counter looks satisfied

| Clock | Reads | Actually |
| --- | --- | --- |
| Capture streak | **3 / 14** | day 1 is 2026-08-09; `08-11` settled at 09:30 on 08-12 (`src=daily_summary`) and grades `complete`. **`08-12` is already DOOMED to partial** — two in-window gaps, max **40 min** against a 15-min fatal, so the streak breaks at 3. Lock slips past ~2026-08-22. |
| MM countable days | counter ticks | **7 of 55**, last counted **2026-07-12** (§8b). A countable day never required a `QUOTE`. |
| Archive coverage | `fleet-coverage` **OK 12/12** | **05-10 → 06-30 only** — zero rows for any August target. The re-fetch is permitted and **still un-run**. |
| Execution-tape days | *no counter exists* | **PILOT PROVED THE TAPE EXISTS 2026-08-10** (§8c): 40 trades, 79.98/h, 11 markets, `transaction_hash` on every row. Task self-disarmed; **continuous capture is an unmade operator decision.** |

## Every lever we have tried is closed — and none of them spent α

**The instrument audit is CLOSED (five missions, no defect found).** The gap is **FLAT** across
label-coverage buckets and the market's own Brier is flat too (`-09-67a`); the blind-feature repair
is a **precise null** (`-09-64a`). **Cite the ~13% CEILING of the attribution interval, never the
1.5069% point.** **"We trail the market" survived its last denominator check.**

**The observation-recovery candidate is now closed too, unpowered** — `-09-78a`, §5e below.

`-09-63a` stopped at Gate 3; **decision 10 is CLOSED UNUSED / RETIRED**, not reassigned (§1j).
**The stop stands on two real rows — but two of its cited facts do not:** denver `2026-06-08` was
**served `0.5206313021`, not `0.0`** (`-09-65a`), and the "3 surviving zeros" are **two plus a
blank-floor fallback row** (`-09-68a`). **The realized-band-zero defect is NOT live** — it ended
`2026-06-15` with `28d1c146`; **never quote the pooled 1.017% without the pre/post-fix split.**
Gate 3 is a **panel-size limit** that rejects more often as evidence accumulates *regardless of
candidate quality* — **do not re-register it unchanged.** Traces:
[GATE_3_FIRED…](GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md) ·
[REPLAY_DOES_NOT_REPRODUCE…](REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md) ·
[REPLAY_FLOOR_DIVERGES…](REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md) ·
[SERVED_BAND_FLOOR_DEFECT…](SERVED_BAND_FLOOR_DEFECT_2026-08-10.md).

**The others:** reshaping (`-09-60a`), inputs (`-09-44a`), quoting (`-09-46a`, 114 cells, zero
positive). The served floor helps B only cosmetically (`-09-66a`). `74.97%` and three other
headlines are retired with **no replacement** — cite the stratum. **The remaining lever is knowing
MORE.** Numbers: §1, §1b, §1i, §4.

## Decided — do not relitigate without new evidence

- **THE GOAL IS A BETTER MODEL, NOT A QUALIFIED ONE** (operator, 2026-08-09, §0b). Release and
  qualification machinery is **off the critical path**, but **dropping qualification is NOT dropping
  honesty** — leakage-free evaluation, crossed clustering, power before interpretation.
- **Release #1 DEFERRED**; the retrain still blocks on a release-shaped parent (§4a-bis) and the
  un-run archive re-fetch. **Free-tier Open-Meteo only. Nothing is reserved today.**
- **Amendment A1 ADOPTED 2026-08-10** (§1i): uniform `q=3.1098893`, both required endpoints, base
  protocol byte-identical. **It is a LOWER bound** — the tail is a selected-extreme subset, not
  Gaussian. Ledger unchanged: **7 of 20 spent, 13 available**.
- **Both MM decisions are made (§8c):** execution capture first, paper harvest lane **afterwards**.
  **Do not start lane work until capture is producing rows.**

## In flight

| Ref | What | State |
| --- | --- | --- |
| `-09-73a` … `-09-78a` | observation-recovery candidate | **THREAD CLOSED UNPOWERED, α UNSPENT.** `-09-78a` (§5e) NO-GO under *both* calibration premises including the candidate's own. **The limit is the stratum's 11 date clusters, not the 12-market floor** — ~22 would flip it. Draft stays unfrozen |
| `-09-63a` | B-only screen — **NO-GO at Gate 3** | **STILL QUEUED.** Conflicted 08-11 05:30 in `ESTABLISHED_FINDINGS`/`STATE_OF_PLAY`; driver aborted cleanly. Report **not in-repo** — cite the branch |
| `-09-69a` | execution-tape continuous capture | **DISPATCHED**, blocked on the operator's capture decision. Suite gate re-armed **08-13 20:30** after a 03:00 run aborted on its own commit ceiling — it collided with the training window |
| PIT extract | frozen lead-1 daily features, **shipped in-repo** | `docs/roadmap/pit-lead1-daily-features-2026-09-61a.csv`, sha256 `60b450f1…`, **696 rows** |
| PIT fields | staged 12/12, `06-03 → 08-09`, 100% coverage | **NOT adopted** — a serving change; replay first (§1e) |

Merges run off allowlists, **not** auto-discovery. `WeatherMergeQueueDriver` 05:15 roll-free ·
`WeatherMergeSensitiveDriver` 01:20. **Some branches are held deliberately — never delete one.**

## Operations — what is actually wrong today

- **HEAVY WORK ON THIS HOST COSTS CAPTURE DAYS — including mine.** `08-12` failed
  `capture_host_memory_admission: insufficient_physical_memory` across all 12 markets, with
  available physical down to **116 MB**, producing gaps `13:00→13:34` and `15:08→15:48`. Both are
  **inside the 12:00–18:00 graded window**, so the day is partial and the streak breaks. The
  agent-run analysis in that window is the likeliest cause. **The 16 GB host has no headroom for
  unbudgeted compute during the graded window — run it after 18:00 or not at all.**
- **SETTLEMENT: the repair path WORKS; only `08-08` is still a hole.** `08-06` settled 12/12 with a
  real source (+76 ledger rows) from the 02:00 run on 08-12, and `08-11` self-healed at the 09:30
  refresh — it was a *timing* miss, not a source hole. **`08-08` has now failed three times**
  (`src=none`, 12/12) and should be treated as likely unrecoverable, not under-retried. **Both
  defects behind the old "reported SETTLED and did nothing" note are FIXED**:
  `settlement_backfill_one.ps1` now verifies row **content** per market and emits `SILENT_NOOP`, and
  host commit runs at **~35%**, nowhere near the 70% admission ceiling. **Countable date VOLUME
  remains the critical path.**
- **`08-10` was NOT a source hole and is now RECOVERED 12/12 `complete`.** The 08-11 chain restored
  it (`restored 12/12`) and then lost it: `market_day_labels_finalize` died on a transient
  `[Errno 13]` on austin's ledger, and `finalize_folders` had no per-folder isolation, so
  `write_labels_csv` never ran and no market got an 08-10 row. Fixed in `bcb49506` (ROLL-FREE):
  failures are now isolated, retried, and re-raised *after* surviving labels are persisted. **A
  subset re-finalize must merge the labels CSV — `write_labels_csv` rewrites it whole and would have
  truncated 789 rows to 12.** Trace:
  [FINALIZE_LOST_A_SETTLEMENT_DAY…](FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md).
- **Host commit is NO LONGER at the admission ceiling** — ~**35%** with the full fleet live, against
  70.0%. The old "70.3% idle" note is retired. Heavy steps still defer, but on
  `live_capture_loop_active` with `active_window_source: fail_closed_live_default` and both window
  hours `null` — **worth a trace**, since capture is always healthy by design.
- **Disk is the lock's binding constraint.** 160.1 GB free post-tiering, **−12.6 GB/day** at a fixed
  point in the cycle → exhaustion **~2026-08-23** vs a lock at **~2026-08-22**. Not a leak: ~800 MB
  per market-day × 12. `order_books.jsonl` stays RAW as canonical evidence and gzips **10.97x** —
  **~121 GB recoverable by compression alone** (`PRE_OVERNIGHT_AUDIT_2026-08-10.md` §2).
- **Log rotation is the known capture killer**: the crash mode is **reopening** a big `.jsonl`, and
  **the breaker reads the file being rotated**. Regrowth is unprevented.

## Daily reads

`STALENESS_SWEEP.md` (08:10) · `MORNING_BRIEFING.md` · `MM_COUNTABILITY.md` (08:15) ·
`data/backtest/daily_refresh_report.md`. `OPERATING_REFERENCE.md` is **generated** — fix the
constant, not the doc. Merge timing comes from `roll_verdict.ps1`, **never by hand**.
`WeatherTrainingWindow` exit **2** and the chain's exit **1** are expected. **Master is not fully
green. If something is red, it is yours.**

## Update this file when

A decision changes, the critical path moves, or a mission returns. **Rewrite the affected lines — do
not append.** If you are adding rather than replacing, ask what became untrue.
