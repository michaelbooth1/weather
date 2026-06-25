# 200. First-Class Model Explanation Tape [COMPLETE 2026-06-21 - EXPLANATION SIDECARS QUERYABLE BY SNAPSHOT]

Goal: persist model explanations as a durable per-snapshot tape so settled-day
root-cause analysis can join probabilities, features, components, analogs, and
diagnostic explanations without rerunning the model.

Source: the June 21 log audit found that current live-day logs capture the core
model and replay artifacts, but `SnapshotStore` persists only selected fields as
queryable sidecars. The model build contract already returns `analog_search`,
`boundary_transitions`, `late_day_risk`, `source_diagnostics`, and
`model_explanation`; those are not all written into a first-class
`snapshot_explanations.jsonl` or long-form CSV.

Why this matters: hourly, 10-minute, candidate replay, and stage attribution
reports can identify when and where the model loses. To improve the model
quickly, each weak slice also needs a durable explanation of which analogs,
boundary transitions, source diagnostics, and late-day rules were active at the
time, without relying on manual dashboard inspection or non-reproducible
rebuilds.

## Design

1. Add `snapshot_explanations.jsonl` and, where useful, a normalized
   `snapshot_explanations_long.csv` sidecar under each snapshot folder.
2. Persist model explanation payloads with `snapshot_id`, event, market,
   target date, runtime identity, model identity, feature schema, and source
   hashes.
3. Include analog-search summaries, boundary-transition probabilities,
   late-day risk, source diagnostics, family-secondary gates, and explanation
   waterfall references.
4. Teach settled-day root-cause and daily learning reports to prefer the sidecar
   when explaining weak slices.
5. Add replay checks proving explanation rows line up with snapshot, feature,
   component, and replay-input rows.

- [x] Add explanation sidecar paths and writers to snapshot persistence.
- [x] Normalize the largest nested explanation sections into queryable rows.
- [x] Backfill explanation sidecars for replayable recent market days.
- [x] Join explanation rows into settled-day root-cause reports.
- [x] Add coverage and schema gates to data-layer audit.

Acceptance: for a settled weak slot, one query can join the snapshot row to its
feature vector, component stages, replay input, and explanation payload, with no
model rerun required.

Completion note 2026-06-21: `SnapshotStore` now writes
`snapshot_explanations.jsonl` and `snapshot_explanations_long.csv` whenever a
snapshot model carries explanation payloads. The JSONL stores analog search,
boundary transitions, late-day risk, source diagnostics, source health,
family-secondary gates, model explanations, calibration context, component
metadata, runtime identity, model identity hash, and source hash. The long CSV
normalizes scalar and nested sections by `snapshot_id`/section/item for joins.
`python -m weather.collection.snapshot_store backfill-explanations <folder>`
idempotently backfills replayable folders from `snapshots.jsonl` plus
`replay_inputs.jsonl`. Settled-day root-cause and daily learning reports now
surface explanation tape coverage, and the data-layer audit counts and
recommends the sidecar.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - EXPLANATION SIDECARS QUERYABLE BY SNAPSHOT`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

