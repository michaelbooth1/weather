# 314. Artifact And Training-Data Schema Forward-Migration To Retire Historical-Only Quarantines [OPEN 2026-06-25 - SCHEMA BUMPS STRAND ARTIFACTS HISTORICAL-ONLY INSTEAD OF MIGRATING]

Goal: replace the "quarantine artifacts and rows as historical-only whenever the
feature schema bumps" shortcut with a forward-migration / re-export path, so a
schema bump does not permanently strand the artifact set or cap the training
corpus.

Source: 2026-06-25 gate audit (prompted by the observation that gate-building was
becoming a substitute for hard model work). `weather.reporting.per_location_artifact_quarantine`
marks per-location artifacts `historical-only` by schema family, and the active
pooled-F artifact is stamped `toronto_feature_store_v1.13` while runtime is
`v1.14`/`v1.15` - so the broad retrain/location gate stays BLOCK and the
artifacts are stranded rather than migrated (this is the live item 224/48
blocker). The same pattern excludes legacy "bad" training rows (item 208) and
impossible/anomalous source rows (items 193/252) from the corpus, permanently
removing recoverable data instead of repairing it.

Why this matters: quarantine is a legitimate safety guard, but using it as the
default response to a schema bump or to recoverable legacy data is a shortcut
that silently caps model quality - the artifact set and training corpus shrink at
every schema bump, and promotion stays blocked on schema-currency rather than on
skill. The hard work (migrate/re-export artifacts to the current schema,
re-derive recoverable rows) is deferred indefinitely behind a quarantine that
looks "done."

Why it is not already covered: per_location_artifact_quarantine and item 226 own
the quarantine itself (the safety guard); items 208/193/252 own specific
data-quality quarantines; none owns a forward-migration path that retires the
historical-only disposition by bringing artifacts and rows to the current
schema. Item 290 migrates closed-day tapes to parquet, not model artifacts to the
current feature schema; item 224 re-exported the pooled artifact but did not
migrate the stranded per-location set.

## Design

1. Define an artifact schema-migration contract: when the feature schema bumps,
   attempt a deterministic forward-migration or re-export of active artifacts to
   the current schema before quarantining, so `historical-only` is the exception
   (genuinely unmigratable) rather than the default.
2. Add a recoverable-row recovery path for quarantined training rows: re-derive
   or re-backfill rows quarantined for fixable reasons (legacy schema, since-
   recovered source) so they re-enter the corpus instead of permanent exclusion.
3. Classify every quarantined artifact/row as `migratable` versus
   `unrecoverable`, and report counts so the permanently-excluded set is visible
   and shrinking.
4. Wire the migration into nightly retrain / promotion so a schema bump triggers
   migration rather than a stranded-artifact BLOCK.
5. Keep the quarantine as a fail-closed guard for the genuinely unrecoverable
   remainder only.

- [ ] Add a deterministic artifact forward-migration / re-export to the current
  feature schema, attempted before quarantine.
- [ ] Add a recoverable-row recovery path that returns fixable quarantined rows
  to the corpus.
- [ ] Classify quarantined items `migratable` vs `unrecoverable` with counts.
- [ ] Trigger migration on schema bump in nightly retrain/promotion instead of a
  stranded BLOCK.
- [ ] Add tests for a schema-bump artifact migration and a recoverable-row
  recovery, and prove the broad retrain/location gate is no longer blocked purely
  on schema-currency.

Acceptance: a feature-schema bump migrates or re-exports active artifacts to the
current schema rather than stranding them historical-only, recoverable
quarantined training rows re-enter the corpus, the quarantine fires only on
genuinely unrecoverable data, and the broad retrain/location gate is no longer
blocked purely by schema-currency, proven by migration and recovery tests.

Related: items 24, 178, 208, 224, 226, 244, 290.
