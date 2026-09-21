# Stage 2 place-and-hold: owner decision draft

**NOT IN FORCE. No authorization is added by this document.** This is the
decision sheet for mission 09-80a. Read it before a successor implementation or
owner review; the [pilot runbook](INTERNATIONAL_MM_LIVE_PILOT.md) owns execution.

## Decisions blocking the requested session

1. **W0 wallet falsifier is met for the recorded September 6 flow.** Its
   existing-wallet cash was 275.48 pUSD at the first failure and 489.60767 at
   the final success. The real shared validator rejects both under the
   restored isolated 100 pUSD whole-wallet contract. A fresh dedicated wallet
   funded 50–100 can pass that contract; relabelling the old allocation cannot.
   W0 explicitly says to stop and report this, then continue independent work.
2. **W3's one-heartbeat cancellation requirement is unsupported.** Cadence is
   five seconds, while the existing lifecycle requires observed dead-man
   cancellation in 10–15 seconds. The heartbeat sender cannot configure a
   shorter venue timeout. Choose whether to retain the stop or commission a
   corrected bound with immediate cancel-all on detected failure. No timeout,
   geography, or heartbeat control has been weakened.
3. **The unchanged RE-1 verdict and session budget conflict with the scope
   cut.** Every 45-minute session is below the 180 visible-minute evidence
   minimum. Even three full sessions total only 135 minutes. Aggregating them
   would still fail; silently raising the three-session cap or counting a
   hypothetical 360-minute prediction as earnings evidence is invalid. Define
   a new measurement unit/budget before implementing evidence verdicts.

The second and third decisions are specification changes, not live approvals.
The source handoff was read at `a1ee3ba986bedde452e6953236d4b0553cc6dde0`,
`docs/roadmap/workstation-handoff-2026-09-80a-build-the-resting-quote-session.md`.
The frozen RE-1 source is on `origin/codex/reward-epoch-design-20260920`.

## Four-relaxation disposition

| Control | Why the September 6 flow changed it | Disposition in this mission |
| --- | --- | --- |
| Typed stage and location/no-circumvention literals | A pasted command was consumed as a literal; the owner then rejected repeated prompts and authorized reviewed-command invocation | Trace confirms hardcoded attestations in both templates. Restoration is pending W0 disposition; no template changed. A successor must collect the exact literals before credentials and use the existing geography validator. |
| Isolated wallet | Whole-wallet cash exceeded 100, so the owner used a 100 allocation inside an existing wallet | Real-validator tests reproduce the W0 stop. Keep the accounting helper, do not pretend the allocation is isolation. A fresh dedicated-wallet Stage 0/1 is required for the proposed Stage 2 lane. |
| Credential comparison expiry | The preceding redesign made backup comparison a setup/recovery operation rather than a repeatedly expiring prerequisite | Sealer currently checks a real past timestamp, host, principal and exact comparison, without maximum age. A successor must bind comparison to the sealed session; restoration is pending W0 disposition. No credential or receipt was read. |
| Zero fee eligibility | Current chosen-market fee zero would fail the former strictly-positive gate | Existing lifecycle compares the fresh token-bound market rule with the candidate and journals it. Zero is evidence, never a missing-value default. No fee gate changed. |

## Proposed authorization text and config disposition

**Do not copy this into current authority yet.** After the blockers above are
resolved, host qualification and guarded integration pass, and fresh attended
Stage 0/1 succeeds, an owner grant would need to name: `stage2_hold_v1`, its exact
profile hash, the adopted source tip, condition and selection-table hashes,
the assigned host/principal, a dedicated wallet by non-secret identity reference,
an exact UTC session start/end, two post-only BUY submissions, and every capital
ceiling (16/order, 20/band, 25/event, 25/daily loss, 100/wallet).

**Executable config diff: withheld.** The assignment schema currently rejects
extra fields and authorizes three workload names only. Publishing a grant-shaped
diff before the corrected session/control schema exists would imply a runnable
authorization that the implementation cannot consume. No assignment was edited.

## Abort card for the proposed lane

- Before submission: missing literal, dedicated-wallet proof, current geography,
  tunnel-down attestation, fresh book/reward terms, source binding, or owner grant
  means no submit.
- At first fill, rejected/ambiguous submit, midpoint distance outside 1–3 cents
  or reward spread, minimum above 20, rate below 40, one-sided book, failed
  geography refresh, heartbeat loss, operator stop or deadline: stop submissions,
  request account-wide cancel-all, reconcile authoritative zero open orders.
- Unknown cleanup is a failed attempt, never success. Preserve its journal;
  reconcile inventory explicitly. A fill is held to settlement, with no taker
  exit or re-entry. No second attempt inherits its authority.
- Freeze prediction and journal hash before any earnings read. A short or
  incomplete session cannot be upgraded to a paid-epoch verdict.

## Update when

Rewrite this draft when the owner settles these specification decisions or the
implementation supports an exact reviewable grant. It is never authority itself.
