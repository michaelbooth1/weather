# Agent report 2026-08-28 — a floor-safe observation recovery rule

## Verdict

**`OBSERVABLE_RECOVERY_CLEARS_INPUT_SAFETY; M1_LABEL_WRONG;
M5_M3_POSTHOC_FILTER_NOT_A_RULE; PREREGISTRATION_FROZEN_ALPHA_UNALLOCATED`.**

The payload-observable rule clears every predeclared input-integrity gate:

> At capture `t`, trust every row in the current WU payload. Recover a previously published missing
> row only when the current payload contains no row at or after that row's target-date-local minute.

It repairs **744 / 906** B decrease events and **366 / 368** in the peak-heating plus settlement
decision window. On the complete population of **28,254 B feature snapshots with replay support**,
it creates **zero** new above-settlement rows. It consumes zero future snapshots, has zero blank
current or strict-prior event receipts, and leaves zero recovered-row provenance violations. On the
21,554 paired B snapshots comparable to archive-rebuilt training values, mismatches fall from
**2,057 to 1,510**; the rule therefore does not widen the `-09-70a` train/serve skew.

The San Francisco contradiction resolves against the frozen label. The vendor summary stayed at
`latest=12:56`, both payloads contained 18 target-date rows, and positional zipping saw `68 -> 67`.
The actual row identities changed: **`13:00 / 68 F` disappeared and `14:00 / 67 F` appeared**.
This is not a same-timestamp restatement. The frozen `M1_restatement` label is wrong. The other B
`M1` row, Seattle `2026-06-09`, has the same timestamp-replacement shape (`14:00` removed,
`15:00` added), so neither of B's two `M1` labels is a demonstrated restatement.

The handoff's `M5 ∪ M3` arithmetic reproduces exactly as a **post-hoc filter**: 736 repaired events
and 366 decision-window events. It is not a point-in-time candidate. It filters an envelope path
after the transition label is known, even though that envelope had already changed earlier
snapshots; it therefore defines no value for prior or non-event snapshots and cannot be evaluated
on the 28,254-snapshot gate. The nearest stateful interpretation—apply `envelope_last` only at
frozen M5/M3 event snapshots—measures **166 / 906** repairs, **35 / 368** decision-window repairs,
and zero new above-settlement rows. Thus the tidy 736 result dies twice: its San Francisco exclusion
is fitted to a label error, and its post-hoc semantics are not servable.

Because the observable candidate clears, the successor protocol is frozen at
`docs/roadmap/observation-envelope-preregistration-2026-09-73a.json` with status
`FROZEN_PRE_REGISTRATION_SAFETY_CLEARED_ALPHA_UNALLOCATED_NOT_EXECUTABLE`.
`outcome_scoring_authorized`, `allocated_now`, and `spent_now` are all **false**. No outcome was
read, no alpha was allocated, and decision 10 remains `CLOSED_UNUSED_NOT_REASSIGNED`.

This mission measured counterfactual inputs only. It does not authorize a serving change, and a
repaired input is not evidence of a better forecast.

## Raw-payload resolution of the contradiction

### San Francisco `2026-06-09`: revision, not restatement

The harness walks the two replay records end to end and retains their raw replay-line hashes.

| Field | Previous `20260609T170137-0400` | Current `20260609T171152-0400` |
| --- | --- | --- |
| Captured UTC | `2026-06-09T21:01:37.254676+00:00` | `2026-06-09T21:11:52.019691+00:00` |
| Target-date row count | **18** | **18** |
| Vendor `summary.latest` | `12:56 / 67 F` | `12:56 / 67 F` |
| Vendor summary max | `67 F` | `67 F` |
| Actual last row | **`13:00 / 68 F`** | **`14:00 / 67 F`** |
| Replay-line SHA-256 | `ee251d6a80cdfa9fe0cfce686eb5c2afb10483ef748730383c91d025ee4702c7` | `b0a3341c1fa6b4f91c2cf9f2c5da83c45fd9e66e9efb11045436fc3c918855a2` |

