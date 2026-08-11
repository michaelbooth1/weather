# Workstation handoff 2026-09-70a — measure the `high_so_far` population

Written 2026-08-11 by the production agent. Read on `origin/master` and execute.
**No α, no candidate, no fitting, no C endpoint.** This is an input-integrity measurement of a live
serving feature — the same standing as `-09-64a` and `-09-65a`: it audits an instrument and an
input, not a hypothesis about the world.

## 1. What is established, and the exact thing that is not

`high_so_far` is computed as a **maximum** and it **decreases**:

| | B | C |
| --- | ---: | ---: |
| Snapshots scanned | 28,376 | 49,033 |
| Below the running max of `current_temp` already seen that day | **5,283 = 18.62%** | **14,995 = 30.58%** |
| Market-days with ≥1 decrease | **125 / 204 = 61.3%** | **292 / 320 = 91.2%** |
| Total decrease events | **906** | **1,284** |

Largest: denver `2026-06-26` `89.0 → 70.0` in ten minutes; seattle `2026-07-30` `75.0 → 60.1`;
toronto `2026-06-15` `24.0 → 13.0`.

Two mechanisms are **traced**, through captured `replay_inputs.jsonl` payloads:

1. **The upstream series is mutable.** san-francisco `2026-06-09`: three snapshots, same 18
   `wu_history` rows, same `max_times`, same `latest` `12:56` — and the last row's temp changed
   **68 → 67 between fetches**. WU restated a published observation. **`wu_history.max_c` read
   `67.0` in all three**, including while the rows still held a 68. The vendor's summary was right,
   the row was the transient, settlement agreed at 67.
2. **Empty history → fallback to the instantaneous reading.** chicago `2026-06-14` 01:10:
   `wu_history` had `rows=0`, `max_c=None`, so `high_so_far` tracked `current_temp` — `70.0`, then
   `68.0` eight minutes later. Not a maximum of anything.

> **What is NOT established: how the 18.62% / 30.58% divides between these, or whether other
> mechanisms exist. I traced two rows; I did not measure a population.** That is your mission.

Full context: `docs/operations/GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md` §5.

## 1a. Why this is worth a mission — it is not only the floor

`high_so_far` is **not** a floor input that happens to also be a feature. Ten of the model's base
features are **dead at serve** (imputed medians, always — §4). `high_so_far` is one of the **nine
survivors**, and it is the observed-temperature-path one. It also generates:

- `high_so_far_anomaly` (`pooled_feature_assembly.py:749`)
- `forecast_gap` = `forecast_high − high_so_far` (`feature_model.py:1042`)
- `is_extended` (`feature_model.py:1047`)
- `band_minus_high_so_far`, `band_hi_minus_high_so_far`, `band_mid_minus_high_so_far`
  (`pooled_feature_assembly.py:237-239`), the last becoming `floor_gap` in pooled density training
  (`pooled_density_training.py:615`)
- the **intraday analog set** — `feature_model.py:1356-1358` selects matching training days by
  `round_half_up(high_so_far)`

A wrong value does not perturb one column. It moves the set of days the prediction is built from.

**`-09-44a`'s precise null does not transfer here, and I want you to hold that distinction.** That
null repaired features that were **dead** — constants the model had learned to ignore. This is a
feature that is **alive and wrong**: the model conditions on it. That is a reason the prior does not
apply, **not** a reason to expect a win. Returning a clean null here is a fully successful mission.

## 2. What to do

### 2a. Classify every decrease event by mechanism

Emit `docs/roadmap/high-so-far-decreases-2026-09-70a.csv` with a `-manifest.json` and `.sha256`
beside it, exactly as `-09-65a` did. **One row per decrease event** (~2,190 expected: 906 B +
1,284 C). Reconcile your count against the table in §1 and **say so if it differs** — a different
population is itself a finding, not a detail to quietly absorb.

| Column | Meaning |
| --- | --- |
| `stratum` | `B` or `C` |
| `market_id`, `target_date`, `snapshot_id` | join key — `snapshot_id` verbatim, do not reformat |
| `local_time`, `minute_of_day` | when in the day it fired |
| `high_so_far`, `prev_running_max`, `drop_degrees` | the event and its magnitude |
| `wu_history_rows`, `wu_history_max_c`, `wu_current_max_since_7am_c`, `current_temp` | the candidate fields, as captured |
| `rows_changed`, `rows_dropped`, `latest_datetime_changed`, `cutoff_hour_changed` | the discriminants |
| `source_kind` | `wu` / `station` / `eccc` / other, as the payload identifies it |
| `mechanism` | your classification, from the fixed set below |
| `settled_high` | the day's settled high |

Classify into a **fixed set**, so the residual is visible:

