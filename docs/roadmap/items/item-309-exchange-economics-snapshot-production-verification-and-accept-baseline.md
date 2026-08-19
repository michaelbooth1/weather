# 309. Current Exchange-Economics Snapshot Production, Verification, And Accept-Baseline Workflow [PARTIAL 2026-08-19 - INTERNATIONAL V0.3/PUSD CONTRACT INTEGRATED; EXPLICIT ACCEPTANCE OPEN]

Goal: produce and maintain a current, source-verified exchange-economics
snapshot, with a tracked template, an accept-baseline mechanism, and a recurring
refresh workflow, so the item-300 gate has real data to validate instead of
failing closed.

Source: 2026-06-24 review of item 300. The item-300 gate framework is built -
`weather.market.exchange_economics` validates a snapshot, the daily-refresh
`exchange_economics_rule_drift` step runs it, and `market_making_run`,
`mm_paper`, and `taker_bot_bakeoff` all consume the gate. But there is no
`data/backtest/exchange_economics_snapshot.json` on disk, no tracked template
under `docs/`, no operator command to refresh it, and no README/runbook
documentation. The only snapshot constructor is `build_snapshot_payload`, a test
helper with hardcoded defaults. There is also no writer that promotes a
validated current snapshot to `exchange_economics_accepted_snapshot.json`, so
`accepted_snapshot_present` is always false and the material-drift detector can
never fire.

Why this matters: because no snapshot exists, the gate fails closed today and
every taker and maker paper run is downgraded to `paper_stale_exchange_economics`,
so the entire item-300 framework currently produces only BLOCKs and zero
countable evidence. The drift gate is also inert without an accepted baseline. A
profitability or promotion claim cannot be trusted until the fee, rebate,
reward, tick-size, and minimum-order assumptions are verified against current
official International Polymarket documentation and market surfaces rather
than test defaults. Legacy US evidence remains historical compatibility only.

Why it is not already covered: item 300 owns the gate, drift logic, evidence
threading, and tests - the software that consumes a snapshot - but not the
production, source-verification, template, accept-baseline, or refresh cadence of
the snapshot itself. Item 45 owns live platform/account verification for live
order submission, a different artifact gating a different action. Item 240
defines the friction model but does not source or refresh the rule values. No
item owns the operator lifecycle of the economics snapshot.

## Design

1. Author a tracked template (for example
   `docs/research/exchange_economics_snapshot_template.json`, mirroring item 45's
   `mm_platform_verification_template.json`) populated from current International
   Polymarket
   documentation: taker fee, maker fee, flattening fee, maker rebate pool-share
   and formula, liquidity-reward formula (distance threshold and c), tick size,
   minimum order size, and order/API semantics, each with source URLs and a
   source hash. Reconcile values against the taker config
   (`taker_fee_rate=0.05`, `fee_effective_date=2026-03-30`,
   `polymarket_symmetric_price_v1`).
2. Add an operator generator/refresh command that writes the runtime
   `exchange_economics_snapshot.json` with a fresh `verified_at_utc`, validating
   it through the item-300 gate before writing so an invalid snapshot is never
   published.
3. Add an audited accept/promote-baseline action that copies a validated current
   snapshot to `exchange_economics_accepted_snapshot.json`, so the item-300
   material-drift gate has a baseline and `rescore_required` can fire on a real
   change.
4. Add a recurring refresh cadence (a scheduled task or a daily-refresh
   sub-action) that keeps the snapshot inside the freshness window and emits a
   remediation when it ages out or material drift is detected.
5. Document the refresh and accept workflow, with the source URLs, in the README
   and an operations runbook.

- [x] Author the tracked, source-verified snapshot template from current
  Polymarket US documentation.
- [x] Add an operator generator/refresh command that writes a gate-valid runtime
  snapshot with fresh `verified_at_utc`.
- [x] Add an audited accept/promote-baseline action that populates the accepted
  snapshot.
