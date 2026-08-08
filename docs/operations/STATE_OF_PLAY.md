# State of play

**Last rewritten: 2026-08-08.** Read this first, then `ESTABLISHED_FINDINGS.md`.

> **REWRITTEN, never appended. Capped at ~90 lines.** The one document answering *"what is happening
> right now?"* `ESTABLISHED_FINDINGS` owns what we know, `RETRACTED_AND_FALSE_LEADS` what is false,
> `AGENT_CONTEXT` invariants, `DELEGATION_CONTRACT` how to work. **Over the cap means something
> stopped being current — cut it**; stale content here is believed rather than ignored.

**Objectives:** 1. protect the Toronto capture streak · 2. **find a model that beats the market —
we do not** · 3. the market-making bot is the end goal.

## Where the model actually stands

**The blind block is repaired and it lands tonight** (`-09-43a`, §4). Parity **196 → 100 blockers,
0 unexpected**; 9 of the 10 dead base features are now routed from our own captured station rows.
Reproduced on this host, not taken on report. **Two caveats decide how you cite it:**

- **It is not powered.** Brier **−0.00816 [−0.02972, +0.00961], power 0.131**. Favourable
  direction, interval crosses zero. **A defect repair, never a scoring gain.**
- **`pressure` and `pressure_trend_3h` stay dead in the 11 F markets, correctly.** METAR carries
  altimeter/sea-level pressure; the trained feature is *station* pressure, materially different at
  Denver's altitude. Aliasing would pass a presence check and be false. Imputation load falls from
  8 of 29 trained inputs to **2 of 29 in F markets, 0 of 29 in Toronto** — *going forward*; the
  retained corpus holds no `rh` and no station pressure and cannot be enriched without synthesis.

**The cool bias is seasonal coverage, not the weather** (`-09-31a`, §2): the archive holds
**May 10 – Jun 30 only, every year**, so in August every date we serve is out-of-season. **But the
gap does not vanish in-season** (`-09-34a`, §4e): served in-season **1.4233x, excluding 1.0** —
nearly unbiased, still losing, on a **resolution** deficit. That contrast is **not powered**.

```
archive window  ->  PIT corpus   ->  parity  ->  first retrain      ->  release #1
  DONE 1740/1740    DONE 12180/12180  0 unexp.   BLOCK 12586/12600      (DEFERRED)
```

**The retrain blocks on 14 cells, not on the corpus.** Denver **2025-07-28** has 17 WU hourly rows
against a floor of 18 and **the gap is unfillable** — WU, METAR and NOAA GHCN-hourly return the
identical 17 timestamps. Only **2 market-days in 1,740** fail, both Denver. **The floor of 18 is NOT
a knob**: `COMPLETE_DAY_MIN_ROWS` also decides whether settlement trusts the WU daily summary and
feeds the streak's day-completeness. The fix is the code-owned exclusion list (`-09-42a`), never a
lower floor. The PIT surface is real but narrow (`-09-41a`): of **441** cells only **21** are
complete. The retrain fixes the **centre** (74.97% of oracle excess loss); **nothing is aimed at
resolution**, which §1 says recalibration cannot supply — **necessary, not sufficient.** Intervals
and power live in §2 / §4 / §4d / §4e — **cite them from there, never from here.**

## Decided — do not relitigate without new evidence

- **Release #1 is DEFERRED** until a retrained candidate exists
  ([why](release-one-deferred-until-a-retrained-candidate.md)) — it would freeze artifacts measured
  a full degree cool. The lock does **not** expire; the 7-day rule is rolling source recency.
- **Free-tier Open-Meteo only, no paid API. Training population 2021–2025.** Closed; **do not stop
  a mission on either.**
- **Nothing is reserved today**; the window arms at candidate freeze.
  `reserved-confirmation-window.md` wins over every other document.

## Do not redo these — they are answered

- **The free-source blindness repair is NO-GO** (`-09-26a`) — that measured filling from *external*
  sources at 8.90% coverage. It never applied to routing **captured** data, which `-09-43a` just did.
- **Contamination is not the lever** (§6): every interval includes zero, and honest ≡ hybrid
  numerically — the 20 extra settled fields contributed nothing.
- **Release #1 is not sufficient for promotion**; whether it is *necessary* is unestablished (§9).
- **Do not tune the severe-tail band-suppression lever before the retrain** (§4d).

## In flight

