# Workstation report 2026-08-05 — why is the maker starved?

## Verdict

The headline `99 NO_QUOTE_STALE_INPUT / 33 NO_QUOTE_KNOWN_EDGE_PERMISSION`
does not describe the August 4 active window. It is the final 132-row tick at
`2026-08-05 02:59:49–03:01:09 America/Toronto`, after an August 4 maker had
continued past its `07:00–20:00` evidence window. At that time nine markets had
already advanced to August 5 in their native time zones, so their producers no
longer wrote the August 4 folders that the old maker still read. The three
Pacific markets were still on August 4. That target-date rollover explains the
exact nine-versus-three split.

There was nevertheless a real freshness failure inside the August 4 active
window. At `2026-08-04T16:58:40.372723Z` (`12:58:40 Toronto`) the global
observation watcher was `152.371s` old against the maker's `120s` limit. Eleven
markets emitted 11 stale-input band rows each. Miami had the same stale watcher
age but emitted `NO_QUOTE_MISSING_PREFLIGHT` because its harder source-status
degradation block took precedence. Every market's model row and trailing CLOB
row was within its freshness limit at that decision, and neither input breached
its limit at any of the 530 retained active-window decisions per market.

The watcher breach was not caused by twelve-market model or CLOB sampling. The
nominal 60-second observation iteration beginning at
`2026-08-04T16:56:08.001966Z` processed six observation triggers synchronously,
including forced model snapshots, and the next iteration did not begin until
`16:59:02.127308Z`: a `174.125s` period. Lowering the sleep interval cannot cure
an iteration whose synchronous work already exceeds the freshness tolerance.

August 5 has no retained maker run or quote-intent tape in this workstation
mirror. The mirrored `daily_roll_status.json` at `04:29 Toronto` says the
expected target was August 5 but the configured `07:05` start had not been
reached. Therefore no honest per-decision August 5 answer exists here. The
pre-window producer artifacts are useful and are reported below, as is the
production host's later read-only CLOB audit from the handoff, but neither is a
substitute for a decision tape.

No source code or operational state was changed. The complete fix touches a
running capture producer and is not roll-safe without a quiet-window deployment
and soak. This branch changes this report only.

## Evidence boundary

The retained decision source is:

`data/mm_runs/2026-08-04/20260804T110502193025Z/quote_intents_long.csv`

It contains 530 distinct decision times in the Toronto `07:00–20:00` window,
6,360 market-decisions, and 69,960 band rows. The first decision is
`11:05:02.193025Z`; the last is `23:59:23.444290Z`. The active-window row counts
are:

| Classification | Band rows | Interpretation |
| --- | ---: | --- |
| `NO_QUOTE_STALE_INPUT` | 121 | Infrastructure: one watcher-stale decision for 11 markets. |
| `NO_QUOTE_MISSING_PREFLIGHT` | 19,976 | Infrastructure/control evidence, chiefly stale target-date event/economics metadata early in the run; Miami also had source degradation. This is not a freshness reason code. |
| `NO_QUOTE_KNOWN_EDGE_PERMISSION` | 45,518 | Legitimate abstention: promotion/known-edge permission refused quoting. |
| `NO_QUOTE_BLOCKED_PROMOTION` | 4,345 | Legitimate abstention: Toronto promotion state was `BLOCK`. |

The handoff's 99/33 counts come from the latest `run_summary.json`, which
summarises one late 132-row tick rather than the active window. The 99 are an
infrastructure/target-selection defect, but they are not proof that three
quarters of the intended active-window decisions were infrastructure-starved.
The 33 permission rows are a correct refusal and must remain refusals.

The workstation mirror contains no `data/mm_runs/2026-08-05` directory. Its
snapshot, CLOB, and watcher evidence ends around `04:30 Toronto`. The handoff's
approximately `11:00` production audit is later evidence supplied by the host;
its gap timestamps and decision joins are not mirrored here.

## Q1 — exact freshness rules and results

### The rules the maker actually applies

