# State of play

**Last rewritten: 2026-08-13 18:55 (corrected execution tape exact-tip merge armed;
today's grade is already partial).** Read this first, then `ESTABLISHED_FINDINGS.md`.

> **REWRITTEN, never appended. Capped at ~90 lines.** Answers *"what is happening right now?"* —
> **not what we know.** `ESTABLISHED_FINDINGS` owns findings and every interval ·
> `RETRACTED_AND_FALSE_LEADS` what is false · `OPEN_BACKLOG` what is unowned · `AGENT_CONTEXT`
> invariants · `DELEGATION_CONTRACT` how to work. **Cite numbers from §-references, not this page.**

**Objectives:** 1. protect capture continuity · 2. make the **International Polymarket** market maker
profitable after costs, using spread plus documented maker rebates · 3. get our weather model close
enough to the market to control adverse selection and inventory. **We do not beat the market.**

## Four clocks, none of them running — a stopped counter looks satisfied

| Clock | Reads | Actually |
| --- | --- | --- |
| Capture streak | **0 / 14** | `08-13` is already partial after the evidence-refresh failure (§8d). Child-tree containment is now proved, but the workload is still memory-unsafe beside capture, so `WeatherEveningEvidenceRefresh` is disabled again. The earliest new run starts `08-14`. |
| MM countable days | counter ticks | **7 of 55**, last counted **2026-07-12** (§8b). A countable day never required a `QUOTE`. |
| Archive coverage | `fleet-coverage` **OK 12/12** | **05-10 → 06-30 only** — zero rows for any August target. The re-fetch is permitted and **still un-run**. |
| Execution-tape days | *no counter exists* | **PILOT PROVED THE TAPE EXISTS 2026-08-10** (§8c). The corrected exact tip passed its bounded full suite; an exact-tip quiet merge is armed for 01:15. **Continuous capture is approved but is not running yet.** |

## Every lever we have tried is closed — and none of them spent α

**The instrument audit is CLOSED (five missions, no defect found).** The gap is **FLAT** across
label-coverage buckets and the market's own Brier is flat too (`-09-67a`); the blind-feature repair
is a **precise null** (`-09-64a`). **Cite the ~13% CEILING of the attribution interval, never the
1.5069% point.** **"We trail the market" survived its last denominator check.**

**The observation-recovery candidate is now closed too, unpowered** — `-09-78a`, §5e below.

`-09-63a` stopped at Gate 3; **decision 10 is CLOSED UNUSED / RETIRED**, never reassigned (§1j). The
stop stands on two real rows, but two cited facts do not: denver `2026-06-08` was **served
`0.5206313021`, not `0.0`** (`-09-65a`), and the "3 surviving zeros" are **two plus a blank-floor
fallback** (`-09-68a`). **The realized-band-zero defect is NOT live** (ended `2026-06-15`,
`28d1c146`) — **never quote the pooled 1.017% without the pre/post-fix split.** Gate 3 is a
**panel-size limit** that rejects more often as evidence accumulates *regardless of candidate
quality* — **do not re-register it unchanged.** Traces:
[GATE_3…](GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md) ·
[REPLAY_DOES_NOT_REPRODUCE…](REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md) ·
[REPLAY_FLOOR…](REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md) ·
[SERVED_BAND_FLOOR…](SERVED_BAND_FLOOR_DEFECT_2026-08-10.md).

**The others:** reshaping (`-09-60a`), inputs (`-09-44a`), quoting (`-09-46a`, 114 cells, zero
positive). The served floor helps B only cosmetically (`-09-66a`). `74.97%` and three other
headlines are retired with **no replacement** — cite the stratum. **The remaining lever is knowing
MORE.** Numbers: §1, §1b, §1i, §4.

## Decided — do not relitigate without new evidence

- **INTERNATIONAL-ONLY MAKER-REBATE PIVOT APPROVED 2026-08-13.** Never use Polymarket US. The
  primary route is profitable maker execution from spread plus documented International rebates;
  the model is a quote-centre and risk-control input, not assumed alpha. Release and qualification
  machinery remains **off the critical path**, but evidence honesty is unchanged: leakage-free
  evaluation, crossed clustering, and power before interpretation.
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
| `-09-69a` | execution-tape continuous capture | **CORRECTED; EXACT-TIP MERGE ARMED; NOT RUNNING.** The original tip remains rejected because it can discard distinct observations, lacks a documented unique execution ID for count/intensity claims, and counted connection before an inbound routed frame. Corrected `codex/execution-tape-identity-fix` at `d71c2ae` retains every observation for price-path evidence only and passed its bounded full suite. `WeatherQuietWindowExecutionTape0814` is armed for 01:15 with exact-SHA binding and capture-recovery rollback. After it lands, prove real rows before lane work. The old 20:30 wrapper remains unconditionally inert |
| International rebate economics | paper accounting and fail-closed venue evidence | **TESTED, NOT MERGED** on `codex/international-rebate-pivot`; exact official terms and realized payout evidence are content-bound, with unpaid incentives excluded from acceptance P&L. The branch is roll-sensitive after current-baseline integration; merge in the quiet window, then collect and explicitly accept a fresh International snapshot |
| International live probe | bounded exchange-lifecycle test | **PHYSICALLY BLOCKED ON THIS HOST; CODE TESTED, NO LIVE MUTATION** on `codex/international-live-probe`. Official `GET /api/geoblock` returns `blocked=true`, `CA-ON`; Ontario is API close-only. No VPN/proxy circumvention. v0.4 gates bind native pUSD, two distinct cancellation proofs, exact account/fee/rebate evidence, and fresh IP-redacted endpoint checks. A real test needs a genuinely eligible physical host; no credentials, readiness artifact, continuous rows, or order exists |
| PIT extract | frozen lead-1 daily features, **shipped in-repo** | `docs/roadmap/pit-lead1-daily-features-2026-09-61a.csv`, sha256 `60b450f1…`, **696 rows** |
| PIT fields | staged 12/12, `06-03 → 08-09`, 100% coverage | **NOT adopted** — a serving change; replay first (§1e) |

Merges run off allowlists, **not** auto-discovery. `WeatherMergeQueueDriver` 05:15 roll-free ·
`WeatherMergeSensitiveDriver` 01:20. **Some branches are held deliberately — never delete one.**

## Operations — what is actually wrong today

- **`08-13` IS LOST, CAPTURE IS RECOVERED (§8d).** The evidence task's wrapper terminated but its
  S4U `daily_refresh` child survived and starved every snapshot market. Job-object containment now
  proves a task stop reaps the entire child tree, but the contained refresh itself still proved
  memory-unsafe beside capture. `WeatherEveningEvidenceRefresh` is **Disabled** and must stay held
  until admission or workload shape changes. The memory guard catches the ownership failure; it
  does not make this workload safe.
- **SETTLEMENT: every hole through `08-11` is CLOSED — `08-08` recovered on the FOURTH attempt.**
  Verified 2026-08-13: `08-08` carries **12/12 real `daily_summary` sources with real highs**, from
  the 03:08 chain (`public_wu_settlement_restore` PASS, fetched 12). **This page's "failed three
  times, treat as likely unrecoverable" call was WRONG** — the retry path was slower than assumed,
  not exhausted. **Never declare a date unrecoverable from a failure count alone.** The old "reported
  SETTLED and did nothing" defects stay fixed (`settlement_backfill_one.ps1` verifies row **content**,
  emits `SILENT_NOOP`). **Countable date VOLUME remains the critical path.**
