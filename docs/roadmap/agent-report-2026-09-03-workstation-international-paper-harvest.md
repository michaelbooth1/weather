# International market-harvest paper companion

**Verdict: PASS for implementation and workstation verification.** The normal
International model-policy daily roll now has a default-off companion that
evaluates the existing paper-only `market_harvest` policy from the exact inputs
already loaded for each tick. It writes separately identified counterfactual
evidence, uses the canonical strict paper scorer, and cannot grant live
permission or contribute authenticated fills, realized P&L, model promotion,
or live-forward evidence.

## Identity and scope

- Branch: `codex/workstation-international-paper-harvest-2026-09-94a`.
- Required and used source tip:
  `f964b9463dd850d56b10658ade14d1ecb19aec0b`.
- Required and used source tree:
  `3804704bfa72248efe4380a0d937ae62e0b8da0e`.
- Implementation/test tip:
  `d65144ec75be546db8aee254c8e9bbe02fad4a13`.
- Implementation/test tree:
  `f96bcf08acddc53d89e7e0a38c96ba89387f8ca6`.
- The source identity was checked after a live read-only fetch of `origin`; no
  mismatch occurred.
- This report is committed separately after the implementation/test commit.
  The exact final tip and tree are supplied in the handback accompanying the
  pushed branch.

The work was performed in the isolated worktree
`C:\Users\Michael\Documents\github\weather-workstation-international-paper-harvest-2026-09-94a`.
Unrelated state in the original checkout was not changed.

## P0 trace and result

The recurring path is the existing daily-roll process, not a second worker:

1. `weather.operations.market_making_daily_roll` calls the normal
   `weather.market.market_making_run` loop with `permission_profile=model`.
2. A tick reads token discovery, public book rows, source-status rows, and the
   frozen exchange-economics receipt once. Normal preflight computes its book
   audit, CSV diagnostics, and source degradation from those objects.
3. With the new flag only, the runner projects the same objects into
   market-centred harvest features, calls the existing `market_harvest` policy,
   and passes the cached normal preflight diagnostics into the companion. There
   is no second poller, large-tape reread, provider call, or exchange call.
4. The companion applies the existing run-budget and TTL lifecycle machinery,
   appends only permitted paper quote rows plus simulated lifecycle evidence,
   and atomically checkpoints bounded restart state. The ordinary model quote
   rows and their gates are not changed or replaced.
5. Daily refresh discovers only nested `market_harvest_companion` folders and
   sends them through `weather.market.mm_paper`, whose strict public
   trade-through-and-size, queue, markout, settlement, and P&L rules remain the
   scoring authority. Companion reports, fills, and queue projections have
   separate names and evidence classes.

Exact token/book/time identity is retained through run, target-date, platform,
event/condition/token, capture ID/time, policy hash, TTL, canonical hashes of
the exact book/token/source rows, source hash set, and exchange-economics
snapshot ID/hash/basis. The P0 stop conditions therefore did not apply.

## Resource bound for the 12-market day

The current built-in fleet has 12 markets and the representative fleet test
uses 11 outcomes per market: 132 policy decisions per tick. The normal
07:05-20:00 local window at a 60-second cadence is at most 775 ticks, so the
companion adds at most 102,300 row-policy evaluations for the day. These are
in-process calculations over already-loaded rows; no additional network I/O
or long-running process is introduced.

For the current two-sided 5-share, 0.49/0.51 harvest quote and the hard
25-USDC companion ceiling, the executable resource regression proves that a
132-opportunity tick persists only five quote rows, opens ten legs, records 20
first-tick lifecycle transitions, and reserves no more than 25 USDC. At 775
ticks, that sizing gives these conservative daily record bounds:

| Artifact | Current-policy daily bound |
| --- | ---: |
| Policy evaluations/opportunities summarized | 102,300 |
| Persisted quote rows | 3,875 |
| Lifecycle records, including replacement/release | 23,240 |
| Retained budget-ledger records | 17,050 |
| Processed tick hashes in restart state | 775 of the 2,048-entry cap |
| Simultaneously retained open legs | 10 in the tested fleet geometry |

That is 44,165 line records plus small atomic JSON summaries/configuration,
approximately 45-90 MB/day if serialized rows average 1-2 KiB. The byte figure
is a sizing estimate, not a storage-contract cap; the table's row counts are
the auditable bound for the tested current policy geometry.

For defensive capacity planning independent of the risk ceiling, the code's
structural ceiling is 132 persisted quote rows and 264 open legs per tick. If
every outcome fit the budget and every leg were replaced on every tick, the
one-day ceilings would be 102,300 quote rows, 613,272 lifecycle rows, and
410,486 retained ledger rows. Tick memory remains linear in one 132-row fleet,
12 binding objects, and at most 264 open legs; restart memory is capped at
2,048 64-character tick hashes plus those open legs. The normal scorer already
uses streamed/spill-backed run input; a 14-day current-policy scoring window is
at most 54,250 persisted quote rows and 108,500 quote legs.

## Preserved evidence and safety contracts

- The option is absent by default. It requires the ordinary `model` permission
  profile and rejects `live-pilot`; direct `market_harvest` remains paper-only.
- Every companion row says `platform_id=polymarket_global`. Its run ID, schema,
  directory, quote tape, lifecycle, state, live gate, scorer report, simulated
  fills, and queue output are separate from the normal model artifact family.