| Input | Canonical artifact and value | Freshness rule | Enforcement |
| --- | --- | --- | --- |
| Model row | Latest row in the target event folder's `snapshots_long.csv`; `captured_at_utc` becomes `model_age_seconds`. The source-status proof must also match the latest snapshot and remain current. | Model age must be `<= max_model_age_seconds`, configured as `900s`. Missing rows are a missing-preflight block; excessive age is stale input. | `src/weather/market/market_making_run_support.py:514-616`, especially the `model_freshness` gate at line 596; defaults in `src/weather/market/mm_policy.py:64-66`. |
| CLOB books/features | Latest `order_books_summary.csv` rows and band-level features for the target event folder. `book_age_seconds` on a quote row is the selected trailing row's age. Separately, `preflight_book_audit` scans all capture timestamps in that target folder. | Rows/features must exist. The audit requires no counted internal gap and a trailing capture within the effective threshold. The configured floor is `120s`; on the final August 4 tick loop telemetry raised most market audits to `127.2s`. The later host audit used `140.1s`. | `src/weather/market/market_making_run_support.py:182-228` and `:497-509`; `clob_books`, `clob_features`, and `clob_freshness` gates at `:608-615`; dynamic cycle tolerance in `src/weather/market/market_microstructure.py:609-641`. |
| Observation watcher | `data/snapshots/observation_trigger_status.json:last_heartbeat` plus `consecutive_errors`. This is one global age copied to every market row. | Age must be `<= max_watcher_age_seconds=120s` and `consecutive_errors == 0`. | `src/weather/market/mm_policy.py:960-989`; `observation_trigger` preflight gate at `src/weather/market/market_making_run_support.py:616`. |
| Producer useful work/runtime | Snapshot, CLOB, and watcher status files; recent useful-write timestamps; latest per-market results; runtime identity. | Active-day all-market evidence additionally rejects stale useful writes, stale/missing market rows, nested `stale_code`, nested `blocked`, and runtime identity drift. | `src/weather/market/market_making_run.py:397-691`. |

This distinction explains the audit trap. A quote row's `book_age_seconds` can
be fresh because the current native-date folder has a recent book, while
`preflight_book_audit` can be stale because the maker explicitly asked for an
old target-date folder whose trailing capture stopped hours ago. The host audit
is a historical inter-capture-gap test. Neither is interchangeable with the
other.

### August 4, decision-level active-window result

All ages below are seconds. `max model` and `max book row` are maxima over all
530 active-window decisions. The three ages under `12:58 stale tick` are the
model/book/watcher ages at the only caught watcher breach. Limits are
`900 / 120 / 120`.

| Market | Max model / 900 | Max book row / 120 | 12:58 stale tick: model / book / watcher | Emitted result at that tick |
| --- | ---: | ---: | ---: | --- |
| Atlanta | 592.732 | 59.587 | 147.512 / 10.812 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |
| Austin | 626.623 | 59.238 | 143.288 / 15.109 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |
| Chicago | 630.686 | 59.308 | 220.522 / 12.906 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |
| Dallas | 542.537 | 58.467 | 135.147 / 23.212 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |
| Denver | 567.694 | 59.854 | 490.239 / 28.141 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |
| Houston | 643.895 | 57.020 | 52.501 / 30.810 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |
| Los Angeles | 657.928 | 59.304 | 0.000 / 33.638 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |
| Miami | 638.626 | 59.225 | 376.663 / 6.687 / **152.371** | 11 `NO_QUOTE_MISSING_PREFLIGHT`; source degradation masked watcher staleness |
| NYC | 605.005 | 59.498 | 360.353 / 7.969 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |
| San Francisco | 613.802 | 56.753 | 435.195 / 8.207 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |
| Seattle | 667.575 | 59.754 | 423.316 / 20.054 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |
| Toronto | 624.159 | 58.372 | 500.244 / 18.172 / **152.371** | 11 `NO_QUOTE_STALE_INPUT` |

The watcher diagnostics contain 774 nominal iterations during this window.
Their median period was `60.002s`, p95 `60.014s`, and maximum `227.055s`. Two
periods exceeded 120 seconds:

- `14:54:31Z -> 14:58:18Z`, `227.055s`; no trigger was recorded on the prior
  diagnostic. The maker's sampling phase missed the over-120 portion (its last
  read before recovery saw `98.964s`), so this did not emit stale input.
- `16:56:08Z -> 16:59:02Z`, `174.125s`; the prior iteration handled six
  triggers synchronously. The maker read it at age `152.371s` and failed closed.

### The cited late 99/33 tick