The row-identity diff is removed minute **780**, added minute **840**, and zero same-minute value
changes. `-09-70a` called this `M1_restatement` because it compared the stale summary latest field,
equal row counts, and temperatures at the same list position. Position 17 changed both timestamp
and temperature. The observable rule sees the new 14:00 row at or after 13:00, trusts the current
payload, and allows `68 -> 67`; settlement was 67 F.

### Atlanta `2026-06-13`: tail loss

| Field | Previous `20260613T112144-0400` | Current `20260613T113204-0400` |
| --- | --- | --- |
| Captured UTC | `2026-06-13T15:21:44.675351+00:00` | `2026-06-13T15:32:04.120502+00:00` |
| Target-date row count | **11** | **10** |
| Vendor latest | **`10:52 / 87 F`** | **`09:52 / 84 F`** |
| Raw identity diff | `10:52` present | minute **652 removed**, nothing added |
| Replay-line SHA-256 | `ecb16ee230b8c3d9066a549863406eed2f96119c6ce22d70a6957065adce75d2` | `e76f8e760e9ce146b43dbd8a2096a57400cd834e39c75292ea54a36d1ba22942` |

Nothing in the current payload is at or after 10:52, so the rule recovers that row. Under the
historical cutoff semantics, serving moved `84 -> 81` with cutoff `10 -> 9`; the candidate stays
`84 -> 84` with cutoff 10. No later payload or settlement participates.

These traces use parsed row identities, not a grep and not vendor summary fields.

## Head-to-head comparison

Every full-snapshot number below is an exact census of the same **28,254** replay-supported B
feature snapshots. The paired train/serve denominator is 21,554 for each stateful rule.

| Rule | B events repaired | Decision window repaired | New above settlement | Paired mismatch, baseline → candidate | Closer / farther / equal | Disposition |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `envelope_max` | 748 / 906 | 368 / 368 | **55** | 2,057 → 1,564 | 865 / 114 / 20,575 | Safety fail |
| `envelope_last` | 748 / 906 | 368 / 368 | **55** | 2,057 → 1,563 | 865 / 113 / 20,576 | Safety fail |
| `M5 ∪ M3` | **736 / 906 post-hoc; 166 / 906 stateful** | **366 / 368 post-hoc; 35 / 368 stateful** | **not defined post-hoc; 0 stateful** | not defined post-hoc; 2,057 → 1,992 stateful | not defined; 73 / 0 / 21,481 stateful | Label wrong and post-hoc rule non-servable |
| **Observable no-row-at-or-after** | **744 / 906** | **366 / 368** | **0** | **2,057 → 1,510** | **862 / 57 / 20,635** | **Clears** |

The observable repairs by frozen historical label are:

| Frozen label | Repaired | Of |
| --- | ---: | ---: |
| `M5_cutoff_change` | **658** | 658 |
| `M3_rows_dropped` | **77** | 78 |
| `M2_empty_history` | **9** | 144 |
| `M1_restatement` | 0 | 2 |
| `M4_source_switch` | 0 | 4 |
| `M6_unexplained` | 0 | 20 |
| **Total** | **744** | **906** |

The one unrecovered M3 row is Los Angeles `2026-06-09` at snapshot
`20260609T143649-0400`: minute 653 disappeared, but the current payload still published a later
row, so the observable rule deliberately trusts the revision. The two unrepaired decision-window
events are exactly the San Francisco and Seattle timestamp replacements mislabelled M1.

Across the full B safety population, captured serving has 7 above-settlement rows. The observable
candidate has 6, creates **0**, and resolves 1. It never clamps to settlement.

## Train/serve direction and native units

The historical positive control reproduces `-09-70a`: **2,112 / 21,676 = 9.7435%** comparable B
snapshots differ from archive-rebuilt training values. On the common 21,554 candidate-comparable
rows, baseline mismatches are 2,057 and candidate mismatches are 1,510.

Movement remains separated by native unit:

| Native unit within B | Comparable | Baseline mismatch → candidate | Closer / farther / equal |
| --- | ---: | ---: | ---: |
| F | 19,409 | 1,924 → 1,485 | 751 / 57 / 18,601 |
| C | 2,145 | 133 → 25 | 111 / 0 / 2,034 |

