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
archive window  ->  PIT corpus   ->  parity  ->  first retrain      ->  release #1
  DONE 1740/1740    DONE 12180/12180  0 unexp.   BLOCK 12586/12600      (DEFERRED)
```

**The PIT surface is real but narrow, and that is now measured at breadth** (`-09-41a`): of **441**
cells — 21 fields × 7 leads × 3 markets — only **21** are complete, `temperature_2m` at every lead
in every market. **Only one of the two hosts is the PIT surface**; **"`previous_runs=` is a leakage
trap" is RETRACTED** (host-specific, not general).

**The retrain now blocks on 14 cells, not on the corpus.** Denver **2025-07-28** has 17 WU hourly
rows against a floor of 18. **The gap is unfillable — WU, METAR and NOAA GHCN-hourly return the
identical 17 timestamps**, so the station did not report. Only **2 market-days in 1,740** fail, both
Denver. **The floor of 18 is NOT a knob**: `COMPLETE_DAY_MIN_ROWS` also decides whether settlement
trusts the WU daily summary and feeds day-completeness for the streak. The fix is a code-owned
exclusion list (`-09-42a`), never a lower floor.

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
| `-09-39a` | train/serve parity — **base of the corpus stack** | verified 24 unexpected → 0; awaiting merge (**roll-sensitive**) |
| `-09-41a` | honest vs rich corpus (supersedes `-38a`/`-40a`) | **NO CANDIDATE.** PIT **21/441**, **12,180/12,180** rows, honest/rich/hybrid selector built; **correctly stopped at 12,586/12,600** |
| `-09-42a` | exclude Denver station-days, then fit | **NO CANDIDATE.** Exclusion contract built (`first_retrain_station_day_exclusions_v1`, 899 market-days / 12,586 cells); all three fits ran, **none qualifies** — rich's interval includes zero, **power 0.054** |
| `-09-35a` | rotate snapshot + observation-trigger logs | written, NOT dispatched |
| `-09-33a` / `-09-28a` | season window (**contained by `-09-39a`**) / input-surface gate | awaiting merge (roll-sensitive) |
| `fix-wu-404` | scraper 404 misclassification | **SUPERSEDED by `-09-37a`** — do not merge, it conflicts |

**MERGED 08-07:** `-09-29a`/`-31a`/`-32a`/`-34a`/`-36a`. `-09-29a` **revived the learning loop** —
`daily_learning.json` and the market-beating scoreboard were 28 days stale and now write daily; the
scoreboard reads **BLOCK, `weather_only_model_proof_packet` missing**, the first time it could name
its own blocker rather than not run. **MERGED 08-08 01:20/01:25:** `-09-37a` + `-09-14a`, capture
healthy across both rolls. Merges run daily off allowlists (**not** auto-discovery — some branches
are held deliberately): `WeatherMergeQueueDriver` 05:15 roll-free, `WeatherMergeSensitiveDriver`
01:20.

## Open, unowned

- **Settlement: the SOURCE is fixed, a CONTAINMENT RACE now blocks it.** `-09-37a` merged 01:20
  08-08 and works — `public_wu_settlement_restore` ran **699 s, 40 processes, 15.9 GB read**, real
  work. It then failed `containment_setup_failed` on **one transient
  `OSError [Errno 31]` in 1 of 3,402 capture calls** (`process_identity_query_failed`, a process
  exiting between handle-open and query). **18 of 19 lifetime checks PASS**; the only false one is
  `no_capture_failures`, and `windows_process_lifetime.py:92` is `PASS if all(checks.values())`.
  A 1-in-3,402 benign race hard-stops the chain. There is already a
  `capture_failure_cardinality_bounded` check, so tolerating bounded transients fits the design.
  **Unowned.** Settlement frozen at **2026-08-04**; streak **15/14 banked and safe**.
  [wu-settlement-source-down-2026-08-07.md](wu-settlement-source-down-2026-08-07.md).
- **Capture memory pressure is the live streak risk, not the network.** 2026-08-07: **430**
  `capture_host_memory_admission` refusals 11:00–18:00, RAM down to **13 MB** against **3.49 GB**
  per worker → two in-window gaps and the day **AT_RISK**. Cause: a **duplicate
  `market_making_run` orphan** holding 431 MB, because a daily-roll supervisor stops only the pid
  in its status file, so a start-race orphan is **unreapable** (same class as the taker orphans of
  06-30 / 07-04). Killed by hand; `staleness_sweep.ps1` §12 detects it now. **The code fix is
  unowned.**
- **MM SCORED ITS FIRST COUNTABLE DAY IN 42 (2026-08-08).** `live_forward_gate` **PASS**,
  `counts_toward_live_forward_gate` **true**, `paper_trading_evidence` **12/12** — and
  `live_trade_permission_evidence` is **still 0/12**, which proves live trading was never required
  for a countable paper day. Standing count **3 → 4 of 55**; the gate needs 22–43.
  It was never blocked on live permission — that lane reads 0/12 only because
  `mode != "live-pilot"`, which is *correct* in paper mode and **not required for paper evidence**.
  Two real blockers, both now cleared: `clob_freshness` (one 120.0 s gap poisoned a whole
  market-day, since the gate takes the **max gap across the DAY**) — fixed by `-09-14a`; and
  **`exchange_economics_gate`, which was stale because
  `WeatherExchangeEconomicsSnapshotRefresh` HAD NEVER BEEN REGISTERED.** The register script sat
  in `scripts/ops/` unused. **18 of 20 economics checks always passed** — only
  `target_date_matches` and `verified_at_recent` (24 h max age) failed. Now armed daily at 06:50
  and proof-run. **The repo's own register script would NOT have fixed it**: it passes no
  `-TargetDate`, so the refresh defaults to *yesterday* — right for the settlement chain, wrong
  for the maker, which targets today.
- **Resolution / sharpness** — still the larger half of the gap; `-09-36a` localised only ~7% of
  it and found no usable signal. Nothing is aimed at the remaining ~93%.
- **Disk: ~12 days headroom** (130.4 GB free, ~11 GB/day). **The taker is PAUSED — operator
  decision 2026-08-07, 100% focus on the maker.** Both its tasks are Disabled and its tree went
  26.67 → 7.51 GB; the quoted **74.7 GB was stale**, it was 26.67 GB when measured. What remains
  is `CANONICAL_EVIDENCE` and was kept deliberately
  ([record](taker-paused-and-pruned-2026-08-07.md)). CLOB tiering *is* working — 1.4 GB
  `order_books_long.csv` → 62.6 MB `.gz` — so the 35 GB of `/MIR` "Extras" is **not** data loss.
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