At about `03:00 Toronto` on August 5, the old target remained August 4. The
final preflight recorded:

| Market | Model age / 900 | Target-folder trailing book age / audit threshold | Result |
| --- | ---: | ---: | --- |
| Toronto | 10,938.0 | 10,796.3 / 120.0 | stale model and CLOB |
| NYC | 11,023.3 | 10,796.3 / 120.0 | stale model and CLOB |
| Atlanta | 11,039.4 | 10,796.2 / 127.2 | stale model and CLOB |
| Austin | 7,238.3 | 7,200.5 / 127.2 | stale model and CLOB |
| Chicago | 7,636.6 | 7,200.5 / 127.2 | stale model and CLOB |
| Dallas | 7,691.8 | 7,200.6 / 127.2 | stale model and CLOB |
| Denver | 3,754.0 | 3,591.3 / 127.2 | stale model and CLOB |
| Houston | 7,677.1 | 7,200.6 / 127.2 | stale model and CLOB |
| Miami | 11,091.2 | 10,796.3 / 127.2 | stale model and CLOB |
| Los Angeles | -2.1 clock skew | 0.0 / 127.2 | preflight pass |
| San Francisco | 480.5 | 0.0 / 127.2 | preflight pass |
| Seattle | 518.2 | 0.0 / 127.2 | preflight pass |

The non-Pacific market producers had selected their August 5 native-date
events. Los Angeles, San Francisco, and Seattle were still at 23:59 August 4
local and continued writing the requested folders. The nine stale markets each
had eleven bands: `9 * 11 = 99`. The three fresh-but-unpermissioned markets
each had eleven bands: `3 * 11 = 33`.

This tick was later reclassified with an operator override as active-day
evidence even though `run_config.json` records a local start of `02:59:49`,
outside the declared `07:00–20:00` window. It must not replace the frozen
active-window result.

### August 5 retained pre-window evidence

There are no maker decisions to enumerate. Through approximately `04:30
Toronto`, the producer folders show the following actual capture gaps. The
model limit is 900 seconds; the configured CLOB floor is 120 seconds. Different
first timestamps reflect each market's native midnight, not a fleet outage.

| Market | Max model gap | Max retained CLOB gap | Triggered snapshots blocked as `stale_code` after deployment |
| --- | ---: | ---: | ---: |
| Atlanta | 551.837 | 60.294 | 1 |
| Austin | 564.450 | 60.376 | 3 |
| Chicago | 560.877 | 60.394 | 3 |
| Dallas | 566.276 | 60.165 | 3 |
| Denver | 555.729 | 60.382 | 3 |
| Houston | 569.984 | 60.384 | 2 |
| Los Angeles | 564.886 | 60.410 | 7 |
| Miami | 557.083 | 60.129 | 2 |
| NYC | 623.934 | 60.426 | 1 |
| San Francisco | 774.493 | 60.181 | 1 |
| Seattle | 564.243 | 60.358 | 2 |
| Toronto | 597.837 | 60.158 | 6 |

The watcher itself completed 211 polls from `05:00:17Z` through `08:30:18Z`;
median period was `60.002s`, maximum `60.016s`, and no period exceeded 120.
However, the observation process had loaded `master@1c764f2bc624` before the
`498757fbccd7` deployment. Its direct triggered snapshot guard compared the
loaded identity to the new tree and rejected every triggered recompute shown in
the table. `run_once` then overwrote the status file's runtime identity with a
fresh filesystem identity on every poll, making the process look current to
the outer runtime check. At the late maker preflight the latest iteration's LA
trigger was the nested stale result, so the gate named only LA. The underlying
defect affected all twelve markets and was not caused by LA's clock.

The later production-host CLOB audit supplied by the handoff used a dynamic
`140.1s` threshold and found Denver (two gaps, max `201.0s`), Miami (one,
`207.5s`), and LA (one, `151.8s`), while all twelve were trailing-fresh at
`32.6s`. Those are real audit failures if they fall in the intended folder and
outside startup grace. The mirror does not contain their timestamps or an
August 5 maker tape, so it cannot establish which maker decisions they blocked
or attribute their cause. They are not evidence for the late nine-market
rollover pattern.

## Q2 — root cause against all five hypotheses

### 1. Per-market sequential sampling

Rejected for the nine-market headline and for the active model/CLOB inputs.

