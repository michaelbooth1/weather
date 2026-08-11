# Agent report 2026-08-27 — point-in-time observation envelope

## Verdict

**`B_MAIN_PATH_RECOVERABLE; C_PREDECLARED_NULL_CONFIRMED; DIRECT_SERVING_UNSAFE;
PRE_REGISTRATION_FROZEN_SAFETY_BLOCKED`.**

A point-in-time append-only WU envelope repairs **748 / 906 = 82.56%** of B decrease events under
either restatement rule. It repairs **all 658 / 658 `M5_cutoff_change` events**, all **78 / 78
`M3_rows_dropped` events**, and all **368 / 368** B events in the predeclared peak-heating plus
settlement windows. The Atlanta `2026-06-13` row is recovered exactly: production served
`84 -> 81` with cutoff `10 -> 9`; the envelope retains the missing 10:52 row, holds
`84 -> 84`, and keeps cutoff 10.

The predeclared C null is exact: **0 / 1,284** C events are repaired under either rule. Every C
feature snapshot falls back to its captured non-WU path because no target-date WU row exists to
union. This leaves the Gate 3 pre-dawn corner untouched.

The same result that establishes feasibility blocks direct serving. Both rules create **55 new
above-settlement feature rows**, all on San Francisco `2026-06-09`; one is a decrease event.
The transient 68 F row was timestamped 13:00, while the next payload reported a new 14:00 row at
67 F. `envelope_last` cannot treat that as a same-timestamp correction, so it correctly retains
13:00/68 F; settlement was 67 F. The counterfactual therefore recovers information and can also
freeze a wrong transient print into the trusted floor.

The required pre-registration is frozen at
`docs/roadmap/observation-envelope-preregistration-2026-09-72a.json`, but it is explicitly
**safety-blocked and not executable**. It selects `envelope_last`, allocates no alpha, authorizes no
outcome look, and requires a new safe candidate plus a new versioned pre-registration before any
Brier, CRPS, market, or C forecast outcome is read.

This mission measured only. It changed no feature, cutoff, producer, floor, collection, replay,
scoring, model, or serving behavior.

## Population and point-in-time integrity

The output reconciles the committed `-09-71a` population one-to-one on
`(stratum, market_id, target_date, snapshot_id, mechanism)`:

| Quantity | B | C |
| --- | ---: | ---: |
| Date clusters | **23** | **27** |
| Market clusters | **12** | **12** |
| Market-days | **204** | **320** |
| Decrease events | **906** | **1,284** |
| Output rows | **906** | **1,284** |

The complete workstation evidence root was
`C:\Users\Michael\Documents\github\weather\data\snapshots`; it yields all 23 B dates. The partial
root that yields only seven B dates was not used. Archive-rebuilt training values came from the
same workstation evidence root under `data/wunderground`. Nothing under either root was written.

The harness streamed **all 524 `replay_inputs.jsonl` files**, not only feature/event payloads:

| Receipt | Value |
| --- | ---: |
| Replay rows / bytes scanned | **85,538 / 31,850,348,940** |
| Unique captured snapshots after exact-key duplicate removal | **85,536** |
| Exact duplicate replay capture keys removed | **2** |
| Raw append-order inversions sorted by `captured_at_utc` | **3** |
| Off-target-calendar-date WU rows excluded | **34** |
| Feature capture states rebuilt | **77,276** |
| Feature capture keys lacking replay | **131** |
| Event/predecessor replay coverage | **4,360 / 4,360** |
| Per-event point-in-time receipts | **2,190 / 2,190** |
| Strict-prior guard failures | **0** |
| Future snapshots consumed | **0** |

Each day is sorted by `captured_at_utc`, with original file position only as the stable tie-break.
At event snapshot `t`, the current payload is admitted and the retained union contains only it plus
strictly earlier snapshots. Every CSV row records `prior_snapshots_used` and
`max_captured_at_utc_used`; the harness asserts the latter is `< captured_at_utc`. The canonical
digest of all 2,190 event receipt records is
`6a0fdd396c08e703cb3d2ec1a467e3953739d22e0abeba1a93d40af07a565b47`.

The 34 off-target WU rows are important, not bookkeeping. A first implementation failed closed on
Toronto `2026-06-15` because a payload contained a `2026-06-14 00:00` row. Excluding those rows is
required by the per-`(market_id, target_date)` envelope definition; retaining them would recover
yesterday's information and create a second leakage path.

## Repair census

The two declared restatement rules give the same event-level result:

