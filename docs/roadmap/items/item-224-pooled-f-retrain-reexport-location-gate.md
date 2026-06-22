# 224. Pooled F Retrain/Re-Export Location Gate [PARTIAL 2026-06-22 - GATE REFRESHED, RETRAIN/LOCATION BLOCKED]

Goal: re-export the active pooled F artifact under serving-parity and honest
blocked-validation fixes, then make the new artifact pass the location audit
before any broad core-model improvement claim.

Source: `docs/roadmap/audits/location-performance-model-audit-2026-06-22.md`,
plus the early-hour and core-model audits. The early-hour failure matches the
core-model finding that serving applied transforms the tuning objective did not
see, and historical validation was asymmetric between the ML path and baseline.
The active location audit shows bottom markets remain outside tolerance.

Why this matters: even when code-level validation fixes exist, production proof
depends on a regenerated artifact and the exact served distribution passing the
same location and weak-slot gates.

## Design

1. Run the long-job-safe pooled F retrain/re-export path after serving-parity
   and honest blocked-validation fixes.
2. Stamp the artifact with schema, training cutoff, runtime identity, and
   validation provenance.
3. Replay the new artifact against current, item147, and predawn/item147 repair
   on the same market-day corpus.
4. Require hourly, ten-minute, promotion refresh, stage attribution, and
   location split reports to clear market-specific gates before any broad claim.

- [ ] Produce a regenerated pooled F artifact with current validation
  provenance.
- [ ] Run paired replay against current, item147, and predawn repair.
- [x] Regenerate hourly, ten-minute, promotion refresh, stage attribution, and
  location audit outputs.
- [x] Add an artifact gate that blocks broad claims when the active artifact is
  older than the serving-parity validation fixes.

## Progress 2026-06-22

Added `weather.reporting.pooled_f_retrain_location_gate` with schema
`pooled_f_retrain_location_gate_v0.1`.

Artifacts:

- `data/backtest/pooled_f_retrain_location_gate.json`
- `data/backtest/pooled_f_retrain_location_gate_report.md`

Command:

`python -m weather.reporting.pooled_f_retrain_location_gate --out data\backtest\pooled_f_retrain_location_gate.json --report data\backtest\pooled_f_retrain_location_gate_report.md`

Result: **BLOCK** with 7 blockers. Broad core-model improvement claims remain
disallowed.

Current blockers:

- Active artifact `artifacts\models\hgb\feature_model_hgb_f_pooled_v0_3.pkl`
  was trained at `2026-06-21T21:53:04.962892` with
  `toronto_feature_store_v1.13`, while the active runtime schema is
  `toronto_feature_store_v1.14`.
- Paired candidate replay is `BLOCK`; daily-first blocked validation is
  `BLOCK`; cutover remains `DO_NOT_CUT_OVER`.
- Promotion refresh readiness is `OPEN`; weather-only broad-claim allowance is
  false because aggregate `delta_vs_market` is still positive.
- Hourly/ten-minute weak-slot promotion remains blocked.
- Bottom-location winner-centering remains blocked; first blocker is Seattle
  weak-slot current regression `+0.0307`.
- Exact-band and settlement-distance-0 calibration remains blocked; first
  blocker is exact-band early market gap `+0.0047`.
- Source/missingness location gate remains blocked; first blocker is Miami
  all-fresh market gap `+0.0215`.

The gate passes the validation-provenance check for the current artifact/report,
but it intentionally fails closed until a current-schema retrain/re-export and
all replay, weak-slot, promotion, and location-split reports clear on the same
corpus.

Acceptance: the regenerated pooled F artifact has fresh validation provenance
and clears weak-slot, market-specific, and aggregate promotion gates on the same
corpus before any broad core-model improvement claim is allowed.

Related: items 48, 106, 177, 178, 179, 217, 219.

## 2026-06-22 gate refresh after upstream repairs

Regenerated the broad-claim gate after refreshing the predawn sweep,
bottom-location, exact-band, and current-max trust evidence:

- `data/backtest/pooled_f_retrain_location_gate.json`
- `data/backtest/pooled_f_retrain_location_gate_report.md`

The refreshed gate remains `BLOCK` with `7` blockers and keeps broad pooled-F
core-model improvement claims disallowed.

Current blockers:

- `artifact_runtime_schema`: active artifact
  `artifacts\models\hgb\feature_model_hgb_f_pooled_v0_3.pkl` is still stamped
  with `toronto_feature_store_v1.13`, while the active runtime feature schema is
  `toronto_feature_store_v1.14`.
- `paired_candidate_replay`: paired candidate replay remains `BLOCK`, daily-
  first blocked validation remains `BLOCK`, and cutover remains
  `DO_NOT_CUT_OVER`.
- `promotion_refresh_broad_claim`: aggregate/daily-first promotion evidence
  still does not allow the weather-only broad claim.
- `hourly_ten_minute_weak_slot_gate`: the hourly/ten-minute weak-slot promotion
  gate is not clear.
- `bottom_location_gate`: bottom-location winner-centering remains blocked;
  first blocker is current Brier regression `+0.0307`.
- `exact_band_distance_zero_gate`: exact-band/distance-zero calibration remains
  blocked; first blocker is market gap `+0.0047` against the `+0.0030`
  tolerance.
- `source_missingness_location_gate`: source/missingness location gate remains
  blocked; first blocker is Miami all-fresh market gap `+0.0215`.

The gate still passes training validation provenance for the existing artifact
and report, but no schema-current retrain/re-export was produced here. The item
therefore remains partial with an up-to-date fail-closed gate and explicit
blocking evidence.