No Celsius magnitude is pooled with Fahrenheit. This is input parity only, not an outcome or skill
claim.

## Population, receipts, and positive controls

The complete workstation evidence root used was
`C:\Users\Michael\Documents\github\weather\data\snapshots`, yielding all **23 B dates**. The
partial root that yields only seven B dates was not used. Archive-rebuilt values came from
`data/wunderground` under the same workstation root. Nothing under either ignored evidence root was
written.

| Quantity | B | C |
| --- | ---: | ---: |
| Date clusters | **23** | **27** |
| Market clusters | **12** | **12** |
| Market-days | **204** | **320** |
| Decrease events | **906** | **1,284** |

The harness streamed all 524 `replay_inputs.jsonl` files:

| Receipt | Value |
| --- | ---: |
| Replay rows / bytes scanned | **85,538 / 31,850,348,940** |
| Feature capture states / snapshot receipts | **77,276 / 77,276** |
| Feature capture keys lacking replay | **131** |
| Off-target-calendar-date WU rows excluded | **34** |
| Raw append-order inversions sorted | **3** |
| Event receipts | **2,190** |
| Blank current event receipts | **0** |
| Blank strict-prior event receipts | **0** |
| Future snapshot / event receipts | **0 / 0** |
| Strict-prior recovered-row failures | **0** |

Snapshot receipt digest:
`1837c93b88872195f8ca8e646eb31db53beb1d58ff560afd7dbea4d17267762d`.
Event receipt digest:
`3e991e7f16e0974d2858fe1669b71ec9541456ff491c5a64051e70ef4a4b1049`.

The extended harness reproduces every retained `-09-72a` positive control before accepting the new
result: both envelopes repair 748 / 906 B and 368 / 368 decision-window events; C remains
0 / 1,284; both envelopes create 55 new B above-settlement rows and zero C rows; future consumption
and strict-prior failures remain zero.

C was read only for these input-integrity positive controls and floor receipts. The new B candidate
is a captured-serving passthrough on C. No C candidate, endpoint, probability, forecast score,
market price, accept rule, or selection was created. B and C were never pooled across the
`2026-07-31` provenance boundary.

This is an exact finite-population input-integrity census. No sampling interval, crossed bootstrap,
power calculation, alpha look, or multiple-testing adjustment applies. There is no outcome estimate
in this report.

## Frozen successor protocol

The successor pre-registration selects
`point_in_time_wu_observable_tail_recovery_v2` and binds the harness, versioned seed, CSV, and
manifest. Its SHA-256 is
`481689ddbe6ba1058047386ab627b7290f6ee03915fdedad5e1d4c265864e211`.

The prior B-only outcome protocol is carried forward but cannot execute:

- `outcome_scoring_authorized: false`
- `alpha.allocated_now: false`
- `alpha.spent_now: false`
- `ledger_decision_id: null`
- ledger unchanged at **7 of 20 spent, 13 available**
- decision 10 remains **CLOSED UNUSED** and is not reassigned

The operator must allocate and authorize the first outcome look in a later mission. This mission did
not compute Brier, CRPS, log loss, probability outcomes, market comparisons, or power.

## Artifacts and reproducibility

Two complete runs with the finalized harness reproduced every committed output byte for byte. Each
final run completed in about 90 seconds with bundled Codex Python 3.12; nothing was installed.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| CSV | 766,134 | `871c5308805e531c34999258018551cb65a6e348812cd2f7480afc4a20f96288` |
| Manifest | 306,657 | `1e6407d31758759579d20b31350262d6893e7e54d110448e249a6959c30052d5` |
| SHA receipt | 108 | `69b6fb05c0e8e0b619c9c79df6b5da49659b2f85b234292a4a0a00821e1dea57` |
| Frozen pre-registration | 7,154 | `481689ddbe6ba1058047386ab627b7290f6ee03915fdedad5e1d4c265864e211` |
| Harness | 65,583 | `11624223857a3eba71bf2275c0700ee338a09a42132ff9708fc76d12896fe676` |
| Versioned seed | 5,837 | `ad3337ffe4a7a6325583abb807df65842924ff7a0d30af2657399cee33e45df4` |

