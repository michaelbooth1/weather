# 60. Snapshot Range-Band Audit Schema And Serving Version Guard [NEW - AUDIT]

Goal: make snapshot, component, and replay artifacts sufficient to audit native
range bands and catch stale serving processes immediately.

Miami audit source (2026-06-15): the same market window showed a clean current
code replay near 29% for 92-93 F, while a later persisted CSV row showed 0%.
Current `bin_probability` correctly sums range bands over `[value, value_hi]`,
but `snapshots_long.csv` and `components_long.csv` persist only `bin_value_c`.
That makes it hard to distinguish "92 only" from "92-93" in downstream audit
tools. The persisted rows were also labeled `v0.5.8` while current constants
were `v0.5.10`, and feature-schema rows alternated between v0.4 and v0.5.

- [ ] Add `bin_value_hi_c` or a native-unit equivalent to snapshot long rows,
  component rows, CLOB feature rows where needed, and wide-row band keys.
- [ ] Add a migration/backfill helper or compatibility reader so old rows
  without `bin_value_hi_c` can reconstruct the high endpoint from `range_label`
  and market metadata.
- [ ] Add a snapshot self-check that recomputes each band probability from the
  persisted distribution and stored bin metadata, then fails or warns when the
  stored row differs materially.
- [ ] Add a runtime version guard for snapshot and watcher processes: emitted
  `model_version`, feature schema, and code identity must match the current
  runtime identity or surface as a stale-process/preflight incident.
- [ ] Extend replay and dashboard diagnostics to show exact range semantics,
  model version, feature schema version, and current code identity for the
  latest row.

Acceptance: a future audit can reconstruct 92-93 F exactly from persisted
artifacts without querying Polymarket again, and stale snapshot/watch processes
cannot silently emit mixed-version model rows.

