# Workstation handoff 2026-09-80b — finish the resting-quote session

Host: the 32 GB workstation (non-capture). Issued by the production operations agent, 2026-09-21.
Successor to `2026-09-80a`. Its handback is accepted: both stops were correct, and both came from errors in the 80a
handoff, corrected here. Everything in the 80a handoff that this file does not change still applies
(`docs/roadmap/workstation-handoff-2026-09-80a-build-the-resting-quote-session.md`).

## 1. Goal

A pushed, fully tested branch on which one command can run a sealed, attended **Stage 2 place-and-hold session** against
fakes and public books, and which **cannot** reach the venue until two dated owner grants exist. No live authority.

## 2. Corrections to the 80a handoff

- **Cancellation bound (80a W3 falsifier withdrawn).** "Dead-man within one heartbeat interval" was wrong. The venue
  contract is cancel-on-disconnect after 10 s with a 5 s buffer; the Stage 1 lifecycle already accepts disappearance in
  10–15 s, and the 2026-09-06 run measured 10.359 s. New rule: **an explicit cancel of both legs, acknowledged and
  journaled, is the primary action on every end condition; the dead-man is the backstop and uses the existing 10–15 s
  acceptance window unchanged.** State the residual exposure in the owner draft: two post-only 20-share buys may rest up
  to 15 s after total loss of connectivity; reserved capital about 19.40 pUSD bounds the loss.
- **Evidence minutes.** Three 45-minute sessions cannot reach the frozen 180 visible two-sided minutes. Write a dated
  **RE-1A treatment addendum, marked PROPOSED — owner ratifies before the first order**, that changes only this: the
  180-minute floor and `P_many >= 2.0` are assessed on **cumulative visible two-sided minutes on one band within one UTC
  reward day**, summed over place-and-hold sessions (the prediction is already a per-minute sum, and earnings are per UTC
  day); session ceiling **120 minutes**; at most **four sessions per UTC day**; RE-1A capped at **three reward days**, all
  reported. RE-1M, the selection rule, the prediction formula and the verdict thresholds are untouched. Build the
  ceiling as a `stage2_hold_v1` profile constant.
- **The four 2026-09-06 relaxations — build to these defaults; the owner may still change them:**
  1. Wallet: **fresh dedicated wallet, isolated branch, cash <= 100.** Do not touch the allocation validator. Your W0 test
     stays as the proof that the old mixed wallet cannot run.
  2. Typed confirmation: **one typed confirmation per sealed session**, in the templates; not one per step (the owner
     rejected repeated prompts) and not zero.
  3. Credential-import receipt age: **stays without a maximum age**; host, principal and exact-field binding remain. Your
     trace shows the age rule forced re-creation of a correctly deleted source.
  4. Fee: **unchanged** — fresh venue fee finite and >= 0, equal to the candidate's, journaled before the submit boundary.
- **Parent moved.** `origin/codex/maker-reconcile-20260920` is now `0fc25f40b` (adds the audit-wording fix, so
  `test_paid_provider_weather_policy_terms_do_not_regress` passes on this lineage). Merge it first.

## 3. Ownership granted for this mission

In addition to the 80a list: `scripts/ops/international_live_templates/{stage0,stage1_cancel_all}.py.tmpl` and a new
stage-2 template; `src/weather/operations/international_live_wrapper_sealer.py`,
`src/weather/operations/international_live_session_runner.py`, `src/weather/execution_host.py`;
`scripts/ops/workload_admission.ps1` (the workload-name pattern only; another open branch edits its offline-module list,
so keep your change to separate lines); `src/weather/schema_registry_data.py` for exactly the two policy-identifier
entries you proposed; and the tests of each. Anything else: report the need.

## 4. Work

- **W2 — finish the envelope.** Replace the scattered runtime constants with the hash-bound profiles. The adapter's clamp
  at 10 becomes profile-driven: `stage1_v1` stays 10 / 10, `stage2_hold_v1` is 16 per order / 20 per band; event 25, daily
  loss 25, wallet 100 unchanged. Ratchet tests prove Stage 0 / 1 behaviour is byte-identical under `stage1_v1`.
- **W3 — the runner.** One runner owning **two independently bound single-token capabilities and one account heartbeat**:
  account-wide zero-open-orders check once before leg 1; exactly our leg 1 and nothing else before leg 2; at most two
  submits per session; stop-on-fill; end conditions as 80a §3; geoblock receipt refreshed in-loop at <= 45 s, fail-closed;
  the cancellation rule from §2. Fake-clock tests drive every end condition, including heartbeat loss and a geoblock flip
  mid-hold, a fill on one leg, and a failed leg-2 submit (leg 1 must be cancelled). If two capabilities cannot be composed
  without weakening a control, stop and price the two-token adapter instead.
- **W4 — stage, template, sealer, host schema, workload name** for `stage2_hold`, refusing unless both dated grants match
  the profile hash. **W5 — earnings and order-scoring readers**, recorded fixtures only, never at import.
  **W6 — one command and a three-band public-book rehearsal against fakes**, journals retained.
  **W7 — documents**: pilot runbook, portable-host runbook, owner authorization draft and abort card updated to §2.
- Full suite through `scripts/ops/workstation_heavy.ps1`; the branch is handed back only with zero failures, or with each
  failure reproduced at the exact parent.

## 5. Boundaries

`docs/operations/DELEGATION_CONTRACT.md` §2 binds this mission in full. In addition: no real order, signature,
cancellation, authenticated venue call, account or wallet read, credential file or store access; no grant file that would
authorize Stage 2; no Scheduler, capture or production change; International Polymarket only; nothing that masks location
or alters eligibility or geoblock logic; never loosen cancel-all, heartbeat, post-only, no-naked-sell, stop-on-fill,
confirmation or wallet-isolation checks in code **or in tests** beyond §2. Commit and push freely; never merge to `master`.

## 6. What would stop this mission

- The SDK cannot acknowledge an explicit cancel of two orders on two tokens inside the session's teardown budget ⇒ say
  so, with the measured fake-path timing and the SDK types that show it.
- Profile-driven caps cannot be introduced without changing Stage 0 / 1 bytes ⇒ stop; report the smallest diff.
- Any end condition leaves an order open in a fake-clock test ⇒ NO-GO, reported as such.

## 7. Branch and report

- Branch: continue `codex/stage2-hold-build-20260921` (merge `origin/codex/stage2-hold-handoff-b-20260921` and the new
  parent first).
- Report: `docs/roadmap/agent-report-2026-09-80b-workstation-finish-the-resting-quote-session.md`, per contract §5 —
  verdict first in bold; package dispositions; test counts; per-file roll verdict (it will be re-run on the production
  host; this branch is roll-sensitive); what was NOT done; reproduction commands.
