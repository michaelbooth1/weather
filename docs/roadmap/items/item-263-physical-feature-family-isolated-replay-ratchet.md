# 263. Physical Feature-Family Isolated Replay Ratchet [COMPLETE 2026-06-23 - FAIL-CLOSED PHYSICAL FAMILY RATCHET LIVE]

Goal: require every physical-weather feature family to produce isolated,
lineage-clean, settlement-scored replay evidence before it can influence a
promotion claim.

Source: the 2026-06-23 research audit found that the repo already has many
physical feature lanes in the roadmap, including pressure-level predictors,
boundary-layer and mixing context, soil moisture, radiation/clouds,
smoke/aerosols, lake or sea effects, snow/albedo, ECMWF/AIFS, NBM
probabilistic Tmax, and analog or ensemble post-processing. Item 125 created a
source-family inventory and promotion queue, but the family-specific audit
thread still needs a stricter cross-family ratchet for isolated replay,
artifact lineage, active artifact columns, missingness, and settlement-sliced
lift.

Why this matters: richer meteorological inputs can make a model look more
scientific while silently borrowing lift from unrelated code changes, fallback
behavior, market overlays, or train/serve mismatch. Physical predictors should
earn promotion through family-level evidence, not through broad candidate
movement where the causal contribution is unclear.

## Design

1. Define a shared physical-family evidence contract with provider/source,
   raw-payload lineage, historical availability, live availability, feature
   transforms, missingness/fallback behavior, train rows, served rows, and
   active artifact columns.
2. Require isolated replay or ablation evidence for each family before it can
   be counted as a model-quality improvement.
3. Score each family by market, local cutoff hour, early-hour regime,
   weak-location regime, source-health state, and settlement-distance slice.
4. Track family statuses with explicit blocker vocabulary: `LIVE_ONLY`,
   `LINEAGE_BLOCKED`, `MISSING_ACTIVE_ARTIFACT`, `MISSING_SETTLED_REPLAY`,
   `ISOLATED_REPLAY_BLOCK`, `SHADOW_PASS`, and `PROMOTION_ELIGIBLE`.
5. Keep market-informed overlays and CLOB-derived columns out of the
   physical-weather family scorecard.
6. Add a rollup table that shows which roadmap feature families are ready for
   retraining, which are diagnostic-only, and which are blocked by evidence
   rather than implementation.

- [x] Add the physical-family evidence contract and report.
- [x] Backfill or link lineage evidence for each candidate physical family.
- [x] Add isolated replay or ablation rows for every family that is active in a
  candidate artifact.
- [x] Add explicit skip/block reasons for live-only or payload-missing
  families.
- [x] Add settlement-sliced lift/harm tables by market and cutoff regime.
- [x] Update individual physical-family item notes only from the rollup
  evidence, not from broad candidate movement alone.

## Completion Notes

Implemented `weather.reporting.source_gates.physical_feature_family_ratchet` with schema
`physical_feature_family_ratchet_v0.1` and canonical outputs at
`data/backtest/physical_feature_family_ratchet.json` and
`data/backtest/physical_feature_family_ratchet.md`.

The report consumes `source_family_inventory.json` and
`source_family_ablation.json`, excludes CLOB/market-overlay families from the
physical-weather rollup, and maps each physical family to the item-263 status
vocabulary: `LIVE_ONLY`, `LINEAGE_BLOCKED`, `MISSING_ACTIVE_ARTIFACT`,
`MISSING_SETTLED_REPLAY`, `ISOLATED_REPLAY_BLOCK`, `SHADOW_PASS`, and
`PROMOTION_ELIGIBLE`.

`source_family_ablation` now carries optional settlement-sliced effects by
market, cutoff regime, market/cutoff regime, and settlement distance. Older
ablation artifacts without those rows fail closed as
`ISOLATED_REPLAY_BLOCK`, which is the current state of the generated ratchet:
10 physical families are evidence-blocked and the CLOB microstructure overlay
is explicitly excluded.

Promotion readiness now reads `physical_feature_family_ratchet.json` and emits
a `physical_feature_family_ratchet` blocker whenever the ratchet is missing or
not `PASS`. The promotion report lists the ratchet in operational gates and
refresh artifacts, so broad candidate movement cannot bypass family-level
lineage, active-column, missingness, and isolated settlement-scored evidence.

Verification:

- `python -m weather.reporting.source_gates.physical_feature_family_ratchet --json-out data\backtest\physical_feature_family_ratchet.json --report-out data\backtest\physical_feature_family_ratchet.md`
- `python -m pytest tests\reporting\test_physical_feature_family_ratchet.py tests\backtesting\test_replay_ablation.py tests\operations\test_schema_registry.py tests\calibration\test_promotion_refresh.py -q`

Acceptance: no pressure-level, boundary-layer, soil, radiation, smoke, marine,
snow, ECMWF/AIFS, NBM, analog, or ensemble post-processing feature can support a
promotion claim unless its own lineage, parity, missingness, and isolated
settlement-scored replay evidence pass the shared ratchet.

Related: items 32, 50, 74, 75, 76, 125, 185, 186, 187, 188, 189, 190, 191, 242.