- Quote opportunities, simulated lifecycle, public trades, simulated queue,
  and simulated fills have distinct evidence classes. `live_trade_permission`,
  `authenticated_fill`, and `realized_pnl_eligible` remain false; authenticated
  fill and realized-P&L counts remain zero.
- Authoritative fees, rebates, and incentives remain zero. Policy estimates
  are retained only in separately labelled configured-estimate fields.
- The parent frozen economics snapshot is hard-linked on the same volume when
  possible. The fallback copies to a sibling temporary file and atomically
  replaces it; either path verifies the exact SHA-256 before the companion
  config is published.
- Stale or missing books, stale watcher state, tape gaps, missing trade size,
  token/condition mismatch, ambiguous source revisions, platform mismatch, and
  incomplete settlement fail closed through existing preflight and strict
  scorer blockers. Touch-only public trading does not fill.
- Restart state retains at most 2,048 tick identities and atomically commits
  the current open-order map. Replaying an exact tick appends no duplicate quote
  or lifecycle identity.
- The ordinary model-policy rows, known-edge gate, candidate/promotion gates,
  midpoint behavior, live gates, model artifacts, and reserved confirmation
  dates are unchanged.

## Changed files and runtime relationship

| File | Evidence supplied |
| --- | --- |
| `README.md` | Documents the default-off CLI, evidence separation, and guarded adoption. |
| `docs/operations/OPERATIONS_DESIGN.md` | Documents the one-process fan-out, strict scorer, blockers, and two-action adoption requirement. |
| `scripts/ops/market_making_daily_roll_task.ps1` | Passes the opt-in flag to the existing child only when requested. |
| `scripts/ops/register_market_making_daily_roll.ps1` | Exposes the switch for the launcher action; it was not executed. |
| `scripts/ops/register_market_making_daily_roll_supervisor.ps1` | Exposes the switch for recovery/ensure; it was not executed. |
| `src/weather/market/market_harvest_companion.py` | Owns isolated persistence, input/economics binding, restart state, evidence labels, strict scoring projection, and summaries. |
| `src/weather/market/market_making_run.py` | Fans out from the already-loaded tick while leaving normal model rows intact. |
| `src/weather/market/market_making_run_support.py` | Exposes reusable harvest book projection/assembly and cached preflight inputs. |
| `src/weather/operations/daily_refresh_trading_steps.py` | Discovers and scores companion folders separately in the existing paper-score step. |
| `src/weather/operations/market_making_daily_roll.py` | Carries the default-off option through the recurring runner. |
| `src/weather/schema_registry_recent_data.py` | Registers `market_harvest_paper_companion_v0.1`. |
| `tests/market/test_market_harvest_companion.py` | Covers strict fill/queue/settlement isolation, blockers, resume identity, economics SHA, and 132-row resource geometry. |
| `tests/market/test_market_making_run.py` | Proves a fresh companion opportunity while the normal model lane stays blocked and unchanged, plus default inertness. |
| `tests/operations/test_host_task_wrappers.py` | Proves wrapper/registrar option propagation. |
| `tests/operations/test_market_making_daily_roll.py` | Proves daily-roll propagation and default inertness. |

This is the exact per-file static diff evidence available to the canonical roll
tool. No roll classification is inferred from it here.

## Verification

| Check | Result |
| --- | --- |
| Complete directly affected market/scorer/daily-roll/wrapper/schema/reporting files | `302 passed, 35 subtests passed in 56.81s` |
| Final focused companion/resource/economics regressions | `5 passed, 4 subtests passed` |
| Full repository suite at the implementation tip via `workstation_heavy.ps1` | `4230 passed, 22 skipped, 866 subtests passed in 464.25s`; 13 warnings |
| `compileall -q app src tests` via `workstation_heavy.ps1` | exit `0` |
| PowerShell AST parse for all three changed scripts | `PASS` |
| Agent-document audit | `PASS (18 agent files, 829 Markdown files)` after this report |
| Roadmap lint/check | `OK (generated report matches sources)` |
| `git diff --check` | exit `0` before the implementation commit |

The full-suite warnings were the existing scikit-learn empty-feature warnings
and one NumPy/netCDF binary-size warning. No test failed, so there was no
introduced-versus-pre-existing failure separation to report. The full suite
and compileall ran through the checkout-owned `workstation_heavy.ps1` with the
`workstation_offline_v1` profile, host-global mutex, and kill-on-close Job.

## Adoption, roll verdict, and prohibited actions

Production cannot enable this by one guarded re-registration. After reviewed
integration, both the existing launcher action and the existing ensure/
supervisor action must be re-registered with
`-EnableMarketHarvestCompanion`; otherwise a supervisor recovery could restart
the worker without the companion. No further code integration is known to be
required, but adoption and both registrations remain separate production-owner
actions.

No roll classification was derived by hand. The canonical
`scripts/ops/roll_verdict.ps1` is unavailable inside this mission's explicit
boundary because it calls `Get-ScheduledTask` and reads production capture
closure/status files, while the mission forbids Scheduler and production
access. The production integration owner must obtain the canonical verdict
against the pushed branch before considering integration:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch origin/codex/workstation-international-paper-harvest-2026-09-94a
```

No frozen mirror, production state, Scheduler, provider, exchange, credential,
account, live execution, model, corpus, alpha allocation, promotion, release,
merge, pull request, or production mutation was accessed or performed. GitHub
`master` was not mutated; the only remote-master operation was the required
read-only origin fetch.