- Raw CLOB fleet capture uses a `ThreadPoolExecutor` with the retained status
  showing `raw_max_workers=12`. In the August 4 active window every market had
  a maximum retained CLOB gap between `60.180s` and `61.216s`; row ages seen by
  the maker were all below 60 seconds.
- The snapshot loop uses bounded isolated workers and independent per-market
  due times. Observed active-window maximum model gaps ranged from `631.512s`
  to `714.141s`, all below 900. The maker's actual maximum model ages were
  lower still.
- Observation source polling does walk markets sequentially, and a trigger
  invokes `capture_snapshot(force=True, ...)` inline at
  `src/weather/operations/observation_trigger.py:648`. But the maker gate uses
  one global heartbeat, so sequential position cannot yield nine stale and
  three fresh watcher ages. At the caught tick all twelve had the identical
  `152.371s` age.

### 2. Cadence versus tolerance

Confirmed only for the observation producer's worst case.

- Model: nominal due interval `600s`; observed active maximum gap `714.141s`,
  observed maker age `667.575s`, limit `900s`. This has headroom and did not
  fail.
- CLOB: nominal baseline `60s`, fast mode `15s`; observed active maximum gap
  `61.216s`, observed maker row age `59.854s`, configured floor `120s`. This did
  not fail on August 4. The later August 5 three-market audit says its bound was
  breached and must be cleared separately.
- Watcher: nominal `60s`, but observed maximum periods were `174.125s` and
  `227.055s`, limit `120s`. The synchronous trigger path has no bounded
  completion contract below 120 seconds. This is genuine starvation, not a
  benign threshold typo. Raising the limit would permit observations older
  than a quote TTL and is not the fix.

### 3. Priority contention

Rejected as the cause of the caught failure. `WeatherCapturePriorityGuard`
targets snapshot, CLOB, and observation processes and reasserts `AboveNormal`.
The maker is deliberately lower priority. Despite that, its 530 active ticks
had a median spacing of `85.047s`, p95 `112.936s`, and maximum `125.669s`; it
continued reading while the watcher was busy. At the stale decision, model and
CLOB ages remained healthy. The delay is accounted for by synchronous work
inside the higher-priority watcher, not by the maker starving its producers.

### 4. Memory pressure

Rejected for the caught `16:58Z` watcher breach, but not claimed away for the
unmirrored host gaps. At that tick the maker continued, CLOB books for all
twelve remained 8–34 seconds old, model rows remained below 501 seconds, and
the producer status recorded no all-loop error burst. That is not the previous
host-wide memory-pressure signature. Later retained resource evidence also
showed `9.238GB` available at `05:00Z`, while snapshot worker admission at
`08:29Z` measured `9.948GB` available and admitted two workers under a
`1,792MB` child cap plus `1,536MB` reserve. These observations rule out
sustained pressure; they cannot disprove a transient at the later, unmirrored
Denver/Miami/LA gap timestamps.

### 5. Los Angeles specifically

Two defects were accidentally attached to the same label:

1. LA's later CLOB tape contained a historical gap (`151.8s` in the host audit;
   an earlier `227.4s` gap was ignored as startup in the final August 4
   preflight). This is a book-cadence artifact.
2. LA's triggered snapshot returned `stale_code` at the late gate because the
   whole observation process predated deployment. Every one of the twelve
   markets had at least one identically blocked triggered recompute in the
   retained pre-window console. LA happened to be the latest trigger when the
   maker scanned `last_poll_results`.

LA's local clock does explain why it remained on the August 4 folder while nine
other markets had rolled. It does not explain stale code. The CLOB gap, stale
runtime, and native-date rollover are three separate mechanisms.

## Q3 — fix and roll safety

### Immediate quiet-window recovery

After the final code deployment and before maker readiness is assessed, the
operator should re-adopt the observation process once:

```powershell
.\venv\Scripts\python.exe -m weather.operations.observation_trigger ensure --force
```

Then wait for a complete all-market poll and verify that the process-start
identity—not a filesystem identity rewritten by `run_once`—matches the deployed
tree and that no latest nested result is `stale_code` or `blocked`. This changes
no cadence, adds no loop, and has zero steady-state CPU, memory, or disk cost.
It was not run here because the Toronto streak forbids restarting a capture
loop in this mission.

