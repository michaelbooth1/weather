# State of play

**Last rewritten: 2026-08-23 20:28 America/Toronto.** Read this first, then
`ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before model,
measurement, or research work.

> **REWRITTEN, never appended. Capped at about 90 lines.** Quantitative evidence
> belongs in `ESTABLISHED_FINDINGS`; false claims in `RETRACTED_AND_FALSE_LEADS`;
> durable invariants and delegation mechanics in their canonical files.

**Objectives:** protect irreplaceable capture and settlement; determine whether
International maker spread plus paid rebates exceeds adverse selection,
inventory/settlement loss, fees, and operational costs; improve the weather
forecast as a quote-centre and risk-control input. **We do not beat the market.**

## Current truth

| Area | State / next action |
| --- | --- |
| Capture | The second reboot recovery is now real: snapshot, CLOB, and observation are RUNNING on current process identities, the hardened recovery checker passes creation-token/command/lock proof for all three, and public execution capture is connected. Pre-reset network failures plus both reboots left 16.6–32.5 minute snapshot gaps and roughly 352–411 seconds of execution-tape darkness, so today's complete price path is unusable. |
| Production | The roll-free Codex host-load guard and PID-reuse-resistant boot proof are production-adopted. `HEAD == master == origin/master == 4feef39a44f920affcb05387a8882fb5f735cfa0`; the working tree is clean after the owner-approved live-readiness merge and one-shot publication. |
| Integration recovery | The live-readiness closure is production-adopted at `4feef39a44f920affcb05387a8882fb5f735cfa0`. Its guarded retry proved three-worker recovery, execution-tape recovery onto source fingerprint `ec5e6f8531bae817`, and remote acknowledgement. Earlier bootstrap/recovery, morning-workflow, and fixed-scope Stage-0/1 integrations remain adopted. |
| Morning chain | The 2026-08-23 Stage-A run terminalized at 11:38 for target 2026-08-22. Settlement restore/finalize and every scheduled tail step ran; the chain correctly remained `critical` at the settled-day barrier with seven payload blocks, including exchange-economics/maker-paper/trading evidence and model-performance gates. This is a truthful terminal run, not readiness. |
| Settlement | August 17 remains an explicit 12-market settlement hole and will not be retried by the ordinary chain. Recover it only through the bounded stop-after-finalize path, then prove normal lock release and real settlement evidence. |
| Tiering | The canonical 05:00 projection and 06:00 raw-tape tasks are enabled and both produced durable `OK` status on their first post-adoption runs. Scheduler zero alone is not the proof; retain the task-status artifacts and free-space trail. |
| Held work | Stage B remains disabled pending its separate monolithic resource proof. The training window remains opt-in and disabled; its independent 04:15 restore task is enabled and healthy. Do not enable either merely to test a blocker. |
| Documentation | The three-integration documentation transaction is published at `33fa374898507adc7231b6ff30af6d148f848556`; its content-addressed completion receipt is present and valid. |
| Host safety | Two reboots occurred. The 12:54 maintenance reboot was planned and clean; the 14:53 reset was unclean after yielded recursive Codex scans, parallel protected-window verification, and a contemporaneous DNS/network failure. This was not a recorded OOM. The S4U guard now runs every minute and terminates out-of-window/concurrent Codex heavy trees; the user-layer PreToolUse hook is installed, trusted, and confirmed active across a fresh Codex session. |
| Live money | The fixed-scope sealer, session runner, process-local pinned SDK overlay, provenance hardening, and interrupt cleanup are production software. All three public sealer inventories pass against current production. Geographic eligibility remains an action-time check and must not be inferred from repository timezone; VPN/proxy circumvention is forbidden. The current external source now passes all nine offline key/topology checks, but the create-only importer found pre-existing fixed Credential Manager entries and correctly wrote or overwrote zero. A compare-only, no-mutation exact-verification repair is being prepared; until it lands and an attended run proves all four entries match, credential readiness remains open. No exchange contact, mutation, or order has run. Fresh International economics/paper candidate, explicit baseline acceptance, public identity, authenticated doctor, Stage 0 bootstrap, sealed current wrappers, current account evidence, and supervised literal confirmations remain separate gates. |

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
- No order from a blocked jurisdiction or location circumvention. An unblocked
  egress response cannot override the operator's or host's physical location.

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
4. Require an eligible physical location, fresh official geoblock result, and
   attended no-circumvention attestation; otherwise stop at paper/read-only.
5. Land and run the compare-only credential reconciliation. Then bind identity
   and all three current fixed-session launchers, run the keyless doctor, and
   run Stage 0 plus the two Stage 1 modes consecutively under their separate
   literal confirmations.
6. Let tiering run serially; diagnose durable status, not Scheduler zero. Keep
   Stage B and training held until their own preconditions pass.

## Host and workflow state

- Attempt `stage1-readiness-0823-a2` retains the immutable suite and PASS merge
  receipts for source tip `a6327ccf52499ed8d9ab0c34580fcd013ca7f094`
  and production merge `0af64ecf36287a8e88aa1f85cbfa2ff540adb03b`.
  Its authority is explicitly `NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY`.
- The earlier fixed bootstrap pair is spent evidence. Its initial merge task
  refused before production mutation; the reviewed retry produced the pushed
  report that binds the actual first landing.
- **Recorded immediate-integration exception (2026-08-23):** the repository
  owner explicitly ordered `codex/live-readiness-closure-20260823` merged now
  so the day can be used for live-test preparation. Scope waives the ordinary
  01:00-04:00 merge timing and pre-merge Python/pytest verification for this
  exact attempt; focused and 25-file suites are recorded `NOT_RUN_OWNER_WAIVER`.
  At 19:15 the ordinary `-Force` path stopped before mutation because the
  protected-window and workload-lease gates are deliberately harder. The owner
  then explicitly approved one dated bypass, bound in code to this branch
  lineage and synchronized baseline. The S4U process guard remains enabled;
  an attended operator invocation runs outside the Codex-owned process tree.
  The first guarded attempt remained unpublished and rolled back cleanly after
  the execution-tape worker stayed on stale code: its one-minute supervisor ran,
  but six explicitly failed/no-mutation starts were incorrectly counted as
  recoveries and imposed a 3,600-second backoff. The reviewed repair excludes
  only refused starts that launched no child while preserving failed-launch,
  failed-restart, legacy-history, and ordinary restart-budget protection. A
  retry restarted the execution-tape worker onto the merged source, committed
  `4feef39a44f920affcb05387a8882fb5f735cfa0`, and received remote-master
  acknowledgement. That exact merge exception is spent and grants no standing
  bypass to later branches.
- `WeatherClobTiering` and `WeatherClobRawTapeTiering` are recurring, enabled,
  and bound to the canonical 05:00/06:00 topology without late catch-up.
- `WeatherEveningEvidenceRefresh`, `WeatherTrainingWindow`, the mirror, and
  legacy merge-queue drivers remain disabled where required.
- Disabled tasks, Scheduler result zero, and mutable latest reports are not
  outcome evidence. Require immutable receipts, exact hashes, ancestry, and
  current worker identity.

## Update this file when

Rewrite after Stage-1 integration, August 17 recovery, a new Stage-A soak,
Stage-B proof, fresh eligibility/candidate evidence, or a live lifecycle result.