| Stratum / rule | Events | Repaired | Repair rate |
| --- | ---: | ---: | ---: |
| B / `envelope_max` | 906 | **748** | **82.56%** |
| B / `envelope_last` | 906 | **748** | **82.56%** |
| C / `envelope_max` | 1,284 | **0** | **0.00%** |
| C / `envelope_last` | 1,284 | **0** | **0.00%** |

### B by mechanism

| Mechanism | Events | Repaired, either rule | Rate |
| --- | ---: | ---: | ---: |
| `M1_restatement` | 2 | **2** | 100.00% |
| `M2_empty_history` | 144 | **9** | 6.25% |
| `M3_rows_dropped` | 78 | **78** | 100.00% |
| `M4_source_switch` | 4 | **0** | 0.00% |
| `M5_cutoff_change` | 658 | **658** | 100.00% |
| `M6_unexplained` | 20 | **1** | 5.00% |
| **Total** | **906** | **748** | **82.56%** |

The dropped-row population the handoff expected to be recoverable is recovered exactly:
`M3 + M5 = 736 / 736`. The largest C mechanism remains exactly the predeclared null:
`M2_empty_history = 0 / 1,278` repaired.

There are WU rows absent from the current payload on 747 B event rows. Their `rows_recovered`
distribution is p50 **1**, p90 **1**, p95 **2**, p99 **10**, maximum **29**. The 748th repaired
event is repaired by point-in-time value history rather than an additional missing timestamp.
C recovers zero rows on every event.

### Placement in local time

| B window | Events | Repaired, either rule | Rate |
| --- | ---: | ---: | ---: |
| Pre-dawn | 218 | **61** | 27.98% |
| Peak heating | 163 | **163** | **100.00%** |
| Remaining settlement | 205 | **205** | **100.00%** |
| Other | 320 | **319** | 99.69% |
| **Peak + settlement** | **368** | **368** | **100.00%** |

The manifest contains the exact repair count and rate for every observed `minute_of_day`; the CSV
retains the minute on every event. C remains zero in every window, including its 1,049 pre-dawn
events and 80 peak-plus-settlement events.

## Feature movement, in native units

Delta is `envelope high_so_far - served high_so_far` at the event snapshot. No Toronto Celsius
magnitude is pooled with Fahrenheit markets.

| B unit / rule | Rows raised | Unchanged | Mean | p50 / p90 / p95 / p99 / max |
| --- | ---: | ---: | ---: | --- |
| F / `envelope_max` | 113 | 724 | +0.3047 F | 0 / 1 / 2 / 7 / **20 F** |
| F / `envelope_last` | 113 | 724 | +0.3047 F | 0 / 1 / 2 / 7 / **20 F** |
| C / `envelope_max` | 64 | 5 | +1.1449 C | 1 / 2 / 2 / 2 / **3 C** |
| C / `envelope_last` | 64 | 5 | +1.1449 C | 1 / 2 / 2 / 2 / **3 C** |

C feature deltas are exactly zero under both rules: 1,160 F events and 124 C events remain on the
captured fallback path.

## Floor safety — why this is not a serving change

Among the 2,190 decrease-event rows, captured serving had zero above-settlement values. The
envelope creates one:

| Stratum / rule | Event rows above settlement | Newly created |
| --- | ---: | ---: |
| B / either rule | **1 / 906** | **1** |
| C / either rule | 0 / 1,284 | 0 |

Across every feature snapshot with replay support:

| Stratum / rule | Available | Served above settlement | Envelope above settlement | New | Resolved |
| --- | ---: | ---: | ---: | ---: | ---: |
| B / `envelope_max` | 28,254 | 7 | **61** | **55** | 1 |
| B / `envelope_last` | 28,254 | 7 | **61** | **55** | 1 |
| C / `envelope_max` | 49,024 | 7,850 | 7,850 | **0** | 0 |
| C / `envelope_last` | 49,024 | 7,850 | 7,850 | **0** | 0 |

All 55 new B rows are San Francisco `2026-06-09`, each exactly **+1 F** above settlement. The first
is decrease event `20260609T171152-0400`: current serving and settlement are 67 F; both envelopes
hold 68 F.

Captured payload trace:

- At `20260609T170137-0400`, the final row is `time=13:00`,
  `datetime=2026-06-09T13:54:24-0700`, 68 F.
- At `20260609T171152-0400`, that row is absent and a new final row is `time=14:00`,
  `datetime=2026-06-09T14:04:25-0700`, 67 F.
