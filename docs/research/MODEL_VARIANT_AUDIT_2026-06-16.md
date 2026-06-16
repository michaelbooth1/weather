# Model Variant Audit - 2026-06-16

Question: are the model variants collecting more data as intended?

Answer: partially. The item-69 harness is collecting more paired variant
predictions over the same settled observations, which is useful for faster
model comparison. It is not, by itself, collecting more independent labels,
market-days, or snapshots. More variants multiply scored rows; only new settled
market-days or broader corpora increase independent evidence.

## Evidence Inventory

Current full F-family shadow evidence centers on 67,430 unique
market/date/snapshot/band observations across 6,130 snapshots, 44 market-days,
and 11 markets.

| Export | Rows | Unique observations | Snapshots | Market-days | Markets | Variants | Finding |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| `item70_exact_winner_shadow_variants_full.csv` | 67,430 | 67,430 | 6,130 | 44 | 11 | 1 | One exact-winner score per observation. |
| `item71_dynamic_source_shadow_variants_full.csv` | 67,430 | 67,430 | 6,130 | 44 | 11 | 1 | One dynamic-source score per observation. |
| `item70_71_full_multi_variant_shadow_long.csv` | 134,860 | 67,430 | 6,130 | 44 | 11 | 2 | Clean paired comparison: exactly two no-market scores per observation. |
| `clob_overlay_shadow_variants.csv` | 154,528 | 67,430 | 6,130 | 44 | 11 | 3 | Adds market-informed CLOB variants; raw OOF only covers 19,668 rows / 22 days. |
| `conservative_bridge_shadow_variants.csv` | 134,860 | 67,430 | 6,130 | 44 | 11 | 2 | Adds a no-market policy score plus a control row per observation. |
| `item35_density_full_shadow_variants.csv` | 76,879 | 76,879 | 6,989 | 51 | 12 | 1 | Only inspected export that expands independent market-day/snapshot coverage. |

## Current Variant Performance

No-market model variants are giving useful paired evidence:

| Variant | Rows | Days | Daily delta vs current | Daily delta vs market | Status |
| :--- | ---: | ---: | ---: | ---: | :--- |
| `pooled_f_dynamic_source_state_v0_1` | 67,430 | 44 | -0.001454 | +0.004212 | Best current no-market lane; still trails market. |
| `pooled_f_exact_winner_catchup_v0_1` | 67,430 | 44 | -0.000552 | +0.005114 | Useful targeted exact-winner evidence; weaker aggregate than dynamic source. |
| `conservative_bridge_policy_v0_1` | 67,430 | 44 | -0.001143 | +0.004523 | Useful operational policy evidence, not a model-learning fix. |
| `item50_pooled_forecast_v3_candidate` | 67,430 | 44 | -0.001567 | +0.004099 | Strong no-market candidate in current exports; should be compared directly with dynamic-source in a clean report. |
| `pooled_f_candidate_miami_current_fallback_v0_1` | 67,430 | 44 | -0.001452 | +0.004215 | Looks close to current canonical promotion behavior; not new independent evidence. |

Market-informed variants are useful but must stay in a separate lane:

| Variant | Rows | Days | Daily delta vs current | Daily delta vs market | Status |
| :--- | ---: | ---: | ---: | ---: | :--- |
| `clob_overlay_gated_taxonomy` | 67,430 | 44 | -0.001456 | +0.004210 | Gated market-informed evidence; not valid for no-market model-edge claims. |
| `clob_overlay_raw_oof` | 19,668 | 22 | -0.003824 | +0.000295 | Stronger where CLOB data exists, but coverage is incomplete and market-informed. |

The current promotion/monitor layer still warns against broad edge claims:

- `shadow_ab_monitor` status is `ALERT`.
- Aggregate candidate still trails market Brier by about `+0.0042`.
- 7 F markets remain shadow: Austin, Chicago, Dallas, Miami, NYC,
  San Francisco, and Seattle.
- 4 markets are promote-ready: Atlanta, Denver, Houston, and Los Angeles.

## Data Collection Assessment

What is working:

- The harness is collecting paired predictions for multiple variants over the
  same observations. This is the intended data shape for fast A/B comparison.
- Item 70 and item 71 are fully paired: both cover the same 67,430
  observations, so their deltas are comparable without row-selection bias.
