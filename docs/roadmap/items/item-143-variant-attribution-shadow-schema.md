# 143. Variant Attribution Shadow Schema [COMPLETE 2026-06-18 - ATTRIBUTION SCHEMA AND SIDECAR LIVE]

Goal: expand the durable variant shadow row schema so variant wins and losses
can be diagnosed after the fact, not just scored.

Source: 2026-06-18 model-variant data audit. The current long-form shadow
schema keeps observation keys, probabilities, current/recorded/market
comparators, outcome, artifact hash, postprocess hash, and a few band/time
fields. It drops source freshness state, settlement-distance bucket, casebook
taxonomy, model feature values, source issue times, missingness flags, and
other attribution fields before the multi-variant table.

Why this matters: the current schema is enough to compare Brier/log-loss/ECE,
but weak for model improvement. When a variant wins or loses, we need durable
slice context to decide whether the cause was source freshness, cutoff regime,
forecast profile, market microstructure, settlement-distance behavior, or
feature missingness.

## Design

1. Add a versioned attribution extension to the multi-variant shadow long
   table instead of overloading the minimal scoring schema.
2. Preserve source freshness state, source family availability, source issue
   time basis, settlement-distance bucket, cutoff regime, bin type/value,
   casebook taxonomy, feature schema version, and selected feature-family
   hashes.
3. Store high-cardinality feature vectors in a separate sidecar keyed by
   `variant_id`, `market_id`, `target_date`, `snapshot_id`, and `band_key`.
4. Keep the scoring columns stable so existing reports continue to read old
   exports.
5. Add report slices for source freshness, settlement distance, cutoff regime,
   casebook taxonomy, and feature-family missingness.

- [x] Define `multi_variant_shadow_attribution_v0.1` fields and compatibility
  rules.
- [x] Update candidate replay shadow-row builders to carry attribution fields
  forward.
- [x] Add a compact feature sidecar for large feature vectors or hashes.
- [x] Extend multi-variant reports with attribution slices.
- [x] Add round-trip tests proving old minimal rows still score and new rows
  retain attribution context.

Acceptance: fresh active-variant shadow exports can answer why a variant won
or lost on a slice without re-running the original replay, while old minimal
shadow CSVs remain readable for scoring.

## Implementation update - 2026-06-18

Added schema `multi_variant_shadow_attribution_v0.1` and optional attribution
columns to the multi-variant long table. Required scoring columns are unchanged,
so old minimal CSVs still normalize and score. New rows can retain cutoff
regime, source freshness, source availability/issue-time basis, settlement
distance, forecast-source buckets, casebook taxonomy, feature schema/hash,
feature missingness hash, CLOB feature diagnostics, and microstructure gate
context.

Candidate, source-state, conservative bridge, and CLOB shadow-row builders now
carry attribution context forward when it is present and stamp feature hashes
for compact diagnostics. `multi_variant_shadow` now reports attribution
coverage and slices for source freshness, settlement distance, cutoff regime,
casebook taxonomy, and feature missingness. It also writes a JSONL attribution
sidecar keyed by `variant_id`, `market_id`, `target_date`, `snapshot_id`, and
`band_key`.

`active_variant_shadow_refresh` writes
`data/backtest/active_variant_shadow_attribution.jsonl` beside the canonical
long table. The current regenerated active-shadow output remains scoring
compatible (`OK`; evidence growth `WARN` with SLA `PASS`), but its sidecar is
empty because the source exports it consumed predate this attribution schema.
Future per-variant exports produced through the updated row builders will
populate the sidecar without changing the scoring contract.

Verification:

- `python -m pytest -q tests\reporting\test_multi_variant_shadow.py tests\calibration\test_pooled_candidate_replay.py tests\operations\test_daily_refresh.py tests\operations\test_schema_registry.py`
- `python -m weather.reporting.candidate_lifecycle.active_variant_shadow_refresh --variant-registry config\model_variant_registry.json --long-out data\backtest\active_variant_shadow_long.csv --attribution-sidecar-out data\backtest\active_variant_shadow_attribution.jsonl --json-out data\backtest\active_variant_shadow.json --report-out data\backtest\active_variant_shadow_report.md`
- `python -m weather.reporting.candidate_lifecycle.variant_evidence_growth data\backtest\active_variant_shadow_long.csv --baseline-predictions data\backtest\item86_no_market_bakeoff_multi_variant_shadow_long.csv --json-out data\backtest\model_variant_evidence_growth.json --report-out data\backtest\model_variant_evidence_growth_report.md`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - ATTRIBUTION SCHEMA AND SIDECAR LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

