# State of play

**Last rewritten: 2026-08-08.** Read this first, then `ESTABLISHED_FINDINGS.md`.

> **REWRITTEN, never appended. Capped at ~90 lines.** The one document answering *"what is happening
> right now?"* `ESTABLISHED_FINDINGS` owns what we know, `RETRACTED_AND_FALSE_LEADS` what is false,
> `AGENT_CONTEXT` invariants, `DELEGATION_CONTRACT` how to work. **Over the cap means something
> stopped being current — cut it**; stale content here is believed rather than ignored.

**Objectives:** 1. protect the Toronto capture streak · 2. **find a model that beats the market —
we do not** · 3. the market-making bot is the end goal.

## Where the model actually stands

**THE BLIND-BLOCK REPAIR DID NOT MOVE THE GAP, AND THAT IS NOW MEASURED PRECISELY** (`-09-44a`, §4).
`-09-43a` routes 9 of the 10 dead base features — parity **196 → 100 blockers, 0 unexpected** — and
**7,112 of 12,289 served distributions changed.** The in-season gap went **1.423260x → 1.423246x**,
paired delta **−0.0000140 [−0.0022674, +0.0024795]** on D=50 / M=12 / 524 market-days.

**That interval is tight, not empty.** The reported power `0.050` is plug-in power at an observed
effect of ~0, so it is the α floor and means nothing; the *interval* is the result. The gap sits
0.4233 above parity, so **the repair moved it by at most ~0.6% of the distance to parity.** This is
the project's first **precise** null — every earlier "not powered" was a wide interval that licensed
nothing.

**So input completeness was a correctness problem, not a skill problem. Do not sequence work as
though finishing the input population will close the gap.** Remaining input work (`wind_group`,
F-market pressure, `humidity` going forward) is still owed, but never costed as gap closure.
`pressure` stays dead in the 11 F markets **correctly** — METAR carries altimeter/sea-level, the
trained feature is *station* pressure; aliasing would pass a presence check and be false.

**Four legacy headlines are retired from citation** (§1): `98.88%/1.12%` → **84.772% / 15.228%**,
`−0.6641 C-eq` → **−0.64387**, `4.26%/60.2%` → **4.387% / 64.140%**, and **`74.97%` is unciteable
with no replacement** — so the retrain's centre argument is now §2's −0.8346 C-eq alone, which is
smaller than the programme assumed. **The reliability share went 1.12% → 15.228% on panel change,
not on the repair; whether any of it is recoverable is NOT established — check the denominator
before anyone fits a recalibration.**

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

- **Do not re-open "will completing the inputs close the gap?"** — `-09-44a` answered it: **no**,
  with a tight interval. Also **the free-source blindness repair is NO-GO** (`-09-26a`) — that
  measured filling from *external* sources at 8.90% coverage, never captured-data routing.
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
| `-09-44a` | **RETURNED — the gap did not move** | report-only, 278 lines, **QUEUED 01:20 after `-09-43a`**. Roll-sensitive *only* by inherited base; roll-free once `-09-43a` lands |
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
- **THE CHAIN HAS BEEN DEAD AT STEP 4 SINCE 08-04 — fix queued 01:20.** Not "settlement is behind":
  it runs 4 of ~45 steps and stops, so **settlement, maker paper scoring, every `mm_*` gate (all
  null) and variant learning (SKIPPED) never run at all.** One transient `OSError [Errno 31]` in
  1 of 3,402 capture calls fails `containment_setup_failed`; 18 of 19 lifetime checks PASS.
  **A null there is ABSENT evidence, not weak evidence.** After the fix lands, **08-05 → 08-07 need
  an explicit backfill via `chain_recovery_run.ps1` — each run settles only yesterday.** Streak
  **15/14 banked and safe**. [detail](wu-settlement-source-down-2026-08-07.md).
- **Start-race bot orphans are unreapable, and they starve capture.** The supervisor stops only the
  pid in its status file; on 08-07 a duplicate maker caused **430** memory-admission refusals and
  put the streak day **AT_RISK**. `staleness_sweep.ps1` §12 detects it; **the code fix is unowned.**
- **MM: first countable day in 42 scored 08-08** — gate **PASS**, standing **4 of 55** against a
  22–43 bar, so the binding constraint is now just **elapsed countable days**. **Live trading was
  never required** — `live_trade_permission_evidence` is still 0/12 and the gate passes anyway.
- **RESOLUTION IS NOW THE WHOLE GAME, AND NOTHING IS AIMED AT IT.** `-09-44a` ruled out inputs;
  §1 retired the centre ceiling; `-09-36a` localised only ~7% of the sharpness deficit and found no
  usable signal. **84.772% of served loss is resolution and we have no line of work on it.** The
  one cheap, unclaimed lead is the **15.228% reliability share** — an order of magnitude above the
  retired `1.12%` — which needs its **denominator established before**, not after, someone fits a
  recalibration pass.
- **Disk: ~12 days headroom** (137.8 GB free). The **taker is PAUSED** (operator, 2026-08-07);
  what remains is `CANONICAL_EVIDENCE` ([record](taker-paused-and-pruned-2026-08-07.md)).
- **`pytest -q` on master is GREEN** — **3,349 passed, 829 subtests, 0 failed** once tonight's
  schema-literal branch lands. **If something is red, it is yours — there is no known-red baseline
  to hide behind.** (The four failures this file used to list are fixed and two never failed;
  `test_tracked_artifact_manifests_match_current_repository_identity` only trips on *untracked*
  files, so it is red mid-edit and green once staged.)

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
