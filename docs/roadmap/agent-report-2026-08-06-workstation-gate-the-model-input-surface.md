# Agent report 2026-08-06 — gate the model input surface

**Implementation GO; acceptance remains NO-GO until the exact retained 11-market
positive-control scope is recovered and rerun on production.** P0 is proven: the
trained feature list is recoverable per HGB hour bundle, and populated/null counts
are recoverable from already-captured feature rows without a new capture path. The
standalone gate is implemented and reproduces the core known defect: exactly 10 base
features are uniformly empty, and Toronto has exactly 8 dead trained inputs in all 14
of its 29-feature hour models. It deliberately does **not** claim the full retained
93.6–100% survivor-range control: the retained finding does not enumerate its 11
market IDs, and this workstation's provisional non-Toronto comparison is 91.36–100%.

The implementation follows the [2026-09-28a handoff](workstation-handoff-2026-09-28a-gate-the-model-input-surface.md)
and cites the retained facts in [ESTABLISHED_FINDINGS.md §4 and §8](../operations/ESTABLISHED_FINDINGS.md).
It measures and gates only; it does not repair a feature.

The protected defect class remains important even though the repair itself is a
NO-GO. The later `-09-26a` fleet measurement corrected the deliverable free-source
parity effect to **6.7395% all-severe SSE improvement** with crossed interval
**[0.5208%, 14.3964%]**, while pooled Brier delta was **-0.000721** with crossed
interval **[-0.032916, +0.030983]**: the interval crosses zero and the point estimate
is a mild degradation. `ESTABLISHED_FINDINGS.md` §4's 12.77% is the theoretical
repair, not the free-source deliverable. This gate therefore makes no activation or
retrain-benefit claim. Its value is fail-closed input-surface integrity: the concrete
gate catches the serving-blindness defect, and the same code-owned-population check
class also catches defects such as §4b's season-window archive reporting fleet
coverage `OK 12/12` while containing zero rows for the retrain's target dates.

## Verdict and scope

The new [`model_input_surface_gate.py`](../../src/weather/reporting/source_gates/model_input_surface_gate.py)
is a read-only, no-network, no-model-replay CLI. It emits a dated registered JSON
artifact and exits nonzero on `BLOCK`. It is not registered in either daily-refresh
lane.

The gate has three evidence layers:

1. It loads every registered market's exact active-release HGB component when a
   verified active release exists, otherwise the ambient per-market HGB artifact. It
   extracts each hour bundle's `feature_names`, `all_wind_groups`, and
   `all_cloud_groups`.
2. It joins `features.jsonl` exactly to paired `snapshots.jsonl` rows by snapshot ID
   and event. Ambient rows must carry the exact normalized HGB path and SHA-256 that
   was evaluated. Release-bound rows must additionally carry matching, canonically
   self-hashed `replay_inputs.jsonl` lineage and exactly the same snapshot/replay
   model identity. Missing, duplicate, mixed, mismatched, or unjoined evidence is
   excluded and blocks.
3. It reports the required three-day population fraction per
   `(market, cutoff_hour, trained_feature)`. A code-owned 0.25 window floor blocks
   complete and severe loss without giving the judged artifact a threshold override.
   A separate current-day rule catches a feature with no artifact-bound arrival
   anywhere across its trained 07:00–20:00 models. Per-hour daily cells remain
   diagnostic; making every sparse feature arrive at every hour would have created 25
   known false alarms on the retained mirror.

All markets are judged separately. There is no pooled gate verdict and no CLI market,
window-size, population-floor, or sparse-feature override.

`wind_gust_kmh` has an explicit evidence-qualified policy. Any observed gust proves
arrival for the slice. All-null gust is exempt only when every row carries affirmative
nonnegative sustained wind at or below 5.0 in the captured field's native unit. Missing
or stronger sustained-wind evidence with no gust blocks; gust is not blanket-exempt.

Derived wind/cloud one-hots are judged on arrival of their source group, not on the
synthetic zero that serving creates when the group is absent. This closes a categorical
train/serve-skew blind spot found during independent review.

## P0 feasibility proof

Both sides are present without capture changes:

- The 12 serving HGB artifacts expose a nonempty trained feature list for every hour
  07:00–20:00. Toronto exposes 29 trained inputs in every hour model.
