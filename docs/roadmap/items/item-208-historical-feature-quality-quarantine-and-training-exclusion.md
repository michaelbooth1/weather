# 208. Historical Feature-Quality Quarantine And Training Exclusion [COMPLETE 2026-06-21 - FEATURE-QUALITY QUARANTINE EXCLUDES LEGACY BAD ROWS]

Goal: quarantine or backfill historical feature rows with known impossible
startup observations or current-max anomalies so they cannot contaminate
training, replay, or promotion evidence.

Source: items 193 and 197 fixed runtime handling for WU current-max anomalies
and startup live-observation sentinels. The generated June 20 root-cause
artifacts still contain legacy feature rows with F-market startup values like
`high_so_far=17.0` and `current_temp=17.0`, and hundreds of current-max anomaly
issue rows mapped to completed items. Those rows are reported, but there is no
active item that backfills, quarantines, or excludes the affected historical
feature rows from future training and claims.

Why this matters: fixing serving going forward is not enough if stale
`features_long.csv`, replay inputs, or training corpora still carry the bad
values. A model retrain or historical promotion report should know whether a
row is corrected, excluded, or score-only because feature quality is not
trustworthy.

## Design

1. Audit historical `features_long.csv`, replay inputs, and snapshot sidecars
   for startup sentinel values, unit-implausible live observations, and
   current-max anomaly fields.
2. Write a feature-quality quarantine manifest keyed by event, market,
   snapshot, feature field, reason, and disposition.
3. Backfill rows when raw source evidence is available; otherwise mark them
   score-only or training-excluded with an explicit reason.
4. Teach promotion corpus, candidate replay, and data-layer audit to consume
   the feature-quality disposition.
5. Add regression tests using the June 20 Austin, Denver, Miami, NYC, Houston,
   and Seattle patterns.

- [x] Build the historical feature-quality audit and quarantine manifest.
- [x] Backfill reconstructable startup/current-max feature rows from source
  evidence.
- [x] Exclude non-reconstructable bad feature rows from training and promotion
  eligibility.
- [x] Surface feature-quality exclusion counts in data-layer and promotion
  reports.
- [x] Add tests for known June 20 sentinel and current-max anomaly rows.

Acceptance: known historical bad feature rows are either corrected or excluded
from training/promotion eligibility, and broad model-improvement claims report
how many rows were feature-quality quarantined.

## 2026-06-21 completion

`weather.reporting.feature_quality_quarantine` now emits
`feature_quality_quarantine_v0.1` JSON/CSV/Markdown manifests keyed by event,
market, snapshot, source file, feature field, reason, and disposition. It scans
`features_long.csv`, `snapshots_long.csv`, and affected replay inputs for
startup sentinels, unit-implausible live observations, current-max trust
quarantines, and sidecar current-max values that exceed observed support.

The retained fleet artifact
`data/backtest/feature_quality_quarantine.json` scanned `201` folders,
`28,770` feature rows, and `318,472` snapshot rows. It quarantined `4,857`
rows across `141` folders, `4,770` event/snapshot pairs, and all `12` markets:
`174` startup live-observation rows, `4,680` current-max sidecar anomaly rows,
and `3` current-max feature-schema quarantine rows. No affected row had raw
observation payload evidence, so every row is explicitly
`training_excluded_no_raw_evidence`, score-only, and promotion-excluded rather
than silently backfilled.

`data_layer_audit` consumes the per-folder quarantine summary and removes
affected folders from `training_ready` sidecar eligibility with
`feature_quality_training_excluded_rows:*` promotion-exclusion reasons. The
refreshed `data/backtest/data_layer_audit.json` and report surface the same
`4,857` quarantined/training-excluded rows. Promotion corpus construction now
drops quarantined snapshot IDs before hashing pinned corpora, and candidate
replay reports carry feature-quality quarantine counts in both corpus and
sidecar sections.

Verification:

`python -m weather.reporting.feature_quality_quarantine --snapshots-root data\snapshots --json-out data\backtest\feature_quality_quarantine.json --csv-out data\backtest\feature_quality_quarantine.csv --report-out data\backtest\feature_quality_quarantine_report.md`

`python -m weather.reporting.data_layer_audit --snapshots-root data\snapshots --backtest-root data\backtest --out data\backtest\data_layer_audit.json --report data\backtest\data_layer_audit_report.md`

`python -m pytest tests\reporting\test_feature_quality_quarantine.py tests\reporting\test_data_layer_audit.py tests\reporting\test_promotion_corpus.py tests\calibration\test_pooled_candidate_replay.py tests\operations\test_schema_registry.py -q`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - FEATURE-QUALITY QUARANTINE EXCLUDES LEGACY BAD ROWS`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

