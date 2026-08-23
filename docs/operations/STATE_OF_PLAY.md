# State of play

**Last rewritten: 2026-08-23 15:59 America/Toronto.** Read this first, then
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
| Capture | The second reboot recovery is now real: snapshot, CLOB, and observation are RUNNING on current process identities, the hardened recovery checker passes creation-token/command/lock proof for all three, and public execution capture is connected. Pre-reset network failures plus both reboots left 16.6–32.5 minute snapshot gaps and roughly 352–411 seconds of execution-tape darkness, so today's complete price path is unusable. |
| Production | The roll-free Codex host-load guard and PID-reuse-resistant boot proof are production-adopted. The working tree still has only the two expected generated location-config modifications; verify `HEAD == master == origin/master` dynamically through the one-shot publication path before relying on remote state. |
| Integration recovery | Three integrations are production-adopted: bootstrap/recovery machinery at `d8e95c04be7c0b2daa351103b19efc1e942bc469`, the bounded morning workflow at `cfdad9e5225f4dad86eaeddae7631893cd6c5350`, and the fixed-scope Stage-0/1 stack at `0af64ecf36287a8e88aa1f85cbfa2ff540adb03b`. The last exact tip passed 19/19 chunks before guarded merge, three-worker recovery, execution-tape recovery, and remote acknowledgement. |
| Morning chain | The 2026-08-23 Stage-A run terminalized at 11:38 for target 2026-08-22. Settlement restore/finalize and every scheduled tail step ran; the chain correctly remained `critical` at the settled-day barrier with seven payload blocks, including exchange-economics/maker-paper/trading evidence and model-performance gates. This is a truthful terminal run, not readiness. |
| Settlement | August 17 remains an explicit 12-market settlement hole and will not be retried by the ordinary chain. Recover it only through the bounded stop-after-finalize path, then prove normal lock release and real settlement evidence. |
| Tiering | The canonical 05:00 projection and 06:00 raw-tape tasks are enabled and both produced durable `OK` status on their first post-adoption runs. Scheduler zero alone is not the proof; retain the task-status artifacts and free-space trail. |
| Held work | Stage B remains disabled pending its separate monolithic resource proof. The training window remains opt-in and disabled; its independent 04:15 restore task is enabled and healthy. Do not enable either merely to test a blocker. |
| Documentation | The three-integration documentation transaction is published at `33fa374898507adc7231b6ff30af6d148f848556`; its content-addressed completion receipt is present and valid. |
| Host safety | Two reboots occurred. The 12:54 maintenance reboot was planned and clean; the 14:53 reset was unclean after yielded recursive Codex scans, parallel protected-window verification, and a contemporaneous DNS/network failure. This was not a recorded OOM. The S4U guard now runs every minute and terminates out-of-window/concurrent Codex heavy trees; the user-layer PreToolUse hook is installed, trusted, and confirmed active across a fresh Codex session. |
| Live money | The fixed-scope sealer, session runner, process-local pinned SDK overlay, and interrupt cleanup are production software. All three public sealer inventories pass against current production, but Stage 0/1 execution remains `HOLD` until the explicit 00:30-09:00 guard, truthful authenticated-write confirmation, canonical session-manifest builder, and a dated non-circular staged-readiness policy/receipt land and receive exact-tip reproof. No credential value or exchange mutation was authorized by integration, and no order has run. Credential references are prepared, but the accepted economics baseline is still the ineligible legacy US platform; fresh International economics/paper candidate, explicit baseline acceptance, public identity, keyless doctor, Stage 0 bootstrap, sealed current wrappers, current account evidence, and supervised literal confirmations remain separate gates. |

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

1. Protect the post-reboot capture day. Do not run live or heavy preparation in
   the protected windows, and do not treat today's restart-spent price path as
   repairable evidence.
2. Recover August 17 separately through the already reviewed bounded
   stop-after-finalize path; require
   12/12 real settlements, normal lock release, and current capture.
3. On a later uninterrupted target date, prepare a live lifecycle only for an
   attended, non-protected window with no heavy-work overlap. Refresh public
   International economics and a one-market paper candidate; baseline acceptance
   remains an explicit informed operator action.
4. After the live-session hardening is integrated and re-inventoried, bind
   identity and all three current fixed-session launchers, run the keyless
   doctor, and then run Stage 0 plus the two Stage 1 modes consecutively under
   their separate literal confirmations.
5. Let tiering run serially; diagnose durable status, not Scheduler zero. Keep
   Stage B and training held until their own preconditions pass.

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
