# State of play

**Last rewritten: 2026-08-14 21:38 (same-PC execution is the approved deployment
shape; the exact Stage 0/1 and execution-tape chain is armed for tonight).**
Read this first, then `ESTABLISHED_FINDINGS.md` and
`RETRACTED_AND_FALSE_LEADS.md` for evidence.

> **REWRITTEN, never appended. Capped at ~90 lines.** This page answers what is
> happening now. Findings and numbers belong in `ESTABLISHED_FINDINGS`; false
> claims in `RETRACTED_AND_FALSE_LEADS`; invariants in `AGENT_CONTEXT`;
> cross-host mechanics in `DELEGATION_CONTRACT`. Do not cite this page as
> quantitative evidence. The production operations master is its sole
> integration owner.

**Objectives:** protect capture continuity; make the **International
Polymarket** market maker profitable after costs from spread plus documented
maker rebates; get the weather model close enough to the market to control
adverse selection and inventory. **We do not currently beat the market.**

## Closed decisions — do not relitigate without new evidence

- **International Polymarket only. Never use Polymarket US.** The model is a
  quote-centre and risk-control input, not assumed alpha. Profit must survive
  spread, adverse selection, inventory, fees, and rebates actually received.
- **This production PC is the intended live execution machine after physical
  relocation.** Its historical Ontario/blocked response remains binding at that
  location. A fresh official response matching the real location, explicit
  authorization, exact reviewed code, credentials by reference, fixed-scope
  wrapper, and every readiness/risk gate remain mandatory. The same-PC decision
  removes a source-transfer step; it does not authorize an order.
- The first real-money lifecycle test remains exactly one market, post-only,
  no naked sells, and a finite non-raisable 100 USDC-equivalent cap. Existing
  lower risk ceilings remain non-raisable.
- **No alpha is allocated.** Decision 10 remains closed unused. The instrument,
  observation-recovery, reshaping, old input, and historical edge-reproduction
  paths are closed or unpowered. Do not rebuild them from dated correspondence.
- Release #1 remains off the rebate-pilot critical path. Free weather sources
  only; no paid provider.
- Public execution capture and own-account lifecycle evidence answer different
  questions. Public paths support counterfactual markouts. Authoritative user
  events, open orders, positions, fees, and rebate receipts establish realized
  lifecycle and economics.
- The off-host mirror is operator-paused. Do not restart it until the operator
  decides the project has shown enough value to justify the mirror.

## Critical path

| Work | Current state / next action |
| --- | --- |
| Capture continuity | Healthy and current-code-bound. Protect the graded window; the reset streak is rebuilding. |
| International Stage 0/1 | Refreshed cumulative branch is clean, pushed, exact-tip task-bound, and roll-sensitive. Its bounded full suite runs at 00:30; its suite-gated quiet merge runs at 01:00. Either must refuse on identity, resource, receipt, merge, or recovery disagreement. |
| Public execution tape | Continuous public-only supervision is integrated but intentionally Disabled after a Windows venv parent/child identity mismatch. Its exact repair is stacked behind Stage 0/1, with suite at 01:30, guarded merge at 02:00, and fail-closed adoption at 02:15. This never proves our fills, rebates, or P&L. |
| Unified International client | The official unified-client upgrade and bodyless heartbeat contract are prepared on a separate roll-sensitive branch. Do not integrate it ahead of tonight's chain; combine it with the resulting master and reprove the exact combined tip. |
| Bounded maker Stage 2 | Pre-stacked on the unified-client line with one-submit, BUY-only, post-only, no-naked-sell, and bounded-risk behavior. It is not integration- or live-ready until its parents land, the combined tip is reproved, and the fixed-scope relocated-host wrapper is reviewed. |
| First live-money test | Preparation is authorized; exchange mutation is not an unattended next step. After relocation, fresh eligibility, wallet/bootstrap, user-event, position, heartbeat, cancel, paper-counterfactual, and explicit session gates must all pass. |
| LAN dashboard | Deferred to tomorrow. This host has measured RAM headroom; the existing launcher is low priority and LAN-bind capable. Add a private-network-only firewall rule, then measure real per-view memory before making it recurring. |

## Overnight host state

- The six exact one-shots from 00:30 through 04:20 are armed. Task Scheduler
  actions own their full tips, branches, receipts, and order; copied hashes in
  prose do not.
- `WeatherExecutionTapeSupervisor` stays **Disabled** until the fail-closed
  adoption proves the exact merged source, managed child, status, writer lock,
  and all three core capture workers.
- `WeatherEveningEvidenceRefresh` stays **Disabled**. The wrapper-owned child
  teardown defect remains disqualifying beside capture.
- `WeatherTrainingWindow` is intentionally held Disabled tonight. Its 04:15
  dead-man restore remains armed; a 04:20 one-shot re-enables the daily window.
- Windows has a pending reboot. Active hours are 12:00-06:00 to protect both
  grading and tonight's integration. Do not reboot before the chain completes;
  later maintenance must prove S4U capture recovery and restore the interactive
  session needed by `WeatherOneShotPush`.
- Production `master` equals `origin/master`. The only tracked dirt is the two
  expected generated location-config files; guarded merge owns their safe
  pre-merge commit. `WeatherOneShotPush` has the canonical master action.
- AC sleep and hibernation are disabled. No dashboard or heavyweight process is
  running. Disk and memory have adequate current headroom, but every heavy
  wrapper still needs its own admission and the shared OS-held lease.

## Do not chase these as new incidents

- The two old International suite/bundle `0x1` results belong to superseded
  failed tips. The bundle correctly produced no artifact.
- The execution-tape supervisor's Disabled state is intentional until adoption.
- A blocked promotion chain is expected before release and live evidence; do
  not weaken gates to turn it green.
- The status clock-age note uses the last Time-Service event and can lag the
  live `w32tm` synchronization time. Verify the live source before alarming.
- The status disk headline is a short-window trend, not an established burn
  rate. Preserve raw evidence and use longer-window measurements.

## Update this file when

Rewrite this page immediately after tonight's tasks produce real outcomes,
after any operator decision or accepted handback changes the critical path, and
after every merge/runtime adoption. Remove superseded state rather than adding
another layer. Feature branches do not independently publish this page as
current; the production operations master resolves it on the integration line.
