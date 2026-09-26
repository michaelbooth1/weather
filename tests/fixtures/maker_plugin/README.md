# Synthetic weather maker inputs

All values and dates in test_maker_plugin.py are invented (2030). No production
or historical weather records are used. The factories emit these writer shapes:

- `maker_evidence_store.EvidenceStore.record`: inline `body_utf8` discovery and
  books records with capture time and SHA-256; discovery body matches
  `maker_evidence_public.discovery_projection`, including stringified token lists.
- `nbm_probabilistic_tmax.nbp_raw_payload`: text, station, target, capture, hash;
  text uses six-column codes, pipe-delimited min/max pairs and NBP issue header.
- `snapshot_store.persist_snapshot`: long-row `model_probability`, native-unit
  `bin_value_c`/`bin_value_hi_c`, token/condition/event/snapshot identity.
- `snapshot_store` explanation JSON: `explanations.probability_calibration_context`
  and its `afternoon_residual_centering` context. Release lineage comes from
  source rows, not an invented long-row release field.
- `forecast_archive.make_row`: daily_high/forecast_high_c with provider issue and
  captured_at_utc. Legacy _c values remain native-unit.
- `observation_trigger.trigger_record`: current capture time and observed_at,
  previous/current values and buckets, reason/source, event/market/target/unit.
- `settlement_ledger.upsert_ledger_record`: versioned label payload with revision
  hashes, supersession links, reconciliation_status and venue winning-band label.

The v2 selector oracle is copied verbatim from `abd648c7c`, without provider
imports. It is tested against synthetic FHR layouts for all qualified stations,
cycle hours and T+1/T+2 targets, including timezone transitions. No dependency
on that branch or a network request is needed to run tests.

These are minimal required field projections of the captured shapes, not proof
of production coverage. 88a discovery does not capture band metadata: a bounded
real export must supply captured band rows and both-token book rules. If absent,
the offline universe refuses construction. T+1/T+2 metadata, complete NBP
bulletins, T+0 stage/release joins and reconciled ledger histories still need
real-sample validation by the production agent.
