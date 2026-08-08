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
| `-09-42a` | exclude Denver station-days, then fit | **NO CANDIDATE.** Exclusion contract built (`first_retrain_station_day_exclusions_v1`, 899 market-days / 12,586 cells); all three fits ran, **none qualifies** — every interval includes zero, **power 0.054–0.146**. **Reconciled with master and QUEUED 01:20** — lands all 5 missions |
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
- **Start-race bot orphans are unreapable, and they starve capture.** A daily-roll supervisor
  stops only the pid in its status file. On 08-07 a duplicate maker held 431 MB → **430**
  memory-admission refusals → the streak day **AT_RISK**. `staleness_sweep.ps1` §12 detects it
  now; **the code fix is unowned.** Same class as the taker orphans of 06-30 / 07-04.
- **MM SCORED ITS FIRST COUNTABLE DAY IN 42 (08-08)** — gate **PASS**, `paper_trading_evidence`
  **12/12**, standing count **4 of 55** against a 22–43 bar. **Live trading was never required**:
  `live_trade_permission_evidence` is *still* 0/12 and the gate passes, because that lane only
  reads `mode != "live-pilot"`. The two real blockers were `clob_freshness` (fixed by `-09-14a`;
  the gate takes the **max gap across the DAY**, so one 120 s stall cost the whole fleet-day) and
  `exchange_economics_gate` — stale because **`WeatherExchangeEconomicsSnapshotRefresh` had never
  been registered**. Now armed 06:50 and proof-run. **The repo's register script alone would not
  have fixed it**: it passes no `-TargetDate`, so the refresh defaults to *yesterday* — right for
  the chain, wrong for the maker.
- **THE CORPUS QUESTION IS CLOSED: contamination is NOT the lever** (§6). Every interval includes
  zero, sign flips by slice, power 0.054–0.146, and **honest ≡ hybrid numerically** — the 20 extra
  settled fields contributed nothing. **That leaves the blindness repair as the only untried model
  lever**: 8 of 10 local-meteorology features dead at serve, ~28% of inputs imputed always, and
  `-09-39a` proved the repair on the other 2 from our own `station_latest`. **`-09-26a`'s NO-GO
  does not apply** — it measured filling from *external* sources at 8.90% coverage, not routing
  captured data. **Unowned; top model item.**
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
