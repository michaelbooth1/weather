# State of play

**Last rewritten: 2026-08-22 14:32 America/Toronto.** Read this first, then
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
| Capture | The three streak-critical workers are healthy and the current graded day is on track. The supervised public execution tape is connected and integrity-valid, but complete price-path evidence is not currently usable. Preserve the graded and near-close windows. |
| Production | `master`, checked-out `HEAD`, and `origin/master` are synchronized at `cfdad9e5225f4dad86eaeddae7631893cd6c5350`. Only the two expected generated location-config files are modified. |
| Integration recovery | The bootstrap machinery landed as merge `d8e95c04be7c0b2daa351103b19efc1e942bc469`; the repaired lean workflow then passed its immutable preflight, exact 18/18-chunk suite, guarded merge, capture recovery, and remote acknowledgement as `cfdad9e5225f4dad86eaeddae7631893cd6c5350`. The canonical immutable-attempt registrar is now production-adopted. |
| Morning chain | The first post-adoption 09:30 Stage-A run published a terminal `COMPLETED` manifest at 11:30, inside its SLA. The formerly unbounded fleet tail completed quickly with every scheduled omission explicit. This is terminal-tail proof, not a clean soak: stale locks were repaired and the barrier correctly blocked on exchange-economics and maker-paper evidence. |
| Settlement | August 17 remains an explicit 12-market settlement hole and will not be retried by the ordinary chain. Recover it only through the bounded stop-after-finalize path, then prove normal lock release and real settlement evidence. |
| Tiering | The canonical 05:00 projection and 06:00 raw-tape tasks are enabled and both produced durable `OK` status on their first post-adoption runs. Scheduler zero alone is not the proof; retain the task-status artifacts and free-space trail. |
| Held work | Stage B remains disabled pending its separate monolithic resource proof. The training window remains opt-in and disabled; its independent 04:15 restore task is enabled and healthy. Do not enable either merely to test a blocker. |
| Documentation | Commit `e0d54db06699fc1c6e104dbdc3ccd4800cb16dd7` reconciles the two exact integration commits, their receipts, and the first morning readback. It is preserved as an exact ancestor of the pending Stage-1 cumulative branch, not landed production documentation. `weather.operations.documentation_transaction status` and its matching content-addressed receipt remain the authority for the ignored closeout transaction. |
| Host safety | The temporary active-hours package protected the reboot-pending morning and restored the normal graded-window policy at 11:56/11:58 without initiating a reboot. A reboot is still pending and is not authorized during protected capture. |
| Live money | The operator has authorized a bounded first live test, but no exchange mutation has run. Interrupt cleanup commit `da32c0895bb5b40c842b35232ff266c7968d4439` is combined with the documentation closeout only on `codex/stage1-readiness-cumulative-20260822`; that cumulative tip is pending exact-suite proof and guarded integration, not landed. Stage 0, fresh candidate, fixed-scope wrapper, runtime, economics, and account evidence remain separate gates. |

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

1. Inside protected capture, do not mutate production Git, Scheduler, reboot,
   or heavy work. Preparing or pushing a topic is not runtime adoption.
2. Publish `codex/stage1-readiness-cumulative-20260822`, then run its immutable
   exact-tip suite overnight. Parent or focused results cannot prove this tip.
3. After PASS, use only the guarded integration path; require capture recovery,
   `HEAD == master == origin/master`, and immutable receipts.
4. Only after that exact production adoption, bind Stage 0 and the fixed-scope
   wrapper to the production identity and a fresh candidate.
5. Recover August 17 separately through bounded stop-after-finalize; require
   12/12 real settlements, normal lock release, and current capture.
6. Let tiering run serially; diagnose durable status, not Scheduler zero.
7. Keep Stage B and training held until their own preconditions pass.

## Host and workflow state

- `codex/stage1-readiness-cumulative-20260822` preserves exact commits
  `e0d54db06699fc1c6e104dbdc3ccd4800cb16dd7` and
  `da32c0895bb5b40c842b35232ff266c7968d4439`; it is pending and has no
  production authority. `workflow-minimal-0822-a1` remains retained PASS evidence.
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
