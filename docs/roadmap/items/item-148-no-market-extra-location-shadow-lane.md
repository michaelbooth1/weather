# 148. No-Market Extra-Location Shadow Lane [COMPLETE 2026-06-18 - SHADOW LANE QUARANTINED]

Goal: create a separate shadow lane for training experiments that add
non-Polymarket locations, with hard gates that prevent naive cross-location
pooling from entering the promoted model.

Source: `scratch/no_market_location_fast_audit.md` and
`scratch/no_market_location_fast_audit.json`. The paired 2024-2025 holdout over
the 11 F-family markets showed that naive extra-location pooling was harmful
relative to target-only history: `target_plus_extra` worsened daily-first
synthetic-band Brier by `+0.00729` with CI `[+0.00501, +0.00969]`, and
`extra_only` worsened it by `+0.08004` with CI `[+0.07000, +0.09036]`.
Exact-bucket scoring told the same story. Item 86 still shows that no-market
variants can help versus current replay, but item 48 keeps promotion blocked
until market-price and per-market gates clear.

Why this matters: adding more locations can look like evidence growth while
actually adding domain-shift noise. The current no-market variant lane compares
candidate probabilities on existing market observations, but it does not yet
separate "extra-location supervised labels" from ordinary pooled candidate
training.

## Design

1. Add a `no_market_extra_locations` variant track distinct from existing
   no-market weather candidates and market-informed overlays.
2. Require every export row to declare whether it used extra-location labels,
   which locations were included, and whether target-local labels were present.
3. Gate promotion on target-market self-comparison: target-only versus
   target-plus-extra on the same held-out target market-days.
4. Block the lane when daily-first Brier, log loss, or mean absolute error
   regresses beyond tolerance for any target market or key cutoff regime.
5. Keep market-price comparison optional for this lane, but keep market-price
   readiness as a separate item-48 promotion blocker for actual serving.
6. Feed independent location/day counts into item 85's evidence-growth report
   so row multiplication cannot masquerade as new labels.

- [x] Add a variant registry track for `no_market_extra_locations`.
- [x] Add shadow export metadata for extra-location provenance and target-local
  label inclusion.
- [x] Add a promotion gate that compares target-only, target-plus-extra, and
  extra-only runs on daily-first target market-days.
- [x] Block any extra-location candidate whose confidence interval is clearly
  positive for Brier/log-loss deltas versus target-only.
- [x] Surface the gate status in promotion refresh and multi-variant shadow
  reports.

Acceptance: extra-location labels can be scored in shadow, but they cannot
affect promoted serving artifacts unless target-plus-extra beats or ties
target-only on blocked daily-first self-comparison with explicit per-market and
per-regime evidence.

## 2026-06-18 implementation update

Added a quarantined `no_market_extra_locations` track to
`config/model_variant_registry.json` with flat-pooling and
similarity-weighted variants marked shadow-only and excluded from ordinary
no-market headline selection.

`weather.reporting.multi_variant_shadow` now accepts extra-location provenance
columns on every long-table row:

- `used_extra_location_labels`
- `extra_location_ids`
- `target_local_labels_present`
- `extra_location_gate_status`
- `extra_location_gate_reason`
- `extra_location_weight`

The report now has a `No-Market Extra-Location Shadow Lane` section and blocks
or shadows the lane independently from item 50/current no-market promotion
selection. `weather.reporting.variant_evidence_growth` also reports
extra-location label rows and independent extra-location days so row
multiplication cannot count as new labels.

`weather.reporting.promotion_refresh` accepts
`--extra-location-transfer-report` and surfaces that report's
`promotion_gate` as a readiness blocker/open item. Serving promotion remains
disallowed unless the target-vs-extra gate is `PASS`.
