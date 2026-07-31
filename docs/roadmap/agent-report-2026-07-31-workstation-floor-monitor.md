# Agent report - 2026-07-31 workstation floor monitor

Status: **the compensating control is shipped; the redistribution hypothesis
is rejected as a general regression mechanism; queue the C-family candidate
after the Toronto lock.**

This handback executes
`docs/roadmap/workstation-handoff-2026-07-31e-where-the-floored-mass-should-go.md`
from exact `origin/master` `42749c98696e8c0b0e866cac6ec86b95ce6adbfa` on fresh branch
`codex/workstation-floor-mass-2026-07-31e`. The branch was pushed before work.
No `data/` file, release pointer, serving route, promotion state, scheduler,
capture loop, mirror, ACL, paid-provider setting, or master branch was changed.

## 1. Compensating control

Standalone commit `1e0f9e86` (`Monitor served floors against settlement`) was
committed and pushed before the research work.

`weather.reporting.source_gates.observed_floor_safety_monitor` now joins each
captured snapshot's persisted
`probability_calibration_context.observed_floor_bucket` to the finalized
settlement label. It reads the snapshot tape and sibling
`snapshot_explanations.jsonl`; it does not replay the model.

The contract is deliberately fail-closed:

- `PASS`: every captured snapshot has exactly one matching explanation, every
  enforced floor has an attributable rescue source, and none exceeds settlement;
- `ALERT`: at least one floor exceeds settlement; and
- `BLOCK`: evidence is missing, malformed, duplicated, mismatched, or lacks
  floor provenance.

Every alert reports market, target date, snapshot id, floor bucket, settlement
bucket, rescue source, and overshoot in buckets. A non-PASS result sets
`hard_stop_pipeline=true`. The monitor runs after finalized labels as a critical,
non-skippable dependency of `settled_day_analysis_barrier`, so either `ALERT` or
`BLOCK` stops the daily chain rather than becoming a quiet diagnostic.

The report is registered as `observed_floor_safety_monitor_v0.1`; daily status,
rollup, and Markdown reporting surface its status and counts.

Focused verification for the standalone commit:

- monitor and daily-chain tests: **122 passed, 4 subtests passed**;
- import architecture/runtime-audit tests: **28 passed**;
- affected compile checks: passed;
- strict schema audit: **0 unregistered versions**;
- agent-doc audit: **PASS**, 18 agent files and 536 Markdown files; and
- `git diff --check`: passed.

## 2. Where `floor == settlement`

The measurement reused only the accepted frozen POST outputs from the prior
floor-safety run. All source hashes matched before and after the scan.

Overall, 4,779 of 12,813 enforced floors equal settlement (37.2981%). The
late-day concentration is real:

| Family | 00-02 | 03-08 | 09-14 | 15-17 | 18-23 | Overall |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| F | 2/1,503 (0.13%) | 0/3,095 (0.00%) | 369/2,750 (13.42%) | 1,130/1,382 (81.77%) | 2,870/2,870 (100.00%) | 4,371/11,600 (37.68%) |
| Toronto C | 6/147 (4.08%) | 0/349 (0.00%) | 8/294 (2.72%) | 110/139 (79.14%) | 284/284 (100.00%) | 408/1,213 (33.64%) |
| Combined | 8/1,650 (0.48%) | 0/3,444 (0.00%) | 377/3,044 (12.39%) | 1,240/1,521 (81.53%) | 3,154/3,154 (100.00%) | 4,779/12,813 (37.30%) |

There were 61 F and two Toronto floorless snapshots, retained in snapshot
totals but excluded from the enforced-floor denominators.

### Regression split

The worst cases came from the equality slice, but most regressions did not.
The equality slice also has a lower within-slice regression rate in every lane:

| Lane | Total regressions | `floor == settlement` | Share | Slice regression rate | Below-settlement rate | Mean positive delta, equal / below |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| F current | 4,385 | 1,166 | 26.59% | 26.68% | 44.53% | `+0.0141590` / `+0.0003435` |
| F postblend | 4,046 | 1,166 | 28.82% | 26.68% | 39.84% | `+0.0041190` / `+0.0001679` |
| Toronto current | 407 | 57 | 14.00% | 13.97% | 43.48% | `+0.0030849` / `+0.0004032` |

The hypothesis therefore describes a **severity mechanism**, not the general
regression source: equality explains a minority of regression counts but a
much larger loss when it does regress. The supplied stopping rule said to stop
if the fraction was low or regressions were spread. I stopped. No redistribution
counterfactual was run, no curve was tuned, and model behavior is unchanged.

## 3. Toronto C-family candidate scope

### Recommendation

Queue a Toronto-only C-family candidate immediately after the
release-admissible Toronto lock is secured. Do not compete with the current
9/14 clock by changing serving. Release #1 does not require this candidate: the
supported all-shadow bootstrap can bind Toronto's incumbent with its seven
existing base components. The C candidate answers the later question of
whether Toronto should leave that incumbent route.

### Missing prerequisites

