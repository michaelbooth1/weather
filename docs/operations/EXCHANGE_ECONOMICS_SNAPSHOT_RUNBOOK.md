# Exchange Economics Snapshot Runbook

This runbook owns the production lifecycle for
`data/backtest/exchange_economics_snapshot.json` and
`data/backtest/exchange_economics_accepted_snapshot.json`.

The production venue is **International Polymarket** (`polymarket_global`).
Polymarket US is not an allowed production platform on this host.

## Runtime proof

The v0.2 snapshot is collected from current official Gamma and CLOB APIs. It
binds every configured active weather condition to its condition ID, token IDs,
fee schedule, maker-rebate rate, order minimum, tick size, and current reward
configuration. Each HTTP response is represented by its URL and SHA-256 hash.
The snapshot hash includes the complete per-condition table.

The tracked file
`docs/research/exchange_economics_snapshot_template.json` documents the shape
only. Its `manual_template_not_runtime_proof` marker intentionally fails the
runtime gate. Stamping a new `verified_at_utc` on that file is not verification.

Official sources:

- https://docs.polymarket.com/trading/fees
- https://docs.polymarket.com/programs/maker-rebates
- https://docs.polymarket.com/programs/liquidity-rewards
- https://docs.polymarket.com/api-reference/rewards/get-current-active-rewards-configurations
- https://docs.polymarket.com/api-reference/rebates/get-current-rebated-fees-for-a-maker

## Collect a current snapshot

Run outside the 12:00-18:00 graded capture window:

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics collect-global --target-date 2026-08-13
```

The collector reads `config/location_market_events.json` to choose exact active
conditions, validates Gamma identity against the tracked condition/token map,
fetches current reward campaigns from the CLOB, validates the complete payload,
and only then replaces the ignored runtime snapshot.

The daily helper uses today's local date and the same collector:

```powershell
.\scripts\ops\register_exchange_economics_refresh.ps1
```

It accepts only `polymarket_global`. A missing, stale, partially matched, or
content-tampered snapshot blocks paper/trading evidence.

## Economic claim boundary

Maker rebates are execution-dependent. Paper fills use the exact bound
condition's fee rate and rebate rate. The scorer supports the current weather
fee curve (`exponent = 1`) and fails closed if that field changes; it does not
silently extrapolate a new curve. A later live pilot must reconcile paid rebates
and payout asset through the authenticated `/rebates/current` endpoint before
scaling.

Liquidity rewards are excluded from primary P&L: the enforced assumption is
zero. Per-condition campaign metadata is retained for diagnostics, but no
counterfactual reward dollars enter profitability until venue-valid scoring and
actual payout reconciliation exist. Do not increase risk or notional caps to
qualify for a reward campaign.

## Accept the baseline

Accept only after reviewing the current per-condition snapshot and deciding
whether material drift requires paper-evidence rescoring:

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics accept --target-date 2026-08-13
```

Acceptance copies the validated snapshot to
`data/backtest/exchange_economics_accepted_snapshot.json` and writes the drift
report. Never schedule automatic acceptance.

## Drift check

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics drift --target-date 2026-08-13
```

Healthy state requires a passing current gate, a present reviewed baseline, and
`rescore_required = false`. Exact condition and token identity is revalidated
on every collection and changes normally as daily weather markets roll. It is
part of the snapshot hash, but identity rotation alone is not economics drift.
Location-level fee, rebate, fee-curve, tick, or minimum-order profile changes
are material. Reward configuration is retained but cannot trigger a primary-P&L
rescore while the enforced reward assumption remains zero.

## Update when

Update when the venue, official endpoints, snapshot schema, per-condition
binding, reward claim boundary, refresh command, or acceptance procedure
changes.
