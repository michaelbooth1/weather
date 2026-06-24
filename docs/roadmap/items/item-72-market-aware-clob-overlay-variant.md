# 72. Market-Aware CLOB Overlay Variant [COMPLETE 2026-06-16 - MARKET-INFORMED QUOTE GATES LIVE]

Goal: evaluate a market-informed CLOB overlay as a separate quote-time variant,
without using it as evidence that the weather model independently beats the
market.

Source: `docs/research/MULTI_VARIANT_SHADOW_TEST_DESIGN_2026-06-15.md`.
The current raw CLOB overlay is promising on eligible rows: micro Brier
`0.0303` versus base candidate Brier `0.0376` and market Brier `0.0299`. The
taxonomy-gated overlay currently affects only `437` rows and has near-zero
aggregate effect, so the next work is a disciplined market-informed shadow
track rather than broad serving.

Why this is missing: item 38 created the CLOB feature and taxonomy-gated overlay
path, but the broader promotion stack still treats one candidate artifact as
the main comparison target. The project needs a separate market-aware track
with its own gates, log-loss/calibration checks, and quote-use semantics.

- [x] Register the CLOB overlay as a market-informed variant in item 69's
  multi-variant shadow harness.
- [x] Keep raw overlay and gated overlay scores separate; only the gated overlay
  can be eligible for operational policy use.
- [x] Require out-of-fold training and paired replay gates by taxonomy, with
  separate thresholds for delta versus base candidate and delta versus market.
- [x] Start with the predeclared target taxonomies `market_lead` and
  `book_liquidity_artifact`, then consider `boundary_rounding_error` and
  `stale_source` only after minimum-row and replay gates pass.
- [x] Add log-loss, ECE, and overconfidence checks so an overlay cannot pass on
  Brier while becoming unusably sharp for quoting.
- [x] Feed gated, proven market-aware cells into the known-edge map and
  market-making policy as quote-time permissions, not no-market model
  promotion evidence.

Acceptance: the CLOB overlay has a durable market-informed shadow lane with
taxonomy-level replay proof, calibration/log-loss guardrails, and clear
downstream quote-policy semantics that remain separate from weather-model
accuracy claims.

Implementation update 2026-06-15:

- The CLOB overlay report now exports an item-69-compatible long-form CSV at
  `data/backtest/clob_overlay_shadow_variants.csv` by default.
- The exported shadow family includes a no-market base control,
  `clob_overlay_raw_oof`, and `clob_overlay_gated_taxonomy`; the overlay variants
  are marked `uses_market_features = true`.
- Raw overlay and taxonomy-gated overlay scores remain separate in the
  microstructure report.
- The initial gate target list is restricted to `market_lead` and
  `book_liquidity_artifact`.
- Taxonomy gates now require Brier improvement versus the base candidate and
  market, no log-loss regression versus the base candidate, bounded ECE, and a
  bounded high-confidence wrong-rate.
- The CLI exposes `--microstructure-variant-out`; passing an empty string
  disables variant export.

Verification 2026-06-15:

- `.\venv\Scripts\python.exe -m pytest tests\calibration\test_pooled_candidate_replay.py -q`
  passed.
- `.\venv\Scripts\python.exe -m src.schema_registry audit --strict --paths src\weather\calibration\pooled_candidate_replay.py src\weather\schema_registry.py`
  passed.

Paired shadow evidence 2026-06-16:

- Ran `data/backtest/clob_overlay_shadow_variants.csv` through item 69's
  multi-variant report and wrote
  `data/backtest/item72_clob_multi_variant_shadow_report.md`,
  `data/backtest/item72_clob_multi_variant_shadow.json`, and
  `data/backtest/item72_clob_multi_variant_shadow_long.csv`.
- The item-69 report scored `154,528` rows across `44` market-days and `11`
  F markets with status `OK`, `0` errors, and `0` warnings.
- `clob_overlay_gated_taxonomy` remains on the market-informed track. Its
  daily-first Brier was `0.0430` versus current serving `0.0435` and market
  `0.0378`, so it improves current by `0.0005` but trails market by `0.0052`.
- The raw out-of-fold overlay scored `19,668` eligible rows over `22` days with
  daily-first Brier `0.0176` versus current `0.0214` and market `0.0173`.
  This is close to market parity on eligible rows, but it is still
  market-informed evidence, not no-market model edge.
- The refreshed full replay gate allowed only `market_lead` (`75` overlay rows;
  overlay Brier `0.0000` versus candidate `0.0087` and market `0.0007`).
  `book_liquidity_artifact` stayed blocked even though its Brier improved,
  because log-loss regressed versus the base candidate
  (`logloss_delta_vs_candidate +0.2029 > +0.0000`).

Completion update 2026-06-16:

- Refreshed `data/backtest/f_family_promotion_refresh.json` and regenerated
  `data/backtest/mm_known_edge_map.json` plus
  `data/backtest/mm_known_edge_map.md`.
- The known-edge map now carries one `CLOB_OVERLAY_MARKET_INFORMED` record for
  `market_lead`. The record is `edge_research`, not `edge_allowed`, and is
  marked `uses_market_features=true`, `market_informed=true`,
  `quote_time_only=true`, and `weather_model_promotion_evidence=false`.
- `book_liquidity_artifact` is visible as a blocked taxonomy in the refreshed
  promotion gate, not as a quote permission.
- `mm_known_edge_map.md` renders a dedicated `CLOB Overlay Quote Permissions`
  section with taxonomy row counts, overlay/candidate/market Brier, ECE,
  log-loss, and quote permissions.
- `mm_policy` consumes these taxonomy-specific known-edge records when a
  quote-time row carries `casebook_taxonomy` or `known_edge_taxonomy`. Only
  `edge_allowed` sets `known_edge_allowed=true`, so this market-informed
  `edge_research` record is traceable policy context, not permission for
  model-skewed quoting.
- Focused tests cover known-edge map generation and quote-policy consumption of
  guarded CLOB overlay taxonomy records, including a stale-gate case that must
  emit no permission records.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - MARKET-INFORMED QUOTE GATES LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

