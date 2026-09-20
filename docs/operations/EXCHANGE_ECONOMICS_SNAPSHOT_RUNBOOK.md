# Exchange Economics Snapshot Runbook

- **Owns:** collect / accept / drift for the exchange-economics snapshot
  (`weather.market.exchange_economics`), its daily refresh task, and the
  rebate/reward claim boundary.
- **Read when:** the economics gate blocks paper evidence, the snapshot is
  stale, or fees/rebates/rewards enter a P&L claim.
- **Do not use for:** maker strategy or economic scope
  ([item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md)),
  live order authority (none is authorized — `STATE_OF_PLAY.md`).
- **Verify with:** `Get-ScheduledTask -TaskName WeatherExchangeEconomicsSnapshotRefresh | Get-ScheduledTaskInfo`
  and the `verified_at_utc`/gate fields of
  `data\backtest\exchange_economics_snapshot.json`.

> **Status:** armed. The 2026-09-13 owner-reviewed Scheduler inventory retained the
> economics refresh; confirm with `Get-ScheduledTask -TaskName WeatherExchangeEconomicsSnapshotRefresh`. Acceptance is always manual.

This runbook owns the production lifecycle for
`data/backtest/exchange_economics_snapshot.json` and
`data/backtest/exchange_economics_accepted_snapshot.json`.

The production venue is **International Polymarket** (`polymarket_global`).
Polymarket US is not an allowed production platform on this host.

## Runtime proof

The v0.3 snapshot is collected from current official Gamma, CLOB, and
documentation surfaces. It
binds every configured active weather condition to its condition ID, token IDs,
fee schedule, maker-rebate rate, order minimum, tick size, and current reward
configuration. It also binds the official pUSD collateral proxy, the program's
pUSD payout description, the reconciliation API's legacy USDC-named amount
field, and the requirement for later wallet-delta reconciliation. Each HTTP
response or rule document is represented by its URL and SHA-256 hash. The
snapshot hash includes the complete per-condition table and payout semantics.

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
- https://docs.polymarket.com/resources/contracts

## Collect a current snapshot

Run outside the 12:00-18:00 graded capture window:

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics collect-global --target-date <yyyy-mm-dd>
```

The collector reads `config/location_market_events.json` to choose exact active
conditions, validates Gamma identity against the tracked condition/token map,
fetches current reward campaigns from the CLOB, validates the complete payload,
and only then replaces the ignored runtime snapshot.

For isolated preparation or a branch proof, write a new external snapshot
instead of replacing production state. Collection is not baseline acceptance:

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics collect-global `
  --event-metadata C:\pilot\location-market-events.json `
  --snapshot C:\pilot\exchange-economics-v0.3.json `
  --target-date $targetDate `
  --max-age-hours 2
```

Audit the resulting gate and source hashes. Do not run `accept` merely because
collection passed.

The daily helper `scripts\ops\refresh_exchange_economics_snapshot.ps1`
(`-TargetDate` defaults to today's local date; `-EventMetadata`, `-Snapshot`,
`-Platform`) runs the same collector. The scheduled task
`WeatherExchangeEconomicsSnapshotRefresh` runs it daily; its registrar
(`-At`, default `09:00`) replaces the task when re-run, so do not run the
registrar just to refresh a snapshot:

```powershell
.\scripts\ops\refresh_exchange_economics_snapshot.ps1          # refresh now
.\scripts\ops\register_exchange_economics_refresh.ps1          # (re)register the daily task
```

The helper accepts only `polymarket_global` and never accepts a baseline. A missing, stale, partially matched, or
content-tampered snapshot blocks paper/trading evidence.

This is a **current-day** proof. Do not apply today's per-condition rates to a
historical leg merely because its token still appears in a file. Historical
paper rows need economics captured contemporaneously on the row or in a
date-bound snapshot; otherwise their economics stay unbound and zero. The
maker runner therefore freezes the validated snapshot as
`exchange_economics_snapshot.json` inside each run folder. Later ticks may
reuse only the exact same content, and scoring verifies the file hash, source
hash, snapshot identity, quote-row identity, target date, and run-time
freshness before binding a leg. A legacy run without that capture remains
unbound; the scorer must not substitute today's daily condition for it. The
binding pass keeps only per-run identity summaries, then mutates disk-backed
legs in place; it must not group or materialize all legs in memory. The
daily drift step therefore records the settled-analysis date separately while
validating the snapshot against the current Toronto operating date.

## Economic claim boundary

Maker rebates are execution-dependent. Paper fills use the exact bound
condition's fee rate and rebate rate. The scorer supports the current weather
fee curve (`exponent = 1`) and fails closed if that field changes; it does not
silently extrapolate a new curve. The snapshot also binds the documented
five-decimal fee precision, `0.00001 pUSD` minimum non-zero fee, daily payout
cadence, per-market calculation scope, and `$1 pUSD` minimum accrued rebate.
The theoretical fee-curve rebate stays diagnostic and is excluded from
acceptance P&L until a later live pilot reconciles the public, exact-maker,
exact-date, exact-condition daily `/rebates/current` result and payout asset.
The endpoint does not require authentication, but its response still needs
strict scope and completed-cycle validation. This matters most for min-size
tests: a positive per-fill estimate does not prove that any rebate was paid.

Liquidity rewards are excluded from primary P&L: the enforced assumption is
zero. Per-condition campaign metadata is retained for diagnostics, but no
counterfactual reward dollars enter profitability until venue-valid scoring and
actual payout reconciliation exist. Do not increase risk or notional caps to
qualify for a reward campaign.

## Accept the baseline

Accept only after reviewing the current per-condition snapshot and deciding
whether material drift requires paper-evidence rescoring:

```powershell
$targetDate = "YYYY-MM-DD"
.\venv\Scripts\python.exe -m weather.market.exchange_economics accept `
  --target-date $targetDate `
  --acknowledge-payout-asset-conflict
```

Acceptance copies the validated snapshot to
`data/backtest/exchange_economics_accepted_snapshot.json` and writes the drift
report. The acknowledgment is mandatory because the official program calls the
payout pUSD while the reconciliation API describes `rebated_fees_usdc` as a
USDC amount. It does not resolve that conflict or prove payment; the later live
receipt still requires the returned asset address and observed wallet balance
delta. The address must equal the current pUSD collateral proxy content-bound
from the official contracts page. Never schedule automatic acceptance.

## Drift check

```powershell
.\venv\Scripts\python.exe -m weather.market.exchange_economics drift --target-date <yyyy-mm-dd>
```

Healthy state requires a passing current gate, a present reviewed baseline, and
`rescore_required = false`. Exact condition and token identity is revalidated
on every collection and changes normally as daily weather markets roll. It is
part of the snapshot hash, but identity rotation alone is not economics drift.
Location-level fee, rebate, fee-curve, tick, or minimum-order profile changes
are material. Reward configuration is retained but cannot trigger a primary-P&L
rescore while the enforced reward assumption remains zero.

## Update this file when

Update when the venue, official endpoints, snapshot schema, per-condition
binding, reward claim boundary, refresh command, or acceptance procedure
changes.