| Ref | What | State |
| --- | --- | --- |
| `-09-43a` | **blind-feature repair — lands 6 missions in one merge** | verified on this host; **QUEUED 01:20**. Contains `-09-33a`/`-38a`/`-39a`/`-41a`/`-42a`; do **not** queue those separately |
| `tolerate-benign-capture-race` | **restarts the dead chain** | verified on this host; **QUEUED 01:20** |
| `register-two-schema-literals` | last red test on master | based on `-09-43a`; **QUEUED 01:20, must merge after it** |
| `-09-44a` | **re-measure the gap on the repaired model** | written, **next to dispatch — top model item** |
| `-09-35a` | rotate snapshot + observation-trigger logs | written, NOT dispatched |

Merges run daily off allowlists (**not** auto-discovery — some branches are held deliberately):
`WeatherMergeQueueDriver` 05:15 roll-free, `WeatherMergeSensitiveDriver` 01:20. Landed 08-07/08-08:
`-09-29a`/`-31a`/`-32a`/`-34a`/`-36a`/`-37a`/`-14a`. The learning loop is alive again after 28 days
stale, and the market-beating scoreboard reads **BLOCK, `weather_only_model_proof_packet` missing**
— the first time it could name its own blocker rather than not run.

## Open, unowned

- **Two follow-ups the repair created.** (1) The parity gate **cannot reach exit 0** until
  `nine_empty_base_features_09_to_14` is narrowed to `wind_group` — it still demands 9 dead fields
  and only 1 is. Narrowing **records** the repair, it does not weaken it. (2) `pressure` and
  `pressure_trend_3h` should be **dropped from training in the F markets** per §5's
  unknowable-at-serve rule. Neither is started.
- **THE CHAIN HAS BEEN DEAD AT STEP 4 SINCE 08-04 — fix queued for tonight.** Not "settlement is
  behind": the chain runs 4 of its steps and stops, so **settlement, maker paper scoring, every
  `mm_*` gate (all null in the report) and variant learning (SKIPPED) never run at all.**
  `public_wu_settlement_restore` does real work (699 s, 40 processes, 15.9 GB read) then fails
  `containment_setup_failed` on **one transient `OSError [Errno 31]` in 1 of 3,402 capture
  calls** — a process exiting between handle-open and job-membership query. 18 of 19 lifetime
  checks PASS. Fixed by `tolerate-benign-capture-race`, queued 01:20.
  **After it lands, 08-05 → 08-07 still need an explicit settlement backfill — each run settles
  only yesterday.** Streak **15/14 banked and safe**.
  [detail](wu-settlement-source-down-2026-08-07.md).
- **Start-race bot orphans are unreapable, and they starve capture.** The supervisor stops only the
  pid in its status file; on 08-07 a duplicate maker caused **430** memory-admission refusals and
  put the streak day **AT_RISK**. `staleness_sweep.ps1` §12 detects it; **the code fix is unowned.**
- **MM: first countable day in 42 scored 08-08** — gate **PASS**, standing **4 of 55** against a
  22–43 bar, so the binding constraint is now just **elapsed countable days**. **Live trading was
  never required** — `live_trade_permission_evidence` is still 0/12 and the gate passes anyway.
- **Resolution / sharpness** — still the larger half of the gap; `-09-36a` localised only ~7% and
  found no usable signal. Nothing is aimed at the remaining ~93%.
- **Disk: ~12 days headroom** (137.8 GB free). The **taker is PAUSED** (operator, 2026-08-07);
  what remains is `CANONICAL_EVIDENCE` ([record](taker-paused-and-pruned-2026-08-07.md)).
- **`pytest -q` on master is GREEN as of 2026-08-08** — **3,349 passed, 829 subtests, 0 failed**
  once tonight's schema-literal branch lands. This file previously named four failures and **two
  of them do not fail at all** (`test_afternoon_residual_centering`,
  `test_tracked_artifact_manifests_match_current_repository_identity` — the latter only trips on
  *untracked* files, so it fails mid-edit and passes once staged). Two real ones were never
  listed. All four now fixed: the two `test_long_job_guard` failures were **the product working**
  — 64 MiB doubles as the Job private-commit cap and cannot start CPython 3.11, so the child died
  `STATUS_QUOTA_EXCEEDED`; raised to the 256 MiB every other call site in that file uses. The
  paid-provider ratchet was red because two settlement docs quoted the provider host literally.
  **If something is red, it is yours — do not assume a known-red baseline.**

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