- Existing market-day `features.jsonl` rows retain all direct fields plus
  `wind_group` and `cloud_group`; paired `snapshots.jsonl` retains the artifact model
  identity; release-bound `replay_inputs.jsonl` retains verified release lineage and a
  canonical self-hash.
- The final retained run bound 6,275 rows from 12 markets over three target dates and
  covered all 504 expected market-date-hour slices. One malformed Austin snapshot
  identity row was excluded and surfaced as evidence instead of silently shrinking a
  denominator.

Neither P0 falsifier holds. No new collector, payload, sidecar, extractor, or provider
call is required.

## Retained Aug. 3–5 gate result

The final proof used target dates 2026-08-03 through 2026-08-05, all 12 registered
markets, and all 14 cutoff hours. Its temporary JSON SHA-256 was
`48fb334490d28baf85dfc45f56916c9a40d601ebaf07f96ee80645d8480d0b00`.

| Measure | Result |
| --- | ---: |
| Artifact-bound captured rows | 6,275 |
| Expected / covered market-date-hour slices | 504 / 504 |
| Loaded serving artifact markets | 12 / 12 |
| Three-day `(market, hour, trained feature)` cells | 4,382 |
| Blocking three-day cells | 3,276 |
| Current-day `(market, trained feature)` groups blocking across trained hours | 234 |
| Evidence blockers with full positive-control requirement | 3 |

The 3,276 blocking window cells comprise:

- 1,344 direct cells: the established 8 dead trained features × 12 markets × 14
  hours; and
- 1,932 derived categorical cells: 1,008 wind-group one-hots and 924 cloud-group
  one-hots whose raw categorical source never arrived. Wind source loss affected all
  12 markets; cloud source loss affected 11.

The 0.25 window floor was selected after false-positive characterization, not from the
judged artifact. The weakest nonblocking retained window cell was Miami 18:00
`forecast_disagreement` at 7/23 = 30.43%. A 25% floor leaves a measured buffer while
still blocking total or severe arrival loss. The current-day across-hours rule catches
the all-day recurrence this mission exists to stop without converting legitimate
within-day sparsity into a permanent alarm.

The two input-evidence blockers, independent of the requested positive control, are
both for one Austin 2026-08-05 snapshot: malformed JSON at `snapshots.jsonl` line 60
and the resulting unmatched feature-row identity. The third blocker is intentional:
`--require-established-positive-control` demands the exact full retained scope and
range, which cannot be identity-bound until the historical 11 market IDs are
enumerated in a reviewed source.

## Positive control

The core control reproduces:

- Provisional non-Toronto scope: 5,731 artifact-bound rows after the strict Austin-row
  exclusion.
- Uniform-zero base set: exactly `rise_from_7am`, `warming_rate_2h`, `hours_at_peak`,
  `dewpoint_c`, `humidity`, `pressure`, `pressure_trend_3h`, `wind_speed_kmh`,
  `wind_gust_kmh`, and `wind_shift_3h_degrees`.
- Toronto serving artifact: exactly the first eight of those direct trained fields are
  0.0% in every one of the 14 hour models, each with 29 trained features.

The full retained control does not reproduce on this host and is not claimed. The nine
surviving base features span 91.36–100%, not 93.6–100%, and the retained source says
only "11 markets" without enumerating their IDs. The JSON therefore records
`core_dead_input_control_reproduced=true`,
`full_retained_range_reproduced_on_this_host=false`, and
`reference_scope_market_ids_enumerated=false`.

This is a coverage census, not a model-quality or edge estimate. There is no sampled
performance interval and no date × market cluster inference to report. The support is
the complete retained three-date × 12-market × 14-hour surface. No Brier, edge, or
forecast-improvement claim is made.

## Reproduction commands

Run from the repository root on the production host. These commands use repository
paths, not workstation scratch paths.

Daily gate, without the one-time historical-control requirement:

```powershell
.\venv\Scripts\python.exe -m weather.reporting.source_gates.model_input_surface_gate `
  --end-date 2026-08-05 `
  --snapshot-root data/snapshots `
  --artifact-root artifacts/models/hgb