- [x] Add a recurring refresh cadence and an age-out/material-drift remediation.
- [x] Document the refresh/accept workflow and source URLs, and add tests for
  template validity and an accept-to-drift round-trip.

Acceptance: a current, source-verified exchange-economics snapshot exists and
validates through the item-300 gate with evidence basis
`current_exchange_economics` (not `paper_stale_exchange_economics`), an accepted
baseline exists so material drift can be detected, the snapshot is refreshed on a
documented cadence inside the freshness window, and the template and workflow are
tracked and tested.

## Completion Notes

Completed 2026-06-24. `docs/research/exchange_economics_snapshot_template.json`
is the tracked source-verified template, with source hash
`9ca10e5517a9d4be486414dcb9162a3a` from current Polymarket US fee, order,
market, liquidity-incentive, FIX order-entry, and changelog documentation.
`weather.market.exchange_economics publish` now stamps and validates the ignored
runtime `data/backtest/exchange_economics_snapshot.json` before writing it, and
`weather.market.exchange_economics accept` promotes only a current validated
snapshot to `data/backtest/exchange_economics_accepted_snapshot.json`. The
current runtime snapshot and accepted baseline were published for target date
`2026-06-23`; `data/backtest/exchange_economics_drift.json` is `PASS` with
`accepted_snapshot_present=true`, `rescore_required=false`,
`material_change_count=0`, and evidence basis `current_exchange_economics`.
The documented cadence is `scripts/ops/register_exchange_economics_refresh.ps1`
at 09:00 before `register_daily_refresh.ps1`; the runbook is
`docs/operations/EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md`. Verification:
`python -m pytest tests\market\test_exchange_economics.py tests\operations\test_daily_refresh.py -q`
passed (`66 passed`).

Related: items 44, 45, 240, 259, 260, 300.

## 2026-08-14 International reopening

The June completion notes preserve the Polymarket US workflow that was true at
that time; they are not current authorization. The approved product is now
International Polymarket only, and Polymarket US must never be used. Production
has not yet integrated the isolated International snapshot implementation, so
the item's current acceptance is not satisfied.

- [x] Integrate a source-verified `polymarket_global` snapshot whose per-market
  fee schedule, maker-rebate terms, tick size, minimum size, condition id, and
  token ids come from the official International surfaces.
- [ ] Preserve explicit operator acceptance of a new economics baseline; drift
  detection must never accept a baseline automatically.
- [x] Prove the refreshed International workflow with an exact-tip full suite
  and the item-300 per-run binding repair before restoring `COMPLETE`.

Legacy US implementation and tests are compatibility/history only. They do not
authorize a US live probe, credential installation, or order mutation.

## 2026-08-15 current disposition

International snapshot production and item 300's per-run binding are integrated
and exact-suite proven. The official pUSD payout-asset contract and informed
acceptance repair are included in the current-master cumulative live-test
branch; focused tests pass, while its immutable full suite and guarded
integration remain open. The contract correctly rejects the old production
v0.2 snapshot and requires a newly collected v0.3 International snapshot.
Collection does not accept a baseline. Until the branch lands and the operator
explicitly accepts a reviewed current International baseline, drift must remain
BLOCK. No scheduled path may accept the baseline automatically.

The external one-market paper proof subsequently collected and independently
audited a fresh gate-valid v0.3 International snapshot without invoking
`accept` or changing production economics state. That closes live collection
as an assumption, but not the unchecked informed-acceptance requirement. The
paper and candidate outcome is recorded only in
`docs/operations/ESTABLISHED_FINDINGS.md` section 8q.

The cumulative client/pUSD parent is now in production at merge
`3c326ac1c03b415877da33dc254b39d32f576de4` after its exact 4,489-test suite
passed. Collection and validation are therefore production software rather
than branch-only capability. The accepted-baseline checkbox deliberately
remains open: neither the merge, scheduled refresh, paper proof, nor candidate
selection may accept an economics baseline on the operator's behalf.