Input support is 1,094 receipts / 31,991,726,687 bytes; the canonical input-receipt digest is
`e321f86048ada109ca4270f75f6ce63215958b9f729087d338072ac242650415`.

Full workstation reproduction on the host holding the ignored captured evidence:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

Set-Location $repo
& $python .\tools\research\measure_safe_observation_recovery_09_73a.py `
  --repo-root $repo `
  --evidence-root $repo
Get-FileHash -Algorithm SHA256 `
  .\docs\roadmap\safe-observation-recovery-2026-09-73a.csv, `
  .\docs\roadmap\safe-observation-recovery-2026-09-73a-manifest.json, `
  .\docs\roadmap\observation-envelope-preregistration-2026-09-73a.json
```

Expected exit is 0 with verdict
`OBSERVABLE_RECOVERY_FLOOR_SAFE_PREREG_FROZEN_ALPHA_UNALLOCATED`, 744 / 906 B repairs,
366 / 368 decision-window repairs, zero new above settlement across 28,254 B snapshots, and all
receipt counters zero.

Production-host acceptance uses committed paths only; ignored workstation evidence is not claimed
to exist there:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-a-safe-recovery-rule-2026-09-73a'
$report = 'docs/roadmap/agent-report-2026-08-28-workstation-safe-recovery-rule.md'

git rev-parse $branch
git show "${branch}:$report"
git show "${branch}:docs/roadmap/safe-observation-recovery-2026-09-73a.sha256"
git show "${branch}:docs/roadmap/safe-observation-recovery-2026-09-73a-manifest.json"
git show "${branch}:docs/roadmap/observation-envelope-preregistration-2026-09-73a.json"
git show "${branch}:tools/research/measure_safe_observation_recovery_09_73a.py"
git show "${branch}:tools/research/measure_safe_observation_recovery_09_73a_seed.json"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

## Branch and roll verdict

Base: `97bce2d3d9207844c1c8310697b661f6700e115a` (`origin/master`).

Branch: `codex/workstation-a-safe-recovery-rule-2026-09-73a`.

Analysis commit: `52e985a6`.

At the analysis commit, the authoritative repository command returned exit 0 and
**`VERDICT: ROLL-FREE`**: six changed files, zero importable files, with live closures `loop`,
`clob_loop`, and `observation_trigger`. The 367.1-hour dormant `clob_enrichment` closure was fully
subsumed by live closure evidence.

| Changed path | Mechanical disposition |
| --- | --- |
| `docs/roadmap/observation-envelope-preregistration-2026-09-73a.json` | Roll-free frozen research protocol |
| `docs/roadmap/safe-observation-recovery-2026-09-73a.csv` | Roll-free committed evidence |
| `docs/roadmap/safe-observation-recovery-2026-09-73a-manifest.json` | Roll-free committed manifest |
| `docs/roadmap/safe-observation-recovery-2026-09-73a.sha256` | Roll-free evidence receipt |
| `tools/research/measure_safe_observation_recovery_09_73a.py` | Roll-free one-off research harness; outside package roots and every live closure |
| `tools/research/measure_safe_observation_recovery_09_73a_seed.json` | Roll-free versioned research seed |
| `docs/roadmap/agent-report-2026-08-28-workstation-safe-recovery-rule.md` | Roll-free Markdown report |

## Explicitly not done

- No alpha allocation or spend, Brier, CRPS, log loss, probability outcome, market comparison,
  interval, bootstrap, power calculation, C endpoint, or ledger decision was made.
- No `high_so_far`, `cutoff_hour`, producer, serving floor, collection, replay, scoring, feature,
  model, calibration, settlement, or production source was changed. The floor was not weakened or
  clamped to settlement.
- No production `data/`, tape, ledger, artifact, scheduled task, collector, supervisor, process,
  release, or trading state was written, registered, started, restarted, promoted, or activated.
- No provider, exchange, or other network endpoint was called. Nothing was installed.
- No PR, merge, master update, production checkout change, order, or trade was performed.
