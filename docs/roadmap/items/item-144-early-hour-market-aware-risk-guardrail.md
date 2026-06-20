# 144. Early-Hour Market-Aware Risk Guardrail [PARTIAL 2026-06-18 - GUARDRAIL LIVE, MARKOUT EVIDENCE BLOCKED]

Goal: protect trading and quote decisions during 00:00-08:00 local hours where
the no-market weather model trails market prices, without treating a
market-price blend as improved weather edge.

Source: `data/backtest/hourly_model_performance_report.md` from the repeatable
hourly audit in `src/weather/reporting/hourly_model_performance.py`. On the
complete/manual_override corpus, the audit scored 54 market-days and 14,025
hourly checkpoint rows. The worst Brier hours were 03:00, 04:00, and 05:00.
The market-price blend probe improved 03:00 Brier from `0.0739` to `0.0600`
and 05:00 from `0.0704` to `0.0586`, while the model-only partition-power
probe barely moved those hours: 03:00 from `0.0739` to `0.0733` and 05:00
from `0.0704` to `0.0698`.

Why this matters: early-hour losses are not mostly a probability-sharpening
problem. The model distribution is often centered wrong while the day is still
forecast-driven. Market-price blending can reduce quote risk, but it mostly
does so by becoming the market, so it should be a risk overlay rather than a
weather-model promotion path.

## Design

1. Add an early-hour trust or risk multiplier keyed by local capture hour,
   market, source state, and source agreement.
2. In market-making policy, cap position size, widen quotes, or require a
   larger model-market edge for 00:00-08:00 unless forecast/source agreement is
   strong.
3. Optionally compute a market-aware fair-value overlay for quote-risk
   decisions only, stored separately from the no-market model probability.
4. Shadow the base policy against the guardrail on settled tapes and
   live-forward markouts before enabling live controls.
5. Coordinate with items 134, 135, and 136 for the medium-term forecast-dominant
   model lane, but keep this item focused on near-term risk control.

- [x] Add hourly trust bands for 00:00-08:00, 09:00-14:00, 15:00-19:00, and
  20:00-23:00 to market-making policy inputs.
- [x] Add a market-aware guardrail field that can constrain size or quote
  aggressiveness without replacing the no-market probability.
- [x] Produce a shadow report comparing base policy, early-hour capped policy,
  and market-aware guardrail policy on settled market-days.
- [ ] Add live-forward markout evidence showing whether the guardrail reduces
  early-hour drawdown and stale-confidence exposure.
- [x] Document when the guardrail may be overridden, including minimum edge,
  source agreement, and forecast freshness requirements.

Acceptance: the guardrail reduces early-hour realized or mark-to-market loss
versus the current policy on replay and live-forward evidence, while no-market
model metrics remain reported separately and cannot be hidden by market-price
overlays.

## Implementation update - 2026-06-18

`weather.market.mm_policy` now emits market-local hourly trust bands on quote
intents: `early_00_08`, `midday_09_14`, `late_15_19`, and `closing_20_23`.
For active early-hour rows it writes a risk-only
`market_aware_overlay_probability`/`market_aware_overlay_edge`, widens quotes,
caps size by `early_hour_guardrail_size_multiplier`, and blocks edge-mode quotes
that do not clear `early_hour_guardrail_min_edge`. The no-market
`fair_probability` is left unchanged and remains the only model-quality field.

Override requirements are explicit in policy config. The default override needs:
`source_fresh=True`, `source_freshness_state=all_fresh`,
`forecast_source_count_bucket` in `normal_count,high_count,full_count`,
`forecast_disagreement_bucket` in `low_disagreement,moderate_disagreement`,
`forecast_disagreement <= 1.5` when present, and absolute no-market edge at
least `early_hour_guardrail_override_min_edge` (`0.10` by default). Without that
combination, early-hour rows remain capped/widened or fail the minimum-edge
guard.

`weather.market.mm_paper` now includes
`early_hour_market_guardrail_shadow_v0.1` in the paper payload and markdown
report. It compares current/base exposure, early-hour capped exposure, and a
market-aware stand-down shadow while recording
`market_overlay_is_risk_only=True` and `no_market_probability_preserved=True`.
The item-specific artifact
`data/backtest/item144_early_hour_guardrail_paper_report.md` was generated from
`data/mm_runs/2026-06-16/20260616T134955890758Z`: 14 live-forward early-hour
quote rows, base quote size 140.0, capped quote size 49.0, and market-aware
stand-down quote size 0.0. The run has 5 queue-estimated fill legs but zero
conservative fill rows, so the guardrail shadow status is `NO_FILL_EVIDENCE`.

Partial blocker: the guardrail is wired into policy and paper reporting, and
unit coverage proves loss reduction on a settled early-hour losing fill, but
the current live-forward artifacts do not yet contain conservative early-hour
fill markouts. Acceptance remains open until a scoreable live-forward or
settled replay run provides conservative fill rows with 30m/settlement markouts.

Validation:

- `python -m pytest -q tests\market\test_mm_policy.py tests\market\test_mm_paper.py tests\operations\test_schema_registry.py`
- `python -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-16\20260616T134955890758Z --json-out data\backtest\item144_early_hour_guardrail_paper_report.json --report-out data\backtest\item144_early_hour_guardrail_paper_report.md --fills-out data\backtest\item144_early_hour_guardrail_fills_long.csv --known-edge-out data\backtest\item144_early_hour_guardrail_known_edge_map.json --known-edge-report-out data\backtest\item144_early_hour_guardrail_known_edge_map.md`