- `envelope_last` retains the distinct 13:00 row; this is not a same-timestamp restatement.

That is the exact failure mode the handoff asked this mission to detect. A monotone union cannot
know which transient print settlement will later retract. No settlement clamp is proposed; using
realized settlement to repair the rule would be leakage and would weaken the trusted-floor
contract.

## Train/serve direction

The historical baseline reproduces `-09-70a`: **2,112 / 21,676 = 9.74%** comparable B snapshots
and **45,849 / 48,922 = 93.72%** comparable C snapshots differ from the archive-rebuilt training
value.

On the common B snapshot set where both served and envelope paths have replay plus archive support:

| Rule | Comparable | Closer to training | Farther | Equal | Baseline mismatch -> envelope mismatch |
| --- | ---: | ---: | ---: | ---: | ---: |
| `envelope_max` | 21,554 | **865** | 114 | 20,575 | 2,057 -> **1,564** |
| `envelope_last` | 21,554 | **865** | **113** | 20,576 | 2,057 -> **1,563** |

Native-unit detail selects `envelope_last` without reading a forecast outcome:

| B unit / rule | Comparable | Mean absolute distance, served -> envelope | Closer / farther / equal |
| --- | ---: | ---: | ---: |
| F / either | 19,409 | 0.32696 -> **0.24633 F** | 754 / 113 / 18,542 |
| C / `envelope_max` | 2,145 | 0.15152 -> **0.01958 C** | 111 / 1 / 2,033 |
| C / `envelope_last` | 2,145 | 0.15152 -> **0.01911 C** | 111 / **0** / 2,034 |

On the 749 B decrease-event snapshots comparable to training, either rule moves 80 closer, 2
farther and 667 the same; mismatches fall from 156 to 89. C is unchanged on all 48,913 common
snapshots. The feature repair therefore moves B predominantly toward training and does not widen
the C skew, but floor safety still fails.

## Required end-to-end traces

### Repaired — Atlanta `2026-06-13`

Previous/current snapshots are `20260613T112144-0400 -> 20260613T113204-0400`, captured at
`15:21:44.675351Z -> 15:32:04.120502Z`. The current event receipt uses **67 prior snapshots** and
has `max_captured_at_utc_used=15:21:44.675351Z`, strictly before the current capture.

The current payload has 10 target-date WU rows; the envelope has 11 and recovers one. Production
serves `84 -> 81` with cutoff `10 -> 9`. Both point-in-time rules serve `84 -> 84` with envelope
cutoff `10 -> 10`. No later payload or settlement participates.

### Unrepaired — Chicago `2026-06-14`

Previous/current snapshots are `20260614T011002-0400 -> 20260614T011808-0400`. The current event
receipt uses one prior snapshot and has its maximum prior capture strictly before the event. Both
payloads have zero target-date WU rows, so the envelope is empty and the unchanged fallback serves
`70 -> 68`. Both rules correctly report the event unrepaired.

## Frozen pre-registration and campaign boundary

The frozen file is
`docs/roadmap/observation-envelope-preregistration-2026-09-72a.json`, SHA-256
`42ff19a8aabd01dffe388b870ba8d542fc412f680ff1a61721db9048fbd3f2d7`.

It chooses `envelope_last` because it gives up no measured repair, preserves genuine
same-timestamp corrections, and has one fewer B snapshot farther from training than
`envelope_max`. The choice used only input integrity, settlement-floor safety, and train/serve
parity — no model probability, Brier, CRPS, market price, or C endpoint.

The protocol is frozen as
`FROZEN_PRE_REGISTRATION_SAFETY_BLOCKED_NOT_EXECUTABLE`. Its terminal pre-execution gate requires
zero newly above-settlement rows; the measured value is 55. It therefore authorizes no outcome
scoring. If a future safe candidate is independently specified, it would require a new versioned
pre-registration and an explicit **two-sided alpha 0.0025** allocation before the first outcome
look, using crossed date x market clustering and the standing uniform `q=3.1098893` convention.

This mission allocated and spent zero alpha. The ledger remains **7 of 20 spent, 13 available**.
Decision 10 remains **CLOSED UNUSED** and was not reopened, reassigned, or spent. C settlement was
read only for the expressly required input-integrity floor-safety census; no C forecast score,
market price, candidate probability, endpoint, accept rule, or model selection was computed.

## Support and evidence hashes

