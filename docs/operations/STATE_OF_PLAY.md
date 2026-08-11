# State of play

**Last rewritten: 2026-08-11 (instrument audit closed; six research branches landed).** Read this
first, then `ESTABLISHED_FINDINGS.md`.

> **REWRITTEN, never appended. Capped at ~90 lines.** Answers *"what is happening right now?"* —
> **not what we know.** `ESTABLISHED_FINDINGS` owns findings and every interval ·
> `RETRACTED_AND_FALSE_LEADS` what is false · `OPEN_BACKLOG` what is unowned · `AGENT_CONTEXT`
> invariants · `DELEGATION_CONTRACT` how to work. **Cite numbers from §-references, not this page.**

**Objectives:** 1. protect the Toronto capture streak · 2. **find a model that beats the market — we
do not** · 3. the market-making bot is the end goal.

## Four clocks, none of them running — a stopped counter looks satisfied

| Clock | Reads | Actually |
| --- | --- | --- |
| Capture streak | **1 / 14** | day 1 is 2026-08-09; lock ~**2026-08-22** if every day stays clean. The 7-day shelf life on the latest source day means a banked run cannot be hoarded. |
| MM countable days | counter ticks | **7 of 55**, last counted **2026-07-12** (§8b). A countable day never required a `QUOTE`. |
| Archive coverage | `fleet-coverage` **OK 12/12** | **05-10 → 06-30 only** — zero rows for any August target. The re-fetch is permitted and **still un-run**. |
| Execution-tape days | *no counter exists* | **PILOT PROVED THE TAPE EXISTS 2026-08-10** (§8c): 40 trades, 79.98/h, 11 markets, `transaction_hash` on every row. Task self-disarmed; **continuous capture is an unmade operator decision.** |

## The instrument audit is CLOSED — the gap is real

**Five missions hunted an instrument defect big enough to explain why we trail the market. None
found one; none spent α.** `-09-64a` **PRECISE NULL** — the blind-feature repair adds **zero**
realized-band zeros, repaired ≡ control row-for-row, so post-processing did not manufacture the gap.
`-09-67a` closes the audit: the gap is **FLAT** across label-coverage buckets and the market's own
Brier is flat too. **Cite the ~13% CEILING of the attribution interval — never the 1.5069% point**,
which is a diagnostic, not a result. **"We trail the market" survived its last denominator check.**

## Gate 3 fired on a floor we never served — and is a size limit anyway

`-09-63a` stopped at Gate 3; **decision 10 is CLOSED UNUSED / RETIRED**, not reassigned (§1j).
**The stop stands on two real rows — but two of its cited facts do not.** Denver `2026-06-08` was
**served `0.5206313021`, not `0.0`** (`-09-65a`: replay rebuilt the floor from a stale
`wu_current.max_since_7am_c`), and the "3 surviving zeros" are **two plus a blank-floor fallback
row** (`-09-68a`). **The realized-band-zero defect is NOT live** — it ended `2026-06-15` with
`28d1c146`; **never quote the pooled 1.017% without the pre/post-fix split.** `-09-68a` also shows
Gate 3 is a **panel-size limit** that rejects more often as evidence accumulates *regardless of
candidate quality* — **do not re-register it unchanged.** Traces:
[GATE_3_FIRED…](GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md) ·
[REPLAY_FLOOR_DIVERGES…](REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md) ·
[SERVED_BAND_FLOOR_DEFECT…](SERVED_BAND_FLOOR_DEFECT_2026-08-10.md) (both versions).

**Every other lever is closed too** — reshaping (`-09-60a`, conditional loses to global on its own
training score), inputs (`-09-44a`), quoting (`-09-46a`, 114 cells, zero positive). The served floor
helps B only cosmetically (`-09-66a`), so **the B screens stand as run**. `74.97%` and three other
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
| `-09-63a` | B-only screen — **NO-GO at Gate 3** | **STILL QUEUED.** Conflicted 08-11 05:30 in `ESTABLISHED_FINDINGS`/`STATE_OF_PLAY`; driver aborted cleanly. Report **not in-repo** — cite the branch |
| `-09-69a` | execution-tape continuous capture | **DISPATCHED**, blocked on the operator's capture decision, not on evidence |
| PIT extract | frozen lead-1 daily features, **shipped in-repo** | `docs/roadmap/pit-lead1-daily-features-2026-09-61a.csv`, sha256 `60b450f1…`, **696 rows** |
| PIT fields | staged 12/12, `06-03 → 08-09`, 100% coverage | **NOT adopted** — a serving change; replay first (§1e) |

Merges run off allowlists, **not** auto-discovery. `WeatherMergeQueueDriver` 05:15 roll-free ·
`WeatherMergeSensitiveDriver` 01:20. **Some branches are held deliberately — never delete one.**

## Operations — what is actually wrong today

- **SETTLEMENT HOLES OUTPACE REPAIR.** `08-06` and `08-08` are unsettled (`source='none'`,
  `high=None`, 12/12); `08-10` is absent pending today's 09:30 chain. The 08-11 05:30 backfill for
  08-06 **ran, reported `SETTLED`, and did nothing** — deferred at admission (commit `74.324%` vs a
  `70.0%` ceiling) 15 ms in, while the guard checks only *"is the date string in the ledger"*, which
  a `source='none'` row satisfies. **Countable date VOLUME is the critical path.**
- **Host commit sits AT the admission ceiling** (70.3% vs 70.0%), so heavy chain steps keep
  deferring. The chain reading "deferred" is that, **not** a gate defect.
- **Disk is the lock's binding constraint.** 155.0 GB free post-tiering, **−12.6 GB/day** at a fixed
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