This one command clears the August 5 deployment drift. It does not solve the
August 4 synchronous-work overrun.

### Required producer repair

The watcher needs a bounded fast lane and a separate bounded recompute lane:

1. Poll all twelve observation states and persist their per-market poll times
   without waiting for a model recompute.
2. Coalesce triggered recomputes by market and submit them to a bounded queue.
3. Let the existing snapshot supervisor consume that queue under its existing
   worker admission, memory ceiling, and cadence protections. Do not add a
   second provider-polling loop and do not manufacture freshness by touching a
   heartbeat while tail markets remain unpolled.
4. Preserve process-start runtime identity in watcher status; do not overwrite
   it with the current filesystem identity in `run_once`.

The acceptance bound is mechanical: observation polling, including status
publication for all twelve, must complete in less than 120 seconds even when
multiple recomputes are queued. Recomputes may finish later; their model rows
still have the independent 900-second contract.

A separate new recompute loop is not accepted without resource proof. It could
overlap the existing snapshot supervisor and add up to another `1,792MB`
working-set peak on a 16GB host. Queueing through the existing supervisor keeps
the present two-worker admission, `1,792MB` per-child ceiling, and `1,536MB`
host reserve. It adds no provider polling and should add zero incremental
snapshot rows or disk per day relative to today's synchronous trigger path;
CPU work is moved, not duplicated. It must retain the capture process priority
and remain subordinate to the streak's existing admission control.

This repair was not implemented. `observation_trigger.py` is imported by the
live observation capture process and directly imports snapshot/model/source
capture code. Changing it is roll-sensitive by actual import closure and
requires a quiet-window re-adoption plus a production soak. The evidence here
is sufficient to specify the contract, not to prove an implementation safe.

### Required maker rollover repair

The maker must finalize and freeze an active-day report at `20:00 Toronto` and
must not keep re-adopting an August 4 target until the August 5 `07:05` start.
Late evaluation can remain available only as explicitly
`post_settlement_evaluation`; it must not overwrite active-day gate evidence or
use an operator override to call a `02:59` start active-day.

This belongs in the maker daily-roll/finalization path, not any weather or CLOB
producer. It reduces late CPU and disk use. It is roll-free with respect to the
Toronto capture streak because the capture loops do not import
`weather.operations.market_making_daily_roll`; it is still maker-evidence
sensitive and needs focused tests before deployment.

### Later CLOB gaps

Do not restart or reconfigure CLOB from this report. Before a day begins, run
the existing read-only audit against the exact target folders. If Denver,
Miami, or LA still has a counted gap above the effective cycle threshold, that
date is not ready. The retained evidence is insufficient to choose a safe CLOB
code or schedule change; any such change would be roll-sensitive because
`market_microstructure.py` and `market_microstructure_capture.py` are imported
by the protected CLOB loop.

### Per-file verdict for this branch and proposed ownership

