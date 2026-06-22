# 222. Blocked-Market Variant Basket No-Go Guard [COMPLETE 2026-06-22 - FAILED BASKETS EMIT NO-GO DISPOSITIONS]

Goal: turn the failed blocked-market basket experiments into an explicit no-go
guard so future promotion work does not keep retesting the same item134,
item135, item147, and item32 variant combinations without new evidence.

Source: `docs/roadmap/audits/location-performance-model-audit-2026-06-22.md`.
The blocked-market basket validation selected among existing variant rows on
earlier market-days and evaluated on later market-days. The selected basket
remained `+0.0106` Brier worse than market, and all five tested markets
blocked. Adding item32 reanalysis rows did not improve the selected basket.
Guarded branch policies also failed, including Seattle item147 at about
`+0.0152` vs market and NYC item147 at `+0.0035`.

Why this matters: the audit ruled out a tempting shortcut. Without a durable
no-go record, the team can spend cycles reselecting existing variants instead
of building a new centering candidate.

## Design

1. Record failed basket/guard policies in a durable experiment-disposition
   artifact keyed by variant ids, markets, train/eval dates, and slice policy.
2. Make promotion tooling warn when a requested basket matches a known failed
   disposition without new market-days or a changed candidate family.
3. Keep oracle columns diagnostic-only and require held-out selected-policy
   clearance before any basket can count.
4. Link failed basket evidence to the repair item that owns the next experiment.

- [x] Emit a durable no-go disposition for the existing blocked-market basket
  experiments.
- [x] Add a warning/blocker when the same basket is proposed without new
  evidence.
- [x] Add a report link from the no-go disposition to item 219.
- [x] Add a regression test for a known failed basket replay.

## Completion Notes

`variant_basket_selection_validation` now emits a durable
`blocked_market_variant_basket_no_go_v0.1` disposition for blocked basket runs.
The signature is keyed by candidate variant ids, variant families, markets,
train/eval dates, slice keys, guard policies, market tolerance, and row counts.
The validation report includes a `Blocked-Market Basket No-Go Disposition`
section with the no-go status, oracle-evidence diagnostic-only policy, and a
link to item 219 as the owning repair path.

The tool can also compare a proposed basket to a known no-go disposition. It
blocks exact repeats with no new market-days or changed candidate family, warns
when new market-days are present, and treats changed candidate sets as a
non-match that still must pass the normal held-out validation gates.

Regenerated artifacts:

- `data/backtest/item147_blocked_markets_variant_basket_no_go.json`
- `data/backtest/item147_blocked_markets_variant_basket_with_item32_no_go.json`
- `data/backtest/item147_blocked_markets_variant_basket_selection_validation.json`
- `data/backtest/item147_blocked_markets_variant_basket_with_item32_validation.json`

Both regenerated basket validations remain `blocked` with selected basket
`+0.0106` Brier versus market and `5` blocked markets. The item32-expanded run
also emits its own `NO_GO` disposition because the changed candidate set still
fails held-out validation.

Verification:

- `python -m pytest tests\reporting\test_variant_basket_selection_validation.py -q`
- `python -m weather.reporting.variant_basket_selection_validation data\backtest\item147_time_split_alpha_variant_rows.csv data\backtest\item134_forecast_profile_all_hours_shadow_variants.csv data\backtest\item135_regime_weighted_all_hours_shadow_variants.csv --markets austin,los-angeles,nyc,san-francisco,seattle --out data\backtest\item147_blocked_markets_variant_basket_selection_validation.json --report data\backtest\item147_blocked_markets_variant_basket_selection_validation_report.md --no-go-out data\backtest\item147_blocked_markets_variant_basket_no_go.json`
- `python -m weather.reporting.variant_basket_selection_validation data\backtest\item147_time_split_alpha_variant_rows.csv data\backtest\item134_forecast_profile_all_hours_shadow_variants.csv data\backtest\item135_regime_weighted_all_hours_shadow_variants.csv data\backtest\item32_reanalysis_rich_no_pressure_full_merged_variant_rows.csv --markets austin,los-angeles,nyc,san-francisco,seattle --out data\backtest\item147_blocked_markets_variant_basket_with_item32_validation.json --report data\backtest\item147_blocked_markets_variant_basket_with_item32_validation_report.md --known-no-go data\backtest\item147_blocked_markets_variant_basket_no_go.json --no-go-out data\backtest\item147_blocked_markets_variant_basket_with_item32_no_go.json`

Acceptance: promotion reports identify known failed blocked-market baskets and
refuse to count them as new promotion evidence unless the run has new
market-days, a new candidate family, or a documented override.

Related: items 32, 134, 135, 147, 219.
