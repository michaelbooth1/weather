# 347. Weather Expansion F3 [OPEN]

Goal: make the simulated F3-SIM-1 trial discoverable, reproducible and auditable through governed, pinned inputs.
This item routes the durable definitions; current campaign status and decisions belong in
[STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md), maintained by the master.

Source: F3 WP-05 phase-A handoff and the [prereg source checklist](../../research/f3-sim-trial-2026-11/PREREG.md#18-frozen-element-checklist).

Why this matters: an auditable trial needs one route from its gate definitions to the protocol, frozen inputs and receipts.

## Contracts and evidence owners

- [Protocol](../../operations/F3_SIM_TRIAL.md): estimand, one alpha arm, diagnostics, transfer, inference and looks.
- [Rollout gates](../../operations/F3_ROLLOUT.md): P0 capture, P1 calibration, P2 freeze, P3 future live prerequisites.
- [Engine runbook](../../operations/f3-maker-expansion.md): modules, admitted inputs, routing and reproducibility.
- [Prereg draft and frozen-element checklist](../../research/f3-sim-trial-2026-11/PREREG.md): key-to-producer bindings.
- [Edge charter](../../operations/EDGE_TRIAL_CHARTER.md) and [reserved window](../../operations/reserved-confirmation-window.md): governing trial/read authority.

## Gate definitions and acceptance

P0 requires verified capture coverage, discovery, pack integrity, trade completeness and no capture regression.
P1 requires admitted calibration, run-time claimant checks, validated envelope, accuracy pre-gate, kill-test
survival, determinism and an outcome-free power projection; declared failure dispositions are mandatory.
P2 requires the decision tokens, prereg landing, separate JSON/Markdown hashes, no trial-date leakage and a freeze receipt.
P3 requires both-world trial PASS and binding gate PASS, followed by separate money/release authority.
An accurately simulated positive forecast or diagnostic is not an edge claim.

Definition checklist template (boxes define acceptance predicates, not live gate states):

- [ ] P0: capture, discovery, trade completeness and pack verification meet the linked criteria.
- [ ] P1: calibration admission, envelope/gate/kill-test checks, determinism and power meet the linked criteria.
- [ ] P2: decision tokens, prereg binding, zero-leakage check and freeze receipt meet the linked criteria.
- [ ] P3: both-world PASS and binding accuracy PASS precede any separate live authorization.

Acceptance: every frozen element maps to a schema key and producer receipt; documented commands resolve;
the integrated run branch reproduces digests; guarded looks and receipts support the declared verdict.
The linked rollout owns exact criteria and deadlines; this item does not duplicate live gate states.
