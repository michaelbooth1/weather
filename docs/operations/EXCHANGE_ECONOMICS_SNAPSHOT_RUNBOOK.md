# Exchange Economics Snapshot Runbook

This runbook owns the production lifecycle for
`data/backtest/exchange_economics_snapshot.json` and
`data/backtest/exchange_economics_accepted_snapshot.json`.

## Source Template

The tracked source template is:

```text
docs/research/exchange_economics_snapshot_template.json
```

It records current Polymarket US fee, maker rebate, liquidity-incentive,
tick-size, minimum-quantity, and order-semantics evidence from official
documentation:

- https://docs.polymarket.us/fees
- https://docs.polymarket.us/api-reference/orders/overview
- https://docs.polymarket.us/api-reference/market/overview
- https://docs.polymarket.us/incentives/liquidity
- https://docs.polymarket.us/institutional/fix-api/fix-order-entry-overview
- https://docs.polymarket.us/changelog

Update that template only after checking the current official docs. Do not edit
the ignored runtime snapshot directly.

## Publish A Current Snapshot

Publish a runtime snapshot for the evidence target date:

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics publish --target-date 2026-06-23
```

The publish action stamps `verified_at_utc`, writes
`verified_for_target_date`, recomputes the source hash and economics hash, runs
the item-300 gate, and writes the runtime snapshot only after the gate passes.

For the daily settlement refresh, use the settled market date being analyzed.
The default scheduled helper computes yesterday's local date and publishes that
snapshot before the morning refresh:

```powershell
.\scripts\ops\register_exchange_economics_refresh.ps1
```

## Accept The Baseline

Accept only after reviewing the current snapshot and confirming no paper
evidence needs rescoring:

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics accept --target-date 2026-06-23
```

This copies the current validated snapshot to
`data/backtest/exchange_economics_accepted_snapshot.json` and writes
`data/backtest/exchange_economics_drift.json`. Do not schedule automatic
acceptance; otherwise a real rule change could be accepted before affected
paper evidence is rescored.

## Drift Check

Daily refresh runs the exchange economics drift gate by default:

```powershell
.\venv\Scripts\python.exe -m weather.operations.daily_refresh run --continue-on-error --fail-on-variant-evidence-alert
```

Focused drift validation:

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics drift --target-date 2026-06-23
```

Expected healthy state:

- `current_gate.status` is `PASS`.
- `current_gate.evidence_basis` is `current_exchange_economics`.
- `accepted_snapshot_present` is `true`.
- `rescore_required` is `false`.

If the current snapshot ages out, publish a new one for the target date. If
`rescore_required` is true, rescore paper evidence under the new economics
snapshot before accepting the new baseline.