1. **A reviewed C-family entry point.** The pooled trainer and promotion-refresh
   CLIs currently admit only `F` or `all`; the family-secondary trainer admits
   only `F`. The underlying unit filters and replay internals are mostly generic,
   but `C` is not a canonical executable lane.
2. **The real Toronto preselection lock.** The candidate-independent contiguous
   fourteen-date lock and pinned replay manifest do not exist yet. The 9/14
   operational streak is necessary but is not that production lock.
3. **A candidate-owned training graph.** Toronto's checked-in components are
   incumbent artifacts. The checked-in probability-calibration evidence covers
   4,763 rows on four May/June days; it is neither the new candidate nor an
   authorized frozen postblend.
4. **C calibration, trust, and routing artifacts.** Their fit inventories must
   exclude the locked dates and bind to the same immutable selection universe.
5. **A fresh locked replay.** It must preserve `candidate_preblend_p` and the
   actual gated `candidate_p`, alongside exact incumbent, market, label,
   captured-input identity, source-quality, and split-audit evidence.
6. **Production qualification.** Materialized PIT corpus, validation plan,
   streaming evaluation, promotion decision, and immutable training-graph
   verification must all bind to the same candidate.

The required `C` admission patch belongs to training/promotion control-plane
code and can stay candidate-only and inactive. It does **not** require a
`TorontoHighTempModel` serving change, active route, pointer, scheduler, or
capture change.

### Cost

- one narrow `C` admission/schema/test patch, kept separate from lock-day
  evidence and proved not to alter the `F` lane;
- one Toronto prelock, one candidate fit over the fourteen cutoff-hour models
  (07-20), one locked Toronto replay, and the existing PIT/promotion
  qualification chain; no fleet replay is necessary; and
- at the accepted nine-day POST density (1,215 snapshots and 13,365 band rows),
  a fourteen-day evaluation is approximately 1,890 snapshots and 20,790 band
  rows. Training additionally consumes eligible pre-lock history while excluding
  the locked dates.

No wall-clock estimate is asserted because no canonical C production run has
completed on this host. The bounded compute is much smaller than a twelve-market
fleet candidate, but integrity and review, not row volume, dominate the work.

### What an unfrozen run can and cannot say

Without an authorized frozen postblend, a run can prove mechanics: C admission,
trainability, schema/feature compatibility, strict replay identity, simplex,
coverage, and preblend score.

It cannot produce a promotion verdict. Every current skill gate consumes
postblend `candidate_p`, not `candidate_preblend_p`. A preblend-only result
cannot isolate the blend/floor effect, compare candidate and incumbent on one
authorized immutable population, authorize a route, or qualify a release.
Toronto's improved `1.175213x` served/market ratio makes this run worth doing
after lock; it is not promotion evidence by itself.

## 4. Non-strict `current_temp` review

Confirmed intentional: removing the non-strict
`row_temp_native(rows[-1])` fallback is a cutoff-safety tightening.
`rows[-1]` is unfiltered by cutoff. When no cutoff-aligned WU row and no admitted
current/station reading exist, the old path could admit a later printed row as
both `current_temp` and `high_so_far`. The new helper may inspect that value only
for startup-sentinel quarantine; it cannot become a feature or floor.

Strict analog extraction returned `None` before the old fallback and is
unchanged. Direct non-strict callers are:

- HGB/LR serving through `_evaluate_feature_model_for_cutoff`;
- late-day continuation through `predict_late_day_continuation`;
- runtime and captured-parity records through `live_feature_record`;
- pooled candidate replay in `pooled_candidate_replay._record_feature_row`;
- residual-distribution training-corpus materialization in
  `residual_distribution_corpus._default_feature_builder`; and
- the Austin model-hardening research report.

Only the degraded no-cutoff-row/no-live-observation shape changes. Those callers
now carry `current_temp`/`high_so_far` as missing for the trained imputer or
native-NaN handling instead of leaking the unfiltered last row. Normal
cutoff-aligned rows and valid current/station rescue observations are unchanged.
Candidate replay and future corpus regeneration may therefore change on those
degraded rows, but they use the same shared extractor as serving; regenerate
both sides rather than mixing artifacts across this boundary.

## Evidence and integrity

Single declared output root:

```text
C:\Users\Michael\Documents\github\weather\scratch\agent-runs\workstation-floor-monitor-2026-07-31e
```

Artifacts:

- `predeclaration.md`;
- `measure_floor_equals_settlement.py`;
- `floor_equals_settlement_measurement.json`;
- `floor_equals_settlement_by_hour.csv`; and
- `scope_toronto_and_non_strict.md`.

Accepted frozen inputs and hashes:

- F snapshot deltas:
  `a3974379c2fcdb8c24e8527ddbbe2e679c6f7e40d18d87093a894130c3d98f50`;
- Toronto snapshot deltas:
  `0b9fa34f3f0f71de020b6cd91c727f92fd73aa8dce62b9e2af6e86fa4ed1512b`.

Both hashes were unchanged after measurement. All ignored outputs stayed below
the declared root, and all `data/` evidence remained read-only.
