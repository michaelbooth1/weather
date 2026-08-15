# State of play

**Last rewritten: 2026-08-15 15:23 America/Toronto.** Read this first, then
`ESTABLISHED_FINDINGS.md` and `RETRACTED_AND_FALSE_LEADS.md` before model,
measurement, or research work.

> **REWRITTEN, never appended. Capped at about 90 lines.** This page answers
> what is happening now. Quantitative evidence belongs in
> `ESTABLISHED_FINDINGS`; false claims in `RETRACTED_AND_FALSE_LEADS`; durable
> invariants in `AGENT_CONTEXT`; cross-host mechanics in
> `DELEGATION_CONTRACT`. Do not cite this page as quantitative evidence.

**Objectives:** protect capture continuity; prove a bounded, International-only
maker lifecycle; then measure whether spread plus paid maker rebates exceeds
adverse selection, inventory/settlement loss, and all costs. The weather model
is a quote-centre and risk-control input. **We do not beat the market.**

## Current truth

| Area | State / next action |
| --- | --- |
| Capture | Healthy and on track today. Protect the 12:00-18:00 graded window; do not run heavy work or merge roll-sensitive code there. |
| Production software | International Stage 0/1 and continuous public execution capture are adopted. They prove software consistency and public observation, not order authority, fills, or profit. |
| Cumulative live-test parent | `codex/live-test-parent-refresh-20260815` is refreshed on current master and contains the paper harvest lane, unified official client, and pUSD payout-asset contract. Focused tests and the isolated real-wheel SDK contract pass; immutable exact-tip full-suite proof and guarded integration remain open. |
| Paper proof boundary | Candidate-plan v0.2 now requires a still-current successful one-market `market_harvest` quote, hashes the complete retained paper tape, binds the exact condition/token, and remains explicitly non-authorizing. `run_stage1` revalidates it before credential resolution. |
| Active paper attempt | The first real one-market attempt failed closed on two independent inputs: production economics is v0.2 while the branch requires v0.3, and missing prebuilt CLOB features exposed a model-anchored fallback in the model-independent lane. The branch now projects current harvest features directly from public books. Collect a fresh external v0.3 snapshot and reprove after 18:00; do not accept a baseline automatically. |
| Public execution tape | Supervised producer is current, connected, and integrity-valid. Retained gaps make the accumulated full price path unusable; keep collecting future clean intervals. Public rows never prove our fills or P&L. |
| Stage 2 | Prepared only as a stacked successor. Refresh it on the integrated cumulative parent and require a new exact-tip suite; do not merge it into the parent early. |
| First live-money test | After this PC is physically moved to a genuinely eligible location: rerun public metadata/economics/paper selection, import credentials by reference, pass doctor and Stage 0, perform the two tiny supervised Stage 1 cancellation probes, build verification, then run one bounded Stage 2 quote session. |
| Model evidence | Promotion remains blocked. That is not the live-pilot critical path and must not be weakened to manufacture quote permission. |

## Closed decisions — do not relitigate without new evidence

- International Polymarket only. Never use Polymarket US.
- The first live test is a plumbing and evidence probe, not a profitability
  claim. Exactly one market, finite non-raisable 100 pUSD-equivalent wallet
  cap, post-only, no naked sells, and all existing lower risk ceilings remain.
- No order mutation from the current Ontario/blocked location. Relocating this
  same PC changes nothing until a fresh official geoblock response and real-
  location/no-circumvention confirmations pass.
- Public market data supplies counterfactual paths and markouts. Authoritative
  user events, open orders, exact positions, balances, fees, rebates, and
  settlement supply our realized lifecycle and economics.
- No alpha is allocated. Release promotion and speculative model work remain
  off the live-pilot critical path. Free-tier weather sources only.
- An economics baseline is never accepted automatically. The official payout
  asset and current International rules must be explicit and content-bound.
- Credential import and authentication wait for physical eligibility. Never
  expose secret values through a CLI, environment value, log, or artifact.

## Immediate execution order

1. After 18:00, collect a fresh external International economics v0.3 snapshot
   on the cumulative branch. Audit it; do not run `accept`.
2. Rerun one Toronto `paper-live-forward` tick with `market_harvest`. Require
   nonzero quote permission, two-sided intent, zero live permission, current
   exchange size/tick, retained ceilings, and counterfactual tape fields.
3. Finish the cumulative branch, push only through `WeatherOneShotPush`, obtain
   `roll_verdict.ps1`, and run an immutable exact-tip full suite with the real
   pinned SDK contract. Never weaken or ignore a failure.
4. Merge the roll-sensitive parent only through the guarded 01:00-04:00 path,
   prove capture recovery/adoption, then refresh Stage 2 on that production tip.
5. Before relocation, review a fixed-scope host-owned wrapper sealed to new
   output paths and the fresh candidate plan. It must not expose a generic
   mutation or secret-bearing CLI.

## Host and workflow state

- Production `master` equals `origin/master`. Generated location config and
  `OPERATING_REFERENCE.md` have user/runtime-owned changes; preserve them.
- `WeatherExecutionTapeSupervisor` is enabled as S4U/Limited. Do not restart it
  merely to erase historical gap counters.
- `WeatherEveningEvidenceRefresh` stays Disabled pending wrapper-owned
  child-tree teardown proof. The weather mirror remains operator-paused.
- A reboot remains pending. Do not reboot during grading; later maintenance
  must prove unattended S4U recovery and restore the interactive session used
  by `WeatherOneShotPush`.
- Disabled spent one-shots are normal scheduler hygiene. Read their action,
  result, and durable receipt before calling them incidents.

## Update this file when

Rewrite after cumulative-parent integration/adoption, successful active paper
proof, Stage 2 refresh, credential/eligible-host milestone, or live lifecycle
result. Remove superseded state instead of layering another dated handoff.