- **THE OFF-HOST MIRROR IS PAUSED (operator, 2026-08-12)** — three tasks Disabled, nothing deleted,
  restart is two `Enable-ScheduledTask` calls. **No off-host copy of anything written after
  `2026-08-12 05:03`**, and that frozen copy was already **not proven restorable** (exit 11; 8
  restore problems). The workstation's `data\` is **frozen, not lagging**. `status.ps1` suppresses
  off the **task state**, so re-enabling restores alerting by itself.
  [mirror-paused-2026-08-12.md](mirror-paused-2026-08-12.md).
- **`08-10` recovered 12/12; the finalize defect behind it is FIXED (`bcb49506`, ROLL-FREE).** A
  subset re-finalize must still merge the labels CSV. Trace:
  [FINALIZE_LOST_A_SETTLEMENT_DAY…](FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md).
- **Host commit is NO LONGER at the admission ceiling** — ~**35%** with the full fleet live, against
  70.0%. The old "70.3% idle" note is retired. Heavy steps still defer, but on
  `live_capture_loop_active` with `active_window_source: fail_closed_live_default` and both window
  hours `null` — **worth a trace**, since capture is always healthy by design.
- **Disk: RE-DERIVED 2026-08-13 — the burn is decelerating and disk is NO LONGER the lock's binding
  constraint.** Midnight-to-midnight from `data\alerts\disk_free_trail.jsonl` (400 samples,
  08-09→08-13): **−10.5, −5.3, −0.7 GB/day** on 08-10/08-11/08-12, then **+44 GB on 08-13** to
  **181.6 GB free** — the most headroom since 08-09. Cause: `clob_order_book_tiering` now runs and
  passes every chain (08-13: candidates 4, compressed 4, deleted 4), reclaiming ~25 GB between 05:50
  and 06:35 alone. **The −12.6 GB/day → exhaustion ~2026-08-23 this page carried is RETIRED**, and so
  is the "~57 days" reading. **Do not quote `status.ps1`'s headline GB/day**: it references a sample
  up to 24h back, so one discrete reclaim flips it to a bogus *positive* (it read **+21.1 GB/day**
  today — the disk is not gaining). Not a leak either way: ~800 MB per market-day × 12.
  `order_books.jsonl` stays RAW as canonical evidence and gzips **10.97x** — **~121 GB still
  recoverable by compression alone** (`PRE_OVERNIGHT_AUDIT_2026-08-10.md` §2).
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