| File | Changed here? | Import-closure verdict |
| --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-05-workstation-why-is-the-maker-starved.md` | Yes | **Roll-free.** Markdown is not imported by any runtime. |
| `src/weather/operations/observation_trigger.py` | No; proposed owner | **Roll-sensitive.** Loaded by an `AboveNormal` protected producer and closes over snapshot/model/source capture. Requires restart/re-adoption. |
| `src/weather/operations/market_making_daily_roll.py` | No; proposed rollover owner | **Capture-roll-free, maker-sensitive.** Capture loops do not import it; it launches/finalizes maker runs only. |
| `src/weather/market/market_microstructure.py` and `_capture.py` | No | **Roll-sensitive.** Loaded by the protected CLOB producer. No cause-proven edit is authorized. |

The unrelated LFS model artifact shown dirty by this worktree was not edited or
staged.

## Q4 — mechanical definition of an un-starved day

No pre-window test can prove future availability. It can prove that the day is
allowed to start and that each producer has demonstrated a bound inside its
tolerance. The maker must then enforce the same invariant at every decision.

### Before `07:00 Toronto`

For the exact target date and all twelve registered markets:

1. The daily-roll target and evidence classification are current; no previous
   target process is alive, and the run will start inside `07:00–20:00`.
2. The snapshot, CLOB, and observation processes report their process-start
   runtime identities as the deployed tree. Any deployment after process start
   requires a quiet-window re-adoption before this check.
3. Each target folder has a latest model row and matching current source-status
   proof. Its age is at most 900 seconds, and recent per-market capture gaps
   demonstrate a worst case below 900 seconds.
4. Each target folder has current book rows and band features. A read-only book
   audit is `ok:true`: no counted internal gap exceeds the loop-aware effective
   threshold and trailing age is inside it. The later host audit's three failed
   markets would fail this box even though their trailing age was 32.6 seconds.
5. The observation watcher has completed an error-free all-market poll within
   120 seconds, every market has a current per-market poll time, and no nested
   triggered result is `stale_code` or `blocked`.
6. Two consecutive read-only maker preflights one maker interval apart pass all
   twelve markets. This samples the producer phase boundary rather than relying
   on one lucky instant. It must not call providers or write quote evidence.

The present observation implementation cannot establish item 5's worst-case
bound: retained iterations reached 174 and 227 seconds. Therefore the next day
is not mechanically guaranteed un-starved even if a point-in-time preflight is
green.

### At every decision from `07:00` through `20:00`

For every market `m` and decision time `t`, all of these must hold:

```text
model_age(m,t) <= 900s
source_status_for_latest_snapshot(m,t) is current
book rows and band features exist
book_audit(target_folder(m),t).ok is true
observation_watcher_age(t) <= 120s and consecutive_errors == 0
latest producer results contain no stale_code/blocked result
producer useful-write and runtime-identity gates pass
```

Any failure makes the whole fleet-date non-countable. A correct
promotion/known-edge refusal remains a valid zero-action cell; it is not
starvation and must not be converted into a quote. Missing preflight is also
not `NO_QUOTE_STALE_INPUT`, but a countable day must be free of both.

## MM timeline

Registering `WeatherMakerExecutionCapture` is necessary for scoring but is not
sufficient for a countable day. The day after registration is reachable only
after all of the following happen before its window: the observation process
re-adopts the final code, the watcher fast/recompute lanes have a demonstrated
sub-120-second poll bound, the old-target maker rollover is fixed, and the
exact target's all-market CLOB audit passes. Without those, a day might avoid a
trigger burst by luck, but it is not mechanically ready and can still be lost.

Starvation therefore pushes the first defensible countable day out to the first
eligible target date after the quiet-window fixes and one complete pre-window
readiness proof. The reservation is currently armed but undated; no date is
reserved today, so reservation does not add a separate delay. Once a retrain
candidate is frozen, the canonical reservation must be dated before scoring and
MM paper scoring must stop on those dates unless explicitly exempted.

## What would falsify this

- An immutable August 5 maker quote tape covering `07:00–20:00 Toronto` would
  falsify the statement that decision-level August 5 evidence is unavailable.
  It must be analysed directly; producer snapshots or a later audit are not a
  substitute.
- Recomputing the August 4 tape and finding any active decision whose model age
  exceeded 900 seconds or whose CLOB audit failed would falsify the finding
  that the caught active-window stale input was watcher-only.
- Showing that the nine late stale markets were still writing their August 4
  native-date folders at `03:00 Toronto`, or that a different set than the nine
  non-Pacific markets was stale, would falsify the rollover explanation.
- Showing a watcher heartbeat publication between `16:56:08Z` and the maker's
  `16:58:40Z` read, or showing that the six synchronous triggered snapshots did
  not execute in that interval, would falsify the causal attribution of the
  174-second breach.
- A process-start identity proving the August 5 watcher loaded `498757fbccd7`,
  together with successful triggered snapshots during the same interval,
  would falsify the stale-runtime diagnosis. The retained console instead
  records the loaded `1c764f2bc624` identity and blocked triggers for all twelve
  markets.
- Time-aligned resource telemetry showing severe memory exhaustion plus
  simultaneous snapshot, CLOB, maker, and watcher gaps at `16:56–16:59Z` would
  falsify the rejection of memory pressure for the caught event.
- A cause-proven reconstruction of the later Denver/Miami/LA CLOB gap
  timestamps could falsify the decision to leave that root cause unresolved.
- Finally, two complete active windows after current-code re-adoption and
  recompute decoupling, with all twelve markets satisfying the Q4 invariant at
  every decision and zero stale/missing-preflight rows, would falsify the claim
  that starvation still blocks the next countable day.