- `M1_restatement` — rows present in both, same count and same `latest`, a row's temp changed
- `M2_empty_history` — `rows=0` or `max_c=None`; `high_so_far` tracked `current_temp`
- `M3_rows_dropped` — the series lost rows between snapshots
- `M4_source_switch` — the feature resolved through a different source at the two snapshots
- `M5_cutoff_change` — `cutoff_hour` moved (**measure it, do not assume**: SF *widened* 13 → 14 as
  `high_so_far` fell, so the natural guess is already falsified once)
- `M6_unexplained` — **report this number first and prominently.** If it is large, we do not
  understand a live serving feature, and that is the headline regardless of everything else.

### 2b. The counterfactual — was the right answer already in the payload?

At every decrease event we hold three candidates: `max(rows)` (what we use), `wu_history.max_c`, and
`wu_current.max_since_7am_c`. For each, report **separately for B and C**:

- **Is it monotone within the market-day?** (the property `max(rows)` fails)
- **How often does it exceed the day's settled high?** — the floor-safety property. A floor above
  the settled high is what produces an irreversible `0.0`.
- On the two known blocking rows (chicago `2026-06-14` 01:10, san-francisco `2026-06-09` 17:01),
  what would each candidate have served?

**This is a measurement, not a proposal.** Do not recommend switching the floor to `max_c`; do not
change `high_so_far`, the floor, or collection. Produce the numbers a serving change would need.

### 2c. Train/serve — two implementations of the same maximum

There are **two separate call sites**, and I want to know whether they agree:

```
src/weather/model/feature_store.py:1232        high_so_far = max(temps_before)   # SERVE
src/weather/calibration/feature_model.py:996   high_so_far = max(temps_before)   # TRAIN
```

Serving computed it from the rows **as they were at that moment**. Training rebuilds it from the
**archived** history. If WU restates published observations — and §1 has one traced instance — those
are two different series, and the training corpus holds a value production never saw.

For each panel market-day, compare the `high_so_far` recorded at serve time against the value the
training path computes from the archive today. Report the count, the magnitude distribution, and
the sign. **A systematic difference here is train/serve skew on a live feature** — the defect class
that has cost this project more than any other (`train-serve-parity-gate`).

### 2d. Where in the day does this land

Report the decrease events by `minute_of_day`, and separately for the **decision-relevant windows**
(`peak_heating_window`, `settlement_window`) versus pre-dawn.

**My predeclared expectation, so it is falsifiable:** `M2_empty_history` dominates and concentrates
pre-dawn — which would make this decisive for Gate 3 (four of the five zero-carrying rows found
anywhere fall between 00:01 and 03:05) but small for the model. **I would rather be wrong.** If the
decreases are spread across the peak-heating window, this is a live feature defect on the model's
main path and a much bigger finding. Report what you measure, not what I expected.

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED** — `-09-63a` retired it and it must not be reassigned.
- **You may read C**, on the same grounds as `-09-64a`/`-09-65a`: no candidate, no fitted parameter,
  no endpoint comparison, no accept rule. **Say so explicitly in the report.**
- **Never pool across `2026-07-31`** (anchor `b77cfbed`). Report B and C separately throughout.
- **Change nothing.** Not `high_so_far`, not the floor, not collection, not the replay, not scoring.
  The canon doc names this exclusion itself. Measuring is the deliverable; a serving change is
  production work that needs a replay measurement first.
- **Never weaken the serving floor.** It is the one shipped win (`1.6639 → 1.4980`), and `-09-63a`
  was right to refuse epsilon mass.
- **A grep is not a trace.** Every mechanism you assign to a class must be checkable from the
  captured payload fields you emit. Walk at least one row of each class end to end in the report.
- `DELEGATION_CONTRACT.md` §2 in full. No provider or exchange calls, nothing written under
  production `data/`, no promotion, activation, release or trading.

## 4. What would close this as a null

- **The decreases are overwhelmingly `M2`, pre-dawn, and small** → the feature is sound where the
  model actually decides, the Gate 3 blockers are a narrow pre-dawn fallback, and the model-input
  concern in §1a is retired. **Write that down with the trace; it is as valuable as the
  alternative,** and it would be the second precise null this campaign has earned.
- **`M6_unexplained` is small and the two known mechanisms account for the population** → we
  understand the feature even if we do not yet fix it. Also a good outcome. Say so plainly.

## 5. Environment, branch and report

The repo venv on that host points at a removed Python 3.11 — use the bundled Codex 3.12 runtime.
**Install nothing.**

- Branch: `codex/workstation-measure-the-high-so-far-population-2026-09-70a`
- Report: `docs/roadmap/agent-report-2026-08-25-workstation-high-so-far-population.md`
- Commit the analysis script and its seed alongside the artifact, as `-09-66a`/`-09-68a` did.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
