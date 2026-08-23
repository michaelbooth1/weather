# State of play

**Last rewritten: 2026-08-23 12:15 America/Toronto.** Read this first, then
`ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before model,
measurement, or research work.

> **REWRITTEN, never appended. Capped at about 90 lines.** This page answers
> what is happening now. Quantitative evidence belongs in
> `ESTABLISHED_FINDINGS`; false claims in `RETRACTED_AND_FALSE_LEADS`; durable
> invariants in `AGENT_CONTEXT`; cross-host mechanics in
> `DELEGATION_CONTRACT`. Do not cite this page as quantitative evidence.

**Objectives:** protect irreplaceable capture and settlement; determine whether
International maker spread plus paid rebates exceeds adverse selection,
inventory/settlement loss, fees, and operational costs; improve the weather
forecast as a quote-centre and risk-control input. **We do not beat the market.**

## Current truth

| Area | State / next action |
| --- | --- |
| Capture | At the last pre-maintenance read, all three streak-critical workers were healthy and the supervised public execution tape was connected and integrity-valid. Complete price-path evidence remains unusable. Any maintenance restart spends capture continuity and requires fresh worker/tape recovery proof. |
| Production | `master`, checked-out `HEAD`, and `origin/master` are synchronized at `0af64ecf36287a8e88aa1f85cbfa2ff540adb03b`. Only the two expected generated location-config files are modified. |
| Integration recovery | Three integrations are production-adopted: bootstrap/recovery machinery at `d8e95c04be7c0b2daa351103b19efc1e942bc469`, the bounded morning workflow at `cfdad9e5225f4dad86eaeddae7631893cd6c5350`, and the fixed-scope Stage-0/1 stack at `0af64ecf36287a8e88aa1f85cbfa2ff540adb03b`. The last exact tip passed 19/19 chunks before guarded merge, three-worker recovery, execution-tape recovery, and remote acknowledgement. |
| Morning chain | The first post-adoption 09:30 Stage-A run published a terminal `COMPLETED` manifest at 11:30, inside its SLA. The formerly unbounded fleet tail completed quickly with every scheduled omission explicit. This is terminal-tail proof, not a clean soak: stale locks were repaired and the barrier correctly blocked on exchange-economics and maker-paper evidence. |
| Settlement | August 17 remains an explicit 12-market settlement hole and will not be retried by the ordinary chain. Recover it only through the bounded stop-after-finalize path, then prove normal lock release and real settlement evidence. |
| Tiering | The canonical 05:00 projection and 06:00 raw-tape tasks are enabled and both produced durable `OK` status on their first post-adoption runs. Scheduler zero alone is not the proof; retain the task-status artifacts and free-space trail. |
| Held work | Stage B remains disabled pending its separate monolithic resource proof. The training window remains opt-in and disabled; its independent 04:15 restore task is enabled and healthy. Do not enable either merely to test a blocker. |
| Documentation | The canonical files now reconcile all three pending integration tips and the first bounded morning readback. The transaction is complete only after this roll-free closeout is integrated and published and `weather.operations.documentation_transaction complete` writes the matching content-addressed PASS receipt. |
| Host safety | A reboot is pending and Windows reports a free-running, unsynchronized clock. Both are hard live-session blockers. Restart only in the operator-selected maintenance window, log in once afterward, and re-prove Git, clock, capture, and execution-tape health before treating the host as ready. |
| Live money | The fixed-scope sealer, session runner, process-local pinned SDK overlay, and interrupt cleanup are production software. No credential value or exchange mutation was authorized by integration, and no order has run. Credential references are prepared host evidence, but fresh economics/paper candidate, public identity, keyless doctor, Stage 0 bootstrap, sealed current wrappers, current account evidence, and supervised literal confirmations remain separate gates. |

## Closed decisions -- do not relitigate without new evidence

- International Polymarket only. Never use Polymarket US for a new probe,
  credential path, readiness decision, or mutation.
- The first live test is a plumbing/evidence probe: one market, finite
  non-raisable 100 pUSD-equivalent wallet cap, post-only, no naked sells, and
  every existing lower ceiling.
- Candidate selection is never authorization. Authoritative user events, open
  orders, positions, balances, fees, rebates, cancellation, and settlement are
  required for realized lifecycle and economics.
- Model promotion remains blocked and is not the market-centred maker pilot's
  critical path. Do not weaken promotion, serving floors, freshness, economics,
  readers, risk, or post-only enforcement to manufacture permission.
- No alpha and no paid weather provider. Economics baseline acceptance remains
  an explicit informed operator action and is never scheduled automatically.

## Immediate execution order

1. Finish the three-integration documentation transaction through a roll-free
   documentation merge, publication, and content-addressed completion receipt.
2. Use the operator-selected maintenance window for the pending reboot. After
   one login, require a synchronized clock, clean Git identity, and recovered
   capture plus execution-tape supervision before further preparation.
3. Recover August 17 separately through bounded stop-after-finalize; require
   12/12 real settlements, normal lock release, and current capture.
4. Prepare a live lifecycle only for an attended, non-protected window. Select
   a fresh safe candidate first; then bind identity and all three fixed-session
   launchers and run Stage 0 plus the two Stage 1 modes consecutively.
5. Let tiering run serially; diagnose durable status, not Scheduler zero.
6. Keep Stage B and training held until their own preconditions pass.

## Host and workflow state

- Attempt `stage1-readiness-0823-a2` retains the immutable suite and PASS merge
  receipts for source tip `a6327ccf52499ed8d9ab0c34580fcd013ca7f094`
  and production merge `0af64ecf36287a8e88aa1f85cbfa2ff540adb03b`.
  Its authority is explicitly `NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY`.
- The earlier fixed bootstrap pair is spent evidence. Its initial merge task
  refused before production mutation; the reviewed retry produced the pushed
  report that binds the actual first landing.
- `WeatherClobTiering` and `WeatherClobRawTapeTiering` are recurring, enabled,
  and bound to the canonical 05:00/06:00 topology without late catch-up.
- `WeatherEveningEvidenceRefresh`, `WeatherTrainingWindow`, the mirror, and
  legacy merge-queue drivers remain disabled where required.
- Disabled tasks, Scheduler result zero, and mutable latest reports are not
  outcome evidence. Require immutable receipts, exact hashes, ancestry, and
  current worker identity.

## Update this file when

Rewrite after cumulative Stage-1 integration, August 17 recovery, a new Stage-A
soak, Stage-B proof or enablement, fresh candidate selection, action-time
eligibility, or a live lifecycle result. Remove superseded state.
