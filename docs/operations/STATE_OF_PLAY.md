# State of play

**Last rewritten: 2026-08-15 15:10 America/Toronto.** Read this first, then
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
| Paper maker | The current active-day run is countable but still emits zero quote permissions because the model-promotion path blocks. Countability alone does not test quoting, fills, or economics. |
| Public execution tape | Supervised producer is adopted, current, connected, and integrity-valid. Retained gaps make the accumulated full price path unusable; keep collecting future clean intervals. Public rows never prove our fills or P&L. |
| Stage 0/1 software | The refreshed International bootstrap and one-submit lifecycle stack passed its exact suite, merged, and was adopted. This is software consistency, not order authority or live evidence. |
| Paper market-harvest lane | Prepared on a held branch. It bypasses model promotion only for paper midpoint quotes while retaining market, freshness, economics, and risk gates. Refresh onto master, prove, integrate, and run one active-market tick. |
| Official client upgrade | Prepared but stacked behind the paper lane and behind current master. Refresh the unified client and exact pUSD rebate-asset contract onto the paper parent; rerun its real-wheel contract and immutable full suite before integration. |
| Stage 2 | Prepared only as a stacked successor. It must wait for the paper/client parent, merge that production result, and pass a fresh exact-tip suite. |
| First live-money test | After this PC is physically moved to a genuinely eligible location: rerun public selection and economics, import credentials by reference, pass doctor and Stage 0, perform the two tiny supervised Stage 1 cancellation probes, build verification, then run one bounded Stage 2 quote session. |
| Model evidence | Promotion remains blocked. That is not the live-pilot critical path and must not be weakened to manufacture quote permission. |

## Closed decisions — do not relitigate without new evidence

- International Polymarket only. Never use Polymarket US.
- The first live test is a plumbing and evidence probe, not a profitability
  claim. Exactly one market, finite non-raisable 100 pUSD-equivalent wallet
  cap, post-only, no naked sells, and all existing lower risk ceilings remain.
- No order mutation from the current blocked location. Relocating this same PC
  changes nothing until a fresh official geoblock response and real-location /
  no-circumvention confirmations pass.
- Public market data supplies counterfactual paths and markouts. Authoritative
  user events, open orders, exact positions, balances, fees, rebates, and
  settlement supply our realized lifecycle and economics.
- No alpha is allocated. Release promotion and speculative model work remain
  off the live-pilot critical path. Free-tier weather sources only.
- An economics baseline is never accepted automatically. The official payout
  asset and current International rules must be explicit and content-bound.

## Immediate integration order

1. Land the roll-free status/documentation repair that removes the stale clock
   event false alarm and classifies the completed overnight audit by its durable
   receipt rather than by a deliberately Disabled spent task.
2. Refresh and prove the paper-only market-harvest lane. Resolve its roadmap
   number collision; do not let it emit live permission or relax promotion for
   the ordinary model lane.
3. Refresh the official client plus payout-asset contract on that exact parent.
   Verify production imports resolve inside the worktree and the checked-in SDK
   contract cannot silently skip in the immutable suite.
4. Run the paper lane on one active market. Require nonzero quote permission,
   two-sided post-only intent, zero live permission, current exchange-valid
   size/tick, and counterfactual execution-tape fields.
5. Refresh and prove Stage 2 only after its parent is in production. Review the
   host-owned fixed-scope wrapper before relocation; do not add a generic CLI
   mutation path.

All roll-sensitive branches use `scripts\ops\roll_verdict.ps1` and merge only
through the guarded 01:00-04:00 path. A branch push does not roll production.
Push only through `WeatherOneShotPush`.

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

Rewrite after any paper/client/Stage 2 integration, runtime adoption, active
paper quote proof, credential/eligible-host milestone, or live lifecycle result.
Remove superseded state instead of layering another dated handoff.