```

The dated artifact is written to
`data/backtest/model_input_surface_gate/model-input-surface-gate-2026-08-05.json`.

Exact initial positive-control attempt; exit 2 is required until the retained fleet
scope is identity-bound and the full 93.6–100% range reproduces:

```powershell
.\venv\Scripts\python.exe -m weather.reporting.source_gates.model_input_surface_gate `
  --end-date 2026-08-05 `
  --snapshot-root data/snapshots `
  --artifact-root artifacts/models/hgb `
  --require-established-positive-control
```

Focused verification:

```powershell
.\venv\Scripts\python.exe -m pytest tests/reporting/test_model_input_surface_gate.py -q
.\venv\Scripts\python.exe -m pytest tests/reporting -q
.\venv\Scripts\python.exe -m pytest tests/operations/test_import_architecture.py tests/operations/test_schema_registry.py -q
.\venv\Scripts\python.exe -m compileall -q app src tests
.\venv\Scripts\python.exe -m weather.schema_registry audit --strict
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
```

## Verification

| Check | Result |
| --- | --- |
| Focused model-input gate suite | 36 passed |
| Full reporting owner suite | 898 passed, 1 skipped, 23 subtests passed |
| Import architecture + schema registry tests | 28 passed |
| `compileall` | PASS |
| Strict schema audit | PASS — 511 registered, 846 discovered, 0 unregistered, 8 excluded |
| Independent final implementation review | No remaining actionable findings |
| Full repository suite | 3,316 passed, 4 skipped, 820 subtests passed; 21 host/pre-existing failures |

The 21 full-suite failures are outside this change and do not touch the reporting gate:
one local settlement-ledger binding collision, two expected writes denied by the local
`data/` ACL, one pre-existing broken historical-doc link, four Windows
PowerShell/provenance tests, and 13 experiment-executor containment/path fixtures. The
task-owned reporting, architecture, schema, compile, and strict registry checks are
green.

## Per-file roll verdict

This verdict was re-derived from each retained
`runtime_identity.source_scope_files` array, not from `SOURCE_PATTERNS`. The retained
closures contained 77 snapshot-loop files, 23 CLOB-loop files, 85
observation-trigger files, and 21 CLOB-enrichment files. All five implementation/test
files are stated individually:

| File | `loop_status.json` | `clob_loop_status.json` | `observation_trigger_status.json` | `clob_enrichment_status.json` | Verdict |
| --- | --- | --- | --- | --- | --- |
| `src/weather/reporting/source_gates/model_input_surface_gate.py` | absent | absent | absent | absent | Standalone; no capture-loop roll |
| `src/weather/schema_registry_recent_data.py` | present | present | present | present | **Roll-sensitive in all four closures** |
| `tests/reporting/test_model_input_surface_gate.py` | absent | absent | absent | absent | Test-only; no capture-loop roll |
| `tests/operations/test_import_architecture.py` | absent | absent | absent | absent | Test-only; no capture-loop roll |
| `tests/operations/test_schema_registry.py` | absent | absent | absent | absent | Test-only; no capture-loop roll |

The `schema_registry_recent_data.py` change is **additive-only**: it appends one
`SchemaSpec` for `model_input_surface_gate_v0.1` and does not modify or remove any
existing registration. Central registration is mandatory, so this behaviourally inert
addition cannot avoid entering all four closures. This report is documentation-only
and absent from every Python source closure.

The branch is therefore roll-sensitive even though the gate module itself is
standalone. Integration must use the repository's 01:00–04:00 quiet-window workflow.

## Git handoff

- Branch: `codex/workstation-gate-the-model-input-surface-2026-09-28a`
- Base: `589bd7eae180ad741b23b4520e67c54a671d1ac0` (`origin/master` at task start)
- Corrected delegation contract reviewed from `origin/master` commit
  `d91f2335`; workstation commit/push is roll-free, while the production merge owns
  the quiet-window constraint.
- Implementation commit: `557e720096db72bba1dd8b55c5dc6306444b377e`

## Explicit non-actions

- No `model_features.py`, `free_source_feature_parity.py`, extractor, repair, or
  `daily_refresh*.py` file was changed.
- No chain step, scheduler, task, supervisor, or service was registered.
- No provider call, network collection, retrain, fit, candidate build, release
  promotion, active-pointer write, production-data write, or live-trading action
  occurred.
- No capture process was restarted or re-adopted.
- No merge or pull request occurred.
- The workstation commit and branch push do not alter the production working tree;
  the production agent retains merge sequencing, including the recovery job and
  01:00–04:00 quiet window.
