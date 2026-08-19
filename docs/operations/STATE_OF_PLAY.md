# State of play

**Last rewritten: 2026-08-16 10:30 America/Toronto.** Read this first, then
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
| Cumulative live-test parent | `codex/live-test-parent-refresh-20260815` is refreshed on current master and contains the paper harvest lane, unified official client, pUSD payout-asset contract, ownership-ratchet remediation, and the bounded Windows sampler type-cache repair found during the host audit. A new immutable exact-tip suite plus guarded integration remain open. |
| Paper proof | The one-market `market_harvest` route passed preflight, emitted two-sided paper permission and lifecycle intent, retained all ceilings, and emitted no live permission. Candidate-plan v0.2 safely selected nothing because the only proved books were outside its fixed midpoint interval. This is a route proof, not a safe candidate or profit result. |
| Candidate boundary | Keep the existing midpoint, fee/rebate, book, paper-proof, expiry, and condition/token gates. Select again from a fresh paper tick when a market naturally qualifies; never weaken a gate to force a candidate. `run_stage1` revalidates the non-authorizing plan before credential resolution. |
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

1. Finish and verify the cumulative branch ownership-ratchet remediation.
   Preserve the audited paper proof as evidence for its original exact source
   tip; do not accept the economics baseline.
2. Push only through `WeatherOneShotPush`, obtain
   `roll_verdict.ps1`, and run an immutable exact-tip full suite with the real
   pinned SDK contract. Never weaken or ignore a failure.
3. Merge the roll-sensitive parent only through the guarded 01:00-04:00 path,
   prove capture recovery/adoption, then refresh Stage 2 on that production tip.
4. Obtain a new paper-bound candidate only when a current market passes the
   existing safe interval naturally. Before relocation, review a fixed-scope
   host-owned wrapper sealed to new output paths and that fresh plan. It must
   not expose a generic mutation or secret-bearing CLI.

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