- The long CSVs include immutable variant metadata: artifact hash,
  postprocess config hash, experiment start date, market id, target date,
  snapshot id, band key, current probability, market price, and outcome.
- Source-state and CLOB outputs create useful diagnostic slices that did not
  exist in the single-candidate lane.

What is not working as "more data":

- Most variant exports do not add independent evidence. They rescore the same
  44 settled market-days and 6,130 snapshots.
- Several old alpha/smoke/full variant files remain side by side. They are
  useful history, but they can inflate perceived experiment volume if counted
  as active evidence.
- Combining CLOB and bridge exports duplicated the same
  `pooled_f_candidate_control` observations. Before this audit the combined
  item72/73 report showed `OK`; after the governance fix it now shows `WARN`.
- Raw CLOB OOF evidence covers only 19,668 rows and 22 days, so it is a
  narrower slice than the 67,430-row full replay lane.

## Governance Fix Applied

`weather.reporting.multi_variant_shadow` now warns when:

- the same `variant_id` repeats the same market/date/snapshot/band observation;
- one `variant_id` carries conflicting immutable metadata, such as different
  `variant_family` values across combined exports.

Regenerated evidence:

- `item70_71_full_multi_variant_shadow_report.md`: `OK`, 134,860 scored rows,
  2 variants, zero warnings.
- `item72_73_full_multi_variant_shadow_report.md`: `WARN`, 289,388 scored
  rows, 4 variants, two warnings for duplicated `pooled_f_candidate_control`
  rows and conflicting control-family metadata.

## Verdict

The multi-variant system is useful and is collecting the right kind of paired
prediction data for faster model iteration. It is not yet collecting more
independent outcome data. The current evidence says "more scored comparisons,"
not "more labels."

The highest-signal next step is to keep the paired harness but make experiment
accounting stricter:

1. Count unique market/date/snapshot/band observations separately from scored
   variant rows in every monitor.
2. Deduplicate or namespace shared control rows before combining unrelated
   families such as CLOB overlay and conservative bridge.
3. Promote reports should distinguish active variants from stale alpha/smoke
   historical artifacts.
4. If the goal is truly more independent data, the bottleneck is daily settled
   market-day collection, not the number of variants.

## Roadmap Follow-Ups

Added follow-up roadmap tasks:

- Item 83: [Shadow Evidence Accounting And Active Variant Registry](../roadmap/items/item-83-shadow-evidence-accounting-and-active-variant-registry.md).
- Item 84: [Cross-Family Control De-Duplication And Variant Namespace Hygiene](../roadmap/items/item-84-cross-family-control-deduplication-and-variant-namespace-hygiene.md).
- Item 85: [Independent Market-Day Evidence Expansion For Variant Evaluation](../roadmap/items/item-85-independent-market-day-evidence-expansion-for-variant-evaluation.md).
- Item 86: [No-Market Candidate Bakeoff And Promotion Lane Selection](../roadmap/items/item-86-no-market-candidate-bakeoff-and-promotion-lane-selection.md).

Completion evidence:

- Item 83 is complete: `multi_variant_shadow`, `shadow_ab_monitor`, and
  `promotion_refresh` now expose unique-observation accounting separately from
  scored rows, and `config/model_variant_registry.json` classifies active,
  control, archived, smoke/alpha, no-market, market-informed, and policy-only
  variants.
- Item 84 is complete: regenerated `item72_73_full_multi_variant_shadow_report.md`
  is `OK` after dropping 67,430 duplicate shared-control rows, with zero
  warnings and zero errors under duplicate-observation policy `error`.
- Item 85 is complete: `model_variant_evidence_growth_report.md` alerts when
  item 86 adds 269,720 scored rows but 0 unique observations versus the 70/71
  baseline, defines a default minimum increment of at least 1 new unique
  observation and 1 new market-day for broad promotion claims, and the same
  report is wired into daily refresh as `model_variant_evidence_growth`.
- Item 86 is complete: `item86_no_market_bakeoff_multi_variant_shadow_report.md`
  selects `item50_pooled_forecast_v3_candidate` as the canonical no-market
  shadow lane over the same 67,430 unique observations. It is not
  promotion-ready because it still trails market by `+0.0041`.
