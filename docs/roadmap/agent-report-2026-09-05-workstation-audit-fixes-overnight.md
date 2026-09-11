# Audit repair handback and September 6 overnight preparation

**IMPLEMENTATION REPAIRED; PRODUCTION ADOPTION HELD ON DISK ADMISSION.**

Goal: deliver the unblocked correctness repairs and leave an exact, reviewable
integration path that protects overnight capture. The owner requested this work
on September 5. Live authorization remains absent.

## Source and verification

- Branch: `codex/audit-fixes-20260905`, [PR 28](https://github.com/michaelbooth1/weather/pull/28).
- Initial repair: `016e1c92c006c37eb321e9a549eb3e83b1f19fff`.
- Repaired implementation: `7e2cf5075c60c9b5637e29ac93ce82782d3235d5`.
- Explicit stack: PR 28 -> PR 27 -> PR 26 -> PR 6. The reviewed code and
  documentation lineage includes production baseline
  `6714b77d8bb57fa36b4d2dd33675cab971ef2432`.
- Production-side clean candidate worktree:
  `C:/Users/micha/Desktop/github/weather-audit-fixes-20260905`.
- This report's documentation commit may be a descendant of the implementation
  commit. Freeze the final published full SHA only after its exact-head CI and
  review pass. Do not freeze the failed initial commit or a movable branch alone.

The expanded workstation run passed 401 checks and 38 subtests; the remaining
registry check passed in a ten-check follow-up including agent-docs audit and
generated-backlog parity. Initial full Linux CI passed compilation and both
documentation checks, then reported seven maker-run failures, 4,615 passes,
259 skips and 946 passing subtests. That failed run is
[CI 609](https://github.com/michaelbooth1/weather/actions/runs/34001670231).
The corrected maker-run and policy bundle passed all 116 checks and 19 subtests.
Final PR CI owns final source qualification; this dated handback does not turn
a pending run green. The original dated audit witnesses remain unchanged.

Tests ran through the assigned non-capture workstation wrapper with source-root
and loaded-module assertions. JUnit copies are retained under this candidate
worktree's ignored `scratch/audit/`: `fixes-qualified.xml`,
`fixes-final-ratchets.xml`, and `fixes-run-support-final.xml`. The implementation
does not rewrite old evidence or establish a current market/account result.
Repair dispositions and remaining acceptance belong to
[item 330](items/item-330-maker-economics-refocus-master-plan.md).

## Start from the established contracts

Read [STATE_OF_PLAY](../operations/STATE_OF_PLAY.md),
[established findings](../operations/ESTABLISHED_FINDINGS.md), and
[retracted claims](../operations/RETRACTED_AND_FALSE_LEADS.md). No new alpha,
profitable maker opportunity, paid incentive or settlement-source equivalence
was proved. Preserve the WU proxy/floor, native units and captured-input replay.
The reserved-window contract currently declares no dated reservation; re-read
it before any dated evidence work.

The production-local canonical status receipt at September 5 20:27 reports
capture CLEAN (162 captures, zero gap), three capture families with zero
consecutive errors, 5.78 GiB available RAM and 28.9 GiB free disk. Public tape is
CONNECTED/integrity PASS but its complete price path is unusable. These are
point-in-time observations, not settlement or future admission proofs.

## Ordered overnight actions and stopping conditions

1. **Check reserve before creating an integration attempt.** Ordinary production
   suites require 50 GiB free on every involved volume, fresh memory/capture
   admission and the shared lease. At the retained observation this fails.
   No new integration or downstream task was registered. The prepared local
   JSON is a planning record, not an executable integration manifest.
2. **Preserve the existing storage jobs.** Read-only Scheduler XML and runtime
   queries verified `WeatherClobTiering` Ready/enabled for September 6 05:00 and
   `WeatherClobRawTapeTiering` Ready/enabled for 06:00. Their canonical actions
   retain S4U, wake, no late catch-up, 1,800/2,400-second child bounds and
   PT31M/PT41M task limits; raw tiering retains limit 150. Review their own
   terminal receipts and measured free space afterward. They run after the
   01:00–04:00 merge window and cannot justify an earlier suite reservation.
3. **Integrate only if fresh admission is actually proved.** Recheck source and
   live refs, preserve the two original generated-config edits, and obtain a
   fresh canonical roll verdict. Use a new immutable attempt with the adopted
   creator/registrar, its exact preflight/full-suite receipt and guarded merge.
   A possible September 6 plan is suite 00:30, merge 02:00, only if every gate
   passes before registration. If that slot is missed, select a new valid
   future window; do not use catch-up or rebind a spent namespace.
4. **After an actual merge**, prove all capture-worker recovery and canonical
   remote acknowledgement, then close the pending documentation transaction
   for integrations that actually landed. Seven pending integrations are
   recorded in the status receipt; this branch alone does not clear them.
5. **Keep tomorrow's attended path separate.** PR 6's existing named portable
   source exception and source/SDK preparation remain the route described by
   item 67. Do not substitute the audit branch as a newly authorized portable
   branch. Fresh host/clock/restart, source, account and stage gates plus attended
   owner authorization still govern every live action. No overnight live launch.

Follow [the integration-attempt runbook](../operations/INTEGRATION_ATTEMPT_RUNBOOK.md)
for all mandatory creator and registrar parameters and immutable recovery.
The proposed local parameter record is
`scratch/handoffs/audit-fixes-overnight-preparation-20260906.json` under production.
It must be updated to the finally reviewed tip and CI before use as planning
input; only the canonical creator emits a real manifest.

What would falsify proceeding: any failed CI/review, changed source/ref, missing
or stale capture evidence, unmet volume reserve, busy lease, invalid schedule,
unproved termination, or mismatched suite/merge receipt stops integration.
Storage success that still leaves less than 50 GiB does not fix admission.
The expired one-file hashing proposal and the provisional archive's successful
restore do not authorize production hashing or reclaim under a new disk floor.

## Mechanical roll verdict

The production canonical script classified the repaired implementation as
**ROLL-SENSITIVE** against `6714b77d8`; 33 importable files were checked.

| Changed file | Live closures |
| --- | --- |
| `src/weather/model/model_presentation.py` | snapshot, observation-trigger |
| `src/weather/schema_registry_data.py` | snapshot, CLOB, observation-trigger, public execution tape |
| `src/weather/time.py` | snapshot, CLOB, observation-trigger, public execution tape |
| `src/weather/units.py` | snapshot, observation-trigger |

Every other importable file in the retained per-file verdict is roll-free,
including `market_making_run_support.py`. The dormant enrichment closure is
fully subsumed by live closures. **The registry change is not additive-only:**
the active paper policy advances, with prior versions retained for history.

Reproduce the verdict from production with:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch origin/codex/audit-fixes-20260905
```

Retained production-local receipts are
`scratch/handoffs/audit-fixes-overnight-status-20260905.json`,
`audit-fixes-overnight-tasks-20260905.json`, and
`audit-fixes-overnight-repaired-roll-20260905.json` in the same directory.
They are ignored runtime evidence and are not assumed to exist in a clean clone.

No production source merge, capture restart, Scheduler mutation, credential
read, account call, order, cancel or heartbeat was performed. Source branches,
original generated-config modifications, tapes, ledgers and spent attempts
were preserved. Ordinary status collection retains its canonical disk sample.
