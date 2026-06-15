# 62. Nearby Station Validation And Promotion Gates [NEW - AUDIT FOLLOW-UP]

Goal: require empirical validation before a nearby station can be promoted from
"available data" to "usable redundant history."

Audit source: `docs/research/HISTORICAL_AND_NEARBY_DATA_AUDIT_2026-06-15.md`.
Toronto `CAN06158733` is the reference case: 0.05 km from the canonical station,
537 target-season WU overlap days, 0.247 C MAE, and 99.6% WU bucket match.

Tasks:

- [ ] Define validation thresholds by market unit and source role: minimum
  overlap days, target-season MAE, bucket-match rate, max absolute difference,
  missing-day reduction, and maximum distance/elevation mismatch.
- [ ] Generate a durable bias report for each candidate nearby source against
  WU settlement history, METAR/ASOS, canonical GHCNh where available, and
  reanalysis as a weak sanity check.
- [ ] Split validation by full period, target season, and weather regime so a
  station that works in mild May/June weather is not blindly trusted elsewhere.
- [ ] Add promotion states: `candidate`, `validated_supplemental`,
  `shadow_only`, `rejected`, and `retired`.
- [ ] Fail closed when a supplemental source lacks a current validation report
  or when its metrics fall outside the configured thresholds.

Acceptance: no nearby station can enter training or source-trust features until
its validation artifact proves acceptable overlap, bias, bucket agreement, and
distance/elevation suitability for the intended market/date window.