The harness read 1,089 input files totaling 31,990,665,748 bytes. The canonical receipt-list digest
is `89ad267a6bcbc7bbd124810a3da78701a158648e50f49c2296fd871b5eade0a8`.
Two complete runs with the final target-date-filtered harness reproduced the CSV and manifest byte
for byte.

| Committed evidence | Bytes | SHA-256 |
| --- | ---: | --- |
| CSV | 521,582 | `2309a8ebb0d41773d77e3e2bc4dfc85f147a9153a4b4e451ed5ee1d813bd7550` |
| Manifest | 486,159 | `4032f7cc52574d238f5c0e1b7770fc28314404add24b393be52d60046e086592` |
| SHA receipt | 103 | `e6e1352a5b8f6ccc40ce5121bf3d073d3a235fd1f5fbca0b077c6b407a60493b` |
| Frozen pre-registration | 7,385 | `42ff19a8aabd01dffe388b870ba8d542fc412f680ff1a61721db9048fbd3f2d7` |
| Harness | 42,158 | `776116e99846cc5a0936498fca16037c2990103b00fdd3759531869fdb3cdae0` |
| Frozen seed | 3,655 | `ce2d1d27073d555dc117e358db4d47311d038278940530e32a366987854b8347` |

This is an exact finite-population input-integrity census. No sampling interval, bootstrap, power
calculation, alpha, or multiple-testing adjustment applies to these counts. No outcome estimate is
present.

## Verification and reproduction

Full workstation reproduction on the host holding the ignored captured evidence:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

Set-Location $repo
& $python .\tools\research\measure_observation_envelope_09_72a.py `
  --repo-root $repo `
  --evidence-root $repo
Get-FileHash -Algorithm SHA256 `
  .\docs\roadmap\observation-envelope-2026-09-72a.csv, `
  .\docs\roadmap\observation-envelope-2026-09-72a-manifest.json, `
  .\docs\roadmap\observation-envelope-preregistration-2026-09-72a.json
```

Expected exit is 0, verdict `POINT_IN_TIME_OBSERVATION_ENVELOPE_MEASURED`, 2,190 event receipts,
zero strict-prior failures, zero future snapshots consumed, 748 / 906 B repairs under each rule,
zero C repairs, CSV SHA-256 `2309a8eb...7550`, and manifest SHA-256 `4032f7cc...6592`.

Production-host acceptance uses committed paths only; ignored workstation evidence is not claimed
to exist there:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-can-we-recover-the-lost-observations-2026-09-72a'
$report = 'docs/roadmap/agent-report-2026-08-27-workstation-observation-envelope.md'

git rev-parse $branch
git show "${branch}:$report"
git show "${branch}:docs/roadmap/observation-envelope-2026-09-72a.sha256"
git show "${branch}:docs/roadmap/observation-envelope-2026-09-72a-manifest.json"
git show "${branch}:docs/roadmap/observation-envelope-preregistration-2026-09-72a.json"
git show "${branch}:tools/research/measure_observation_envelope_09_72a.py"
git show "${branch}:tools/research/measure_observation_envelope_09_72a_seed.json"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

## Branch and roll verdict

Base: `2874c664de27cc05ab689a6cd845356ad3e75585` (`origin/master`).

Branch: `codex/workstation-can-we-recover-the-lost-observations-2026-09-72a`.

Analysis commit: `5cf0a621`.

At the analysis commit, the authoritative repository command returned exit 0 and
**`VERDICT: ROLL-FREE`**: six changed files, zero importable files, live closures `loop`,
`clob_loop`, and `observation_trigger`; the 366.3-hour dormant `clob_enrichment` closure was fully
subsumed by live closure evidence.

Final report-inclusive verdict: **PENDING REPORT COMMIT AND MECHANICAL RECHECK**.

Per-file disposition after the report commit will be recorded here from the same command; no
roll-sensitive source is present in this mission.

## Explicitly not done

- No Brier, CRPS, log loss, forecast outcome, market comparison, interval, bootstrap, power, or
  alpha decision was computed. No candidate was fit or frozen. No C endpoint was created.
- No `high_so_far`, `cutoff_hour`, producer, serving floor, collection, replay, scoring, feature,
  model, calibration, settlement, or production source was changed. The serving floor was not
  weakened or clamped with settlement.
- No production `data/`, tape, ledger, artifact, scheduled task, collector, supervisor, process,
  release, or trading state was written, registered, started, restarted, promoted, or activated.
- No provider, exchange, or other network endpoint was called. Nothing was installed.
- No PR, merge, master update, production checkout change, order, or trade was performed.
